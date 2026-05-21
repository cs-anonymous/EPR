#!/usr/bin/env python3
"""Generate full EPR SFT dataset with train/val/test splits."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tokens import add_lm_midi_tokens


TASKS = ["measure_epr", "phrase_epr"]
TASK_TYPES = ["coldstart", "main", "ending"]
COUNT_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]


def run_generate(metadata_path: Path, output_dir: Path, task: str) -> None:
    """Run generate_sft_data.py for a specific task."""
    cmd = [
        sys.executable,
        str(ROOT / "generate_sft_data.py"),
        "--metadata",
        str(metadata_path),
        "--base_dir",
        str(ROOT),
        "--output_dir",
        str(output_dir),
        "--task",
        task,
        "--dataset-filter",
        "core-s",
    ]
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def add_split_field(input_path: Path, output_dir: Path, task: str, metadata_path: Path) -> dict[str, int]:
    """Add split field to generated JSONL and split by task_type and split."""
    # Load metadata to get split info
    split_map = {}
    with metadata_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            perf_path = row.get("performance_tsv_path", "")
            if perf_path:
                # Extract piece_id from performance_tsv_path
                piece_id = perf_path.replace("PianoCoReS/miditsv/", "").replace(".tsv", "")
                split_map[piece_id] = row.get("split", "train")

    # Process JSONL file
    output_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    counts = defaultdict(lambda: defaultdict(int))

    try:
        # Open output files for each task_type and split combination
        for task_type in TASK_TYPES:
            for split in ["train", "val", "test"]:
                key = f"{task_type}_{split}"
                handles[key] = (output_dir / f"{task}_{task_type}_{split}.jsonl").open("w", encoding="utf-8")

        # Read input and distribute to appropriate files
        with input_path.open(encoding="utf-8") as f:
            for line in tqdm(f, desc=f"Processing {task}"):
                if not line.strip():
                    continue

                record = json.loads(line)
                piece_id = record.get("piece_id", "")
                task_type = record.get("task_type", "main")

                # Determine split
                split = split_map.get(piece_id, "train")

                # Add split field to record
                record["split"] = split

                # Write to appropriate file
                key = f"{task_type}_{split}"
                if key in handles:
                    handles[key].write(json.dumps(record, ensure_ascii=False) + "\n")
                    counts[task_type][split] += 1

    finally:
        for handle in handles.values():
            handle.close()

    return dict(counts)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    """Compute token lengths for a list of texts."""
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def record_text(record: dict, fields: list[str] = COUNT_FIELDS) -> str:
    """Concatenate record fields into a single text."""
    return " ".join(str(record.get(field, "")) for field in fields)


def percentiles(values: list[int]) -> dict[str, float | int]:
    """Compute percentile statistics."""
    arr = np.array(values, dtype=np.int64)
    if arr.size == 0:
        return {}
    return {
        "count": int(arr.size),
        "mean": float(arr.mean()),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": int(arr.max()),
    }


def analyze_files(tokenizer, files: list[Path], batch_size: int) -> dict:
    """Analyze token distributions across files."""
    lengths_by_split: dict[str, list[int]] = defaultdict(list)
    lengths_by_task_type: dict[str, list[int]] = defaultdict(list)
    component_lengths: dict[str, list[int]] = defaultdict(list)

    for path in files:
        if not path.exists():
            continue

        # Extract split and task_type from filename
        # Format: {task}_{task_type}_{split}.jsonl
        stem = path.stem
        parts = stem.rsplit("_", 2)
        if len(parts) == 3:
            task_type = parts[1]
            split = parts[2]
        else:
            continue

        with path.open(encoding="utf-8") as f:
            records = []
            for line in f:
                if not line.strip():
                    continue
                records.append(json.loads(line))

                if len(records) >= batch_size:
                    flush_records(tokenizer, records, split, task_type,
                                lengths_by_split, lengths_by_task_type, component_lengths)
                    records = []

            flush_records(tokenizer, records, split, task_type,
                        lengths_by_split, lengths_by_task_type, component_lengths)

    all_lengths = [v for values in lengths_by_split.values() for v in values]
    summary = {
        "overall": percentiles(all_lengths),
        "by_split": {split: percentiles(values) for split, values in lengths_by_split.items()},
        "by_task_type": {tt: percentiles(values) for tt, values in lengths_by_task_type.items()},
        "components": {field: percentiles(values) for field, values in component_lengths.items()},
    }

    return summary


def flush_records(
    tokenizer,
    records: list[dict],
    split: str,
    task_type: str,
    lengths_by_split: dict[str, list[int]],
    lengths_by_task_type: dict[str, list[int]],
    component_lengths: dict[str, list[int]],
) -> None:
    """Process a batch of records and update statistics."""
    if not records:
        return

    texts = [record_text(record) for record in records]
    lengths = token_lengths(tokenizer, texts)

    lengths_by_split[split].extend(lengths)
    lengths_by_task_type[task_type].extend(lengths)

    for field in COUNT_FIELDS:
        component_lengths[field].extend(
            token_lengths(tokenizer, [str(record.get(field, "")) for record in records])
        )


def check_coverage(stats: dict, max_length: int) -> dict:
    """Check what percentage of samples fit within max_length."""
    overall = stats.get("overall", {})
    count = overall.get("count", 0)
    if count == 0:
        return {"max_length": max_length, "coverage": 0.0, "truncated": 0}

    # Estimate coverage based on percentiles
    p95 = overall.get("p95", 0)
    p99 = overall.get("p99", 0)

    if max_length >= p99:
        coverage = 99.0
    elif max_length >= p95:
        # Linear interpolation between p95 and p99
        coverage = 95.0 + 4.0 * (max_length - p95) / (p99 - p95)
    else:
        # Rough estimate
        coverage = 95.0 * max_length / p95 if p95 > 0 else 0.0

    truncated = int(count * (100 - coverage) / 100)

    return {
        "max_length": max_length,
        "coverage_pct": round(coverage, 2),
        "truncated_samples": truncated,
        "avg_padding_ratio": round((max_length - overall.get("mean", 0)) / max_length, 3) if max_length > 0 else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoReS/metadata.csv"))
    parser.add_argument("--output-root", type=Path, default=Path("PianoCoReS/Corpora"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--skip-generation", action="store_true", help="Skip data generation, only analyze")
    args = parser.parse_args()

    if not args.skip_generation:
        print("Generating full EPR SFT data...")
        raw_root = args.output_root / "raw_full"
        raw_root.mkdir(parents=True, exist_ok=True)

        for task in TASKS:
            print(f"\nGenerating {task}...")
            run_generate(args.metadata, raw_root, task)
    else:
        raw_root = args.output_root / "raw_full"

    print("\nAdding split fields and organizing data...")
    raw_paths = {
        "measure_epr": raw_root / "measure-based" / "measure_epr.jsonl",
        "phrase_epr": raw_root / "phrase-based" / "phrase_epr.jsonl",
    }

    split_counts = {}
    for task, raw_path in raw_paths.items():
        if not raw_path.exists():
            print(f"Warning: {raw_path} not found, skipping")
            continue

        task_dir = args.output_root / f"{task}_sft_full"
        print(f"Processing {task} -> {task_dir}")
        split_counts[task] = add_split_field(raw_path, task_dir, task, args.metadata)

    print("\nLoading tokenizer with LM-MIDI vocabulary...")
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    added = add_lm_midi_tokens(tokenizer)
    print(f"LM-MIDI tokens added: {added}")

    print("\nAnalyzing token distributions...")
    summary = {
        "metadata": str(args.metadata),
        "tokenizer": str(args.tokenizer),
        "split_counts": split_counts,
        "tasks": {},
    }

    for task in TASKS:
        task_dir = args.output_root / f"{task}_sft_full"
        if not task_dir.exists():
            continue

        files = list(task_dir.glob(f"{task}_*.jsonl"))
        print(f"Analyzing {len(files)} files for {task}...")
        summary["tasks"][task] = analyze_files(tokenizer, files, args.batch_size)

    # Add coverage analysis for recommended max_lengths
    recommended_max_lengths = {
        "measure_epr": 768,
        "phrase_epr": 1536,
    }

    for task, max_len in recommended_max_lengths.items():
        if task in summary["tasks"]:
            summary["tasks"][task]["coverage_analysis"] = check_coverage(
                summary["tasks"][task], max_len
            )

    # Save summary
    summary_path = args.output_root / "epr_token_distribution_full.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Print summary
    print("\n" + "=" * 80)
    print("FULL DATASET STATISTICS")
    print("=" * 80)

    for task, task_summary in summary["tasks"].items():
        overall = task_summary["overall"]
        by_split = task_summary.get("by_split", {})
        coverage = task_summary.get("coverage_analysis", {})

        print(f"\n{task.upper()}:")
        print(f"  Total samples: {overall.get('count', 0):,}")
        print(f"  Mean length: {overall.get('mean', 0):.1f} tokens")
        print(f"  p50: {overall.get('p50', 0):.0f}, p95: {overall.get('p95', 0):.0f}, p99: {overall.get('p99', 0):.0f}, max: {overall.get('max', 0):,}")

        print(f"\n  Split distribution:")
        for split in ["train", "val", "test"]:
            split_stats = by_split.get(split, {})
            count = split_stats.get("count", 0)
            mean = split_stats.get("mean", 0)
            print(f"    {split}: {count:,} samples (mean: {mean:.1f} tokens)")

        if coverage:
            print(f"\n  Coverage at max_length={coverage['max_length']}:")
            print(f"    Coverage: {coverage['coverage_pct']:.1f}%")
            print(f"    Truncated: {coverage['truncated_samples']:,} samples")
            print(f"    Avg padding: {coverage['avg_padding_ratio']:.1%}")

    print(f"\n{'=' * 80}")
    print(f"Summary saved to: {summary_path}")
    print(f"Data saved to: {args.output_root}/{{measure,phrase}}_epr_sft_full/")


if __name__ == "__main__":
    main()
