#!/usr/bin/env python3
"""Convert ABCX files from abc_from_xml to aligned ABCX format for data.

This script processes all .abcx files in EPR/data/abc_from_xml and generates
aligned.abcx files in EPR/data/unpaired_abcx/Asap.
"""

import sys
from pathlib import Path
from tqdm import tqdm

# Add scripts directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aligned_abcx_format import build_orphan_aligned_abcx, AlignedAbcxError


def process_abcx_file(input_path: Path, output_dir: Path, phrase_size: int = 4) -> bool:
    """Process a single ABCX file and generate aligned ABCX.

    Args:
        input_path: Path to input .abcx file
        output_dir: Output directory for aligned files
        phrase_size: Number of measures per phrase (default: 4)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Generate aligned ABCX content
        aligned_content = build_orphan_aligned_abcx(input_path, phrase_size=phrase_size)

        # Determine output path
        # Keep the directory structure: Composer/Piece/file_aligned.abcx
        rel_path = input_path.relative_to(input_path.parent.parent.parent)
        output_path = output_dir / rel_path.parent / f"{input_path.stem}_aligned.abcx"

        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write aligned ABCX
        with open(output_path, 'w', encoding='utf-8') as f:
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
        description='Convert ABCX files to aligned ABCX format'
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
        default=Path('EPR/data/unpaired_abcx/Asap'),
        help='Output directory (default: EPR/data/unpaired_abcx/Asap)'
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

    # Find all ABCX files
    abcx_files = sorted(args.input_dir.rglob('*.abcx'))

    if not abcx_files:
        print(f"No ABCX files found in {args.input_dir}")
        return

    print(f"Found {len(abcx_files)} ABCX files")

    if args.dry_run:
        print("\nFiles to process:")
        for f in abcx_files:
            print(f"  {f.relative_to(args.input_dir)}")
        return

    # Process files
    print(f"\nProcessing files (phrase_size={args.phrase_size})...")
    success_count = 0
    failed_count = 0

    for abcx_file in tqdm(abcx_files, desc="Converting"):
        if process_abcx_file(abcx_file, args.output_dir, args.phrase_size):
            success_count += 1
        else:
            failed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Conversion complete!")
    print(f"  ✓ Success: {success_count}")
    print(f"  ✗ Failed:  {failed_count}")
    print(f"  Output:    {args.output_dir}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
