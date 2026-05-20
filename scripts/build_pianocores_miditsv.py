#!/usr/bin/env python3
"""Rebuild PianoCoReS aligned ABCX and MIDI-TSV files from metadata.

This is a small wrapper around the current metadata-driven alignment pipeline.
It adapts the PianoCoReS manifest, whose score paths may already point at an
older output tree, back to the canonical PianoCoRe/score source paths before
regenerating outputs.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


OLD_SCORE_PREFIXES = (
    "PianoCoReS/aligned/",
    "PianoCoRe/aligned/",
    "PianoCoReS/miditsv/",
)


def piece_rel_from_score_path(value: str) -> str:
    path = value.strip()
    if not path:
        raise ValueError("empty score_abcx_path")

    if path.startswith("PianoCoRe/score/"):
        rel = path.removeprefix("PianoCoRe/score/")
    else:
        for prefix in OLD_SCORE_PREFIXES:
            if path.startswith(prefix):
                rel = path.removeprefix(prefix)
                break
        else:
            parts = Path(path).parts
            if "aligned" in parts:
                rel = Path(*parts[parts.index("aligned") + 1 :]).as_posix()
            elif "miditsv" in parts:
                rel = Path(*parts[parts.index("miditsv") + 1 :]).as_posix()
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


def selected_score_midi(row: dict[str, str]) -> str:
    return row.get("refined_score_midi_path") or row.get("score_midi_path") or ""


def selected_perf_midi(row: dict[str, str]) -> str:
    return row.get("refined_performance_midi_path") or row.get("performance_midi_path") or ""


def score_aligned_name(row: dict[str, str]) -> str:
    return "score_aligned_mini.abcx" if "_mini" in selected_score_midi(row) else "score_aligned.abcx"


def output_score_path(output_dir: Path, piece_rel: str, row: dict[str, str]) -> str:
    return (output_dir / piece_rel / score_aligned_name(row)).as_posix()


def output_tsv_path(output_dir: Path, piece_rel: str, row: dict[str, str]) -> str:
    perf_midi = selected_perf_midi(row)
    if not perf_midi:
        raise ValueError(f"missing performance MIDI for {row.get('id', '<unknown>')}")
    return (output_dir / piece_rel / (Path(perf_midi).name + ".tsv")).as_posix()


def make_pipeline_metadata(input_csv: Path, temp_csv: Path) -> tuple[int, int]:
    fixed = 0
    with input_csv.open(encoding="utf-8", newline="") as fin, temp_csv.open(
        "w", encoding="utf-8", newline=""
    ) as fout:
        reader = csv.DictReader(fin)
        if reader.fieldnames is None:
            raise ValueError(f"{input_csv} has no header")
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        total = 0
        for row in reader:
            total += 1
            piece_rel = piece_rel_from_score_path(row.get("score_abcx_path", ""))
            source_score = f"PianoCoRe/score/{piece_rel}/score.abcx"
            if row.get("score_abcx_path") != source_score:
                fixed += 1
            row["score_abcx_path"] = source_score
            writer.writerow(row)
    return total, fixed


def run_pipeline(
    metadata_csv: Path,
    output_dir: Path,
    pianocore_root: Path,
    jobs: int,
    tier: str,
    overwrite_tsv: bool,
) -> None:
    cmd = [
        sys.executable,
        "scripts/align_score_performance.py",
        "--metadata",
        str(metadata_csv),
        "--pianocore-root",
        str(pianocore_root),
        "--output-dir",
        str(output_dir),
        "--tier",
        tier,
        "--jobs",
        str(jobs),
    ]
    if overwrite_tsv:
        cmd.append("--overwrite-tsv")
    subprocess.run(cmd, check=True)


def update_and_verify_metadata(input_csv: Path, output_csv: Path, output_dir: Path) -> tuple[int, list[str]]:
    missing: list[str] = []
    with input_csv.open(encoding="utf-8", newline="") as fin, output_csv.open(
        "w", encoding="utf-8", newline=""
    ) as fout:
        reader = csv.DictReader(fin)
        if reader.fieldnames is None:
            raise ValueError(f"{input_csv} has no header")
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        total = 0
        for row in reader:
            total += 1
            piece_rel = piece_rel_from_score_path(row.get("score_abcx_path", ""))
            score_path = output_score_path(output_dir, piece_rel, row)
            tsv_path = output_tsv_path(output_dir, piece_rel, row)
            row["score_abcx_path"] = score_path
            row["performance_tsv_path"] = tsv_path

            if not Path(score_path).is_file():
                missing.append(f"{row.get('id', '<unknown>')}: missing {score_path}")
            if not Path(tsv_path).is_file():
                missing.append(f"{row.get('id', '<unknown>')}: missing {tsv_path}")
            writer.writerow(row)
    return total, missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoReS/metadata.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("PianoCoReS/miditsv"))
    parser.add_argument("--pianocore-root", type=Path, default=Path("PianoCoRe"))
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--tier", choices=["a", "a_star", "b", "all"], default="all")
    parser.add_argument("--overwrite-tsv", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pianocores_miditsv_") as tmp:
        temp_metadata = Path(tmp) / "metadata.pipeline.csv"
        total, fixed = make_pipeline_metadata(args.metadata, temp_metadata)
        print(f"Prepared pipeline metadata: {total} rows, remapped {fixed} score paths")

        if not args.skip_generate:
            run_pipeline(
                temp_metadata,
                args.output_dir,
                args.pianocore_root,
                args.jobs,
                args.tier,
                args.overwrite_tsv,
            )

        updated = Path(tmp) / "metadata.updated.csv"
        total, missing = update_and_verify_metadata(args.metadata, updated, args.output_dir)
        if missing:
            print(f"Verification failed: {len(missing)} missing outputs", file=sys.stderr)
            for item in missing[:50]:
                print(item, file=sys.stderr)
            if len(missing) > 50:
                print(f"... {len(missing) - 50} more", file=sys.stderr)
            raise SystemExit(1)

        staged = args.metadata.with_name(f".{args.metadata.name}.updated")
        shutil.copy2(updated, staged)
        staged.replace(args.metadata)
        print(f"Updated {args.metadata}: {total} rows verified")


if __name__ == "__main__":
    main()
