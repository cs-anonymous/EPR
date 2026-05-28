#!/usr/bin/env python3
"""Re-convert IMSLP files with proper metadata injection.

This script re-processes IMSLP MusicXML files and injects composer metadata
from filenames into the ABCX headers.
"""

import sys
import re
import subprocess
from pathlib import Path
from tqdm import tqdm

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aligned_abcx_format import build_orphan_aligned_abcx, AlignedAbcxError


# Composer name mapping
COMPOSER_MAP = {
    'bach': 'Johann Sebastian Bach',
    'beethoven': 'Ludwig van Beethoven',
    'chopin': 'Frédéric Chopin',
    'mozart': 'Wolfgang Amadeus Mozart',
    'liszt': 'Franz Liszt',
    'brahms': 'Johannes Brahms',
    'schubert': 'Franz Schubert',
    'schumann': 'Robert Schumann',
    'debussy': 'Claude Debussy',
    'haydn': 'Joseph Haydn',
    'mendelssohn': 'Felix Mendelssohn',
    'grieg': 'Edvard Grieg',
    'tchaikovsky': 'Pyotr Ilyich Tchaikovsky',
    'rachmaninoff': 'Sergei Rachmaninoff',
    'prokofiev': 'Sergei Prokofiev',
    'ravel': 'Maurice Ravel',
    'scriabin': 'Alexander Scriabin',
}


def parse_composer_from_filename(filename: str) -> str:
    """Extract composer name from filename."""
    # e.g., bach_bwv0854_... -> Bach
    parts = filename.split('_')
    if parts:
        composer_key = parts[0].lower()
        return COMPOSER_MAP.get(composer_key, parts[0].title())
    return ''


def parse_work_from_filename(filename: str) -> str:
    """Extract work identifier from filename."""
    # e.g., bach_bwv0854_... -> BWV 854
    parts = filename.split('_')
    if len(parts) >= 2:
        work = parts[1]
        # Format common catalog numbers
        if work.startswith('bwv'):
            return f"BWV {work[3:].lstrip('0')}"
        elif work.startswith('op'):
            return f"Op. {work[2:].lstrip('0')}"
        elif work.startswith('k'):
            return f"K. {work[1:].lstrip('0')}"
        elif work.startswith('d'):
            return f"D. {work[1:].lstrip('0')}"
        return work.upper()
    return ''


def inject_metadata_into_abcx(abcx_path: Path, composer: str, work: str) -> bool:
    """Inject composer and work metadata into ABCX file headers."""
    try:
        with open(abcx_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Find insertion point (after T: and before L:)
        new_lines = []
        inserted = False

        for line in lines:
            new_lines.append(line)

            # Insert after T: line
            if not inserted and line.startswith('T:'):
                if composer:
                    new_lines.append(f'C:{composer}\n')
                if work:
                    new_lines.append(f'Z:{work}\n')
                inserted = True

        # Write back
        with open(abcx_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        return True

    except Exception as e:
        print(f"Error injecting metadata into {abcx_path}: {e}")
        return False


def reconvert_file(
    original_path: Path,
    abcx_dir: Path,
    aligned_dir: Path,
    phrase_size: int = 4
) -> bool:
    """Re-convert a single file with metadata injection."""
    try:
        # Get base filename
        base_name = original_path.stem

        # Parse metadata from filename
        composer = parse_composer_from_filename(base_name)
        work = parse_work_from_filename(base_name)

        # Convert MusicXML to ABCX
        abcx_path = abcx_dir / f"{base_name}.abcx"

        xml_to_abcx_script = SCRIPT_DIR.parent / "xml_to_abcx.py"
        if not xml_to_abcx_script.exists():
            return False

        result = subprocess.run(
            [sys.executable, str(xml_to_abcx_script), str(original_path), "-o", str(abcx_path)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if not abcx_path.exists() or abcx_path.stat().st_size == 0:
            return False

        # Inject metadata
        if not inject_metadata_into_abcx(abcx_path, composer, work):
            return False

        # Generate aligned ABCX
        aligned_content = build_orphan_aligned_abcx(abcx_path, phrase_size=phrase_size)

        aligned_path = aligned_dir / f"{base_name}_aligned.abcx"
        with open(aligned_path, 'w', encoding='utf-8') as f:
            f.write(aligned_content)

        return True

    except (subprocess.TimeoutExpired, AlignedAbcxError):
        return False
    except Exception as e:
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Re-convert IMSLP files with metadata injection'
    )
    parser.add_argument(
        '--dataset-dir',
        type=Path,
        default=Path('data/unpaired_abcx/IMSLP'),
        help='Dataset directory'
    )
    parser.add_argument(
        '--phrase-size',
        type=int,
        default=4,
        help='Number of measures per phrase'
    )

    args = parser.parse_args()

    original_dir = args.dataset_dir / 'original'
    abcx_dir = args.dataset_dir / 'abcx'
    aligned_dir = args.dataset_dir / 'abcx_aligned'

    if not original_dir.exists():
        print(f"Error: {original_dir} does not exist")
        return

    # Find all original files
    original_files = sorted(original_dir.glob('*.mxl'))
    original_files.extend(sorted(original_dir.glob('*.xml')))
    original_files.extend(sorted(original_dir.glob('*.musicxml')))

    if not original_files:
        print(f"No original files found in {original_dir}")
        return

    print(f"Found {len(original_files)} original files")
    print(f"Re-converting with metadata injection...")
    print()

    success_count = 0
    failed_count = 0

    for original_file in tqdm(original_files, desc="Re-converting"):
        if reconvert_file(original_file, abcx_dir, aligned_dir, args.phrase_size):
            success_count += 1
        else:
            failed_count += 1

    print(f"\n{'='*60}")
    print(f"Re-conversion complete!")
    print(f"  ✓ Success: {success_count}")
    print(f"  ✗ Failed:  {failed_count}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
