#!/usr/bin/env python3
"""
分析 phrase_epr 数据的 token 长度分布
比较原始设计（上一整句演奏条件）和新设计（上一小节演奏状态）的长度差异
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
import numpy as np
from tqdm import tqdm


def estimate_token_count(text: str) -> int:
    """粗略估计 token 数量（按空格和换行符分割）"""
    if not text:
        return 0
    # 简单估计：按空格分割 + 特殊符号
    return len(text.split()) + text.count('\n') + text.count(':')


def analyze_current_design(jsonl_path: Path) -> dict:
    """分析当前设计的长度分布"""
    lengths = []
    component_stats = defaultdict(list)

    with jsonl_path.open('r', encoding='utf-8') as f:
        for line in tqdm(f, desc=f"Analyzing {jsonl_path.name}"):
            if not line.strip():
                continue
            sample = json.loads(line)

            # 计算各部分的 token 数
            header_tokens = estimate_token_count(sample.get('score_header', ''))
            score_snip_tokens = estimate_token_count(sample.get('score_snip', ''))
            perf_context_tokens = estimate_token_count(sample.get('perf_context', ''))
            perf_target_tokens = estimate_token_count(sample.get('perf_target', ''))

            # 总输入长度（不含 target）
            input_length = header_tokens + score_snip_tokens + perf_context_tokens
            # 总长度（含 target）
            total_length = input_length + perf_target_tokens

            lengths.append({
                'task_type': sample.get('task_type', ''),
                'piece_id': sample.get('piece_id', ''),
                'target_phrase_id': sample.get('target_phrase_id', ''),
                'header': header_tokens,
                'score_snip': score_snip_tokens,
                'perf_context': perf_context_tokens,
                'perf_target': perf_target_tokens,
                'input_length': input_length,
                'total_length': total_length,
                'sample': sample  # 保存原始 sample 用于新设计估计
            })

            component_stats['header'].append(header_tokens)
            component_stats['score_snip'].append(score_snip_tokens)
            component_stats['perf_context'].append(perf_context_tokens)
            component_stats['perf_target'].append(perf_target_tokens)
            component_stats['input_length'].append(input_length)
            component_stats['total_length'].append(total_length)

    return {
        'samples': lengths,
        'component_stats': component_stats
    }


def estimate_new_design_length(sample_data: dict, tsv_data: dict = None) -> dict:
    """估计新设计下的长度

    新设计：
    - score_snip: 上一小节乐谱 + 当前整句乐谱 + 下一小节乐谱
    - perf_context: 上一小节演奏
    """
    # 从原始 sample 中获取字符串数据
    sample = sample_data['sample'] if 'sample' in sample_data else sample_data

    # 解析当前的 score_snip（包含 H_{k-1}, H_k, H_{k+1}）
    score_snip = sample.get('score_snip', '')
    if not isinstance(score_snip, str):
        # 如果不是字符串，返回空结果
        return {
            'new_score_snip_tokens': 0,
            'new_perf_context_tokens': 0,
            'new_input_length': 0,
            'new_total_length': 0,
            'saved_tokens': 0,
            'reduction_ratio': 0
        }
    score_lines = score_snip.split('\n')

    # 找到当前 phrase 的内容
    target_phrase_id = sample.get('target_phrase_id', '')
    current_phrase_lines = []
    in_current_phrase = False

    for line in score_lines:
        if line.startswith(target_phrase_id):
            in_current_phrase = True
            current_phrase_lines.append(line)
        elif in_current_phrase:
            if line.startswith('H'):
                break
            if line.startswith('M'):
                current_phrase_lines.append(line)

    # 提取第一个和最后一个小节（作为 prev/next context）
    prev_measure = None
    next_measure = None

    # 从 score_snip 中找上一个 phrase 的最后一个小节
    prev_phrase_lines = []
    for i, line in enumerate(score_lines):
        if line.startswith(target_phrase_id):
            # 找到当前 phrase 之前的内容
            prev_phrase_lines = score_lines[:i]
            break

    if prev_phrase_lines:
        # 找最后一个 M 开头的行
        for line in reversed(prev_phrase_lines):
            if line.startswith('M'):
                prev_measure = line
                break

    # 从 score_snip 中找下一个 phrase 的第一个小节
    next_phrase_lines = []
    found_current = False
    for line in score_lines:
        if line.startswith(target_phrase_id):
            found_current = True
        elif found_current and line.startswith('H'):
            # 进入下一个 phrase
            for next_line in score_lines[score_lines.index(line):]:
                if next_line.startswith('M'):
                    next_measure = next_line
                    break
            break

    # 构建新的 score_snip
    new_score_snip_lines = []
    if prev_measure:
        new_score_snip_lines.append(prev_measure)
    new_score_snip_lines.extend(current_phrase_lines)
    if next_measure:
        new_score_snip_lines.append(next_measure)

    new_score_snip = '\n'.join(new_score_snip_lines)

    # 估计新的 perf_context（上一小节演奏）
    # 从当前的 perf_context（整个 H_{k-1}）中提取最后一个小节
    perf_context = sample.get('perf_context', '')
    new_perf_context = ''

    if perf_context:
        perf_lines = perf_context.split('\n')
        # 找最后一个 M 开头的行
        for line in reversed(perf_lines):
            if line.startswith('M'):
                new_perf_context = line
                break

    # 计算新设计的 token 数
    header_tokens = estimate_token_count(sample.get('score_header', ''))
    new_score_snip_tokens = estimate_token_count(new_score_snip)
    new_perf_context_tokens = estimate_token_count(new_perf_context)
    perf_target_tokens = estimate_token_count(sample.get('perf_target', ''))

    new_input_length = header_tokens + new_score_snip_tokens + new_perf_context_tokens
    new_total_length = new_input_length + perf_target_tokens

    # 计算节约的长度
    old_input_length = sample_data.get('input_length', 0)
    saved_tokens = old_input_length - new_input_length

    return {
        'new_score_snip_tokens': new_score_snip_tokens,
        'new_perf_context_tokens': new_perf_context_tokens,
        'new_input_length': new_input_length,
        'new_total_length': new_total_length,
        'saved_tokens': saved_tokens,
        'reduction_ratio': saved_tokens / old_input_length if old_input_length > 0 else 0
    }


def print_statistics(stats: dict, title: str):
    """打印统计信息"""
    print(f"\n{'='*80}")
    print(f"{title}")
    print(f"{'='*80}")

    for component, values in stats.items():
        if not values:
            continue
        arr = np.array(values)
        print(f"\n{component}:")
        print(f"  Mean:   {arr.mean():.1f}")
        print(f"  Median: {np.median(arr):.1f}")
        print(f"  Std:    {arr.std():.1f}")
        print(f"  Min:    {arr.min()}")
        print(f"  Max:    {arr.max()}")
        print(f"  P50:    {np.percentile(arr, 50):.1f}")
        print(f"  P90:    {np.percentile(arr, 90):.1f}")
        print(f"  P95:    {np.percentile(arr, 95):.1f}")
        print(f"  P99:    {np.percentile(arr, 99):.1f}")


def print_coverage_analysis(lengths: list, thresholds: list = [2048, 3096, 4096]):
    """分析不同 max_length 的覆盖率"""
    print(f"\n{'='*80}")
    print("Coverage Analysis (% of samples within max_length)")
    print(f"{'='*80}")

    total = len(lengths)
    for threshold in thresholds:
        within = sum(1 for l in lengths if l <= threshold)
        coverage = within / total * 100
        print(f"  max_length={threshold}: {within}/{total} ({coverage:.2f}%)")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze phrase_epr token length distribution'
    )
    parser.add_argument('--input', type=Path, required=True,
                        help='Path to phrase_epr.jsonl file')
    parser.add_argument('--estimate-new-design', action='store_true',
                        help='Estimate new design token lengths')

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} does not exist")
        return

    print(f"Analyzing {args.input}...")
    result = analyze_current_design(args.input)

    print(f"\nTotal samples: {len(result['samples'])}")

    # 按 task_type 分组统计
    by_task_type = defaultdict(lambda: defaultdict(list))
    for sample in result['samples']:
        task_type = sample['task_type']
        for key in ['header', 'score_snip', 'perf_context', 'perf_target', 'input_length', 'total_length']:
            by_task_type[task_type][key].append(sample[key])

    # 打印当前设计的统计
    print_statistics(result['component_stats'], "Current Design - Overall Statistics")

    for task_type in ['coldstart', 'main', 'ending']:
        if task_type in by_task_type:
            print_statistics(by_task_type[task_type], f"Current Design - {task_type.upper()}")

    # 覆盖率分析
    print_coverage_analysis(result['component_stats']['total_length'])

    # 估计新设计
    if args.estimate_new_design:
        print(f"\n{'='*80}")
        print("Estimating New Design...")
        print(f"{'='*80}")

        new_design_stats = defaultdict(list)

        for sample_data in tqdm(result['samples'], desc="Estimating new design"):
            # 将完整的 sample_data 传递给估计函数
            new_est = estimate_new_design_length(sample_data)

            for key, value in new_est.items():
                new_design_stats[key].append(value)

        print_statistics({
            'new_input_length': new_design_stats['new_input_length'],
            'new_total_length': new_design_stats['new_total_length'],
            'saved_tokens': new_design_stats['saved_tokens']
        }, "New Design - Estimated Statistics")

        # 新设计的覆盖率分析
        print_coverage_analysis(new_design_stats['new_total_length'])

        # 节约比例分析
        reduction_ratios = new_design_stats['reduction_ratio']
        print(f"\n{'='*80}")
        print("Token Reduction Analysis")
        print(f"{'='*80}")
        print(f"  Mean reduction: {np.mean(reduction_ratios)*100:.1f}%")
        print(f"  Median reduction: {np.median(reduction_ratios)*100:.1f}%")
        print(f"  Min reduction: {np.min(reduction_ratios)*100:.1f}%")
        print(f"  Max reduction: {np.max(reduction_ratios)*100:.1f}%")


if __name__ == '__main__':
    main()
