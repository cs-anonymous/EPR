#!/usr/bin/env python3
"""
评估新的小节对齐算法（V2）的准确性

不使用GT reference作为算法输入，只用于评估结果
"""

import argparse
import subprocess
from pathlib import Path


def parse_alignment(alignment_str):
    """解析对齐结果字符串"""
    alignments = {}
    for pair in alignment_str.strip().split():
        if ':' in pair:
            parts = pair.split(':')
            if len(parts) == 2 and parts[0] and parts[1]:
                measure, tick = parts
                alignments[int(measure)] = int(tick)
    return alignments


def load_ground_truth(gt_path):
    """加载标准答案"""
    with open(gt_path, 'r') as f:
        return parse_alignment(f.read())


def run_alignment_v2(abcx_file, midi_file, verbose=False):
    """运行V2对齐算法（不使用GT reference）"""
    cmd = ['python3', 'align_measures_v2.py', abcx_file, midi_file]
    if verbose:
        cmd.append('--verbose')

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return parse_alignment(result.stdout)


def evaluate(predicted, ground_truth, tolerance=0, verbose=False):
    """
    评估预测结果

    Args:
        predicted: 预测的对齐结果
        ground_truth: 标准答案
        tolerance: 允许的tick误差范围
        verbose: 是否显示详细信息

    Returns:
        (accuracy, correct_count, total_count, errors)
    """
    total = len(ground_truth)
    correct = 0
    errors = []

    for measure, gt_tick in ground_truth.items():
        pred_tick = predicted.get(measure)

        if pred_tick is None:
            errors.append((measure, gt_tick, None, 'missing'))
        elif abs(pred_tick - gt_tick) <= tolerance:
            correct += 1
        else:
            diff = abs(pred_tick - gt_tick)
            errors.append((measure, gt_tick, pred_tick, diff))

    # 检查多余的预测
    for measure in predicted:
        if measure not in ground_truth:
            errors.append((measure, None, predicted[measure], 'extra'))

    accuracy = correct / total if total > 0 else 0.0

    if verbose:
        print(f"\n评估结果 (tolerance={tolerance}):")
        print(f"总小节数: {total}")
        print(f"正确匹配: {correct}")
        print(f"准确率: {accuracy:.2%}")

        if errors:
            print(f"\n错误详情 ({len(errors)} 个):")
            for measure, gt, pred, err in errors[:20]:
                if err == 'missing':
                    print(f"  小节 {measure}: 缺失 (GT: {gt})")
                elif err == 'extra':
                    print(f"  小节 {measure}: 多余 (预测: {pred})")
                else:
                    print(f"  小节 {measure}: GT={gt}, 预测={pred}, 差距={err}")

            if len(errors) > 20:
                print(f"  ... 还有 {len(errors) - 20} 个错误")

    return accuracy, correct, total, errors


def main():
    parser = argparse.ArgumentParser(description='评估V2小节对齐算法')
    parser.add_argument('ground_truth', help='标准答案文件路径')
    parser.add_argument('abcx_file', help='ABCX文件路径')
    parser.add_argument('midi_file', help='MIDI文件路径')
    parser.add_argument('--tolerance', type=int, default=0,
                       help='允许的tick误差（默认0=精确匹配）')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')

    args = parser.parse_args()

    # 加载标准答案
    if args.verbose:
        print(f"加载标准答案: {args.ground_truth}")
    ground_truth = load_ground_truth(args.ground_truth)
    if args.verbose:
        print(f"  {len(ground_truth)} 个小节")

    # 运行V2算法（不使用GT reference）
    if args.verbose:
        print(f"\n运行V2对齐算法（无GT reference）...")

    predicted = run_alignment_v2(args.abcx_file, args.midi_file, args.verbose)

    # 评估
    accuracy, correct, total, errors = evaluate(predicted, ground_truth, args.tolerance, args.verbose)

    # 输出简要结果
    if not args.verbose:
        print(f"准确率: {accuracy:.2%} ({correct}/{total})")

    # 额外统计：不同tolerance下的准确率
    if args.verbose:
        print(f"\n不同tolerance下的准确率:")
        for tol in [0, 1, 5, 10, 50]:
            acc, corr, _, _ = evaluate(predicted, ground_truth, tol, False)
            print(f"  tolerance={tol}: {acc:.2%} ({corr}/{total})")


if __name__ == '__main__':
    main()
