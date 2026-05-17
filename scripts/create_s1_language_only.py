#!/usr/bin/env python3
"""Create S1 language-only subset (6 Language Learning tasks, no EPR).

Requirements:
1. Include all ASAP performance-language samples from source.
2. Ensure every performance has at least one sample in each available
   performance-level task.
3. Use all score_lang_continuation samples.
4. Balance score_lang_mask to match score_lang_continuation count.
5. Target score language : performance language = 2 : 8.

EPR tasks (measure_epr, phrase_epr) are NOT included -- they belong to S2a.
"""
import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd
from tqdm import tqdm

TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]

PERFORMANCE_TASKS = [
    "measure_perf_lang_continuation",
    "measure_perf_lang_mask",
]

PERF_LANG_TASKS = PERFORMANCE_TASKS

SCORE_LANG_CONT_TASKS = [
    "measure_score_lang_continuation",
    "phrase_score_lang_continuation",
]

SCORE_LANG_MASK_TASKS = [
    "measure_score_lang_mask",
    "phrase_score_lang_mask",
]


def performance_piece_id(perf_tsv_path: str) -> str:
    path = str(perf_tsv_path)
    if path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/"):]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/"):]
    if path.endswith(".tsv"):
        path = path[: -len(".tsv")]
    return path


def is_score_lang_task(task_name: str) -> bool:
    return "score_lang" in task_name


def is_continuation_task(task_name: str) -> bool:
    return "continuation" in task_name


def sample_from_available(available: list, n: int, rng: random.Random) -> list:
    if n <= 0 or not available:
        return []
    if n >= len(available):
        return list(available)
    return rng.sample(available, n)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-metadata", required=True,
                        help="Path to metadata CSV")
    parser.add_argument("--input-dir", required=True,
                        help="Directory containing JSONL task files")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for selected samples")
    parser.add_argument("--label", default="S1",
                        help="Label for print output")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    input_dir = Path(args.input_dir)

    metadata = pd.read_csv(args.train_metadata)
    metadata = metadata[metadata["performance_tsv_path"].notna()].copy()
    metadata["performance_piece_id"] = metadata["performance_tsv_path"].astype(str).map(performance_piece_id)

    train_perf_pieces = set(metadata["performance_piece_id"])
    asap_perf_pieces = set(
        metadata[~metadata["is_transcription"].astype(bool)]["performance_piece_id"]
    )
    print(f"[{args.label}] ASAP performances: {len(asap_perf_pieces):,}")
    print(f"[{args.label}] Total performances: {len(train_perf_pieces):,}")

    print(f"\n[{args.label}] Phase 1: Indexing samples...")
    task_samples = defaultdict(list)
    perf_task_samples = defaultdict(lambda: defaultdict(list))

    for file_name in TASK_FILES:
        src = input_dir / file_name
        if not src.exists():
            print(f"Warning: {src} not found, skipping")
            continue
        task_name = file_name.removesuffix(".jsonl")
        with src.open("r", encoding="utf-8") as fin:
            for line in tqdm(fin, desc=f"Index {file_name}"):
                sample = json.loads(line)
                piece_id = sample.get("piece_id", "")
                task_samples[task_name].append((piece_id, line))
                if task_name in PERFORMANCE_TASKS:
                    perf_task_samples[piece_id][task_name].append(line)

    print(f"\n[{args.label}] Phase 2: Selecting samples...")
    selected_samples = defaultdict(list)
    selected_line_sets = defaultdict(set)

    def add_line(task_name: str, line: str) -> bool:
        if line in selected_line_sets[task_name]:
            return False
        selected_line_sets[task_name].add(line)
        selected_samples[task_name].append(line)
        return True

    print(f"[{args.label}] Step 1: Including all ASAP performance-level samples...")
    asap_counts = defaultdict(int)
    for perf_piece in tqdm(asap_perf_pieces, desc="ASAP samples"):
        for task_name, lines in perf_task_samples.get(perf_piece, {}).items():
            for line in lines:
                if add_line(task_name, line):
                    asap_counts[task_name] += 1

    print(f"  ASAP samples by task:")
    for task_name in sorted(asap_counts):
        print(f"    {task_name}: {asap_counts[task_name]:,}")

    print(f"\n[{args.label}] Step 2: Including all score_lang_continuation samples...")
    for task_name in SCORE_LANG_CONT_TASKS:
        for _, line in tqdm(task_samples.get(task_name, []), desc=f"All {task_name}"):
            add_line(task_name, line)

    print(f"\n[{args.label}] Step 3: Ensuring per-performance task coverage...")
    coverage_counts = defaultdict(int)
    for perf_piece in tqdm(train_perf_pieces, desc="Coverage samples"):
        for task_name in PERFORMANCE_TASKS:
            lines = perf_task_samples.get(perf_piece, {}).get(task_name, [])
            if not lines:
                continue
            if any(line in selected_line_sets[task_name] for line in lines):
                continue
            if add_line(task_name, rng.choice(lines)):
                coverage_counts[task_name] += 1

    print(f"  Coverage samples added:")
    for task_name in sorted(coverage_counts):
        print(f"    {task_name}: {coverage_counts[task_name]:,}")

    print(f"\n[{args.label}] Step 4: Balancing score language masks...")
    score_cont = sum(len(selected_samples[t]) for t in SCORE_LANG_CONT_TASKS)
    score_mask = sum(len(selected_samples[t]) for t in SCORE_LANG_MASK_TASKS)
    needed_score_mask = max(0, score_cont - score_mask)
    if needed_score_mask:
        per_task = {
            "measure_score_lang_mask": needed_score_mask // 2,
            "phrase_score_lang_mask": needed_score_mask - needed_score_mask // 2,
        }
        for task_name, n_to_add in per_task.items():
            available = [
                line
                for _, line in task_samples.get(task_name, [])
                if line not in selected_line_sets[task_name]
            ]
            sampled = sample_from_available(available, n_to_add, rng)
            for line in sampled:
                add_line(task_name, line)
            print(f"    Added {len(sampled):,} samples to {task_name}")

    print(f"\n[{args.label}] Step 5: Balancing score:performance language to 2:8...")
    score_lang_total = sum(
        len(lines)
        for task_name, lines in selected_samples.items()
        if is_score_lang_task(task_name)
    )
    perf_lang_total = sum(len(selected_samples[t]) for t in PERF_LANG_TASKS)
    target_perf_lang_total = int(score_lang_total * 4)
    needed_perf_lang = max(0, target_perf_lang_total - perf_lang_total)
    print(f"  Score language: {score_lang_total:,}")
    print(f"  Current performance language: {perf_lang_total:,}")
    print(f"  Target performance language: {target_perf_lang_total:,}")
    print(f"  Need to add: {needed_perf_lang:,}")

    if needed_perf_lang:
        cont_total = sum(len(selected_samples[t]) for t in selected_samples if is_continuation_task(t))
        mask_total = sum(len(selected_samples[t]) for t in selected_samples if "mask" in t)
        target_cont_add = max(0, (cont_total + mask_total + needed_perf_lang) // 2 - cont_total)
        target_mask_add = needed_perf_lang - target_cont_add

        plan = {
            "measure_perf_lang_continuation": target_cont_add,
            "measure_perf_lang_mask": target_mask_add,
        }
        for task_name, n_to_add in plan.items():
            available = [
                line
                for _, line in task_samples.get(task_name, [])
                if line not in selected_line_sets[task_name]
            ]
            sampled = sample_from_available(available, n_to_add, rng)
            for line in sampled:
                add_line(task_name, line)
            print(f"    Added {len(sampled):,} samples to {task_name}")

    print(f"\n[{args.label}] Phase 3: Writing output files...")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    counts = []
    for file_name in TASK_FILES:
        task_name = file_name.removesuffix(".jsonl")
        samples = selected_samples.get(task_name, [])
        dst = output_dir / file_name
        with dst.open("w", encoding="utf-8") as fout:
            for line in samples:
                fout.write(line)
        counts.append({"file": file_name, "kept_samples": len(samples)})
        print(f"  {file_name}: {len(samples):,} samples")

    counts_path = output_dir / "counts.csv"
    with counts_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples"])
        writer.writeheader()
        writer.writerows(counts)

    total_samples = sum(row["kept_samples"] for row in counts)
    score_lang_total = sum(row["kept_samples"] for row in counts if "score_lang" in row["file"])
    perf_lang_total = sum(row["kept_samples"] for row in counts if "perf_lang" in row["file"])
    continuation_total = sum(row["kept_samples"] for row in counts if "continuation" in row["file"])
    mask_total = sum(row["kept_samples"] for row in counts if "mask" in row["file"])

    print(f"\n{'='*80}")
    print(f"[{args.label}] Subset Statistics:")
    print(f"{'='*80}")
    print(f"Total samples: {total_samples:,}")
    print(f"\nLanguage type distribution:")
    total_lang = score_lang_total + perf_lang_total
    if total_lang > 0:
        print(f"  Score language:       {score_lang_total:,} ({100*score_lang_total/total_lang:.1f}%)")
        print(f"  Performance language: {perf_lang_total:,} ({100*perf_lang_total/total_lang:.1f}%)")
    print(f"\nTask type distribution:")
    total_cm = continuation_total + mask_total
    if total_cm > 0:
        print(f"  Continuation: {continuation_total:,} ({100*continuation_total/total_cm:.1f}%)")
        print(f"  Mask:         {mask_total:,} ({100*mask_total/total_cm:.1f}%)")
    print(f"\nCounts saved to: {counts_path}")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
