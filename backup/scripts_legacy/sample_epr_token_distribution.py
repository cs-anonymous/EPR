#!/usr/bin/env python3
"""Sample data EPR corpora and report LM-MIDI token distributions."""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tokens import add_lm_midi_tokens


TASKS = ["measure_epr", "phrase_epr"]
TASK_TYPES = ["coldstart", "main", "ending"]
COUNT_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]


def write_train_sample_metadata(
    metadata_path: Path,
    output_path: Path,
    max_performances: int,
    seed: int,
) -> int:
    with metadata_path.open(encoding="utf-8", newline="") as f:
        rows = [row for row in csv.DictReader(f) if row.get("split") == "train"]

    if max_performances > 0 and max_performances < len(rows):
        selected = random.Random(seed).sample(rows, max_performances)
    else:
        selected = rows
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(selected)
    return len(selected)


def run_generate(metadata_path: Path, output_dir: Path, task: str) -> None:
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


def split_by_task_type(input_path: Path, output_dir: Path, task: str) -> dict[str, int]:
    counts = {task_type: 0 for task_type in TASK_TYPES}
    handles = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for task_type in TASK_TYPES:
            handles[task_type] = (output_dir / f"{task}_{task_type}.jsonl").open("w", encoding="utf-8")
        with input_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                task_type = row.get("task_type", "main")
                if task_type not in handles:
                    task_type = "main"
                handles[task_type].write(line)
                counts[task_type] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return counts


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def record_text(record: dict, fields: list[str] = COUNT_FIELDS) -> str:
    return " ".join(str(record.get(field, "")) for field in fields)


def percentiles(values: list[int]) -> dict[str, float | int]:
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


def analyze_files(
    tokenizer,
    baseline_tokenizer,
    files: list[Path],
    batch_size: int,
) -> dict:
    lengths_by_task_type: dict[str, list[int]] = defaultdict(list)
    baseline_by_task_type: dict[str, list[int]] = defaultdict(list)
    component_lengths: dict[str, list[int]] = defaultdict(list)

    for path in files:
        task_type = path.stem.rsplit("_", 1)[-1]
        with path.open(encoding="utf-8") as f:
            records = []
            for line in f:
                if not line.strip():
                    continue
                records.append(json.loads(line))
                if len(records) >= batch_size:
                    flush_records(tokenizer, baseline_tokenizer, records, task_type, lengths_by_task_type, baseline_by_task_type, component_lengths)
                    records = []
            flush_records(tokenizer, baseline_tokenizer, records, task_type, lengths_by_task_type, baseline_by_task_type, component_lengths)

    all_lengths = [value for values in lengths_by_task_type.values() for value in values]
    all_baseline = [value for values in baseline_by_task_type.values() for value in values]
    summary = {
        "overall": percentiles(all_lengths),
        "by_task_type": {task_type: percentiles(values) for task_type, values in lengths_by_task_type.items()},
        "components": {field: percentiles(values) for field, values in component_lengths.items()},
    }
    if all_lengths and all_baseline:
        summary["baseline_without_lm_midi_added"] = percentiles(all_baseline)
        summary["lm_midi_to_baseline_ratio_mean"] = float(np.mean(np.array(all_lengths) / np.array(all_baseline)))
    return summary


def flush_records(
    tokenizer,
    baseline_tokenizer,
    records: list[dict],
    task_type: str,
    lengths_by_task_type: dict[str, list[int]],
    baseline_by_task_type: dict[str, list[int]],
    component_lengths: dict[str, list[int]],
) -> None:
    if not records:
        return
    texts = [record_text(record) for record in records]
    lengths_by_task_type[task_type].extend(token_lengths(tokenizer, texts))
    baseline_by_task_type[task_type].extend(token_lengths(baseline_tokenizer, texts))
    for field in COUNT_FIELDS:
        component_lengths[field].extend(token_lengths(tokenizer, [str(record.get(field, "")) for record in records]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("data/metadata.csv"))
    parser.add_argument("--output-root", type=Path, default=Path("backup/legacy_Corpora"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--max-performances", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="sample_epr_", dir=str(args.output_root)))
    try:
        sample_meta = temp_root / "metadata_train_sample.csv"
        selected = write_train_sample_metadata(args.metadata, sample_meta, args.max_performances, args.seed)
        print(f"Sampled train metadata rows: {selected:,}")

        raw_root = temp_root / "raw"
        for task in TASKS:
            run_generate(sample_meta, raw_root, task)

        output_files = []
        split_counts = {}
        raw_paths = {
            "measure_epr": raw_root / "measure-based" / "measure_epr.jsonl",
            "phrase_epr": raw_root / "phrase-based" / "phrase_epr.jsonl",
        }
        for task, raw_path in raw_paths.items():
            task_dir = args.output_root / f"{task}_sft"
            if task_dir.exists():
                shutil.rmtree(task_dir)
            split_counts[task] = split_by_task_type(raw_path, task_dir, task)
            output_files.extend(task_dir / f"{task}_{task_type}.jsonl" for task_type in TASK_TYPES)

        print("Loading tokenizer with LM-MIDI vocabulary...")
        tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
        added = add_lm_midi_tokens(tokenizer)
        baseline_tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
        print(f"LM-MIDI tokens added: {added}")

        summary = {
            "metadata": str(args.metadata),
            "sampled_train_rows": selected,
            "seed": args.seed,
            "tokenizer": str(args.tokenizer),
            "split_counts": split_counts,
            "tasks": {},
        }
        for task in TASKS:
            files = [args.output_root / f"{task}_sft" / f"{task}_{task_type}.jsonl" for task_type in TASK_TYPES]
            summary["tasks"][task] = analyze_files(tokenizer, baseline_tokenizer, files, args.batch_size)

        summary_path = args.output_root / "epr_token_distribution_sample.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        for task, task_summary in summary["tasks"].items():
            overall = task_summary["overall"]
            baseline = task_summary.get("baseline_without_lm_midi_added", {})
            ratio = task_summary.get("lm_midi_to_baseline_ratio_mean", 0.0)
            print(
                f"{task}: n={overall.get('count', 0):,}, mean={overall.get('mean', 0):.1f}, "
                f"p95={overall.get('p95', 0):.1f}, p99={overall.get('p99', 0):.1f}, "
                f"max={overall.get('max', 0):,}, baseline_mean={baseline.get('mean', 0):.1f}, "
                f"ratio={ratio:.3f}"
            )
        print(f"Wrote summary: {summary_path}")
    finally:
        if args.keep_temp:
            print(f"Kept temp dir: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
