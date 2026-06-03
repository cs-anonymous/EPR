#!/usr/bin/env python3
"""Convert CoRe-S1 JSONL tasks to Swift chat-message SFT format.

Outputs:
  - sft_data/core-s1/sft_language_train.jsonl
  - sft_data/examples/s1_swift/<task>.jsonl with N examples per task

The output JSONL uses the MS-SWIFT compatible shape:
  {"messages": [{"role": "system", ...}, {"role": "user", ...}, ...]}
"""
import argparse
import json
from pathlib import Path
from typing import Callable


SYSTEM_PROMPT = "You are a music score and performance language model."

TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]


def join_nonempty(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part)


def score_context(sample: dict, input_key: str = "input") -> str:
    header = sample.get("header") or sample.get("score_header") or ""
    body = sample.get(input_key) or sample.get("score_snip") or ""
    return join_nonempty([header, body])


def make_messages(user_content: str, assistant_content: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    }


def section(title: str, content: str) -> str:
    content = content.rstrip()
    return f"{title}:\n{content}" if content else ""


def sample_instruction(sample: dict, default: str) -> str:
    return str(sample.get("instruction") or default)


def convert_measure_epr(sample: dict) -> dict:
    target = sample.get("target_measure_id", "")
    task_type = sample.get("task_type", "")
    perf_context = sample.get("perf_context", "")
    instruction = (
        f"Render target measure {target} from aligned ABCX score into expressive compact MIDI-TSV performance. "
        "Use the previous performance context if provided. Output only the target measure."
    )
    user = join_nonempty([
        instruction,
        f"Task type: {task_type}" if task_type else "",
        section("Score", score_context(sample, "score_snip")),
        section("Previous performance", perf_context),
    ])
    return make_messages(user, sample["perf_target"])


def convert_phrase_epr(sample: dict) -> dict:
    target = sample.get("target_phrase_id", "")
    task_type = sample.get("task_type", "")
    perf_context = sample.get("perf_context", "")
    instruction = (
        f"Render target phrase {target} from aligned ABCX score into expressive compact MIDI-TSV performance. "
        "Use the previous performance context if provided. Output only the target phrase."
    )
    user = join_nonempty([
        instruction,
        f"Task type: {task_type}" if task_type else "",
        section("Score", score_context(sample, "score_snip")),
        section("Previous performance", perf_context),
    ])
    return make_messages(user, sample["perf_target"])


def convert_abcx2pm(sample: dict) -> dict:
    task_type = sample.get("task_type", "")
    perf_context = sample.get("perf_context", "")
    if task_type == "coldstart" or not perf_context:
        instruction = sample_instruction(
            sample,
            "Render the provided abcx score into expressive performance midi. Output only the target span.",
        )
    else:
        instruction = sample_instruction(
            sample,
            "Using the provided first performance measure as a style reference, render the rest of the abcx score into expressive performance midi. Output only the target span.",
        )
    user = join_nonempty([
        instruction,
        f"Task type: {task_type}" if task_type else "",
        section("abcx", score_context(sample, "score_snip")),
        section("first performance measure", perf_context),
    ])
    return make_messages(user, sample["perf_target"])


def convert_sm2pm(sample: dict) -> dict:
    task_type = sample.get("task_type", "")
    perf_context = sample.get("perf_context", "")
    if task_type == "coldstart" or not perf_context:
        instruction = sample_instruction(
            sample,
            "Render the provided score midi into expressive performance midi. Output only the target span.",
        )
    else:
        instruction = sample_instruction(
            sample,
            "Using the provided first performance measure as a style reference, render the rest of the score midi into expressive performance midi. Output only the target span.",
        )
    user = join_nonempty([
        instruction,
        f"Task type: {task_type}" if task_type else "",
        section("score midi", sample.get("score_midi_snip", "")),
        section("first performance measure", perf_context),
    ])
    return make_messages(user, sample["perf_target"])


def convert_score_continuation(sample: dict) -> dict:
    level = "phrase" if sample["task"].startswith("phrase_") else "measure"
    instruction = (
        f"Continue the aligned ABCX score from the given {level}. Output only the next {level}."
    )
    user = join_nonempty([
        instruction,
        section("Score", score_context(sample)),
    ])
    return make_messages(user, sample["target"])


def convert_score_mask(sample: dict) -> dict:
    level = "phrase" if sample["task"].startswith("phrase_") else "measure"
    mask_type = sample.get("mask_type", "")
    instruction = (
        f"Restore the {mask_type}-masked aligned ABCX score {level}. Output only the restored {level}."
    )
    user = join_nonempty([
        instruction,
        section("Score", score_context(sample)),
    ])
    return make_messages(user, sample["target"])


def convert_perf_continuation(sample: dict) -> dict:
    instruction = (
        "Continue the compact MIDI-TSV performance from the given measure. Output only the next measure."
    )
    user = join_nonempty([
        instruction,
        section("Performance", sample["input"]),
    ])
    return make_messages(user, sample["target"])


def convert_perf_mask(sample: dict) -> dict:
    mask_type = sample.get("mask_type", "")
    instruction = (
        f"Restore the {mask_type}-masked compact MIDI-TSV performance measure. "
        "Output only the restored measure."
    )
    user = join_nonempty([
        instruction,
        section("Performance", sample["input"]),
    ])
    return make_messages(user, sample["target"])


CONVERTERS: dict[str, Callable[[dict], dict]] = {
    "measure_epr": convert_measure_epr,
    "phrase_epr": convert_phrase_epr,
    "abcx2pm": convert_abcx2pm,
    "sm2pm": convert_sm2pm,
    "measure_score_lang_continuation": convert_score_continuation,
    "measure_score_lang_mask": convert_score_mask,
    "phrase_score_lang_continuation": convert_score_continuation,
    "phrase_score_lang_mask": convert_score_mask,
    "measure_perf_lang_continuation": convert_perf_continuation,
    "measure_perf_lang_mask": convert_perf_mask,
}


def convert_sample(sample: dict) -> dict:
    task = sample.get("task", "")
    converter = CONVERTERS.get(task)
    if converter is None:
        raise ValueError(f"Unsupported task: {task}")
    return converter(sample)


def convert_dataset(input_dir: Path, output_path: Path, examples_dir: Path, examples_per_task: int) -> dict[str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    examples_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    example_handles = {}
    try:
        with output_path.open("w", encoding="utf-8") as fout:
            for file_name in TASK_FILES:
                src = input_dir / file_name
                if not src.exists():
                    print(f"SKIP missing file: {src}")
                    continue

                task_name = file_name.removesuffix(".jsonl")
                example_path = examples_dir / file_name
                example_handles[task_name] = example_path.open("w", encoding="utf-8")
                count = 0

                with src.open("r", encoding="utf-8") as fin:
                    for line in fin:
                        if not line.strip():
                            continue
                        sample = json.loads(line)
                        converted = convert_sample(sample)
                        encoded = json.dumps(converted, ensure_ascii=False) + "\n"
                        fout.write(encoded)
                        if count < examples_per_task:
                            example_handles[task_name].write(encoded)
                        count += 1

                counts[task_name] = count
                print(f"{task_name}: {count:,}")
    finally:
        for handle in example_handles.values():
            handle.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("sft_data/core-s1"))
    parser.add_argument("--output", type=Path, default=Path("sft_data/core-s1/sft_language_train.jsonl"))
    parser.add_argument("--examples-dir", type=Path, default=Path("sft_data/examples/s1_swift"))
    parser.add_argument("--examples-per-task", type=int, default=10)
    args = parser.parse_args()

    counts = convert_dataset(args.input_dir, args.output, args.examples_dir, args.examples_per_task)
    print(f"TOTAL: {sum(counts.values()):,}")
    print(f"Train: {args.output}")
    print(f"Examples: {args.examples_dir}")


if __name__ == "__main__":
    main()
