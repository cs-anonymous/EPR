#!/usr/bin/env python3
"""Copy ASAP original MusicXML files to unpaired_abcx/ASAP/original directory."""

import shutil
from pathlib import Path
from tqdm import tqdm


def get_flat_name_from_path(xml_path: Path, asap_root: Path) -> str:
    """Generate flat filename from ASAP path structure.

    Example:
        Mozart/Piano_Sonatas/8-1/xml_score.musicxml
        -> Mozart_Piano_Sonatas_8-1.musicxml
    """
    rel_path = xml_path.relative_to(asap_root)
    parts = list(rel_path.parts[:-1])  # Exclude xml_score.musicxml

    # Join parts with underscore
    flat_name = '_'.join(parts) + '.musicxml'

    return flat_name


def main():
    asap_root = Path('data/asap-dataset')
    output_dir = Path('data/unpaired_abcx/ASAP/original')

    if not asap_root.exists():
        print(f"Error: {asap_root} does not exist")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all MusicXML files
    xml_files = []
    for pattern in ['**/*.xml', '**/*.musicxml', '**/*.mxl']:
        xml_files.extend(asap_root.glob(pattern))

    xml_files = sorted(set(xml_files))

    print(f"Found {len(xml_files)} MusicXML files")
    print(f"Copying to {output_dir}...")

    copied = 0
    for xml_file in tqdm(xml_files, desc="Copying"):
        try:
            flat_name = get_flat_name_from_path(xml_file, asap_root)
            output_path = output_dir / flat_name

            shutil.copy2(xml_file, output_path)
            copied += 1
        except Exception as e:
            print(f"Error copying {xml_file}: {e}")

    print(f"\nCopied {copied}/{len(xml_files)} files")
    print(f"Output: {output_dir}")


if __name__ == '__main__':
    main()
