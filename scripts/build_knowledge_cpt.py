#!/usr/bin/env python3
"""Build knowledge-only CPT chunks for format and Seeker38 separately."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_language_cpt_chunks import build_corpus, write_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-dir", type=Path, default=Path("PianoCoReS/knowledge"))
    parser.add_argument("--out-dir", type=Path, default=Path("PianoCoReS/Corpora/language_cpt"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI-Full"))
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    format_items = [
        (path, "knowledge")
        for path in sorted((args.knowledge_dir / "format").glob("*.md"))
    ]
    seeker_items = [
        (path, "knowledge")
        for path in sorted((args.knowledge_dir / "Seeker38").glob("*.md"))
    ]

    print("=" * 60)
    print("Building Knowledge CPT Chunks")
    print("=" * 60)
    print(f"Knowledge dir: {args.knowledge_dir}")
    print(f"Output dir: {args.out_dir}")
    print(f"Tokenizer: {args.tokenizer}")
    print(f"Max tokens: {args.max_tokens}")
    print(f"Workers: {args.workers}")
    print(f"Format markdown files: {len(format_items)}")
    print(f"Seeker38 markdown files: {len(seeker_items)}")

    rows = []
    if format_items:
        rows.append(
            build_corpus(
                "knowledge_format",
                format_items,
                args.out_dir / "knowledge_format.jsonl",
                "markdown",
                args.tokenizer,
                args.max_tokens,
                min(args.workers, max(1, len(format_items))),
            )
        )
    if seeker_items:
        rows.append(
            build_corpus(
                "knowledge_Seeker38",
                seeker_items,
                args.out_dir / "knowledge_Seeker38.jsonl",
                "markdown",
                args.tokenizer,
                args.max_tokens,
                min(args.workers, max(1, len(seeker_items))),
            )
        )

    if not rows:
        print("No knowledge markdown files found.")
        return

    existing_rows = []
    summary_json = args.out_dir / "cpt_dataset_summary.json"
    if summary_json.exists():
        existing_rows = json.loads(summary_json.read_text(encoding="utf-8"))
        existing_rows = [
            row
            for row in existing_rows
            if row["corpus_type"] not in {"knowledge_format", "knowledge_Seeker38"}
        ]

    merged_rows = []
    order = ["aligned_abcx", "midi_tsv_no_header", "knowledge_format", "knowledge_Seeker38"]
    rows_by_type = {row["corpus_type"]: row for row in [*existing_rows, *rows]}
    for corpus_type in order:
        row = rows_by_type.get(corpus_type)
        if row is not None:
            merged_rows.append(row)
    for corpus_type, row in rows_by_type.items():
        if corpus_type not in order:
            merged_rows.append(row)

    write_summary(args.out_dir, merged_rows)

    csv_path = args.out_dir / "cpt_dataset_summary.csv"
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as f:
            summary_rows = list(csv.DictReader(f))
        for row in summary_rows:
            if row["corpus_type"] in {"knowledge_format", "knowledge_Seeker38"}:
                print(
                    f"{row['corpus_type']}: "
                    f"samples={row['samples']}, size={row['size']}, "
                    f"all_tokens={row['all_tokens']}, avg_token={row['avg_token']}, "
                    f"avg_chars={row['avg_chars']}"
                )


if __name__ == "__main__":
    main()
