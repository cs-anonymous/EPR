#!/usr/bin/env python3
"""
使用ASAP数据集的beat annotations进行measure-level对齐

ASAP数据集已经提供了beat-level的对齐：
- midi_score_annotations.txt: score的beat时间
- performance_annotations.txt: performance的beat时间
- db = downbeat（小节开始）
- b = beat（拍子）

策略：
1. 从score annotations中提取每个小节的开始时间（downbeat）
2. 从performance annotations中提取对应的downbeat时间
3. 将时间转换为tick格式（time * 100）
"""

import argparse
import re
from pathlib import Path


def parse_annotations(annotation_file):
    """
    解析ASAP annotations文件

    Returns:
        downbeats: [(score_time, perf_time, measure_num), ...]
        beats: [(score_time, perf_time), ...]
    """
    downbeats = []
    beats = []
    measure_num = 0

    with open(annotation_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) < 3:
                continue

            score_time = float(parts[0])
            perf_time = float(parts[1])
            annotation = parts[2]

            if annotation.startswith('db'):
                # Downbeat（小节开始）
                measure_num += 1
                downbeats.append((score_time, perf_time, measure_num))
            elif annotation == 'b':
                # Beat（拍子）
                beats.append((score_time, perf_time))

    return downbeats, beats


def align_measures_from_annotations(score_annotations, perf_annotations, verbose=False):
    """
    从ASAP annotations中提取measure-level对齐

    Returns:
        alignments: {measure_num: tick, ...}
    """
    if verbose:
        print(f"解析score annotations: {score_annotations}")

    score_downbeats, score_beats = parse_annotations(score_annotations)

    if verbose:
        print(f"  找到 {len(score_downbeats)} 个downbeats")
        print(f"  找到 {len(score_beats)} 个beats")

    if verbose:
        print(f"\n解析performance annotations: {perf_annotations}")

    perf_downbeats, perf_beats = parse_annotations(perf_annotations)

    if verbose:
        print(f"  找到 {len(perf_downbeats)} 个downbeats")
        print(f"  找到 {len(perf_beats)} 个beats")

    # 生成对齐结果
    alignments = {}

    # 假设score和performance的downbeat数量相同且对应
    for i, (score_time, perf_time, measure_num) in enumerate(perf_downbeats):
        # 转换为tick格式（time * 100）
        tick = int(perf_time * 100)
        alignments[measure_num] = tick

    if verbose:
        print(f"\n对齐结果: {len(alignments)} 个小节")
        print(f"前10个小节:")
        for m in range(1, min(11, len(alignments) + 1)):
            if m in alignments:
                print(f"  小节 {m}: tick {alignments[m]}")

    return alignments


def main():
    parser = argparse.ArgumentParser(
        description='使用ASAP annotations进行measure-level对齐'
    )
    parser.add_argument('score_annotations', help='Score annotations文件路径')
    parser.add_argument('performance_annotations', help='Performance annotations文件路径')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    # 执行对齐
    alignments = align_measures_from_annotations(
        args.score_annotations,
        args.performance_annotations,
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
