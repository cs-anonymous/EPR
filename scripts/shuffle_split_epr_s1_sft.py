#!/usr/bin/env python3
"""Build shuffled MS-SWIFT train/val JSONLs from EPR S1 split fields."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_core_s1_swift import convert_sample


TASKS = {
    "measure_epr": {
        "input": Path("PianoCoReS/Corpora/epr_sft/measure_epr_s1.jsonl"),
        "train_output": Path("PianoCoReS/Corpora/epr_sft/measure_epr_s1_shuffle_train.jsonl"),
        "val_output": Path("PianoCoReS/Corpora/epr_sft/measure_epr_s1_shuffle_val.jsonl"),
        "val_size": 10_000,
    },
    "phrase_epr": {
        "input": Path("PianoCoReS/Corpora/epr_sft/phrase_epr_s1.jsonl"),
        "train_output": Path("PianoCoReS/Corpora/epr_sft/phrase_epr_s1_shuffle_train.jsonl"),
        "val_output": Path("PianoCoReS/Corpora/epr_sft/phrase_epr_s1_shuffle_val.jsonl"),
        "val_size": 5_000,
    },
    "abcx2pm": {
        "input": Path("PianoCoReS/Corpora/epr_sft/abcx2pm_s1.jsonl"),
        "train_output": Path("PianoCoReS/Corpora/epr_sft/abcx2pm_s1_shuffle_train.jsonl"),
        "val_output": Path("PianoCoReS/Corpora/epr_sft/abcx2pm_s1_shuffle_val.jsonl"),
        "val_size": 5_000,
    },
    "sm2pm": {
        "input": Path("PianoCoReS/Corpora/epr_sft/sm2pm_s1.jsonl"),
        "train_output": Path("PianoCoReS/Corpora/epr_sft/sm2pm_s1_shuffle_train.jsonl"),
        "val_output": Path("PianoCoReS/Corpora/epr_sft/sm2pm_s1_shuffle_val.jsonl"),
        "val_size": 5_000,
    },
}


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


def write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as fout:
        for line in lines:
            fout.write(line if line.endswith("\n") else line + "\n")
    temp_path.replace(path)


def split_task(task: str, config: dict, seed: int, tokenizer, max_tokens: int, batch_size: int) -> dict:
    start = time.time()
    train_lines: list[str] = []
    val_lines: list[str] = []
    split_counts = {"train": 0, "val": 0, "test": 0, "other": 0}
    filtered_counts = {"train": 0, "val": 0}
    dropped_overlength = {"train": 0, "val": 0}
    batch: list[tuple[str, dict]] = []

    def flush_batch() -> None:
        nonlocal batch
        if not batch:
            return
        texts = [render_messages(tokenizer, item[1]["messages"]) for item in batch]
        lengths = token_lengths(tokenizer, texts)
        for (split, converted), length in zip(batch, lengths):
            if length > max_tokens:
                dropped_overlength[split] += 1
                continue
            serialized = json.dumps(converted, ensure_ascii=False) + "\n"
            if split == "train":
                train_lines.append(serialized)
            else:
                val_lines.append(serialized)
            filtered_counts[split] += 1
        batch = []

    with config["input"].open("r", encoding="utf-8") as fin:
        for line in fin:
            if not line.strip():
                continue
            sample = json.loads(line)
            split = sample.get("split")
            if split == "train":
                pass
            elif split == "val":
                pass
            elif split == "test":
                split_counts["test"] += 1
                continue
            else:
                split_counts["other"] += 1
                continue
            split_counts[split] += 1
            batch.append((split, convert_sample(sample)))
            if len(batch) >= batch_size:
                flush_batch()

    flush_batch()

    train_rng = random.Random(f"{seed}:{task}:train")
    val_rng = random.Random(f"{seed}:{task}:val")
    train_rng.shuffle(train_lines)
    val_rng.shuffle(val_lines)

    sampled_val_lines = val_lines[: min(config["val_size"], len(val_lines))]
    write_jsonl(config["train_output"], train_lines)
    write_jsonl(config["val_output"], sampled_val_lines)

    return {
        "input": str(config["input"]),
        "train_output": str(config["train_output"]),
        "val_output": str(config["val_output"]),
        "seed": seed,
        "max_tokens": max_tokens,
        "source_split_counts": split_counts,
        "filtered_split_counts": filtered_counts,
        "dropped_overlength": dropped_overlength,
        "train_rows": len(train_lines),
        "val_source_rows": len(val_lines),
        "val_sample_rows": len(sampled_val_lines),
        "excluded_test_rows": split_counts["test"],
        "format": "ms-swift messages",
        "elapsed_seconds": round(time.time() - start, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI-Resized"))
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--tasks", nargs="+", choices=sorted(TASKS.keys()), default=list(TASKS.keys()))
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("PianoCoReS/Corpora/epr_sft/epr_s1_shuffle_sft_summary.json"),
    )
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)

    summary = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tasks": {
            task: split_task(task, config, args.seed, tokenizer, args.max_tokens, args.batch_size)
            for task, config in TASKS.items()
            if task in args.tasks
        },
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
