#!/usr/bin/env python3
"""
从已生成的 language learning SFT 数据中采样 ~300M token 第一版（扩大 3x）。

采样策略：
  measure_score_lang_continuation: 全量（覆盖所有可用数据）
  phrase_score_lang_continuation:  全量（覆盖所有可用数据）
  measure_score_lang_mask:         360k  (120k * 3)
  phrase_score_lang_mask:          153k  (51k * 3)
  measure_perf_lang_continuation:  927k  (309k * 3)
  measure_perf_lang_mask:          945k  (315k * 3)
"""

import json
import random
import argparse
from pathlib import Path

random.seed(42)

# 使用 None 表示全量采样（覆盖所有可用数据）
TARGETS = {
    'measure_score_lang_continuation': None,   # 全量 ~638k
    'measure_score_lang_mask':         360_000,  # 120k * 3
    'phrase_score_lang_continuation':  None,   # 全量 ~156k
    'phrase_score_lang_mask':          153_000,  # 51k * 3
    'measure_perf_lang_continuation':  927_000,  # 309k * 3
    'measure_perf_lang_mask':          945_000,  # 315k * 3
}

FILE_MAP = {
    'measure_score_lang_continuation': 'measure-based/measure_score_lang_continuation.jsonl',
    'measure_score_lang_mask':         'measure-based/measure_score_lang_mask.jsonl',
    'phrase_score_lang_continuation':  'phrase-based/phrase_score_lang_continuation.jsonl',
    'phrase_score_lang_mask':          'phrase-based/phrase_score_lang_mask.jsonl',
    'measure_perf_lang_continuation':  'measure-based/measure_perf_lang_continuation.jsonl',
    'measure_perf_lang_mask':          'measure-based/measure_perf_lang_mask.jsonl',
}


def sample_file(src: Path, n: int | None, dest: Path):
    """Stream-read a JSONL, reservoir-sample n lines, write to dest. None = all."""
    # Count total lines first
    total = 0
    with open(src) as f:
        for _ in f:
            total += 1

    if n is None or n >= total:
        # Just copy
        import shutil
        shutil.copy2(src, dest)
        print(f"  {src.name}: all {total:,} samples (full copy)")
        return total

    # Reservoir sampling
    reservoir = []
    with open(src) as f:
        for i, line in enumerate(f):
            if i < n:
                reservoir.append(line)
            else:
                j = random.randint(0, i)
                if j < n:
                    reservoir[j] = line

    random.shuffle(reservoir)

    with open(dest, 'w') as f:
        f.writelines(reservoir)
    print(f"  {src.name}: sampled {n:,} from {total:,} lines")
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_dir', type=str, default='sft_data',
                        help='Directory containing generated JSONL files')
    parser.add_argument('--output_dir', type=str, default='sft_data_sampled',
                        help='Output directory for sampled data')
    parser.add_argument('--targets', type=str, nargs='*', default=None,
                        help='Override target counts: task1=count task2=count ...')
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Language Learning SFT Data Sampling (300M tokens)")
    print("=" * 60)

    total_samples = 0
    total_est_tokens = 0

    # Rough avg tokens per sample (from profiling 10k samples each)
    AVG_TOKENS = {
        'measure_score_lang_continuation': 82,
        'measure_score_lang_mask':         101,
        'phrase_score_lang_continuation':  213,
        'phrase_score_lang_mask':          234,
        'measure_perf_lang_continuation':  107,
        'measure_perf_lang_mask':          102,
    }

    for task_name, rel_path in FILE_MAP.items():
        src = input_dir / rel_path
        if not src.exists():
            print(f"\n  WARNING: {src} not found, skipping {task_name}")
            continue

        target_n = TARGETS[task_name]
        dest = output_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        n = sample_file(src, target_n, dest)
        est_tokens = n * AVG_TOKENS[task_name]
        total_samples += n
        total_est_tokens += est_tokens
        label = f"all {n:,}" if target_n is None else f"{target_n:,}"
        print(f"    ({label} / est tokens: {est_tokens/1_000_000:.1f}M)")

    print(f"\n{'=' * 60}")
    print(f"Total samples: {total_samples:,}")
    print(f"Est total tokens: {total_est_tokens/1_000_000:.1f}M")
    print(f"Output: {output_dir}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
