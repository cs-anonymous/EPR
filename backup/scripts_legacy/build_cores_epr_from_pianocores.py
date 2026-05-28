#!/usr/bin/env python3
"""Build CoReS EPR S1/S2 datasets from current data assets.

Pipeline:
1. Generate raw train-only measure/phrase EPR JSONL from current
   `data/metadata.csv` and its current score/performance paths.
2. Sample filtered S1 datasets.
3. Sample S2 from S1.

This intentionally leaves language_* corpora untouched.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EPR_TASK_TYPES = ["coldstart", "main", "ending"]


def performance_piece_id(perf_tsv_path: str) -> str:
    path = str(perf_tsv_path)
    if path.startswith("data/miditsv/"):
        path = path[len("data/miditsv/") :]
    elif path.startswith("data/aligned/"):
        path = path[len("data/aligned/") :]
    elif path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/") :]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/") :]
    if path.endswith(".tsv"):
        path = path[:-4]
    return path


def write_train_metadata(src: Path, dst: Path) -> int:
    with src.open(encoding="utf-8", newline="") as fin, dst.open("w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        rows = 0
        for row in reader:
            if row.get("split") == "train":
                writer.writerow(row)
                rows += 1
    return rows


def load_train_groups(metadata_csv: Path) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    with metadata_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            grouped[(row.get("composer", ""), row.get("composition", ""), row.get("movement", ""))].append(row)
    return grouped


def chunk_groups(groups: dict[tuple[str, str, str], list[dict[str, str]]], jobs: int) -> list[list[dict[str, str]]]:
    items = list(groups.values())
    if not items:
        return []
    jobs = max(1, min(jobs, len(items)))
    chunks: list[list[list[dict[str, str]]]] = [[] for _ in range(jobs)]
    for idx, group in enumerate(items):
        chunks[idx % jobs].append(group)
    flat_chunks: list[list[dict[str, str]]] = []
    for bucket in chunks:
        rows: list[dict[str, str]] = []
        for group in bucket:
            rows.extend(group)
        flat_chunks.append(rows)
    return [chunk for chunk in flat_chunks if chunk]


def write_chunk_metadata(chunks: list[list[dict[str, str]]], temp_root: Path) -> list[Path]:
    paths: list[Path] = []
    for idx, rows in enumerate(chunks):
        path = temp_root / f"train_chunk_{idx:02d}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        paths.append(path)
    return paths


def run_generate_sft(chunk_metadata: Path, out_dir: Path, task: str) -> None:
    cmd = [
        sys.executable,
        str(ROOT / "generate_sft_data.py"),
        "--metadata",
        str(chunk_metadata),
        "--base_dir",
        str(ROOT),
        "--output_dir",
        str(out_dir),
        "--task",
        task,
        "--dataset-filter",
        "core-s",
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def worker_main(args: tuple[str, str, str]) -> None:
    meta, out_dir, task = args
    run_generate_sft(Path(meta), Path(out_dir), task)


def merge_jsonl(files: list[Path], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with output_path.open("w", encoding="utf-8") as fout:
        for path in files:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as fin:
                for line in fin:
                    if line.strip():
                        fout.write(line)
                        rows += 1
    return rows


def split_epr(source_file: Path, out_dir: Path, prefix: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    try:
        for task_type in EPR_TASK_TYPES:
            handles[task_type] = (out_dir / f"{prefix}_{task_type}.jsonl").open("w", encoding="utf-8")
        with source_file.open("r", encoding="utf-8") as fin:
            for line in fin:
                if not line.strip():
                    continue
                sample = json.loads(line)
                task_type = sample.get("task_type", "main")
                if task_type not in handles:
                    task_type = "main"
                handles[task_type].write(line)
    finally:
        for handle in handles.values():
            handle.close()


def build_raw_epr(train_meta: Path, temp_root: Path, jobs: int) -> tuple[Path, Path]:
    groups = load_train_groups(train_meta)
    chunks = chunk_groups(groups, jobs)
    meta_chunks = write_chunk_metadata(chunks, temp_root)

    measure_jobs = []
    phrase_jobs = []
    for idx, meta_path in enumerate(meta_chunks):
        chunk_out = temp_root / f"chunk_out_{idx:02d}"
        measure_jobs.append((str(meta_path), str(chunk_out), "measure_epr"))
        phrase_jobs.append((str(meta_path), str(chunk_out), "phrase_epr"))

    with multiprocessing.Pool(min(jobs, len(measure_jobs))) as pool:
        pool.map(worker_main, measure_jobs)
    with multiprocessing.Pool(min(jobs, len(phrase_jobs))) as pool:
        pool.map(worker_main, phrase_jobs)

    measure_parts = [temp_root / f"chunk_out_{idx:02d}" / "measure-based" / "measure_epr.jsonl" for idx in range(len(meta_chunks))]
    phrase_parts = [temp_root / f"chunk_out_{idx:02d}" / "phrase-based" / "phrase_epr.jsonl" for idx in range(len(meta_chunks))]

    merged_measure = temp_root / "raw_measure_epr.jsonl"
    merged_phrase = temp_root / "raw_phrase_epr.jsonl"
    measure_rows = merge_jsonl(measure_parts, merged_measure)
    phrase_rows = merge_jsonl(phrase_parts, merged_phrase)
    print(f"Merged raw measure EPR rows: {measure_rows:,}")
    print(f"Merged raw phrase EPR rows: {phrase_rows:,}")
    return merged_measure, merged_phrase


def count_matching_piece_ids(jsonl_paths: list[Path], target_piece_ids: set[str]) -> int:
    matched = set()
    for path in jsonl_paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                pid = obj.get("piece_id", "")
                if pid in target_piece_ids:
                    matched.add(pid)
    return len(matched)


def collect_backfilled_asap_piece_ids(metadata_csv: Path) -> set[str]:
    piece_ids = set()
    with metadata_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            p = row.get("performance_tsv_path", "")
            if row.get("split") == "train" and row.get("performance_dataset") == "ASAP" and row.get("is_refined") == "False":
                piece_ids.add(performance_piece_id(p))
    return piece_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores-root", type=Path, default=Path("backup/legacy_CoReS"))
    parser.add_argument("--metadata", type=Path, default=Path("data/metadata.csv"))
    parser.add_argument("--jobs", type=int, default=24)
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--sample-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=1024)
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="build_cores_epr_", dir=str(args.cores_root)))
    try:
        train_meta = temp_root / "metadata_train.csv"
        rows = write_train_metadata(args.metadata, train_meta)
        print(f"Train metadata rows: {rows:,}")

        raw_measure, raw_phrase = build_raw_epr(train_meta, temp_root, args.jobs)

        old_dirs = [
            args.cores_root / "measure_epr_sft_s1",
            args.cores_root / "measure_epr_sft_s2",
            args.cores_root / "phrase_epr_sft_s1",
            args.cores_root / "phrase_epr_sft_s2",
        ]
        for path in old_dirs:
            if path.exists():
                shutil.rmtree(path)

        stage_root = temp_root / "stage_cores"
        stage_root.mkdir(parents=True, exist_ok=True)
        split_epr(raw_measure, stage_root / "measure_epr_sft", "measure_epr")
        split_epr(raw_phrase, stage_root / "phrase_epr_sft", "phrase_epr")

        # Sample S1 from full EPR using current metadata.
        sample_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "build_epr_sample_datasets.py"),
            "--cores-root",
            str(stage_root),
            "--metadata",
            str(train_meta),
            "--tokenizer",
            str(args.tokenizer),
            "--sample-ratio",
            str(args.sample_ratio),
            "--seed",
            str(args.seed),
            "--batch-size",
            str(args.batch_size),
            "--work-dir",
            str(temp_root / ".tmp_cores_epr_sample"),
        ]
        subprocess.run(sample_cmd, check=True, cwd=str(ROOT))

        # Rename sampled dirs to explicit S1 names.
        shutil.move(str(stage_root / "measure_epr_sft"), str(stage_root / "measure_epr_sft_s1"))
        shutil.move(str(stage_root / "phrase_epr_sft"), str(stage_root / "phrase_epr_sft_s1"))

        # Build S2 from S1.
        s2_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "build_cores_s2_datasets.py"),
            "--cores-root",
            str(stage_root),
            "--metadata",
            str(train_meta),
            "--seed",
            "20260518",
            "--skip-language",
        ]
        subprocess.run(s2_cmd, check=True, cwd=str(ROOT))

        for name in [
            "measure_epr_sft_s1",
            "measure_epr_sft_s2",
            "phrase_epr_sft_s1",
            "phrase_epr_sft_s2",
        ]:
            src = stage_root / name
            dst = args.cores_root / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))

        backfilled_ids = collect_backfilled_asap_piece_ids(args.metadata)
        matched_s1_measure = count_matching_piece_ids(
            [args.cores_root / "measure_epr_sft_s1" / "measure_epr_main.jsonl"],
            backfilled_ids,
        )
        matched_s1_phrase = count_matching_piece_ids(
            [args.cores_root / "phrase_epr_sft_s1" / "phrase_epr_main.jsonl"],
            backfilled_ids,
        )
        print(f"Backfilled ASAP piece_ids in measure_epr_sft_s1/main: {matched_s1_measure}/{len(backfilled_ids)}")
        print(f"Backfilled ASAP piece_ids in phrase_epr_sft_s1/main: {matched_s1_phrase}/{len(backfilled_ids)}")

    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
