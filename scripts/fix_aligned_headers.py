#!/usr/bin/env python3
"""Fix aligned.abcx files by copying missing header fields from source ABCX files.

This script ensures that aligned.abcx files contain all the metadata from
the original ABCX files (C:, Q:, T:, etc.).
"""

import sys
from pathlib import Path
from tqdm import tqdm


def extract_header_fields(abcx_path: Path) -> dict:
    """Extract all header fields from an ABCX file."""
    headers = {}

    try:
        with open(abcx_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()

                # Stop at body content
                if stripped.startswith('<H>') or stripped.startswith('<M>'):
                    break

                # Stop at first measure bar or voice content
                if not stripped or '|' in stripped:
                    if 'K:' in headers:  # Already found K:, so we're past header
                        break

                # Extract header fields
                for prefix in ['X:', 'T:', 'C:', 'Z:', 'L:', 'Q:', 'M:', 'K:', 'I:']:
                    if stripped.startswith(prefix):
                        field = prefix[0]
                        if field not in headers:
                            headers[field] = []
                        headers[field].append(line.rstrip())
                        break

    except Exception as e:
        print(f"Error reading {abcx_path}: {e}")

    return headers


def fix_aligned_abcx(abcx_path: Path, aligned_path: Path) -> bool:
    """Fix aligned.abcx by copying missing headers from source ABCX."""

    if not abcx_path.exists() or not aligned_path.exists():
        return False

    # Extract headers from source
    source_headers = extract_header_fields(abcx_path)

    # Read aligned file
    try:
        with open(aligned_path, 'r', encoding='utf-8') as f:
            aligned_lines = [line.rstrip() for line in f]
    except Exception as e:
        print(f"Error reading {aligned_path}: {e}")
        return False

    # Find where to insert missing headers (after K:)
    k_index = None
    for i, line in enumerate(aligned_lines):
        if line.startswith('K:'):
            k_index = i
            break

    if k_index is None:
        return False

    # Build new header
    new_lines = []
    seen_fields = set()

    # Copy existing lines up to and including K:
    for i in range(k_index + 1):
        line = aligned_lines[i]
        new_lines.append(line)
        if line and line[0] in 'XTCZLQMKI':
            seen_fields.add(line[0])

    # Insert missing fields before K: (in correct order)
    insert_lines = []
    field_order = ['X', 'T', 'C', 'Z', 'L', 'Q', 'M', 'I', 'K']

    for field in field_order:
        if field in source_headers and field not in seen_fields:
            insert_lines.extend(source_headers[field])

    # If we have lines to insert, rebuild the header
    if insert_lines:
        new_lines = []

        # Add all fields in order
        for field in field_order:
            if field in source_headers:
                new_lines.extend(source_headers[field])

        # Add rest of aligned file (body)
        new_lines.extend(aligned_lines[k_index + 1:])
    else:
        # No changes needed
        return True

    # Write fixed file
    try:
        with open(aligned_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines) + '\n')
        return True
    except Exception as e:
        print(f"Error writing {aligned_path}: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix aligned.abcx files by copying headers from source ABCX'
    )
    parser.add_argument(
        '--dataset-dir',
        type=Path,
        required=True,
        help='Dataset directory (e.g., PianoCoReS/unpaired_abcx/IMSLP)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be fixed without making changes'
    )

    args = parser.parse_args()

    abcx_dir = args.dataset_dir / 'abcx'
    aligned_dir = args.dataset_dir / 'abcx_aligned'

    if not abcx_dir.exists() or not aligned_dir.exists():
        print(f"Error: {abcx_dir} or {aligned_dir} does not exist")
        return

    # Find all aligned files
    aligned_files = sorted(aligned_dir.glob('*_aligned.abcx'))

    if not aligned_files:
        print(f"No aligned files found in {aligned_dir}")
        return

    print(f"Found {len(aligned_files)} aligned files")

    if args.dry_run:
        print("\nDry run mode - no changes will be made")

    fixed_count = 0
    error_count = 0

    for aligned_file in tqdm(aligned_files, desc="Fixing headers"):
        # Find corresponding source ABCX
        score_id = aligned_file.name.replace('_aligned.abcx', '')
        abcx_file = abcx_dir / f"{score_id}.abcx"

        if not abcx_file.exists():
            error_count += 1
            continue

        if args.dry_run:
            # Just check if headers are missing
            source_headers = extract_header_fields(abcx_file)
            aligned_headers = extract_header_fields(aligned_file)

            missing = []
            for field in ['C', 'Q']:
                if field in source_headers and field not in aligned_headers:
                    missing.append(field)

            if missing:
                print(f"  {aligned_file.name}: missing {', '.join(missing)}")
                fixed_count += 1
        else:
            if fix_aligned_abcx(abcx_file, aligned_file):
                fixed_count += 1
            else:
                error_count += 1

    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"Would fix: {fixed_count} files")
    else:
        print(f"Fixed: {fixed_count} files")
    print(f"Errors: {error_count}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
