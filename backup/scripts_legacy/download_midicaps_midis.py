#!/usr/bin/env python3
"""Download MIDI files from MidiCaps dataset and convert to MIDI-TSV format.

This script:
1. Downloads MIDI files from the MidiCaps dataset
2. Uses omnizart to detect beats
3. Converts to MIDI-TSV format
4. Counts total tokens
"""

import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional
from tqdm import tqdm
import multiprocessing as mp
from functools import partial

# Add wave-roll to path for midi_tsv module
sys.path.insert(0, str(Path(__file__).parent.parent / "wave-roll"))
from midi_tsv import midi_to_tsv


def download_midi_file(location: str, output_dir: Path) -> Optional[Path]:
    """Download a single MIDI file from HuggingFace dataset."""
    # MidiCaps uses the Lakh MIDI Dataset
    # Files are stored in the dataset repository
    base_url = "https://huggingface.co/datasets/amaai-lab/MidiCaps/resolve/main/lmd_full"

    # Extract path components
    # location format: "lmd_full/1/17655598958db48a34cd882f81402568.mid"
    parts = location.split("/")
    if len(parts) != 3 or parts[0] != "lmd_full":
        return None

    subdir = parts[1]
    filename = parts[2]

    # Create output path
    output_subdir = output_dir / subdir
    output_subdir.mkdir(parents=True, exist_ok=True)
    output_path = output_subdir / filename

    # Skip if already downloaded
    if output_path.exists():
        return output_path

    # Download URL
    url = f"{base_url}/{subdir}/{filename}"

    # Use wget with proxy
    try:
        env = os.environ.copy()
        env['http_proxy'] = 'http://127.0.0.1:7890'
        env['https_proxy'] = 'http://127.0.0.1:7890'

        subprocess.run(
            ["wget", "-q", "-O", str(output_path), url],
            env=env,
            check=True,
            timeout=30
        )
        return output_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if output_path.exists():
            output_path.unlink()
        return None


def convert_midi_to_tsv_file(midi_path: Path, output_dir: Path) -> Optional[Path]:
    """Convert MIDI to TSV format using midi_tsv module."""
    # Output path mirrors MIDI structure
    relative_path = midi_path.relative_to(midi_path.parent.parent)
    output_path = output_dir / relative_path.with_suffix(".mid.tsv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Skip if already converted
    if output_path.exists():
        return output_path

    # Convert using midi_tsv module with omnizart
    try:
        midi_data = midi_path.read_bytes()
        tsv_content = midi_to_tsv(
            midi_data,
            source=midi_path.name,
            annotation_path=None,
            auto_downbeat=True,
            midi_path=midi_path,
        )
        output_path.write_text(tsv_content, encoding="utf-8")
        return output_path
    except Exception:
        if output_path.exists():
            output_path.unlink()
        return None


def process_single_item(item_json: str, midi_dir: Path, tsv_dir: Path) -> dict:
    """Process a single MidiCaps item: download and convert."""
    item = json.loads(item_json)
    location = item["location"]

    result = {
        "location": location,
        "midi_downloaded": False,
        "tsv_converted": False,
    }

    # Download MIDI
    midi_path = download_midi_file(location, midi_dir)
    if midi_path is None:
        return result
    result["midi_downloaded"] = True

    # Convert to TSV
    tsv_path = convert_midi_to_tsv_file(midi_path, tsv_dir)
    if tsv_path is None:
        return result
    result["tsv_converted"] = True

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("data/MidiCaps/piano_primary.jsonl"))
    parser.add_argument("--midi-dir", type=Path,
                        default=Path("data/MidiCaps/midis"))
    parser.add_argument("--tsv-dir", type=Path,
                        default=Path("data/MidiCaps/tsv"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of files to process (for testing)")
    args = parser.parse_args()

    args.midi_dir.mkdir(parents=True, exist_ok=True)
    args.tsv_dir.mkdir(parents=True, exist_ok=True)

    # Read input file
    print(f"Reading {args.input}...")
    with args.input.open("r", encoding="utf-8") as f:
        items = [line.strip() for line in f if line.strip()]

    if args.limit:
        items = items[:args.limit]

    print(f"Processing {len(items)} items with {args.workers} workers...")

    # Process in parallel
    process_fn = partial(
        process_single_item,
        midi_dir=args.midi_dir,
        tsv_dir=args.tsv_dir,
    )

    stats = {
        "total": len(items),
        "midi_downloaded": 0,
        "tsv_converted": 0,
        "failed": 0
    }

    with mp.Pool(args.workers) as pool:
        for result in tqdm(pool.imap_unordered(process_fn, items), total=len(items)):
            if result["midi_downloaded"]:
                stats["midi_downloaded"] += 1
            if result["tsv_converted"]:
                stats["tsv_converted"] += 1
            if not result["tsv_converted"]:
                stats["failed"] += 1

    print("\n=== Statistics ===")
    print(f"Total items: {stats['total']}")
    print(f"MIDI downloaded: {stats['midi_downloaded']}")
    print(f"TSV converted: {stats['tsv_converted']}")
    print(f"Failed: {stats['failed']}")

    # Count tokens
    print("\nCounting tokens...")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("Qwen3.5-4B-LM-MIDI", trust_remote_code=True)

    total_tokens = 0
    tsv_files = list(args.tsv_dir.rglob("*.tsv"))

    for tsv_path in tqdm(tsv_files, desc="Counting tokens"):
        try:
            content = tsv_path.read_text(encoding="utf-8")
            tokens = tokenizer.encode(content)
            total_tokens += len(tokens)
        except Exception:
            pass

    print(f"\n=== Token Statistics ===")
    print(f"Total TSV files: {len(tsv_files)}")
    print(f"Total tokens: {total_tokens:,}")
    if tsv_files:
        print(f"Avg tokens/file: {total_tokens/len(tsv_files):.1f}")

    # Save statistics
    stats_file = args.tsv_dir / "conversion_stats.json"
    with stats_file.open("w", encoding="utf-8") as f:
        json.dump({
            **stats,
            "total_tokens": total_tokens,
            "avg_tokens_per_file": total_tokens / len(tsv_files) if tsv_files else 0
        }, f, indent=2)

    print(f"\nStats saved to {stats_file}")


if __name__ == "__main__":
    main()
