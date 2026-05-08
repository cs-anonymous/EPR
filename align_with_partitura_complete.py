#!/usr/bin/env python3
"""
使用partitura进行note-level alignment，然后粗化到measure-level

Pipeline:
1. 使用partitura进行score MIDI和performance MIDI的note-level对齐
2. 从ABCX中提取每个小节的第一个音符
3. 在score MIDI中找到对应的音符
4. 通过alignment映射到performance MIDI
5. 输出measure-level对齐结果
"""

import argparse
import re
import sys
from pathlib import Path

# 检查依赖
try:
    import partitura as pt
except ImportError:
    print("错误: partitura未安装")
    print("请安装: pip install partitura")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("错误: numpy未安装")
    print("请安装: pip install numpy")
    sys.exit(1)


# ===== ABCX解析部分 =====

KEY_FLATS = {
    'F': {'B'}, 'Bb': {'B', 'E'}, 'Eb': {'B', 'E', 'A'},
    'Ab': {'B', 'E', 'A', 'D'}, 'Db': {'B', 'E', 'A', 'D', 'G'},
    'Gb': {'B', 'E', 'A', 'D', 'G', 'C'}, 'Cb': {'B', 'E', 'A', 'D', 'G', 'C', 'F'},
}

KEY_SHARPS = {
    'G': {'F'}, 'D': {'F', 'C'}, 'A': {'F', 'C', 'G'},
    'E': {'F', 'C', 'G', 'D'}, 'B': {'F', 'C', 'G', 'D', 'A'},
    'F#': {'F', 'C', 'G', 'D', 'A', 'E'}, 'C#': {'F', 'C', 'G', 'D', 'A', 'E', 'B'},
}

NOTE_BASE_PITCH = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def parse_key_signature(key_str):
    key_str = key_str.strip()
    if key_str.endswith('m') and len(key_str) > 1:
        minor_roots = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
        root = key_str[:-1]
        idx = minor_roots.index(root) if root in minor_roots else -1
        if idx >= 0:
            major_root = minor_roots[(idx + 3) % 7]
            return KEY_FLATS.get(major_root, set()), KEY_SHARPS.get(major_root, set())
        return set(), set()
    return KEY_FLATS.get(key_str, set()), KEY_SHARPS.get(key_str, set())


def apply_key_signature(note_name, key_flats, key_sharps):
    if not note_name or note_name[0] in ('_', '^', '='):
        return note_name
    if note_name in key_flats:
        return '_' + note_name
    if note_name in key_sharps:
        return '^' + note_name
    return note_name


def note_to_pitch(note_str):
    if not note_str:
        return None
    accidental = 0
    clean = note_str
    if note_str[0] == '^':
        accidental = 1
        clean = note_str[1:]
    elif note_str[0] == '_':
        accidental = -1
        clean = note_str[1:]
    elif note_str[0] == '=':
        clean = note_str[1:]
    note_name = clean[0].upper()
    if note_name not in NOTE_BASE_PITCH:
        return None
    octave = 4 if clean[0].isupper() else 5
    for char in clean[1:]:
        if char == ',':
            octave -= 1
        elif char == "'":
            octave += 1
    pitch = (octave + 1) * 12 + NOTE_BASE_PITCH[note_name] + accidental
    return pitch


def extract_first_note_of_measure(measure_content, key_flats, key_sharps):
    """提取小节的第一个音符的pitch"""
    content = re.sub(r'\{[^}]*\}', '', measure_content)
    content = re.sub(r'![^!]*!', '', content)
    content = re.sub(r'"[^"]*"', '', content)

    def expand_chord(match):
        return ' '.join(match.group(1).replace(',', ' '))
    content = re.sub(r'\[([^\]]*)\]', expand_chord, content)

    pattern = r'([_=^]?[A-Ga-g][,\']*)(\d+(?:/\d+)?|/\d+)?'

    for voice in content.split(';'):
        for match in re.finditer(pattern, voice):
            note_str = match.group(1)
            clean_note = note_str.lstrip('_^=').upper()
            if clean_note and clean_note[0] not in ['Z', 'X']:
                named = apply_key_signature(note_str, key_flats, key_sharps)
                pitch = note_to_pitch(named)
                if pitch is not None:
                    return pitch
    return None


def parse_abcx_measure_starts(abcx_path):
    """
    解析ABCX，提取每个小节的第一个音符

    Returns:
        [(measure_num, first_pitch), ...]
    """
    measure_starts = []
    measure_num = 0
    key_flats = set()
    key_sharps = set()

    with open(abcx_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            k_match = re.match(r'^K:(\S+)', line)
            if k_match:
                key_flats, key_sharps = parse_key_signature(k_match.group(1))
                continue

            if re.match(r'^[A-JL-Z%]:', line) or line.startswith('%%'):
                continue

            for part in line.split('|'):
                part = part.strip()
                if part:
                    measure_num += 1
                    first_pitch = extract_first_note_of_measure(part, key_flats, key_sharps)
                    if first_pitch is not None:
                        measure_starts.append((measure_num, first_pitch))

    return measure_starts


# ===== Partitura对齐部分 =====

def align_with_partitura(score_midi_path, perf_midi_path, verbose=False):
    """
    使用partitura进行note-level对齐

    Returns:
        score_notes: partitura note array for score
        perf_notes: partitura note array for performance
        alignment: list of (score_note_idx, perf_note_idx) pairs
    """
    if verbose:
        print(f"加载score MIDI: {score_midi_path}")

    # 加载MIDI文件为performance对象
    score_perf = pt.load_performance_midi(score_midi_path)
    perf_perf = pt.load_performance_midi(perf_midi_path)

    if verbose:
        print(f"  Score: {len(score_perf.notes)} 个音符")
        print(f"  Performance: {len(perf_perf.notes)} 个音符")

    if verbose:
        print("\n执行note-level对齐...")

    # 使用partitura的对齐功能
    # match函数返回一个对齐结果
    alignment = pt.match.match_note_alignments(
        score_perf.notes,
        perf_perf.notes
    )

    if verbose:
        print(f"  对齐完成: {len(alignment)} 个匹配")

    return score_perf.notes, perf_perf.notes, alignment


def coarsen_to_measure_level(measure_starts, score_notes, perf_notes, alignment, verbose=False):
    """
    将note-level对齐粗化到measure-level

    Args:
        measure_starts: [(measure_num, first_pitch), ...] 从ABCX提取
        score_notes: partitura note array for score
        perf_notes: partitura note array for performance
        alignment: list of (score_idx, perf_idx) pairs

    Returns:
        {measure_num: tick, ...}
    """
    if verbose:
        print("\n粗化到measure-level...")

    # 创建alignment映射字典: score_idx -> perf_idx
    align_map = {}
    for score_idx, perf_idx in alignment:
        if score_idx not in align_map:
            align_map[score_idx] = []
        align_map[score_idx].append(perf_idx)

    # 对于每个小节，找到其第一个音符在score中的位置
    measure_alignments = {}
    used_score_indices = set()

    for measure_num, target_pitch in measure_starts:
        # 在score notes中找到第一个匹配的音符（未被使用过）
        score_idx = None

        for i, note in enumerate(score_notes):
            if note['pitch'] == target_pitch and i not in used_score_indices:
                score_idx = i
                used_score_indices.add(i)
                break

        if score_idx is None:
            if verbose:
                print(f"  警告: 小节 {measure_num} (pitch={target_pitch}) 在score中未找到")
            continue

        # 通过alignment找到对应的performance note
        if score_idx in align_map:
            perf_indices = align_map[score_idx]
            if perf_indices:
                # 如果有多个匹配，取第一个
                perf_idx = perf_indices[0]
                perf_note = perf_notes[perf_idx]
                perf_time = perf_note['onset_sec']
                tick = int(perf_time * 100)
                measure_alignments[measure_num] = tick

                if verbose and measure_num <= 10:
                    print(f"  小节 {measure_num}: score_idx={score_idx}, perf_idx={perf_idx}, time={perf_time:.2f}s, tick={tick}")
        else:
            if verbose:
                print(f"  警告: 小节 {measure_num} 的score音符未在alignment中找到")

    if verbose:
        print(f"\n对齐完成: {len(measure_alignments)}/{len(measure_starts)} 个小节")

    return measure_alignments


def align_measures(abcx_path, score_midi_path, perf_midi_path, verbose=False):
    """
    完整的measure-level对齐pipeline

    Returns:
        {measure_num: tick, ...}
    """
    if verbose:
        print("步骤1: 解析ABCX，提取每个小节的第一个音符")

    measure_starts = parse_abcx_measure_starts(abcx_path)

    if verbose:
        print(f"  找到 {len(measure_starts)} 个小节")
        if measure_starts:
            print(f"  前5个: {measure_starts[:5]}")

    if verbose:
        print("\n步骤2: 使用partitura进行note-level对齐")

    score_notes, perf_notes, alignment = align_with_partitura(
        score_midi_path,
        perf_midi_path,
        verbose
    )

    if verbose:
        print("\n步骤3: 粗化到measure-level")

    alignments = coarsen_to_measure_level(
        measure_starts,
        score_notes,
        perf_notes,
        alignment,
        verbose
    )

    return alignments


def main():
    parser = argparse.ArgumentParser(
        description='使用partitura进行measure-level对齐'
    )
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('score_midi', help='Score MIDI文件路径')
    parser.add_argument('performance_midi', help='Performance MIDI文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    try:
        alignments = align_measures(
            args.abcx_file,
            args.score_midi,
            args.performance_midi,
            args.verbose
        )

        result = ' '.join(f"{m}:{tick}" for m, tick in sorted(alignments.items()))
        print(result)

        if args.output:
            with open(args.output, 'w') as f:
                f.write(result + '\n')
            if args.verbose:
                print(f"\n结果已保存到: {args.output}")

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
