#!/usr/bin/env python3
"""Rebuild performance MIDI TSVs from metadata, preserving lower-staff note labels."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.align_score_performance import (
    align_performance_with_score,
    build_performance_measure_note_staffs,
    build_score_structure_from_paths,
    generate_performance_tsv_with_phrases,
    load_midi_tsv_module,
    write_aligned_abcx,
)


def _target_tsv_path(row: dict[str, str]) -> Path | None:
    tsv_rel = (row.get("performance_tsv_path") or "").strip()
    if tsv_rel.startswith("PianoCoReS/"):
        return ROOT / tsv_rel

    tsv_rel = (row.get("tsv_path") or "").strip()
    if tsv_rel:
        return ROOT / "PianoCoReS" / tsv_rel

    tsv_rel = (row.get("performance_tsv_path") or "").strip()
    if tsv_rel:
        return ROOT / tsv_rel
    return None


def _score_midi_rel(row: dict[str, str]) -> str:
    refined = (row.get("refined_score_midi_path") or "").strip()
    if refined:
        return refined
    return (row.get("score_midi_path") or "").strip()


def _perf_midi_rel(row: dict[str, str]) -> str:
    refined = (row.get("refined_performance_midi_path") or "").strip()
    if refined:
        return refined
    return (row.get("performance_midi_path") or "").strip()


def _align_rel(row: dict[str, str]) -> str:
    refined = (row.get("refined_alignment_path") or "").strip()
    if refined:
        return refined
    return (row.get("raw_alignment_path") or "").strip()


def _resolve_pianocore_asset(pianocore_root: Path, rel_path: str) -> Path:
    if not rel_path:
        return Path("")
    bucket = "refined" if ("_refined" in rel_path or "_mini" in rel_path) else "raw"
    return pianocore_root / bucket / rel_path


def _mapping_source_path(pianocore_root: Path, score_rel: str, score_midi: Path) -> Path:
    raw_rel = score_rel.replace("_refined.mid", ".mid")
    raw_candidate = _resolve_pianocore_asset(pianocore_root, raw_rel)
    return raw_candidate if raw_candidate.exists() else score_midi


def load_rows(metadata_paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for metadata_path in metadata_paths:
        with metadata_path.open(encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def build_groups(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        score_rel = _score_midi_rel(row)
        abcx_rel = (row.get("score_abcx_path") or "").strip()
        perf_rel = _perf_midi_rel(row)
        align_rel = _align_rel(row)
        target_tsv = _target_tsv_path(row)
        if not (score_rel and abcx_rel and perf_rel and align_rel and target_tsv):
            continue
        groups[(score_rel, abcx_rel)].append(row)
    return groups


_WORKER_PIANOCORE_ROOT: Path | None = None
_WORKER_MIDI_TSV = None


def _init_worker(pianocore_root: str) -> None:
    global _WORKER_PIANOCORE_ROOT, _WORKER_MIDI_TSV
    _WORKER_PIANOCORE_ROOT = Path(pianocore_root)
    _WORKER_MIDI_TSV = load_midi_tsv_module()


def _process_group(item: tuple[tuple[str, str], list[dict[str, str]]]) -> tuple[int, int]:
    global _WORKER_PIANOCORE_ROOT, _WORKER_MIDI_TSV
    assert _WORKER_PIANOCORE_ROOT is not None
    assert _WORKER_MIDI_TSV is not None

    (score_rel, abcx_rel), group_rows = item
    score_midi = _resolve_pianocore_asset(_WORKER_PIANOCORE_ROOT, score_rel)
    score_abcx = ROOT / abcx_rel
    if not score_midi.exists() or not score_abcx.exists():
        return 0, len(group_rows)

    mapping_source = _mapping_source_path(_WORKER_PIANOCORE_ROOT, score_rel, score_midi)
    score_structure = build_score_structure_from_paths(
        score_midi,
        score_abcx,
        _WORKER_MIDI_TSV,
        mapping_source=mapping_source,
    )
    if score_structure is None:
        return 0, len(group_rows)

    sample_target = _target_tsv_path(group_rows[0])
    if sample_target is None:
        return 0, len(group_rows)
    staff_abcx = score_abcx
    if "aligned" not in score_abcx.name:
        aligned_abcx = sample_target.parent / "score_aligned.abcx"
        write_aligned_abcx(
            score_abcx,
            aligned_abcx,
            score_structure.phrases,
            score_structure.midi_measure_content,
        )
        if aligned_abcx.exists():
            staff_abcx = aligned_abcx

    written = 0
    skipped = 0
    for row in group_rows:
        perf_midi = _resolve_pianocore_asset(_WORKER_PIANOCORE_ROOT, _perf_midi_rel(row))
        align_file = _resolve_pianocore_asset(_WORKER_PIANOCORE_ROOT, _align_rel(row))
        target_tsv = _target_tsv_path(row)
        if target_tsv is None or not perf_midi.exists() or not align_file.exists():
            skipped += 1
            continue

        perf_entries = align_performance_with_score(
            score_midi,
            perf_midi,
            align_file,
            score_structure,
        )
        perf_staffs = build_performance_measure_note_staffs(
            score_midi,
            perf_midi,
            align_file,
            score_structure,
            staff_abcx,
            perf_entries,
        )
        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_entries,
            target_tsv,
            _WORKER_MIDI_TSV,
            measure_note_staffs=perf_staffs,
        ):
            written += 1
        else:
            skipped += 1

    return written, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        nargs="+",
        default=[
            ROOT / "PianoCoReS" / "performance_S_metadata.csv",
            ROOT / "PianoCoReS" / "performance_Astar_metadata.csv",
        ],
        help="One or more metadata CSV files to rebuild from.",
    )
    parser.add_argument(
        "--pianocore-root",
        type=Path,
        default=ROOT / "PianoCoRe",
        help="Root directory containing raw/ and refined/ PianoCoRe assets.",
    )
    parser.add_argument(
        "--limit-groups",
        type=int,
        default=None,
        help="Optional limit on grouped score entries for testing.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=16,
        help="Number of worker processes. Use 1 for single-process mode.",
    )
    args = parser.parse_args()
    rows = load_rows(args.metadata)
    groups = list(build_groups(rows).items())
    if args.limit_groups is not None:
        groups = groups[: args.limit_groups]

    written = 0
    skipped = 0
    jobs = max(1, args.jobs)
    if jobs == 1:
        _init_worker(str(args.pianocore_root))
        for item in tqdm(groups, desc="Rebuilding TSVs"):
            group_written, group_skipped = _process_group(item)
            written += group_written
            skipped += group_skipped
    else:
        n_workers = min(jobs, len(groups), os.cpu_count() or jobs)
        with Pool(n_workers, initializer=_init_worker, initargs=(str(args.pianocore_root),)) as pool:
            for group_written, group_skipped in tqdm(
                pool.imap_unordered(_process_group, groups),
                total=len(groups),
                desc="Rebuilding TSVs",
            ):
                written += group_written
                skipped += group_skipped

    print(f"Written TSVs: {written}")
    print(f"Skipped rows: {skipped}")


if __name__ == "__main__":
    main()
