#!/usr/bin/env python3
"""Balance phrase EPR S1/S2 datasets toward smaller token budgets.

Policy:
1. Keep all coldstart / ending rows unchanged.
2. Keep all ASAP rows in main unchanged.
3. For S1 main non-ASAP rows, prefer dropping lower-priority sources first,
   then downsample the remaining non-ASAP rows by piece to fit a target token
   budget.
4. Derive S2 from the new S1:
   - keep all ASAP rows
   - keep all non-ASAP rows from selected keep sources
   - sample remaining non-ASAP rows by piece so the final S2 token total fits
     its target budget.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from transformers import AutoTokenizer


COUNT_FIELDS = ["instruction", "score_header", "score_snip", "perf_context", "perf_target"]
SOURCE_PRIORITY = {
    "ASAP": 0,
    "PERiScoPe": 1,
    "Aria-MIDI": 2,
    "ATEPP": 3,
    "GiantMIDI-Piano": 4,
    "unknown": 5,
}


@dataclass
class Sample:
    raw: str
    piece_id: str
    source: str
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


def load_metadata_mapping(metadata_path: Path) -> tuple[set[str], dict[str, str]]:
    asap_ids = set()
    piece_to_source: dict[str, str] = {}
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            piece_id = performance_piece_id(row.get("performance_tsv_path", ""))
            if not piece_id:
                continue
            source = row.get("performance_dataset") or "unknown"
            piece_to_source[piece_id] = source
            if row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False":
                asap_ids.add(piece_id)
    return asap_ids, piece_to_source


def record_text(record: dict) -> str:
    return " ".join(str(record.get(field, "")) for field in COUNT_FIELDS)


def token_lengths(tokenizer, texts: list[str]) -> list[int]:
    encoded = tokenizer(
        texts,
        add_special_tokens=False,
        truncation=False,
        padding=False,
        return_attention_mask=False,
    )
    return [len(ids) for ids in encoded["input_ids"]]


def load_samples(path: Path, tokenizer, asap_ids: set[str], piece_to_source: dict[str, str], batch_size: int) -> list[Sample]:
    samples: list[Sample] = []
    raw_batch: list[str] = []
    text_batch: list[str] = []
    meta_batch: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            piece_id = record.get("piece_id", "")
            source = "ASAP" if piece_id in asap_ids else piece_to_source.get(piece_id, "unknown")
            raw_batch.append(line)
            text_batch.append(record_text(record))
            meta_batch.append((piece_id, source))
            if len(raw_batch) >= batch_size:
                for raw, (pid, source_name), tokens in zip(raw_batch, meta_batch, token_lengths(tokenizer, text_batch)):
                    samples.append(Sample(raw=raw, piece_id=pid, source=source_name, tokens=tokens))
                raw_batch = []
                text_batch = []
                meta_batch = []
    if raw_batch:
        for raw, (pid, source_name), tokens in zip(raw_batch, meta_batch, token_lengths(tokenizer, text_batch)):
            samples.append(Sample(raw=raw, piece_id=pid, source=source_name, tokens=tokens))
    return samples


def write_samples(path: Path, samples: list[Sample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(sample.raw)


def source_summary(samples: list[Sample]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "tokens": 0})
    for sample in samples:
        stats[sample.source]["rows"] += 1
        stats[sample.source]["tokens"] += sample.tokens
    return dict(stats)


def total_tokens(samples: list[Sample]) -> int:
    return sum(sample.tokens for sample in samples)


def total_rows(samples: list[Sample]) -> int:
    return len(samples)


def sample_by_piece_token_budget(samples: list[Sample], target_tokens: int, seed: int, label: str) -> list[Sample]:
    if not samples or target_tokens <= 0:
        return []

    by_piece: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_piece[sample.piece_id].append(sample)

    rng = random.Random(stable_seed(seed, label, "piece_budget"))
    piece_ids = list(by_piece)
    rng.shuffle(piece_ids)
    for piece_id in piece_ids:
        rng.shuffle(by_piece[piece_id])

    # Round-robin by piece depth so no single piece dominates early.
    max_depth = max(len(rows) for rows in by_piece.values())
    rounds: list[list[Sample]] = []
    for depth in range(max_depth):
        round_samples = [by_piece[piece_id][depth] for piece_id in piece_ids if depth < len(by_piece[piece_id])]
        rng.shuffle(round_samples)
        round_samples.sort(key=lambda sample: sample.tokens)
        rounds.append(round_samples)

    selected: list[Sample] = []
    used_tokens = 0
    for round_samples in rounds:
        added_any = False
        for sample in round_samples:
            if used_tokens + sample.tokens <= target_tokens:
                selected.append(sample)
                used_tokens += sample.tokens
                added_any = True
        if not added_any and used_tokens >= target_tokens:
            break

    return selected


def balance_s1_main_non_asap(
    samples: list[Sample],
    target_tokens: int,
    keep_sources: set[str],
    seed: int,
) -> list[Sample]:
    kept: list[Sample] = [sample for sample in samples if sample.source in keep_sources]
    kept_tokens = total_tokens(kept)
    if kept_tokens >= target_tokens:
        return kept

    remaining = [sample for sample in samples if sample.source not in keep_sources]
    remaining_budget = target_tokens - kept_tokens
    selected_rest = sample_by_piece_token_budget(remaining, remaining_budget, seed, "s1_non_asap")
    return kept + selected_rest


def balance_s2_main_non_asap(
    s1_non_asap: list[Sample],
    keep_sources: set[str],
    target_tokens: int,
    seed: int,
) -> list[Sample]:
    kept: list[Sample] = [sample for sample in s1_non_asap if sample.source in keep_sources]
    kept_tokens = total_tokens(kept)
    if kept_tokens >= target_tokens:
        return kept

    remaining = [sample for sample in s1_non_asap if sample.source not in keep_sources]
    remaining_budget = target_tokens - kept_tokens
    selected_rest = sample_by_piece_token_budget(remaining, remaining_budget, seed, "s2_non_asap")
    return kept + selected_rest


def write_counts_csv(path: Path, counts: dict[str, int]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples"])
        writer.writeheader()
        for file_name, rows in counts.items():
            writer.writerow({"file": file_name, "kept_samples": rows})


def print_breakdown(label: str, samples: list[Sample]) -> None:
    print(f"{label}: rows={total_rows(samples):,}, tokens={total_tokens(samples):,}")
    for source, stats in sorted(
        source_summary(samples).items(),
        key=lambda item: (SOURCE_PRIORITY.get(item[0], 99), item[0]),
    ):
        print(f"  {source}: rows={stats['rows']:,}, tokens={stats['tokens']:,}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores-root", type=Path, default=Path("backup/legacy_CoReS"))
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--s1-target-tokens", type=int, default=610_000_000)
    parser.add_argument("--s2-target-tokens", type=int, default=318_000_000)
    parser.add_argument("--keep-source", action="append", default=["PERiScoPe"],
                        help="Non-ASAP sources to fully keep before downsampling the rest. Repeatable.")
    args = parser.parse_args()

    asap_ids, piece_to_source = load_metadata_mapping(args.metadata)
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)

    s1_dir = args.cores_root / "phrase_epr_sft_s1"
    s2_dir = args.cores_root / "phrase_epr_sft_s2"
    keep_sources = set(args.keep_source)

    s1_cold = load_samples(s1_dir / "phrase_epr_coldstart.jsonl", tokenizer, asap_ids, piece_to_source, args.batch_size)
    s1_end = load_samples(s1_dir / "phrase_epr_ending.jsonl", tokenizer, asap_ids, piece_to_source, args.batch_size)
    s1_main = load_samples(s1_dir / "phrase_epr_main.jsonl", tokenizer, asap_ids, piece_to_source, args.batch_size)

    s1_main_asap = [sample for sample in s1_main if sample.source == "ASAP"]
    s1_main_non_asap = [sample for sample in s1_main if sample.source != "ASAP"]

    fixed_s1_tokens = total_tokens(s1_cold) + total_tokens(s1_end) + total_tokens(s1_main_asap)
    target_s1_non_asap_tokens = max(0, args.s1_target_tokens - fixed_s1_tokens)
    new_s1_main_non_asap = balance_s1_main_non_asap(
        s1_main_non_asap,
        target_s1_non_asap_tokens,
        keep_sources=keep_sources,
        seed=args.seed,
    )
    new_s1_main = s1_main_asap + new_s1_main_non_asap

    fixed_s2_tokens = total_tokens(s1_cold[:0])  # placeholder for symmetry in summary only
    del fixed_s2_tokens

    s2_cold = load_samples(s2_dir / "phrase_epr_coldstart.jsonl", tokenizer, asap_ids, piece_to_source, args.batch_size)
    s2_end = load_samples(s2_dir / "phrase_epr_ending.jsonl", tokenizer, asap_ids, piece_to_source, args.batch_size)
    fixed_s2_target_tokens = total_tokens(s2_cold) + total_tokens(s2_end) + total_tokens(s1_main_asap)
    target_s2_non_asap_tokens = max(0, args.s2_target_tokens - fixed_s2_target_tokens)
    new_s2_main_non_asap = balance_s2_main_non_asap(
        new_s1_main_non_asap,
        keep_sources=keep_sources,
        target_tokens=target_s2_non_asap_tokens,
        seed=args.seed,
    )
    new_s2_main = s1_main_asap + new_s2_main_non_asap

    print_breakdown("Original S1 main non-ASAP", s1_main_non_asap)
    print_breakdown("New S1 main non-ASAP", new_s1_main_non_asap)
    print_breakdown("New S2 main non-ASAP", new_s2_main_non_asap)

    new_s1_total = total_tokens(s1_cold) + total_tokens(s1_end) + total_tokens(new_s1_main)
    new_s2_total = total_tokens(s2_cold) + total_tokens(s2_end) + total_tokens(new_s2_main)
    print(f"New S1 total tokens: {new_s1_total:,}")
    print(f"New S2 total tokens: {new_s2_total:,}")

    tmp_root = Path(tempfile.mkdtemp(prefix="phrase_balance_", dir=str(args.cores_root.parent)))
    try:
        tmp_s1 = tmp_root / "phrase_epr_sft_s1"
        tmp_s2 = tmp_root / "phrase_epr_sft_s2"

        write_samples(tmp_s1 / "phrase_epr_coldstart.jsonl", s1_cold)
        write_samples(tmp_s1 / "phrase_epr_ending.jsonl", s1_end)
        write_samples(tmp_s1 / "phrase_epr_main.jsonl", new_s1_main)
        write_counts_csv(tmp_s1 / "counts.csv", {
            "phrase_epr_coldstart.jsonl": total_rows(s1_cold),
            "phrase_epr_ending.jsonl": total_rows(s1_end),
            "phrase_epr_main.jsonl": total_rows(new_s1_main),
        })

        write_samples(tmp_s2 / "phrase_epr_coldstart.jsonl", s2_cold)
        write_samples(tmp_s2 / "phrase_epr_ending.jsonl", s2_end)
        write_samples(tmp_s2 / "phrase_epr_main.jsonl", new_s2_main)
        write_counts_csv(tmp_s2 / "counts.csv", {
            "phrase_epr_coldstart.jsonl": total_rows(s2_cold),
            "phrase_epr_ending.jsonl": total_rows(s2_end),
            "phrase_epr_main.jsonl": total_rows(new_s2_main),
        })

        backup_s1 = args.cores_root / "phrase_epr_sft_s1.bak_before_balance"
        backup_s2 = args.cores_root / "phrase_epr_sft_s2.bak_before_balance"
        if backup_s1.exists():
            shutil.rmtree(backup_s1)
        if backup_s2.exists():
            shutil.rmtree(backup_s2)
        shutil.move(str(s1_dir), str(backup_s1))
        shutil.move(str(s2_dir), str(backup_s2))
        shutil.move(str(tmp_s1), str(s1_dir))
        shutil.move(str(tmp_s2), str(s2_dir))

        summary = {
            "keep_sources": sorted(keep_sources),
            "s1_target_tokens": args.s1_target_tokens,
            "s2_target_tokens": args.s2_target_tokens,
            "s1_total_tokens": new_s1_total,
            "s2_total_tokens": new_s2_total,
            "s1_main_non_asap_by_source": source_summary(new_s1_main_non_asap),
            "s2_main_non_asap_by_source": source_summary(new_s2_main_non_asap),
        }
        (args.cores_root / "phrase_epr_balance_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
