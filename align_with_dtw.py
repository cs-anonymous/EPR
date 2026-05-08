#!/usr/bin/env python3
"""
通用的measure-level对齐pipeline

步骤：
1. 使用DTW进行note-level对齐（score MIDI <-> performance MIDI）
2. 将note-level对齐粗化到measure-level
3. 从ABCX中提取每个小节的第一个音符
4. 在score MIDI中找到对应的音符
5. 通过alignment映射到performance MIDI

使用pretty_midi进行MIDI处理，使用scipy的DTW
"""

import argparse
import re
import numpy as np
from pathlib import Path
import mido
import pretty_midi


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
                    return pitch  # 返回第一个音符
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


# ===== MIDI处理部分 =====

def load_midi_notes(midi_path):
    """
    加载MIDI文件的所有音符

    Returns:
        notes: [(start_time, pitch, duration), ...]
    """
    pm = pretty_midi.PrettyMIDI(midi_path)
    notes = []

    for instrument in pm.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            notes.append((note.start, note.pitch, note.end - note.start))

    # 按开始时间排序
    notes.sort(key=lambda x: x[0])
    return notes


def compute_chroma_features(notes, hop_length=0.1):
    """
    从音符序列计算chroma特征

    Args:
        notes: [(start_time, pitch, duration), ...]
        hop_length: 时间窗口大小（秒）

    Returns:
        chroma: (n_frames, 12) 的chroma矩阵
        times: (n_frames,) 每帧的时间
    """
    if not notes:
        return np.zeros((0, 12)), np.array([])

    # 确定时间范围
    max_time = max(n[0] + n[2] for n in notes)
    n_frames = int(np.ceil(max_time / hop_length))

    chroma = np.zeros((n_frames, 12))
    times = np.arange(n_frames) * hop_length

    # 为每个音符填充chroma
    for start_time, pitch, duration in notes:
        start_frame = int(start_time / hop_length)
        end_frame = int((start_time + duration) / hop_length) + 1
        pitch_class = pitch % 12

        for frame in range(start_frame, min(end_frame, n_frames)):
            chroma[frame, pitch_class] += 1.0

    # 归一化
    row_sums = chroma.sum(axis=1, keepdims=True)
    chroma = np.divide(chroma, row_sums, where=row_sums > 0)

    return chroma, times


def dtw_alignment(score_chroma, perf_chroma):
    """
    使用DTW对齐两个chroma序列

    Returns:
        path: [(score_idx, perf_idx), ...] 对齐路径
    """
    from scipy.spatial.distance import cdist

    # 计算距离矩阵
    D = cdist(score_chroma, perf_chroma, metric='cosine')

    # DTW
    n, m = D.shape
    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i, j] = D[i-1, j-1] + min(
                cost[i-1, j],    # 插入
                cost[i, j-1],    # 删除
                cost[i-1, j-1]   # 匹配
            )

    # 回溯找路径
    path = []
    i, j = n, m
    while i > 0 and j > 0:
        path.append((i-1, j-1))

        # 选择最小的前驱
        candidates = [
            (cost[i-1, j], i-1, j),
            (cost[i, j-1], i, j-1),
            (cost[i-1, j-1], i-1, j-1)
        ]
        _, i, j = min(candidates)

    path.reverse()
    return path


def align_measures(abcx_path, score_midi_path, perf_midi_path, verbose=False):
    """
    完整的measure-level对齐pipeline

    Returns:
        alignments: {measure_num: perf_time_tick, ...}
    """
    if verbose:
        print("步骤1: 解析ABCX，提取每个小节的第一个音符")

    measure_starts = parse_abcx_measure_starts(abcx_path)

    if verbose:
        print(f"  找到 {len(measure_starts)} 个小节")
        print(f"  前5个: {measure_starts[:5]}")

    if verbose:
        print("\n步骤2: 加载MIDI文件")

    score_notes = load_midi_notes(score_midi_path)
    perf_notes = load_midi_notes(perf_midi_path)

    if verbose:
        print(f"  Score: {len(score_notes)} 个音符")
        print(f"  Performance: {len(perf_notes)} 个音符")

    if verbose:
        print("\n步骤3: 计算chroma特征")

    score_chroma, score_times = compute_chroma_features(score_notes, hop_length=0.1)
    perf_chroma, perf_times = compute_chroma_features(perf_notes, hop_length=0.1)

    if verbose:
        print(f"  Score chroma: {score_chroma.shape}")
        print(f"  Performance chroma: {perf_chroma.shape}")

    if verbose:
        print("\n步骤4: 执行DTW对齐")

    dtw_path = dtw_alignment(score_chroma, perf_chroma)

    if verbose:
        print(f"  DTW路径长度: {len(dtw_path)}")

    if verbose:
        print("\n步骤5: 粗化到measure-level")

    # 创建DTW路径的映射字典（score_frame -> perf_frame）
    dtw_map = {}
    for s_idx, p_idx in dtw_path:
        if s_idx not in dtw_map:
            dtw_map[s_idx] = p_idx
        else:
            # 如果有多个映射，取平均
            dtw_map[s_idx] = (dtw_map[s_idx] + p_idx) // 2

    alignments = {}
    used_score_times = set()  # 避免重复使用同一个音符

    for measure_num, first_pitch in measure_starts:
        # 在score MIDI中找到第一个匹配的音符（且未被使用过）
        score_note_idx = None
        score_time = None

        for i, (start_time, pitch, duration) in enumerate(score_notes):
            if pitch == first_pitch and start_time not in used_score_times:
                score_note_idx = i
                score_time = start_time
                used_score_times.add(start_time)
                break

        if score_note_idx is None or score_time is None:
            if verbose:
                print(f"  警告: 小节 {measure_num} 的第一个音符 (pitch={first_pitch}) 在score MIDI中未找到或已被使用")
            continue

        # 找到score_time对应的chroma frame
        score_frame = int(score_time / 0.1)

        # 通过DTW映射找到对应的performance frame
        if score_frame in dtw_map:
            perf_frame = dtw_map[score_frame]
        else:
            # 如果精确frame不在映射中，找最近的
            closest_frame = min(dtw_map.keys(), key=lambda x: abs(x - score_frame))
            perf_frame = dtw_map[closest_frame]

        if perf_frame < len(perf_times):
            perf_time = perf_times[perf_frame]
            tick = int(perf_time * 100)
            alignments[measure_num] = tick

    if verbose:
        print(f"\n对齐完成: {len(alignments)}/{len(measure_starts)} 个小节")

    return alignments


def main():
    parser = argparse.ArgumentParser(
        description='通用measure-level对齐（使用DTW）'
    )
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('score_midi', help='Score MIDI文件路径')
    parser.add_argument('performance_midi', help='Performance MIDI文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    # 执行对齐
    alignments = align_measures(
        args.abcx_file,
        args.score_midi,
        args.performance_midi,
        args.verbose
    )

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
