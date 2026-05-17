#!/usr/bin/env python3
"""Create a CoRe-S training subset by excluding test and validation works.

The split unit is a score/work key: (composer, composition, movement).
All CoRe-S records NOT in test or validation sets are assigned to training.
"""
import argparse
import csv
import json
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


def task_filter(sample: dict, task_name: str, train_perf_piece_ids: set, train_score_piece_ids: set) -> bool:
    """Check if sample belongs to training set."""
    piece_id = sample.get("piece_id", "")
    if "score_lang" in task_name:
        return piece_id in train_score_piece_ids
    return piece_id in train_perf_piece_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", default="PianoCoRe/metadata.csv")
    parser.add_argument("--test-metadata", default="sft_data/core-s-test/metadata_test.csv")
    parser.add_argument("--val-metadata", default="sft_data/core-s-val/metadata_val.csv")
    parser.add_argument("--input-dir", default="sft_data/core-s")
    parser.add_argument("--output-dir", default="sft_data/core-s-train")
    args = parser.parse_args()

    # Load metadata
    metadata = pd.read_csv(args.metadata)
    s_star = metadata[core_s_star_mask(metadata)].copy()

    # Load test and validation work keys
    test_metadata = pd.read_csv(args.test_metadata)
    val_metadata = pd.read_csv(args.val_metadata)

    test_keys = set(work_key_frame(test_metadata))
    val_keys = set(work_key_frame(val_metadata))
    excluded_keys = test_keys | val_keys

    print(f"Test set work keys: {len(test_keys)}")
    print(f"Validation set work keys: {len(val_keys)}")
    print(f"Total excluded work keys: {len(excluded_keys)}")

    # Filter for training set (exclude test and val)
    all_keys = work_key_frame(s_star)
    train_metadata = s_star[~all_keys.isin(excluded_keys)].copy()
    train_perf_ids = set(train_metadata["performance_id"].astype(str))
    train_perf_piece_ids = set(
        performance_piece_id(path)
        for path in train_metadata["performance_tsv_path"].dropna().astype(str)
    )
    train_score_piece_ids = set(
        score_piece_id(path)
        for path in train_metadata["score_abcx_path"].dropna().astype(str)
    )

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save training metadata
    train_metadata.to_csv(output_dir / "metadata_train.csv", index=False)

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
                if task_filter(sample, task_name, train_perf_piece_ids, train_score_piece_ids):
                    fout.write(line)
                    kept += 1
        counts.append({"file": file_name, "kept_samples": kept, "source_samples": total})

    # Save counts
    counts_path = output_dir / "counts.csv"
    with counts_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples", "source_samples"])
        writer.writeheader()
        writer.writerows(counts)

    print(f"\nTraining set created:")
    print(f"  Training work keys: {len(set(all_keys) - excluded_keys)}")
    print(f"  Metadata rows: {len(train_metadata):,}")
    print(f"  Performance IDs: {len(train_perf_ids):,}")
    print(f"  Score piece IDs: {len(train_score_piece_ids):,}")
    print(f"  Counts: {counts_path}")


if __name__ == "__main__":
    main()
