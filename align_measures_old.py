#!/usr/bin/env python3
"""
小节配对算法：找到 abcx 文件中每个小节在 midi-tsv 中的起始行号。

策略：
1. 提取小节中的所有音符
2. 在 TSV 中找到一个位置，使得从该位置开始的窗口内包含小节的大部分音符
3. 该位置就是小节的起始行（第一个音符下键的位置）
4. 使用滑动窗口 + IOU 评分找到最佳匹配位置
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path
from collections import Counter


def parse_abcx(abcx_path):
    """解析 abcx 文件，提取每个小节的内容。"""
    measures = []
    measure_num = 0

    with open(abcx_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or re.match(r'^[A-Z%]:', line) or line.startswith('%%'):
                continue

            for part in line.split('|'):
                part = part.strip()
                if part:
                    measure_num += 1
                    measures.append((measure_num, part))

    return measures


def extract_notes_from_measure(measure_content):
    """从小节内容中提取所有音符。"""
    notes = []
    content = re.sub(r'\{[^}]*\}', '', measure_content)
    content = re.sub(r'![^!]*!', '', content)
    content = re.sub(r'"[^"]*"', '', content)
    content = re.sub(r'\[([^\]]*)\]', lambda m: ' '.join(m.group(1).replace(',', ' ')), content)

    for voice in content.split(';'):
        for note in re.findall(r'[_=^]?[A-Ga-g][,\']*', voice):
            clean_note = note.lstrip('_=^').rstrip(',\'0123456789/').upper()
            if clean_note and clean_note not in ['Z', 'X']:
                notes.append(clean_note)

    return Counter(notes)


def midi_to_tsv(midi_path):
    """将 MIDI 文件转换为 TSV 格式。"""
    tsv_path = tempfile.mktemp(suffix='.tsv')
    midi_tsv_script = Path(__file__).parent / 'wave-roll-studio' / 'midi_tsv.py'
    subprocess.run([
        'python3', str(midi_tsv_script),
        'midi2tsv', str(midi_path),
        '--out', tsv_path
    ], check=True, capture_output=True)
    return tsv_path


def parse_tsv(tsv_path):
    """解析 TSV 文件，提取音符事件。"""
    events = []
    with open(tsv_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r'^([A-Ga-g_][A-Ga-g_\',]*):', line)
            if match:
                parts = line.split('\t')
                if len(parts) >= 2:
                    note_name = match.group(1)
                    tick = int(parts[1])
                    clean_note = note_name.lstrip('_=^').rstrip(',\'').upper()
                    events.append((line_num, tick, clean_note))
    return events


def calculate_f1_score(measure_notes, window_notes):
    """
    计算 F1 分数，综合考虑覆盖率（召回率）和精确度。

    - 覆盖率（Recall）：小节中有多少音符在窗口中出现
    - 精确度（Precision）：窗口中有多少音符是小节需要的
    - F1 = 2 * Precision * Recall / (Precision + Recall)

    返回值在 [0, 1] 之间，1 表示完美匹配。
    """
    if not measure_notes:
        return 0.0

    # 覆盖率（召回率）
    matched = sum(min(measure_notes[note], window_notes.get(note, 0))
                  for note in measure_notes)
    total_measure = sum(measure_notes.values())
    recall = matched / total_measure if total_measure > 0 else 0.0

    # 精确度
    total_window = sum(window_notes.values())
    if total_window == 0:
        return 0.0

    needed = sum(min(measure_notes.get(note, 0), window_notes[note])
                for note in window_notes)
    precision = needed / total_window

    # F1 分数
    if precision + recall == 0:
        return 0.0

    f1 = 2 * precision * recall / (precision + recall)
    return f1


def find_measure_start(measure_notes, tsv_events, start_idx, end_idx):
    """
    为单个小节找到起始位置。

    策略：
    1. 使用多个固定窗口大小（行号范围）进行搜索
    2. 对每个位置，计算从该位置开始的窗口的 F1 分数
    3. 选择 F1 分数最高的位置作为起始位置
    """
    # 使用固定的窗口大小范围（行号差，不是事件数）
    # 经验值：一个小节通常对应30-60行TSV
    window_line_ranges = [30, 40, 50, 60]

    best_score = 0.0
    best_line = None
    best_idx = None

    for i in range(start_idx, end_idx):
        start_line = tsv_events[i][0]

        for window_range in window_line_ranges:
            # 提取窗口内的音符（基于行号范围）
            window_notes = Counter()
            for j in range(i, len(tsv_events)):
                line_num, tick, note = tsv_events[j]
                if line_num >= start_line + window_range:
                    break
                window_notes[note] += 1

            # 计算 F1 分数
            score = calculate_f1_score(measure_notes, window_notes)

            if score > best_score:
                best_score = score
                best_line = start_line
                best_idx = i

    return best_score, best_line, best_idx


def find_measure_alignments(measures, tsv_events, min_gap=15, threshold=0.3, search_range=200, verbose=False):
    """
    找到每个小节在 TSV 中的起始行号。

    参数:
        min_gap: 相邻小节之间的最小行数间隔（TSV文件的行号差）
        threshold: F1 分数阈值，低于此值的匹配将被拒绝
        search_range: 每个小节的搜索范围（事件数）
    """
    alignments = {}
    last_line_num = 0  # 上一个小节的起始行号

    for measure_num, measure_content in measures:
        measure_notes = extract_notes_from_measure(measure_content)

        if not measure_notes:
            if verbose:
                print(f"  小节 {measure_num}: 跳过（无音符）")
            continue

        # 搜索范围：从上一个小节之后开始，搜索search_range个事件
        search_start_idx = 0
        for i, (line_num, tick, note) in enumerate(tsv_events):
            if line_num > last_line_num + min_gap:
                search_start_idx = i
                break

        search_end_idx = min(search_start_idx + search_range, len(tsv_events))

        # 找到最佳起始位置
        best_score, best_line, best_idx = find_measure_start(
            measure_notes, tsv_events, search_start_idx, search_end_idx
        )

        if best_score >= threshold:
            alignments[measure_num] = best_line
            last_line_num = best_line  # 更新为行号，不是索引

            if verbose:
                note_count = sum(measure_notes.values())
                print(f"  小节 {measure_num}: 行 {best_line}, F1 {best_score:.3f}, "
                      f"音符数 {note_count}")
        elif verbose:
            print(f"  小节 {measure_num}: 未找到匹配 (最佳 F1 {best_score:.3f})")

    return alignments


def main():
    parser = argparse.ArgumentParser(description='小节配对算法')
    parser.add_argument('abcx_file', help='ABCX 文件路径')
    parser.add_argument('midi_file', help='MIDI 文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径（可选）')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')
    parser.add_argument('--keep-tsv', action='store_true', help='保留生成的 TSV 文件')
    parser.add_argument('--min-gap', type=int, default=15,
                       help='相邻小节之间的最小行数间隔（默认15）')
    parser.add_argument('--threshold', type=float, default=0.3,
                       help='F1 分数阈值（默认0.3）')
    parser.add_argument('--search-range', type=int, default=200,
                       help='每个小节的搜索范围（事件数，默认200）')

    args = parser.parse_args()

    # 解析 ABCX 文件
    if args.verbose:
        print(f"解析 ABCX 文件: {args.abcx_file}")
    measures = parse_abcx(args.abcx_file)
    if args.verbose:
        print(f"找到 {len(measures)} 个小节\n")

    # 转换 MIDI 到 TSV
    if args.verbose:
        print(f"转换 MIDI 文件: {args.midi_file}")
    tsv_path = midi_to_tsv(args.midi_file)

    # 解析 TSV 文件
    if args.verbose:
        print(f"解析 TSV 文件: {tsv_path}")
    tsv_events = parse_tsv(tsv_path)
    if args.verbose:
        print(f"找到 {len(tsv_events)} 个音符事件\n")

    # 查找对齐
    if args.verbose:
        print(f"查找小节对齐（最小间隔: {args.min_gap} 行，F1 阈值: {args.threshold:.2f}，搜索范围: {args.search_range}）...")
    alignments = find_measure_alignments(
        measures, tsv_events, args.min_gap, args.threshold, args.search_range, args.verbose
    )

    # 输出结果
    if args.verbose:
        print(f"\n结果 ({len(alignments)}/{len(measures)} 个小节已对齐):")

    for measure_num in sorted(alignments.keys()):
        line_num = alignments[measure_num]
        print(f"{measure_num}:{line_num}")

    # 保存到文件
    if args.output:
        with open(args.output, 'w') as f:
            for measure_num in sorted(alignments.keys()):
                f.write(f"{measure_num}:{alignments[measure_num]}\n")
        if args.verbose:
            print(f"\n结果已保存到: {args.output}")

    # 清理临时文件
    if not args.keep_tsv:
        Path(tsv_path).unlink(missing_ok=True)
    elif args.verbose:
        print(f"\nTSV 文件保留在: {tsv_path}")


if __name__ == '__main__':
    main()
