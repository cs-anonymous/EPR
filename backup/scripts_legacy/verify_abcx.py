#!/usr/bin/env python3
"""Verify ABCX files for structural validity.

Checks:
1. No phantom patterns: same non-musical token in both voices (e.g. `1 ; 1`, `: ; :`)
2. Each measure has actual music content in at least one voice
3. No `$` linebreak markers in content
4. No ABC field directives (L:, M:, K:) in body content
5. Volta markers are attached to actual music (not standalone)

Usage:
    python scripts/verify_abcx.py --input-dir PianoCoRe/score
    python scripts/verify_abcx.py --input-dir PianoCoRe/score --piece-filter "Tico"
    python scripts/verify_abcx.py PianoCoRe/score/Composer/Piece/score.abcx
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


# Patterns that indicate invalid ABCX (phantom measures) — these are cases
# where BOTH voice parts of a measure are empty/non-musical tokens.
# NOTE: patterns like `] ; z` are NOT phantoms — they are legitimate cases
# where one voice has a chord ending with `]` and another voice rests (`z`).
PHANTOM_PATTERNS = [
    re.compile(r':\s*;\s*:'),               # : ; :
    re.compile(r'\|\s*;\s*\|'),             # | ; |
    re.compile(r'\]\s*;\s*\]'),             # ] ; ]
]

# Content that should never appear as a standalone measure
FORBID_STANDALONE = re.compile(r'^[LlMmKkQqVvIW]:')


def _parse_abcx_measures(text: str) -> list[tuple[str, str]]:
    """Parse ABCX body into (opening, content) tuples per segment.

    Returns list of (opening_bar, content) for each ABCX segment.
    """
    results = []
    in_body = False
    for line in text.split('\n'):
        s = line.strip()
        if not in_body:
            if s.startswith('K:'):
                in_body = True
            continue
        if not s or s.startswith('%') or re.match(r'^[A-Z]:', s):
            continue
        # Each line is one or more measures.
        # Opening bar (|:, |], |1, etc.) is at the start.
        opening = ''
        content = s
        # Extract opening bar prefix
        bar_m = re.match(r'^(\|[:\]\[]*\d?\s*)', content)
        if bar_m:
            opening = bar_m.group(1).rstrip()
            content = content[bar_m.end():]
        results.append((opening, content))
    return results


def verify_abcx(text: str, path: str = '') -> list[str]:
    """Verify ABCX text for structural validity.

    Returns list of error messages (empty if valid).
    """
    errors: list[str] = []
    prefix = f"{path}: " if path else ""

    # 1. Check for phantom patterns
    for i, line in enumerate(text.split('\n'), 1):
        s = line.strip()
        if not s or s.startswith('%') or s.startswith(('X:', 'T:', 'M:', 'L:', 'Q:', 'K:', 'V:', 'I:', '%%')):
            continue
        # Split by voice separator and check adjacent segments for phantoms.
        # A phantom is when two adjacent segments are both ONLY a digit
        # (orphaned volta marker with no music content).
        parts = s.split(' ; ')
        for j in range(len(parts) - 1):
            a = parts[j].strip()
            b = parts[j + 1].strip()
            if (re.match(r'^\d+(\s*%\s*\d+)?$', a) and
                    re.match(r'^\d+(\s*%\s*\d+)?$', b)):
                errors.append(f"{prefix}line {i}: phantom pattern 'digit ; digit' in: {s[:100]}")
                break
        else:
            # Check other phantom patterns on the full line
            for pat in PHANTOM_PATTERNS:
                if pat.search(s):
                    errors.append(f"{prefix}line {i}: phantom pattern in: {s[:100]}")
                    break

    # 2. Parse body and check each segment
    segments = _parse_abcx_measures(text)
    if not segments:
        errors.append(f"{prefix}no body content found")
        return errors

    for idx, (opening, content) in enumerate(segments):
        # Check for forbidden standalone content
        if FORBID_STANDALONE.match(content.strip()):
            errors.append(f"{prefix}segment {idx+1}: forbidden directive in content: {content[:60]}")

        # Check for $ markers
        if '$' in content:
            errors.append(f"{prefix}segment {idx+1}: $ linebreak marker in content: {content[:60]}")

        # Check for voice separators in wrong place (indicates parsing issue)
        voice_parts = content.split(' ; ')
        for v_idx, part in enumerate(voice_parts):
            part = part.strip()
            if not part:
                errors.append(f"{prefix}segment {idx+1}: voice {v_idx+1} is empty")
            elif part == 'z':
                # Single 'z' rest in one voice is OK if the other voice has music
                other_parts = [p.strip() for j, p in enumerate(voice_parts) if j != v_idx]
                if all(p == 'z' for p in other_parts):
                    errors.append(f"{prefix}segment {idx+1}: all voices are just 'z' rest")

    # 3. Check that %%score header exists
    has_score = '%%score' in text
    if not has_score:
        errors.append(f"{prefix}missing %%score header")

    # 4. Check that body has `;` voice separators
    in_body = False
    has_separator = False
    for line in text.split('\n'):
        s = line.strip()
        if not in_body:
            if s.startswith('K:'): in_body = True
            continue
        if not s or s.startswith('%') or re.match(r'^[A-Z]:', s):
            continue
        if ' ; ' in s:
            has_separator = True
            break
    if not has_separator and segments:
        errors.append(f"{prefix}no voice separators (;) found in body")

    return errors


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify ABCX files for structural validity.")
    parser.add_argument("input", help="ABCX file or root directory to scan.")
    parser.add_argument("--piece-filter", default=None,
                        help="Only check pieces whose path contains this string.")
    args = parser.parse_args(argv)

    input_path = Path(args.input).expanduser().resolve()

    if input_path.is_file():
        files = [input_path]
    else:
        files = sorted(input_path.rglob("*.abcx"))
        if args.piece_filter:
            files = [f for f in files if args.piece_filter in str(f)]

    print(f"Checking {len(files)} ABCX files...")

    ok = 0
    failed = 0
    all_errors: list[tuple[str, list[str]]] = []

    for i, fpath in enumerate(files, 1):
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(files)}] READ ERROR: {fpath}: {e}")
            continue

        errors = verify_abcx(text, str(fpath))
        if errors:
            failed += 1
            all_errors.append((str(fpath), errors))
            print(f"  [{i}/{len(files)}] FAIL: {fpath.name} ({len(errors)} errors)")
        else:
            ok += 1
            if i % 100 == 0 or i == len(files):
                print(f"  [{i}/{len(files)}] ok={ok} failed={failed}")

    print(f"\n{'=' * 60}")
    print(f"Summary: {ok} ok, {failed} failed, {len(files)} total")

    if all_errors:
        print(f"\nFailures:")
        for fpath, errs in all_errors[:20]:
            print(f"\n  {fpath}:")
            for e in errs[:5]:
                print(f"    {e}")
            if len(errs) > 5:
                print(f"    ... and {len(errs) - 5} more")
        if len(all_errors) > 20:
            print(f"\n  ... and {len(all_errors) - 20} more files with errors")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
