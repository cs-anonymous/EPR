#!/usr/bin/env python3
"""Build phrase/measure-safe language_cpt corpus for A* performance data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_language_cpt_chunks import chunk_midi_tsv  # noqa: E402
from scripts.lm_midi_tokens import add_lm_midi_tokens  # noqa: E402


_WORKER_TOKENIZER = None


class TokenCounter:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def count(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])


def init_worker(tokenizer_path: str) -> None:
    global _WORKER_TOKENIZER
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
    add_lm_midi_tokens(tokenizer, mode="full")
    _WORKER_TOKENIZER = tokenizer


def process_source(task: tuple[str, str, int]) -> dict:
    source_path_str, split, max_tokens = task
    if _WORKER_TOKENIZER is None:
        raise RuntimeError("worker tokenizer is not initialized")
    source_path = Path(source_path_str)
    counter = TokenCounter(_WORKER_TOKENIZER)
    chunks = chunk_midi_tsv(source_path, counter, max_tokens)
    records = []
    for chunk_id, (text, num_tokens) in enumerate(chunks, 1):
        records.append({
            "task": "language_cpt",
            "corpus_type": "midi_tsv_no_header",
            "source": str(source_path),
            "source_split": split,
            "chunk_id": chunk_id,
            "text": text,
            "num_tokens": num_tokens,
        })
    return {
        "source": str(source_path),
        "source_split": split,
        "records": records,
    }


def build_astar_performance_corpus(
    metadata_path: Path,
    output_path: Path,
    tokenizer_path: str,
    max_tokens: int = 2048,
    workers: int = os.cpu_count() or 1,
) -> None:
    print("\nBuilding A* performance corpus...")
    print(f"  Metadata: {metadata_path}")
    print(f"  Output: {output_path}")
    print(f"  Tokenizer: {tokenizer_path} + full LM-MIDI (+797)")
    print(f"  Max tokens: {max_tokens}")
    print(f"  Workers: {workers}")

    meta = pd.read_csv(metadata_path)
    meta = meta[meta["tsv_path"].notna()]

    tasks: list[tuple[str, str, int]] = []
    missing = 0
    for _, row in meta.iterrows():
        tsv_path = ROOT / "PianoCoReS" / str(row["tsv_path"])
        if not tsv_path.exists():
            missing += 1
            continue
        tasks.append((str(tsv_path), str(row["split"]), max_tokens))

    print(f"  Found {len(meta)} metadata rows with TSV")
    print(f"  Existing TSV files: {len(tasks)}")
    if missing:
        print(f"  Missing TSV files: {missing}")

    if not tasks:
        raise RuntimeError("no TSV files found for A* metadata")

    if workers <= 1:
        init_worker(tokenizer_path)
        results = list(map(process_source, tasks))
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=init_worker,
            initargs=(tokenizer_path,),
        ) as executor:
            results = list(executor.map(process_source, tasks, chunksize=16))

    samples = []
    split_counts = Counter()
    source_counts = Counter()
    max_seen = 0
    all_tokens = 0
    for result in results:
        split_counts[result["source_split"]] += len(result["records"])
        source_counts[result["source"]] += len(result["records"])
        for record in result["records"]:
            max_seen = max(max_seen, record["num_tokens"])
            all_tokens += record["num_tokens"]
            samples.append(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"\n  Output samples: {len(samples):,}")
    print(f"  Source performances: {len(source_counts):,}")
    print(f"  Avg chunks/source: {len(samples) / max(1, len(source_counts)):.2f}")
    print(f"  Avg tokens: {all_tokens / max(1, len(samples)):.1f}")
    print(f"  Max tokens seen: {max_seen}")
    print(f"  File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    print("\n  Split distribution:")
    for split, count in split_counts.most_common():
        print(f"    {split}: {count:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("PianoCoReS/performance_Astar_metadata.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("PianoCoReS/CorporaV2/language_cpt/performance_Astar_midi.jsonl"),
    )
    parser.add_argument(
        "--tokenizer",
        type=str,
        default="Qwen3.5-4B",
        help="Base tokenizer path. Full LM-MIDI (+797) is added in-memory.",
    )
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    build_astar_performance_corpus(
        metadata_path=args.metadata,
        output_path=args.output,
        tokenizer_path=args.tokenizer,
        max_tokens=args.max_tokens,
        workers=args.workers,
    )

    print("\n✓ A* performance corpus generation complete!")


if __name__ == "__main__":
    main()
