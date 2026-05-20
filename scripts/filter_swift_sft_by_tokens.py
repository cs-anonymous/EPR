#!/usr/bin/env python3
"""Filter Swift chat JSONL SFT data by tokenizer length.

The length check mirrors Swift/Qwen chat formatting: messages are rendered with
the tokenizer chat template, then tokenized without adding extra special tokens.
Input lines are preserved byte-for-byte in the filtered output.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from transformers import AutoTokenizer


def task_name(row: dict) -> str:
    messages = row.get("messages") or []
    user = messages[1].get("content", "") if len(messages) > 1 else ""
    if user.startswith("Continue the aligned ABCX score from the given measure"):
        return "measure_score_lang_continuation"
    if user.startswith("Continue the aligned ABCX score from the given phrase"):
        return "phrase_score_lang_continuation"
    if user.startswith("Restore the") and "ABCX score measure" in user:
        return "measure_score_lang_mask"
    if user.startswith("Restore the") and "ABCX score phrase" in user:
        return "phrase_score_lang_mask"
    if user.startswith("Continue the compact MIDI-TSV performance"):
        return "measure_perf_lang_continuation"
    if user.startswith("Restore the") and "compact MIDI-TSV performance measure" in user:
        return "measure_perf_lang_mask"
    return "unknown"


def render_messages(tokenizer, messages: list[dict]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
    except Exception:
        return "\n".join(str(message.get("content", "")) for message in messages)


def percentile(lengths: list[int], q: float) -> int:
    if not lengths:
        return 0
    ordered = sorted(lengths)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))]


def flush_batch(tokenizer, batch: list[tuple[str, str, str]], fout, max_tokens: int, dry_run: bool, stats: dict) -> None:
    if not batch:
        return
    texts = [item[2] for item in batch]
    encoded = tokenizer(texts, add_special_tokens=False, truncation=False, padding=False)
    for (line, task, _), input_ids in zip(batch, encoded["input_ids"]):
        length = len(input_ids)
        row_stats = stats[task]
        row_stats["total"] += 1
        row_stats["max"] = max(row_stats["max"], length)
        row_stats["lengths"].append(length)
        if length <= max_tokens:
            row_stats["kept"] += 1
            if not dry_run:
                fout.write(line)
        else:
            row_stats["dropped"] += 1
    batch.clear()


def filter_file(tokenizer, input_path: Path, output_path: Path, max_tokens: int, batch_size: int, dry_run: bool) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = defaultdict(lambda: {"total": 0, "kept": 0, "dropped": 0, "max": 0, "lengths": []})
    fout = None if dry_run else output_path.open("w", encoding="utf-8")
    batch: list[tuple[str, str, str]] = []
    try:
        with input_path.open("r", encoding="utf-8") as fin:
            for line in fin:
                if not line.strip():
                    continue
                row = json.loads(line)
                task = task_name(row)
                text = render_messages(tokenizer, row.get("messages") or [])
                batch.append((line, task, text))
                if len(batch) >= batch_size:
                    flush_batch(tokenizer, batch, fout, max_tokens, dry_run, stats)
        flush_batch(tokenizer, batch, fout, max_tokens, dry_run, stats)
    finally:
        if fout is not None:
            fout.close()

    result = {}
    for task, row in sorted(stats.items()):
        lengths = row.pop("lengths")
        row["p50"] = percentile(lengths, 0.50)
        row["p95"] = percentile(lengths, 0.95)
        row["p99"] = percentile(lengths, 0.99)
        result[task] = dict(row)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    stats = filter_file(tokenizer, args.input, args.output, args.max_tokens, args.batch_size, args.dry_run)

    total = {"total": 0, "kept": 0, "dropped": 0, "max": 0}
    for row in stats.values():
        total["total"] += row["total"]
        total["kept"] += row["kept"]
        total["dropped"] += row["dropped"]
        total["max"] = max(total["max"], row["max"])

    print(f"Input: {args.input}")
    print(f"Output: {args.output}{' (dry run)' if args.dry_run else ''}")
    print(
        f"Total: {total['total']:,}; kept: {total['kept']:,}; "
        f"dropped: {total['dropped']:,}; max_tokens_seen: {total['max']:,}"
    )
    for task, row in stats.items():
        kept_pct = 100 * row["kept"] / row["total"] if row["total"] else 0
        print(
            f"  {task}: kept {row['kept']:,}/{row['total']:,} ({kept_pct:.2f}%), "
            f"dropped {row['dropped']:,}, max {row['max']}, p50 {row['p50']}, "
            f"p95 {row['p95']}, p99 {row['p99']}"
        )


if __name__ == "__main__":
    main()
