#!/usr/bin/env python3
"""Fix score_metadata.csv to point to correct PianoCoRe/score paths."""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "data" / "score_metadata.csv"
METADATA_BACKUP = ROOT / "data" / "score_metadata.csv.backup"


def extract_piece_path(abcx_path: str) -> str:
    """Extract piece path from score_abcx_path.

    Example:
        data/miditsv/Composer/Piece/score.abcx -> Composer/Piece
    """
    path = Path(abcx_path)
    parts = path.parts

    # Find the index after 'miditsv' or 'aligned'
    for i, part in enumerate(parts):
        if part in ('miditsv', 'aligned'):
            # Everything after this until score.abcx is the piece path
            piece_parts = parts[i+1:-1]  # Exclude 'score.abcx'
            return str(Path(*piece_parts))

    # Fallback: just remove the filename
    return str(path.parent)


def main():
    # Backup original
    if not METADATA_BACKUP.exists():
        import shutil
        shutil.copy2(METADATA, METADATA_BACKUP)
        print(f"✓ Backed up original to {METADATA_BACKUP}")

    rows = []
    with METADATA.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        for row in reader:
            old_abcx = row.get('score_abcx_path', '')
            if old_abcx and old_abcx.strip():
                piece_path = extract_piece_path(old_abcx)
                # Update to point to PianoCoRe/score
                row['score_abcx_path'] = f"PianoCoRe/score/{piece_path}/score.abcx"
            rows.append(row)

    # Write updated metadata
    with METADATA.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Updated {len(rows)} rows in {METADATA}")
    print(f"  Changed score_abcx_path to point to PianoCoRe/score/")


if __name__ == '__main__':
    main()
