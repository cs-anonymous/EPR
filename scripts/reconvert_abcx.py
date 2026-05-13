#!/usr/bin/env python3
"""Batch convert all PianoCoRe MXL files to verified ABCX.

Saves output to PianoCoRe/score/<Composer>/<Piece>/score.abcx

Usage:
    python scripts/reconvert_abcx.py --jobs 16
    python scripts/reconvert_abcx.py --jobs 16 --limit 100
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# Path wiring
_HERE = Path(__file__).resolve().parent.parent
_XML2ABC_DIR = _HERE / "xml2abc"
_ABCX_SCRIPTS_DIR = _HERE / "abcx" / "scripts"

for p in (_XML2ABC_DIR, _ABCX_SCRIPTS_DIR):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

import xml2abc  # type: ignore
from abc2abcx import to_standard_abcx, AbcError  # type: ignore

# Import clean_for_abcjs from xml_to_abcx
sys.path.insert(0, str(_HERE))
from xml_to_abcx import _xml2abc_convert, clean_for_abcjs  # type: ignore


def convert_one(mxl_path: Path, output_dir: Path, raw_dir: Path) -> dict:
    """Convert one MXL file to ABCX and verify.

    Returns dict with status info.
    """
    result = {
        "path": str(mxl_path),
        "status": "pending",
        "error": None,
    }
    try:
        # Step 1: MXL -> ABC via xml2abc
        with tempfile.TemporaryDirectory() as tmp:
            abc_path = _xml2abc_convert(mxl_path, Path(tmp))
            abc_text = abc_path.read_text(encoding="utf-8")

        # Step 2: Clean ABC for abcjs compatibility
        cleaned = clean_for_abcjs(abc_text)

        # Step 3: Convert to ABCX
        abcx_text = to_standard_abcx(cleaned)

        # Step 4: Basic verification
        # Check for phantom patterns
        phantoms = []
        for line in abcx_text.split('\n'):
            if '1 ; 1' in line or ': ; :' in line:
                phantoms.append(line[:100])
        if phantoms:
            result["status"] = "phantom"
            result["error"] = f"phantom patterns: {phantoms[:3]}"
            return result

        # Step 5: Write output
        # Preserve full directory structure relative to raw_dir
        rel_path = mxl_path.parent.relative_to(raw_dir)
        out_path = output_dir / rel_path / "score.abcx"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            abcx_text if abcx_text.endswith("\n") else abcx_text + "\n",
            encoding="utf-8",
        )
        result["status"] = "ok"
        result["output"] = str(out_path)
        return result

    except AbcError as e:
        result["status"] = "validate_error"
        result["error"] = str(e)[:200]
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{e} // {traceback.format_exc(limit=1).strip().splitlines()[-1]}"
        return result


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Batch convert MXL to verified ABCX.")
    parser.add_argument("--raw-dir", default=None,
                        help="PianoCoRe raw directory (default: PianoCoRe/raw).")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (default: PianoCoRe/score).")
    parser.add_argument("--jobs", type=int, default=16,
                        help="Number of parallel workers (default: 16).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to first N files.")
    parser.add_argument("--force", action="store_true",
                        help="Force reconvert even if output exists.")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir or "PianoCoRe/raw").expanduser().resolve()
    output_dir = Path(args.output_dir or "PianoCoRe/score").expanduser().resolve()

    if not raw_dir.is_dir():
        print(f"Error: raw directory not found: {raw_dir}", file=sys.stderr)
        return 1

    # Collect all score files (.mxl and .musicxml)
    score_files = sorted(raw_dir.rglob("score.mxl")) + sorted(raw_dir.rglob("score.musicxml"))
    if args.limit:
        score_files = score_files[:args.limit]

    print(f"Found {len(score_files)} score files to convert")
    print(f"Output directory: {output_dir}")
    print(f"Workers: {args.jobs}")

    # Check existing files
    existing = 0
    to_convert = []
    for score in score_files:
        rel_path = score.parent.relative_to(raw_dir)
        out_path = output_dir / rel_path / "score.abcx"
        if out_path.exists() and not args.force:
            existing += 1
        else:
            to_convert.append(score)

    print(f"Already converted: {existing}, need to convert: {len(to_convert)}")

    # Convert
    ok = 0
    failed = 0
    phantom = 0
    validate_error = 0
    failures = []

    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(convert_one, mxl, output_dir, raw_dir): mxl
            for mxl in to_convert
        }

        for i, future in enumerate(as_completed(futures), 1):
            mxl = futures[future]
            try:
                result = future.result()
            except Exception as e:
                failed += 1
                failures.append((str(mxl), f"exception: {e}"))
                if i % 50 == 0 or i == len(to_convert):
                    print(f"  [{i}/{len(to_convert)}] ok={ok} phantom={phantom} "
                          f"validate_error={validate_error} failed={failed}")
                continue

            status = result["status"]
            if status == "ok":
                ok += 1
            elif status == "phantom":
                phantom += 1
                failures.append((result["path"], result["error"] or ""))
            elif status == "validate_error":
                validate_error += 1
            else:
                failed += 1
                failures.append((result["path"], result["error"] or ""))

            if i % 50 == 0 or i == len(to_convert):
                print(f"  [{i}/{len(to_convert)}] ok={ok} phantom={phantom} "
                      f"validate_error={validate_error} failed={failed}")

    print(f"\n{'=' * 60}")
    print(f"Summary: {ok} ok, {phantom} phantom, {validate_error} validate-error, "
          f"{failed} failed, {len(to_convert)} converted")

    if failures:
        print(f"\nFailures ({len(failures)}):")
        for path, err in failures[:20]:
            print(f"  {path}: {err[:120]}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")

    return 0 if (phantom + failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
