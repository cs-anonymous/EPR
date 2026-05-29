#!/usr/bin/env python3
"""Step 3: Write annotated score MIDI TSV.

This script:
1. Reads score_structure.json (from Step 2)
2. Reads score MIDI and score.abcx
3. Generates score MIDI TSV with H/M structure
4. Extracts annotations from ABCX
5. Merges annotations into TSV
6. Writes score.annotated_score.mid.tsv

Input:
  - data/miditsv/Composer/Piece/score.abcx
  - data/miditsv/Composer/Piece/score_structure.json
  - PianoCoRe/raw/Composer/Piece/score_*.mid

Output:
  - data/miditsv/Composer/Piece/score.annotated_score.mid.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts import align_score_performance as asp
    from scripts.build_annotated_score_tsv import (
        extract_annotations_from_abcx,
        merge_annotations_into_tsv,
    )
except ModuleNotFoundError:
    import align_score_performance as asp
    from build_annotated_score_tsv import (
        extract_annotations_from_abcx,
        merge_annotations_into_tsv,
    )


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


@dataclass
class ScoreStructure:
    """Reconstructed structure from JSON."""
    measures: list
    phrases: list
    measure_to_phrase: dict
    abcx_measures: list
    midi_to_abcx: dict
    midi_measure_content: dict


def load_structure_from_json(json_path: Path) -> ScoreStructure | None:
    """Load structure from JSON file."""
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return ScoreStructure(
            measures=data["measures"],
            phrases=data["phrases"],
            measure_to_phrase=data["measure_to_phrase"],
            abcx_measures=data["abcx_measures"],
            midi_to_abcx=data["midi_to_abcx"],
            midi_measure_content={int(k): v for k, v in data["midi_measure_content"].items()},
        )
    except Exception as e:
        print(f"Error loading structure from {json_path}: {e}", file=sys.stderr)
        return None


def copy_source_abcx(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def process_row(row: dict[str, str], pianocore_root: Path) -> dict[str, object]:
    """Write annotated score TSV for one score."""
    source_abcx = resolve_path(row.get("score_abcx_path", ""))
    if not source_abcx.is_file():
        return {"ok": False, "kind": "missing_abcx", "path": str(source_abcx)}

    score_rel = selected_score_rel(row)

    # Skip orphan scores (no MIDI)
    if not score_rel:
        return {"ok": True, "kind": "orphan_skipped", "path": str(source_abcx)}

    # Load structure from JSON
    json_path_value = row.get("score_json_path", "")
    if not nonempty(json_path_value):
        return {"ok": False, "kind": "missing_json_path", "path": str(source_abcx)}
    json_path = resolve_path(json_path_value)

    if not json_path.is_file():
        return {"ok": False, "kind": "missing_structure_json", "path": str(json_path)}

    structure = load_structure_from_json(json_path)
    if structure is None:
        return {"ok": False, "kind": "structure_load_failed", "path": str(json_path)}

    if _worker_midi_tsv is None:
        return {"ok": False, "kind": "worker_not_initialized", "path": str(source_abcx)}

    midi_path = score_midi_path(score_rel, pianocore_root)
    if not midi_path.is_file():
        return {"ok": False, "kind": "missing_score_midi", "path": str(midi_path)}

    # Generate annotated TSV
    annotated_tsv_value = row.get("annotated_score_midi_path", "")
    if not nonempty(annotated_tsv_value):
        return {"ok": False, "kind": "missing_annotated_path", "path": str(source_abcx)}

    annotated_tsv = resolve_path(annotated_tsv_value)

    # Generate base TSV first (in temp file)
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False, encoding='utf-8') as tmp:
        tmp_tsv_path = Path(tmp.name)

    try:
        # Generate base TSV
        asp.generate_score_tsv_with_phrases(
            midi_path,
            structure,
            source_abcx,
            tmp_tsv_path,
            _worker_midi_tsv,
        )

        # Extract annotations from ABCX
        annotations = extract_annotations_from_abcx(source_abcx)

        # Merge annotations into TSV
        merge_annotations_into_tsv(
            tmp_tsv_path,
            annotated_tsv,
            annotations,
            structure,
        )
    finally:
        # Clean up temp file
        if tmp_tsv_path.exists():
            tmp_tsv_path.unlink()

    return {"ok": True, "kind": "annotated_tsv_written", "path": str(annotated_tsv)}


def _worker_init(pianocore_root: str) -> None:
    global _worker_midi_tsv
    _worker_midi_tsv = asp.load_midi_tsv_module()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Step 3: Write annotated score MIDI TSV"
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
