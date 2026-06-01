#!/usr/bin/env python3
"""Rebuild annotated score TSVs for the score variants referenced by metadata."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_annotated_module():
    script = ROOT / "scripts" / "03_write_annotated_tsv.py"
    module_name = "write_annotated_tsv_dynamic"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ANNOTATED = load_annotated_module()


def output_name_for_abcx(abcx_path: Path) -> str:
    return f"{abcx_path.stem}.annotated_score.mid.tsv"


def choose_score_midi(row: dict[str, str], pianocore_root: Path) -> Path | None:
    score_rel = (row.get("refined_score_midi_path") or row.get("score_midi_path") or "").strip()
    if not score_rel:
        return None
    if "_refined" in score_rel or "_mini" in score_rel:
        path = pianocore_root / "refined" / score_rel
    else:
        path = pianocore_root / "raw" / score_rel
    return path if path.exists() else None


def build_tasks(metadata_paths: list[Path], pianocore_root: Path) -> list[dict[str, str]]:
    dedup: dict[tuple[str, str], dict[str, str]] = {}
    for metadata_path in metadata_paths:
        with metadata_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                abcx_raw = (row.get("score_abcx_path") or "").strip()
                if not abcx_raw:
                    continue
                abcx_path = Path(abcx_raw)
                if not abcx_path.exists():
                    continue
                score_midi = choose_score_midi(row, pianocore_root)
                if score_midi is None:
                    continue
                key = (str(abcx_path), str(score_midi))
                if key in dedup:
                    continue
                dedup[key] = {
                    "score_abcx_path": str(abcx_path),
                    "score_midi_path": str(score_midi),
                    "output_path": str(abcx_path.parent / output_name_for_abcx(abcx_path)),
                }
    return list(dedup.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        nargs="+",
        default=[
            ROOT / "data" / "performance_S_metadata.csv",
            ROOT / "data" / "performance_Astar_metadata_updated.csv",
        ],
    )
    parser.add_argument("--pianocore-root", type=Path, default=ROOT / "PianoCoRe")
    parser.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() // 2))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    tasks = build_tasks(args.metadata, args.pianocore_root)
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"Discovered {len(tasks):,} unique annotated score variant tasks")

    if not args.overwrite:
        tasks = [task for task in tasks if not Path(task["output_path"]).exists()]
        print(f"After filtering existing outputs: {len(tasks):,} tasks remaining")

    if not tasks:
        print("No tasks to process")
        return

    results = []
    with mp.Pool(processes=args.jobs, initializer=ANNOTATED._worker_init) as pool:
        for result in pool.imap_unordered(ANNOTATED.process_score, tasks):
            results.append(result)
            if result["ok"]:
                print(f"OK {result['output']}")
            else:
                print(f"FAIL {result['path']}: {result['error']}")

    ok = sum(1 for item in results if item["ok"])
    print(f"Completed: {ok}/{len(results)} successful")


if __name__ == "__main__":
    main()
