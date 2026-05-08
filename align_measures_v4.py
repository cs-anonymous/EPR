#!/usr/bin/env python3
"""
小节对齐算法 V4：全局搜索 + 动态规划

核心思路：
1. 使用绝对pitch（不是pitch class）
2. 考虑音符时长
3. 对每个小节在整个MIDI中搜索所有可能的匹配位置
4. 使用DP找到全局最优路径
5. 不依赖GT reference
"""

import argparse
import re
import mido
from collections import Counter


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

NOTE_BASE_PITCH = {
    'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11,
}


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
        accidental = 0
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


def midi_to_notes(midi_path):
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
    return notes


def score_match(measure_notes, midi_notes, start_idx):
    """
    计算小节与MIDI位置的匹配分数

    使用pitch序列匹配 + duration相似度
    """
    if not measure_notes or start_idx >= len(midi_notes):
        return 0.0

    # 窗口大小：小节音符数的2倍
    window_size = max(len(measure_notes) * 2, 10)
    window_end = min(start_idx + window_size, len(midi_notes))

    # 提取窗口内的pitch序列
    window_pitches = [midi_notes[i][0] for i in range(start_idx, window_end)]
    measure_pitches = [n[0] for n in measure_notes]

    # 计算pitch序列匹配度
    matched = 0
    midi_idx = 0
    for target_pitch in measure_pitches:
        # 在窗口中查找这个pitch
        found = False
        for i in range(midi_idx, len(window_pitches)):
            if window_pitches[i] == target_pitch:
                matched += 1
                midi_idx = i + 1
                found = True
                break
        if not found:
            # 没找到，跳过
            pass

    # 召回率
    recall = matched / len(measure_pitches) if measure_pitches else 0

    # 第一个音符匹配奖励
    first_match = 1.0 if measure_pitches and midi_notes[start_idx][0] == measure_pitches[0] else 0.0

    # 综合分数
    score = recall * 1000 + first_match * 500

    return score


def find_measure_alignments(measures, midi_notes, verbose=False):
    if not measures or not midi_notes:
        return {}

    num_measures = len(measures)
    num_notes = len(midi_notes)

    if verbose:
        print(f"总小节数: {num_measures}, 总MIDI音符数: {num_notes}")

    # 步骤1：为每个小节生成候选位置（全局搜索）
    all_candidates = []

    for measure_idx, (measure_num, measure_notes) in enumerate(measures):
        if not measure_notes:
            # 空小节：使用估计位置
            estimated_pos = int((measure_idx + 1) / num_measures * num_notes)
            all_candidates.append([(estimated_pos, 0.0)])
            continue

        # 全局搜索：在整个MIDI中寻找匹配位置
        first_pitch = measure_notes[0][0]
        candidates = []

        # 只在第一个音符匹配的位置评分
        for pos in range(num_notes):
            if midi_notes[pos][0] == first_pitch:
                score = score_match(measure_notes, midi_notes, pos)
                if score > 100:  # 只保留有一定匹配度的候选
                    candidates.append((pos, score))

        if not candidates:
            # 如果没找到匹配，使用估计位置
            estimated_pos = int((measure_idx + 1) / num_measures * num_notes)
            candidates.append((estimated_pos, 0.0))

        # 保留top-30候选
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:30]

        all_candidates.append(candidates)

    # 步骤2：动态规划找到全局最优路径
    NEG_INF = float('-inf')
    prev_dp = {}
    parent = [{} for _ in range(num_measures)]

    # 初始化第一个小节
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

                # 间隔惩罚：相邻小节不应该离得太远
                gap = pos2 - pos1
                expected_gap = num_notes / num_measures

                if gap > expected_gap * 3:
                    # 间隔太大，惩罚
                    gap_penalty = -(gap - expected_gap * 3) * 0.5
                else:
                    gap_penalty = 0

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

    # 回溯
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
            start_time_seconds = midi_notes[pos][3]
            tick = int(start_time_seconds * 100)
            alignments[measure_num] = tick

    if verbose:
        print(f"\n对齐结果: {len(alignments)}/{num_measures} 个小节")

    return alignments


def main():
    parser = argparse.ArgumentParser(description='小节对齐算法 V4（全局搜索）')
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

    if args.verbose:
        print(f"\n解析MIDI文件: {args.midi_file}")
    midi_notes = midi_to_notes(args.midi_file)
    if args.verbose:
        print(f"找到 {len(midi_notes)} 个音符")

    if args.verbose:
        print(f"\n开始对齐...")

    alignments = find_measure_alignments(measures, midi_notes, args.verbose)

    result = ' '.join(f"{m}:{tick}" for m, tick in sorted(alignments.items()))
    print(result)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(result + '\n')
        if args.verbose:
            print(f"\n结果已保存到: {args.output}")


if __name__ == '__main__':
    main()
