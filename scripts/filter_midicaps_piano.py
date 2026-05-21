#!/usr/bin/env python3
"""Filter MidiCaps dataset for piano pieces - works with local parquet files.

This script can work with:
1. Downloaded parquet files from Hugging Face
2. Streaming mode (if network available)
3. Local JSONL files with MidiCaps format
"""

import json
import os
from pathlib import Path
from typing import Iterator, Dict, Any

try:
    from datasets import load_dataset
    from tqdm import tqdm
    HAS_DATASETS = True
except ImportError:
    HAS_DATASETS = False
    print("Warning: datasets library not available, will only work with local files")


PIANO_INSTRUMENTS = {
    "piano", "acoustic grand piano", "bright acoustic piano",
    "electric grand piano", "honky-tonk piano", "rhodes piano",
    "chorused piano", "electric piano", "harpsichord", "clavinet"
}


def is_piano_instrument(instrument_name: str) -> bool:
    """Check if instrument is a piano variant."""
    name_lower = instrument_name.lower().strip()
    return any(piano in name_lower for piano in PIANO_INSTRUMENTS)


def parse_instruments_from_tags(tags_str: str) -> list[str]:
    """Extract instruments from tags string."""
    instruments = []
    for line in tags_str.split("\n"):
        if "instruments summary tags:" in line:
            # Extract list from line like: instruments summary tags: ['Piano', 'Bass']
            start = line.find("[")
            end = line.find("]", start)
            if start != -1 and end != -1:
                import ast
                try:
                    instruments = ast.literal_eval(line[start:end+1])
                except:
                    pass
            break
    return instruments


def filter_piano_from_dataset(dataset_path: str, output_dir: Path, mode: str = "primary"):
    """Filter piano pieces from Hugging Face dataset."""
    if not HAS_DATASETS:
        raise RuntimeError("datasets library required for this mode")

    print(f"Loading dataset from {dataset_path}...")
    dataset = load_dataset(dataset_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"piano_{mode}.jsonl"
    stats_file = output_dir / f"piano_{mode}_stats.json"

    stats = {"total": 0, "piano_primary": 0, "piano_any": 0, "no_instruments": 0, "filtered": 0}

    with output_file.open("w", encoding="utf-8") as f:
        for split in dataset.keys():
            print(f"\nProcessing split: {split}")
            for item in tqdm(dataset[split]):
                stats["total"] += 1

                instruments = item.get("instrument_summary", [])
                if not instruments:
                    stats["no_instruments"] += 1
                    continue

                has_piano = any(is_piano_instrument(inst) for inst in instruments)
                is_primary = is_piano_instrument(instruments[0]) if instruments else False

                if is_primary:
                    stats["piano_primary"] += 1
                if has_piano:
                    stats["piano_any"] += 1

                if (mode == "primary" and is_primary) or (mode == "any" and has_piano):
                    stats["filtered"] += 1
                    record = {
                        "location": item.get("location", ""),
                        "caption": item.get("caption", ""),
                        "instruments": instruments,
                        "instrument_numbers": item.get("instrument_numbers_sorted", []),
                        "genre": item.get("genre", []),
                        "genre_prob": item.get("genre_prob", []),
                        "mood": item.get("mood", []),
                        "mood_prob": item.get("mood_prob", []),
                        "tempo": item.get("tempo", 0),
                        "tempo_word": item.get("tempo_word", ""),
                        "key": item.get("key", ""),
                        "time_signature": item.get("time_signature", ""),
                        "chords": item.get("chord_summary", []),
                        "chords_occurence": item.get("chord_summary_occurence", 0),
                        "duration": item.get("duration", 0),
                        "duration_word": item.get("duration_word", ""),
                        "split": split,
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with stats_file.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\n=== Statistics ===")
    print(f"Total: {stats['total']:,}")
    print(f"Piano primary: {stats['piano_primary']:,} ({stats['piano_primary']/stats['total']*100:.1f}%)")
    print(f"Piano any: {stats['piano_any']:,} ({stats['piano_any']/stats['total']*100:.1f}%)")
    print(f"Filtered: {stats['filtered']:,}")
    print(f"\nOutput: {output_file}")
    print(f"Stats: {stats_file}")


def filter_piano_from_jsonl(input_file: Path, output_dir: Path, mode: str = "primary"):
    """Filter piano pieces from local JSONL file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"piano_{mode}.jsonl"
    stats_file = output_dir / f"piano_{mode}_stats.json"

    stats = {"total": 0, "piano_primary": 0, "piano_any": 0, "no_instruments": 0, "filtered": 0}

    with input_file.open("r", encoding="utf-8") as fin, \
         output_file.open("w", encoding="utf-8") as fout:

        for line in fin:
            if not line.strip():
                continue

            stats["total"] += 1
            item = json.loads(line)

            # Try to get instruments from different possible fields
            instruments = item.get("instruments", [])
            if not instruments and "tags" in item:
                instruments = parse_instruments_from_tags(item["tags"])
            if not instruments:
                stats["no_instruments"] += 1
                continue

            has_piano = any(is_piano_instrument(inst) for inst in instruments)
            is_primary = is_piano_instrument(instruments[0]) if instruments else False

            if is_primary:
                stats["piano_primary"] += 1
            if has_piano:
                stats["piano_any"] += 1

            if (mode == "primary" and is_primary) or (mode == "any" and has_piano):
                stats["filtered"] += 1
                fout.write(line)

    with stats_file.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\n=== Statistics ===")
    print(f"Total: {stats['total']:,}")
    print(f"Piano primary: {stats['piano_primary']:,} ({stats['piano_primary']/stats['total']*100:.1f}%)")
    print(f"Piano any: {stats['piano_any']:,} ({stats['piano_any']/stats['total']*100:.1f}%)")
    print(f"Filtered: {stats['filtered']:,}")
    print(f"\nOutput: {output_file}")
    print(f"Stats: {stats_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Filter MidiCaps for piano pieces")
    parser.add_argument("--mode", choices=["primary", "any"], default="primary",
                        help="Filter mode: primary (piano is first) or any (piano anywhere)")
    parser.add_argument("--input", type=Path, default=None,
                        help="Local JSONL file to filter (if not using HF dataset)")
    parser.add_argument("--dataset", type=str, default="amaai-lab/MidiCaps",
                        help="Hugging Face dataset path")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/home/sy/EPR/PianoCoReS/MidiCaps"),
                        help="Output directory")
    args = parser.parse_args()

    if args.input:
        print(f"Filtering from local file: {args.input}")
        filter_piano_from_jsonl(args.input, args.output_dir, args.mode)
    else:
        print(f"Filtering from Hugging Face dataset: {args.dataset}")
        filter_piano_from_dataset(args.dataset, args.output_dir, args.mode)


if __name__ == "__main__":
    main()
