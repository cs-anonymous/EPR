#!/usr/bin/env python3
"""Convert ABCX files from abc_from_xml to flat aligned ABCX structure for PianoCoReS.

This script processes all .abcx files in EPR/data/abc_from_xml and generates:
- abcx/: Original ABCX files (flattened)
- abcx_aligned/: Aligned ABCX files with H/M markers (flattened)

All files are placed in a flat structure (no subdirectories).
"""

import sys
import shutil
from pathlib import Path
from tqdm import tqdm

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aligned_abcx_format import build_orphan_aligned_abcx, AlignedAbcxError


def flatten_filename(input_path: Path, base_dir: Path) -> str:
    """Generate a flat filename from the hierarchical path.

    Example:
        Chopin/Ballades/1/Chopin_Ballades_1.abcx -> Chopin_Ballades_1.abcx
        Bach/Fugue/bwv_846/Bach_Fugue_bwv_846.abcx -> Bach_Fugue_bwv_846.abcx
    """
    # The filename already contains the full identifier
    return input_path.name


def process_abcx_file(
    input_path: Path,
    abcx_dir: Path,
    aligned_dir: Path,
    phrase_size: int = 4
) -> bool:
    """Process a single ABCX file and generate flat structure.

    Args:
        input_path: Path to input .abcx file
        abcx_dir: Output directory for original ABCX files
        aligned_dir: Output directory for aligned ABCX files
        phrase_size: Number of measures per phrase (default: 4)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Generate flat filename
        flat_name = flatten_filename(input_path, input_path.parent.parent.parent)

        # Copy original ABCX to abcx/
        output_abcx = abcx_dir / flat_name
        shutil.copy2(input_path, output_abcx)

        # Generate aligned ABCX content
        aligned_content = build_orphan_aligned_abcx(input_path, phrase_size=phrase_size)

        # Write aligned ABCX to abcx_aligned/
        aligned_name = flat_name.replace('.abcx', '_aligned.abcx')
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
        description='Convert ABCX files to flat aligned ABCX structure'
    )
    parser.add_argument(
        '--input-dir',
        type=Path,
        default=Path('EPR/data/abc_from_xml'),
        help='Input directory containing ABCX files (default: EPR/data/abc_from_xml)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('EPR/PianoCoReS/unpaired_abcx/Asap'),
        help='Output directory (default: EPR/PianoCoReS/unpaired_abcx/Asap)'
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
    abcx_dir = args.output_dir / 'abcx'
    aligned_dir = args.output_dir / 'abcx_aligned'

    if not args.dry_run:
        abcx_dir.mkdir(parents=True, exist_ok=True)
        aligned_dir.mkdir(parents=True, exist_ok=True)

    # Find all ABCX files
    abcx_files = sorted(args.input_dir.rglob('*.abcx'))

    if not abcx_files:
        print(f"No ABCX files found in {args.input_dir}")
        return

    print(f"Found {len(abcx_files)} ABCX files")

    if args.dry_run:
        print("\nFiles to process:")
        for f in abcx_files:
            flat_name = flatten_filename(f, args.input_dir)
            print(f"  {f.relative_to(args.input_dir)} -> {flat_name}")
        return

    # Process files
    print(f"\nProcessing files (phrase_size={args.phrase_size})...")
    print(f"  abcx/         -> {abcx_dir}")
    print(f"  abcx_aligned/ -> {aligned_dir}")
    print()

    success_count = 0
    failed_count = 0

    for abcx_file in tqdm(abcx_files, desc="Converting"):
        if process_abcx_file(abcx_file, abcx_dir, aligned_dir, args.phrase_size):
            success_count += 1
        else:
            failed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Conversion complete!")
    print(f"  ✓ Success: {success_count}")
    print(f"  ✗ Failed:  {failed_count}")
    print(f"  Output:    {args.output_dir}")
    print(f"    - abcx/: {len(list(abcx_dir.glob('*.abcx')))} files")
    print(f"    - abcx_aligned/: {len(list(aligned_dir.glob('*_aligned.abcx')))} files")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
