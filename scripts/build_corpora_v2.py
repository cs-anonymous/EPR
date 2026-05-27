#!/usr/bin/env python3
"""Build CorporaV2 with updated token limits and split annotations.

CorporaV2 changes:
- language_cpt: max_tokens = 1536
- epr_sft: max_tokens = 1536
- All samples include 'split' field (train/val/test)
- Generate full datasets first, then create summary statistics
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class CorpusConfig:
    """Configuration for a corpus type."""
    name: str
    source_file: Path
    max_tokens: int
    output_dir: Path

    def output_jsonl(self) -> Path:
        return self.output_dir / f"{self.name}.jsonl"

    def summary_json(self) -> Path:
        return self.output_dir / f"{self.name}_summary.json"


def human_size(num_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def token_length(tokenizer, text: str) -> int:
    """Get token length of text."""
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return len(encoded["input_ids"])


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


def process_language_cpt_corpus(
    config: CorpusConfig,
    tokenizer,
) -> dict[str, Any]:
    """Process a language CPT corpus file.

    Reads existing JSONL, adds token counts, filters by max_tokens,
    and writes to output with split annotations.
    """
    print(f"\nProcessing {config.name}...")
    print(f"  Source: {config.source_file}")
    print(f"  Max tokens: {config.max_tokens}")

    if not config.source_file.exists():
        print(f"  ⚠ Source file not found, skipping")
        return None

    # Read all samples first
    records = []
    texts = []
    source_splits = Counter()

    with config.source_file.open('r', encoding='utf-8') as f:
        for line in tqdm(f, desc=f"  Reading {config.name}"):
            if not line.strip():
                continue

            record = json.loads(line)
            text = record.get("text", "")

            records.append(record)
            texts.append(text)

            source_split = record.get("source_split", "unspecified")
            source_splits[source_split] += 1

    # Batch tokenize all texts
    print(f"  Tokenizing {len(texts)} samples...")
    token_lengths = batch_token_length(tokenizer, texts, batch_size=512)

    # Filter and write output
    samples = []
    over_limit = 0

    for record, num_tokens in zip(records, token_lengths):
        if num_tokens > config.max_tokens:
            over_limit += 1
            continue

        record["num_tokens"] = num_tokens
        samples.append(record)

    # Write output
    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = config.output_jsonl()

    with output_path.open('w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')

    # Calculate statistics
    all_tokens = sum(s["num_tokens"] for s in samples)
    all_chars = sum(len(s.get("text", "")) for s in samples)
    file_size = output_path.stat().st_size

    stats = {
        "corpus_type": config.name,
        "file": str(output_path),
        "source_file": str(config.source_file),
        "source_samples": source_splits.total(),
        "source_splits": dict(source_splits),
        "output_samples": len(samples),
        "over_limit": over_limit,
        "max_tokens": config.max_tokens,
        "bytes": file_size,
        "size": human_size(file_size),
        "all_tokens": all_tokens,
        "avg_tokens": all_tokens / len(samples) if samples else 0,
        "all_chars": all_chars,
        "avg_chars": all_chars / len(samples) if samples else 0,
    }

    print(f"  ✓ Output samples: {len(samples)}")
    print(f"  ✓ Over limit: {over_limit}")
    print(f"  ✓ Avg tokens: {stats['avg_tokens']:.1f}")

    return stats


def process_epr_sft_corpus(
    config: CorpusConfig,
    tokenizer,
) -> dict[str, Any]:
    """Process an EPR SFT corpus file.

    Reads existing JSONL, calculates training tokens, filters by max_tokens,
    and writes to output with split annotations.
    """
    print(f"\nProcessing {config.name}...")
    print(f"  Source: {config.source_file}")
    print(f"  Max tokens: {config.max_tokens}")

    if not config.source_file.exists():
        print(f"  ⚠ Source file not found, skipping")
        return None

    # Import conversion function
    from scripts.prepare_core_s1_swift import convert_sample

    # Read all samples first
    records = []
    training_texts = []
    source_splits = Counter()

    with config.source_file.open('r', encoding='utf-8') as f:
        for line in tqdm(f, desc=f"  Reading {config.name}"):
            if not line.strip():
                continue

            record = json.loads(line)

            # Convert to messages format and render with chat template
            try:
                converted = convert_sample(record)
                messages = converted["messages"]

                training_text = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=False,
                )

                records.append(record)
                training_texts.append(training_text)

                source_split = record.get("source_split", "unspecified")
                source_splits[source_split] += 1

            except Exception as e:
                print(f"  ⚠ Error processing sample: {e}")
                continue

    # Batch tokenize all texts
    print(f"  Tokenizing {len(training_texts)} samples...")
    token_lengths = batch_token_length(tokenizer, training_texts, batch_size=256)

    # Filter and write output
    samples = []
    over_limit = 0

    for record, num_tokens in zip(records, token_lengths):
        if num_tokens > config.max_tokens:
            over_limit += 1
            continue

        record["num_tokens"] = num_tokens
        samples.append(record)

    # Write output
    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = config.output_jsonl()

    with output_path.open('w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')

    # Calculate statistics
    all_tokens = sum(s["num_tokens"] for s in samples)
    file_size = output_path.stat().st_size

    stats = {
        "corpus_type": config.name,
        "file": str(output_path),
        "source_file": str(config.source_file),
        "source_samples": source_splits.total(),
        "source_splits": dict(source_splits),
        "output_samples": len(samples),
        "over_limit": over_limit,
        "max_tokens": config.max_tokens,
        "bytes": file_size,
        "size": human_size(file_size),
        "all_tokens": all_tokens,
        "avg_tokens": all_tokens / len(samples) if samples else 0,
    }

    print(f"  ✓ Output samples: {len(samples)}")
    print(f"  ✓ Over limit: {over_limit}")
    print(f"  ✓ Avg tokens: {stats['avg_tokens']:.1f}")

    return stats


def build_language_cpt_v2(
    corpora_root: Path,
    tokenizer_path: str,
    output_root: Path,
) -> None:
    """Build language_cpt CorporaV2."""
    print("\n" + "=" * 60)
    print("Building language_cpt CorporaV2")
    print("=" * 60)

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    output_dir = output_root / "language_cpt"

    # Define corpus configs - only MIDI data (performance and score)
    configs = [
        CorpusConfig(
            name="performance_midi",
            source_file=corpora_root / "language_cpt" / "midi_tsv_no_header.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
        CorpusConfig(
            name="score_midi",
            source_file=corpora_root / "language_cpt" / "aligned_abcx.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
    ]

    # Process each corpus
    all_stats = []
    for config in configs:
        stats = process_language_cpt_corpus(config, tokenizer)
        if stats:
            all_stats.append(stats)

    # Write summary
    summary_path = output_dir / "language_cpt_v2_summary.json"
    with summary_path.open('w', encoding='utf-8') as f:
        json.dump(all_stats, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Summary written to: {summary_path}")

    # Print overall statistics
    print("\n" + "=" * 60)
    print("Language CPT V2 Summary")
    print("=" * 60)
    total_samples = sum(s["output_samples"] for s in all_stats)
    total_tokens = sum(s["all_tokens"] for s in all_stats)
    total_bytes = sum(s["bytes"] for s in all_stats)

    print(f"Total samples: {total_samples:,}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Total size: {human_size(total_bytes)}")
    print(f"Avg tokens/sample: {total_tokens / total_samples:.1f}")

    # Print split distribution
    print("\nSplit distribution:")
    split_counts = Counter()
    for stats in all_stats:
        for split, count in stats["source_splits"].items():
            split_counts[split] += count

    for split, count in split_counts.most_common():
        pct = 100 * count / sum(split_counts.values())
        print(f"  {split}: {count:,} ({pct:.1f}%)")


def build_epr_sft_v2(
    corpora_root: Path,
    tokenizer_path: str,
    output_root: Path,
) -> None:
    """Build epr_sft CorporaV2."""
    print("\n" + "=" * 60)
    print("Building epr_sft CorporaV2")
    print("=" * 60)

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    output_dir = output_root / "epr_sft"

    # Define corpus configs - only sm2pm (score-to-performance)
    # Process all splits: main and coldstart, train/val/test
    configs = [
        CorpusConfig(
            name="sm2pm_main_train",
            source_file=corpora_root / "sm2pm_sft" / "sm2pm_main_train.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
        CorpusConfig(
            name="sm2pm_main_val",
            source_file=corpora_root / "sm2pm_sft" / "sm2pm_main_val.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
        CorpusConfig(
            name="sm2pm_main_test",
            source_file=corpora_root / "sm2pm_sft" / "sm2pm_main_test.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
        CorpusConfig(
            name="sm2pm_coldstart_train",
            source_file=corpora_root / "sm2pm_sft" / "sm2pm_coldstart_train.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
        CorpusConfig(
            name="sm2pm_coldstart_val",
            source_file=corpora_root / "sm2pm_sft" / "sm2pm_coldstart_val.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
        CorpusConfig(
            name="sm2pm_coldstart_test",
            source_file=corpora_root / "sm2pm_sft" / "sm2pm_coldstart_test.jsonl",
            max_tokens=1536,
            output_dir=output_dir,
        ),
    ]

    # Process each corpus
    all_stats = []
    for config in configs:
        stats = process_epr_sft_corpus(config, tokenizer)
        if stats:
            all_stats.append(stats)

    # Write summary
    summary_path = output_dir / "epr_sft_v2_summary.json"
    with summary_path.open('w', encoding='utf-8') as f:
        json.dump(all_stats, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Summary written to: {summary_path}")

    # Print overall statistics
    print("\n" + "=" * 60)
    print("EPR SFT V2 Summary")
    print("=" * 60)
    total_samples = sum(s["output_samples"] for s in all_stats)
    total_tokens = sum(s["all_tokens"] for s in all_stats)
    total_bytes = sum(s["bytes"] for s in all_stats)

    print(f"Total samples: {total_samples:,}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Total size: {human_size(total_bytes)}")
    print(f"Avg tokens/sample: {total_tokens / total_samples:.1f}")

    # Print split distribution
    print("\nSplit distribution:")
    split_counts = Counter()
    for stats in all_stats:
        for split, count in stats["source_splits"].items():
            split_counts[split] += count

    for split, count in split_counts.most_common():
        pct = 100 * count / sum(split_counts.values())
        print(f"  {split}: {count:,} ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpora-root",
        type=Path,
        default=Path("PianoCoReS/Corpora"),
        help="Root directory of existing corpora",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("PianoCoReS/CorporaV2"),
        help="Output root directory for V2 corpora",
    )
    parser.add_argument(
        "--tokenizer",
        type=str,
        default="Qwen/Qwen2.5-0.5B",
        help="Tokenizer to use for token counting",
    )
    parser.add_argument(
        "--task",
        choices=["language_cpt", "epr_sft", "all"],
        default="all",
        help="Which task to build",
    )

    args = parser.parse_args()

    if args.task in ["language_cpt", "all"]:
        build_language_cpt_v2(args.corpora_root, args.tokenizer, args.output_root)

    if args.task in ["epr_sft", "all"]:
        build_epr_sft_v2(args.corpora_root, args.tokenizer, args.output_root)

    print("\n" + "=" * 60)
    print("✓ CorporaV2 generation complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

