#!/usr/bin/env python3
"""
评估小节对齐算法的准确性。

比较算法输出与标准答案（ground truth）。
"""

import argparse
import subprocess
import tempfile
from pathlib import Path


def parse_alignment(alignment_str):
    """解析对齐结果字符串。

    格式: "1:16 2:64 3:110 ..."
    返回: {1: 16, 2: 64, 3: 110, ...}
    """
    alignments = {}
    for pair in alignment_str.strip().split():
        if ':' in pair:
            measure, pos = pair.split(':')
            alignments[int(measure)] = int(pos)
    return alignments


def load_ground_truth(gt_path):
    """加载标准答案。"""
    with open(gt_path, 'r') as f:
        return parse_alignment(f.read())


def run_alignment_algorithm(abcx_file, midi_file, **kwargs):
    """运行对齐算法。

    Args:
        abcx_file: ABCX文件路径
        midi_file: MIDI文件路径
        **kwargs: 传递给算法的其他参数

    Returns:
        对齐结果字典
    """
    cmd = ['python3', 'align_measures.py', abcx_file, midi_file]

    # 添加可选参数
    if 'min_gap' in kwargs:
        cmd.extend(['--min-gap', str(kwargs['min_gap'])])
    if 'threshold' in kwargs:
        cmd.extend(['--threshold', str(kwargs['threshold'])])
    if 'search_range' in kwargs:
        cmd.extend(['--search-range', str(kwargs['search_range'])])

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return parse_alignment(result.stdout)


def evaluate(predicted, ground_truth, verbose=False):
    """评估预测结果。

    Args:
        predicted: 预测的对齐结果
        ground_truth: 标准答案
        verbose: 是否显示详细信息

    Returns:
        (accuracy, correct_count, total_count, errors)
    """
    total = len(ground_truth)
    correct = 0
    errors = []

    for measure, gt_pos in ground_truth.items():
        pred_pos = predicted.get(measure)

        if pred_pos is None:
            errors.append((measure, gt_pos, None, 'missing'))
        elif pred_pos == gt_pos:
            correct += 1
        else:
            diff = abs(pred_pos - gt_pos)
            errors.append((measure, gt_pos, pred_pos, diff))

    # 检查是否有多余的预测
    for measure in predicted:
        if measure not in ground_truth:
            errors.append((measure, None, predicted[measure], 'extra'))

    accuracy = correct / total if total > 0 else 0.0

    if verbose:
        print(f"\n评估结果:")
        print(f"总小节数: {total}")
        print(f"正确匹配: {correct}")
        print(f"准确率: {accuracy:.2%}")

        if errors:
            print(f"\n错误详情 ({len(errors)} 个):")
            for measure, gt, pred, err in errors[:20]:  # 只显示前20个错误
                if err == 'missing':
                    print(f"  小节 {measure}: 缺失 (标准答案: {gt})")
                elif err == 'extra':
                    print(f"  小节 {measure}: 多余 (预测: {pred})")
                else:
                    print(f"  小节 {measure}: 标准={gt}, 预测={pred}, 差距={err}")

            if len(errors) > 20:
                print(f"  ... 还有 {len(errors) - 20} 个错误")

    return accuracy, correct, total, errors


def main():
    parser = argparse.ArgumentParser(description='评估小节对齐算法')
    parser.add_argument('ground_truth', help='标准答案文件路径')
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--min-gap', type=int, default=10, help='最小间隔')
    parser.add_argument('--threshold', type=float, default=0.3, help='F1阈值')
    parser.add_argument('--search-range', type=int, default=200, help='搜索范围')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    # 加载标准答案
    if args.verbose:
        print(f"加载标准答案: {args.ground_truth}")
    ground_truth = load_ground_truth(args.ground_truth)

    # 运行算法
    if args.verbose:
        print(f"运行对齐算法...")
        print(f"  参数: min_gap={args.min_gap}, threshold={args.threshold}, search_range={args.search_range}")

    predicted = run_alignment_algorithm(
        args.abcx_file,
        args.midi_file,
        min_gap=args.min_gap,
        threshold=args.threshold,
        search_range=args.search_range
    )

    # 评估
    accuracy, correct, total, errors = evaluate(predicted, ground_truth, args.verbose)

    # 输出简要结果
    if not args.verbose:
        print(f"准确率: {accuracy:.2%} ({correct}/{total})")


if __name__ == '__main__':
    main()
