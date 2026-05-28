#!/usr/bin/env python3
"""Download and filter MidiCaps dataset for piano-as-main-instrument pieces."""

import json
import os
from pathlib import Path
from datasets import load_dataset
from tqdm import tqdm


def is_piano_instrument(instrument_name: str) -> bool:
    """Check if instrument is a piano variant."""
    piano_keywords = [
        "piano", "rhodes", "clavinet", "harpsichord",
        "electric piano", "honky-tonk piano"
    ]
    name_lower = instrument_name.lower()
    return any(keyword in name_lower for keyword in piano_keywords)


def filter_piano_pieces(dataset, output_dir: Path, mode: str = "primary"):
    """Filter MidiCaps for piano pieces.

    Args:
        dataset: Hugging Face dataset
        output_dir: Output directory
        mode: "primary" (piano is first instrument) or "any" (piano anywhere)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    piano_pieces = []
    stats = {
        "total": 0,
        "piano_primary": 0,
        "piano_any": 0,
        "no_instruments": 0,
    }

    for split in dataset.keys():
        print(f"\nProcessing split: {split}")
        for item in tqdm(dataset[split]):
            stats["total"] += 1

            # Extract instruments from tags
            instruments_summary = item.get("instruments_summary_tags", [])
            if not instruments_summary:
                stats["no_instruments"] += 1
                continue

            # Check if piano is present
            has_piano = any(is_piano_instrument(inst) for inst in instruments_summary)
            if not has_piano:
                continue

            # Check if piano is primary (first instrument)
            is_primary = is_piano_instrument(instruments_summary[0])

            if is_primary:
                stats["piano_primary"] += 1
            if has_piano:
                stats["piano_any"] += 1

            # Filter based on mode
            if mode == "primary" and not is_primary:
                continue
            if mode == "any" and not has_piano:
                continue

            # Add to filtered list
            piano_pieces.append({
                "location": item.get("location", ""),
                "caption": item.get("caption", ""),
                "tags": item.get("tags", ""),
                "instruments": instruments_summary,
                "genre": item.get("genre_tags", []),
                "mood": item.get("mood_tags", []),
                "tempo": item.get("tempo_tags", []),
                "key": item.get("key_tags", ""),
                "time_signature": item.get("time_signature_tags", ""),
                "chords": item.get("chords_summary_tags", []),
                "duration": item.get("duration_tags", []),
                "split": split,
            })

    # Write filtered data
    output_file = output_dir / f"piano_{mode}.jsonl"
    with output_file.open("w", encoding="utf-8") as f:
        for piece in piano_pieces:
            f.write(json.dumps(piece, ensure_ascii=False) + "\n")

    # Write statistics
    stats_file = output_dir / f"piano_{mode}_stats.json"
    stats["filtered_count"] = len(piano_pieces)
    stats["filter_mode"] = mode
    with stats_file.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\n=== Statistics ===")
    print(f"Total pieces: {stats['total']:,}")
    print(f"Piano as primary instrument: {stats['piano_primary']:,} ({stats['piano_primary']/stats['total']*100:.1f}%)")
    print(f"Piano anywhere: {stats['piano_any']:,} ({stats['piano_any']/stats['total']*100:.1f}%)")
    print(f"No instruments listed: {stats['no_instruments']:,}")
    print(f"Filtered output: {len(piano_pieces):,} pieces")
    print(f"\nOutput: {output_file}")
    print(f"Stats: {stats_file}")

    return piano_pieces, stats


def main():
    print("Loading MidiCaps dataset from Hugging Face...")
    try:
        dataset = load_dataset("amaai-lab/MidiCaps")
    except Exception as e:
        print(f"Error loading dataset: {e}")
        print("\nTrying with streaming mode...")
        dataset = load_dataset("amaai-lab/MidiCaps", streaming=True)

    output_dir = Path("/home/sy/EPR/data/MidiCaps")

    # Filter for piano as primary instrument
    print("\n" + "="*60)
    print("Filtering for piano as PRIMARY instrument...")
    print("="*60)
    filter_piano_pieces(dataset, output_dir, mode="primary")

    # Also create a version with piano anywhere
    print("\n" + "="*60)
    print("Filtering for piano ANYWHERE in instruments...")
    print("="*60)
    filter_piano_pieces(dataset, output_dir, mode="any")


if __name__ == "__main__":
    main()
