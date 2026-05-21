#!/usr/bin/env python3
"""Quick sampled analysis of EPR SFT data."""

import json
import random
import sys
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.lm_midi_tokens import add_lm_midi_tokens


def analyze_jsonl_sampled(path: Path, tokenizer, sample_size: int = 10000) -> dict:
    """Analyze a JSONL file with sampling for large files."""
    # Count total lines first
    with path.open(encoding="utf-8") as f:
        total_lines = sum(1 for _ in f)

    # If file is small, analyze all
    if total_lines <= sample_size:
        return analyze_jsonl_full(path, tokenizer)

    # Sample lines
    sample_indices = set(random.sample(range(total_lines), sample_size))
    lengths = []

    with path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx not in sample_indices:
                continue
            if not line.strip():
                continue
            record = json.loads(line)
            text = " ".join([
                str(record.get("instruction", "")),
                str(record.get("score_header", "")),
                str(record.get("score_snip", "")),
                str(record.get("perf_context", "")),
                str(record.get("perf_target", "")),
            ])
            encoded = tokenizer(text, add_special_tokens=False, return_attention_mask=False)
            lengths.append(len(encoded["input_ids"]))

    arr = np.array(lengths, dtype=np.int64)
    return {
        "count": total_lines,
        "sampled": len(lengths),
        "mean": float(arr.mean()),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": int(arr.max()),
    }


def analyze_jsonl_full(path: Path, tokenizer) -> dict:
    """Analyze all lines in a JSONL file."""
    lengths = []
    count = 0

    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            text = " ".join([
                str(record.get("instruction", "")),
                str(record.get("score_header", "")),
                str(record.get("score_snip", "")),
                str(record.get("perf_context", "")),
                str(record.get("perf_target", "")),
            ])
            encoded = tokenizer(text, add_special_tokens=False, return_attention_mask=False)
            lengths.append(len(encoded["input_ids"]))
            count += 1

    arr = np.array(lengths, dtype=np.int64)
    return {
        "count": count,
        "sampled": count,
        "mean": float(arr.mean()),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": int(arr.max()),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--sample-size", type=int, default=10000)
    args = parser.parse_args()

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    add_lm_midi_tokens(tokenizer)

    for task in ["measure_epr", "phrase_epr"]:
        task_dir = args.data_dir / f"{task}_sft_full"
        if not task_dir.exists():
            print(f"Skipping {task} (directory not found)")
            continue

        print(f"\n{task.upper()}:")
        files = sorted(task_dir.glob(f"{task}_*.jsonl"))

        for file in files:
            print(f"  Analyzing {file.name}...", end=" ", flush=True)
            stats = analyze_jsonl_sampled(file, tokenizer, args.sample_size)
            if stats['count'] == stats['sampled']:
                print(f"{stats['count']:,} samples, mean={stats['mean']:.1f}, p95={stats['p95']:.0f}")
            else:
                print(f"{stats['count']:,} samples (sampled {stats['sampled']:,}), mean={stats['mean']:.1f}, p95={stats['p95']:.0f}")


if __name__ == "__main__":
    main()
