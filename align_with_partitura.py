#!/usr/bin/env python3
"""
使用成熟的note-level alignment方法，然后粗化到measure-level

策略：
1. 使用partitura库进行note-level alignment（基于DTW）
2. 将note-level对齐结果粗化到measure-level
3. 找到每个小节的第一个音符在performance中的位置

partitura是一个成熟的音乐分析库，包含了note alignment功能
"""

import argparse
import subprocess
import sys

# 检查依赖
try:
    import partitura as pt
    print("✓ partitura已安装")
except ImportError:
    print("✗ partitura未安装")
    print("请安装: pip install partitura")
    sys.exit(1)

try:
    import numpy as np
    print("✓ numpy已安装")
except ImportError:
    print("✗ numpy未安装")
    print("请安装: pip install numpy")
    sys.exit(1)


def align_score_to_performance(score_midi_path, performance_midi_path, verbose=False):
    """
    使用partitura进行note-level对齐

    Returns:
        alignment: 对齐结果
    """
    if verbose:
        print(f"加载score MIDI: {score_midi_path}")

    # 加载MIDI文件
    score = pt.load_performance_midi(score_midi_path)
    performance = pt.load_performance_midi(performance_midi_path)

    if verbose:
        print(f"Score: {len(score.notes)} 个音符")
        print(f"Performance: {len(performance.notes)} 个音符")

    # 使用partitura的对齐功能
    if verbose:
        print("执行note-level对齐...")

    # partitura的match_note_alignments函数
    alignment = pt.match.match_note_alignments(
        score.notes,
        performance.notes,
        method='dtw'  # 使用DTW方法
    )

    if verbose:
        print(f"对齐完成: {len(alignment)} 个匹配")

    return alignment, score, performance


def alignment_to_measure_starts(alignment, score, abcx_measures, verbose=False):
    """
    将note-level对齐粗化到measure-level

    找到每个小节的第一个音符在performance中的位置
    """
    if verbose:
        print("\n将note-level对齐粗化到measure-level...")

    # TODO: 实现粗化逻辑
    # 需要：
    # 1. 从ABCX中知道每个小节的第一个音符
    # 2. 在score MIDI中找到对应的音符
    # 3. 通过alignment找到在performance中的位置

    measure_alignments = {}

    return measure_alignments


def main():
    parser = argparse.ArgumentParser(
        description='使用成熟方法进行measure-level对齐'
    )
    parser.add_argument('score_midi', help='Score MIDI文件路径')
    parser.add_argument('performance_midi', help='Performance MIDI文件路径')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    # 执行对齐
    alignment, score, performance = align_score_to_performance(
        args.score_midi,
        args.performance_midi,
        args.verbose
    )

    print(f"\n对齐完成！")
    print(f"匹配的音符对: {len(alignment)}")


if __name__ == '__main__':
    main()
