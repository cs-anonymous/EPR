#!/usr/bin/env python3
"""Build a single-file CPT-S1 JSONL mix from PianoCoReS language corpora.

The mix is line-based and reproducible:
  - midi_tsv_no_header: 100%
  - aligned_abcx: 150%
  - knowledge_Seeker38: 30%
  - knowledge_format: 2000%
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CorpusPlan:
    corpus: str
    filename: str
    ratio: float


DEFAULT_PLAN = [
    CorpusPlan("midi_tsv_no_header", "midi_tsv_no_header.jsonl", 1.0),
    CorpusPlan("aligned_abcx", "aligned_abcx.jsonl", 1.5),
    CorpusPlan("knowledge_Seeker38", "knowledge_Seeker38.jsonl", 0.3),
    CorpusPlan("knowledge_format", "knowledge_format.jsonl", 50.0),
]


def iter_nonempty_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield line


def iter_corpus_lines(path: Path, corpus: str, source_split: str | None) -> Iterable[str]:
    for line in iter_nonempty_lines(path):
        if source_split is None or corpus.startswith("knowledge_"):
            yield line
            continue

        record = json.loads(line)
        if record.get("source_split") == source_split:
            yield line


def count_corpus_lines(path: Path, corpus: str, source_split: str | None) -> int:
    return sum(1 for _ in iter_corpus_lines(path, corpus, source_split))


def rounded_target(total: int, ratio: float) -> int:
    return int(math.floor((total * ratio) + 0.5))


def stable_seed(seed: int, corpus: str) -> int:
    digest = hashlib.sha256(f"{seed}:{corpus}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def choose_sample_indices(total: int, count: int, seed: int) -> set[int]:
    if count <= 0:
        return set()
    if count >= total:
        return set(range(total))

    import random

    rng = random.Random(seed)
    return set(rng.sample(range(total), count))


def append_full_repeats(
    input_path: Path,
    output_handle,
    repeats: int,
    corpus: str,
    source_split: str | None,
) -> int:
    written = 0
    for _ in range(repeats):
        for line in iter_corpus_lines(input_path, corpus, source_split):
            output_handle.write(line)
            written += 1
    return written


def append_selected_indices(
    input_path: Path,
    output_handle,
    indices: set[int],
    corpus: str,
    source_split: str | None,
) -> int:
    if not indices:
        return 0

    written = 0
    current = 0
    for line in iter_corpus_lines(input_path, corpus, source_split):
        if current in indices:
            output_handle.write(line)
            written += 1
        current += 1
    return written


def file_fingerprint(path: Path) -> dict[str, int | str]:
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def plan_lines(
    input_path: Path,
    plan: CorpusPlan,
    input_lines: int,
    seed: int,
    source_split: str | None,
) -> tuple[list[str], dict]:
    target_lines = rounded_target(input_lines, plan.ratio)
    full_repeats = target_lines // input_lines
    fractional_lines = target_lines % input_lines
    sample_seed = stable_seed(seed, plan.corpus)
    sampled_indices = choose_sample_indices(input_lines, fractional_lines, sample_seed)

    lines = []
    for _ in range(full_repeats):
        lines.extend(iter_corpus_lines(input_path, plan.corpus, source_split))
    for current, line in enumerate(iter_corpus_lines(input_path, plan.corpus, source_split)):
        if current in sampled_indices:
            lines.append(line)

    summary = {
        "corpus": plan.corpus,
        "input_file": str(input_path),
        "input_file_fingerprint": file_fingerprint(input_path),
        "input_lines": input_lines,
        "source_split": source_split if not plan.corpus.startswith("knowledge_") else "knowledge",
        "sampling_ratio": plan.ratio,
        "target_output_lines": target_lines,
        "full_repeats": full_repeats,
        "fractional_sample_lines": fractional_lines,
        "fractional_sample_seed": sample_seed,
        "actual_output_lines": len(lines),
    }
    return lines, summary


def build_dataset(
    source_dir: Path,
    output_path: Path,
    summary_path: Path,
    seed: int,
    source_split: str | None,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    corpus_summaries = []
    total_written = 0
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")

    with temp_output.open("w", encoding="utf-8") as out_handle:
        for plan in DEFAULT_PLAN:
            input_path = source_dir / plan.filename
            if not input_path.exists():
                raise FileNotFoundError(input_path)

            input_lines = count_corpus_lines(input_path, plan.corpus, source_split)
            if input_lines == 0:
                raise RuntimeError(f"{input_path} has no non-empty JSONL rows")

            target_lines = rounded_target(input_lines, plan.ratio)
            full_repeats = target_lines // input_lines
            fractional_lines = target_lines % input_lines
            sample_seed = stable_seed(seed, plan.corpus)
            sampled_indices = choose_sample_indices(input_lines, fractional_lines, sample_seed)

            written = 0
            written += append_full_repeats(
                input_path,
                out_handle,
                full_repeats,
                plan.corpus,
                source_split,
            )
            written += append_selected_indices(
                input_path,
                out_handle,
                sampled_indices,
                plan.corpus,
                source_split,
            )
            total_written += written

            corpus_summaries.append(
                {
                    "corpus": plan.corpus,
                    "input_file": str(input_path),
                    "input_file_fingerprint": file_fingerprint(input_path),
                    "input_lines": input_lines,
                    "source_split": source_split if not plan.corpus.startswith("knowledge_") else "knowledge",
                    "sampling_ratio": plan.ratio,
                    "target_output_lines": target_lines,
                    "full_repeats": full_repeats,
                    "fractional_sample_lines": fractional_lines,
                    "fractional_sample_seed": sample_seed,
                    "actual_output_lines": written,
                }
            )

    shutil.move(str(temp_output), str(output_path))

    summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed,
        "source_split": source_split,
        "source_dir": str(source_dir),
        "output_file": str(output_path),
        "output_file_fingerprint": file_fingerprint(output_path),
        "total_output_lines": total_written,
        "corpora": corpus_summaries,
        "elapsed_seconds": round(time.time() - start, 3),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def build_shuffled_only(
    source_dir: Path,
    output_path: Path,
    summary_path: Path,
    seed: int,
    shuffle_seed: int,
    source_split: str | None,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    lines = []
    corpus_summaries = []
    for plan in DEFAULT_PLAN:
        input_path = source_dir / plan.filename
        if not input_path.exists():
            raise FileNotFoundError(input_path)

        input_lines = count_corpus_lines(input_path, plan.corpus, source_split)
        if input_lines == 0:
            raise RuntimeError(f"{input_path} has no selected JSONL rows")

        corpus_lines, corpus_summary = plan_lines(
            input_path,
            plan,
            input_lines,
            seed,
            source_split,
        )
        lines.extend(corpus_lines)
        corpus_summaries.append(corpus_summary)

    rng = random.Random(shuffle_seed)
    rng.shuffle(lines)

    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    with temp_output.open("w", encoding="utf-8") as handle:
        handle.writelines(lines)
    shutil.move(str(temp_output), str(output_path))

    summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed,
        "shuffle_seed": shuffle_seed,
        "source_split": source_split,
        "source_dir": str(source_dir),
        "output_file": str(output_path),
        "output_file_fingerprint": file_fingerprint(output_path),
        "total_output_lines": len(lines),
        "corpora": corpus_summaries,
        "elapsed_seconds": round(time.time() - start, 3),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def shuffle_jsonl(input_path: Path, output_path: Path, seed: int) -> dict:
    start = time.time()
    with input_path.open("r", encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]

    rng = random.Random(seed)
    rng.shuffle(lines)

    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    with temp_output.open("w", encoding="utf-8") as handle:
        handle.writelines(lines)
    shutil.move(str(temp_output), str(output_path))

    return {
        "input_file": str(input_path),
        "output_file": str(output_path),
        "seed": seed,
        "lines": len(lines),
        "output_file_fingerprint": file_fingerprint(output_path),
        "elapsed_seconds": round(time.time() - start, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("PianoCoReS/Corpora/language_cpt"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("PianoCoReS/Corpora/language_cpt/language_cpt_s1.jsonl"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("PianoCoReS/Corpora/language_cpt/language_cpt_s1.summary.json"),
    )
    parser.add_argument(
        "--shuffled-output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--shuffled-only",
        action="store_true",
        help="Write only the shuffled output path without keeping an unshuffled mix.",
    )
    parser.add_argument(
        "--source-split",
        type=str,
        default=None,
        help="Select this source_split from non-knowledge CPT corpora.",
    )
    parser.add_argument("--shuffle-seed", type=int, default=42)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.shuffled_only:
        if args.shuffled_output is None:
            parser.error("--shuffled-only requires --shuffled-output")
        summary = build_shuffled_only(
            args.source_dir,
            args.shuffled_output,
            args.summary,
            args.seed,
            args.shuffle_seed,
            args.source_split,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    summary = build_dataset(args.source_dir, args.output, args.summary, args.seed, args.source_split)
    if args.shuffled_output is not None:
        shuffled = shuffle_jsonl(args.output, args.shuffled_output, args.shuffle_seed)
        summary["shuffled_output"] = shuffled
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
