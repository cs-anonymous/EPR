#!/usr/bin/env python3
"""Build sampled CoReS EPR SFT datasets.

Sampling policy:
  1. Token-filter measure EPR with max_token=1024 and phrase EPR with
     V2 compact context max_token=2560.
  2. Keep all filtered coldstart and ending samples.
  3. For main samples, keep all filtered ASAP samples. For the remaining
     non-ASAP samples, sample about 1/5 with at least one sample per
     performance and an approximately equal budget per performance.

The script writes sampled files to a temporary directory first, then replaces
PianoCoReS/CoReS/{measure,phrase}_epr_sft only after all outputs are complete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import tempfile
import time
from collections import Counter
from pathlib import Path

from transformers import AutoTokenizer


COUNT_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]
TASK_CONFIGS = {
    "measure_epr": {"max_token": 1024},
    "phrase_epr": {"max_token": 2560},
}
TASK_TYPES = ["coldstart", "main", "ending"]


def elapsed(start: float) -> str:
    return f"{time.time() - start:.1f}s"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ["B", "K", "M", "G", "T"]:
        if value < 1024 or unit == "T":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{num_bytes}B"


def stable_seed(seed: int, *parts: str) -> int:
    text = ":".join([str(seed), *parts])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def performance_piece_id(perf_tsv_path: str) -> str:
    path = str(perf_tsv_path)
    if path.startswith("PianoCoReS/aligned/"):
        path = path[len("PianoCoReS/aligned/"):]
    elif path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/"):]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/"):]
    if path.endswith(".tsv"):
        path = path[: -len(".tsv")]
    return path


def load_asap_piece_ids(metadata_path: Path) -> set[str]:
    asap_ids = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False":
                piece_id = performance_piece_id(row.get("performance_tsv_path", ""))
                if piece_id:
                    asap_ids.add(piece_id)
    return asap_ids


def record_text(record: dict) -> str:
    return " ".join(str(record.get(field, "")) for field in COUNT_FIELDS)


def _is_phrase_header(line: str) -> bool:
    stripped = line.strip()
    return bool(re.fullmatch(r"<H><V\d{3}>", stripped)) or (
        stripped.startswith("H") and stripped[1:].isdigit()
    )


def _is_measure_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^<M><V\d{3}>(?:\t|\s|[A-Ga-gz\[\]!\"_^=.])", stripped)) or (
        stripped.startswith("M") and len(stripped) > 1 and stripped[1].isdigit()
    )


def _phrase_groups(score_snip: str) -> list[tuple[str, list[str]]]:
    groups = []
    current_label = ""
    current_lines = []
    for raw_line in score_snip.splitlines():
        line = raw_line.rstrip()
        if _is_phrase_header(line):
            if current_label and current_lines:
                groups.append((current_label, current_lines))
            current_label = line.strip()
            current_lines = [line]
        elif current_label:
            current_lines.append(line)
    if current_label and current_lines:
        groups.append((current_label, current_lines))
    return groups


def _first_measure(lines: list[str]) -> str:
    for line in lines:
        if _is_measure_line(line):
            return line
    return ""


def _last_measure(lines: list[str]) -> str:
    for line in reversed(lines):
        if _is_measure_line(line):
            return line
    return ""


def compact_phrase_epr_context(record: dict) -> dict:
    """Apply phrase EPR V2 context: M_prev + H_k + M_next, phi_M_prev."""
    if record.get("task") != "phrase_epr":
        return record

    out = dict(record)
    groups = _phrase_groups(str(record.get("score_snip", "")))
    target = str(record.get("target_phrase_id", ""))
    target_index = next((idx for idx, (label, _) in enumerate(groups) if label == target), None)
    if target_index is not None:
        score_lines = []
        if target_index > 0:
            prev = _last_measure(groups[target_index - 1][1])
            if prev:
                score_lines.append(prev)
        score_lines.extend(groups[target_index][1])
        if target_index + 1 < len(groups):
            nxt = _first_measure(groups[target_index + 1][1])
            if nxt:
                score_lines.append(nxt)
        out["score_snip"] = "\n".join(score_lines)

    out["perf_context"] = _last_measure(str(record.get("perf_context", "")).splitlines())
    out["context_design"] = "phrase_epr_v2_prev_measure"
    return out


def count_lines(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def filter_by_token_count(
    tokenizer,
    input_path: Path,
    output_path: Path,
    max_token: int,
    batch_size: int,
) -> dict:
    start = time.time()
    total = count_lines(input_path)
    kept = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"  Token filtering: {input_path.name}, max_token={max_token}, rows={total:,}")
    with input_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        raw_batch: list[str] = []
        text_batch: list[str] = []
        processed = 0
        batch_index = 0

        def flush() -> None:
            nonlocal kept, processed, batch_index, raw_batch, text_batch
            if not raw_batch:
                return
            lengths = token_lengths(tokenizer, text_batch)
            for raw, length in zip(raw_batch, lengths):
                if length <= max_token:
                    fout.write(raw)
                    kept += 1
            processed += len(raw_batch)
            batch_index += 1
            if batch_index % 50 == 0 or processed == total:
                rate = kept / processed * 100 if processed else 0.0
                print(
                    f"    processed={processed:,}/{total:,}, kept={kept:,} "
                    f"({rate:.1f}%), {elapsed(start)}",
                    flush=True,
                )
            raw_batch = []
            text_batch = []

        for line in fin:
            if not line.strip():
                continue
            record = json.loads(line)
            record = compact_phrase_epr_context(record)
            raw = json.dumps(record, ensure_ascii=False) + "\n"
            raw_batch.append(raw)
            text_batch.append(record_text(record))
            if len(raw_batch) >= batch_size:
                flush()
        flush()

    return {
        "input_rows": total,
        "filtered_rows": kept,
        "filter_retention": kept / total if total else 0.0,
    }


def copy_filtered_all(filtered_path: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(filtered_path, output_path)
    return count_lines(output_path)


def allocate_equal_budgets(
    counts: dict[str, int],
    target_total: int,
    rng: random.Random,
) -> dict[str, int]:
    if not counts:
        return {}

    pids = list(counts)
    rng.shuffle(pids)
    target_total = min(sum(counts.values()), max(len(pids), target_total))

    base = target_total // len(pids)
    remainder = target_total % len(pids)
    budgets = {
        pid: min(counts[pid], base + (1 if idx < remainder else 0))
        for idx, pid in enumerate(pids)
    }

    # If some performances had fewer samples than their assigned budget,
    # redistribute the unused slots to performances that still have capacity.
    current = sum(budgets.values())
    while current < target_total:
        candidates = [pid for pid in pids if budgets[pid] < counts[pid]]
        if not candidates:
            break
        rng.shuffle(candidates)
        for pid in candidates:
            if current >= target_total:
                break
            budgets[pid] += 1
            current += 1

    return budgets


def sample_main_file(
    filtered_path: Path,
    output_path: Path,
    asap_ids: set[str],
    sample_ratio: float,
    seed: int,
    task_name: str,
) -> dict:
    start = time.time()
    asap_rows = 0
    non_asap_counts: Counter[str] = Counter()

    print("  Main sampling: counting ASAP/non-ASAP rows...")
    with filtered_path.open("r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            piece_id = record.get("piece_id", "")
            if piece_id in asap_ids:
                asap_rows += 1
            else:
                non_asap_counts[piece_id] += 1

    non_asap_rows = sum(non_asap_counts.values())
    rng = random.Random(stable_seed(seed, task_name, "main"))
    target_non_asap = round(non_asap_rows * sample_ratio)
    budgets = allocate_equal_budgets(non_asap_counts, target_non_asap, rng)

    print(
        f"    ASAP kept all: {asap_rows:,}; non-ASAP rows={non_asap_rows:,}; "
        f"performances={len(non_asap_counts):,}; sampled target={sum(budgets.values()):,}",
        flush=True,
    )

    keep_positions: dict[str, set[int]] = {}
    for pid, count in non_asap_counts.items():
        budget = budgets.get(pid, 0)
        if budget >= count:
            keep_positions[pid] = set(range(count))
        else:
            keep_positions[pid] = set(rng.sample(range(count), budget))

    seen_non_asap: Counter[str] = Counter()
    output_rows = 0
    sampled_non_asap = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("  Main sampling: writing sampled output...")
    with filtered_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            record = json.loads(line)
            piece_id = record.get("piece_id", "")
            if piece_id in asap_ids:
                fout.write(line)
                output_rows += 1
                continue

            index = seen_non_asap[piece_id]
            seen_non_asap[piece_id] += 1
            if index in keep_positions[piece_id]:
                fout.write(line)
                output_rows += 1
                sampled_non_asap += 1

    print(
        f"    Wrote main output={output_rows:,} "
        f"(ASAP={asap_rows:,}, sampled non-ASAP={sampled_non_asap:,}) in {elapsed(start)}",
        flush=True,
    )

    return {
        "asap_rows": asap_rows,
        "non_asap_rows": non_asap_rows,
        "non_asap_performances": len(non_asap_counts),
        "sampled_non_asap": sampled_non_asap,
        "output_rows": output_rows,
    }


def process_subset(
    tokenizer,
    input_path: Path,
    output_path: Path,
    task_name: str,
    task_type: str,
    max_token: int,
    asap_ids: set[str],
    sample_ratio: float,
    seed: int,
    batch_size: int,
    temp_dir: Path,
) -> dict:
    print(f"\n--- {task_name}/{task_type} ---", flush=True)
    filtered_path = temp_dir / f"{task_name}_{task_type}.filtered.jsonl"
    result = {
        "family": f"{task_name}_sft",
        "file": str(output_path),
        "task_name": task_name,
        "task_type": task_type,
        "max_token": max_token,
    }
    result.update(filter_by_token_count(tokenizer, input_path, filtered_path, max_token, batch_size))

    if task_type in {"coldstart", "ending"}:
        output_rows = copy_filtered_all(filtered_path, output_path)
        result.update({
            "output_rows": output_rows,
            "note": f"sampled_token<={max_token};kept_all_filtered_{task_type}",
        })
        print(f"  Kept all filtered {task_type}: {output_rows:,}", flush=True)
    else:
        sample_stats = sample_main_file(
            filtered_path=filtered_path,
            output_path=output_path,
            asap_ids=asap_ids,
            sample_ratio=sample_ratio,
            seed=seed,
            task_name=task_name,
        )
        result.update(sample_stats)
        result["note"] = (
            f"sampled_token<={max_token};kept_all_asap;"
            f"uniform_non_asap_ratio={sample_ratio:g};min_one_per_performance"
        )

    filtered_path.unlink(missing_ok=True)
    result["bytes"] = output_path.stat().st_size
    result["size"] = human_size(result["bytes"])
    return result


def read_existing_stats(stats_path: Path) -> list[dict[str, str]]:
    if not stats_path.exists():
        return []
    with stats_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_updated_stats(stats_path: Path, sampled_results: list[dict]) -> None:
    rows = read_existing_stats(stats_path)
    replace_families = {r["family"] for r in sampled_results}
    kept_rows = [row for row in rows if row.get("family") not in replace_families]

    for result in sampled_results:
        kept_rows.append({
            "family": result["family"],
            "file": result["file"],
            "samples": str(result["output_rows"]),
            "bytes": str(result["bytes"]),
            "size": result["size"],
            "note": result["note"],
        })

    fieldnames = ["family", "file", "samples", "bytes", "size", "note"]
    with stats_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)


def replace_task_dirs(out_root: Path, temp_root: Path) -> None:
    for task_name in TASK_CONFIGS:
        final_dir = out_root / f"{task_name}_sft"
        sampled_dir = temp_root / f"{task_name}_sft"
        if not sampled_dir.exists():
            raise FileNotFoundError(sampled_dir)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.move(str(sampled_dir), str(final_dir))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--sample-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--work-dir", type=Path, default=Path("PianoCoReS/.tmp_cores_epr_sample"))
    args = parser.parse_args()

    overall_start = time.time()
    cores_root = args.cores_root
    work_dir = args.work_dir
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    temp_root = work_dir / "sampled_output"
    temp_filter_dir = Path(tempfile.mkdtemp(prefix="epr_filter_", dir=str(work_dir)))

    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)

    print("Loading ASAP performance ids...")
    asap_ids = load_asap_piece_ids(args.metadata)
    print(f"  ASAP performances: {len(asap_ids):,}")

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    print(f"  Tokenizer loaded in {elapsed(overall_start)}")

    results = []
    try:
        for task_name, cfg in TASK_CONFIGS.items():
            max_token = cfg["max_token"]
            input_dir = cores_root / f"{task_name}_sft"
            output_dir = temp_root / f"{task_name}_sft"
            for task_type in TASK_TYPES:
                input_path = input_dir / f"{task_name}_{task_type}.jsonl"
                output_path = output_dir / f"{task_name}_{task_type}.jsonl"
                if not input_path.exists():
                    raise FileNotFoundError(input_path)
                results.append(process_subset(
                    tokenizer=tokenizer,
                    input_path=input_path,
                    output_path=output_path,
                    task_name=task_name,
                    task_type=task_type,
                    max_token=max_token,
                    asap_ids=asap_ids,
                    sample_ratio=args.sample_ratio,
                    seed=args.seed,
                    batch_size=args.batch_size,
                    temp_dir=temp_filter_dir,
                ))

        replace_task_dirs(cores_root, temp_root)

        # Refresh output paths after moving temp directories into place.
        for result in results:
            result["file"] = str(cores_root / f"{result['task_name']}_sft" / f"{result['task_name']}_{result['task_type']}.jsonl")
            result["bytes"] = Path(result["file"]).stat().st_size
            result["size"] = human_size(result["bytes"])

        write_updated_stats(cores_root / "stats.csv", results)
        summary_path = cores_root / "epr_sampling_summary.json"
        summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    finally:
        shutil.rmtree(temp_filter_dir, ignore_errors=True)
        shutil.rmtree(temp_root, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    print("\nSummary")
    print("-------")
    total_input = sum(r["input_rows"] for r in results)
    total_filtered = sum(r["filtered_rows"] for r in results)
    total_output = sum(r["output_rows"] for r in results)
    for result in results:
        print(
            f"{result['task_name']}_{result['task_type']}: "
            f"input={result['input_rows']:,}, filtered={result['filtered_rows']:,}, "
            f"output={result['output_rows']:,}, size={result['size']}"
        )
    print(f"TOTAL: input={total_input:,}, filtered={total_filtered:,}, output={total_output:,}")
    print(f"Overall output/input retention: {total_output / total_input * 100:.2f}%")
    print(f"Done in {elapsed(overall_start)}")


if __name__ == "__main__":
    main()
