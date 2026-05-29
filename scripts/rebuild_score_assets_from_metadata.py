#!/usr/bin/env python3
"""Refresh score-side assets listed in data/score_metadata.csv."""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import shutil
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


def nonempty(value: object) -> bool:
    text = "" if value is None else str(value).strip()
    return bool(text) and text.lower() != "nan"


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


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


def copy_source_abcx(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def process_row(row: dict[str, str], pianocore_root: Path) -> dict[str, object]:
    source_abcx = resolve_path(row.get("score_abcx_path", ""))
    if not source_abcx.is_file():
        return {"ok": False, "kind": "missing_abcx", "path": str(source_abcx)}

    aligned_path = row.get("score_aligned_path", "")
    if not nonempty(aligned_path):
        return {"ok": False, "kind": "missing_aligned_path", "path": str(source_abcx)}
    aligned_abcx = resolve_path(aligned_path)

    score_rel = selected_score_rel(row)
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

    json_path_value = row.get("score_json_path", "")
    if nonempty(json_path_value):
        json_path = resolve_path(json_path_value)
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

    copy_source_abcx(source_abcx, aligned_abcx.parent / "score.abcx")
    asp.write_aligned_abcx(
        source_abcx,
        aligned_abcx,
        structure.phrases,
        structure.midi_measure_content,
    )

    score_tsv_value = row.get("score_midi_tsv_path", "")
    if nonempty(score_tsv_value):
        score_tsv = resolve_path(score_tsv_value)
        asp.generate_score_tsv_with_phrases(
            midi_path,
            structure,
            source_abcx,
            score_tsv,
            _worker_midi_tsv,
        )

    return {"ok": True, "kind": "paired_score", "path": str(aligned_abcx)}


def _worker_init(pianocore_root: str) -> None:
    del pianocore_root
    global _worker_midi_tsv
    _worker_midi_tsv = asp.load_midi_tsv_module()


def _worker_process(args: tuple[dict[str, str], str]) -> dict[str, object]:
    row, pianocore_root = args
    return process_row(row, Path(pianocore_root))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--pianocore-root", type=Path, default=DEFAULT_PIANOCORE_ROOT)
    parser.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() // 2))
    args = parser.parse_args()

    with args.metadata.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    jobs = max(1, args.jobs)
    results: list[dict[str, object]] = []
    if jobs == 1:
        _worker_init(str(args.pianocore_root))
        for row in rows:
            results.append(process_row(row, args.pianocore_root))
    else:
        with mp.Pool(processes=jobs, initializer=_worker_init, initargs=(str(args.pianocore_root),)) as pool:
            for result in pool.imap_unordered(
                _worker_process,
                ((row, str(args.pianocore_root)) for row in rows),
                chunksize=8,
            ):
                results.append(result)

    ok = sum(1 for item in results if item.get("ok"))
    failures = [item for item in results if not item.get("ok")]
    by_kind: dict[str, int] = {}
    for item in results:
        kind = str(item.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1

    print(f"Processed score metadata rows: {len(results):,}")
    print(f"Successful: {ok:,}")
    for kind, count in sorted(by_kind.items()):
        print(f"{kind}: {count:,}")
    if failures:
        print(f"Failures: {len(failures):,}", file=sys.stderr)
        for item in failures[:50]:
            print(item, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
