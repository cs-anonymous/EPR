#!/usr/bin/env python3
"""Summarize CoReS SFT datasets with exact tokenizer counts."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from transformers import AutoTokenizer


EPR_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]


def elapsed(start: float) -> str:
    return f"{time.time() - start:.1f}s"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ["B", "K", "M", "G", "T"]:
        if value < 1024 or unit == "T":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{num_bytes}B"


def text_from_record(record: dict, mode: str) -> str:
    if mode == "messages":
        return "\n".join(
            str(message.get("content", ""))
            for message in record.get("messages", [])
        )
    if mode == "epr":
        return " ".join(str(record.get(field, "")) for field in EPR_FIELDS)
    raise ValueError(f"Unsupported mode: {mode}")


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def summarize_files(tokenizer, files: list[Path], mode: str, batch_size: int) -> dict:
    start = time.time()
    samples = 0
    chars = 0
    tokens = 0
    bytes_total = sum(path.stat().st_size for path in files)

    for path in files:
        file_samples = 0
        text_batch: list[str] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                text = text_from_record(record, mode)
                text_batch.append(text)
                chars += len(text)
                samples += 1
                file_samples += 1
                if len(text_batch) >= batch_size:
                    tokens += sum(token_lengths(tokenizer, text_batch))
                    text_batch = []
            if text_batch:
                tokens += sum(token_lengths(tokenizer, text_batch))

        print(f"  {path.name}: {file_samples:,} rows, cumulative tokens={tokens:,} ({elapsed(start)})", flush=True)

    return {
        "samples": samples,
        "bytes": bytes_total,
        "size": human_size(bytes_total),
        "all_tokens": tokens,
        "avg_token": tokens / samples if samples else 0.0,
        "all_chars": chars,
        "avg_chars": chars / samples if samples else 0.0,
    }


def dataset_specs(cores_root: Path) -> list[tuple[str, str, list[Path]]]:
    return [
        ("language_sft_s1", "messages", [cores_root / "language_sft_s1/sft_language_train.jsonl"]),
        ("language_sft_s2", "messages", [cores_root / "language_sft_s2/sft_language_train.jsonl"]),
        ("measure_epr_sft_s1", "epr", sorted((cores_root / "measure_epr_sft_s1").glob("*.jsonl"))),
        ("measure_epr_sft_s2", "epr", sorted((cores_root / "measure_epr_sft_s2").glob("*.jsonl"))),
        ("phrase_epr_sft_s1", "epr", sorted((cores_root / "phrase_epr_sft_s1").glob("*.jsonl"))),
        ("phrase_epr_sft_s2", "epr", sorted((cores_root / "phrase_epr_sft_s2").glob("*.jsonl"))),
    ]


def summarize_epr_split(tokenizer, split_dir: Path, batch_size: int) -> dict:
    files = sorted(split_dir.glob("*.jsonl"))
    summary = summarize_files(tokenizer, files, "epr", batch_size)
    summary["files"] = []
    for path in files:
        file_summary = summarize_files(tokenizer, [path], "epr", batch_size)
        summary["files"].append({
            "file": path.name,
            "rows": file_summary["samples"],
            "tokens": file_summary["all_tokens"],
            "avg_token": file_summary["avg_token"],
            "bytes": file_summary["bytes"],
            "size": file_summary["size"],
        })
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores-root", type=Path, default=Path("backup/legacy_CoReS"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--batch-size", type=int, default=1024)
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    rows = []
    for dataset, mode, files in dataset_specs(args.cores_root):
        print(f"\nSummarizing {dataset}...")
        summary = summarize_files(tokenizer, files, mode, args.batch_size)
        summary["dataset"] = dataset
        rows.append(summary)

    csv_path = args.cores_root / "sft_dataset_summary.csv"
    fieldnames = ["dataset", "samples", "size", "bytes", "all_tokens", "avg_token", "all_chars", "avg_chars"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "dataset": row["dataset"],
                "samples": row["samples"],
                "size": row["size"],
                "bytes": row["bytes"],
                "all_tokens": row["all_tokens"],
                "avg_token": f"{row['avg_token']:.2f}",
                "all_chars": row["all_chars"],
                "avg_chars": f"{row['avg_chars']:.2f}",
            })

    json_path = args.cores_root / "sft_dataset_summary.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {csv_path}")
    print(f"Wrote {json_path}")

    epr_complete = {
        "measure_max_token": 1024,
        "phrase_max_token": 2560,
        "measure": {
            "measure_epr_sft_s1": summarize_epr_split(tokenizer, args.cores_root / "measure_epr_sft_s1", args.batch_size),
            "measure_epr_sft_s2": summarize_epr_split(tokenizer, args.cores_root / "measure_epr_sft_s2", args.batch_size),
        },
        "phrase": {
            "phrase_epr_sft_s1": summarize_epr_split(tokenizer, args.cores_root / "phrase_epr_sft_s1", args.batch_size),
            "phrase_epr_sft_s2": summarize_epr_split(tokenizer, args.cores_root / "phrase_epr_sft_s2", args.batch_size),
        },
    }
    complete_path = args.cores_root / "epr_s1_s2_complete_summary.json"
    complete_path.write_text(json.dumps(epr_complete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {complete_path}")


if __name__ == "__main__":
    main()
