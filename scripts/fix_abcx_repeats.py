#!/usr/bin/env python3
"""
Fix ABCX files where `::` repeat markers are embedded within measure content
instead of acting as proper measure boundaries.

Problem:
  MXL-to-ABCX conversion can produce segments like:
    [FAd]6 ; D,2 A,,2 D,,2 :: fg ; D,2

  Here `::` is a volta boundary embedded inside a |...| segment.
  The "before ::" content belongs to the first ending measure,
  the "after ::" content belongs to the second ending measure.

  Correct output:
    [FAd]6 ; D,2 A,,2 D,,2 :: | fg ; D,2

Strategy:
  1. Split ABCX body on `|` to get raw segments.
  2. For segments containing `::`, find the position of the first `::`.
     Everything before `::` (across all voices, including full voice
     content before the `::`-containing voice) goes to the first measure.
     Everything after `::` (including voice content after the `::`-containing
     voice) goes to the second measure.
  3. First measure gets ` ::` suffix (phrase-closer marker).
"""

import argparse
import re
from pathlib import Path


def fix_abcx_file(abcx_path: Path, output_path: Path | None = None) -> None:
    """Read an ABCX file, fix embedded `::` markers, write corrected output."""
    if output_path is None:
        output_path = abcx_path

    with open(abcx_path, encoding="utf-8") as f:
        lines = [line.rstrip("\n").rstrip() for line in f]

    # Find header end (K: line)
    header_end = None
    for i, line in enumerate(lines):
        if line.startswith("K:"):
            header_end = i
            break
    if header_end is None:
        print(f"  Skipping {abcx_path}: no K: line found")
        return

    header = lines[: header_end + 1]
    body_text = " ".join(lines[header_end + 1 :]).strip()

    # Split body on `|` to get raw segments
    segments = [s.strip() for s in body_text.split("|") if s.strip()]

    # Process each segment
    fixed_measures = []
    for seg in segments:
        if "::" not in seg:
            # No repeat markers — keep as-is
            fixed_measures.append(seg)
            continue

        # Split on ALL `::` occurrences in the segment.
        # Each `::` marks a volta boundary between first and second endings.
        # We process iteratively: split on first `::`, add before+after,
        # then if after-text still has `::`, split again.
        pending = [seg]
        while pending:
            current = pending.pop(0)
            if "::" not in current:
                fixed_measures.append(current)
                continue

            dd_idx = current.index("::")
            before_text = current[:dd_idx].strip()
            after_text = current[dd_idx + 2 :].strip()

            if before_text:
                fixed_measures.append(before_text + " ::")
            if after_text:
                pending.insert(0, after_text)

    # Reconstruct ABCX with line wrapping
    reconstructed = _reconstruct_body(fixed_measures)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        for line in header:
            f.write(line + "\n")
        f.write(reconstructed + "\n")

    # Report changes
    orig_count = len(segments)
    new_count = len(fixed_measures)
    if new_count != orig_count:
        print(f"  {abcx_path.name}: {orig_count} -> {new_count} measures (+{new_count - orig_count})")


def _reconstruct_body(measures: list[str], max_line_len: int = 100) -> str:
    """Rejoin measures into lines, breaking on `|` at reasonable positions."""
    lines = []
    current = ""
    for m in measures:
        candidate = current + (" | " if current else "") + m
        if len(candidate) > max_line_len and current:
            lines.append(current)
            current = m
        else:
            current = candidate

    if current:
        lines.append(current)

    return " |\n".join(lines) + " |" if lines else ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix ABCX files with embedded :: repeat markers in measure content"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="ABCX files to fix",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Input directory to search for *.abcx files recursively",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: overwrite in-place)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report changes, don't modify files",
    )
    args = parser.parse_args()

    files = list(args.files) if args.files else []

    if args.input_dir:
        input_dir = Path(args.input_dir)
        files.extend(input_dir.rglob("*.abcx"))

    if not files:
        parser.error("No ABCX files specified. Use positional args or --input-dir.")

    total_changes = 0
    for f in sorted(set(str(p) for p in files)):
        fpath = Path(f)
        if not fpath.exists():
            print(f"  Skipping {f}: file not found")
            continue

        if args.dry_run:
            # Just count
            with open(fpath, encoding="utf-8") as fh:
                lines = [line.rstrip() for line in fh]
            body_start = None
            for i, line in enumerate(lines):
                if line.startswith("K:"):
                    body_start = i + 1
                    break
            if body_start is not None:
                body_text = " ".join(lines[body_start:])
                segments = [s.strip() for s in body_text.split("|") if s.strip()]
                has_issue = sum(1 for s in segments if "::" in s)
                if has_issue:
                    total_changes += 1
                    print(f"  {fpath.name}: {has_issue} measures with embedded ::")
        else:
            if args.output_dir:
                if args.input_dir:
                    output = Path(args.output_dir) / fpath.relative_to(args.input_dir)
                else:
                    output = Path(args.output_dir) / fpath.name
            else:
                output = fpath
            output.parent.mkdir(parents=True, exist_ok=True)
            fix_abcx_file(fpath, output)

    if args.dry_run:
        print(f"\nFound {total_changes} files needing fixes")
    else:
        print(f"\nDone")


if __name__ == "__main__":
    main()
