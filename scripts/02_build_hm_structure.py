#!/usr/bin/env python3
"""Step 2: Build H/M structure and write aligned ABCX.

This script:
1. Reads score.abcx and score MIDI
2. Extracts measure grid from MIDI timing
3. Maps ABCX content to MIDI measures
4. Groups measures into phrases (H)
5. Outputs score_structure.json
6. Writes score_aligned.abcx with H/M markers

Input:
  - data/miditsv/Composer/Piece/score.abcx
  - PianoCoRe/raw/Composer/Piece/score_*.mid

Output:
  - data/miditsv/Composer/Piece/score_structure.json
  - data/miditsv/Composer/Piece/score_aligned.abcx
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts import align_score_performance as asp
    from scripts.aligned_abcx_format import AlignedAbcxError, build_orphan_aligned_abcx
except ModuleNotFoundError:
    import align_score_performance as asp
    from aligned_abcx_format import AlignedAbcxError, build_orphan_aligned_abcx


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_METADATA = ROOT / "data" / "score_metadata.csv"
DEFAULT_PIANOCORE_ROOT = ROOT / "PianoCoRe"

_worker_midi_tsv = None


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def nonempty(value: str | None) -> bool:
    return bool(value and str(value).strip())


def selected_score_rel(row: dict[str, str]) -> str:
    for key in ("refined_score_midi_path", "score_midi_path"):
        value = row.get(key, "")
        if nonempty(value):
            return str(value).strip()
    return ""


def score_midi_path(score_rel: str, pianocore_root: Path) -> Path:
    root = pianocore_root if pianocore_root.is_absolute() else ROOT / pianocore_root
    if "_refined" in score_rel or "_mini" in score_rel:
        return root / "refined" / score_rel
    return root / "raw" / score_rel


def raw_score_midi_path(score_rel: str, score_midi: Path, pianocore_root: Path) -> Path:
    root = pianocore_root if pianocore_root.is_absolute() else ROOT / pianocore_root
    raw_rel = score_rel.replace("_refined.mid", ".mid")
    raw_root = root / ("refined" if "_refined" in raw_rel or "_mini" in raw_rel else "raw")
    candidate = raw_root / raw_rel
    return candidate if candidate.exists() else score_midi


def process_row(row: dict[str, str], pianocore_root: Path) -> dict[str, object]:
    """Build H/M structure and write aligned ABCX for one score."""
    source_abcx = resolve_path(row.get("score_abcx_path", ""))
    if not source_abcx.is_file():
        return {"ok": False, "kind": "missing_abcx", "path": str(source_abcx)}

    json_path_value = row.get("score_json_path", "")
    if not nonempty(json_path_value):
        return {"ok": False, "kind": "missing_json_path", "path": str(source_abcx)}
    json_path = resolve_path(json_path_value)

    aligned_path = row.get("score_aligned_path", "")
    if not nonempty(aligned_path):
        return {"ok": False, "kind": "missing_aligned_path", "path": str(source_abcx)}
    aligned_abcx = resolve_path(aligned_path)

    score_rel = selected_score_rel(row)

    # Handle orphan scores (no MIDI)
    if not score_rel:
        try:
            aligned_abcx.parent.mkdir(parents=True, exist_ok=True)
            aligned_abcx.write_text(build_orphan_aligned_abcx(source_abcx), encoding="utf-8")
            return {"ok": True, "kind": "orphan_aligned", "path": str(aligned_abcx)}
        except AlignedAbcxError as exc:
            return {"ok": False, "kind": "orphan_failed", "path": str(source_abcx), "error": str(exc)}

    if _worker_midi_tsv is None:
        return {"ok": False, "kind": "worker_not_initialized", "path": str(source_abcx)}

    midi_path = score_midi_path(score_rel, pianocore_root)
    if not midi_path.is_file():
        return {"ok": False, "kind": "missing_score_midi", "path": str(midi_path)}

    mapping_source = raw_score_midi_path(score_rel, midi_path, pianocore_root)
    structure = asp.build_score_structure_from_paths(
        midi_path,
        source_abcx,
        _worker_midi_tsv,
        mapping_source=mapping_source,
    )
    if structure is None:
        return {"ok": False, "kind": "structure_failed", "path": str(source_abcx)}

    # Write structure JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "measures": [asdict(m) for m in structure.measures],
                "phrases": [asdict(p) for p in structure.phrases],
                "measure_to_phrase": structure.measure_to_phrase,
                "abcx_measures": structure.abcx_measures,
                "midi_to_abcx": structure.midi_to_abcx,
                "midi_measure_content": {
                    str(k): v for k, v in sorted(structure.midi_measure_content.items())
                },
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )

    # Write aligned ABCX
    aligned_abcx.parent.mkdir(parents=True, exist_ok=True)
    asp.write_aligned_abcx(
        source_abcx,
        aligned_abcx,
        structure.phrases,
        structure.midi_measure_content,
    )

    return {"ok": True, "kind": "structure_and_aligned", "path": str(json_path)}


def _worker_init(pianocore_root: str) -> None:
    global _worker_midi_tsv
    _worker_midi_tsv = asp.load_midi_tsv_module()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Step 2: Build H/M structure from score ABCX and MIDI"
    )
    parser.add_argument(
        "--metadata",
        default=str(DEFAULT_METADATA),
        help="Path to score_metadata.csv",
    )
    parser.add_argument(
        "--pianocore-root",
        default=str(DEFAULT_PIANOCORE_ROOT),
        help="PianoCoRe root directory",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=16,
        help="Number of parallel workers",
    )
    args = parser.parse_args()

    pianocore_root = Path(args.pianocore_root).resolve()
    metadata_path = Path(args.metadata).resolve()

    if not metadata_path.is_file():
        print(f"Error: metadata file not found: {metadata_path}", file=sys.stderr)
        return 1

    # Read metadata
    with metadata_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Processing {len(rows)} scores...")
    print(f"Workers: {args.jobs}")

    # Process in parallel
    results = {"ok": 0, "failed": 0, "by_kind": {}}

    with mp.Pool(processes=args.jobs, initializer=_worker_init, initargs=(str(pianocore_root),)) as pool:
        for result in pool.starmap(process_row, [(row, pianocore_root) for row in rows]):
            kind = result.get("kind", "unknown")
            results["by_kind"][kind] = results["by_kind"].get(kind, 0) + 1
            if result.get("ok"):
                results["ok"] += 1
            else:
                results["failed"] += 1

    print(f"\n✓ Completed:")
    print(f"  Success: {results['ok']}")
    print(f"  Failed: {results['failed']}")
    print(f"\nBreakdown:")
    for kind, count in sorted(results["by_kind"].items()):
        print(f"  {kind}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
