#!/usr/bin/env python3
"""Shuffle one language SFT JSONL and split it into train/val files."""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path


def backup_if_exists(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    backup = path.with_name(path.name + ".bak")
    if backup.exists() or backup.is_symlink():
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup)
        else:
            backup.unlink()
    shutil.move(str(path), str(backup))


def read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        return [line for line in f if line.strip()]


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.writelines(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("PianoCoReS/CoReS/language_sft_s2/sft_language_train.jsonl"),
    )
    parser.add_argument(
        "--shuffled-output",
        type=Path,
        default=Path("PianoCoReS/CoReS/language_sft_s2_shuffled.jsonl"),
    )
    parser.add_argument(
        "--train-output",
        type=Path,
        default=Path("PianoCoReS/CoReS/language_sft_s2_train.jsonl"),
    )
    parser.add_argument(
        "--val-output",
        type=Path,
        default=Path("PianoCoReS/CoReS/language_sft_s2_val.jsonl"),
    )
    parser.add_argument(
        "--val-alias-output",
        type=Path,
        default=Path("PianoCoReS/CoReS/language_sft_val_10k.jsonl"),
    )
    parser.add_argument("--val-size", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    lines = read_lines(args.input)
    print(f"Loaded {len(lines):,} rows from {args.input}")

    rng = random.Random(args.seed)
    rng.shuffle(lines)
    print(f"Shuffled with seed={args.seed}")

    val_size = min(args.val_size, len(lines))
    val_lines = lines[:val_size]
    train_lines = lines[val_size:]

    for path in [
        args.shuffled_output,
        args.train_output,
        args.val_output,
        args.val_alias_output,
    ]:
        backup_if_exists(path)

    write_lines(args.shuffled_output, lines)
    write_lines(args.train_output, train_lines)
    write_lines(args.val_output, val_lines)
    write_lines(args.val_alias_output, val_lines)

    print(f"Shuffled: {args.shuffled_output} ({len(lines):,} rows)")
    print(f"Train:    {args.train_output} ({len(train_lines):,} rows)")
    print(f"Val:      {args.val_output} ({len(val_lines):,} rows)")
    print(f"Alias:    {args.val_alias_output} ({len(val_lines):,} rows)")


if __name__ == "__main__":
    main()
