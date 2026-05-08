#!/usr/bin/env python3
"""
简化版：直接使用note-level匹配

策略：
1. 从ABCX提取每个小节的第一个音符（pitch）
2. 在score MIDI中找到对应的音符及其时间
3. 在performance MIDI中找到相同pitch且时间最接近的音符
4. 使用简单的贪心匹配（按时间顺序）
"""

import argparse
import re
import pretty_midi


# ===== ABCX解析部分（复用之前的代码）=====

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


def load_midi_notes(midi_path):
    pm = pretty_midi.PrettyMIDI(midi_path)
    notes = []

    for instrument in pm.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            notes.append((note.start, note.pitch))

    notes.sort(key=lambda x: x[0])
    return notes


def align_measures_simple(abcx_path, score_midi_path, perf_midi_path, verbose=False):
    """
    简单的贪心匹配算法

    对于每个小节：
    1. 找到其第一个音符的pitch
    2. 在score MIDI中找到对应的音符及其时间
    3. 在performance MIDI中找到相同pitch且时间按比例对应的音符
    """
    if verbose:
        print("步骤1: 解析ABCX")

    measure_starts = parse_abcx_measure_starts(abcx_path)

    if verbose:
        print(f"  找到 {len(measure_starts)} 个小节")

    if verbose:
        print("\n步骤2: 加载MIDI文件")

    score_notes = load_midi_notes(score_midi_path)
    perf_notes = load_midi_notes(perf_midi_path)

    if verbose:
        print(f"  Score: {len(score_notes)} 个音符")
        print(f"  Performance: {len(perf_notes)} 个音符")

    # 计算score和performance的总时长比例
    score_duration = score_notes[-1][0] if score_notes else 1.0
    perf_duration = perf_notes[-1][0] if perf_notes else 1.0
    tempo_ratio = perf_duration / score_duration

    if verbose:
        print(f"\n步骤3: 计算tempo比例")
        print(f"  Score时长: {score_duration:.2f}秒")
        print(f"  Performance时长: {perf_duration:.2f}秒")
        print(f"  Tempo比例: {tempo_ratio:.2f}")

    if verbose:
        print("\n步骤4: 匹配小节")

    alignments = {}
    used_score_indices = set()
    used_perf_indices = set()

    for measure_num, target_pitch in measure_starts:
        # 在score中找到第一个匹配的音符（未被使用过）
        score_idx = None
        score_time = None

        for i, (time, pitch) in enumerate(score_notes):
            if pitch == target_pitch and i not in used_score_indices:
                score_idx = i
                score_time = time
                used_score_indices.add(i)
                break

        if score_idx is None:
            if verbose:
                print(f"  警告: 小节 {measure_num} (pitch={target_pitch}) 在score中未找到")
            continue

        # 估计在performance中的时间
        estimated_perf_time = score_time * tempo_ratio

        # 在performance中找到最接近的匹配音符（相同pitch，未被使用）
        best_perf_idx = None
        best_time_diff = float('inf')

        for i, (time, pitch) in enumerate(perf_notes):
            if pitch == target_pitch and i not in used_perf_indices:
                time_diff = abs(time - estimated_perf_time)
                if time_diff < best_time_diff:
                    best_time_diff = time_diff
                    best_perf_idx = i

        if best_perf_idx is not None:
            perf_time = perf_notes[best_perf_idx][0]
            used_perf_indices.add(best_perf_idx)
            tick = int(perf_time * 100)
            alignments[measure_num] = tick

            if verbose and measure_num <= 10:
                print(f"  小节 {measure_num}: score_time={score_time:.2f}, perf_time={perf_time:.2f}, tick={tick}")

    if verbose:
        print(f"\n对齐完成: {len(alignments)}/{len(measure_starts)} 个小节")

    return alignments


def main():
    parser = argparse.ArgumentParser(
        description='简化版measure-level对齐（贪心匹配）'
    )
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('score_midi', help='Score MIDI文件路径')
    parser.add_argument('performance_midi', help='Performance MIDI文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    alignments = align_measures_simple(
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


if __name__ == '__main__':
    main()
