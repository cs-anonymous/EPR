#!/usr/bin/env python3
"""Convert MAESTRO ABC files to ABCX and aligned ABCX format.

This script processes ABC files from maestro_score_v1_abc and generates:
- original/: Original ABC files (flattened)
- abcx/: Converted ABCX files (flattened)
- abcx_aligned/: Aligned ABCX files with H/M markers (flattened)
"""

import sys
import shutil
import subprocess
from pathlib import Path
from tqdm import tqdm

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aligned_abcx_format import build_orphan_aligned_abcx, AlignedAbcxError


def abc_to_abcx(abc_path: Path, abcx_path: Path) -> bool:
    """Convert ABC to ABCX format using abc2abcx.py.

    Returns True if successful, False otherwise.
    """
    try:
        # Look for abc2abcx.py in the abcx/scripts directory
        abc2abcx_script = SCRIPT_DIR.parent / "abcx" / "scripts" / "abc2abcx.py"

        if not abc2abcx_script.exists():
            print(f"  ✗ abc2abcx.py not found at {abc2abcx_script}")
            return False

        # abc2abcx.py writes output to the same directory as input with .abcx extension
        # So we need to run it and then move the file
        temp_abcx = abc_path.with_suffix('.abcx')

        # Run abc2abcx.py
        result = subprocess.run(
            [sys.executable, str(abc2abcx_script), str(abc_path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            print(f"  ✗ abc2abcx failed: {result.stderr[:100]}")
            return False

        # Check if the temp file was created
        if not temp_abcx.exists():
            print(f"  ✗ abc2abcx did not create output file")
            return False

        # Move the file to the target location
        abcx_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_abcx), str(abcx_path))

        return True

    except subprocess.TimeoutExpired:
        print(f"  ✗ abc2abcx timeout")
        return False
    except Exception as e:
        print(f"  ✗ abc2abcx error: {e}")
        return False


def process_abc_file(
    input_path: Path,
    original_dir: Path,
    abcx_dir: Path,
    aligned_dir: Path,
    phrase_size: int = 4
) -> bool:
    """Process a single ABC file and generate all three outputs.

    Args:
        input_path: Path to input .abc file
        original_dir: Output directory for original ABC files
        abcx_dir: Output directory for ABCX files
        aligned_dir: Output directory for aligned ABCX files
        phrase_size: Number of measures per phrase (default: 4)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Generate flat filename from path
        # e.g., chopin/Op028.abc -> chopin_Op028.abc
        composer = input_path.parent.name
        filename = input_path.name
        flat_name = f"{composer}_{filename}"

        # 1. Copy original ABC to original/
        output_original = original_dir / flat_name
        shutil.copy2(input_path, output_original)

        # 2. Convert ABC to ABCX
        abcx_name = flat_name.replace('.abc', '.abcx')
        output_abcx = abcx_dir / abcx_name

        if not abc_to_abcx(input_path, output_abcx):
            return False

        # 3. Generate aligned ABCX
        aligned_content = build_orphan_aligned_abcx(output_abcx, phrase_size=phrase_size)

        aligned_name = abcx_name.replace('.abcx', '_aligned.abcx')
        output_aligned = aligned_dir / aligned_name
        with open(output_aligned, 'w', encoding='utf-8') as f:
            f.write(aligned_content)

        return True

    except AlignedAbcxError as e:
        print(f"  ✗ {input_path.name}: {e}")
        return False
    except Exception as e:
        print(f"  ✗ {input_path.name}: Unexpected error: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert MAESTRO ABC files to ABCX structure'
    )
    parser.add_argument(
        '--input-dir',
        type=Path,
        default=Path('EPR/data/maestro_score_v1_abc'),
        help='Input directory (default: EPR/data/maestro_score_v1_abc)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('EPR/PianoCoReS/unpaired_abcx/MAESTRO'),
        help='Output directory (default: EPR/PianoCoReS/unpaired_abcx/MAESTRO)'
    )
    parser.add_argument(
        '--phrase-size',
        type=int,
        default=4,
        help='Number of measures per phrase (default: 4)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='List files without processing'
    )

    args = parser.parse_args()

    # Create output directories
    original_dir = args.output_dir / 'original'
    abcx_dir = args.output_dir / 'abcx'
    aligned_dir = args.output_dir / 'abcx_aligned'

    if not args.dry_run:
        original_dir.mkdir(parents=True, exist_ok=True)
        abcx_dir.mkdir(parents=True, exist_ok=True)
        aligned_dir.mkdir(parents=True, exist_ok=True)

    # Find all ABC files
    abc_files = sorted(args.input_dir.rglob('*.abc'))

    if not abc_files:
        print(f"No ABC files found in {args.input_dir}")
        return

    print(f"Found {len(abc_files)} ABC files")

    if args.dry_run:
        print("\nFiles to process:")
        for f in abc_files:
            composer = f.parent.name
            print(f"  {composer}/{f.name}")
        return

    # Process files
    print(f"\nProcessing files (phrase_size={args.phrase_size})...")
    print(f"  original/     -> {original_dir}")
    print(f"  abcx/         -> {abcx_dir}")
    print(f"  abcx_aligned/ -> {aligned_dir}")
    print()

    success_count = 0
    failed_count = 0

    for abc_file in tqdm(abc_files, desc="Converting"):
        if process_abc_file(abc_file, original_dir, abcx_dir, aligned_dir, args.phrase_size):
            success_count += 1
        else:
            failed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Conversion complete!")
    print(f"  ✓ Success: {success_count}")
    print(f"  ✗ Failed:  {failed_count}")
    print(f"  Output:    {args.output_dir}")
    print(f"    - original/: {len(list(original_dir.glob('*.abc')))} files")
    print(f"    - abcx/: {len(list(abcx_dir.glob('*.abcx')))} files")
    print(f"    - abcx_aligned/: {len(list(aligned_dir.glob('*_aligned.abcx')))} files")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
