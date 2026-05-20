#!/usr/bin/env python3
"""Rebuild CoReS language_sft_s1 and language_sft_s2 with token budgets.

Policy:
1. Convert the 6 raw language tasks to Swift chat-message format.
2. Filter all rows by exact chat-template token length with max_length=512.
3. Score tasks:
   - keep all continuation rows after filtering
   - sample each mask task down to the row count of its paired continuation task
4. Performance tasks:
   - try to keep all ASAP rows within the perf budget
   - keep at least one non-ASAP row per source per task when available
   - fill remaining budget by source-balanced random sampling
5. Build S1/S2 with explicit score/perf token targets.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import shutil
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from transformers import AutoTokenizer

from prepare_core_s1_swift import convert_sample


RAW_TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]

SCORE_TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
]

PERF_TASK_FILES = [
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]

TOTAL_RANGES = {
    "s1": (600_000_000, 650_000_000),
    "s2": (300_000_000, 350_000_000),
}

SCORE_TARGETS = {
    "s1": 80_000_000,
    "s2": 40_000_000,
}

PERF_TARGETS = {
    "s1": 600_000_000,
    "s2": 300_000_000,
}


@dataclass
class FilteredRow:
    raw_line: str
    task_file: str
    piece_id: str
    source_group: str
    is_asap: bool
    tokens: int


def stable_seed(seed: int, *parts: str) -> int:
    text = ":".join([str(seed), *parts])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def performance_piece_id(perf_tsv_path: str) -> str:
    path = str(perf_tsv_path)
    if path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/"):]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/"):]
    if path.endswith(".tsv"):
        path = path[:-4]
    return path


def load_perf_metadata(metadata_path: Path) -> dict[str, dict[str, object]]:
    info: dict[str, dict[str, object]] = {}
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            perf_path = row.get("performance_tsv_path", "")
            if not perf_path:
                continue
            piece_id = performance_piece_id(perf_path)
            info[piece_id] = {
                "source_group": row.get("performance_dataset") or row.get("capture_model") or "unknown",
                "is_asap": row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False",
            }
    return info


def task_name_from_file(task_file: str) -> str:
    return task_file.removesuffix(".jsonl")


def render_messages(tokenizer, messages: list[dict]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
    except Exception:
        return "\n".join(str(message.get("content", "")) for message in messages)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def convert_and_filter_task(
    tokenizer,
    input_path: Path,
    output_path: Path,
    perf_meta: dict[str, dict[str, object]],
    max_tokens: int,
    batch_size: int,
) -> list[FilteredRow]:
    task_file = input_path.name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    kept_rows: list[FilteredRow] = []
    batch_meta: list[tuple[str, str, bool, str]] = []
    batch_texts: list[str] = []

    with input_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        def flush() -> None:
            nonlocal batch_meta, batch_texts
            if not batch_meta:
                return
            lengths = token_lengths(tokenizer, batch_texts)
            for (piece_id, source_group, is_asap, raw_line), tokens in zip(batch_meta, lengths):
                if tokens <= max_tokens:
                    fout.write(raw_line)
                    kept_rows.append(
                        FilteredRow(
                            raw_line=raw_line,
                            task_file=task_file,
                            piece_id=piece_id,
                            source_group=source_group,
                            is_asap=is_asap,
                            tokens=tokens,
                        )
                    )
            batch_meta = []
            batch_texts = []

        for line in fin:
            if not line.strip():
                continue
            sample = json.loads(line)
            converted = convert_sample(sample)
            raw = json.dumps(converted, ensure_ascii=False) + "\n"
            piece_id = str(sample.get("piece_id", ""))
            meta = perf_meta.get(piece_id, {})
            source_group = str(meta.get("source_group", "score")) if "perf_lang" in task_file else "score"
            is_asap = bool(meta.get("is_asap", False)) if "perf_lang" in task_file else False
            batch_meta.append((piece_id, source_group, is_asap, raw))
            batch_texts.append(render_messages(tokenizer, converted["messages"]))
            if len(batch_meta) >= batch_size:
                flush()
        flush()

    return kept_rows


def total_tokens(rows: list[FilteredRow]) -> int:
    return sum(row.tokens for row in rows)


def total_rows(rows: list[FilteredRow]) -> int:
    return len(rows)


def sample_rows_to_count(rows: list[FilteredRow], target_count: int, seed: int, label: str) -> list[FilteredRow]:
    if target_count >= len(rows):
        return list(rows)
    if target_count <= 0:
        return []
    rng = random.Random(stable_seed(seed, label, "count"))
    pool = list(rows)
    rng.shuffle(pool)
    pool.sort(key=lambda row: row.tokens)
    return pool[:target_count]


def choose_score_rows(all_rows: dict[str, list[FilteredRow]], setting: str, seed: int) -> dict[str, list[FilteredRow]]:
    selected: dict[str, list[FilteredRow]] = {}

    m_cont = list(all_rows.get("measure_score_lang_continuation.jsonl", []))
    p_cont = list(all_rows.get("phrase_score_lang_continuation.jsonl", []))
    m_mask = list(all_rows.get("measure_score_lang_mask.jsonl", []))
    p_mask = list(all_rows.get("phrase_score_lang_mask.jsonl", []))

    selected["measure_score_lang_continuation.jsonl"] = m_cont
    selected["phrase_score_lang_continuation.jsonl"] = p_cont
    selected["measure_score_lang_mask.jsonl"] = sample_rows_to_count(
        m_mask, len(m_cont), seed, f"{setting}:measure_score_lang_mask"
    )
    selected["phrase_score_lang_mask.jsonl"] = sample_rows_to_count(
        p_mask, len(p_cont), seed, f"{setting}:phrase_score_lang_mask"
    )
    return selected


def sample_perf_task(
    rows: list[FilteredRow],
    target_tokens: int,
    seed: int,
    label: str,
) -> list[FilteredRow]:
    if target_tokens <= 0 or not rows:
        return []

    rng = random.Random(stable_seed(seed, label, "perf"))
    asap = [row for row in rows if row.is_asap]
    non_asap = [row for row in rows if not row.is_asap]

    # Start with ASAP, smaller-token rows first so we keep as many as possible.
    asap_sorted = sorted(asap, key=lambda row: row.tokens)
    selected: list[FilteredRow] = []
    used_tokens = 0
    for row in asap_sorted:
        if used_tokens + row.tokens <= target_tokens:
            selected.append(row)
            used_tokens += row.tokens

    if used_tokens >= target_tokens:
        return selected

    # Keep at least one non-ASAP row per source if possible.
    by_source: dict[str, list[FilteredRow]] = defaultdict(list)
    for row in non_asap:
        by_source[row.source_group].append(row)

    source_names = list(by_source)
    rng.shuffle(source_names)
    remaining_by_source: dict[str, deque[FilteredRow]] = {}
    for source in source_names:
        pool = list(by_source[source])
        rng.shuffle(pool)
        pool = deque(sorted(pool, key=lambda row: row.tokens))
        first = pool.popleft()
        if used_tokens + first.tokens <= target_tokens:
            selected.append(first)
            used_tokens += first.tokens
        if pool:
            remaining_by_source[source] = pool

    # Source-balanced round-robin fill.
    active = [source for source in source_names if source in remaining_by_source]
    while active and used_tokens < target_tokens:
        rng.shuffle(active)
        next_active = []
        for source in active:
            pool = remaining_by_source[source]
            if not pool:
                continue
            row = pool.popleft()
            if used_tokens + row.tokens <= target_tokens:
                selected.append(row)
                used_tokens += row.tokens
            if pool:
                next_active.append(source)
            if used_tokens >= target_tokens:
                break
        active = next_active

    return selected


def allocate_perf_targets(
    perf_rows: dict[str, list[FilteredRow]],
    total_target_tokens: int,
) -> dict[str, int]:
    totals = {task_file: total_tokens(rows) for task_file, rows in perf_rows.items()}
    total_perf_tokens = sum(totals.values())
    if total_perf_tokens == 0:
        return {task_file: 0 for task_file in perf_rows}
    targets = {}
    assigned = 0
    items = list(perf_rows)
    for task_file in items[:-1]:
        portion = round(total_target_tokens * totals[task_file] / total_perf_tokens)
        targets[task_file] = portion
        assigned += portion
    targets[items[-1]] = max(0, total_target_tokens - assigned)
    return targets


def write_task_dir(
    output_dir: Path,
    selected_rows: dict[str, list[FilteredRow]],
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for task_file in RAW_TASK_FILES:
        rows = selected_rows.get(task_file, [])
        with (output_dir / task_file).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(row.raw_line)
        counts[task_file] = len(rows)
    with (output_dir / "counts.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples"])
        writer.writeheader()
        for task_file in RAW_TASK_FILES:
            writer.writerow({"file": task_file, "kept_samples": counts[task_file]})
    return counts


def write_combined_train(output_dir: Path) -> int:
    output_path = output_dir / "sft_language_train.jsonl"
    with output_path.open("w", encoding="utf-8") as fout:
        total = 0
        for task_file in RAW_TASK_FILES:
            src = output_dir / task_file
            with src.open("r", encoding="utf-8") as fin:
                for line in fin:
                    if not line.strip():
                        continue
                    fout.write(line)
                    total += 1
    return total


def summarize_selected(selected_rows: dict[str, list[FilteredRow]]) -> dict[str, int]:
    score_rows = sum(total_rows(rows) for task, rows in selected_rows.items() if "score_lang" in task)
    perf_rows = sum(total_rows(rows) for task, rows in selected_rows.items() if "perf_lang" in task)
    score_tokens = sum(total_tokens(rows) for task, rows in selected_rows.items() if "score_lang" in task)
    perf_tokens = sum(total_tokens(rows) for task, rows in selected_rows.items() if "perf_lang" in task)
    return {
        "score_rows": score_rows,
        "perf_rows": perf_rows,
        "score_tokens": score_tokens,
        "perf_tokens": perf_tokens,
        "total_rows": score_rows + perf_rows,
        "total_tokens": score_tokens + perf_tokens,
    }


def replace_dir_or_link(path: Path, replacement_dir: Path, backup_name: str) -> None:
    backup = path.parent / backup_name
    if backup.exists() or backup.is_symlink():
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup)
        else:
            backup.unlink()
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            shutil.move(str(path), str(backup))
        elif path.is_dir():
            shutil.move(str(path), str(backup))
        else:
            raise RuntimeError(f"Unexpected path type: {path}")
    shutil.move(str(replacement_dir), str(path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("sft_data/core-s-train"))
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--cores-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    perf_meta = load_perf_metadata(args.metadata)
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)

    filtered_root = args.cores_root / ".language_sft_filtered_tmp"
    if filtered_root.exists():
        shutil.rmtree(filtered_root)
    filtered_root.mkdir(parents=True)

    filtered_rows: dict[str, list[FilteredRow]] = {}
    for task_file in RAW_TASK_FILES:
        input_path = args.input_dir / task_file
        output_path = filtered_root / task_file
        filtered_rows[task_file] = convert_and_filter_task(
            tokenizer=tokenizer,
            input_path=input_path,
            output_path=output_path,
            perf_meta=perf_meta,
            max_tokens=args.max_tokens,
            batch_size=args.batch_size,
        )
        print(
            f"filtered {task_file}: rows={total_rows(filtered_rows[task_file]):,}, "
            f"tokens={total_tokens(filtered_rows[task_file]):,}",
            flush=True,
        )

    for setting in ("s1", "s2"):
        selected: dict[str, list[FilteredRow]] = {}
        score_selected = choose_score_rows(filtered_rows, setting, args.seed)
        selected.update(score_selected)

        score_tokens = sum(total_tokens(rows) for rows in score_selected.values())
        perf_target = PERF_TARGETS[setting]
        perf_rows = {task_file: filtered_rows[task_file] for task_file in PERF_TASK_FILES}
        perf_targets = allocate_perf_targets(perf_rows, perf_target)

        for task_file in PERF_TASK_FILES:
            selected[task_file] = sample_perf_task(
                perf_rows[task_file],
                perf_targets[task_file],
                seed=args.seed,
                label=f"{setting}:{task_file}",
            )

        summary = summarize_selected(selected)
        summary["score_target_tokens"] = SCORE_TARGETS[setting]
        summary["perf_target_tokens"] = PERF_TARGETS[setting]
        summary["total_target_range"] = TOTAL_RANGES[setting]
        print(f"\n{setting.upper()} summary:")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

        tmp_dir = args.cores_root / f".language_sft_{setting}_tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        write_task_dir(tmp_dir, selected)
        write_combined_train(tmp_dir)

    replace_dir_or_link(
        args.cores_root / "language_sft_s1",
        args.cores_root / ".language_sft_s1_tmp",
        "language_sft_s1.bak_before_rebuild",
    )
    replace_dir_or_link(
        args.cores_root / "language_sft_s2",
        args.cores_root / ".language_sft_s2_tmp",
        "language_sft_s2.bak_before_rebuild",
    )

    rebuild_summary = {}
    for setting in ("s1", "s2"):
        out_dir = args.cores_root / f"language_sft_{setting}"
        counts = {}
        with (out_dir / "counts.csv").open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                counts[row["file"]] = int(row["kept_samples"])
        rebuild_summary[setting] = counts

    (args.cores_root / "language_sft_rebuild_summary.json").write_text(
        json.dumps(rebuild_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    shutil.rmtree(filtered_root, ignore_errors=True)


if __name__ == "__main__":
    main()
