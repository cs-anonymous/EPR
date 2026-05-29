#!/usr/bin/env python3
"""Update score_metadata.csv to have correct source paths in score_abcx_path."""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "data" / "score_metadata.csv"
METADATA_BACKUP = ROOT / "data" / "score_metadata.csv.backup"


def extract_piece_path_from_aligned(aligned_path: str) -> str | None:
    """Extract piece path from score_aligned_path.

    Returns None if this is not a standard miditsv path.

    Example:
        data/miditsv/Composer/Piece/score_aligned.abcx -> Composer/Piece
        data/unpaired_abcx/PDMX/abcx_aligned/123_aligned.abcx -> None (not standard)
    """
    path = Path(aligned_path)
    parts = path.parts

    # Only process data/miditsv paths
    if len(parts) < 3 or parts[0] != 'data' or parts[1] != 'miditsv':
        return None

    # Extract piece path: everything between 'miditsv' and the filename
    piece_parts = parts[2:-1]  # Skip 'data/miditsv' and filename
    if not piece_parts:
        return None

    return str(Path(*piece_parts))


def main():
    # Restore from backup
    if METADATA_BACKUP.exists():
        import shutil
        shutil.copy2(METADATA_BACKUP, METADATA)
        print(f"✓ Restored from backup: {METADATA_BACKUP}")
    else:
        print(f"⚠ No backup found at {METADATA_BACKUP}")
        return

    rows = []
    updated = 0
    skipped = 0

    with METADATA.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        for row in reader:
            aligned_path = row.get('score_aligned_path', '').strip()

            if aligned_path:
                piece_path = extract_piece_path_from_aligned(aligned_path)

                if piece_path:
                    # This is a standard data/miditsv path
                    source_path = f"PianoCoRe/score/{piece_path}/score.abcx"
                    row['score_abcx_path'] = source_path
                    updated += 1
                else:
                    # This is unpaired or other non-standard path, leave as-is
                    skipped += 1

            rows.append(row)

    # Write updated metadata
    with METADATA.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Processed {len(rows)} rows")
    print(f"  Updated: {updated} (data/miditsv paths)")
    print(f"  Skipped: {skipped} (unpaired/other paths)")
    print(f"\nUpdated metadata saved to: {METADATA}")


if __name__ == '__main__':
    main()
