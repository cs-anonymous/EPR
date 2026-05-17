#!/usr/bin/env python3
"""Reformat score/performance text fields in SPIRE SFT JSONL files.

This rewrites score measure separators and performance-bearing fields to the
current compact formats:

    score measure:      M1 <ABCX content>
    score phrase:       H1\nM1 <ABCX content>\nM2 <ABCX content>
    performance measure: M1:1055 f:171:0:39 c:157:2:33 P:0:75
    performance phrase:  H1:421\nM1:1055 ...\nM2:936 ...

Non-JSONL files in each directory are copied unchanged.
"""
import argparse
import json
import multiprocessing as mp
import os
import re
import shutil
from pathlib import Path
from typing import Iterable

from tqdm import tqdm


TASK_FILES = [
    "measure_epr.jsonl",
    "phrase_epr.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
]

PERFORMANCE_FIELDS = {
    "measure_epr.jsonl": ["perf_target"],
    "phrase_epr.jsonl": ["perf_target"],
    "measure_perf_lang_continuation.jsonl": ["input", "target"],
    "measure_perf_lang_mask.jsonl": ["input", "target"],
}

PHRASE_PERFORMANCE_FIELDS = {
    "phrase_epr.jsonl": ["perf_target"],
    "phrase_perf_lang_continuation.jsonl": ["input", "target"],
    "phrase_perf_lang_mask.jsonl": ["input", "target"],
}

SCORE_FIELDS = {
    "measure_epr.jsonl": ["score_snip"],
    "phrase_epr.jsonl": ["score_snip"],
    "measure_score_lang_continuation.jsonl": ["input", "target"],
    "measure_score_lang_mask.jsonl": ["input", "target"],
    "phrase_score_lang_continuation.jsonl": ["input", "target"],
    "phrase_score_lang_mask.jsonl": ["input", "target"],
}

MEASURE_LINE_RE = re.compile(r"^(M\d+)\s+(.*)$")


def compact_perf_event(line: str) -> str:
    parts = line.replace("\t", " ").split()
    if not parts:
        return ""
    if parts[0] == "P":
        if len(parts) >= 3:
            return f"P:{parts[1]}:{parts[2]}"
        return ":".join(parts)
    if len(parts) == 1 and parts[0].count(":") >= 3:
        return parts[0]
    if len(parts) >= 3 and ":" in parts[0]:
        return f"{parts[0]}:{parts[1]}:{parts[2]}"
    return ":".join(parts)


def is_marker(token: str) -> bool:
    return len(token) >= 2 and token[0] in {"H", "M"} and token[1:].split(":", 1)[0].isdigit()


def is_compact_perf_marker(token: str) -> bool:
    return ":" in token and is_marker(token)


def compact_perf_text(text: str, phrase_newlines: bool = False) -> str:
    """Compact one measure or phrase performance string.

    Supports legacy newline/tab text and is idempotent for already compact text.
    """
    chunks: list[str] = []
    current = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        tokens = line.split()
        if not tokens:
            continue
        first = tokens[0]
        if is_compact_perf_marker(first):
            if current:
                chunks.append(" ".join(current))
            current = [first]
            for token in tokens[1:]:
                if is_compact_perf_marker(token):
                    chunks.append(" ".join(current))
                    current = [token]
                else:
                    current.append(token if token.count(":") >= 2 else compact_perf_event(token))
        else:
            event = compact_perf_event(line)
            if event:
                if not current:
                    current = [event]
                else:
                    current.append(event)

    if current:
        chunks.append(" ".join(current))
    return "\n".join(chunks) if phrase_newlines else " ".join(chunks)


def normalize_score_text(text: str) -> str:
    """Use `Hn` phrase headers and `Mn <content>` measure lines."""
    out = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        first = line.split(None, 1)[0]
        if re.fullmatch(r"H\d+", first):
            out.append(first)
            continue
        match = MEASURE_LINE_RE.match(line)
        if match:
            out.append(f"{match.group(1)} {match.group(2)}")
        else:
            out.append(line.replace("\t", " "))
    return "\n".join(out)


def transform_batch(args: tuple[str, list[str]]) -> list[str]:
    file_name, lines = args
    performance_fields = PERFORMANCE_FIELDS.get(file_name, [])
    phrase_performance_fields = set(PHRASE_PERFORMANCE_FIELDS.get(file_name, []))
    score_fields = SCORE_FIELDS.get(file_name, [])
    out = []
    for line in lines:
        if not performance_fields and not score_fields:
            out.append(line)
            continue
        sample = json.loads(line)
        for field in performance_fields:
            if field in sample and isinstance(sample[field], str):
                sample[field] = compact_perf_text(
                    sample[field],
                    phrase_newlines=field in phrase_performance_fields,
                )
        for field in score_fields:
            if field in sample and isinstance(sample[field], str):
                sample[field] = normalize_score_text(sample[field])
        out.append(json.dumps(sample, ensure_ascii=False) + "\n")
    return out


def batched_lines(path: Path, batch_size: int) -> Iterable[list[str]]:
    batch = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            batch.append(line)
            if len(batch) >= batch_size:
                yield batch
                batch = []
    if batch:
        yield batch


def reformat_file(src: Path, dst: Path, workers: int, batch_size: int) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.name not in PERFORMANCE_FIELDS and src.name not in SCORE_FIELDS:
        shutil.copyfile(src, dst)
        return sum(1 for _ in src.open("r", encoding="utf-8"))

    total = 0
    with dst.open("w", encoding="utf-8") as fout:
        with mp.Pool(processes=workers) as pool:
            work_iter = ((src.name, batch) for batch in batched_lines(src, batch_size))
            for out_batch in tqdm(
                pool.imap(transform_batch, work_iter, chunksize=2),
                desc=f"Reformat {src.name}",
            ):
                total += len(out_batch)
                fout.writelines(out_batch)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="sft_data/core-s")
    parser.add_argument("--output-dir", default="sft_data/core-s.compact.tmp")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for file_name in TASK_FILES:
        src = input_dir / file_name
        if not src.exists():
            continue
        dst = output_dir / file_name
        total = reformat_file(src, dst, args.workers, args.batch_size)
        print(f"{file_name}: {total:,} rows")

    for src in input_dir.iterdir():
        if src.name in TASK_FILES or src.name == output_dir.name:
            continue
        dst = output_dir / src.name
        if src.is_file():
            shutil.copyfile(src, dst)
        elif src.is_dir():
            shutil.copytree(src, dst)

    if args.replace:
        backup = input_dir.with_name(input_dir.name + ".pre_compact")
        if backup.exists():
            shutil.rmtree(backup)
        input_dir.rename(backup)
        output_dir.rename(input_dir)
        shutil.rmtree(backup)
        print(f"Replaced {input_dir}")
    else:
        print(f"Wrote compact data to {output_dir}")


if __name__ == "__main__":
    main()
