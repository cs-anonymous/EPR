#!/usr/bin/env python3
"""
生成 Language Learning SFT 数据
数据来源：配对数据（PianoCoRe/aligned/）中的 Score (aligned ABCX) 和 Performance (TSV)

任务体系（严格遵循设计文档公式）：

Score Language：
  - Measure continuation:    σ_head + σ_{M_k} → σ_{M_{k+1}}
  - Measure mask:            σ_head + f(σ_{M_k}) → σ_{M_k}
  - Phrase continuation:     σ_head + σ_{H_k} → σ_{H_{k+1}}
  - Phrase mask:             σ_head + f(σ_{H_k}) → σ_{H_k}

Performance Language：
  - Measure continuation:    φ_{M_k} → φ_{M_{k+1}}
  - Measure mask:            g(φ_{M_k}) → φ_{M_k}
  - Phrase continuation:     φ_{H_k} → φ_{H_{k+1}}
  - Phrase mask:             g(φ_{H_k}) → φ_{H_k}

f-mask 变体：acc / treble / bass / label
g-mask 变体：timing / velocity / duration / pedal
"""

import json
import csv
import re
import argparse
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict
import random
from tqdm import tqdm

random.seed(42)


def _csv_bool(value) -> bool:
    return str(value).strip().lower() == 'true'


def _csv_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def path_piece_id(path_like, anchor_names=('aligned', 'orphan_abcx', 'orphan_tsv')):
    """Return a stable relative piece_id from an absolute or relative dataset path."""
    path = Path(str(path_like))
    parts = path.parts
    for anchor in anchor_names:
        if anchor in parts:
            idx = parts.index(anchor)
            return Path(*parts[idx + 1:]).with_suffix('').as_posix()
    return path.with_suffix('').as_posix()


def load_valid_ids_and_abcx_paths(metadata_path: str = 'PianoCoRe/metadata.csv',
                                   perf_tier: str = 'b',
                                   perf_filter: str = None):
    """Load valid performance_ids and abcx-score-to-valid mapping from metadata.csv.

    Args:
        perf_tier: 'a' for tier A only, 'b' for tier B+ (default).
        perf_filter: optional named filter. Currently supports:
            'core-s' =
                is_transcription=False OR
                (tier_a_star AND refined_recall >= 0.90
                 AND interpolation_ratio <= 0.10).
            'core-s-star' =
                is_transcription=False OR
                (tier_a_star AND refined_recall >= 0.95
                 AND interpolation_ratio <= 0.05).

    Returns:
        valid_perf_ids: filtered performance_ids
        valid_abcx_dirs: tier A+ score path tuples relative to `PianoCoRe/score`
    """
    valid_perf_ids = set()
    valid_abcx_dirs = set()
    if not Path(metadata_path).exists():
        print(f"  Warning: {metadata_path} not found, no filtering applied")
        return valid_perf_ids, valid_abcx_dirs

    matched_rows = 0
    with open(metadata_path, 'r') as f:
        for row in csv.DictReader(f):
            tier_a = _csv_bool(row['tier_a'])
            tier_b = _csv_bool(row['tier_b'])
            tier_a_star = _csv_bool(row.get('tier_a_star', 'False'))
            is_dup = _csv_bool(row['is_duplicate'])
            is_transcription = _csv_bool(row.get('is_transcription', 'False'))
            refined_recall = _csv_float(row.get('refined_recall'))
            refined_note_count = _csv_float(row.get('refined_performance_note_count'))
            interpolated_note_count = _csv_float(row.get('refined_performance_interpolated_note_count'))
            interpolation_ratio = (
                interpolated_note_count / refined_note_count
                if refined_note_count > 0 else float('inf')
            )

            if perf_filter == 'core-s':
                core_astar_ok = (
                    tier_a_star
                    and refined_recall >= 0.90
                    and interpolation_ratio <= 0.10
                )
                asap_ok = not is_transcription
                perf_ok = core_astar_ok or asap_ok
            elif perf_filter == 'core-s-star':
                core_astar_ok = (
                    tier_a_star
                    and refined_recall >= 0.95
                    and interpolation_ratio <= 0.05
                )
                asap_ok = not is_transcription
                perf_ok = core_astar_ok or asap_ok
            elif perf_tier == 'a':
                perf_ok = tier_a and not is_dup
            else:
                perf_ok = tier_b and not is_dup

            if perf_ok:
                matched_rows += 1
                perf_id = row.get('performance_id', '').strip()
                if perf_id:
                    valid_perf_ids.add(perf_id)

            if tier_a and not is_dup:
                # Track score paths, preserving movement subdirectories:
                # PianoCoRe/score/Composer/Piece[/Movement]/score.abcx
                # -> ("Composer", "Piece", ..., "Movement")
                abcx_p = row.get('score_abcx_path', '').strip()
                if abcx_p:
                    parts = abcx_p.split('/')
                    for i, p in enumerate(parts):
                        if p == 'score':
                            rel_parts = tuple(parts[i + 1:-1])
                            if rel_parts:
                                valid_abcx_dirs.add(rel_parts)
                            break
    tier_label = perf_filter if perf_filter else ('A' if perf_tier == 'a' else 'B+')
    print(f"  Loaded {len(valid_perf_ids):,} tier {tier_label} performance_ids from {matched_rows:,} metadata rows")
    print(f"  Loaded {len(valid_abcx_dirs):,} tier A+ paired score directories")
    return valid_perf_ids, valid_abcx_dirs


class AlignedABCXParser:
    """解析 aligned ABCX 文件"""

    @staticmethod
    def parse(abcx_path: str) -> Dict:
        """解析 aligned ABCX 文件"""
        with open(abcx_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        header_lines = []
        measures = {}
        phrases = {}
        phrase_display_ids = {}
        measure_display_ids = {}
        current_phrase = None
        phrase_count = 0
        measure_count = 0

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue
            if line.startswith(('X:', 'T:', 'C:', '%%', 'L:', 'Q:', 'M:', 'K:')):
                header_lines.append(line)
            elif (phrase_token_id := _parse_score_phrase_token(line)) is not None:
                phrase_count += 1
                current_phrase = f'H{phrase_count}'
                phrase_display_ids[current_phrase] = f'<H><V{phrase_token_id:03d}>'
                phrases[current_phrase] = []
            elif (measure_token_id := _parse_score_measure_token(line)) is not None and '\t' in line:
                parts = line.split('\t', 1)
                measure_count += 1
                measure_id = f'M{measure_count}'
                measure_display_ids[measure_id] = f'<M><V{measure_token_id:03d}>'
                measure_content = parts[1] if len(parts) > 1 else ''
                measures[measure_id] = measure_content
                if current_phrase:
                    phrases[current_phrase].append(measure_id)

        return {
            'header': '\n'.join(header_lines),
            'measures': measures,
            'phrases': phrases,
            'phrase_display_ids': phrase_display_ids,
            'measure_display_ids': measure_display_ids,
        }


def _parse_score_phrase_token(line: str) -> int | None:
    stripped = line.strip()
    match = re.fullmatch(r"<H><V(\d{3})>", stripped)
    if match:
        return int(match.group(1))
    if stripped.startswith('H') and stripped[1:].isdigit():
        return int(stripped[1:])
    return None


def _parse_score_measure_token(line: str) -> int | None:
    stripped = line.strip()
    token = stripped.split('\t', 1)[0]
    match = re.fullmatch(r"<M><V(\d{3})>", token)
    if match:
        return int(match.group(1))
    if token.startswith('M') and token[1:].isdigit():
        return int(token[1:])
    return None


class TSVParser:
    """解析 MIDI-TSV 文件"""

    @staticmethod
    def parse(tsv_path: str) -> Dict:
        """解析 TSV 文件"""
        with open(tsv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        header_lines = []
        measures = defaultdict(list)
        measure_durations = {}
        phrases = {}
        phrase_durations = {}
        current_phrase = None
        current_measure = None
        strict_structural = False
        phrase_count = 0
        measure_count = 0
        pending_ext = {}

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue
            if line.startswith('#'):
                header_lines.append(line)
                if line.strip() == '# structural_duration=u16_hi_lo':
                    strict_structural = True
            elif line.startswith('H'):
                parts = line.split('\t')
                if parts[0] == 'H' and len(parts) == 4:
                    phrase_count += 1
                    current_phrase = f'H{phrase_count}'
                    phrase_durations[current_phrase] = str(
                        TSVParser._decode_structural_duration(parts, strict_structural)
                    )
                    phrases[current_phrase] = []
                    current_measure = None
                    pending_ext.clear()
                    continue
                # H 行格式: H1:<duration> 或 H1\t<duration>
                if ':' in line:
                    parts = line.split(':', 1)
                    current_phrase = parts[0]
                    phrase_durations[current_phrase] = parts[1] if len(parts) > 1 else ''
                elif '\t' in line:
                    # H1\t<start>\t<end>
                    parts = line.split('\t')
                    current_phrase = parts[0]
                    if len(parts) >= 3:
                        try:
                            start_val = int(parts[1])
                            end_val = int(parts[2])
                            phrase_durations[current_phrase] = str(end_val - start_val)
                        except ValueError:
                            phrase_durations[current_phrase] = parts[1] if len(parts) > 1 else ''
                    elif len(parts) >= 2:
                        phrase_durations[current_phrase] = parts[1]
                    else:
                        current_phrase = line.strip()
                        phrase_durations[current_phrase] = ''
                else:
                    current_phrase = line.strip()
                    phrase_durations[current_phrase] = ''
                phrases[current_phrase] = []
            elif line.startswith('M'):
                parts = line.split('\t')
                if parts[0] == 'M' and len(parts) == 4:
                    measure_count += 1
                    current_measure = f'M{measure_count}'
                    measure_durations[current_measure] = str(
                        TSVParser._decode_structural_duration(parts, strict_structural)
                    )
                    if current_phrase and current_measure not in phrases[current_phrase]:
                        phrases[current_phrase].append(current_measure)
                    pending_ext.clear()
                    continue
                # M 行格式: M1\t<start>\t<end>  或  M1:<duration>
                if ':' in line:
                    first, rest = line.split(':', 1)
                    current_measure = first
                    # Compact v0.2 format:
                    #   M1:117 <event> <event> ...
                    # Legacy compact/partial:
                    #   M1:117
                    rest_parts = rest.strip().split()
                    if rest_parts:
                        measure_durations[current_measure] = rest_parts[0]
                        if len(rest_parts) > 1:
                            measures[current_measure].extend(rest_parts[1:])
                    else:
                        measure_durations[current_measure] = ''
                elif '\t' in line:
                    # M1\t<start>\t<end> → duration = end - start
                    parts = line.split('\t')
                    current_measure = parts[0]
                    if len(parts) >= 3:
                        try:
                            start_val = int(parts[1])
                            end_val = int(parts[2])
                            measure_durations[current_measure] = str(end_val - start_val)
                        except ValueError:
                            measure_durations[current_measure] = ''
                    elif len(parts) >= 2:
                        measure_durations[current_measure] = parts[1]
                    else:
                        current_measure = line.strip()
                        measure_durations[current_measure] = ''
                if current_phrase and current_measure not in phrases[current_phrase]:
                    phrases[current_phrase].append(current_measure)
            elif current_measure:
                parts = line.split('\t')
                if len(parts) == 4 and parts[0] in ('EXD', 'EXO'):
                    try:
                        pending_ext[parts[0]] = int(parts[2]) * 256 + int(parts[3])
                    except ValueError:
                        pending_ext.clear()
                    continue
                if len(parts) == 4:
                    event, value, duration, offset = parts
                    if duration == 'EXT':
                        duration = str(pending_ext.get('EXD', 255))
                    if offset == 'EXT':
                        offset = str(pending_ext.get('EXO', 255))
                    measures[current_measure].append('\t'.join([event, value, duration, offset]))
                    pending_ext.clear()
                    continue
                # Replace tabs with spaces in note event lines for LLM-friendly format
                # E:40\t0\t90 → E:40 0 90
                measures[current_measure].append(line.replace('\t', ' '))

        return {
            'header': '\n'.join(header_lines),
            'measures': dict(measures),
            'measure_durations': measure_durations,
            'phrases': phrases,
            'phrase_durations': phrase_durations
        }

    @staticmethod
    def _decode_structural_duration(parts: list[str], strict_structural: bool) -> int:
        if strict_structural:
            try:
                return int(parts[2]) * 256 + int(parts[3])
            except ValueError:
                return 0
        try:
            return int(parts[2])
        except ValueError:
            return 0


def compact_perf_event(line: str) -> str:
    """Serialize one semantic 4-column event as colon-separated text."""
    parts = line.replace('\t', ' ').split()
    if not parts:
        return ''
    if len(parts) >= 4:
        return ':'.join(parts[:4])
    if len(parts) == 1 and parts[0].count(':') >= 3:
        return parts[0]
    return ':'.join(parts)


def format_perf_measure(measure_id: str, duration: str, event_lines: List[str]) -> str:
    events = [compact_perf_event(line) for line in event_lines]
    events = [event for event in events if event]
    return ' '.join([f"{measure_id}:{duration}"] + events)


def format_perf_phrase(phrase_id: str, duration: str, measure_parts: List[str]) -> str:
    return '\n'.join([f"{phrase_id}:{duration}"] + [part for part in measure_parts if part])


def format_score_measure(measure_id: str, content: str, display_id: str | None = None) -> str:
    label = display_id
    if label is None:
        idx = int(measure_id[1:]) - 1
        label = f"<M><V{idx:03d}>"
    return f"{label}\t{content}"


def format_score_phrase(phrase_id: str, measure_lines: List[str], display_id: str | None = None) -> str:
    label = display_id
    if label is None:
        idx = int(phrase_id[1:]) - 1
        label = f"<H><V{idx:03d}>"
    return '\n'.join([label] + [line for line in measure_lines if line])


# ========== Score Mask Functions ==========

def mask_note_pitches(content: str) -> str:
    """
    Note-level masking: 将音符的pitch信息替换为X，保留结构

    处理规则：
    - 单音符: "E," → "X", "^C''" → "X", "a2" → "X2"
    - 和弦: "[E,E]" → "[XX]", "[^C''D]2" → "[XX]2"
    - 保留: 括号[], 节奏数字, 小节线|, 表情标记!...!, 空格, 分号
    """
    result = []
    i = 0
    while i < len(content):
        char = content[i]

        # 保留表情标记 !...!
        if char == '!':
            end = content.find('!', i + 1)
            if end != -1:
                result.append(content[i:end+1])
                i = end + 1
                continue

        # 保留引号标记 "..."
        if char == '"':
            end = content.find('"', i + 1)
            if end != -1:
                result.append(content[i:end+1])
                i = end + 1
                continue

        # 处理和弦 [...]
        if char == '[':
            result.append('[')
            i += 1
            # 在和弦内部，mask每个音符
            while i < len(content) and content[i] != ']':
                if content[i] in ' \t':
                    result.append(content[i])
                    i += 1
                elif content[i] in 'ABCDEFGabcdefg':
                    # 这是一个音符，mask掉pitch和octave markers
                    # 跳过accidental
                    if i > 0 and content[i-1] in '^_=':
                        pass  # accidental已经被跳过了
                    result.append('X')
                    i += 1
                    # 跳过octave markers (', 或 ,)
                    while i < len(content) and content[i] in '\',':
                        i += 1
                elif content[i] in '^_=':
                    # 跳过accidental，不输出
                    i += 1
                else:
                    # 其他字符（如空格）保留
                    result.append(content[i])
                    i += 1
            if i < len(content) and content[i] == ']':
                result.append(']')
                i += 1
            # 保留和弦后的节奏数字
            while i < len(content) and (content[i].isdigit() or content[i] == '/'):
                result.append(content[i])
                i += 1
            continue

        # 处理单音符 (不在和弦内)
        if char in 'ABCDEFGabcdefg':
            result.append('X')
            i += 1
            # 跳过octave markers
            while i < len(content) and content[i] in '\',':
                i += 1
            # 保留节奏数字
            while i < len(content) and (content[i].isdigit() or content[i] == '/'):
                result.append(content[i])
                i += 1
            continue

        # 跳过accidental (如果单独出现)
        if char in '^_=':
            i += 1
            continue

        # 保留其他字符（空格、小节线、分号等）
        result.append(char)
        i += 1

    return ''.join(result)


def mask_acc(content: str) -> str:
    """f_acc: 遮去所有升降号 (#, ^, _, = natural in ABCX context)

    Returns the content with accidentals removed. If no accidentals present,
    returns the original content unchanged (so the generator can skip it).
    """
    # Check if any accidentals exist
    if not re.search(r'[\^_=][A-Ga-g]', content):
        return content  # No accidentals to mask, return unchanged

    result = content
    result = re.sub(r'\^([A-Ga-g])', r'\1', result)
    result = re.sub(r'_([A-Ga-g])', r'\1', result)
    result = re.sub(r'=([A-Ga-g])', r'\1', result)
    return result


def parse_score_voices(header: str) -> tuple:
    """Parse %%score directive to extract treble and bass voice indices.

    Returns:
        (treble_voices, bass_voices) as sets of voice number strings.
        If no piano group (no { ... }) is found, returns (None, None).

    Examples:
        %%score { 1 | 2 }                           -> ({'1'}, {'2'})
        %%score { ( 1 3 ) | ( 2 4 ) }               -> ({'1', '3'}, {'2', '4'})
        %%score 1 { ( 2 4 ) | ( 3 5 ) }             -> ({'2', '4'}, {'3', '5'})
        %%score ( 1 2 ) ( 3 4 )                     -> (None, None)  # no braces
    """
    for hline in header.split('\n'):
        if '%%score' not in hline:
            continue
        rest = hline.split('%%score', 1)[1].strip()

        # Find the { ... } group containing the piano voices
        # Some patterns: { 1 | 2 }, { ( 1 3 ) | ( 2 4 ) }, (1 2) { (3 5) | (4 6) }
        m = re.search(r'\{([^{}]+?)\}', rest)
        if not m:
            return (None, None)

        inner = m.group(1).strip()
        sides = inner.split('|')
        if len(sides) != 2:
            return (None, None)

        treble_voices = set(re.findall(r'\d+', sides[0]))
        bass_voices = set(re.findall(r'\d+', sides[1]))
        return (treble_voices, bass_voices)

    return (None, None)


def mask_treble(content: str, header: str = '') -> str:
    """f_treble: 遮去高音谱声部（钢琴右手部分）。

    根据 %%score 指令确定哪些 voice 属于 treble clef。
    """
    voices = content.split(' ; ')
    treble_voices, bass_voices = parse_score_voices(header)

    if treble_voices is None:
        # Fallback: mask first segment if >= 2 voices
        if len(voices) >= 2:
            masked = mask_note_pitches(voices[0])
            return ' ; '.join([masked] + voices[1:])
        return content

    # Mask voices belonging to treble clef
    result = []
    for i, v in enumerate(voices):
        voice_num = str(i + 1)
        if voice_num in treble_voices:
            result.append(mask_note_pitches(v))
        else:
            result.append(v)

    masked = ' ; '.join(result)
    return masked if masked != content else content


def mask_bass(content: str, header: str = '') -> str:
    """f_bass: 遮去低音谱声部（钢琴左手部分）。

    根据 %%score 指令确定哪些 voice 属于 bass clef。
    """
    voices = content.split(' ; ')
    treble_voices, bass_voices = parse_score_voices(header)

    if bass_voices is None:
        # Fallback: mask second segment if >= 2 voices
        if len(voices) >= 2:
            masked = mask_note_pitches(voices[1])
            return ' ; '.join([voices[0]] + [masked] + voices[2:])
        return content

    # Mask voices belonging to bass clef
    result = []
    for i, v in enumerate(voices):
        voice_num = str(i + 1)
        if voice_num in bass_voices:
            result.append(mask_note_pitches(v))
        else:
            result.append(v)

    masked = ' ; '.join(result)
    return masked if masked != content else content


def mask_label(content: str) -> str:
    """f_label: 遮去表情、力度、速度与演奏法标记"""
    result = re.sub(r'![^!]*!', '', content)
    result = re.sub(r'"[^"]*"', '', result)
    return result


SCORE_MASKS = {
    'acc': mask_acc,
    'treble': mask_treble,
    'bass': mask_bass,
    'label': mask_label,
}


# ========== Performance Mask Functions ==========

def mask_timing(lines: List[str]) -> List[str]:
    """g_timing: 遮去 offset/timing 信息。"""
    result = []
    for line in lines:
        parts = line.replace('\t', ' ').split()
        if len(parts) >= 4:
            result.append(f"{parts[0]} {parts[1]} {parts[2]} X")
        elif len(parts) >= 3 and parts[0] not in ('P', 'P1', 'P2'):
            result.append(f"{parts[0]} X {parts[2]}")
        else:
            result.append(line)
    return result


def mask_velocity(lines: List[str]) -> List[str]:
    """g_velocity: 遮去 note velocity 信息。"""
    result = []
    for line in lines:
        parts = line.replace('\t', ' ').split()
        if len(parts) >= 4 and parts[0] not in ('P', 'P1', 'P2'):
            result.append(f"{parts[0]} X {parts[2]} {parts[3]}")
        elif len(parts) >= 3 and parts[0] not in ('P', 'P1', 'P2'):
            result.append(f"{parts[0]} {parts[1]} X")
        else:
            result.append(line)
    return result


def mask_duration(lines: List[str]) -> List[str]:
    """g_duration: 遮去 note duration 信息 + measure duration"""
    result = []
    for line in lines:
        parts = line.replace('\t', ' ').split()
        if len(parts) >= 4 and parts[0] not in ('P', 'P1', 'P2'):
            result.append(f"{parts[0]} {parts[1]} X {parts[3]}")
        elif len(parts) >= 3 and parts[0] not in ('P', 'P1', 'P2'):
            pitch_part = parts[0].split(':')[0] if ':' in parts[0] else parts[0]
            result.append(f"{pitch_part}:X {parts[1]} {parts[2]}")
        else:
            result.append(line)
    return result


def mask_pedal(lines: List[str]) -> List[str]:
    """g_pedal: 遮去 pedal events"""
    return [line for line in lines if not line.startswith(('P\t', 'P1\t', 'P2\t', 'P ', 'P1 ', 'P2 '))]


PERF_MASKS = {
    'timing': mask_timing,
    'velocity': mask_velocity,
    'duration': mask_duration,
    'pedal': mask_pedal,
}


class MeasureScoreLangGenerator:
    """生成 Measure-level Score Language Learning 样本
    σ_head + σ_{M_k} → σ_{M_{k+1}}  +  σ_head + f(σ_{M_k}) → σ_{M_k}
    """

    def __init__(self, abcx_files: List[Path], output_dir: str,
                 max_samples_per_piece: int = None,
                 valid_abcx_dirs: set = None,
                 allow_orphan: bool = True):
        self.abcx_files = abcx_files
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece  # None = no limit
        self.valid_abcx_dirs = valid_abcx_dirs or set()
        self.allow_orphan = allow_orphan
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _is_valid(self, abcx_path: Path) -> bool:
        """Check if abcx file belongs to a valid score directory from metadata,
        or is an orphan ABCX (no performance but usable for score tasks)."""
        # Orphan ABCX files are always valid for score language tasks
        if self.allow_orphan:
            parts = abcx_path.parts
            for p in parts:
                if p == 'orphan_abcx':
                    return True
        if not self.valid_abcx_dirs:
            return True  # No filter, accept all
        # Path: PianoCoRe/aligned/Composer/Piece[/Movement]/score_aligned.abcx
        # Match the full relative directory under aligned/.
        try:
            parts = abcx_path.parts
            for i, p in enumerate(parts):
                if p in ('aligned', 'orphan_abcx', 'orphan_tsv') and i + 2 < len(parts):
                    rel_parts = tuple(parts[i + 1:-1])
                    return rel_parts in self.valid_abcx_dirs
            return False
        except (IndexError, ValueError):
            return False

    def generate(self):
        """生成 Measure-level Score Language Learning 数据"""
        continuation_samples = []
        mask_samples = []

        for abcx_path in tqdm(self.abcx_files, desc="Generating Measure Score Lang"):
            if not self._is_valid(abcx_path):
                continue
            try:
                score_data = AlignedABCXParser.parse(str(abcx_path))
            except Exception:
                continue

            if not score_data['measures']:
                continue

            piece_id = path_piece_id(abcx_path, anchor_names=('aligned', 'orphan_abcx'))

            measure_ids = sorted(score_data['measures'].keys(),
                                key=lambda x: int(x[1:]))

            half_limit = self.max_samples_per_piece // 2 if self.max_samples_per_piece else None
            cont_count = 0
            mask_count = 0

            for i in range(len(measure_ids) - 1):
                # Continuation: σ_head + σ_{M_k} → σ_{M_{k+1}}
                if half_limit is None or cont_count < half_limit:
                    curr_m_id = measure_ids[i]
                    target_m_id = measure_ids[i + 1]

                    # 格式: MX <content>
                    input_text = format_score_measure(
                        curr_m_id, score_data['measures'][curr_m_id], score_data['measure_display_ids'].get(curr_m_id)
                    )
                    target_text = format_score_measure(
                        target_m_id, score_data['measures'][target_m_id], score_data['measure_display_ids'].get(target_m_id)
                    )

                    continuation_samples.append({
                        'task': 'measure_score_lang_continuation',
                        'header': score_data['header'],
                        'input': input_text,
                        'target': target_text,
                        'piece_id': piece_id
                    })
                    cont_count += 1

                # Mask reconstruction: σ_head + f(σ_{M_k}) → σ_{M_k}
                # For each measure, always generate treble + bass masks.
                # Additionally try acc and label masks (skip if no change).
                if half_limit is None or mask_count < half_limit:
                    curr_m_id = measure_ids[i]
                    curr_content = score_data['measures'][curr_m_id]

                    # Staff-level masks: always generate (every piece has treble+bass)
                    for m_name in ('treble', 'bass'):
                        m_fn = SCORE_MASKS[m_name]
                        masked = m_fn(curr_content, score_data['header'])
                        if masked != curr_content:
                            input_text = format_score_measure(
                                curr_m_id, masked, score_data['measure_display_ids'].get(curr_m_id)
                            )
                            target_text = format_score_measure(
                                curr_m_id, curr_content, score_data['measure_display_ids'].get(curr_m_id)
                            )
                            mask_samples.append({
                                'task': 'measure_score_lang_mask',
                                'mask_type': m_name,
                                'header': score_data['header'],
                                'input': input_text,
                                'target': target_text,
                                'piece_id': piece_id
                            })
                            mask_count += 1

                    # Optional masks: only if they actually change content
                    for m_name in ('acc', 'label'):
                        m_fn = SCORE_MASKS[m_name]
                        masked = m_fn(curr_content)
                        if masked != curr_content:
                            if half_limit is None or mask_count < half_limit:
                                input_text = format_score_measure(
                                    curr_m_id, masked, score_data['measure_display_ids'].get(curr_m_id)
                                )
                                target_text = format_score_measure(
                                    curr_m_id, curr_content, score_data['measure_display_ids'].get(curr_m_id)
                                )
                                mask_samples.append({
                                    'task': 'measure_score_lang_mask',
                                    'mask_type': m_name,
                                    'header': score_data['header'],
                                    'input': input_text,
                                    'target': target_text,
                                    'piece_id': piece_id
                                })
                                mask_count += 1

        self._save_samples(continuation_samples, 'measure_score_lang_continuation')
        self._save_samples(mask_samples, 'measure_score_lang_mask')
        return len(continuation_samples), len(mask_samples)

    def _save_samples(self, samples: List[Dict], prefix: str):
        """保存样本到 measure-based 文件夹"""
        output_file = self.output_dir / 'measure-based' / f'{prefix}.jsonl'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


class PhraseScoreLangGenerator:
    """生成 Phrase-level Score Language Learning 样本
    σ_head + σ_{H_k} → σ_{H_{k+1}}  +  σ_head + f(σ_{H_k}) → σ_{H_k}
    """

    def __init__(self, abcx_files: List[Path], output_dir: str,
                 max_samples_per_piece: int = None,
                 valid_abcx_dirs: set = None,
                 allow_orphan: bool = True):
        self.abcx_files = abcx_files
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece  # None = no limit
        self.valid_abcx_dirs = valid_abcx_dirs or set()
        self.allow_orphan = allow_orphan
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _is_valid(self, abcx_path: Path) -> bool:
        """Check if abcx file belongs to a valid score directory from metadata,
        or is an orphan ABCX (no performance but usable for score tasks)."""
        # Orphan ABCX files are always valid for score language tasks
        if self.allow_orphan:
            parts = abcx_path.parts
            for p in parts:
                if p == 'orphan_abcx':
                    return True
        if not self.valid_abcx_dirs:
            return True
        try:
            parts = abcx_path.parts
            for i, p in enumerate(parts):
                if p in ('aligned', 'orphan_abcx', 'orphan_tsv') and i + 2 < len(parts):
                    rel_parts = tuple(parts[i + 1:-1])
                    return rel_parts in self.valid_abcx_dirs
            return False
        except (IndexError, ValueError):
            return False

    def generate(self):
        """生成 Phrase-level Score Language Learning 数据"""
        continuation_samples = []
        mask_samples = []

        for abcx_path in tqdm(self.abcx_files, desc="Generating Phrase Score Lang"):
            if not self._is_valid(abcx_path):
                continue
            try:
                score_data = AlignedABCXParser.parse(str(abcx_path))
            except Exception:
                continue

            if not score_data['phrases']:
                continue

            piece_id = path_piece_id(abcx_path, anchor_names=('aligned', 'orphan_abcx'))

            phrase_ids = sorted(score_data['phrases'].keys(),
                               key=lambda x: int(x[1:]))

            half_limit = self.max_samples_per_piece // 2 if self.max_samples_per_piece else None
            cont_count = 0
            mask_count = 0

            for i in range(len(phrase_ids) - 1):
                # Continuation: σ_head + σ_{H_k} → σ_{H_{k+1}}
                if half_limit is None or cont_count < half_limit:
                    curr_p_id = phrase_ids[i]
                    target_p_id = phrase_ids[i + 1]

                    curr_content = []
                    for m_id in score_data['phrases'][curr_p_id]:
                        if m_id in score_data['measures']:
                            curr_content.append(
                                format_score_measure(
                                    m_id, score_data['measures'][m_id], score_data['measure_display_ids'].get(m_id)
                                )
                            )

                    target_content = []
                    for m_id in score_data['phrases'][target_p_id]:
                        if m_id in score_data['measures']:
                            target_content.append(
                                format_score_measure(
                                    m_id, score_data['measures'][m_id], score_data['measure_display_ids'].get(m_id)
                                )
                            )

                    if curr_content and target_content:
                        # 格式: HX\nMX ...
                        input_text = format_score_phrase(
                            curr_p_id, curr_content, score_data['phrase_display_ids'].get(curr_p_id)
                        )
                        target_text = format_score_phrase(
                            target_p_id, target_content, score_data['phrase_display_ids'].get(target_p_id)
                        )

                        continuation_samples.append({
                            'task': 'phrase_score_lang_continuation',
                            'header': score_data['header'],
                            'input': input_text,
                            'target': target_text,
                            'piece_id': piece_id
                        })
                        cont_count += 1

                # Mask reconstruction: σ_head + f(σ_{H_k}) → σ_{H_k}
                # Try all mask types for each phrase, keep those where masked != original.
                curr_p_id = phrase_ids[i]
                curr_content = []
                for m_id in score_data['phrases'][curr_p_id]:
                    if m_id in score_data['measures']:
                        curr_content.append(
                            format_score_measure(
                                m_id, score_data['measures'][m_id], score_data['measure_display_ids'].get(m_id)
                            )
                        )

                if curr_content:
                    full_content_body = '\n'.join(curr_content)
                    for m_name, m_fn in SCORE_MASKS.items():
                        if m_name in ('treble', 'bass'):
                            masked = m_fn(full_content_body, score_data['header'])
                        else:
                            masked = m_fn(full_content_body)
                        if masked != full_content_body:
                            if half_limit is None or mask_count < half_limit:
                                input_text = f"{curr_p_id}\n" + masked
                                target_text = f"{curr_p_id}\n" + full_content_body
                                mask_samples.append({
                                    'task': 'phrase_score_lang_mask',
                                    'mask_type': m_name,
                                    'header': score_data['header'],
                                    'input': input_text,
                                    'target': target_text,
                                    'piece_id': piece_id
                                })
                                mask_count += 1

        self._save_samples(continuation_samples, 'phrase_score_lang_continuation')
        self._save_samples(mask_samples, 'phrase_score_lang_mask')
        return len(continuation_samples), len(mask_samples)

    def _save_samples(self, samples: List[Dict], prefix: str):
        """保存样本到 phrase-based 文件夹"""
        output_file = self.output_dir / 'phrase-based' / f'{prefix}.jsonl'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


class MeasurePerfLangGenerator:
    """生成 Measure-level Performance Language Learning 样本
    φ_{M_k} → φ_{M_{k+1}}  +  g(φ_{M_k}) → φ_{M_k}
    """

    def __init__(self, tsv_files: List[Path], output_dir: str,
                 max_samples_per_piece: int = None,
                 valid_perf_ids: Set[str] = None,
                 file_suffix: str = ''):
        self.tsv_files = tsv_files
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece
        self.valid_perf_ids = valid_perf_ids or set()
        self.file_suffix = file_suffix
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _is_valid(self, tsv_path: Path) -> bool:
        """Check if TSV file corresponds to a valid performance_id from metadata."""
        if not self.valid_perf_ids:
            return True
        fname = tsv_path.stem
        for suffix in ['_refined.mid', '_mini.mid', '.mid']:
            if fname.endswith(suffix):
                fname = fname[:-len(suffix)]
                break
        return fname in self.valid_perf_ids

    def generate(self):
        """生成 Measure-level Performance Language Learning 数据"""
        continuation_samples = []
        mask_samples = []

        for tsv_path in tqdm(self.tsv_files, desc="Generating Measure Perf Lang"):
            if not self._is_valid(tsv_path):
                continue
            try:
                perf_data = TSVParser.parse(str(tsv_path))
            except Exception:
                continue

            if not perf_data['measures']:
                continue

            piece_id = path_piece_id(tsv_path, anchor_names=('aligned', 'orphan_tsv'))

            measure_ids = sorted(perf_data['measures'].keys(),
                                key=lambda x: int(x[1:]))

            half_limit = self.max_samples_per_piece // 2 if self.max_samples_per_piece else None
            cont_count = 0
            mask_count = 0

            for i in range(len(measure_ids) - 1):
                # Continuation: φ_{M_k} → φ_{M_{k+1}}
                if half_limit is None or cont_count < half_limit:
                    curr_m_id = measure_ids[i]
                    target_m_id = measure_ids[i + 1]

                    # 获取 duration
                    curr_duration = perf_data['measure_durations'].get(curr_m_id, '')
                    target_duration = perf_data['measure_durations'].get(target_m_id, '')

                    # Compact format: MX:<duration> <pitch>:<duration>:<timing>:<velocity> ...
                    input_text = format_perf_measure(
                        curr_m_id, curr_duration, perf_data['measures'][curr_m_id]
                    )
                    target_text = format_perf_measure(
                        target_m_id, target_duration, perf_data['measures'][target_m_id]
                    )

                    continuation_samples.append({
                        'task': 'measure_perf_lang_continuation',
                        'input': input_text,
                        'target': target_text,
                        'piece_id': piece_id
                    })
                    cont_count += 1

                # Mask reconstruction: g(φ_{M_k}) → φ_{M_k}
                if half_limit is None or mask_count < half_limit:
                    curr_m_id = measure_ids[i]
                    curr_duration = perf_data['measure_durations'].get(curr_m_id, '')
                    curr_lines = perf_data['measures'][curr_m_id]
                    mask_name = random.choice(list(PERF_MASKS.keys()))
                    masked_lines = PERF_MASKS[mask_name](curr_lines)

                    # For duration mask, also mask the measure duration
                    mask_curr_duration = 'X' if mask_name == 'duration' else curr_duration

                    # Compact format: MX:<duration> <pitch>:<duration>:<timing>:<velocity> ...
                    input_text = format_perf_measure(curr_m_id, mask_curr_duration, masked_lines)
                    target_text = format_perf_measure(curr_m_id, curr_duration, curr_lines)

                    if input_text != target_text:
                        mask_samples.append({
                            'task': 'measure_perf_lang_mask',
                            'mask_type': mask_name,
                            'input': input_text,
                            'target': target_text,
                            'piece_id': piece_id
                        })
                        mask_count += 1

        cont_suffix = self.file_suffix
        mask_suffix = self.file_suffix
        self._save_samples(continuation_samples, 'measure_perf_lang_continuation', cont_suffix)
        self._save_samples(mask_samples, 'measure_perf_lang_mask', mask_suffix)
        return len(continuation_samples), len(mask_samples)

    def _save_samples(self, samples: List[Dict], prefix: str, suffix: str = ''):
        """保存样本到 measure-based 文件夹"""
        fname = f'{prefix}{suffix}.jsonl' if suffix else f'{prefix}.jsonl'
        output_file = self.output_dir / 'measure-based' / fname
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


class PhrasePerfLangGenerator:
    """生成 Phrase-level Performance Language Learning 样本
    φ_{H_k} → φ_{H_{k+1}}  +  g(φ_{H_k}) → φ_{H_k}
    """

    def __init__(self, tsv_files: List[Path], output_dir: str,
                 max_samples_per_piece: int = 25,
                 valid_tsv_paths: Set[str] = None):
        self.tsv_files = tsv_files
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece
        self.valid_tsv_paths = valid_tsv_paths or set()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _is_valid(self, tsv_path: Path) -> bool:
        if not self.valid_tsv_paths:
            return True
        return tsv_path.name in self.valid_tsv_paths

    def generate(self):
        """生成 Phrase-level Performance Language Learning 数据"""
        continuation_samples = []
        mask_samples = []

        for tsv_path in tqdm(self.tsv_files, desc="Generating Phrase Perf Lang"):
            if not self._is_valid(tsv_path):
                continue
            try:
                perf_data = TSVParser.parse(str(tsv_path))
            except Exception:
                continue

            if not perf_data['phrases']:
                continue

            piece_id = path_piece_id(tsv_path, anchor_names=('aligned', 'orphan_tsv'))

            phrase_ids = sorted(perf_data['phrases'].keys(),
                               key=lambda x: int(x[1:]))

            half_limit = self.max_samples_per_piece // 2
            cont_count = 0
            mask_count = 0

            for i in range(len(phrase_ids) - 1):
                # Continuation: φ_{H_k} → φ_{H_{k+1}}
                if cont_count < half_limit:
                    curr_p_id = phrase_ids[i]
                    target_p_id = phrase_ids[i + 1]

                    # 获取 phrase duration
                    curr_p_duration = perf_data['phrase_durations'].get(curr_p_id, '')
                    target_p_duration = perf_data['phrase_durations'].get(target_p_id, '')

                    curr_content = []
                    for m_id in perf_data['phrases'][curr_p_id]:
                        if m_id in perf_data['measures'] and m_id in perf_data['measure_durations']:
                            duration = perf_data['measure_durations'][m_id]
                            curr_content.append(
                                format_perf_measure(m_id, duration, perf_data['measures'][m_id])
                            )

                    target_content = []
                    for m_id in perf_data['phrases'][target_p_id]:
                        if m_id in perf_data['measures'] and m_id in perf_data['measure_durations']:
                            duration = perf_data['measure_durations'][m_id]
                            target_content.append(
                                format_perf_measure(m_id, duration, perf_data['measures'][m_id])
                            )

                    if curr_content and target_content:
                        input_text = format_perf_phrase(curr_p_id, curr_p_duration, curr_content)
                        target_text = format_perf_phrase(target_p_id, target_p_duration, target_content)

                        continuation_samples.append({
                            'task': 'phrase_perf_lang_continuation',
                            'input': input_text,
                            'target': target_text,
                            'piece_id': piece_id
                        })
                        cont_count += 1

                # Mask reconstruction: g(φ_{H_k}) → φ_{H_k}
                if mask_count < half_limit:
                    curr_p_id = phrase_ids[i]
                    curr_p_duration = perf_data['phrase_durations'].get(curr_p_id, '')

                    # Collect all event lines for masking
                    all_lines = []
                    measure_info = []  # Store (m_id, duration, num_lines) for reconstruction
                    for m_id in perf_data['phrases'][curr_p_id]:
                        if m_id in perf_data['measures'] and m_id in perf_data['measure_durations']:
                            duration = perf_data['measure_durations'][m_id]
                            measure_lines = perf_data['measures'][m_id]
                            all_lines.extend(measure_lines)
                            measure_info.append((m_id, duration, len(measure_lines)))

                    if all_lines:
                        mask_name = random.choice(list(PERF_MASKS.keys()))
                        masked_lines = PERF_MASKS[mask_name](all_lines)

                        # Reconstruct full content with structure
                        full_content_parts = []
                        line_idx = 0
                        for m_id, duration, num_lines in measure_info:
                            measure_lines = all_lines[line_idx:line_idx + num_lines]
                            full_content_parts.append(format_perf_measure(m_id, duration, measure_lines))
                            line_idx += num_lines
                        full_content_body = '\n'.join(full_content_parts)

                        # Reconstruct masked content with structure
                        masked_content_parts = []
                        line_idx = 0
                        for m_id, duration, num_lines in measure_info:
                            measure_masked_lines = masked_lines[line_idx:line_idx + num_lines]
                            masked_content_parts.append(format_perf_measure(m_id, duration, measure_masked_lines))
                            line_idx += num_lines
                        masked_content_body = '\n'.join(masked_content_parts)

                        input_text = format_perf_phrase(curr_p_id, curr_p_duration, [masked_content_body])
                        target_text = format_perf_phrase(curr_p_id, curr_p_duration, [full_content_body])

                        if input_text != target_text:
                            mask_samples.append({
                                'task': 'phrase_perf_lang_mask',
                                'mask_type': mask_name,
                                'input': input_text,
                                'target': target_text,
                                'piece_id': piece_id
                            })
                            mask_count += 1

        self._save_samples(continuation_samples, 'phrase_perf_lang_continuation')
        self._save_samples(mask_samples, 'phrase_perf_lang_mask')
        return len(continuation_samples), len(mask_samples)

    def _save_samples(self, samples: List[Dict], prefix: str):
        """保存样本到 phrase-based 文件夹"""
        output_file = self.output_dir / 'phrase-based' / f'{prefix}.jsonl'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


def main():
    parser = argparse.ArgumentParser(
        description='Generate Language Learning SFT data from paired data'
    )
    parser.add_argument('--aligned_dir', type=str, default='PianoCoRe/aligned',
                        help='Directory containing aligned ABCX and TSV files')
    parser.add_argument('--orphan_abcx_dir', type=str, default='PianoCoRe/orphan_abcx',
                        help='Directory containing orphan aligned ABCX files (no performance)')
    parser.add_argument('--orphan_tsv_dir', type=str, default='PianoCoRe/orphan_tsv',
                        help='Directory containing orphan TSV files (no score)')
    parser.add_argument('--output_dir', type=str, default='sft_data',
                        help='Output directory for generated training data')
    parser.add_argument('--task', type=str,
                        choices=['measure_score', 'phrase_score',
                                'measure_perf', 'phrase_perf', 'all'],
                        default='all',
                        help='Which task to generate (all = score measure+phrase + perf measure; phrase_perf excluded)')
    parser.add_argument('--no_filter', action='store_true',
                        help='Skip metadata-based filtering (for backward compatibility)')
    parser.add_argument('--max_score_per_piece', type=int, default=None,
                        help='Max samples per piece for Score tasks (None = unlimited)')
    parser.add_argument('--max_perf_per_piece', type=int, default=None,
                        help='Max samples per piece for Performance tasks (None = unlimited)')
    parser.add_argument('--max_tsv_files', type=int, default=None,
                        help='Max TSV files to process (for perf tasks, None = all)')
    parser.add_argument('--perf-tier', type=str, choices=['a', 'b'], default='b',
                        help='Tier filter for performance data. "a" = tier A only, "b" = tier B+ (default)')
    parser.add_argument('--perf-filter', type=str, choices=['core-s', 'core-s-star'], default=None,
                        help='Named performance filter. core-s/core-s-star = clean CoRe-A* plus all is_transcription=False')

    args = parser.parse_args()
    aligned_dir = Path(args.aligned_dir)
    orphan_abcx_dir = Path(args.orphan_abcx_dir)
    orphan_tsv_dir = Path(args.orphan_tsv_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Language Learning SFT Data Generation")
    print(f"Source (paired): {aligned_dir}")
    print(f"Source (orphan ABCX): {orphan_abcx_dir}")
    print(f"Source (orphan TSV): {orphan_tsv_dir}")
    print(f"Output: {output_dir}")
    print("=" * 60)

    # Collect ABCX files from both paired and orphan directories
    paired_abcx_files = sorted(list(aligned_dir.glob('**/*_aligned.abcx')))
    orphan_abcx_files = sorted(list(orphan_abcx_dir.glob('**/*_aligned.abcx'))) if orphan_abcx_dir.exists() else []
    all_abcx_files = paired_abcx_files + orphan_abcx_files
    print(f"\nFound {len(paired_abcx_files)} paired ABCX files")
    print(f"Found {len(orphan_abcx_files)} orphan ABCX files (score only)")
    print(f"Total: {len(all_abcx_files)} ABCX files")

    # Collect TSV files from both paired and orphan directories
    paired_tsv_files = sorted(list(aligned_dir.glob('**/*.tsv')))
    orphan_tsv_files = sorted(list(orphan_tsv_dir.glob('**/*.tsv'))) if orphan_tsv_dir.exists() else []
    all_tsv_files = paired_tsv_files + orphan_tsv_files
    print(f"Found {len(paired_tsv_files)} paired TSV files")
    print(f"Found {len(orphan_tsv_files)} orphan TSV files (performance only)")
    print(f"Total: {len(all_tsv_files)} TSV files")

    if args.max_tsv_files and len(all_tsv_files) > args.max_tsv_files:
        all_tsv_files_copy = all_tsv_files.copy()
        random.shuffle(all_tsv_files_copy)
        tsv_files = all_tsv_files_copy[:args.max_tsv_files]
        print(f"Sampling {len(tsv_files)} TSV files (max: {args.max_tsv_files})")
    else:
        tsv_files = all_tsv_files
        print(f"Using all {len(tsv_files)} TSV files")

    # Load metadata-based valid IDs (skip if --no_filter)
    valid_perf_ids: Set[str] = set()
    valid_abcx_dirs = set()
    if not args.no_filter:
        print("\nLoading valid IDs from metadata.csv...")
        valid_perf_ids, valid_abcx_dirs = load_valid_ids_and_abcx_paths(
            perf_tier=args.perf_tier,
            perf_filter=args.perf_filter,
        )

    if args.task in ['measure_score', 'all']:
        print("\n[1/4] Generating Measure-level Score Language Learning data...")
        generator = MeasureScoreLangGenerator(
            all_abcx_files, str(output_dir),
            max_samples_per_piece=args.max_score_per_piece,
            valid_abcx_dirs=valid_abcx_dirs,
            allow_orphan=True,
        )
        cont_count, mask_count = generator.generate()
        print(f"✓ Generated {cont_count} continuation + {mask_count} mask samples")

    if args.task in ['phrase_score', 'all']:
        print("\n[2/4] Generating Phrase-level Score Language Learning data...")
        generator = PhraseScoreLangGenerator(
            all_abcx_files, str(output_dir),
            max_samples_per_piece=args.max_score_per_piece,
            valid_abcx_dirs=valid_abcx_dirs,
            allow_orphan=True,
        )
        cont_count, mask_count = generator.generate()
        print(f"✓ Generated {cont_count} continuation + {mask_count} mask samples")

    if args.task in ['measure_perf', 'all']:
        suffix = ''
        if args.perf_filter:
            tier_label = args.perf_filter
        else:
            suffix = '_a' if args.perf_tier == 'a' else ''
            tier_label = 'A' if args.perf_tier == 'a' else 'B+'
        print(f"\n[3/4] Generating Measure-level Performance Language Learning data (tier {tier_label})...")
        generator = MeasurePerfLangGenerator(
            tsv_files, str(output_dir),
            max_samples_per_piece=args.max_perf_per_piece,
            valid_perf_ids=valid_perf_ids,
            file_suffix=suffix,
        )
        cont_count, mask_count = generator.generate()
        print(f"✓ Generated {cont_count} continuation + {mask_count} mask samples")

    # phrase_perf tasks are excluded as decided by the user
    # if args.task in ['phrase_perf', 'all']:


    print("\n" + "=" * 60)
    print("Language Learning data generation complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
