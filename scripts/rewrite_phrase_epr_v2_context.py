#!/usr/bin/env python3
"""Rewrite phrase EPR samples to the V2 compact context design.

V1 phrase EPR used:
  score_snip = H_{k-1} + H_k + H_{k+1}
  perf_context = phi_{H_{k-1}}

V2 uses:
  score_snip = M_prev + H_k + M_next
  perf_context = phi_{M_prev}

This keeps the current phrase score intact while reducing neighboring context
to one score/performance measure.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

from transformers import AutoTokenizer


COUNT_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]
PHRASE_RE = re.compile(r"^(H\d+)(?::\d+)?\s*$")
TOKEN_PHRASE_RE = re.compile(r"^<H><V(\d{3})>\s*$")
MEASURE_RE = re.compile(r"^M\d+(?::|\s|\t|$)")
TOKEN_MEASURE_RE = re.compile(r"^<M><V\d{3}>(?:\t|\s|[A-Ga-gz\[\]!\"_^=.])")


def elapsed(start: float) -> str:
    return f"{time.time() - start:.1f}s"


def record_text(record: dict) -> str:
    return " ".join(str(record.get(field, "")) for field in COUNT_FIELDS)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def phrase_label(line: str) -> str | None:
    stripped = line.strip()
    match = PHRASE_RE.match(stripped)
    if match:
        return match.group(1)
    token_match = TOKEN_PHRASE_RE.match(stripped)
    if token_match:
        return f"H{int(token_match.group(1)) + 1}"
    return None


def is_measure_line(line: str) -> bool:
    stripped = line.strip()
    return bool(MEASURE_RE.match(stripped) or TOKEN_MEASURE_RE.match(stripped))


def phrase_groups(score_snip: str) -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    current_label = ""
    current_lines: list[str] = []

    for raw_line in score_snip.splitlines():
        line = raw_line.rstrip()
        label = phrase_label(line)
        if label:
            if current_label and current_lines:
                groups.append((current_label, current_lines))
            current_label = label
            current_lines = [line]
        elif current_label:
            current_lines.append(line)

    if current_label and current_lines:
        groups.append((current_label, current_lines))
    return groups


def first_measure(lines: list[str]) -> str:
    for line in lines:
        if is_measure_line(line):
            return line
    return ""


def last_measure(lines: list[str]) -> str:
    for line in reversed(lines):
        if is_measure_line(line):
            return line
    return ""


def rewrite_score_snip(score_snip: str, target_phrase_id: str) -> tuple[str, bool]:
    groups = phrase_groups(score_snip)
    if not groups:
        return score_snip, False

    target = target_phrase_id.split(":", 1)[0]
    target_index = next((idx for idx, (label, _) in enumerate(groups) if label == target), None)
    if target_index is None:
        return score_snip, False

    out: list[str] = []
    if target_index > 0:
        prev = last_measure(groups[target_index - 1][1])
        if prev:
            out.append(prev)

    out.extend(groups[target_index][1])

    if target_index + 1 < len(groups):
        nxt = first_measure(groups[target_index + 1][1])
        if nxt:
            out.append(nxt)

    return "\n".join(out), True


def rewrite_perf_context(perf_context: str) -> tuple[str, bool]:
    if not perf_context:
        return "", True
    prev_measure = last_measure(perf_context.splitlines())
    if not prev_measure:
        return "", False
    return prev_measure, True


def rewrite_record(record: dict) -> tuple[dict, bool, bool]:
    if record.get("task") != "phrase_epr":
        return record, False, False

    out = dict(record)
    out["score_snip"], score_ok = rewrite_score_snip(
        str(record.get("score_snip", "")),
        str(record.get("target_phrase_id", "")),
    )
    out["perf_context"], perf_ok = rewrite_perf_context(str(record.get("perf_context", "")))
    out["context_design"] = "phrase_epr_v2_prev_measure"
    return out, score_ok, perf_ok


def rewrite_file(
    src: Path,
    dst: Path,
    tokenizer=None,
    batch_size: int = 1024,
) -> dict:
    stats = {
        "file": str(src),
        "rows": 0,
        "score_rewritten": 0,
        "score_missing": 0,
        "perf_rewritten": 0,
        "perf_missing": 0,
        "tokens": 0,
        "max_tokens": 0,
        "le_2048": 0,
        "le_3096": 0,
        "le_4096": 0,
    }
    dst.parent.mkdir(parents=True, exist_ok=True)

    batch: list[str] = []

    def flush() -> None:
        if not batch or tokenizer is None:
            batch.clear()
            return
        lengths = token_lengths(tokenizer, batch)
        for length in lengths:
            stats["tokens"] += length
            stats["max_tokens"] = max(stats["max_tokens"], length)
            stats["le_2048"] += int(length <= 2048)
            stats["le_3096"] += int(length <= 3096)
            stats["le_4096"] += int(length <= 4096)
        batch.clear()

    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            record = json.loads(line)
            rewritten, score_ok, perf_ok = rewrite_record(record)
            fout.write(json.dumps(rewritten, ensure_ascii=False) + "\n")

            stats["rows"] += 1
            stats["score_rewritten"] += int(score_ok)
            stats["score_missing"] += int(not score_ok)
            stats["perf_rewritten"] += int(perf_ok)
            stats["perf_missing"] += int(not perf_ok)

            if tokenizer is not None:
                batch.append(record_text(rewritten))
                if len(batch) >= batch_size:
                    flush()
        flush()

    return stats


def replace_files(paths: list[Path], tokenizer_path: Path | None, batch_size: int, work_dir: Path) -> list[dict]:
    start = time.time()
    tokenizer = None
    if tokenizer_path is not None:
        tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path), trust_remote_code=True)

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="phrase_epr_v2_", dir=str(work_dir)))

    stats: list[dict] = []
    try:
        for src in paths:
            if not src.exists():
                raise FileNotFoundError(src)
            tmp = temp_dir / src.name
            print(f"Rewriting {src} ...", flush=True)
            row = rewrite_file(src, tmp, tokenizer=tokenizer, batch_size=batch_size)
            shutil.move(str(tmp), str(src))
            stats.append(row)
            print(
                f"  rows={row['rows']:,}, <=2048={row['le_2048']:,}, "
                f"<=3096={row['le_3096']:,}, max={row['max_tokens']:,}, {elapsed(start)}",
                flush=True,
            )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return stats


def expand_inputs(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.glob("phrase_epr_*.jsonl")))
        else:
            files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--tokenizer", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=Path("PianoCoReS/.tmp_phrase_epr_v2"))
    args = parser.parse_args()

    files = expand_inputs(args.paths)
    stats = replace_files(files, args.tokenizer, args.batch_size, args.work_dir)

    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.summary}")


if __name__ == "__main__":
    main()
