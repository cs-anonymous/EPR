#!/usr/bin/env python3
"""Build CoRe-S S1 and S2 EPR datasets with token budget constraints.

Requirements:
- S1: ~600M-800M tokens total
  - Keep all coldstart and ending samples
  - Keep all ASAP samples
  - For other samples, keep at least one per source (performance_dataset), sample by source
- S2: ~300M-400M tokens total (half of S1)
  - Keep all ASAP samples
  - Sample half of non-ASAP samples from S1

Uses:
- measure_epr: existing design with max_length=2048
- phrase_epr: compact design with max_length=2560
"""

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

from transformers import AutoTokenizer
from tqdm import tqdm


COUNT_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]


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
    if path.startswith("PianoCoReS/miditsv/"):
        path = path[len("PianoCoReS/miditsv/"):]
    elif path.startswith("PianoCoReS/aligned/"):
        path = path[len("PianoCoReS/aligned/"):]
    elif path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/"):]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/"):]
    if path.endswith(".tsv"):
        path = path[: -len(".tsv")]
    return path


def load_metadata_mapping(metadata_path: Path) -> tuple[set[str], dict[str, str]]:
    """Load ASAP piece_ids and piece_id -> performance_dataset mapping."""
    asap_ids = set()
    piece_to_source = {}

    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            piece_id = performance_piece_id(row.get("performance_tsv_path", ""))
            if not piece_id:
                continue

            source = row.get("performance_dataset", "")
            piece_to_source[piece_id] = source

            if row.get("is_transcription") == "False":
                asap_ids.add(piece_id)

    return asap_ids, piece_to_source


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
    """Apply phrase EPR compact context: M_prev + H_k + M_next, phi_M_prev."""
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
    out["context_design"] = "phrase_epr_compact_prev_measure"
    return out


def count_tokens_batch(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def filter_and_analyze(
    tokenizer,
    input_path: Path,
    max_token: int,
    asap_ids: set[str],
    piece_to_source: dict[str, str],
    batch_size: int = 512,
) -> dict:
    """Filter by token count and analyze distribution by source."""
    print(f"  Analyzing {input_path.name} (max_token={max_token})...")

    # Statistics by task_type and source
    stats = {
        "coldstart": {"total": 0, "kept": 0, "tokens": 0, "samples": []},
        "ending": {"total": 0, "kept": 0, "tokens": 0, "samples": []},
        "main": {
            "total": 0,
            "kept": 0,
            "tokens": 0,
            "asap": {"count": 0, "tokens": 0, "samples": []},
            "by_source": defaultdict(lambda: {"count": 0, "tokens": 0, "samples": []}),
        },
    }

    with input_path.open("r", encoding="utf-8") as f:
        batch_lines = []
        batch_texts = []
        batch_records = []

        def process_batch():
            if not batch_lines:
                return

            token_counts = count_tokens_batch(tokenizer, batch_texts)

            for line, record, tokens in zip(batch_lines, batch_records, token_counts):
                task_type = record.get("task_type", "main")
                piece_id = record.get("piece_id", "")

                if task_type in ["coldstart", "ending"]:
                    stats[task_type]["total"] += 1
                    if tokens <= max_token:
                        stats[task_type]["kept"] += 1
                        stats[task_type]["tokens"] += tokens
                        stats[task_type]["samples"].append((line, tokens))
                else:
                    stats["main"]["total"] += 1
                    if tokens <= max_token:
                        stats["main"]["kept"] += 1
                        stats["main"]["tokens"] += tokens

                        if piece_id in asap_ids:
                            stats["main"]["asap"]["count"] += 1
                            stats["main"]["asap"]["tokens"] += tokens
                            stats["main"]["asap"]["samples"].append((line, tokens, piece_id))
                        else:
                            source = piece_to_source.get(piece_id, "unknown")
                            stats["main"]["by_source"][source]["count"] += 1
                            stats["main"]["by_source"][source]["tokens"] += tokens
                            stats["main"]["by_source"][source]["samples"].append((line, tokens, piece_id))

            batch_lines.clear()
            batch_texts.clear()
            batch_records.clear()

        for line in tqdm(f, desc=f"  Filtering {input_path.name}"):
            if not line.strip():
                continue

                record = json.loads(line)
                record = compact_phrase_epr_context(record)
                batch_lines.append(json.dumps(record, ensure_ascii=False) + "\n")
                batch_texts.append(record_text(record))
                batch_records.append(record)

            if len(batch_lines) >= batch_size:
                process_batch()

        process_batch()

    return stats


def sample_main_by_source(
    main_stats: dict,
    target_tokens: int,
    seed: int,
    task_name: str,
) -> list[tuple[str, int]]:
    """Sample main samples to reach target token budget.

    Strategy:
    1. Keep all ASAP samples
    2. For non-ASAP, keep at least one per source
    3. Distribute remaining budget proportionally by source
    """
    rng = random.Random(stable_seed(seed, task_name, "main"))

    # Keep all ASAP
    selected = list(main_stats["asap"]["samples"])
    current_tokens = main_stats["asap"]["tokens"]

    print(f"    ASAP: {main_stats['asap']['count']:,} samples, {current_tokens:,} tokens")

    # Calculate remaining budget
    remaining_budget = target_tokens - current_tokens
    if remaining_budget <= 0:
        print(f"    Warning: ASAP samples already exceed target budget!")
        return selected

    # Collect non-ASAP samples by source
    by_source = main_stats["by_source"]
    sources = list(by_source.keys())

    # Keep at least one per source
    for source in sources:
        samples = by_source[source]["samples"]
        if samples:
            rng.shuffle(samples)
            line, tokens, piece_id = samples[0]
            selected.append((line, tokens, piece_id))
            current_tokens += tokens
            remaining_budget -= tokens

    print(f"    Kept 1 sample per source: {len(sources)} sources, {current_tokens:,} tokens")

    if remaining_budget <= 0:
        return selected

    # Calculate how many more samples we can take from each source
    # Distribute proportionally by source token count
    total_source_tokens = sum(s["tokens"] for s in by_source.values())
    source_budgets = {}

    for source, source_stats in by_source.items():
        proportion = source_stats["tokens"] / total_source_tokens if total_source_tokens > 0 else 0
        source_budgets[source] = int(remaining_budget * proportion)

    # Sample from each source up to budget
    for source in sources:
        samples = by_source[source]["samples"]
        budget = source_budgets[source]

        # Skip first sample (already selected)
        available = samples[1:]
        if not available or budget <= 0:
            continue

        # Greedily select samples until budget exhausted
        rng.shuffle(available)
        source_selected = 0
        source_tokens = 0

        for line, tokens, piece_id in available:
            if source_tokens + tokens <= budget:
                selected.append((line, tokens, piece_id))
                source_tokens += tokens
                source_selected += 1
            else:
                break

        current_tokens += source_tokens
        print(f"    {source}: +{source_selected} samples, +{source_tokens:,} tokens")

    print(f"    Total main: {len(selected):,} samples, {current_tokens:,} tokens")
    return selected


def write_s1_dataset(
    task_name: str,
    stats: dict,
    output_dir: Path,
    target_main_tokens: int,
    seed: int,
) -> dict:
    """Write S1 dataset files."""
    print(f"\n--- Writing S1 {task_name} ---")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Write coldstart (all filtered)
    coldstart_path = output_dir / f"{task_name}_coldstart.jsonl"
    with coldstart_path.open("w", encoding="utf-8") as f:
        for line, tokens in stats["coldstart"]["samples"]:
            f.write(line)

    coldstart_count = stats["coldstart"]["kept"]
    coldstart_tokens = stats["coldstart"]["tokens"]
    print(f"  Coldstart: {coldstart_count:,} samples, {coldstart_tokens:,} tokens")

    # Write ending (all filtered)
    ending_path = output_dir / f"{task_name}_ending.jsonl"
    with ending_path.open("w", encoding="utf-8") as f:
        for line, tokens in stats["ending"]["samples"]:
            f.write(line)

    ending_count = stats["ending"]["kept"]
    ending_tokens = stats["ending"]["tokens"]
    print(f"  Ending: {ending_count:,} samples, {ending_tokens:,} tokens")

    # Sample and write main
    main_samples = sample_main_by_source(stats["main"], target_main_tokens, seed, task_name)

    main_path = output_dir / f"{task_name}_main.jsonl"
    main_tokens = 0
    with main_path.open("w", encoding="utf-8") as f:
        for item in main_samples:
            line = item[0]
            tokens = item[1]
            f.write(line)
            main_tokens += tokens

    main_count = len(main_samples)

    total_count = coldstart_count + ending_count + main_count
    total_tokens = coldstart_tokens + ending_tokens + main_tokens

    print(f"  Total S1 {task_name}: {total_count:,} samples, {total_tokens:,} tokens")

    return {
        "task": task_name,
        "coldstart_samples": coldstart_count,
        "coldstart_tokens": coldstart_tokens,
        "ending_samples": ending_count,
        "ending_tokens": ending_tokens,
        "main_samples": main_count,
        "main_tokens": main_tokens,
        "total_samples": total_count,
        "total_tokens": total_tokens,
    }


def sample_s2_from_s1(
    s1_dir: Path,
    s2_dir: Path,
    task_name: str,
    asap_ids: set[str],
    seed: int,
) -> dict:
    """Sample S2 from S1: keep all ASAP, sample half of non-ASAP."""
    print(f"\n--- Sampling S2 {task_name} from S1 ---")

    s2_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(stable_seed(seed, task_name, "s2"))

    stats = {
        "coldstart": {"count": 0, "tokens": 0},
        "ending": {"count": 0, "tokens": 0},
        "main": {"count": 0, "tokens": 0},
    }

    # Copy coldstart and ending as-is
    for task_type in ["coldstart", "ending"]:
        s1_path = s1_dir / f"{task_name}_{task_type}.jsonl"
        s2_path = s2_dir / f"{task_name}_{task_type}.jsonl"
        shutil.copyfile(s1_path, s2_path)

        # Count samples and tokens
        with s1_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    stats[task_type]["count"] += 1

        print(f"  {task_type.capitalize()}: {stats[task_type]['count']:,} samples (copied all)")

    # Sample main: keep all ASAP, sample half of non-ASAP
    s1_main_path = s1_dir / f"{task_name}_main.jsonl"
    s2_main_path = s2_dir / f"{task_name}_main.jsonl"

    asap_samples = []
    non_asap_samples = []

    with s1_main_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            piece_id = record.get("piece_id", "")

            if piece_id in asap_ids:
                asap_samples.append(line)
            else:
                non_asap_samples.append(line)

    # Sample half of non-ASAP
    target_non_asap = len(non_asap_samples) // 2
    rng.shuffle(non_asap_samples)
    sampled_non_asap = non_asap_samples[:target_non_asap]

    # Write S2 main
    with s2_main_path.open("w", encoding="utf-8") as f:
        for line in asap_samples:
            f.write(line)
        for line in sampled_non_asap:
            f.write(line)

    stats["main"]["count"] = len(asap_samples) + len(sampled_non_asap)

    print(f"  Main: {stats['main']['count']:,} samples (ASAP={len(asap_samples):,}, non-ASAP={len(sampled_non_asap):,}/{len(non_asap_samples):,})")

    total_count = stats["coldstart"]["count"] + stats["ending"]["count"] + stats["main"]["count"]
    print(f"  Total S2 {task_name}: {total_count:,} samples")

    return {
        "task": task_name,
        "coldstart_samples": stats["coldstart"]["count"],
        "ending_samples": stats["ending"]["count"],
        "main_samples": stats["main"]["count"],
        "total_samples": total_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Build CoRe-S S1 and S2 EPR datasets")
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="Input directory containing full CoRe-S data")
    parser.add_argument("--output-dir", type=Path, default=Path("sft_data"),
                        help="Output directory for S1 and S2 datasets")
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoRe/metadata.csv"),
                        help="Path to metadata.csv")
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"),
                        help="Tokenizer for token counting")
    parser.add_argument("--s1-target-tokens", type=int, default=700_000_000,
                        help="Target total tokens for S1 (default: 700M)")
    parser.add_argument("--measure-max-token", type=int, default=2048,
                        help="Maximum token length for measure EPR samples")
    parser.add_argument("--phrase-max-token", type=int, default=2560,
                        help="Maximum token length for compact phrase EPR samples")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed")
    parser.add_argument("--batch-size", type=int, default=512,
                        help="Batch size for tokenization")

    args = parser.parse_args()

    overall_start = time.time()

    print("=" * 80)
    print("CoRe-S S1 and S2 Dataset Generation")
    print("=" * 80)

    # Load metadata
    print("\nLoading metadata...")
    asap_ids, piece_to_source = load_metadata_mapping(args.metadata)
    print(f"  ASAP pieces: {len(asap_ids):,}")
    print(f"  Total pieces: {len(piece_to_source):,}")
    print(f"  Sources: {set(piece_to_source.values())}")

    # Load tokenizer
    print("\nLoading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)
    print(f"  Tokenizer loaded: {args.tokenizer}")

    # Process each task
    tasks = ["measure_epr", "phrase_epr"]
    all_stats = {}

    for task_name in tasks:
        print(f"\n{'=' * 80}")
        print(f"Processing {task_name}")
        print(f"{'=' * 80}")

        # Find input files
        input_path = args.input_dir / f"{task_name}.jsonl"
        if not input_path.exists():
            print(f"  Warning: {input_path} not found, skipping...")
            continue

        max_token = args.phrase_max_token if task_name == "phrase_epr" else args.measure_max_token

        # Filter and analyze
        stats = filter_and_analyze(
            tokenizer=tokenizer,
            input_path=input_path,
            max_token=max_token,
            asap_ids=asap_ids,
            piece_to_source=piece_to_source,
            batch_size=args.batch_size,
        )

        all_stats[task_name] = stats

        # Print analysis
        print(f"\n  Analysis for {task_name}:")
        print(f"    Coldstart: {stats['coldstart']['kept']:,}/{stats['coldstart']['total']:,} samples, {stats['coldstart']['tokens']:,} tokens")
        print(f"    Ending: {stats['ending']['kept']:,}/{stats['ending']['total']:,} samples, {stats['ending']['tokens']:,} tokens")
        print(f"    Main ASAP: {stats['main']['asap']['count']:,} samples, {stats['main']['asap']['tokens']:,} tokens")
        print(f"    Main non-ASAP: {stats['main']['kept'] - stats['main']['asap']['count']:,} samples")
        for source, source_stats in sorted(stats['main']['by_source'].items()):
            print(f"      {source}: {source_stats['count']:,} samples, {source_stats['tokens']:,} tokens")

    # Calculate S1 token budgets
    print(f"\n{'=' * 80}")
    print("S1 Token Budget Allocation")
    print(f"{'=' * 80}")

    total_coldstart_ending_tokens = sum(
        all_stats[task]["coldstart"]["tokens"] + all_stats[task]["ending"]["tokens"]
        for task in tasks if task in all_stats
    )

    remaining_budget = args.s1_target_tokens - total_coldstart_ending_tokens

    print(f"  Target S1 total: {args.s1_target_tokens:,} tokens")
    print(f"  Coldstart + Ending: {total_coldstart_ending_tokens:,} tokens")
    print(f"  Remaining for Main: {remaining_budget:,} tokens")

    # Allocate main budget proportionally by task
    task_main_budgets = {}
    total_main_tokens = sum(
        all_stats[task]["main"]["kept"]
        * (args.phrase_max_token if task == "phrase_epr" else args.measure_max_token)  # rough estimate
        for task in tasks if task in all_stats
    )

    for task in tasks:
        if task not in all_stats:
            continue
        task_max_token = args.phrase_max_token if task == "phrase_epr" else args.measure_max_token
        proportion = (all_stats[task]["main"]["kept"] * task_max_token) / total_main_tokens if total_main_tokens > 0 else 0.5
        task_main_budgets[task] = int(remaining_budget * proportion)
        print(f"  {task} main budget: {task_main_budgets[task]:,} tokens")

    # Generate S1
    print(f"\n{'=' * 80}")
    print("Generating S1 Dataset")
    print(f"{'=' * 80}")

    s1_dir = args.output_dir / "core-s-s1"
    s1_results = []

    for task_name in tasks:
        if task_name not in all_stats:
            continue

        result = write_s1_dataset(
            task_name=task_name,
            stats=all_stats[task_name],
            output_dir=s1_dir,
            target_main_tokens=task_main_budgets[task_name],
            seed=args.seed,
        )
        s1_results.append(result)

    # Print S1 summary
    total_s1_samples = sum(r["total_samples"] for r in s1_results)
    total_s1_tokens = sum(r["total_tokens"] for r in s1_results)

    print(f"\n{'=' * 80}")
    print("S1 Summary")
    print(f"{'=' * 80}")
    for result in s1_results:
        print(f"  {result['task']}: {result['total_samples']:,} samples, {result['total_tokens']:,} tokens")
    print(f"  TOTAL S1: {total_s1_samples:,} samples, {total_s1_tokens:,} tokens ({total_s1_tokens/1e6:.1f}M)")

    # Generate S2
    print(f"\n{'=' * 80}")
    print("Generating S2 Dataset")
    print(f"{'=' * 80}")

    s2_dir = args.output_dir / "core-s-s2"
    s2_results = []

    for task_name in tasks:
        if task_name not in all_stats:
            continue

        result = sample_s2_from_s1(
            s1_dir=s1_dir,
            s2_dir=s2_dir,
            task_name=task_name,
            asap_ids=asap_ids,
            seed=args.seed,
        )
        s2_results.append(result)

    # Print S2 summary
    total_s2_samples = sum(r["total_samples"] for r in s2_results)

    print(f"\n{'=' * 80}")
    print("S2 Summary")
    print(f"{'=' * 80}")
    for result in s2_results:
        print(f"  {result['task']}: {result['total_samples']:,} samples")
    print(f"  TOTAL S2: {total_s2_samples:,} samples")

    # Save summary
    summary = {
        "s1": s1_results,
        "s2": s2_results,
        "config": {
            "measure_max_token": args.measure_max_token,
            "phrase_max_token": args.phrase_max_token,
            "s1_target_tokens": args.s1_target_tokens,
            "seed": args.seed,
        }
    }

    summary_path = args.output_dir / "s1_s2_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 80}")
    print(f"Complete! Total time: {elapsed(overall_start)}")
    print(f"{'=' * 80}")
    print(f"  S1 output: {s1_dir}")
    print(f"  S2 output: {s2_dir}")
    print(f"  Summary: {summary_path}")


if __name__ == "__main__":
    main()
