#!/usr/bin/env python3
"""Batch convert Score MIDI → ABCX → validate via abc2abcx.

Organizes output by composer under /home/sy/2026/Music/EPR/abcx/
"""

import os
import sys
import shutil
from pathlib import Path

# Add paths
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "abcx" / "scripts"))

from midi_to_abcx import midi_to_abcx

# Import validation functions from abc2abcx
try:
    from abc2abcx import to_standard_abcx, AbcError
except ImportError:
    print("ERROR: Cannot import abc2abcx.py")
    sys.exit(1)


BASE_DIR = "/home/sy/2026/Music/data/audio_symbolic_alignment/asap-dataset"
OUT_DIR = "/home/sy/2026/Music/EPR/abcx"


def collect_midi_files():
    """Collect all midi_score.mid files, returning list of (composer_subdir, midi_path)."""
    files = []
    for root, dirs, fnames in os.walk(BASE_DIR):
        if "midi_score.mid" in fnames:
            midi_path = os.path.join(root, "midi_score.mid")
            # Relative path like "Bach/Fugue/bwv_846"
            rel = os.path.relpath(root, BASE_DIR)
            parts = rel.split(os.sep)
            composer = parts[0]  # e.g., "Bach"
            files.append((composer, rel, midi_path))
    files.sort()
    return files


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    files = collect_midi_files()
    print(f"Found {len(files)} MIDI files")

    ok = 0
    failed_convert = 0
    failed_validate = 0
    skipped = 0
    failures = []

    for composer, rel, midi_path in files:
        # Output: abcx/{Composer}/{rel}.abcx
        out_subdir = os.path.join(OUT_DIR, composer, *rel.split(os.sep)[1:])
        os.makedirs(out_subdir, exist_ok=True)
        name = rel.replace(os.sep, "_")
        out_path = os.path.join(out_subdir, f"{name}.abcx")

        # Skip if already exists and is non-empty
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            print(f"  SKIP (exists): {name}")
            skipped += 1
            # Still validate existing file
            try:
                source = open(out_path).read()
                to_standard_abcx(source, validate=True)
                ok += 1
            except AbcError as e:
                failed_validate += 1
                failures.append((name, "validate_existing", str(e)))
            continue

        # Convert
        try:
            abc = midi_to_abcx(midi_path)
        except Exception as e:
            failed_convert += 1
            failures.append((name, "convert", str(e)))
            print(f"  CONVERT FAIL: {name}: {e}")
            continue

        # Write
        with open(out_path, "w") as f:
            f.write(abc + "\n")

        # Validate
        try:
            to_standard_abcx(abc, validate=True)
            ok += 1
            print(f"  OK: {name}")
        except AbcError as e:
            failed_validate += 1
            failures.append((name, "validate", str(e)))
            print(f"  VALIDATE FAIL: {name}: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  OK:           {ok}")
    print(f"  Skipped:      {skipped} (already existed)")
    print(f"  Convert fail: {failed_convert}")
    print(f"  Validate fail:{failed_validate}")
    print(f"  Total:        {len(files)}")

    if failures:
        print(f"\n{'='*60}")
        print("Failures:")
        for name, stage, msg in failures:
            print(f"  [{stage}] {name}: {msg[:120]}")

    # List output structure
    print(f"\n{'='*60}")
    print("Output structure:")
    for root, dirs, fnames in os.walk(OUT_DIR):
        level = root.replace(OUT_DIR, "").count(os.sep)
        indent = "  " * level
        if fnames:
            print(f"{indent}{os.path.basename(root)}/ ({len(fnames)} files)")
        elif level > 0:
            print(f"{indent}{os.path.basename(root)}/")


if __name__ == "__main__":
    main()
