#!/usr/bin/env python3
"""Quick analysis of existing EPR SFT data with split info."""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.lm_midi_tokens import add_lm_midi_tokens


def analyze_jsonl(path: Path, tokenizer) -> dict:
    """Analyze a single JSONL file."""
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
            stats = analyze_jsonl(file, tokenizer)
            print(f"{stats['count']:,} samples, mean={stats['mean']:.1f}, p95={stats['p95']:.0f}")


if __name__ == "__main__":
    main()
