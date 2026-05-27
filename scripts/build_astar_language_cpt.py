#!/usr/bin/env python3
"""Build language_cpt corpus for A* performance data.

Generates performance_Astar_midi.jsonl from A* performance TSV files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tsv import lm_midi_tsv_to_tokens


def tsv_to_midi_format(tsv_path: Path) -> str:
    """Convert TSV file to MIDI token format using lm_midi_tsv module."""
    with open(tsv_path, 'r', encoding='utf-8') as f:
        tsv_text = f.read()

    # Use the official converter
    return lm_midi_tsv_to_tokens(tsv_text, wrap=True, pretty=False)


def batch_token_length(tokenizer, texts: list[str], batch_size: int = 256) -> list[int]:
    """Get token lengths for a batch of texts."""
    lengths = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        encoded = tokenizer(
            batch,
            add_special_tokens=False,
            truncation=False,
            padding=False,
            return_attention_mask=False,
        )
        lengths.extend([len(ids) for ids in encoded["input_ids"]])
    return lengths


def build_astar_performance_corpus(
    metadata_path: Path,
    output_path: Path,
    tokenizer_path: str,
    max_tokens: int = 1536,
) -> None:
    """Build performance_Astar_midi.jsonl corpus."""
    print(f"\nBuilding A* performance corpus...")
    print(f"  Metadata: {metadata_path}")
    print(f"  Output: {output_path}")
    print(f"  Max tokens: {max_tokens}")

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

    # Load metadata
    meta = pd.read_csv(metadata_path)

    # Filter to rows with TSV paths
    meta = meta[meta['tsv_path'].notna()]
    print(f"  Found {len(meta)} performances with TSV files")

    # Process each TSV file
    records = []
    texts = []

    for idx, row in tqdm(meta.iterrows(), total=len(meta), desc="  Reading TSV files"):
        tsv_path = Path('PianoCoReS') / row['tsv_path']

        if not tsv_path.exists():
            continue

        try:
            # Convert TSV to MIDI format
            text = tsv_to_midi_format(tsv_path)

            record = {
                'task': 'language_cpt',
                'corpus_type': 'midi_tsv_no_header',
                'source': str(tsv_path),
                'source_split': row['split'],
                'chunk_id': 1,
                'text': text,
            }

            records.append(record)
            texts.append(text)

        except Exception as e:
            print(f"  ⚠ Error processing {tsv_path}: {e}")
            continue

    # Batch tokenize
    print(f"  Tokenizing {len(texts)} samples...")
    token_lengths = batch_token_length(tokenizer, texts, batch_size=512)

    # Filter by max_tokens and add token counts
    samples = []
    over_limit = 0

    for record, num_tokens in zip(records, token_lengths):
        if num_tokens > max_tokens:
            over_limit += 1
            continue

        record['num_tokens'] = num_tokens
        samples.append(record)

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
        default=Path("PianoCoReS/performance_Astar_metadata.csv"),
        help="Path to A* metadata CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("PianoCoReS/CorporaV2/language_cpt/performance_Astar_midi.jsonl"),
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

    args = parser.parse_args()

    build_astar_performance_corpus(
        args.metadata,
        args.output,
        args.tokenizer,
        args.max_tokens,
    )

    print("\n✓ A* performance corpus generation complete!")


if __name__ == "__main__":
    main()
