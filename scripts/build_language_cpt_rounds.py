#!/usr/bin/env python3
"""Build mixed/shuffled multi-round CPT JSONL datasets for CorporaV2."""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class RoundPlan:
    name: str
    perf_file: str
    perf_kind: str
    bucket_index: int
    bucket_count: int


ROUND_PLANS = [
    RoundPlan("round1", "performance_S_midi.jsonl", "performance_S", 0, 2),
    RoundPlan("round2", "performance_S_midi.jsonl", "performance_S", 1, 2),
    RoundPlan("round3", "performance_Astar_midi.json", "performance_Astar", 0, 3),
    RoundPlan("round4", "performance_Astar_midi.json", "performance_Astar", 1, 3),
    RoundPlan("round5", "performance_Astar_midi.json", "performance_Astar", 2, 3),
]


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def iter_json_array(path: Path) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buf = ""
        in_array = False
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            pos = 0
            length = len(buf)
            while True:
                while pos < length and buf[pos].isspace():
                    pos += 1
                if pos >= length:
                    break
                if not in_array:
                    if buf[pos] != "[":
                        raise ValueError(f"{path}: expected '[' at array start")
                    in_array = True
                    pos += 1
                    continue
                if buf[pos] == ",":
                    pos += 1
                    continue
                if buf[pos] == "]":
                    return
                try:
                    obj, next_pos = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    break
                yield obj
                pos = next_pos
            buf = buf[pos:]
    if buf.strip() not in {"", "]"}:
        raise ValueError(f"{path}: trailing JSON content after array parse")


def iter_records(path: Path) -> Iterator[dict]:
    if path.suffix == ".jsonl":
        yield from iter_jsonl(path)
    else:
        yield from iter_json_array(path)


def unique_sources(path: Path) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for record in iter_records(path):
        source = record["source"]
        if source in seen:
            continue
        seen.add(source)
        ordered.append(source)
    ordered.sort()
    return ordered


def bucket_sources(sources: list[str], bucket_count: int) -> list[list[str]]:
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    per_bucket = math.ceil(len(sources) / bucket_count)
    return [sources[idx * per_bucket : (idx + 1) * per_bucket] for idx in range(bucket_count)]


def copy_selected_records(
    input_path: Path,
    output_handle,
    allowed_sources: set[str] | None,
) -> tuple[int, set[str]]:
    written = 0
    used_sources: set[str] = set()
    for record in iter_records(input_path):
        source = record["source"]
        if allowed_sources is not None and source not in allowed_sources:
            continue
        output_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        written += 1
        used_sources.add(source)
    return written, used_sources


def shuffle_jsonl(temp_path: Path, output_path: Path, seed: int) -> None:
    random_source = temp_path.with_suffix(temp_path.suffix + ".rand")
    rng = random.Random(seed)
    with random_source.open("wb") as handle:
        handle.write(bytes(rng.randrange(0, 256) for _ in range(1 << 20)))

    try:
        with output_path.open("w", encoding="utf-8") as out_handle:
            subprocess.run(
                ["shuf", "--random-source", str(random_source), str(temp_path)],
                check=True,
                stdout=out_handle,
            )
    finally:
        random_source.unlink(missing_ok=True)


def file_size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def build_round(
    corpora_dir: Path,
    output_dir: Path,
    plan: RoundPlan,
    seed: int,
    annotated_records_path: Path,
) -> dict:
    perf_path = corpora_dir / plan.perf_file
    sources = unique_sources(perf_path)
    buckets = bucket_sources(sources, plan.bucket_count)
    selected_sources = set(buckets[plan.bucket_index])

    tmp_path = output_dir / f"{plan.name}.tmp.jsonl"
    final_path = output_dir / f"{plan.name}_train.jsonl"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    with tmp_path.open("w", encoding="utf-8") as handle:
        annotated_count, annotated_sources = copy_selected_records(annotated_records_path, handle, None)
        perf_count, perf_used_sources = copy_selected_records(perf_path, handle, selected_sources)

    shuffle_jsonl(tmp_path, final_path, seed=seed + plan.bucket_index)
    tmp_path.unlink(missing_ok=True)

    summary = {
        "round": plan.name,
        "output_path": str(final_path),
        "output_size_mb": round(file_size_mb(final_path), 2),
        "seed": seed + plan.bucket_index,
        "annotated_score_file": str(annotated_records_path),
        "annotated_score_records": annotated_count,
        "annotated_score_sources": len(annotated_sources),
        "performance_file": str(perf_path),
        "performance_kind": plan.perf_kind,
        "performance_bucket_index": plan.bucket_index + 1,
        "performance_bucket_count": plan.bucket_count,
        "performance_candidate_sources": len(sources),
        "performance_selected_sources": len(selected_sources),
        "performance_written_sources": len(perf_used_sources),
        "performance_records": perf_count,
        "total_records": annotated_count + perf_count,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpora-dir",
        type=Path,
        default=Path("data/CorporaV2/language_cpt"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/CorporaV2/language_cpt_rounds"),
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    corpora_dir = args.corpora_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    annotated_path = corpora_dir / "annotated_score_midi.jsonl"
    if not annotated_path.exists():
        raise FileNotFoundError(annotated_path)

    summaries = []
    for plan in ROUND_PLANS:
        summaries.append(build_round(corpora_dir, output_dir, plan, args.seed, annotated_path))

    summary_path = output_dir / "round_build_summary.json"
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
