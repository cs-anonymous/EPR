#!/usr/bin/env python3
"""Update score_metadata.csv to have correct source paths in score_abcx_path."""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "data" / "score_metadata.csv"
METADATA_BACKUP = ROOT / "data" / "score_metadata.csv.backup"


def extract_piece_path(output_path: str) -> str:
    """Extract piece path from output path.

    Example:
        data/miditsv/Composer/Piece/score_aligned.abcx -> Composer/Piece
    """
    path = Path(output_path)
    parts = path.parts

    # Find the index after 'miditsv' or 'aligned'
    for i, part in enumerate(parts):
        if part in ('miditsv', 'aligned', 'score'):
            # Everything after this until the filename is the piece path
            piece_parts = parts[i+1:-1]  # Exclude filename
            return str(Path(*piece_parts))

    # Fallback: just remove the filename
    return str(path.parent)


def main():
    # Backup original if not already backed up
    if not METADATA_BACKUP.exists():
        import shutil
        shutil.copy2(METADATA, METADATA_BACKUP)
        print(f"✓ Backed up original to {METADATA_BACKUP}")

    rows = []
    updated = 0

    with METADATA.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        for row in reader:
            # Get the output path (score_aligned_path or score_abcx_path)
            aligned_path = row.get('score_aligned_path', '').strip()
            current_abcx = row.get('score_abcx_path', '').strip()

            if aligned_path:
                # Extract piece path from aligned_path
                piece_path = extract_piece_path(aligned_path)
                # Source should be in PianoCoRe/score
                source_path = f"PianoCoRe/score/{piece_path}/score.abcx"

                # Check if source exists
                if (ROOT / source_path).exists():
                    if current_abcx != source_path:
                        row['score_abcx_path'] = source_path
                        updated += 1
                else:
                    # Source doesn't exist, keep current or leave empty
                    if not current_abcx or current_abcx.startswith('data/'):
                        row['score_abcx_path'] = source_path  # Set it anyway for consistency
                        updated += 1

            rows.append(row)

    # Write updated metadata
    with METADATA.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Updated {updated} rows in {METADATA}")
    print(f"  Total rows: {len(rows)}")
    print(f"  score_abcx_path now points to PianoCoRe/score/ (source)")
    print(f"  score_aligned_path points to data/miditsv/ (output)")


if __name__ == '__main__':
    main()
