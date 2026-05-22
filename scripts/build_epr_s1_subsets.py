#!/usr/bin/env python3
"""Build EPR S1 subsets with deterministic per-performance downsampling.

Policy:
1. Keep all `coldstart` and `ending` samples.
2. Keep all ASAP `main` samples.
3. For non-ASAP `main` samples, sample within each performance (`piece_id`):
   - phrase_epr: keep about 50%
   - measure_epr: keep about 30%

Outputs:
  - PianoCoReS/Corpora/measure_epr_s1.jsonl
  - PianoCoReS/Corpora/phrase_epr_s1.jsonl
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from array import array
from collections import Counter, defaultdict
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tokens import add_lm_midi_tokens


BATCH_SIZE = 512
TASK_CONFIGS = {
    "measure_epr": {
        "ratio": 0.30,
        "max_length": 768,
        "input_dir": Path("PianoCoReS/Corpora/measure_epr_sft"),
        "output_path": Path("PianoCoReS/Corpora/epr_sft/measure_epr_s1.jsonl"),
        "target_field": "target_measure_id",
        "count_fields": ["instruction", "score_header", "score_snip", "perf_context", "perf_target"],
    },
    "phrase_epr": {
        "ratio": 0.50,
        "max_length": 1536,
        "input_dir": Path("PianoCoReS/Corpora/phrase_epr_sft"),
        "output_path": Path("PianoCoReS/Corpora/epr_sft/phrase_epr_s1.jsonl"),
        "target_field": "target_phrase_id",
        "count_fields": ["instruction", "score_header", "score_snip", "perf_context", "perf_target"],
    },
    "abcx2pm": {
        "ratio": 0.50,
        "max_length": 1536,
        "input_dir": Path("PianoCoReS/Corpora/abcx2pm_sft"),
        "output_path": Path("PianoCoReS/Corpora/epr_sft/abcx2pm_s1.jsonl"),
        "target_field": "target_start_measure_id",
        "count_fields": ["instruction", "score_header", "score_snip", "perf_context", "perf_target"],
    },
    "sm2pm": {
        "ratio": 0.50,
        "max_length": 1536,
        "input_dir": Path("PianoCoReS/Corpora/sm2pm_sft"),
        "output_path": Path("PianoCoReS/Corpora/epr_sft/sm2pm_s1.jsonl"),
        "target_field": "target_start_measure_id",
        "count_fields": ["instruction", "score_midi_snip", "perf_context", "perf_target"],
    },
}


def performance_piece_id(perf_tsv_path: str) -> str:
    path = str(perf_tsv_path)
    prefixes = [
        "PianoCoReS/miditsv/",
        "PianoCoReS/aligned/",
        "PianoCoRe_output/",
        "PianoCoRe/aligned/",
    ]
    for prefix in prefixes:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    if path.endswith(".tsv"):
        path = path[:-4]
    return path


def load_asap_piece_ids(metadata_path: Path) -> set[str]:
    asap_ids: set[str] = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            piece_id = performance_piece_id(row.get("performance_tsv_path", ""))
            if not piece_id:
                continue
            if row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False":
                asap_ids.add(piece_id)
    return asap_ids


def is_asap_piece(piece_id: str, asap_ids: set[str]) -> bool:
    return piece_id in asap_ids or piece_id.startswith("ASAP_")


def record_text(record: dict, count_fields: list[str]) -> str:
    return " ".join(str(record.get(field, "")) for field in count_fields)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def stable_hash64(*parts: str) -> int:
    text = "||".join(str(part) for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def target_key(record: dict, target_field: str) -> str:
    return str(
        record.get(target_field)
        or record.get("instruction")
        or record.get("score_snip")
        or record.get("piece_id")
    )


def rewrite_instruction(task: str, record: dict) -> None:
    task_type = record.get("task_type", "")
    if task == "abcx2pm":
        if task_type == "coldstart":
            record["instruction"] = (
                "Render the provided abcx score into expressive performance midi. "
                "Output only the target span."
            )
        else:
            record["instruction"] = (
                "Using the provided first performance measure as a style reference, "
                "render the rest of the abcx score into expressive performance midi. "
                "Output only the target span."
            )
    elif task == "sm2pm":
        if task_type == "coldstart":
            record["instruction"] = (
                "Render the provided score midi into expressive performance midi. "
                "Output only the target span."
            )
        else:
            record["instruction"] = (
                "Using the provided first performance measure as a style reference, "
                "render the rest of the score midi into expressive performance midi. "
                "Output only the target span."
            )


def human_size(num_bytes: int) -> str:
    gib = num_bytes / (1024 ** 3)
    mib = num_bytes / (1024 ** 2)
    if gib >= 1:
        return f"{gib:.2f} GB"
    return f"{mib:.1f} MB"


def file_order_key(path: Path) -> tuple[int, int, str]:
    task_type_rank = {"coldstart": 0, "main": 1, "ending": 2}
    split_rank = {"train": 0, "val": 1, "test": 2}
    stem_parts = path.stem.split("_")
    task_type = stem_parts[-2] if len(stem_parts) >= 2 else ""
    split = stem_parts[-1] if len(stem_parts) >= 1 else ""
    return (task_type_rank.get(task_type, 9), split_rank.get(split, 9), path.name)


def compute_piece_thresholds(
    input_dir: Path,
    target_field: str,
    ratio: float,
    asap_ids: set[str],
) -> tuple[dict[str, int], Counter]:
    piece_hashes: dict[str, array] = defaultdict(lambda: array("Q"))
    counts = Counter()

    for path in sorted(input_dir.glob("*.jsonl"), key=file_order_key):
        print(f"[scan] {path.name}")
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                task_type = record.get("task_type", "")
                piece_id = str(record.get("piece_id", ""))
                if task_type != "main" or is_asap_piece(piece_id, asap_ids):
                    continue

                token = stable_hash64(piece_id, target_key(record, target_field))
                piece_hashes[piece_id].append(token)
                counts["non_asap_main_seen"] += 1

    thresholds: dict[str, int] = {}
    for piece_id, hashes in piece_hashes.items():
        hashes = array("Q", sorted(hashes))
        keep_count = max(1, min(len(hashes), int(math.floor(len(hashes) * ratio + 0.5))))
        thresholds[piece_id] = hashes[keep_count - 1]
        counts["non_asap_main_pieces"] += 1
        counts["non_asap_main_target"] += keep_count

    return thresholds, counts


def write_subset_and_collect_stats(
    tokenizer,
    task: str,
    input_dir: Path,
    output_path: Path,
    target_field: str,
    count_fields: list[str],
    max_length: int,
    asap_ids: set[str],
    thresholds: dict[str, int],
) -> tuple[dict, Counter]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lengths = array("I")
    counters = Counter()
    total_chars = 0
    batch_texts: list[str] = []

    def flush_lengths() -> None:
        nonlocal batch_texts
        if not batch_texts:
            return
        batch_lengths = token_lengths(tokenizer, batch_texts)
        lengths.extend(batch_lengths)
        batch_texts = []

    with output_path.open("w", encoding="utf-8") as fout:
        for path in sorted(input_dir.glob("*.jsonl"), key=file_order_key):
            print(f"[write] {path.name}")
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    task_type = record.get("task_type", "")
                    piece_id = str(record.get("piece_id", ""))
                    keep = True

                    if task_type == "main":
                        if is_asap_piece(piece_id, asap_ids):
                            counters["main_asap_kept"] += 1
                        else:
                            token = stable_hash64(piece_id, target_key(record, target_field))
                            threshold = thresholds.get(piece_id)
                            keep = threshold is not None and token <= threshold
                            if keep:
                                counters["main_non_asap_kept"] += 1
                            else:
                                counters["main_non_asap_dropped"] += 1
                    elif task_type == "coldstart":
                        counters["coldstart_kept"] += 1
                    elif task_type == "ending":
                        counters["ending_kept"] += 1

                    if not keep:
                        continue

                    rewrite_instruction(task, record)
                    serialized = json.dumps(record, ensure_ascii=False)
                    fout.write(serialized + "\n")
                    counters["samples"] += 1

                    text = record_text(record, count_fields)
                    total_chars += len(text)
                    batch_texts.append(text)
                    if len(batch_texts) >= BATCH_SIZE:
                        flush_lengths()

    flush_lengths()

    sorted_lengths = sorted(lengths)
    count = len(sorted_lengths)
    p95_index = max(0, math.ceil(count * 0.95) - 1) if count else 0
    p95 = sorted_lengths[p95_index] if count else 0
    avg_tokens = sum(sorted_lengths) / count if count else 0.0
    avg_chars = total_chars / count if count else 0.0
    file_size = output_path.stat().st_size if output_path.exists() else 0

    stats = {
        "samples": count,
        "size_bytes": file_size,
        "size_human": human_size(file_size),
        "avg_tokens": avg_tokens,
        "avg_chars": avg_chars,
        "max_length": max_length,
        "p95_tokens": p95,
        "p95_ratio": (p95 / max_length * 100.0) if max_length else 0.0,
        "token_total": int(sum(sorted_lengths)),
    }
    return stats, counters


def build_subset(
    tokenizer,
    task: str,
    input_dir: Path,
    output_path: Path,
    target_field: str,
    count_fields: list[str],
    ratio: float,
    max_length: int,
    asap_ids: set[str],
) -> tuple[dict, Counter]:
    print(f"\n=== Building {task} S1 ===")
    print(f"input:  {input_dir}")
    print(f"output: {output_path}")
    print(f"non-ASAP main keep ratio: {ratio:.0%}")

    thresholds, scan_counts = compute_piece_thresholds(
        input_dir=input_dir,
        target_field=target_field,
        ratio=ratio,
        asap_ids=asap_ids,
    )
    print(
        f"non-ASAP main pieces={scan_counts['non_asap_main_pieces']:,}, "
        f"rows={scan_counts['non_asap_main_seen']:,}, "
        f"target_kept={scan_counts['non_asap_main_target']:,}"
    )

    stats, write_counts = write_subset_and_collect_stats(
        tokenizer=tokenizer,
        task=task,
        input_dir=input_dir,
        output_path=output_path,
        target_field=target_field,
        count_fields=count_fields,
        max_length=max_length,
        asap_ids=asap_ids,
        thresholds=thresholds,
    )
    counts = scan_counts + write_counts

    kept = counts["main_non_asap_kept"]
    seen = counts["non_asap_main_seen"]
    actual_ratio = kept / seen if seen else 0.0
    print(
        f"kept non-ASAP main {kept:,}/{seen:,} ({actual_ratio:.2%}); "
        f"total samples={stats['samples']:,}, total tokens={stats['token_total']:,}"
    )
    return stats, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoReS/metadata.csv"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI-Resized"))
    parser.add_argument("--tasks", nargs="+", choices=sorted(TASK_CONFIGS.keys()), default=list(TASK_CONFIGS.keys()))
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    added = add_lm_midi_tokens(tokenizer)
    print(f"Loaded tokenizer {args.tokenizer} (+{added} LM-MIDI tokens)")

    asap_ids = load_asap_piece_ids(args.metadata)
    print(f"Loaded {len(asap_ids):,} ASAP piece IDs")

    all_stats = {}
    for task in args.tasks:
        config = TASK_CONFIGS[task]
        stats, counts = build_subset(
            tokenizer=tokenizer,
            task=task,
            input_dir=ROOT / config["input_dir"],
            output_path=ROOT / config["output_path"],
            target_field=config["target_field"],
            count_fields=config["count_fields"],
            ratio=config["ratio"],
            max_length=config["max_length"],
            asap_ids=asap_ids,
        )
        all_stats[task] = {
            "stats": stats,
            "counts": dict(counts),
            "output_path": str(config["output_path"]),
        }

    print("\n=== S1 Summary ===")
    print(json.dumps(all_stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
