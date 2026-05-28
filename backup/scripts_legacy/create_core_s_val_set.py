#!/usr/bin/env python3
"""Create a CoRe-S validation subset by randomly sampling works.

Samples works randomly until the total number of samples approximately matches the test set.
Uses a fast estimation method based on performance counts.
"""
import argparse
import csv
import json
import random
from pathlib import Path

import pandas as pd
from tqdm import tqdm


TASK_FILES = [
    "measure_epr.jsonl",
    "phrase_epr.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
]


def core_s_star_mask(df: pd.DataFrame) -> pd.Series:
    """Filter for CoRe-S* subset (clean A* or ASAP)."""
    interpolation_ratio = (
        df["refined_performance_interpolated_note_count"]
        / df["refined_performance_note_count"]
    )
    asap = ~df["is_transcription"].astype(bool)
    clean_astar = (
        df["tier_a_star"].astype(bool)
        & (df["refined_recall"] >= 0.95)
        & (interpolation_ratio <= 0.05)
    )
    return clean_astar | asap


def work_key_frame(df: pd.DataFrame) -> pd.Series:
    """Extract (composer, composition, movement) tuples."""
    return df[["composer", "composition", "movement"]].fillna("").apply(tuple, axis=1)


def score_piece_id(score_abcx_path: str) -> str:
    """Convert score_abcx_path to piece_id format."""
    prefix = "PianoCoRe/score/"
    path = score_abcx_path
    if path.startswith(prefix):
        path = path[len(prefix):]
    if path.endswith("/score.abcx"):
        path = path[: -len("/score.abcx")]
    return f"{path}/score_aligned"


def performance_piece_id(perf_tsv_path: str) -> str:
    """Convert metadata performance_tsv_path to the JSONL piece_id format."""
    path = str(perf_tsv_path)
    if path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/"):]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/"):]
    if path.endswith(".tsv"):
        path = path[: -len(".tsv")]
    return path


def task_filter(sample: dict, task_name: str, val_perf_piece_ids: set, val_score_piece_ids: set) -> bool:
    """Check if sample belongs to validation set."""
    piece_id = sample.get("piece_id", "")
    if "score_lang" in task_name:
        return piece_id in val_score_piece_ids
    return piece_id in val_perf_piece_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", default="PianoCoRe/metadata.csv")
    parser.add_argument("--test-counts", default="sft_data/core-s-test/counts.csv")
    parser.add_argument("--test-metadata", default="sft_data/core-s-test/metadata_test.csv")
    parser.add_argument("--input-dir", default="sft_data/core-s")
    parser.add_argument("--output-dir", default="sft_data/core-s-val")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)

    # Load metadata
    metadata = pd.read_csv(args.metadata)
    s_star = metadata[core_s_star_mask(metadata)].copy()

    # Load test set and calculate samples per performance ratio
    test_counts = pd.read_csv(args.test_counts)
    target_n_samples = test_counts["kept_samples"].sum()
    test_metadata = pd.read_csv(args.test_metadata)
    test_keys = set(work_key_frame(test_metadata))

    # Estimate samples per performance from test set
    samples_per_perf = target_n_samples / len(test_metadata)

    print(f"Test set: {len(test_keys)} works, {len(test_metadata)} performances, {target_n_samples:,} samples")
    print(f"Estimated samples per performance: {samples_per_perf:.1f}")
    print(f"Target validation samples: {target_n_samples:,}")

    # Get all available work keys excluding test set
    all_keys = work_key_frame(s_star)
    available_keys = set(all_keys) - test_keys
    print(f"Available work keys (excluding test): {len(available_keys)}")

    # Group by work key and count performances per work
    work_perf_counts = s_star[all_keys.isin(available_keys)].groupby(
        work_key_frame(s_star[all_keys.isin(available_keys)])
    ).size().to_dict()

    # Estimate samples per work
    work_sample_estimates = {
        work_key: n_perfs * samples_per_perf
        for work_key, n_perfs in work_perf_counts.items()
    }

    # Randomly sample works until we reach target performance count (not sample count)
    # This is more reliable since sample count estimation can be off
    available_works = list(work_perf_counts.keys())
    random.shuffle(available_works)

    target_perfs = len(test_metadata)
    selected_keys = []
    total_perfs = 0
    for work_key in available_works:
        n_perfs = work_perf_counts[work_key]
        if total_perfs + n_perfs <= target_perfs * 1.5:  # Allow 50% overshoot
            selected_keys.append(work_key)
            total_perfs += n_perfs
            if total_perfs >= target_perfs:
                break

    total_estimated_samples = sum(work_sample_estimates[k] for k in selected_keys)

    selected_keys = set(selected_keys)
    print(f"Selected {len(selected_keys)} works with {total_perfs} performances (~{total_estimated_samples:,.0f} estimated samples)")

    # Filter metadata for selected works
    val_metadata = s_star[all_keys.isin(selected_keys)].copy()
    val_perf_ids = set(val_metadata["performance_id"].astype(str))
    val_perf_piece_ids = set(
        performance_piece_id(path)
        for path in val_metadata["performance_tsv_path"].dropna().astype(str)
    )
    val_score_piece_ids = set(
        score_piece_id(path)
        for path in val_metadata["score_abcx_path"].dropna().astype(str)
    )

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save validation metadata
    val_metadata.to_csv(output_dir / "metadata_val.csv", index=False)

    # Save selected work keys manifest
    selected_works = []
    for key in sorted(selected_keys):
        composer, composition, movement = key
        n_perfs = work_perf_counts[key]
        estimated_samples = work_sample_estimates[key]
        selected_works.append({
            "composer": composer,
            "composition": composition,
            "movement": movement,
            "n_performances": n_perfs,
            "estimated_samples": int(estimated_samples),
        })
    manifest_path = output_dir / "val_work_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["composer", "composition", "movement", "n_performances", "estimated_samples"])
        writer.writeheader()
        writer.writerows(selected_works)

    # Filter task files
    counts = []
    input_dir = Path(args.input_dir)
    for file_name in TASK_FILES:
        src = input_dir / file_name
        if not src.exists():
            print(f"Warning: {src} not found, skipping")
            continue
        dst = output_dir / file_name
        kept = 0
        total = 0
        task_name = file_name.removesuffix(".jsonl")
        with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
            for line in tqdm(fin, desc=f"Filter {file_name}"):
                total += 1
                sample = json.loads(line)
                if task_filter(sample, task_name, val_perf_piece_ids, val_score_piece_ids):
                    fout.write(line)
                    kept += 1
        counts.append({"file": file_name, "kept_samples": kept, "source_samples": total})

    # Save counts
    counts_path = output_dir / "counts.csv"
    with counts_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples", "source_samples"])
        writer.writeheader()
        writer.writerows(counts)

    # Check data source composition
    n_asap = (~val_metadata["is_transcription"].astype(bool)).sum()
    n_astar = (val_metadata["tier_a_star"].astype(bool)).sum()
    actual_total_samples = sum(row["kept_samples"] for row in counts)

    print(f"\nValidation set created:")
    print(f"  Selected work keys: {len(selected_keys)}")
    print(f"  Metadata rows: {len(val_metadata):,}")
    print(f"  Performance IDs: {len(val_perf_ids):,}")
    print(f"  Score piece IDs: {len(val_score_piece_ids):,}")
    print(f"  Actual total samples: {actual_total_samples:,} (target: {target_n_samples:,}, {100*actual_total_samples/target_n_samples:.1f}%)")
    print(f"  Data source: {n_asap} ASAP + {n_astar} A*")
    print(f"  Manifest: {manifest_path}")
    print(f"  Counts: {counts_path}")


if __name__ == "__main__":
    main()
