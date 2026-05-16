#!/usr/bin/env python3
"""Fix broken ABCX files that retained stacked voice blocks instead of
interleaved ABCX format.

Root cause: `w:` (lyric) lines in stacked-voice ABC files were treated as
music content by the interleaver, creating extra voice rows that didn't align
with the actual instrumental voices.

Fix: strip lyric lines, then re-pass through `to_standard_abcx`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Wire up import paths
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "xml2abc"))
sys.path.insert(0, str(_ROOT / "abcx" / "scripts"))
sys.path.insert(0, str(_ROOT))

from xml_to_abcx import clean_for_abcjs  # noqa: E402
from abc2abcx import to_standard_abcx, AbcError  # noqa: E402

# Lines to strip — lyric / syllable lines that are not instrumental music.
_LYRIC_RE = re.compile(r"^[sSwW]:", re.MULTILINE)


def _strip_lyrics(text: str) -> str:
    """Remove all w:/W:/s:/S: lyric lines."""
    lines = text.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if re.match(r"^[sSwW]:", s):
            continue
        out.append(line)
    return "\n".join(out)


def fix_one_abcx(path: Path) -> tuple[bool, str]:
    """Fix a single ABCX file. Returns (ok, message)."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"read error: {e}"

    # Check if already has interleaved format
    in_body = False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("K:"):
            in_body = True
            continue
        if in_body and s and not s.startswith("%") and not re.match(r"^[A-Z]:", s):
            if " ; " in s:
                # Already interleaved — skip
                return True, "already interleaved"
            break

    # Strip lyric lines and re-convert
    cleaned = _strip_lyrics(text)

    # Pipeline: cleaned ABC → clean_for_abcjs → to_standard_abcx
    try:
        abc_cleaned = clean_for_abcjs(cleaned)
        abcx_text = to_standard_abcx(abc_cleaned, validate=False)
    except AbcError as e:
        return False, f"ABCX validation: {e}"
    except Exception as e:
        return False, f"convert: {e}"

    # Verify output has interleaved format
    has_interleave = False
    for line in abcx_text.split("\n"):
        s = line.strip()
        if s.startswith("K:"):
            continue
        if s and not s.startswith("%") and not re.match(r"^[A-Z]:", s):
            if " ; " in s:
                has_interleave = True
            break

    if not has_interleave:
        return False, "still no interleaving after fix"

    if not abcx_text.endswith("\n"):
        abcx_text += "\n"

    path.write_text(abcx_text, encoding="utf-8")
    return True, "fixed"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix stacked-voice ABCX files")
    ap.add_argument("input", help="ABCX file or directory to scan")
    ap.add_argument("--force", action="store_true",
                    help="Reconvert even if already interleaved")
    args = ap.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if input_path.is_file():
        files = [input_path]
    else:
        files = sorted(input_path.rglob("*.abcx"))

    ok = failed = skipped = 0
    for i, f in enumerate(files, 1):
        if not args.force:
            # Quick check: skip if already interleaved
            try:
                text = f.read_text(encoding="utf-8")
                has = False
                for line in text.split("\n"):
                    s = line.strip()
                    if s.startswith("K:"):
                        has = True
                        continue
                    if has and s and not s.startswith("%") and not re.match(r"^[A-Z]:", s):
                        has = " ; " in s
                        break
                if has:
                    skipped += 1
                    continue
            except Exception:
                pass

        result, msg = fix_one_abcx(f)
        if result:
            ok += 1
        else:
            failed += 1
            print(f"  FAIL: {f}: {msg}", file=sys.stderr)

        if i % 100 == 0 or i == len(files):
            status = f"[{i}/{len(files)}] ok={ok} failed={failed} skipped={skipped}"
            print(status)

    print(f"\nDone: {ok} fixed, {failed} failed, {skipped} skipped, {len(files)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
