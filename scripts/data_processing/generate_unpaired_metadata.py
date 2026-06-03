#!/usr/bin/env python3
"""Generate metadata CSV entries for unpaired ABCX datasets.

This script scans the unpaired_abcx directories and generates CSV rows
for score_metadata.csv with proper composer, composition, and movement info.
"""

import csv
import re
from pathlib import Path
from typing import Optional


def parse_abc_header(abc_path: Path) -> dict:
    """Extract metadata from ABC/ABCX file header."""
    metadata = {
        'title': '',
        'composer': '',
        'movement': '',
    }

    try:
        with open(abc_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('<'):
                    # Stop at body content
                    if line.startswith('<H>') or line.startswith('<M>'):
                        break
                    continue

                if line.startswith('T:'):
                    title = line[2:].strip()
                    if not metadata['title']:
                        metadata['title'] = title
                    elif not metadata['movement']:
                        metadata['movement'] = title
                elif line.startswith('C:'):
                    metadata['composer'] = line[2:].strip()
                elif line.startswith('K:'):
                    # Key signature marks end of header
                    break
    except Exception as e:
        print(f"Error parsing {abc_path}: {e}")

    return metadata


def generate_metadata_rows(dataset_name: str, dataset_dir: Path, split: str = 'train') -> list[dict]:
    """Generate metadata rows for a dataset."""
    rows = []

    abcx_dir = dataset_dir / 'abcx'
    abcx_aligned_dir = dataset_dir / 'abcx_aligned'
    original_dir = dataset_dir / 'original'

    if not abcx_dir.exists() or not abcx_aligned_dir.exists():
        print(f"Skipping {dataset_name}: missing directories")
        return rows

    # Process each ABCX file
    for abcx_file in sorted(abcx_dir.glob('*.abcx')):
        score_id = abcx_file.stem
        aligned_file = abcx_aligned_dir / f"{score_id}_aligned.abcx"

        if not aligned_file.exists():
            continue

        # Parse metadata from ABCX
        metadata = parse_abc_header(abcx_file)

        # Find original file
        original_path = ''
        if original_dir.exists():
            # Try different extensions
            for ext in ['.abc', '.mxl', '.xml', '.musicxml', '.mscx']:
                orig_file = original_dir / f"{score_id}{ext}"
                if orig_file.exists():
                    original_path = f"data/unpaired_abcx/{dataset_name}/original/{orig_file.name}"
                    break

        # Build row
        row = {
            'source': dataset_name,
            'split': split,
            'composer': metadata['composer'],
            'composition': metadata['title'],
            'movement': metadata['movement'],
            'score_dataset': dataset_name,
            'score_id': score_id,
            'score_xml_path': '',
            'score_midi_path': '',
            'refined_score_midi_path': '',
            'score_abcx_path': f"data/unpaired_abcx/{dataset_name}/abcx/{abcx_file.name}",
            'score_aligned_path': f"data/unpaired_abcx/{dataset_name}/abcx_aligned/{aligned_file.name}",
            'score_aligned_mini_path': '',
            'score_json_path': '',
            'score_json_mini_path': '',
            'original_path': original_path,
        }

        rows.append(row)

    return rows


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate metadata CSV for unpaired ABCX datasets'
    )
    parser.add_argument(
        '--unpaired-dir',
        type=Path,
        default=Path('data/unpaired_abcx'),
        help='Unpaired ABCX root directory'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('data/score_metadata_new.csv'),
        help='Output CSV file'
    )
    parser.add_argument(
        '--datasets',
        nargs='+',
        default=['Asap', 'MAESTRO', 'IMSLP'],
        help='Datasets to process'
    )
    parser.add_argument(
        '--split',
        default='train',
        help='Split to assign (default: train)'
    )

    args = parser.parse_args()

    # CSV fieldnames (matching existing format)
    fieldnames = [
        'source', 'split', 'composer', 'composition', 'movement',
        'score_dataset', 'score_id', 'score_xml_path', 'score_midi_path',
        'refined_score_midi_path', 'score_abcx_path', 'score_aligned_path',
        'score_aligned_mini_path', 'score_json_path', 'score_json_mini_path',
        'original_path'
    ]

    all_rows = []

    # Process each dataset
    for dataset_name in args.datasets:
        dataset_dir = args.unpaired_dir / dataset_name
        if not dataset_dir.exists():
            print(f"Warning: {dataset_dir} does not exist")
            continue

        print(f"Processing {dataset_name}...")
        rows = generate_metadata_rows(dataset_name, dataset_dir, args.split)
        all_rows.extend(rows)
        print(f"  Generated {len(rows)} rows")

    # Write CSV
    print(f"\nWriting {len(all_rows)} rows to {args.output}")
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nDone! Generated {len(all_rows)} metadata rows")
    print(f"Output: {args.output}")
    print(f"\nTo append to existing metadata.csv:")
    print(f"  tail -n +2 {args.output} >> EPR/data/score_metadata.csv")


if __name__ == '__main__':
    main()
