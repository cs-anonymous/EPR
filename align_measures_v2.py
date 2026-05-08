#!/usr/bin/env python3
"""
小节对齐算法 V2：使用绝对pitch和duration信息

核心改进：
1. 使用绝对pitch（MIDI note number），不是pitch class
2. 考虑音符时长（duration）
3. 不依赖GT reference
4. 使用序列匹配算法找到最佳对齐位置
"""

import argparse
import re
import mido
from pathlib import Path
from collections import defaultdict
import numpy as np


# 调号映射
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

# 基础音高映射（C4 = MIDI 60）
NOTE_BASE_PITCH = {
    'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11,
}


def parse_key_signature(key_str):
    """解析调号"""
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
    """应用调号"""
    if not note_name or note_name[0] in ('_', '^', '='):
        return note_name
    if note_name in key_flats:
        return '_' + note_name
    if note_name in key_sharps:
        return '^' + note_name
    return note_name


def note_to_pitch(note_str, base_octave=5):
    """
    将ABCX音符转换为绝对MIDI pitch

    ABCX规则：
    - 大写字母（C, D, E...）表示低八度（octave 4）
    - 小写字母（c, d, e...）表示高八度（octave 5）
    - 每个逗号','降低一个八度
    - 每个撇号'\''升高一个八度
    - ^表示升半音，_表示降半音，=表示还原

    例如：
    - C = MIDI 48 (C4)
    - c = MIDI 60 (C5)
    - C, = MIDI 36 (C3)
    - c' = MIDI 72 (C6)
    """
    if not note_str:
        return None

    # 处理升降号
    accidental = 0
    clean = note_str
    if note_str[0] == '^':
        accidental = 1
        clean = note_str[1:]
    elif note_str[0] == '_':
        accidental = -1
        clean = note_str[1:]
    elif note_str[0] == '=':
        accidental = 0
        clean = note_str[1:]

    # 提取音名和八度标记
    note_name = clean[0].upper()
    if note_name not in NOTE_BASE_PITCH:
        return None

    # 确定八度
    octave = 4 if clean[0].isupper() else 5  # 大写=octave 4, 小写=octave 5

    # 处理八度标记
    for char in clean[1:]:
        if char == ',':
            octave -= 1
        elif char == "'":
            octave += 1

    # 计算MIDI pitch
    pitch = (octave + 1) * 12 + NOTE_BASE_PITCH[note_name] + accidental
    return pitch


def parse_duration(duration_str):
    """
    解析ABCX时长标记

    返回相对时长（以四分音符为1.0）
    例如：
    - A = 1.0 (四分音符)
    - A2 = 2.0 (二分音符)
    - A/2 = 0.5 (八分音符)
    - A3/2 = 1.5
    """
    if not duration_str:
        return 1.0

    # 匹配数字和分数
    match = re.match(r'(\d+)?(?:/(\d+))?', duration_str)
    if not match:
        return 1.0

    numerator = int(match.group(1)) if match.group(1) else 1
    denominator = int(match.group(2)) if match.group(2) else 1

    if match.group(2) and not match.group(1):
        # 只有分母，如 /2
        return 1.0 / denominator

    return numerator / denominator


def extract_measure_notes(measure_content, key_flats=None, key_sharps=None):
    """
    从小节内容中提取音符序列

    返回: [(pitch, duration), ...]
    """
    if key_flats is None:
        key_flats = set()
    if key_sharps is None:
        key_sharps = set()

    notes = []

    # 清理内容
    content = re.sub(r'\{[^}]*\}', '', measure_content)  # 去除装饰音
    content = re.sub(r'![^!]*!', '', content)  # 去除装饰符号
    content = re.sub(r'"[^"]*"', '', content)  # 去除文本

    # 处理和弦 [ABC]
    def expand_chord(match):
        return ' '.join(match.group(1).replace(',', ' '))
    content = re.sub(r'\[([^\]]*)\]', expand_chord, content)

    # 匹配音符：[_=^]?[A-Ga-g][,']* 后面可能跟时长
    pattern = r'([_=^]?[A-Ga-g][,\']*)(\d+(?:/\d+)?|/\d+)?'

    for voice in content.split(';'):
        for match in re.finditer(pattern, voice):
            note_str = match.group(1)
            duration_str = match.group(2) or ''

            # 跳过休止符
            clean_note = note_str.lstrip('_^=').upper()
            if clean_note and clean_note[0] not in ['Z', 'X']:
                # 应用调号
                named = apply_key_signature(note_str, key_flats, key_sharps)
                pitch = note_to_pitch(named)
                if pitch is not None:
                    duration = parse_duration(duration_str)
                    notes.append((pitch, duration))

    return notes


def parse_abcx(abcx_path):
    """解析ABCX文件，返回小节列表"""
    measures = []
    measure_num = 0
    key_flats = set()
    key_sharps = set()

    with open(abcx_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # 解析调号
            k_match = re.match(r'^K:(\S+)', line)
            if k_match:
                key_flats, key_sharps = parse_key_signature(k_match.group(1))
                continue

            # 跳过其他元数据
            if re.match(r'^[A-JL-Z%]:', line) or line.startswith('%%'):
                continue

            # 按小节线分割
            for part in line.split('|'):
                part = part.strip()
                if part:
                    measure_num += 1
                    notes = extract_measure_notes(part, key_flats, key_sharps)
                    measures.append((measure_num, notes))

    return measures


def midi_to_notes(midi_path):
    """
    从MIDI文件提取音符序列

    返回: [(pitch, duration_seconds, start_tick, start_time_seconds), ...]
    """
    mid = mido.MidiFile(midi_path)
    notes = []

    # 收集所有note-on和note-off事件
    for track in mid.tracks:
        current_time = 0
        tempo = 500000  # 默认tempo
        active_notes = {}  # {(pitch, channel): (start_time_seconds, start_tick)}

        for msg in track:
            current_time += msg.time

            if msg.type == 'set_tempo':
                tempo = msg.tempo
            elif msg.type == 'note_on' and msg.velocity > 0:
                # 记录note-on
                key = (msg.note, msg.channel)
                time_seconds = mido.tick2second(current_time, mid.ticks_per_beat, tempo)
                active_notes[key] = (time_seconds, current_time)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                # note-off：计算duration
                key = (msg.note, msg.channel)
                if key in active_notes:
                    start_time, start_tick = active_notes[key]
                    end_time = mido.tick2second(current_time, mid.ticks_per_beat, tempo)
                    duration = end_time - start_time
                    notes.append((msg.note, duration, start_tick, start_time))
                    del active_notes[key]

    # 按开始时间排序
    notes.sort(key=lambda x: x[2])
    return notes


def compute_sequence_score(measure_notes, midi_notes, start_idx, tempo_scale=1.0):
    """
    计算小节音符序列与MIDI片段的匹配分数

    Args:
        measure_notes: [(pitch, duration), ...] 来自ABCX
        midi_notes: [(pitch, duration, start_tick, start_time_seconds), ...] 来自MIDI
        start_idx: MIDI中的起始索引
        tempo_scale: tempo缩放因子（performance可能比score快或慢）

    Returns:
        score: 匹配分数（越高越好）
    """
    if not measure_notes or start_idx >= len(midi_notes):
        return 0.0

    # 窗口大小：小节音符数的1.5倍（允许performance中有额外音符）
    window_size = max(len(measure_notes), int(len(measure_notes) * 1.5), 5)
    window_end = min(start_idx + window_size, len(midi_notes))

    score = 0.0
    matched_count = 0

    # 尝试匹配小节中的每个音符
    midi_idx = start_idx
    for i, (target_pitch, target_dur) in enumerate(measure_notes):
        best_match_score = 0.0
        best_match_idx = -1

        # 在窗口内搜索最佳匹配
        for j in range(midi_idx, window_end):
            midi_pitch, midi_dur, _, _ = midi_notes[j]

            # Pitch匹配（必须完全相同）
            if midi_pitch != target_pitch:
                continue

            # Duration相似度（允许tempo变化）
            # 将ABCX的相对时长转换为秒（假设四分音符=0.5秒作为基准）
            expected_dur = target_dur * 0.5 * tempo_scale
            dur_ratio = min(midi_dur, expected_dur) / max(midi_dur, expected_dur) if max(midi_dur, expected_dur) > 0 else 0

            # 位置奖励：越早出现越好（鼓励按顺序匹配）
            position_bonus = 1.0 / (1.0 + (j - midi_idx) * 0.1)

            match_score = dur_ratio * position_bonus

            if match_score > best_match_score:
                best_match_score = match_score
                best_match_idx = j

        if best_match_idx >= 0:
            score += best_match_score * 100  # pitch完全匹配 + duration相似
            matched_count += 1
            midi_idx = best_match_idx + 1  # 移动到下一个位置
        else:
            # 没找到匹配，轻微惩罚
            score -= 10

    # 计算召回率和精确率
    recall = matched_count / len(measure_notes) if measure_notes else 0
    precision = matched_count / window_size if window_size > 0 else 0

    # 第一个音符匹配奖励
    if measure_notes and start_idx < len(midi_notes):
        first_pitch = measure_notes[0][0]
        # 检查起始位置附近是否有第一个音符
        for j in range(start_idx, min(start_idx + 3, len(midi_notes))):
            if midi_notes[j][0] == first_pitch:
                score += 200  # 第一个音符匹配很重要
                break

    # 综合分数
    final_score = score + recall * 500 + precision * 100

    return final_score


def find_measure_alignments(measures, midi_notes, verbose=False):
    """
    找到每个小节在MIDI中的对齐位置

    Args:
        measures: [(measure_num, [(pitch, duration), ...]), ...]
        midi_notes: [(pitch, duration, start_tick), ...]
        verbose: 是否输出详细信息

    Returns:
        {measure_num: tick, ...}
    """
    if not measures or not midi_notes:
        return {}

    num_measures = len(measures)
    num_notes = len(midi_notes)

    if verbose:
        print(f"总小节数: {num_measures}, 总MIDI音符数: {num_notes}")

    # 步骤1：为每个小节生成候选位置
    all_candidates = []

    for measure_idx, (measure_num, measure_notes) in enumerate(measures):
        if not measure_notes:
            # 空小节：使用估计位置
            estimated_pos = int((measure_idx + 1) / num_measures * num_notes)
            all_candidates.append([(estimated_pos, 0.0)])
            continue

        # 粗略估计位置（基于小节进度）
        estimated_pos = int((measure_idx + 1) / num_measures * num_notes)

        # 搜索范围：估计位置 +/- 20%
        search_margin = max(50, int(num_notes * 0.2 / num_measures))
        search_start = max(0, estimated_pos - search_margin)
        search_end = min(num_notes, estimated_pos + search_margin)

        # 如果有前一个小节，确保搜索范围在其之后
        if all_candidates and measure_idx > 0:
            prev_candidates = all_candidates[-1]
            if prev_candidates:
                min_prev_pos = min(c[0] for c in prev_candidates)
                search_start = max(search_start, min_prev_pos + 1)

        # 采样候选位置（避免搜索过密）
        step = max(1, (search_end - search_start) // 30)
        candidates = []

        # 尝试多个tempo scale
        tempo_scales = [0.8, 1.0, 1.2]  # 允许performance比score快或慢20%

        for pos in range(search_start, search_end, step):
            best_score = 0.0
            for tempo_scale in tempo_scales:
                score = compute_sequence_score(measure_notes, midi_notes, pos, tempo_scale)
                best_score = max(best_score, score)
            candidates.append((pos, best_score))

        # 确保估计位置总是候选之一
        if search_start <= estimated_pos < search_end:
            if not any(c[0] == estimated_pos for c in candidates):
                best_score = 0.0
                for tempo_scale in tempo_scales:
                    score = compute_sequence_score(measure_notes, midi_notes, estimated_pos, tempo_scale)
                    best_score = max(best_score, score)
                candidates.append((estimated_pos, best_score))

        if not candidates:
            candidates.append((estimated_pos, 0.0))

        all_candidates.append(candidates)

    # 步骤2：动态规划找到全局最优路径
    NEG_INF = float('-inf')

    # 初始化第一个小节
    prev_dp = {}
    parent = [{} for _ in range(num_measures)]

    for cand_idx, (pos, score) in enumerate(all_candidates[0]):
        prev_dp[cand_idx] = score

    # 前向传播
    for measure_idx in range(1, num_measures):
        curr_dp = {}

        if not all_candidates[measure_idx] or not prev_dp:
            prev_dp = curr_dp
            continue

        for c2, (pos2, score2) in enumerate(all_candidates[measure_idx]):
            best_total = NEG_INF
            best_prev = -1

            for c1, total1 in prev_dp.items():
                pos1 = all_candidates[measure_idx - 1][c1][0]

                # 约束：位置必须递增
                if pos2 <= pos1:
                    continue

                # 间隔惩罚：相邻小节不应该离得太远或太近
                gap = pos2 - pos1
                expected_gap = num_notes / num_measures
                gap_penalty = -abs(gap - expected_gap) / expected_gap * 50

                total = total1 + score2 + gap_penalty

                if total > best_total:
                    best_total = total
                    best_prev = c1

            if best_total > NEG_INF:
                curr_dp[c2] = best_total
                parent[measure_idx][c2] = best_prev

        prev_dp = curr_dp

    if not prev_dp:
        return {}

    # 回溯找到最优路径
    best_end = max(prev_dp, key=lambda k: prev_dp[k])
    path = []
    ci = best_end

    for mi in range(num_measures - 1, -1, -1):
        if all_candidates[mi] and ci < len(all_candidates[mi]):
            path.append(all_candidates[mi][ci][0])
        else:
            path.append(None)
        ci = parent[mi].get(ci, -1)

    path.reverse()

    # 生成对齐结果
    alignments = {}
    for measure_idx, pos in enumerate(path):
        if pos is not None and pos < len(midi_notes):
            measure_num = measures[measure_idx][0]
            start_time_seconds = midi_notes[pos][3]  # start_time_seconds
            # 转换为 time_seconds * 100 格式（与ground truth一致）
            tick = int(start_time_seconds * 100)
            alignments[measure_num] = tick

    if verbose:
        print(f"\n对齐结果: {len(alignments)}/{num_measures} 个小节")
        for measure_idx, (measure_num, measure_notes) in enumerate(measures):
            if measure_num in alignments:
                print(f"  小节 {measure_num}: tick {alignments[measure_num]}, 音符数 {len(measure_notes)}")

    return alignments


def main():
    parser = argparse.ArgumentParser(description='小节对齐算法 V2（使用绝对pitch和duration）')
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    if args.verbose:
        print(f"解析ABCX文件: {args.abcx_file}")
    measures = parse_abcx(args.abcx_file)
    if args.verbose:
        print(f"找到 {len(measures)} 个小节")
        # 显示前几个小节的音符
        for i, (mnum, notes) in enumerate(measures[:3]):
            print(f"  小节 {mnum}: {len(notes)} 个音符")
            if notes:
                print(f"    前3个音符: {notes[:3]}")

    if args.verbose:
        print(f"\n解析MIDI文件: {args.midi_file}")
    midi_notes = midi_to_notes(args.midi_file)
    if args.verbose:
        print(f"找到 {len(midi_notes)} 个音符")
        if midi_notes:
            print(f"  前3个音符 (pitch, duration, tick, time): {[(n[0], round(n[1], 2), n[2], round(n[3], 2)) for n in midi_notes[:3]]}")

    if args.verbose:
        print(f"\n开始对齐...")

    alignments = find_measure_alignments(measures, midi_notes, args.verbose)

    # 输出结果
    result = ' '.join(f"{m}:{tick}" for m, tick in sorted(alignments.items()))
    print(result)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(result + '\n')
        if args.verbose:
            print(f"\n结果已保存到: {args.output}")


if __name__ == '__main__':
    main()
