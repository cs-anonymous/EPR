#!/usr/bin/env python3
"""Generate aligned score MIDI-TSV files and backfill metadata paths.

For each unique score entry in `PianoCoReS/metadata.csv`, this script:
1. Resolves the selected score MIDI (`refined_score_midi_path` preferred).
2. Resolves the source `score.abcx` for the same piece.
3. Builds score phrase/measure structure using the existing alignment pipeline.
4. Serializes the score MIDI itself into aligned LM-MIDI TSV.
5. Writes/updates `score_midi_tsv_path` in metadata.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts import align_score_performance as asp
except ModuleNotFoundError:
    import align_score_performance as asp


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_METADATA = ROOT / "PianoCoReS" / "metadata.csv"
DEFAULT_OUTPUT_DIR = ROOT / "PianoCoReS" / "miditsv"
DEFAULT_PIANOCORE_ROOT = ROOT / "PianoCoRe"

OLD_SCORE_PREFIXES = (
    "PianoCoReS/aligned/",
    "PianoCoRe/aligned/",
    "PianoCoReS/miditsv/",
    "PianoCoRe/score/",
)

_worker_midi_tsv = None


def is_nonempty(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() != "nan"


def selected_score_midi(row: dict[str, str]) -> str:
    refined = row.get("refined_score_midi_path", "")
    if is_nonempty(refined):
        return str(refined).strip()
    score = row.get("score_midi_path", "")
    if is_nonempty(score):
        return str(score).strip()
    return ""


def piece_rel_from_score_path(value: str) -> str:
    path = str(value).strip()
    if not path:
        raise ValueError("empty score_abcx_path")

    rel = None
    for prefix in OLD_SCORE_PREFIXES:
        if path.startswith(prefix):
            rel = path.removeprefix(prefix)
            break
    if rel is None:
        parts = Path(path).parts
        if "miditsv" in parts:
            rel = Path(*parts[parts.index("miditsv") + 1 :]).as_posix()
        elif "score" in parts:
            rel = Path(*parts[parts.index("score") + 1 :]).as_posix()
        else:
            rel = path

    for suffix in (
        "/score.abcx",
        "/score_aligned.abcx",
        "/score_aligned_mini.abcx",
    ):
        if rel.endswith(suffix):
            return rel[: -len(suffix)]
    raise ValueError(f"cannot derive piece path from {value!r}")


def resolve_source_abcx(
    row: dict[str, str],
    piece_rel: str,
    output_dir: Path,
    pianocore_root: Path,
) -> Path | None:
    raw_metadata_path = str(row.get("score_abcx_path", "")).strip()
    candidates: list[Path] = []

    if raw_metadata_path:
        path = Path(raw_metadata_path)
        if path.name == "score.abcx":
            candidates.append(path)
        else:
            candidates.append(path.with_name("score.abcx"))

    candidates.append(output_dir / piece_rel / "score.abcx")
    candidates.append(pianocore_root / "score" / piece_rel / "score.abcx")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    return None


def resolve_score_midi_path(score_rel: str, pianocore_root: Path) -> Path:
    if "_refined" in score_rel or "_mini" in score_rel:
        return pianocore_root / "refined" / score_rel
    return pianocore_root / "raw" / score_rel


def score_tsv_rel_path(piece_rel: str, score_rel: str) -> str:
    return (Path("PianoCoReS") / "miditsv" / piece_rel / (Path(score_rel).name + ".tsv")).as_posix()


def build_tasks(metadata_csv: Path, pianocore_root: Path, output_dir: Path) -> list[dict[str, str]]:
    tasks: dict[tuple[str, str], dict[str, str]] = {}
    with metadata_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            score_rel = selected_score_midi(row)
            if not score_rel:
                continue
            score_abcx_path = row.get("score_abcx_path", "")
            if not is_nonempty(score_abcx_path):
                continue

            try:
                piece_rel = piece_rel_from_score_path(score_abcx_path)
            except ValueError:
                continue

            source_abcx = resolve_source_abcx(row, piece_rel, output_dir, pianocore_root)
            if source_abcx is None:
                continue

            score_midi = resolve_score_midi_path(score_rel, pianocore_root)
            if not score_midi.is_file():
                continue

            output_tsv = output_dir / piece_rel / (Path(score_rel).name + ".tsv")
            key = (piece_rel, score_rel)
            if key not in tasks:
                tasks[key] = {
                    "piece_rel": piece_rel,
                    "score_rel": score_rel,
                    "score_midi": str(score_midi),
                    "score_abcx": str(source_abcx),
                    "output_tsv": str(output_tsv),
                }
    return list(tasks.values())


def _worker_init() -> None:
    global _worker_midi_tsv
    _worker_midi_tsv = asp.load_midi_tsv_module()


def _process_task(task: dict[str, str], overwrite: bool) -> dict[str, str | bool]:
    output_tsv = Path(task["output_tsv"])
    if not overwrite and output_tsv.exists() and output_tsv.stat().st_size > 0:
        return {"ok": True, "generated": False, "output_tsv": str(output_tsv), "piece_rel": task["piece_rel"]}

    score_midi = Path(task["score_midi"])
    score_abcx = Path(task["score_abcx"])
    structure, ok = asp._build_score_structure(score_midi, score_abcx, score_abcx.parent, _worker_midi_tsv)
    if not ok or structure is None:
        return {"ok": False, "generated": False, "output_tsv": str(output_tsv), "piece_rel": task["piece_rel"]}

    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    generated = asp.generate_score_tsv_with_phrases(score_midi, structure, output_tsv, _worker_midi_tsv)
    return {"ok": bool(generated), "generated": bool(generated), "output_tsv": str(output_tsv), "piece_rel": task["piece_rel"]}


def update_metadata(metadata_csv: Path, backup_csv: Path, tasks: list[dict[str, str]]) -> tuple[int, int]:
    mapping = {
        (task["piece_rel"], task["score_rel"]): score_tsv_rel_path(task["piece_rel"], task["score_rel"])
        for task in tasks
        if Path(task["output_tsv"]).is_file() and Path(task["output_tsv"]).stat().st_size > 0
    }

    with metadata_csv.open("r", encoding="utf-8", newline="") as fin:
        reader = csv.DictReader(fin)
        fieldnames = list(reader.fieldnames or [])
        if "score_midi_tsv_path" not in fieldnames:
            fieldnames.append("score_midi_tsv_path")

        rows = []
        updated = 0
        for row in reader:
            score_rel = selected_score_midi(row)
            if score_rel and is_nonempty(row.get("score_abcx_path", "")):
                try:
                    piece_rel = piece_rel_from_score_path(str(row["score_abcx_path"]))
                except ValueError:
                    row["score_midi_tsv_path"] = ""
                    rows.append(row)
                    continue
                value = mapping.get((piece_rel, score_rel), "")
                if row.get("score_midi_tsv_path", "") != value:
                    updated += 1
                row["score_midi_tsv_path"] = value
            else:
                row["score_midi_tsv_path"] = ""
            rows.append(row)

    shutil.copy2(metadata_csv, backup_csv)
    with metadata_csv.open("w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--pianocore-root", type=Path, default=DEFAULT_PIANOCORE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() // 2))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    tasks = build_tasks(args.metadata, args.pianocore_root, args.output_dir)
    print(f"Discovered {len(tasks):,} unique score MIDI tasks")

    if not tasks:
        print("No score MIDI tasks found")
        return

    results: list[dict[str, str | bool]] = []
    with mp.Pool(processes=args.jobs, initializer=_worker_init) as pool:
        for result in pool.starmap(_process_task, [(task, args.overwrite) for task in tasks]):
            results.append(result)

    ok_count = sum(1 for item in results if item["ok"])
    generated_count = sum(1 for item in results if item["generated"])
    failed = [item for item in results if not item["ok"]]
    print(f"Score MIDI-TSV ready: {ok_count:,}/{len(results):,}")
    print(f"Newly generated: {generated_count:,}")
    if failed:
        print(f"Failed: {len(failed):,}")
        for item in failed[:20]:
            print(f"  - {item['piece_rel']} -> {item['output_tsv']}")

    backup_csv = args.metadata.with_suffix(args.metadata.suffix + ".bak_before_score_midi_tsv")
    row_count, updated_rows = update_metadata(args.metadata, backup_csv, tasks)
    print(f"Metadata rows written: {row_count:,}")
    print(f"Rows updated with score_midi_tsv_path: {updated_rows:,}")
    print(f"Backup saved to: {backup_csv}")


if __name__ == "__main__":
    main()
