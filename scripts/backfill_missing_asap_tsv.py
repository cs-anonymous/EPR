#!/usr/bin/env python3
"""Backfill missing non-refined ASAP TSV files into PianoCoRe/aligned.

This targets metadata rows whose expected `performance_tsv_path` does not exist
under PianoCoRe/aligned but whose raw score/performance/alignment assets still
exist under PianoCoRe/raw.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from tqdm import tqdm


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import align_score_performance as asp


def load_midi_tsv_module():
    midi_tsv_script = ROOT / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def missing_nonrefined_asap_rows(metadata_csv: Path, aligned_root: Path) -> list[dict]:
    rows: list[dict] = []
    with metadata_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("performance_dataset") != "ASAP":
                continue
            if (row.get("is_refined") or "").strip() != "False":
                continue
            perf_tsv = (row.get("performance_tsv_path") or "").strip()
            score_abcx = (row.get("score_abcx_path") or "").strip()
            perf_midi = (row.get("performance_midi_path") or "").strip()
            raw_align = (row.get("raw_alignment_path") or "").strip()
            score_midi = (row.get("score_midi_path") or "").strip()
            if not (perf_tsv and score_abcx and perf_midi and raw_align and score_midi):
                continue

            rel = None
            if perf_tsv.startswith("PianoCoRe_output/"):
                rel = perf_tsv[len("PianoCoRe_output/") :]
            elif perf_tsv.startswith("PianoCoRe/aligned/"):
                rel = perf_tsv[len("PianoCoRe/aligned/") :]
            elif perf_tsv.startswith("PianoCoReS/aligned/"):
                rel = perf_tsv[len("PianoCoReS/aligned/") :]
            if rel is None:
                continue

            if not (aligned_root / rel).exists():
                row["_expected_rel_tsv"] = rel
                rows.append(row)
    return rows


def validate_assets(rows: list[dict], pianocore_root: Path) -> list[dict]:
    valid: list[dict] = []
    for row in rows:
        score_midi = pianocore_root / "raw" / row["score_midi_path"]
        perf_midi = pianocore_root / "raw" / row["performance_midi_path"]
        raw_align = pianocore_root / "raw" / row["raw_alignment_path"]
        abcx = pianocore_root / "score" / row["score_abcx_path"].replace("PianoCoRe/score/", "")
        if score_midi.exists() and perf_midi.exists() and raw_align.exists() and abcx.exists():
            valid.append(row)
    return valid


def build_tasks(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in rows:
        score_midi = row["score_midi_path"]
        abcx_path = row["score_abcx_path"]
        suffix = "_mini" if "_mini" in score_midi else ""
        grouped[(score_midi, abcx_path, suffix)].append(
            (row["performance_midi_path"], row["raw_alignment_path"])
        )

    tasks = []
    for (score_midi, abcx_path, suffix), perfs in grouped.items():
        abcx_rel = abcx_path.replace("PianoCoRe/score/", "").replace("/score.abcx", "")
        tasks.append(
            {
                "score_path": score_midi,
                "piece_path": abcx_rel,
                "suffix": suffix,
                "performances": perfs,
                "abcx_path": abcx_path,
            }
        )
    return tasks


def expected_missing_rel_paths(rows: list[dict]) -> set[str]:
    return {row["_expected_rel_tsv"] for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoRe/metadata.csv"))
    parser.add_argument("--pianocore-root", type=Path, default=Path("PianoCoRe"))
    parser.add_argument("--output-dir", type=Path, default=Path("PianoCoRe/aligned"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    missing_rows = missing_nonrefined_asap_rows(args.metadata, args.output_dir)
    valid_rows = validate_assets(missing_rows, args.pianocore_root)
    if args.limit is not None:
        valid_rows = valid_rows[: args.limit]
    tasks = build_tasks(valid_rows)
    expected = expected_missing_rel_paths(valid_rows)

    midi_tsv = load_midi_tsv_module()
    print(f"Missing ASAP rows: {len(missing_rows)}")
    print(f"Valid rows with raw assets: {len(valid_rows)}")
    print(f"Score tasks: {len(tasks)}")

    generated_task_count = 0
    generated_tsv_count = 0
    for task in tqdm(tasks, desc="Backfilling ASAP TSV"):
        n = asp.process_metadata_task_v2(task, midi_tsv, args.pianocore_root, args.output_dir)
        if n > 0:
            generated_task_count += 1
            generated_tsv_count += n

    now_present = sum(1 for rel in expected if (args.output_dir / rel).exists())
    still_missing = sorted(rel for rel in expected if not (args.output_dir / rel).exists())

    print(f"Tasks with generated TSV: {generated_task_count}")
    print(f"Generated TSV count: {generated_tsv_count}")
    print(f"Expected TSV now present: {now_present}/{len(expected)}")
    if still_missing:
        print("Still missing:")
        for rel in still_missing[:50]:
            print(rel)


if __name__ == "__main__":
    main()
