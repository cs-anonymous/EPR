#!/usr/bin/env python3
"""Remove inline MIDI-TSV marker events from aligned performance TSV files.

This strips only event markers shaped like ``M:<offset>:"..."``. Measure
headers such as ``M1:`` and ``M23:`` are left untouched.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


INLINE_MARKER_RE = re.compile(r'\s+M:\d+:"[^"\n]*"')
LEADING_INLINE_MARKER_RE = re.compile(r'^M:\d+:"[^"\n]*"\s*')


def strip_markers(text: str) -> tuple[str, int]:
    leading_matches = len(LEADING_INLINE_MARKER_RE.findall(text))
    text = LEADING_INLINE_MARKER_RE.sub("", text)
    inline_matches = len(INLINE_MARKER_RE.findall(text))
    text = INLINE_MARKER_RE.sub("", text)
    return text, leading_matches + inline_matches


def iter_tsv_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.mid.tsv"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("PianoCoReS/aligned"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.root.exists():
        raise FileNotFoundError(args.root)

    files_seen = 0
    files_changed = 0
    markers_removed = 0
    bytes_removed = 0

    for path in iter_tsv_files(args.root):
        files_seen += 1
        original = path.read_text(encoding="utf-8")
        cleaned, removed = strip_markers(original)
        if not removed:
            continue
        files_changed += 1
        markers_removed += removed
        bytes_removed += len(original.encode("utf-8")) - len(cleaned.encode("utf-8"))
        if not args.dry_run:
            path.write_text(cleaned, encoding="utf-8")

    mode = "DRY RUN" if args.dry_run else "UPDATED"
    print(f"{mode}: scanned {files_seen:,} files")
    print(f"files_changed={files_changed:,}")
    print(f"markers_removed={markers_removed:,}")
    print(f"bytes_removed={bytes_removed:,}")


if __name__ == "__main__":
    main()
