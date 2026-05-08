#!/usr/bin/env python3
"""
小节对齐算法改进版：不使用GT reference

基于原算法，但改进了位置估计和搜索策略：
1. 使用绝对pitch而不是pitch class
2. 考虑音符时长
3. 更智能的初始位置估计
4. 更宽的搜索范围
"""

import argparse
import re
import mido
from pathlib import Path
from collections import Counter


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


def extract_measure_pitches(measure_content, key_flats=None, key_sharps=None):
    """提取小节中的pitch序列（绝对pitch）"""
    if key_flats is None:
        key_flats = set()
    if key_sharps is None:
        key_sharps = set()

    pitches = []
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
                    pitches.append(pitch)

    return pitches


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
                    pitches = extract_measure_pitches(part, key_flats, key_sharps)
                    measures.append((measure_num, pitches))

    return measures


def midi_to_events(midi_path):
    """提取MIDI note-on事件"""
    mid = mido.MidiFile(midi_path)
    events = []

    for track in mid.tracks:
        current_time = 0
        tempo = 500000

        for msg in track:
            current_time += msg.time
            if msg.type == 'set_tempo':
                tempo = msg.tempo
            elif msg.type == 'note_on' and msg.velocity > 0:
                time_seconds = mido.tick2second(current_time, mid.ticks_per_beat, tempo)
                pitch = msg.note  # 使用绝对pitch
                events.append((time_seconds, pitch))

    events.sort(key=lambda x: x[0])
    indexed_events = [(i, time, pitch) for i, (time, pitch) in enumerate(events, 1)]
    return indexed_events


def score_position(measure_pitches, pitch_counter, n_notes, events, start_idx):
    """
    评分函数：使用绝对pitch匹配
    """
    if start_idx >= len(events):
        return 0, 0

    window_size = max(n_notes, 8)
    window_end = min(start_idx + window_size, len(events))
    window_counter = Counter()
    for j in range(start_idx, window_end):
        window_counter[events[j][2]] += 1

    # Set recall
    matched = sum(min(pitch_counter[p], window_counter.get(p, 0)) for p in pitch_counter)
    recall = matched / n_notes if n_notes > 0 else 0

    # Precision
    total_w = sum(window_counter.values())
    precision = matched / total_w if total_w > 0 else 0

    # 第一个音符匹配
    first_pitch = measure_pitches[0] if measure_pitches else None
    first_nearby = 0
    if first_pitch is not None:
        for j in range(start_idx, min(start_idx + 3, len(events))):
            if events[j][2] == first_pitch:
                first_nearby = 1
                break

    # 有序前缀匹配
    ordered = 0
    if measure_pitches:
        ev_idx = start_idx
        for pitch in measure_pitches:
            while ev_idx < window_end:
                if events[ev_idx][2] == pitch:
                    ordered += 1
                    ev_idx += 1
                    break
                ev_idx += 1
            else:
                break

    score = recall * 1000 + first_nearby * 300 + precision * 100 + ordered * 50
    return score, recall


def find_measure_alignments(measures, events, verbose=False):
    if not measures or not events:
        return {}

    num_measures = len(measures)
    num_events = len(events)

    if verbose:
        print(f"总小节数: {num_measures}, 总事件数: {num_events}")

    # 预处理
    note_counts = []
    pitch_sequences = []
    pitch_counters = []

    for measure_num, pitches in measures:
        pitch_sequences.append(pitches)
        note_counts.append(len(pitches))
        pitch_counters.append(Counter(pitches))

    # 位置估计：基于音符数量的加权估计
    total_notes = sum(note_counts)
    measure_estimates = []
    cumulative_notes = 0

    for nc in note_counts:
        cumulative_notes += nc
        fraction = cumulative_notes / total_notes if total_notes > 0 else 0
        estimate = int(fraction * num_events)
        measure_estimates.append(estimate)

    # 生成候选
    all_candidates = []

    for measure_idx in range(num_measures):
        current_notes = note_counts[measure_idx]

        if current_notes == 0:
            est = measure_estimates[measure_idx]
            all_candidates.append([(est, 0, 0)])
            continue

        measure_seq = pitch_sequences[measure_idx]
        pitch_counter = pitch_counters[measure_idx]
        estimated_event = measure_estimates[measure_idx]

        # 搜索范围：估计位置 +/- 50%
        margin = max(100, int(num_events * 0.5 / num_measures))
        search_start = max(0, estimated_event - margin)
        search_end = min(estimated_event + margin + 1, num_events)

        # 确保在前一个小节之后
        if all_candidates and measure_idx > 0:
            prev_cands = all_candidates[-1]
            if prev_cands:
                min_prev_ev = min(c[0] for c in prev_cands)
                search_start = max(search_start, min_prev_ev + 1)

        # 采样候选（避免过多）
        step = max(1, (search_end - search_start) // 50)
        scored = []

        for i in range(search_start, search_end, step):
            score, recall = score_position(measure_seq, pitch_counter, current_notes, events, i)
            scored.append((i, score, recall))

        # 确保估计位置是候选之一
        if search_start <= estimated_event < search_end:
            if not any(s[0] == estimated_event for s in scored):
                score, recall = score_position(measure_seq, pitch_counter, current_notes, events, estimated_event)
                scored.append((estimated_event, score, recall))

        if not scored:
            scored.append((estimated_event, 0, 0))

        all_candidates.append(scored)

    # DP
    NEG_INF = float('-inf')
    prev_dp = {}
    parent = [{} for _ in range(num_measures)]

    for cand_idx, (event_idx, score, recall) in enumerate(all_candidates[0]):
        prev_dp[cand_idx] = score

    avg_gap = num_events / num_measures

    for measure_idx in range(1, num_measures):
        curr_dp = {}

        if not all_candidates[measure_idx] or not prev_dp:
            prev_dp = curr_dp
            continue

        for c2, (ev2, score2, rec2) in enumerate(all_candidates[measure_idx]):
            best_total = NEG_INF
            best_prev = -1

            for c1, total1 in prev_dp.items():
                ev1 = all_candidates[measure_idx - 1][c1][0]
                gap = ev2 - ev1

                if gap < 1:
                    continue

                # 间隔惩罚
                gap_deviation = abs(gap - avg_gap) / avg_gap if avg_gap > 0 else 0
                gap_score = -gap_deviation * 100

                total = total1 + score2 + gap_score

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

    # 生成结果
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
    parser = argparse.ArgumentParser(description='小节对齐算法（改进版，不使用GT）')
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
    events = midi_to_events(args.midi_file)
    if args.verbose:
        print(f"找到 {len(events)} 个事件")

    if args.verbose:
        print(f"\n开始对齐...")

    alignments = find_measure_alignments(measures, events, args.verbose)

    result = ' '.join(f"{m}:{tick}" for m, tick in sorted(alignments.items()))
    print(result)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(result + '\n')
        if args.verbose:
            print(f"\n结果已保存到: {args.output}")


if __name__ == '__main__':
    main()
