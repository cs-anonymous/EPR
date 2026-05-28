#!/usr/bin/env python3
"""Build language SFT validation dataset from val split in metadata.csv."""

import argparse
import csv
import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import generate_language_learning_data as gll
from prepare_core_s1_swift import convert_sample
from transformers import AutoTokenizer

MAX_TOKENS = 512
TOKENIZER = None


def init_worker(tokenizer_path: str):
    global TOKENIZER
    TOKENIZER = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)


def render_messages(tokenizer, messages: list[dict]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
    except Exception:
        return "\n".join(str(message.get("content", "")) for message in messages)


def token_length(tokenizer, text: str) -> int:
    encoded = tokenizer(
        text, add_special_tokens=False, truncation=False, padding=False
    )
    return len(encoded["input_ids"])


def process_perf_file(tsv_path_str: str) -> list[str]:
    """Generate all language tasks from a performance TSV file."""
    tsv_path = Path(tsv_path_str)
    results = []

    try:
        perf_data = gll.TSVParser.parse(str(tsv_path))
    except Exception:
        return results

    if not perf_data["measures"]:
        return results

    piece_id = tsv_path.stem.replace("_refined.mid", "")
    measure_ids = sorted(perf_data["measures"].keys(), key=lambda x: int(x[1:]))

    for i in range(len(measure_ids) - 1):
        curr_m_id = measure_ids[i]
        next_m_id = measure_ids[i + 1]
        curr_duration = perf_data["measure_durations"].get(curr_m_id, "")
        next_duration = perf_data["measure_durations"].get(next_m_id, "")
        curr_lines = perf_data["measures"][curr_m_id]
        next_lines = perf_data["measures"][next_m_id]

        # Continuation task
        sample = {
            "task": "measure_perf_lang_continuation",
            "input": gll.format_perf_measure(curr_m_id, curr_duration, curr_lines),
            "target": gll.format_perf_measure(next_m_id, next_duration, next_lines),
            "piece_id": piece_id,
        }
        converted = convert_sample(sample)
        text = render_messages(TOKENIZER, converted["messages"])
        tokens = token_length(TOKENIZER, text)

        if tokens <= MAX_TOKENS:
            results.append(json.dumps(converted, ensure_ascii=False) + "\n")

    return results


def main():
    global MAX_TOKENS
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("data/metadata.csv"))
    parser.add_argument("--aligned-root", type=Path, default=Path("data/aligned"))
    parser.add_argument("--output", type=Path, default=Path("backup/legacy_CoReS/language_sft_val.jsonl"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    MAX_TOKENS = args.max_tokens

    # Collect val performance files
    val_perf_files = []
    with args.metadata.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split") != "val":
                continue
            perf_tsv = row.get("performance_tsv_path", "")
            if perf_tsv:
                p = Path(perf_tsv)
                if p.exists():
                    val_perf_files.append(str(p))

    print(f"Found {len(val_perf_files):,} val performance files")

    # Process in parallel
    with mp.Pool(processes=args.workers, initializer=init_worker, initargs=(str(args.tokenizer),)) as pool:
        results = list(pool.imap_unordered(process_perf_file, val_perf_files, chunksize=16))

    # Flatten and write
    all_lines = []
    for result in results:
        all_lines.extend(result)

    print(f"Generated {len(all_lines):,} validation samples")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for line in all_lines:
            f.write(line)

    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
