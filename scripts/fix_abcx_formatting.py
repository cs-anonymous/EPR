#!/usr/bin/env python3
"""Fix formatting issues in existing ABCX files by reconverting them.

This script reads existing ABCX files and passes them through abc_to_abcx()
to apply the three formatting fixes:
1. Grand staff format for 2-staff piano scores
2. Tempo marks moved to header
3. Space between bar lines and inline fields
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "abcx" / "scripts"))

from abc2abcx import to_standard_abcx

def fix_abcx_file(abcx_path: Path) -> bool:
    """Fix formatting in an ABCX file by reconverting it."""
    try:
        # Read the existing ABCX file
        abcx_text = abcx_path.read_text(encoding="utf-8")

        # Pass it through the converter to apply fixes
        fixed_text = to_standard_abcx(abcx_text, validate=False)

        # Write it back
        abcx_path.write_text(
            fixed_text if fixed_text.endswith("\n") else fixed_text + "\n",
            encoding="utf-8",
        )
        return True
    except Exception as e:
        print(f"FAIL: {abcx_path}: {e}", file=sys.stderr)
        return False

def main():
    root = Path("PianoCoRe/score").resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        return 1

    files = sorted(root.rglob("score.abcx"))
    ok = 0
    failed = 0

    for i, abcx_path in enumerate(files, 1):
        if fix_abcx_file(abcx_path):
            ok += 1
        else:
            failed += 1

        if i % 100 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] ok={ok} failed={failed}", file=sys.stderr)

    print(f"Done: {ok} ok, {failed} failed, {len(files)} total", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
