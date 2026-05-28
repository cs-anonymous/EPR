#!/usr/bin/env python3
"""Build language_cpt corpus for A* performance data (fast multiprocess version).

Generates performance_Astar_midi.jsonl from A* performance TSV files.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tsv import lm_midi_tsv_to_tokens


def process_tsv_file(args):
    """Process a single TSV file (for multiprocessing)."""
    tsv_path, split = args

    try:
        with open(tsv_path, 'r', encoding='utf-8') as f:
            tsv_text = f.read()

        # Convert to MIDI tokens
        text = lm_midi_tsv_to_tokens(tsv_text, wrap=True, pretty=False)

        return {
            'source': str(tsv_path),
            'source_split': split,
            'text': text,
        }
    except Exception as e:
        return None


def build_astar_performance_corpus(
    metadata_path: Path,
    output_path: Path,
    tokenizer_path: str,
    max_tokens: int = 1536,
    workers: int = 16,
) -> None:
    """Build performance_Astar_midi.jsonl corpus."""
    print(f"\nBuilding A* performance corpus (fast multiprocess)...")
    print(f"  Metadata: {metadata_path}")
    print(f"  Output: {output_path}")
    print(f"  Max tokens: {max_tokens}")
    print(f"  Workers: {workers}")

    # Load metadata
    meta = pd.read_csv(metadata_path)

    # Filter to rows with TSV paths
    meta = meta[meta['tsv_path'].notna()]
    print(f"  Found {len(meta)} performances with TSV files")

    # Prepare tasks
    tasks = []
    for _, row in meta.iterrows():
        tsv_path = Path('data') / row['tsv_path']
        if tsv_path.exists():
            tasks.append((tsv_path, row['split']))

    print(f"  Processing {len(tasks)} TSV files with {workers} workers...")

    # Process in parallel
    with mp.Pool(workers) as pool:
        results = list(tqdm(
            pool.imap(process_tsv_file, tasks),
            total=len(tasks),
            desc="  Reading TSV files"
        ))

    # Filter out errors
    records = [r for r in results if r is not None]
    errors = len(results) - len(records)

    if errors > 0:
        print(f"  ⚠ Skipped {errors} files due to errors")

    # Extract texts for tokenization
    texts = [r['text'] for r in records]

    # Load tokenizer and batch tokenize
    print(f"  Tokenizing {len(texts)} samples...")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

    token_lengths = []
    batch_size = 512
    for i in tqdm(range(0, len(texts), batch_size), desc="  Tokenizing"):
        batch = texts[i:i + batch_size]
        encoded = tokenizer(
            batch,
            add_special_tokens=False,
            truncation=False,
            padding=False,
            return_attention_mask=False,
        )
        token_lengths.extend([len(ids) for ids in encoded["input_ids"]])

    # Filter by max_tokens and add metadata
    samples = []
    over_limit = 0

    for record, num_tokens in zip(records, token_lengths):
        if num_tokens > max_tokens:
            over_limit += 1
            continue

        sample = {
            'task': 'language_cpt',
            'corpus_type': 'midi_tsv_no_header',
            'source': record['source'],
            'source_split': record['source_split'],
            'chunk_id': 1,
            'text': record['text'],
            'num_tokens': num_tokens,
        }
        samples.append(sample)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')

    # Print statistics
    if len(samples) > 0:
        all_tokens = sum(s['num_tokens'] for s in samples)
        file_size = output_path.stat().st_size

        print(f"\n  ✓ Output samples: {len(samples)}")
        print(f"  ✓ Over limit: {over_limit}")
        print(f"  ✓ Avg tokens: {all_tokens / len(samples):.1f}")
        print(f"  ✓ File size: {file_size / 1024 / 1024:.1f} MB")

        # Split distribution
        from collections import Counter
        split_counts = Counter(s['source_split'] for s in samples)
        print(f"\n  Split distribution:")
        for split, count in split_counts.most_common():
            pct = 100 * count / len(samples)
            print(f"    {split}: {count:,} ({pct:.1f}%)")
    else:
        print(f"\n  ⚠ No samples within token limit!")
        print(f"  ✓ Total processed: {len(records)}")
        print(f"  ✓ Over limit: {over_limit}")
        print(f"  ℹ Consider increasing --max-tokens")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/performance_Astar_metadata.csv"),
        help="Path to A* metadata CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/CorporaV2/language_cpt/performance_Astar_midi.jsonl"),
        help="Output JSONL file",
    )
    parser.add_argument(
        "--tokenizer",
        type=str,
        default="Qwen/Qwen2.5-0.5B",
        help="Tokenizer to use for token counting",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1536,
        help="Maximum tokens per sample",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of parallel workers",
    )

    args = parser.parse_args()

    build_astar_performance_corpus(
        args.metadata,
        args.output,
        args.tokenizer,
        args.max_tokens,
        args.workers,
    )

    print("\n✓ A* performance corpus generation complete!")


if __name__ == "__main__":
    main()
