#!/usr/bin/env python3
"""Merge S1 and S2 language SFT datasets and shuffle for training."""

import argparse
import json
import random
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1-dir", type=Path, default=Path("PianoCoReS/CoReS/language_sft_s1"))
    parser.add_argument("--s2-dir", type=Path, default=Path("PianoCoReS/CoReS/language_sft_s2"))
    parser.add_argument("--output", type=Path, default=Path("PianoCoReS/CoReS/language_sft_merged_shuffled.jsonl"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Loading S1 from {args.s1_dir}")
    s1_file = args.s1_dir / "sft_language_train.jsonl"
    s1_lines = []
    if s1_file.exists():
        with s1_file.open("r", encoding="utf-8") as f:
            s1_lines = [line for line in f if line.strip()]
    print(f"S1: {len(s1_lines):,} samples")

    print(f"Loading S2 from {args.s2_dir}")
    s2_file = args.s2_dir / "sft_language_train.jsonl"
    s2_lines = []
    if s2_file.exists():
        with s2_file.open("r", encoding="utf-8") as f:
            s2_lines = [line for line in f if line.strip()]
    print(f"S2: {len(s2_lines):,} samples")

    # Merge
    all_lines = s1_lines + s2_lines
    print(f"Total: {len(all_lines):,} samples")

    # Shuffle
    print(f"Shuffling with seed={args.seed}")
    rng = random.Random(args.seed)
    rng.shuffle(all_lines)

    # Write
    print(f"Writing to {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for line in all_lines:
            f.write(line)

    print(f"Done! Output: {args.output}")
    print(f"Total samples: {len(all_lines):,}")


if __name__ == "__main__":
    main()
