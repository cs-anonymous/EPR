#!/usr/bin/env python3
"""Shuffle epr_Astar raw and split into shuffled + train rounds 1/2/3."""

import json
import random
import sys
from collections import Counter
from pathlib import Path

DEFAULT_SEED = 43  # different seed from S (42)


def read_jsonl(path: Path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list) -> int:
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            count += 1
    return count


def split_evenly(records: list, n: int, prefix: str):
    base, extra = divmod(len(records), n)
    start = 0
    for idx in range(n):
        size = base + (1 if idx < extra else 0)
        yield f"{prefix}{idx + 1}", records[start: start + size]
        start += size


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    raw_path = Path("data/CorporaV2/sft/epr_Astar_4096_raw.jsonl")
    output_dir = raw_path.parent

    # 1. Read raw
    print(f"Reading {raw_path}...")
    records = read_jsonl(raw_path)
    print(f"  Total: {len(records)} records")

    splits = Counter(r.get("split") for r in records)
    print(f"  Splits: {dict(splits)}")

    # 2. Shuffle (Astar only)
    print(f"Shuffling with seed={seed}...")
    rng = random.Random(seed)
    rng.shuffle(records)

    shuffled_path = output_dir / "epr_Astar_4096_shuffled.jsonl"
    count = write_jsonl(shuffled_path, records)
    print(f"  Wrote {count} records -> {shuffled_path}")

    # 3. Split into rounds
    val_records = [r for r in records if r.get("split") == "val"][:2000]
    test_records = [r for r in records if r.get("split") == "test"]
    train_records = [r for r in records if r.get("split") == "train"]

    rounds_dir = output_dir / "sft_rounds_Astar"
    rounds_dir.mkdir(parents=True, exist_ok=True)

    summary = {}

    for name, part in split_evenly(train_records, 3, "train_Astar"):
        fpath = rounds_dir / f"{name}.jsonl"
        summary[f"{name}.jsonl"] = write_jsonl(fpath, part)
        print(f"  Wrote {len(part)} records -> {fpath}")

    summary["val.jsonl"] = write_jsonl(rounds_dir / "val.jsonl", val_records)
    print(f"  Wrote {len(val_records)} records -> {rounds_dir / 'val.jsonl'}")

    summary["test.jsonl"] = write_jsonl(rounds_dir / "test.jsonl", test_records)
    print(f"  Wrote {len(test_records)} records -> {rounds_dir / 'test.jsonl'}")

    # Summary
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v} samples")
    total = sum(summary.values())
    print(f"  total: {total}")


if __name__ == "__main__":
    main()
