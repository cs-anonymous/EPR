#!/usr/bin/env python3
"""Convert IMSLP MusicXML files to ABCX and aligned ABCX format.

This script processes MusicXML files from IMSLP_Mannual and generates:
- original/: Original MusicXML files (flattened)
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


def xml_to_abcx(xml_path: Path, abcx_path: Path) -> bool:
    """Convert MusicXML to ABCX format using xml_to_abcx.py.

    Returns True if successful, False otherwise.
    """
    try:
        # Look for xml_to_abcx.py in the parent directory
        xml_to_abcx_script = SCRIPT_DIR.parent / "xml_to_abcx.py"

        if not xml_to_abcx_script.exists():
            print(f"  ✗ xml_to_abcx.py not found at {xml_to_abcx_script}")
            return False

        # Run xml_to_abcx.py
        abcx_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(xml_to_abcx_script), str(xml_path), "-o", str(abcx_path)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            # Check if file was created despite error
            if not abcx_path.exists() or abcx_path.stat().st_size == 0:
                return False

        return abcx_path.exists() and abcx_path.stat().st_size > 0

    except subprocess.TimeoutExpired:
        print(f"  ✗ xml_to_abcx timeout")
        return False
    except Exception as e:
        print(f"  ✗ xml_to_abcx error: {e}")
        return False


def process_xml_file(
    input_path: Path,
    original_dir: Path,
    abcx_dir: Path,
    aligned_dir: Path,
    phrase_size: int = 4
) -> bool:
    """Process a single MusicXML file and generate all three outputs.

    Args:
        input_path: Path to input .xml/.mxl file
        original_dir: Output directory for original MusicXML files
        abcx_dir: Output directory for ABCX files
        aligned_dir: Output directory for aligned ABCX files
        phrase_size: Number of measures per phrase (default: 4)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Generate flat filename from path
        # e.g., johann_sebastian_bach/bwv0911/file.mxl -> bach_bwv0911_file.mxl
        parts = input_path.relative_to(input_path.parent.parent.parent).parts
        if len(parts) >= 3:
            composer = parts[0].split('_')[-1] if '_' in parts[0] else parts[0]
            piece = parts[1]
            filename = input_path.name
            flat_name = f"{composer}_{piece}_{filename}"
        else:
            flat_name = input_path.name

        # 1. Copy original MusicXML to original/
        output_original = original_dir / flat_name
        shutil.copy2(input_path, output_original)

        # 2. Convert MusicXML to ABCX
        abcx_name = flat_name.rsplit('.', 1)[0] + '.abcx'
        output_abcx = abcx_dir / abcx_name

        if not xml_to_abcx(input_path, output_abcx):
            return False

        # 3. Generate aligned ABCX
        aligned_content = build_orphan_aligned_abcx(output_abcx, phrase_size=phrase_size)

        aligned_name = abcx_name.replace('.abcx', '_aligned.abcx')
        output_aligned = aligned_dir / aligned_name
        with open(output_aligned, 'w', encoding='utf-8') as f:
            f.write(aligned_content)

        return True

    except AlignedAbcxError as e:
        # Silently skip alignment errors
        return False
    except Exception as e:
        # Silently skip other errors
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert IMSLP MusicXML files to ABCX structure'
    )
    parser.add_argument(
        '--input-dir',
        type=Path,
        default=Path('EPR/data/IMSLP_Mannual'),
        help='Input directory (default: EPR/data/IMSLP_Mannual)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('EPR/data/unpaired_abcx/IMSLP'),
        help='Output directory (default: EPR/data/unpaired_abcx/IMSLP)'
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
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of files to process (for testing)'
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

    # Find all MusicXML files (exclude scan.xml files)
    xml_files = []
    for pattern in ['*.mxl', '*.xml', '*.musicxml']:
        xml_files.extend(args.input_dir.rglob(pattern))

    # Filter out scan.xml files
    xml_files = [f for f in xml_files if 'scan.xml' not in f.name]
    xml_files = sorted(xml_files)

    if args.limit:
        xml_files = xml_files[:args.limit]

    if not xml_files:
        print(f"No MusicXML files found in {args.input_dir}")
        return

    print(f"Found {len(xml_files)} MusicXML files")

    if args.dry_run:
        print("\nFiles to process:")
        for f in xml_files[:20]:
            print(f"  {f.relative_to(args.input_dir)}")
        if len(xml_files) > 20:
            print(f"  ... and {len(xml_files) - 20} more")
        return

    # Process files
    print(f"\nProcessing files (phrase_size={args.phrase_size})...")
    print(f"  original/     -> {original_dir}")
    print(f"  abcx/         -> {abcx_dir}")
    print(f"  abcx_aligned/ -> {aligned_dir}")
    print()

    success_count = 0
    failed_count = 0

    for xml_file in tqdm(xml_files, desc="Converting"):
        if process_xml_file(xml_file, original_dir, abcx_dir, aligned_dir, args.phrase_size):
            success_count += 1
        else:
            failed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Conversion complete!")
    print(f"  ✓ Success: {success_count}")
    print(f"  ✗ Failed:  {failed_count}")
    print(f"  Output:    {args.output_dir}")
    print(f"    - original/: {len(list(original_dir.glob('*')))} files")
    print(f"    - abcx/: {len(list(abcx_dir.glob('*.abcx')))} files")
    print(f"    - abcx_aligned/: {len(list(aligned_dir.glob('*_aligned.abcx')))} files")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
