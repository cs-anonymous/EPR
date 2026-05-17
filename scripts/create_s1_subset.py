#!/usr/bin/env python3
"""Create S1 training subset from S-train.

Requirements:
1. Include all ASAP performance samples from S-train.
2. Ensure every train performance has at least one sample in each available
   performance-level task.
3. Use all score_lang_continuation samples.
4. Target score language : performance language = 2 : 8.
5. Keep continuation : mask close to 1 : 1.
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
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
]

PERFORMANCE_TASKS = [
    "measure_perf_lang_continuation",
    "measure_perf_lang_mask",
]

PERF_LANG_TASKS = [
    "measure_perf_lang_continuation",
    "measure_perf_lang_mask",
]

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
    parser.add_argument("--train-metadata", default="sft_data/core-s-train/metadata_train.csv")
    parser.add_argument("--input-dir", default="sft_data/core-s-train")
    parser.add_argument("--output-dir", default="sft_data/core-s1")
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
    print(f"ASAP performances: {len(asap_perf_pieces):,}")
    print(f"Total performances: {len(train_perf_pieces):,}")

    print("\nPhase 1: Indexing samples...")
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

    print("\nPhase 2: Selecting samples...")
    selected_samples = defaultdict(list)
    selected_line_sets = defaultdict(set)

    def add_line(task_name: str, line: str) -> bool:
        if line in selected_line_sets[task_name]:
            return False
        selected_line_sets[task_name].add(line)
        selected_samples[task_name].append(line)
        return True

    print("Step 1: Including all ASAP performance-level samples...")
    asap_counts = defaultdict(int)
    for perf_piece in tqdm(asap_perf_pieces, desc="ASAP samples"):
        for task_name, lines in perf_task_samples.get(perf_piece, {}).items():
            for line in lines:
                if add_line(task_name, line):
                    asap_counts[task_name] += 1

    print("  ASAP samples by task:")
    for task_name in sorted(asap_counts):
        print(f"    {task_name}: {asap_counts[task_name]:,}")

    print("\nStep 2: Including all score_lang_continuation samples...")
    for task_name in SCORE_LANG_CONT_TASKS:
        for _, line in tqdm(task_samples.get(task_name, []), desc=f"All {task_name}"):
            add_line(task_name, line)

    print("\nStep 3: Ensuring per-performance task coverage...")
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

    print("  Coverage samples added:")
    for task_name in sorted(coverage_counts):
        print(f"    {task_name}: {coverage_counts[task_name]:,}")

    print("\nStep 4: Balancing score language masks...")
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

    print("\nStep 5: Balancing score:performance language to 2:8...")
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

    print("\nPhase 3: Writing output files...")
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

    covered_all = train_perf_pieces
    for task_name in PERFORMANCE_TASKS:
        covered = {
            piece_id for piece_id, task_map in perf_task_samples.items()
            if piece_id in train_perf_pieces and task_map.get(task_name)
        }
        selected_covered = {
            piece_id for piece_id, task_map in perf_task_samples.items()
            if piece_id in train_perf_pieces
            and any(line in selected_line_sets[task_name] for line in task_map.get(task_name, []))
        }
        covered_all = covered_all & selected_covered
        print(f"Coverage {task_name}: {len(selected_covered):,}/{len(covered):,} available performances")

    print(f"\n{'='*80}")
    print("S1 Subset Statistics:")
    print(f"{'='*80}")
    print(f"Total samples: {total_samples:,}")
    print(f"Performances covered in all performance-level tasks: {len(covered_all):,}/{len(train_perf_pieces):,}")
    print(f"\nLanguage type distribution:")
    print(f"  Score language:       {score_lang_total:,} ({100*score_lang_total/(score_lang_total+perf_lang_total):.1f}%)")
    print(f"  Performance language: {perf_lang_total:,} ({100*perf_lang_total/(score_lang_total+perf_lang_total):.1f}%)")
    print(f"\nTask type distribution:")
    print(f"  Continuation: {continuation_total:,} ({100*continuation_total/(continuation_total+mask_total):.1f}%)")
    print(f"  Mask:         {mask_total:,} ({100*mask_total/(continuation_total+mask_total):.1f}%)")
    print(f"\nCounts saved to: {counts_path}")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
