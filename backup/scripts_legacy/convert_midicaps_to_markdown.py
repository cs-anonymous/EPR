#!/usr/bin/env python3
"""Convert MidiCaps captions to structured markdown files for knowledge corpus.

Organizes captions by genre/key/mood into separate markdown files.
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List


def group_captions_by_genre(input_file: Path, max_per_file: int = 500) -> Dict[str, List[dict]]:
    """Group captions by primary genre."""
    groups = defaultdict(list)

    with input_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            genre = item.get("genre", ["unknown"])[0]
            groups[genre].append(item)

    # Split large groups
    result = {}
    for genre, items in groups.items():
        if len(items) <= max_per_file:
            result[genre] = items
        else:
            # Split into multiple files
            for i in range(0, len(items), max_per_file):
                chunk = items[i:i + max_per_file]
                key = f"{genre}_{i//max_per_file + 1}"
                result[key] = chunk

    return result


def group_captions_by_key(input_file: Path, max_per_file: int = 500) -> Dict[str, List[dict]]:
    """Group captions by musical key."""
    groups = defaultdict(list)

    with input_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            key = item.get("key", "unknown")
            # Normalize key name for filename
            key_safe = key.replace(" ", "_").replace("/", "_")
            groups[key_safe].append(item)

    # Split large groups
    result = {}
    for key, items in groups.items():
        if len(items) <= max_per_file:
            result[key] = items
        else:
            for i in range(0, len(items), max_per_file):
                chunk = items[i:i + max_per_file]
                key_name = f"{key}_{i//max_per_file + 1}"
                result[key_name] = chunk

    return result


def format_caption_entry(item: dict, index: int) -> str:
    """Format a single caption as markdown."""
    lines = []

    # Header
    lines.append(f"### {index}. {item.get('key', 'Unknown Key')}")
    lines.append("")

    # Metadata
    genre = ", ".join(item.get("genre", [])[:2])
    mood = ", ".join(item.get("mood", [])[:3])
    tempo = item.get("tempo_word", "")
    time_sig = item.get("time_signature", "")
    duration = item.get("duration_word", "")

    lines.append(f"**Genre**: {genre}")
    lines.append(f"**Mood**: {mood}")
    lines.append(f"**Tempo**: {tempo} ({item.get('tempo', '')} bpm)")
    lines.append(f"**Time Signature**: {time_sig}")
    lines.append(f"**Duration**: {duration}")

    # Chord progression
    chords = item.get("chords", [])
    if chords:
        chord_str = " → ".join(chords[:8])  # First 8 chords
        if len(chords) > 8:
            chord_str += " ..."
        lines.append(f"**Chord Progression**: {chord_str}")

    lines.append("")

    # Caption
    caption = item.get("caption", "")
    lines.append(caption)
    lines.append("")

    return "\n".join(lines)


def write_markdown_file(output_path: Path, title: str, items: List[dict]) -> None:
    """Write a markdown file with grouped captions."""
    lines = []

    # Header
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"This document contains {len(items)} piano music descriptions.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Entries
    for i, item in enumerate(items, 1):
        lines.append(format_caption_entry(item, i))

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("data/MidiCaps/piano_primary.jsonl"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("data/knowledge/MidiCaps"))
    parser.add_argument("--group-by", choices=["genre", "key", "mixed"],
                        default="mixed")
    parser.add_argument("--max-per-file", type=int, default=500)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.group_by == "genre":
        print("Grouping by genre...")
        groups = group_captions_by_genre(args.input, args.max_per_file)
        for genre, items in groups.items():
            title = f"Piano Music: {genre.title()}"
            output_file = args.output_dir / f"piano_{genre}.md"
            write_markdown_file(output_file, title, items)
            print(f"  {output_file.name}: {len(items)} pieces")

    elif args.group_by == "key":
        print("Grouping by key...")
        groups = group_captions_by_key(args.input, args.max_per_file)
        for key, items in groups.items():
            title = f"Piano Music in {key.replace('_', ' ')}"
            output_file = args.output_dir / f"piano_key_{key}.md"
            write_markdown_file(output_file, title, items)
            print(f"  {output_file.name}: {len(items)} pieces")

    else:  # mixed
        print("Creating mixed organization...")

        # By genre (top genres only)
        genre_groups = group_captions_by_genre(args.input, args.max_per_file)
        top_genres = ["pop", "electronic", "classical", "rock", "jazz"]

        for genre in top_genres:
            if genre in genre_groups:
                items = genre_groups[genre]
                title = f"Piano Music: {genre.title()}"
                output_file = args.output_dir / f"piano_{genre}.md"
                write_markdown_file(output_file, title, items)
                print(f"  {output_file.name}: {len(items)} pieces")

        # By key (major keys only)
        key_groups = group_captions_by_key(args.input, args.max_per_file)
        major_keys = ["C_major", "F_major", "G_major", "D_major", "Bb_major", "A_major"]

        for key in major_keys:
            if key in key_groups:
                items = key_groups[key]
                title = f"Piano Music in {key.replace('_', ' ')}"
                output_file = args.output_dir / f"piano_key_{key}.md"
                write_markdown_file(output_file, title, items)
                print(f"  {output_file.name}: {len(items)} pieces")

    print(f"\nMarkdown files written to {args.output_dir}")


if __name__ == "__main__":
    main()
