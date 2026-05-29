#!/usr/bin/env python3
"""Copy score.abcx files from PianoCoRe/score to data/miditsv as specified in metadata."""

import csv
import shutil
from pathlib import Path
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "data" / "score_metadata.csv"


def extract_piece_path(miditsv_path: str) -> str | None:
    """Extract piece path from data/miditsv path.

    Example:
        data/miditsv/Composer/Piece/score.abcx -> Composer/Piece
    """
    path = Path(miditsv_path)
    parts = path.parts

    if len(parts) < 3 or parts[0] != 'data' or parts[1] != 'miditsv':
        return None

    # Extract piece path: everything between 'miditsv' and filename
    piece_parts = parts[2:-1]
    if not piece_parts:
        return None

    return str(Path(*piece_parts))


def main():
    rows = []
    with METADATA.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    copied = 0
    skipped = 0
    missing = 0

    for row in tqdm(rows, desc="Copying score.abcx files"):
        score_abcx_path = row.get('score_abcx_path', '').strip()

        if not score_abcx_path:
            skipped += 1
            continue

        # Extract piece path
        piece_path = extract_piece_path(score_abcx_path)
        if not piece_path:
            # Not a data/miditsv path (e.g., unpaired data)
            skipped += 1
            continue

        # Source and destination paths
        source = ROOT / "PianoCoRe" / "score" / piece_path / "score.abcx"
        dest = ROOT / score_abcx_path

        # Check if source exists
        if not source.exists():
            missing += 1
            continue

        # Create destination directory
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(source, dest)
        copied += 1

    print(f"\n✓ Copying complete:")
    print(f"  Copied: {copied}")
    print(f"  Skipped: {skipped} (empty or unpaired)")
    print(f"  Missing: {missing} (source not found)")
    print(f"  Total: {len(rows)}")


if __name__ == '__main__':
    main()
