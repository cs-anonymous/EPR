#!/usr/bin/env python3
"""Build full ABCX2PM / SM2PM span EPR corpora and summarize token stats."""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from transformers import AutoTokenizer
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generate_sft_data import (  # noqa: E402
    AlignedABCXParser,
    TSVParser,
    format_perf_measure_with_index,
    format_score_measure,
    performance_piece_id,
)
from scripts.lm_midi_tokens import phrase_event_tokens  # noqa: E402
from scripts.prepare_core_s1_swift import convert_sample  # noqa: E402


MAX_LENGTH = 1536
TASK_TYPES = ["coldstart", "main"]

TASK_CONFIG = {
    "abcx2pm": {
        "dir_name": "abcx2pm_sft",
        "fields": ["instruction", "score_header", "score_snip", "perf_context", "perf_target"],
        "readme_name": "abcx2pm_sft",
        "approx_char_budget": 6500,
    },
    "sm2pm": {
        "dir_name": "sm2pm_sft",
        "fields": ["instruction", "score_midi_snip", "perf_context", "perf_target"],
        "readme_name": "sm2pm_sft",
        "approx_char_budget": 7800,
    },
}

_WORKER_ROOT: Path | None = None
_WORKER_TEMP_ROOT: Path | None = None
_WORKER_TOKENIZER = None


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            if unit in {"MB", "GB"}:
                return f"{value:.2f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def sorted_measure_ids(mapping: dict[str, object]) -> list[str]:
    return sorted(mapping.keys(), key=lambda x: int(x[1:]))


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def resolve_tokenizer_path(tokenizer_path: Path) -> str:
    if tokenizer_path.exists():
        return str(tokenizer_path)
    rooted = ROOT / tokenizer_path
    if rooted.exists():
        return str(rooted)
    return str(tokenizer_path)


def text_from_record(record: dict, fields: list[str]) -> str:
    return " ".join(str(record.get(field, "")) for field in fields)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def token_length(tokenizer, text: str) -> int:
    return token_lengths(tokenizer, [text])[0]


def render_messages(tokenizer, messages: list[dict]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
    except Exception:
        return "\n".join(str(message.get("content", "")) for message in messages)


def training_text(record: dict, tokenizer) -> str:
    return render_messages(tokenizer, convert_sample(record)["messages"])


def training_token_length(record: dict, tokenizer) -> int:
    return token_length(tokenizer, training_text(record, tokenizer))


def score_phrase_maps(score_data: dict) -> tuple[dict[str, str], dict[str, int]]:
    measure_to_phrase: dict[str, str] = {}
    local_index: dict[str, int] = {}
    for phrase_id, measure_ids in score_data["phrases"].items():
        for idx, measure_id in enumerate(measure_ids):
            measure_to_phrase[measure_id] = phrase_id
            local_index[measure_id] = idx
    return measure_to_phrase, local_index


def tsv_phrase_maps(tsv_data: dict) -> tuple[dict[str, str], dict[str, int]]:
    measure_to_phrase: dict[str, str] = {}
    local_index: dict[str, int] = {}
    for phrase_id, measure_ids in tsv_data["phrases"].items():
        for idx, measure_id in enumerate(measure_ids):
            measure_to_phrase[measure_id] = phrase_id
            local_index[measure_id] = idx
    return measure_to_phrase, local_index


def maybe_phrase_header_for_score(
    measure_id: str,
    global_index: int,
    measure_ids: list[str],
    measure_to_phrase: dict[str, str],
    phrase_display_ids: dict[str, str],
) -> str:
    phrase_id = measure_to_phrase.get(measure_id)
    if not phrase_id:
        return ""
    if global_index == 0:
        return phrase_display_ids.get(phrase_id, phrase_id)
    prev_phrase = measure_to_phrase.get(measure_ids[global_index - 1])
    if prev_phrase != phrase_id:
        return phrase_display_ids.get(phrase_id, phrase_id)
    return ""


def maybe_phrase_header_for_tsv(
    measure_id: str,
    global_index: int,
    measure_ids: list[str],
    measure_to_phrase: dict[str, str],
    phrase_durations: dict[str, int],
) -> str:
    phrase_id = measure_to_phrase.get(measure_id)
    if not phrase_id:
        return ""
    should_emit = global_index == 0
    if not should_emit and global_index > 0:
        prev_phrase = measure_to_phrase.get(measure_ids[global_index - 1])
        should_emit = prev_phrase != phrase_id
    if not should_emit:
        return ""
    duration = phrase_durations.get(phrase_id, 0)
    return phrase_event_tokens(int(phrase_id[1:]) - 1, duration)


def serialize_abcx_prev_measure(score_data: dict, measure_id: str) -> str:
    return format_score_measure(
        measure_id,
        score_data["measures"][measure_id],
        score_data["measure_display_ids"].get(measure_id),
    )


def serialize_abcx_span(
    score_data: dict,
    measure_ids: list[str],
    start_idx: int,
    end_idx: int,
    measure_to_phrase: dict[str, str],
) -> str:
    lines: list[str] = []
    for global_index in range(start_idx, end_idx + 1):
        measure_id = measure_ids[global_index]
        phrase_header = maybe_phrase_header_for_score(
            measure_id,
            global_index,
            measure_ids,
            measure_to_phrase,
            score_data["phrase_display_ids"],
        )
        if phrase_header:
            lines.append(phrase_header)
        lines.append(
            format_score_measure(
                measure_id,
                score_data["measures"][measure_id],
                score_data["measure_display_ids"].get(measure_id),
            )
        )
    return "\n".join(lines)


def serialize_tsv_measure(tsv_data: dict, measure_id: str, local_index: dict[str, int]) -> str:
    return format_perf_measure_with_index(
        local_index[measure_id],
        tsv_data["measure_durations"][measure_id],
        tsv_data["measures"][measure_id],
    )


def serialize_tsv_span(
    tsv_data: dict,
    measure_ids: list[str],
    start_idx: int,
    end_idx: int,
    measure_to_phrase: dict[str, str],
    local_index: dict[str, int],
) -> str:
    parts: list[str] = []
    for global_index in range(start_idx, end_idx + 1):
        measure_id = measure_ids[global_index]
        phrase_header = maybe_phrase_header_for_tsv(
            measure_id,
            global_index,
            measure_ids,
            measure_to_phrase,
            tsv_data["phrase_durations"],
        )
        if phrase_header:
            parts.append(phrase_header)
        parts.append(serialize_tsv_measure(tsv_data, measure_id, local_index))
    return "".join(parts)


def common_measure_ids(*sources: tuple[list[str], set[str]]) -> list[str]:
    order, first_set = sources[0]
    valid = set(first_set)
    for _, values in sources[1:]:
        valid &= set(values)
    return [measure_id for measure_id in order if measure_id in valid]


def build_abcx_record(
    row: dict,
    score_data: dict,
    perf_data: dict,
    measure_ids: list[str],
    score_measure_to_phrase: dict[str, str],
    perf_local_index: dict[str, int],
    perf_measure_to_phrase: dict[str, str],
    start_idx: int,
    end_idx: int,
) -> dict:
    start_measure_id = measure_ids[start_idx]
    end_measure_id = measure_ids[end_idx]
    task_type = "coldstart" if start_idx == 0 else "main"
    prev_measure = serialize_abcx_prev_measure(score_data, measure_ids[start_idx - 1]) if start_idx > 0 else ""
    current_span = serialize_abcx_span(score_data, measure_ids, start_idx, end_idx, score_measure_to_phrase)
    score_snip = "\n".join(part for part in [prev_measure, current_span] if part)
    perf_context = serialize_tsv_measure(perf_data, measure_ids[start_idx - 1], perf_local_index) if start_idx > 0 else ""
    perf_target = serialize_tsv_span(
        perf_data,
        measure_ids,
        start_idx,
        end_idx,
        perf_measure_to_phrase,
        perf_local_index,
    )
    return {
        "task": "abcx2pm",
        "variant": "abcx2pm",
        "task_type": task_type,
        "instruction": (
            "Render the provided abcx score into expressive performance midi. Output only the target span."
            if task_type == "coldstart"
            else "Using the provided first performance measure as a style reference, render the rest of the abcx score into expressive performance midi. Output only the target span."
        ),
        "score_header": score_data["header"],
        "score_snip": score_snip,
        "perf_context": perf_context,
        "perf_target": perf_target,
        "target_start_measure_id": start_measure_id,
        "target_end_measure_id": end_measure_id,
        "target_measure_count": end_idx - start_idx + 1,
        "crosses_phrase_boundary": score_measure_to_phrase.get(start_measure_id) != score_measure_to_phrase.get(end_measure_id),
        "piece_id": performance_piece_id(row["performance_tsv_path"]),
        "split": row.get("split", "train"),
    }


def build_sm2pm_record(
    row: dict,
    score_midi_data: dict,
    perf_data: dict,
    measure_ids: list[str],
    score_midi_measure_to_phrase: dict[str, str],
    score_midi_local_index: dict[str, int],
    perf_local_index: dict[str, int],
    perf_measure_to_phrase: dict[str, str],
    start_idx: int,
    end_idx: int,
) -> dict:
    start_measure_id = measure_ids[start_idx]
    end_measure_id = measure_ids[end_idx]
    task_type = "coldstart" if start_idx == 0 else "main"
    prev_measure = serialize_tsv_measure(score_midi_data, measure_ids[start_idx - 1], score_midi_local_index) if start_idx > 0 else ""
    current_span = serialize_tsv_span(
        score_midi_data,
        measure_ids,
        start_idx,
        end_idx,
        score_midi_measure_to_phrase,
        score_midi_local_index,
    )
    score_midi_snip = "".join(part for part in [prev_measure, current_span] if part)
    perf_context = serialize_tsv_measure(perf_data, measure_ids[start_idx - 1], perf_local_index) if start_idx > 0 else ""
    perf_target = serialize_tsv_span(
        perf_data,
        measure_ids,
        start_idx,
        end_idx,
        perf_measure_to_phrase,
        perf_local_index,
    )
    return {
        "task": "sm2pm",
        "variant": "sm2pm",
        "task_type": task_type,
        "instruction": (
            "Render the provided score midi into expressive performance midi. Output only the target span."
            if task_type == "coldstart"
            else "Using the provided first performance measure as a style reference, render the rest of the score midi into expressive performance midi. Output only the target span."
        ),
        "score_midi_snip": score_midi_snip,
        "perf_context": perf_context,
        "perf_target": perf_target,
        "target_start_measure_id": start_measure_id,
        "target_end_measure_id": end_measure_id,
        "target_measure_count": end_idx - start_idx + 1,
        "crosses_phrase_boundary": score_midi_measure_to_phrase.get(start_measure_id) != score_midi_measure_to_phrase.get(end_measure_id),
        "piece_id": performance_piece_id(row["performance_tsv_path"]),
        "split": row.get("split", "train"),
    }


def build_variant_record(
    variant: str,
    row: dict,
    score_data: dict | None,
    score_midi_data: dict | None,
    perf_data: dict,
    measure_ids: list[str],
    score_measure_to_phrase: dict[str, str] | None,
    score_midi_measure_to_phrase: dict[str, str] | None,
    score_midi_local_index: dict[str, int] | None,
    perf_measure_to_phrase: dict[str, str],
    perf_local_index: dict[str, int],
    start_idx: int,
    end_idx: int,
) -> dict:
    if variant == "abcx2pm":
        return build_abcx_record(
            row,
            score_data,
            perf_data,
            measure_ids,
            score_measure_to_phrase,
            perf_local_index,
            perf_measure_to_phrase,
            start_idx,
            end_idx,
        )
    return build_sm2pm_record(
        row,
        score_midi_data,
        perf_data,
        measure_ids,
        score_midi_measure_to_phrase,
        score_midi_local_index,
        perf_local_index,
        perf_measure_to_phrase,
        start_idx,
        end_idx,
    )


def choose_span_end(
    variant: str,
    row: dict,
    score_data: dict | None,
    score_midi_data: dict | None,
    perf_data: dict,
    measure_ids: list[str],
    score_measure_to_phrase: dict[str, str] | None,
    score_midi_measure_to_phrase: dict[str, str] | None,
    score_midi_local_index: dict[str, int] | None,
    perf_measure_to_phrase: dict[str, str],
    perf_local_index: dict[str, int],
    start_idx: int,
) -> tuple[int, dict | None]:
    if _WORKER_TOKENIZER is None:
        raise RuntimeError("Worker tokenizer is not initialized")

    approx_budget = TASK_CONFIG[variant]["approx_char_budget"]
    fields = TASK_CONFIG[variant]["fields"]
    chosen_record = None
    chosen_end = start_idx
    overshot = False

    for end_idx in range(start_idx, len(measure_ids)):
        record = build_variant_record(
            variant,
            row,
            score_data,
            score_midi_data,
            perf_data,
            measure_ids,
            score_measure_to_phrase,
            score_midi_measure_to_phrase,
            score_midi_local_index,
            perf_measure_to_phrase,
            perf_local_index,
            start_idx,
            end_idx,
        )
        chosen_record = record
        chosen_end = end_idx
        if len(text_from_record(record, fields)) > approx_budget and end_idx > start_idx:
            chosen_end = end_idx - 1
            overshot = True
            break

    if chosen_record is None:
        raise ValueError(f"Failed to build any candidate for {variant}")

    if overshot:
        chosen_record = build_variant_record(
            variant,
            row,
            score_data,
            score_midi_data,
            perf_data,
            measure_ids,
            score_measure_to_phrase,
            score_midi_measure_to_phrase,
            score_midi_local_index,
            perf_measure_to_phrase,
            perf_local_index,
            start_idx,
            chosen_end,
        )

    current_length = training_token_length(chosen_record, _WORKER_TOKENIZER)
    while chosen_end > start_idx:
        if current_length <= MAX_LENGTH:
            break
        chosen_end -= 1
        chosen_record = build_variant_record(
            variant,
            row,
            score_data,
            score_midi_data,
            perf_data,
            measure_ids,
            score_measure_to_phrase,
            score_midi_measure_to_phrase,
            score_midi_local_index,
            perf_measure_to_phrase,
            perf_local_index,
            start_idx,
            chosen_end,
        )
        current_length = training_token_length(chosen_record, _WORKER_TOKENIZER)

    if current_length > MAX_LENGTH:
        return start_idx, None

    while chosen_end + 1 < len(measure_ids):
        next_record = build_variant_record(
            variant,
            row,
            score_data,
            score_midi_data,
            perf_data,
            measure_ids,
            score_measure_to_phrase,
            score_midi_measure_to_phrase,
            score_midi_local_index,
            perf_measure_to_phrase,
            perf_local_index,
            start_idx,
            chosen_end + 1,
        )
        next_length = training_token_length(next_record, _WORKER_TOKENIZER)
        if next_length > MAX_LENGTH:
            break
        chosen_end += 1
        chosen_record = next_record
    return chosen_end, chosen_record


def generate_variant_samples(
    variant: str,
    row: dict,
    score_data: dict | None,
    score_midi_data: dict | None,
    perf_data: dict,
) -> list[dict]:
    perf_measure_order = sorted_measure_ids(perf_data["measures"])
    perf_measure_to_phrase, perf_local_index = tsv_phrase_maps(perf_data)
    perf_valid = {
        measure_id
        for measure_id in perf_measure_order
        if measure_id in perf_data["measure_durations"] and measure_id in perf_local_index
    }

    if variant == "abcx2pm":
        score_measure_order = sorted_measure_ids(score_data["measures"])
        score_measure_to_phrase, _ = score_phrase_maps(score_data)
        measure_ids = common_measure_ids(
            (score_measure_order, set(score_measure_order)),
            (perf_measure_order, perf_valid),
        )
        if not measure_ids:
            return []
        cursor = 0
        records: list[dict] = []
        while cursor < len(measure_ids):
            end_idx, record = choose_span_end(
                variant,
                row,
                score_data,
                score_midi_data,
                perf_data,
                measure_ids,
                score_measure_to_phrase,
                None,
                None,
                perf_measure_to_phrase,
                perf_local_index,
                cursor,
            )
            if record is not None:
                records.append(record)
            cursor = end_idx + 1
        return records

    score_midi_measure_order = sorted_measure_ids(score_midi_data["measures"])
    score_midi_measure_to_phrase, score_midi_local_index = tsv_phrase_maps(score_midi_data)
    score_midi_valid = {
        measure_id
        for measure_id in score_midi_measure_order
        if measure_id in score_midi_data["measure_durations"] and measure_id in score_midi_local_index
    }
    measure_ids = common_measure_ids(
        (score_midi_measure_order, score_midi_valid),
        (perf_measure_order, perf_valid),
    )
    if not measure_ids:
        return []

    cursor = 0
    records = []
    while cursor < len(measure_ids):
        end_idx, record = choose_span_end(
            variant,
            row,
            score_data,
            score_midi_data,
            perf_data,
            measure_ids,
            None,
            score_midi_measure_to_phrase,
            score_midi_local_index,
            perf_measure_to_phrase,
            perf_local_index,
            cursor,
        )
        if record is not None:
            records.append(record)
        cursor = end_idx + 1
    return records


def _worker_init(root: str, temp_root: str, tokenizer_path: str) -> None:
    global _WORKER_ROOT, _WORKER_TEMP_ROOT, _WORKER_TOKENIZER
    _WORKER_ROOT = Path(root)
    _WORKER_TEMP_ROOT = Path(temp_root)
    _WORKER_TOKENIZER = AutoTokenizer.from_pretrained(
        resolve_tokenizer_path(Path(tokenizer_path)),
        trust_remote_code=True,
        local_files_only=True,
    )


def _worker_process_group(task: tuple[int, str, str, list[dict]]) -> dict:
    group_index, score_abcx_path, score_midi_tsv_path, rows = task
    assert _WORKER_ROOT is not None
    assert _WORKER_TEMP_ROOT is not None

    score_abcx_file = _WORKER_ROOT / str(score_abcx_path)
    score_midi_tsv_file = _WORKER_ROOT / str(score_midi_tsv_path)
    if not score_abcx_file.exists() or not score_midi_tsv_file.exists():
        return {"group_index": group_index, "counts": {}, "files": {}}

    try:
        score_data = AlignedABCXParser.parse_aligned_abcx(str(score_abcx_file))
        score_midi_data = TSVParser.parse_tsv(str(score_midi_tsv_file))
    except Exception:
        return {"group_index": group_index, "counts": {}, "files": {}}

    lines_by_key: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    counts: dict[str, dict[str, dict[str, int]]] = {
        variant: {task_type: defaultdict(int) for task_type in TASK_TYPES}
        for variant in TASK_CONFIG
    }

    for row in rows:
        perf_file = _WORKER_ROOT / str(row["performance_tsv_path"])
        if not perf_file.exists():
            continue
        try:
            perf_data = TSVParser.parse_tsv(str(perf_file))
        except Exception:
            continue

        abcx_records = generate_variant_samples("abcx2pm", row, score_data, None, perf_data)
        sm_records = generate_variant_samples("sm2pm", row, None, score_midi_data, perf_data)

        for variant, records in [("abcx2pm", abcx_records), ("sm2pm", sm_records)]:
            for record in records:
                split = record.get("split", "train")
                task_type = record.get("task_type", "main")
                key = (variant, task_type, split)
                lines_by_key[key].append(json.dumps(record, ensure_ascii=False) + "\n")
                counts[variant][task_type][split] += 1

    file_map: dict[str, str] = {}
    for (variant, task_type, split), lines in lines_by_key.items():
        temp_path = _WORKER_TEMP_ROOT / f"group_{group_index:05d}_{variant}_{task_type}_{split}.jsonl"
        temp_path.write_text("".join(lines), encoding="utf-8")
        file_map[f"{variant}|{task_type}|{split}"] = str(temp_path)

    serializable_counts = {
        variant: {
            task_type: dict(split_counts)
            for task_type, split_counts in task_counts.items()
        }
        for variant, task_counts in counts.items()
    }
    return {
        "group_index": group_index,
        "counts": serializable_counts,
        "files": file_map,
    }


def summarize_dataset(tokenizer, dataset_dir: Path, variant: str, batch_size: int) -> dict:
    files = sorted(dataset_dir.glob("*.jsonl"))
    lengths_by_split: dict[str, list[int]] = defaultdict(list)
    lengths_by_task_type: dict[str, list[int]] = defaultdict(list)
    all_lengths: list[int] = []
    sample_count = 0
    char_count = 0
    total_bytes = sum(path.stat().st_size for path in files)

    for path in files:
        parts = path.stem.rsplit("_", 2)
        if len(parts) != 3:
            continue
        task_type = parts[1]
        split = parts[2]
        with path.open("r", encoding="utf-8") as handle:
            batch_records: list[dict] = []
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                batch_records.append(record)
                sample_count += 1
                if len(batch_records) >= batch_size:
                    batch_texts = [training_text(record, tokenizer) for record in batch_records]
                    char_count += sum(len(text) for text in batch_texts)
                    batch_lengths = token_lengths(tokenizer, batch_texts)
                    lengths_by_split[split].extend(batch_lengths)
                    lengths_by_task_type[task_type].extend(batch_lengths)
                    all_lengths.extend(batch_lengths)
                    batch_records = []
            if batch_records:
                batch_texts = [training_text(record, tokenizer) for record in batch_records]
                char_count += sum(len(text) for text in batch_texts)
                batch_lengths = token_lengths(tokenizer, batch_texts)
                lengths_by_split[split].extend(batch_lengths)
                lengths_by_task_type[task_type].extend(batch_lengths)
                all_lengths.extend(batch_lengths)

    arr = np.array(all_lengths, dtype=np.int64) if all_lengths else np.array([], dtype=np.int64)
    overall = {
        "count": int(arr.size),
        "mean": float(arr.mean()) if arr.size else 0.0,
        "p50": float(np.percentile(arr, 50)) if arr.size else 0.0,
        "p90": float(np.percentile(arr, 90)) if arr.size else 0.0,
        "p95": float(np.percentile(arr, 95)) if arr.size else 0.0,
        "p99": float(np.percentile(arr, 99)) if arr.size else 0.0,
        "max": int(arr.max()) if arr.size else 0,
    }
    by_split = {}
    for split, lengths in lengths_by_split.items():
        split_arr = np.array(lengths, dtype=np.int64)
        by_split[split] = {
            "count": int(split_arr.size),
            "mean": float(split_arr.mean()) if split_arr.size else 0.0,
        }
    by_task_type = {}
    for task_type, lengths in lengths_by_task_type.items():
        tt_arr = np.array(lengths, dtype=np.int64)
        by_task_type[task_type] = {
            "count": int(tt_arr.size),
            "mean": float(tt_arr.mean()) if tt_arr.size else 0.0,
            "p95": float(np.percentile(tt_arr, 95)) if tt_arr.size else 0.0,
            "max": int(tt_arr.max()) if tt_arr.size else 0,
        }

    return {
        "samples": sample_count,
        "bytes": total_bytes,
        "size": human_size(total_bytes),
        "avg_tokens": overall["mean"],
        "avg_chars": (char_count / sample_count) if sample_count else 0.0,
        "overall": overall,
        "by_split": by_split,
        "by_task_type": by_task_type,
        "max_length": overall["max"],
        "p95_coverage_ratio": (overall["p95"] / MAX_LENGTH) if MAX_LENGTH else 0.0,
    }


def build_readme_stats_row(name: str, summary: dict) -> str:
    p95 = round(summary["overall"]["p95"])
    pct = summary["p95_coverage_ratio"] * 100
    return (
        f"| **{name}** | {summary['samples']:,} | {summary['size']} | "
        f"{summary['avg_tokens']:.0f} | {summary['avg_chars']:.0f} | {summary['max_length']} | "
        f"{p95:,} ({pct:.1f}%) |"
    )


def update_corpora_readme(readme_path: Path, summaries: dict[str, dict]) -> None:
    text = readme_path.read_text(encoding="utf-8")
    marker = "### 完整数据集统计\n\n| Dataset | Samples | Size | Avg Tokens | Avg Chars | Max Length | P95 Coverage |\n|---------|---------|------|------------|-----------|------------|--------------|\n"
    if marker not in text:
        raise ValueError(f"Cannot locate summary table marker in {readme_path}")

    old_rows = [
        "| **measure_epr_sft_full** | 5,839,547 | 8.70 GB | 362 | 1,277 | 768 | 633 (82.4%) |",
        "| **phrase_epr_sft_full** | 1,442,852 | 4.38 GB | 749 | 2,933 | 1536 | 1,331 (86.7%) |",
        "| **measure_epr_sft** (sampled) | 46,576 | 69.0 MB | 349 | 1,252 | 768 | 616 (80.2%) |",
        "| **phrase_epr_sft** (sampled) | 11,517 | 34.9 MB | 718 | 2,867 | 1536 | 1,295 (84.3%) |",
    ]
    insert = "\n".join(
        [
            build_readme_stats_row(TASK_CONFIG["abcx2pm"]["readme_name"], summaries["abcx2pm"]),
            build_readme_stats_row(TASK_CONFIG["sm2pm"]["readme_name"], summaries["sm2pm"]),
        ]
    )
    replacement = marker + insert + "\n" + "\n".join(old_rows) + "\n"

    start = text.index(marker)
    end = start + len(marker)
    for row in old_rows:
        row_with_nl = row + "\n"
        idx = text.find(row_with_nl, end)
        if idx == -1:
            raise ValueError(f"Cannot locate expected README row: {row}")
        end = idx + len(row_with_nl)

    text = text[:start] + replacement + text[end:]

    file_marker = "├── training_config.yaml                   # 训练配置（max_length 等）\n"
    if file_marker in text and "abcx2pm_sft/" not in text:
        insert_block = (
            "├── abcx2pm_sft/                          # 完整数据集（动态 span, max_length=1536）\n"
            "│   ├── abcx2pm_coldstart_train.jsonl\n"
            "│   ├── abcx2pm_coldstart_val.jsonl\n"
            "│   ├── abcx2pm_coldstart_test.jsonl\n"
            "│   ├── abcx2pm_main_train.jsonl\n"
            "│   ├── abcx2pm_main_val.jsonl\n"
            "│   └── abcx2pm_main_test.jsonl\n"
            "│\n"
            "├── sm2pm_sft/                            # 完整数据集（动态 span, max_length=1536）\n"
            "│   ├── sm2pm_coldstart_train.jsonl\n"
            "│   ├── sm2pm_coldstart_val.jsonl\n"
            "│   ├── sm2pm_coldstart_test.jsonl\n"
            "│   ├── sm2pm_main_train.jsonl\n"
            "│   ├── sm2pm_main_val.jsonl\n"
            "│   └── sm2pm_main_test.jsonl\n"
            "│\n"
        )
        text = text.replace(file_marker, file_marker + insert_block, 1)

    readme_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=ROOT / "PianoCoReS" / "metadata.csv")
    parser.add_argument("--corpora-root", type=Path, default=ROOT / "PianoCoReS" / "Corpora")
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "Qwen3.5-4B-LM-MIDI-Resized")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 1) // 2))
    args = parser.parse_args()

    print(f"Reading metadata from {args.metadata}...")
    df = pd.read_csv(args.metadata, low_memory=False)
    required = ["score_abcx_path", "score_midi_tsv_path", "performance_tsv_path", "split"]
    for column in required:
        if column not in df.columns:
            raise ValueError(f"Missing required metadata column: {column}")

    df = df[
        df["score_abcx_path"].notna()
        & df["score_midi_tsv_path"].notna()
        & df["performance_tsv_path"].notna()
    ].copy()
    print(f"Usable paired rows: {len(df):,}")

    out_dirs = {
        variant: args.corpora_root / config["dir_name"]
        for variant, config in TASK_CONFIG.items()
    }
    for path in out_dirs.values():
        clean_dir(path)

    temp_root = args.corpora_root / ".tmp_span_epr"
    clean_dir(temp_root)

    handles = {}
    counts: dict[str, dict[str, dict[str, int]]] = {
        variant: {task_type: defaultdict(int) for task_type in TASK_TYPES}
        for variant in TASK_CONFIG
    }
    try:
        for variant, out_dir in out_dirs.items():
            for task_type in TASK_TYPES:
                for split in ["train", "val", "test"]:
                    key = (variant, task_type, split)
                    handles[key] = (out_dir / f"{variant}_{task_type}_{split}.jsonl").open("w", encoding="utf-8")

        grouped = list(df.groupby(["score_abcx_path", "score_midi_tsv_path"], sort=False))
        tasks = [
            (idx, score_abcx_path, score_midi_tsv_path, group.to_dict("records"))
            for idx, ((score_abcx_path, score_midi_tsv_path), group) in enumerate(grouped)
        ]

        start = time.time()
        with mp.Pool(
            processes=args.jobs,
            initializer=_worker_init,
            initargs=(str(ROOT), str(temp_root), str(args.tokenizer)),
        ) as pool:
            for result in tqdm(
                pool.imap_unordered(_worker_process_group, tasks, chunksize=1),
                total=len(tasks),
                desc="Building span corpora",
            ):
                for key, path_str in result["files"].items():
                    variant, task_type, split = key.split("|")
                    path = Path(path_str)
                    with path.open("r", encoding="utf-8") as fin:
                        shutil.copyfileobj(fin, handles[(variant, task_type, split)])
                    path.unlink()
                for variant, task_counts in result["counts"].items():
                    for task_type, split_counts in task_counts.items():
                        for split, value in split_counts.items():
                            counts[variant][task_type][split] += value

        print(f"Generation finished in {time.time() - start:.1f}s")
    finally:
        for handle in handles.values():
            handle.close()
        if temp_root.exists():
            shutil.rmtree(temp_root)

    print("Summarizing datasets...")
    tokenizer = AutoTokenizer.from_pretrained(
        resolve_tokenizer_path(args.tokenizer),
        trust_remote_code=True,
        local_files_only=True,
    )
    summaries = {}
    for variant, out_dir in out_dirs.items():
        summaries[variant] = summarize_dataset(tokenizer, out_dir, variant, args.batch_size)
        summaries[variant]["split_counts"] = {
            task_type: dict(split_counts)
            for task_type, split_counts in counts[variant].items()
        }

    summary_path = args.corpora_root / "span_epr_sft_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "metadata": str(args.metadata),
                "tokenizer": str(args.tokenizer),
                "max_length": MAX_LENGTH,
                "tasks": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {summary_path}")

    update_corpora_readme(args.corpora_root / "README.md", summaries)
    print(f"Updated {args.corpora_root / 'README.md'}")

    for variant, summary in summaries.items():
        print(
            f"{variant}: samples={summary['samples']:,}, size={summary['size']}, "
            f"avg_tokens={summary['avg_tokens']:.1f}, p95={summary['overall']['p95']:.0f}, max={summary['overall']['max']}"
        )


if __name__ == "__main__":
    main()
