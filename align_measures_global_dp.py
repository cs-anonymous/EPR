#!/usr/bin/env python3
"""
小节对齐算法 - 全局DP版本

借鉴music synchronization的思想：
1. 全局动态规划（类似DTW）
2. 基于pitch和duration的局部打分器
3. Measure-level对齐（比note-level更粗粒度）

核心思想：
- 不使用贪心搜索，而是全局DP找最优路径
- 为每个小节在整个MIDI中生成候选位置
- 使用DP确保全局最优，同时允许局部纠错
"""

import argparse
import re
import mido
from collections import Counter
import numpy as np


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
    """将ABCX音符转换为绝对MIDI pitch"""
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


def parse_duration(duration_str):
    """解析ABCX时长"""
    if not duration_str:
        return 1.0
    match = re.match(r'(\d+)?(?:/(\d+))?', duration_str)
    if not match:
        return 1.0
    numerator = int(match.group(1)) if match.group(1) else 1
    denominator = int(match.group(2)) if match.group(2) else 1
    if match.group(2) and not match.group(1):
        return 1.0 / denominator
    return numerator / denominator


def extract_measure_notes(measure_content, key_flats=None, key_sharps=None):
    """提取小节的音符序列 (pitch, duration)"""
    if key_flats is None:
        key_flats = set()
    if key_sharps is None:
        key_sharps = set()

    notes = []
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
            duration_str = match.group(2) or ''
            clean_note = note_str.lstrip('_^=').upper()
            if clean_note and clean_note[0] not in ['Z', 'X']:
                named = apply_key_signature(note_str, key_flats, key_sharps)
                pitch = note_to_pitch(named)
                if pitch is not None:
                    duration = parse_duration(duration_str)
                    notes.append((pitch, duration))

    return notes


def parse_abcx(abcx_path):
    """解析ABCX文件"""
    measures = []
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
                    notes = extract_measure_notes(part, key_flats, key_sharps)
                    measures.append((measure_num, notes))

    return measures


def midi_to_events(midi_path):
    """提取MIDI事件 (index, time_seconds, pitch, duration)"""
    mid = mido.MidiFile(midi_path)
    notes = []

    for track in mid.tracks:
        current_time = 0
        tempo = 500000
        active_notes = {}

        for msg in track:
            current_time += msg.time

            if msg.type == 'set_tempo':
                tempo = msg.tempo
            elif msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.note, msg.channel)
                time_seconds = mido.tick2second(current_time, mid.ticks_per_beat, tempo)
                active_notes[key] = (time_seconds, current_time)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.note, msg.channel)
                if key in active_notes:
                    start_time, start_tick = active_notes[key]
                    end_time = mido.tick2second(current_time, mid.ticks_per_beat, tempo)
                    duration = end_time - start_time
                    notes.append((msg.note, duration, start_tick, start_time))
                    del active_notes[key]

    notes.sort(key=lambda x: x[2])

    # 返回 (index, time_seconds, pitch, duration)
    events = [(i, n[3], n[0], n[1]) for i, n in enumerate(notes)]
    return events


def compute_local_score(measure_notes, events, start_idx):
    """
    局部打分器：计算小节与MIDI位置的匹配分数

    考虑：
    1. Pitch序列匹配（绝对pitch）
    2. Duration相似度
    3. 第一个音符匹配
    4. 有序匹配
    """
    if not measure_notes or start_idx >= len(events):
        return 0.0

    # 窗口大小：小节音符数的2倍
    window_size = max(len(measure_notes) * 2, 8)
    window_end = min(start_idx + window_size, len(events))

    # 提取窗口内的音符
    window_notes = [(events[i][2], events[i][3]) for i in range(start_idx, window_end)]

    # 1. Pitch序列匹配（使用Counter）
    measure_pitches = [n[0] for n in measure_notes]
    window_pitches = [n[0] for n in window_notes]

    measure_pitch_counter = Counter(measure_pitches)
    window_pitch_counter = Counter(window_pitches)

    # Set recall
    matched_pitches = sum(min(measure_pitch_counter[p], window_pitch_counter.get(p, 0))
                         for p in measure_pitch_counter)
    pitch_recall = matched_pitches / len(measure_pitches) if measure_pitches else 0

    # 2. 第一个音符匹配
    first_match = 1.0 if measure_pitches and events[start_idx][2] == measure_pitches[0] else 0.0

    # 3. 有序匹配（类似LCS）
    ordered_matches = 0
    window_idx = 0
    for target_pitch in measure_pitches:
        while window_idx < len(window_pitches):
            if window_pitches[window_idx] == target_pitch:
                ordered_matches += 1
                window_idx += 1
                break
            window_idx += 1

    ordered_ratio = ordered_matches / len(measure_pitches) if measure_pitches else 0

    # 4. Duration相似度（可选，如果需要）
    # 这里简化处理，主要依赖pitch匹配

    # 综合分数
    score = (
        pitch_recall * 1000 +      # Pitch召回率最重要
        first_match * 500 +         # 第一个音符匹配很重要
        ordered_ratio * 300         # 有序匹配
    )

    return score


def find_measure_alignments_global_dp(measures, events, verbose=False):
    """
    全局动态规划对齐

    状态：DP[measure_idx][event_idx] = 前measure_idx个小节对齐到前event_idx个事件的最优分数
    转移：对于每个小节，尝试所有可能的起始位置
    """
    if not measures or not events:
        return {}

    num_measures = len(measures)
    num_events = len(events)

    if verbose:
        print(f"总小节数: {num_measures}, 总事件数: {num_events}")
        print(f"使用全局DP算法...")

    # 步骤1：为每个小节生成候选位置
    # 使用稀疏采样减少计算量
    all_candidates = []

    for measure_idx, (measure_num, measure_notes) in enumerate(measures):
        if not measure_notes:
            # 空小节：使用估计位置
            estimated_pos = int((measure_idx + 1) / num_measures * num_events)
            all_candidates.append([(estimated_pos, 0.0)])
            continue

        # 候选位置：在整个MIDI中采样
        # 策略：以第一个音符的pitch为锚点
        first_pitch = measure_notes[0][0]
        candidates = []

        # 找到所有第一个音符匹配的位置
        for event_idx in range(num_events):
            if events[event_idx][2] == first_pitch:
                score = compute_local_score(measure_notes, events, event_idx)
                if score > 100:  # 只保留有一定匹配度的候选
                    candidates.append((event_idx, score))

        if not candidates:
            # 如果没找到匹配，使用估计位置
            estimated_pos = int((measure_idx + 1) / num_measures * num_events)
            score = compute_local_score(measure_notes, events, estimated_pos)
            candidates.append((estimated_pos, score))

        # 保留top-K候选（减少DP复杂度）
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:20]  # 每个小节最多20个候选

        all_candidates.append(candidates)

    if verbose:
        avg_candidates = sum(len(c) for c in all_candidates) / len(all_candidates)
        print(f"平均每个小节有 {avg_candidates:.1f} 个候选位置")

    # 步骤2：全局动态规划
    NEG_INF = float('-inf')

    # DP状态：prev_dp[candidate_idx] = 最优分数
    prev_dp = {}
    parent = [{} for _ in range(num_measures)]

    # 初始化第一个小节
    for cand_idx, (event_idx, score) in enumerate(all_candidates[0]):
        prev_dp[cand_idx] = score

    # 前向传播
    for measure_idx in range(1, num_measures):
        curr_dp = {}

        if not all_candidates[measure_idx] or not prev_dp:
            prev_dp = curr_dp
            continue

        for c2, (ev2, score2) in enumerate(all_candidates[measure_idx]):
            best_total = NEG_INF
            best_prev = -1

            for c1, total1 in prev_dp.items():
                ev1 = all_candidates[measure_idx - 1][c1][0]

                # 约束1：位置必须递增（单调性）
                if ev2 <= ev1:
                    continue

                # 约束2：间隔惩罚（软约束，不拒绝）
                gap = ev2 - ev1
                expected_gap = num_events / num_measures

                # 使用更温和的惩罚函数
                gap_deviation = abs(gap - expected_gap) / expected_gap if expected_gap > 0 else 0
                gap_penalty = -gap_deviation * 50  # 降低惩罚系数

                total = total1 + score2 + gap_penalty

                if total > best_total:
                    best_total = total
                    best_prev = c1

            if best_total > NEG_INF:
                curr_dp[c2] = best_total
                parent[measure_idx][c2] = best_prev

        # 如果当前小节没有有效转移，放宽约束重试
        if not curr_dp:
            if verbose:
                print(f"警告：小节 {measure_idx+1} 没有有效转移，放宽约束...")
            # 允许任意转移（只要递增）
            for c2, (ev2, score2) in enumerate(all_candidates[measure_idx]):
                best_total = NEG_INF
                best_prev = -1

                for c1, total1 in prev_dp.items():
                    ev1 = all_candidates[measure_idx - 1][c1][0]

                    if ev2 <= ev1:
                        continue

                    # 不加任何惩罚
                    total = total1 + score2

                    if total > best_total:
                        best_total = total
                        best_prev = c1

                if best_total > NEG_INF:
                    curr_dp[c2] = best_total
                    parent[measure_idx][c2] = best_prev

        prev_dp = curr_dp

    if not prev_dp:
        if verbose:
            print("警告：DP失败，没有找到有效路径")
        return {}

    # 步骤3：回溯找到最优路径
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

    # 步骤4：生成对齐结果
    alignments = {}
    for measure_idx, event_idx in enumerate(path):
        if event_idx is not None and event_idx < len(events):
            measure_num = measures[measure_idx][0]
            event_time = events[event_idx][1]
            tick = int(event_time * 100)
            alignments[measure_num] = tick

    if verbose:
        print(f"对齐结果: {len(alignments)}/{num_measures} 个小节")

    return alignments


def main():
    parser = argparse.ArgumentParser(description='小节对齐算法 - 全局DP版本')
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    if args.verbose:
        print(f"解析ABCX文件: {args.abcx_file}")
    measures = parse_abcx(args.abcx_file)
    if args.verbose:
        print(f"找到 {len(measures)} 个小节\n")

    if args.verbose:
        print(f"解析MIDI文件: {args.midi_file}")
    events = midi_to_events(args.midi_file)
    if args.verbose:
        print(f"找到 {len(events)} 个事件\n")

    alignments = find_measure_alignments_global_dp(measures, events, args.verbose)

    result = ' '.join(f"{m}:{tick}" for m, tick in sorted(alignments.items()))
    print(result)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(result + '\n')
        if args.verbose:
            print(f"\n结果已保存到: {args.output}")


if __name__ == '__main__':
    main()
