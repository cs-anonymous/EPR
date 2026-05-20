#!/usr/bin/env python3
"""Build sampled Language CPT subsets for CPT-S4/S2/S1.

The base corpus is expected to be produced by ``build_language_cpt_chunks.py``:

  - aligned_abcx.jsonl
  - knowledge_markdown.jsonl
  - midi_tsv_no_header.jsonl

Policy:
  - ABCX keeps every base record and oversamples by fixed repeat counts.
  - Knowledge is first expanded to at least 100k tokens, then every expanded
    record is kept and oversampled to the target token budgets.
  - MIDI-TSV is heavily sampled.  All ASAP records are kept.  Non-ASAP records
    are sampled by source file with at least one chunk per source file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from transformers import AutoTokenizer


SETTINGS = {
    "CPT-S4": {
        "dir": "language_cpt_s4",
        "abcx_repeat_min": 3,
        "abcx_repeat_max": 3,
        "abcx_target_min": 0,
        "abcx_target_max": 999_000_000,
        "knowledge_target": 300_000,
        "midi_ratio": 0.125,
        "total_range": "150M-200M",
        "total_target": 175_000_000,
    },
    "CPT-S2": {
        "dir": "language_cpt_s2",
        "abcx_repeat_min": 1,
        "abcx_repeat_max": 1,
        "abcx_target_min": 20_000_000,
        "abcx_target_max": 30_000_000,
        "knowledge_target": 450_000,
        "midi_ratio": 0.25,
        "total_range": "300M-350M",
        "total_target": 325_000_000,
    },
    "CPT-S1": {
        "dir": "language_cpt_s1",
        "abcx_repeat_min": 1,
        "abcx_repeat_max": 1,
        "abcx_target_min": 30_000_000,
        "abcx_target_max": 40_000_000,
        "knowledge_target": 600_000,
        "midi_ratio": 0.50,
        "total_range": "600M-650M",
        "total_target": 625_000_000,
    },
}

KNOWLEDGE_CARD_TYPES = [
    (
        "Operational rule",
        "State the rule as a direct modelling constraint. Preserve the exact "
        "format names and symbol meanings from the source note.",
    ),
    (
        "Common failure mode",
        "Describe mistakes a language model should avoid when applying this "
        "knowledge to ABCX, compact MIDI-TSV, or score-to-performance text.",
    ),
    (
        "Validation checklist",
        "Turn the note into a compact checklist for verifying generated text.",
    ),
    (
        "Rendering heuristic",
        "Explain how the note should influence timing, duration, velocity, "
        "pedal, phrase grouping, or serialization choices.",
    ),
    (
        "Boundary case",
        "Explain how to handle edge cases without breaking the surrounding "
        "phrase, measure, or event sequence.",
    ),
    (
        "Negative example guidance",
        "Describe what an invalid or musically implausible output would look "
        "like, while keeping the original rule in view.",
    ),
    (
        "Source-target alignment note",
        "Relate the source-side representation to the target-side compact "
        "performance representation.",
    ),
    (
        "Short memory card",
        "Condense the note into a reusable memory card for CPT training.",
    ),
]


@dataclass(frozen=True)
class RecordMeta:
    index: int
    source: str
    source_group: str
    is_asap: bool
    tokens: int


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


def perf_path_from_metadata(value: str) -> Path | None:
    if not value or value == "nan":
        return None
    if value.startswith("PianoCoRe_output/"):
        return Path("PianoCoReS/aligned") / value.removeprefix("PianoCoRe_output/")
    if value.startswith("PianoCoRe/aligned/"):
        return Path("PianoCoReS/aligned") / value.removeprefix("PianoCoRe/aligned/")
    return Path(value)


def is_asap_row(row: dict[str, str]) -> bool:
    return row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False"


def load_performance_metadata(metadata_path: Path) -> dict[str, dict[str, str | bool]]:
    info = {}
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = perf_path_from_metadata(row.get("performance_tsv_path", ""))
            if path is None:
                continue
            source = str(path)
            info[source] = {
                "source_group": row.get("performance_dataset") or row.get("capture_model") or "unknown",
                "is_asap": is_asap_row(row),
            }
    return info


class TokenCounter:
    def __init__(self, tokenizer_path: Path):
        self.tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path), trust_remote_code=True)

    def count_many(self, texts: list[str]) -> list[int]:
        if not texts:
            return []
        encoded = self.tokenizer(
            texts,
            add_special_tokens=False,
            truncation=False,
            padding=False,
            return_attention_mask=False,
        )
        return [len(ids) for ids in encoded["input_ids"]]


def file_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def record_to_json(record: RecordMeta) -> dict:
    return {
        "index": record.index,
        "source": record.source,
        "source_group": record.source_group,
        "is_asap": record.is_asap,
        "tokens": record.tokens,
    }


def record_from_json(row: dict) -> RecordMeta:
    return RecordMeta(
        index=int(row["index"]),
        source=str(row["source"]),
        source_group=str(row["source_group"]),
        is_asap=bool(row["is_asap"]),
        tokens=int(row["tokens"]),
    )


def load_record_cache(cache_path: Path, expected_meta: dict) -> list[RecordMeta] | None:
    if not cache_path.exists():
        return None
    with cache_path.open("r", encoding="utf-8") as f:
        first = f.readline()
        if not first:
            return None
        header = json.loads(first)
        if header.get("_cache") != expected_meta:
            return None
        return [record_from_json(json.loads(line)) for line in f if line.strip()]


def save_record_cache(cache_path: Path, cache_meta: dict, records: list[RecordMeta]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"_cache": cache_meta}, ensure_ascii=False) + "\n")
        for record in records:
            f.write(json.dumps(record_to_json(record), ensure_ascii=False) + "\n")
    tmp_path.replace(cache_path)


def read_jsonl(path: Path) -> Iterable[tuple[int, dict, str]]:
    with path.open("r", encoding="utf-8") as f:
        for index, line in enumerate(f):
            if not line.strip():
                continue
            yield index, json.loads(line), line


def text_of(row: dict) -> str:
    return str(row.get("text", ""))


def count_jsonl_tokens(
    path: Path,
    counter: TokenCounter,
    batch_size: int,
    perf_info: dict[str, dict[str, str | bool]] | None = None,
    cache_path: Path | None = None,
    cache_meta: dict | None = None,
) -> list[RecordMeta]:
    if cache_path is not None and cache_meta is not None:
        cached = load_record_cache(cache_path, cache_meta)
        if cached is not None:
            print(f"  loaded token index cache: {cache_path} ({len(cached):,} records)", flush=True)
            return cached

    start = time.time()
    records: list[RecordMeta] = []
    pending: list[tuple[int, str, str, bool, str]] = []

    def flush() -> None:
        if not pending:
            return
        lengths = counter.count_many([item[4] for item in pending])
        for (index, source, source_group, is_asap, _), tokens in zip(pending, lengths):
            records.append(RecordMeta(index, source, source_group, is_asap, tokens))
        pending.clear()
        if len(records) % 100_000 < batch_size:
            print(f"  indexed {path.name}: {len(records):,} records ({elapsed(start)})", flush=True)

    for index, row, _ in read_jsonl(path):
        source = str(row.get("source", ""))
        if perf_info is not None:
            meta = perf_info.get(source, {})
            source_group = str(meta.get("source_group", "unknown"))
            is_asap = bool(meta.get("is_asap", False))
        else:
            source_group = str(row.get("corpus_type", "unknown"))
            is_asap = False
        pending.append((index, source, source_group, is_asap, text_of(row)))
        if len(pending) >= batch_size:
            flush()
    flush()
    if cache_path is not None and cache_meta is not None:
        save_record_cache(cache_path, cache_meta, records)
        print(f"  saved token index cache: {cache_path}", flush=True)
    return records


def total_tokens(records: Iterable[RecordMeta]) -> int:
    return sum(record.tokens for record in records)


def repeat_plan(records: list[RecordMeta], repeats: int) -> tuple[list[int], int]:
    indices = [record.index for record in records] * repeats
    return indices, total_tokens(records) * repeats


def choose_repeat_count(records: list[RecordMeta], cfg: dict) -> tuple[int, int]:
    base_tokens = total_tokens(records)
    repeat_min = int(cfg["abcx_repeat_min"])
    repeat_max = int(cfg["abcx_repeat_max"])
    target_min = int(cfg["abcx_target_min"])
    target_max = int(cfg["abcx_target_max"])
    candidates = []
    for repeats in range(repeat_min, repeat_max + 1):
        tokens = base_tokens * repeats
        if target_min <= tokens <= target_max:
            return repeats, tokens
        if tokens < target_min:
            distance = target_min - tokens
        else:
            distance = tokens - target_max
        candidates.append((distance, repeats, tokens))
    _, repeats, tokens = min(candidates)
    return repeats, tokens


def cycle_to_token_target(records: list[RecordMeta], target_tokens: int) -> tuple[list[int], int]:
    if not records:
        return [], 0
    indices: list[int] = []
    tokens = 0
    while tokens < target_tokens:
        for record in records:
            indices.append(record.index)
            tokens += record.tokens
            if tokens >= target_tokens:
                break
    return indices, tokens


def select_midi_records(records: list[RecordMeta], ratio: float, seed: int, setting: str) -> tuple[set[int], dict]:
    rng = random.Random(stable_seed(seed, setting, "midi"))
    all_tokens = total_tokens(records)
    target_tokens = round(all_tokens * ratio)
    asap = [record for record in records if record.is_asap]
    non_asap = [record for record in records if not record.is_asap]

    selected: set[int] = {record.index for record in asap}
    selected_tokens = total_tokens(asap)

    by_source: dict[str, list[RecordMeta]] = defaultdict(list)
    for record in non_asap:
        by_source[record.source].append(record)

    source_names = list(by_source)
    rng.shuffle(source_names)

    remaining_by_source: dict[str, list[RecordMeta]] = {}
    min_one_tokens = 0
    for source in source_names:
        rows = by_source[source]
        rng.shuffle(rows)
        first, rest = rows[0], rows[1:]
        selected.add(first.index)
        selected_tokens += first.tokens
        min_one_tokens += first.tokens
        if rest:
            remaining_by_source[source] = rest

    # Source-balanced round-robin fill until the ratio target is reached.
    active = [source for source in source_names if source in remaining_by_source]
    while active and selected_tokens < target_tokens:
        rng.shuffle(active)
        next_active = []
        for source in active:
            rows = remaining_by_source[source]
            if not rows:
                continue
            row = rows.pop()
            selected.add(row.index)
            selected_tokens += row.tokens
            if rows:
                next_active.append(source)
            if selected_tokens >= target_tokens:
                next_active.extend(s for s in active if s != source and remaining_by_source.get(s))
                break
        active = next_active

    selected_asap = sum(1 for record in asap if record.index in selected)
    selected_non_asap = len(selected) - selected_asap
    return selected, {
        "target_tokens": target_tokens,
        "selected_tokens": selected_tokens,
        "all_tokens": all_tokens,
        "ratio": ratio,
        "asap_records_total": len(asap),
        "asap_tokens_total": total_tokens(asap),
        "asap_records_kept": selected_asap,
        "non_asap_records_total": len(non_asap),
        "non_asap_records_kept": selected_non_asap,
        "non_asap_sources_total": len(by_source),
        "min_one_non_asap_source_tokens": min_one_tokens,
        "selected_records": len(selected),
    }


def select_midi_records_to_token_target(
    records: list[RecordMeta],
    target_tokens: int,
    seed: int,
    setting: str,
    reference_ratio: float,
) -> tuple[set[int], dict]:
    rng = random.Random(stable_seed(seed, setting, "midi_target"))
    all_tokens = total_tokens(records)
    target_tokens = max(0, min(target_tokens, all_tokens))
    asap = [record for record in records if record.is_asap]
    non_asap = [record for record in records if not record.is_asap]

    selected: set[int] = {record.index for record in asap}
    selected_tokens = total_tokens(asap)

    by_source: dict[str, list[RecordMeta]] = defaultdict(list)
    for record in non_asap:
        by_source[record.source_group].append(record)

    source_names = list(by_source)
    rng.shuffle(source_names)

    remaining_by_source: dict[str, list[RecordMeta]] = {}
    min_one_tokens = 0
    for source in source_names:
        rows = by_source[source]
        rng.shuffle(rows)
        rows.sort(key=lambda record: record.tokens)
        first, rest = rows[0], rows[1:]
        if first.index not in selected:
            selected.add(first.index)
            selected_tokens += first.tokens
            min_one_tokens += first.tokens
        if rest:
            remaining_by_source[source] = rest

    active = [source for source in source_names if source in remaining_by_source]
    while active and selected_tokens < target_tokens:
        rng.shuffle(active)
        next_active = []
        for source in active:
            rows = remaining_by_source[source]
            if not rows:
                continue
            row = rows.pop(0)
            if selected_tokens + row.tokens <= target_tokens or selected_tokens < target_tokens * 0.995:
                selected.add(row.index)
                selected_tokens += row.tokens
            if rows:
                next_active.append(source)
            if selected_tokens >= target_tokens:
                next_active.extend(s for s in active if s != source and remaining_by_source.get(s))
                break
        active = next_active

    selected_asap = sum(1 for record in asap if record.index in selected)
    selected_non_asap = len(selected) - selected_asap
    return selected, {
        "target_tokens": target_tokens,
        "selected_tokens": selected_tokens,
        "all_tokens": all_tokens,
        "ratio": selected_tokens / all_tokens if all_tokens else 0.0,
        "reference_ratio": reference_ratio,
        "asap_records_total": len(asap),
        "asap_tokens_total": total_tokens(asap),
        "asap_records_kept": selected_asap,
        "non_asap_records_total": len(non_asap),
        "non_asap_records_kept": selected_non_asap,
        "non_asap_sources_total": len(by_source),
        "min_one_non_asap_source_tokens": min_one_tokens,
        "selected_records": len(selected),
    }


def write_repeated_by_indices(input_path: Path, output_path: Path, ordered_indices: list[int], plan_only: bool) -> int:
    if plan_only:
        return 0
    lines = [line for _, _, line in read_jsonl(input_path)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fout:
        for index in ordered_indices:
            fout.write(lines[index])
    return output_path.stat().st_size


def write_selected_set(input_path: Path, output_path: Path, selected: set[int], plan_only: bool) -> int:
    if plan_only:
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        for index, line in enumerate(fin):
            if index in selected:
                fout.write(line)
    return output_path.stat().st_size


def make_knowledge_card(base: dict, base_id: int, card_id: int, card_type: str, instruction: str) -> dict:
    source = base.get("source", "")
    chunk_id = base.get("chunk_id", "")
    text = str(base.get("text", "")).strip()
    return {
        "task": "language_cpt",
        "corpus_type": "knowledge_markdown",
        "source": f"knowledge_augmented::{source}",
        "chunk_id": f"{base_id}.{card_id}",
        "text": (
            f"# Knowledge Card: {card_type}\n\n"
            f"Source note: `{source}` chunk `{chunk_id}`.\n\n"
            f"{instruction}\n\n"
            "Reference material:\n\n"
            f"{text}\n\n"
            "Training reminder: preserve syntax exactly when the note refers to "
            "ABCX symbols, compact MIDI-TSV event fields, phrase labels, measure "
            "labels, dynamics, pedal events, or timing units."
        ),
    }


def build_expanded_knowledge(
    base_path: Path,
    output_path: Path,
    counter: TokenCounter,
    min_tokens: int,
    batch_size: int,
) -> tuple[list[RecordMeta], dict]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_rows = [row for _, row, _ in read_jsonl(base_path)]
    rows = list(base_rows)

    def count_rows(items: list[dict]) -> int:
        total = 0
        for start in range(0, len(items), batch_size):
            total += sum(counter.count_many([text_of(row) for row in items[start:start + batch_size]]))
        return total

    tokens = count_rows(rows)
    cycle = 0
    while tokens < min_tokens:
        for base_id, base in enumerate(base_rows, 1):
            card_type, instruction = KNOWLEDGE_CARD_TYPES[cycle % len(KNOWLEDGE_CARD_TYPES)]
            rows.append(make_knowledge_card(base, base_id, cycle + 1, card_type, instruction))
            if len(rows) % batch_size == 0:
                tokens = count_rows(rows)
                if tokens >= min_tokens:
                    break
        cycle += 1
        if cycle > 10_000:
            raise RuntimeError("Knowledge expansion did not converge")
        if len(rows) % batch_size != 0:
            tokens = count_rows(rows)

    with output_path.open("w", encoding="utf-8") as fout:
        for row in rows:
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")

    records = count_jsonl_tokens(output_path, counter, batch_size)
    return records, {
        "base_records": len(base_rows),
        "expanded_records": len(rows),
        "expanded_tokens": total_tokens(records),
        "file": str(output_path),
        "bytes": output_path.stat().st_size,
        "size": human_size(output_path.stat().st_size),
    }


def write_summary(out_root: Path, summary: dict) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "language_cpt_sampling_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_path = out_root / "language_cpt_sampling_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "setting",
            "total_tokens",
            "abcx_tokens",
            "abcx_repeats",
            "knowledge_tokens",
            "knowledge_target",
            "midi_tokens",
            "midi_ratio",
            "midi_records",
            "note",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for setting, row in summary["settings"].items():
            writer.writerow({
                "setting": setting,
                "total_tokens": row["total_tokens"],
                "abcx_tokens": row["abcx"]["tokens"],
                "abcx_repeats": row["abcx"]["repeats"],
                "knowledge_tokens": row["knowledge"]["tokens"],
                "knowledge_target": row["knowledge"]["target_tokens"],
                "midi_tokens": row["midi"]["selected_tokens"],
                "midi_ratio": row["midi"]["ratio"],
                "midi_records": row["midi"]["selected_records"],
                "note": row["target_total_range"],
            })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, default=Path("PianoCoReS/CoReS/language_cpt"))
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--out-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--knowledge-min-tokens", type=int, default=100_000)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--work-dir", type=Path, default=Path("PianoCoReS/.tmp_language_cpt_subsets"))
    parser.add_argument("--setting", action="append", choices=sorted(SETTINGS))
    args = parser.parse_args()

    start = time.time()
    base_abcx = args.base_dir / "aligned_abcx.jsonl"
    base_midi = args.base_dir / "midi_tsv_no_header.jsonl"
    base_knowledge = args.base_dir / "knowledge_markdown.jsonl"
    for path in [base_abcx, base_midi, base_knowledge, args.metadata]:
        if not path.exists():
            raise FileNotFoundError(path)

    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="language_cpt_subsets_", dir=str(args.work_dir)))

    try:
        print("Loading tokenizer...")
        counter = TokenCounter(args.tokenizer)

        print("Expanding knowledge...")
        expanded_knowledge_path = temp_dir / "knowledge_markdown_expanded_100k.jsonl"
        knowledge_records, knowledge_expansion = build_expanded_knowledge(
            base_knowledge,
            expanded_knowledge_path,
            counter,
            args.knowledge_min_tokens,
            args.batch_size,
        )

        args.out_root.mkdir(parents=True, exist_ok=True)
        cache_common = {
            "tokenizer": str(args.tokenizer),
            "metadata": file_fingerprint(args.metadata),
        }

        print("Indexing ABCX...")
        abcx_records = count_jsonl_tokens(
            base_abcx,
            counter,
            args.batch_size,
            cache_path=args.out_root / "language_cpt_abcx_token_index.jsonl",
            cache_meta={**cache_common, "corpus": "aligned_abcx", "file": file_fingerprint(base_abcx)},
        )
        print("Indexing MIDI-TSV...")
        perf_info = load_performance_metadata(args.metadata)
        midi_records = count_jsonl_tokens(
            base_midi,
            counter,
            args.batch_size,
            perf_info,
            cache_path=args.out_root / "language_cpt_midi_token_index.jsonl",
            cache_meta={**cache_common, "corpus": "midi_tsv_no_header", "file": file_fingerprint(base_midi)},
        )

        final_knowledge_base = args.out_root / "language_cpt_knowledge_expanded_100k.jsonl"
        if not args.plan_only:
            shutil.copy2(expanded_knowledge_path, final_knowledge_base)

        summary = {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "plan_only": args.plan_only,
            "base_dir": str(args.base_dir),
            "metadata": str(args.metadata),
            "knowledge_expansion": {
                **knowledge_expansion,
                "file": str(final_knowledge_base),
            },
            "base_tokens": {
                "aligned_abcx": total_tokens(abcx_records),
                "knowledge_markdown_expanded": total_tokens(knowledge_records),
                "midi_tsv_no_header": total_tokens(midi_records),
            },
            "settings": {},
        }

        settings = args.setting or list(SETTINGS)
        for setting in settings:
            cfg = SETTINGS[setting]
            print(f"\nPlanning {setting}...")
            final_setting_dir = args.out_root / cfg["dir"]
            setting_dir = temp_dir / cfg["dir"] if not args.plan_only else final_setting_dir
            if not args.plan_only:
                if setting_dir.exists():
                    shutil.rmtree(setting_dir)
                setting_dir.mkdir(parents=True, exist_ok=True)

            abcx_repeats, _ = choose_repeat_count(abcx_records, cfg)
            abcx_indices, abcx_tokens = repeat_plan(abcx_records, abcx_repeats)
            knowledge_indices, knowledge_tokens = cycle_to_token_target(
                knowledge_records,
                cfg["knowledge_target"],
            )
            midi_target_tokens = int(cfg["total_target"]) - abcx_tokens - knowledge_tokens
            midi_selected, midi_stats = select_midi_records_to_token_target(
                midi_records,
                midi_target_tokens,
                args.seed,
                setting,
                cfg["midi_ratio"],
            )

            abcx_bytes = write_repeated_by_indices(
                base_abcx,
                setting_dir / "aligned_abcx.jsonl",
                abcx_indices,
                args.plan_only,
            )
            knowledge_bytes = write_repeated_by_indices(
                expanded_knowledge_path,
                setting_dir / "knowledge_markdown.jsonl",
                knowledge_indices,
                args.plan_only,
            )
            midi_bytes = write_selected_set(
                base_midi,
                setting_dir / "midi_tsv_no_header.jsonl",
                midi_selected,
                args.plan_only,
            )

            total = abcx_tokens + knowledge_tokens + midi_stats["selected_tokens"]
            summary["settings"][setting] = {
                "directory": str(final_setting_dir),
                "target_total_range": cfg["total_range"],
                "total_tokens": total,
                "abcx": {
                    "tokens": abcx_tokens,
                    "repeats": abcx_repeats,
                    "target_tokens_min": cfg["abcx_target_min"],
                    "target_tokens_max": cfg["abcx_target_max"],
                    "records": len(abcx_indices),
                    "bytes": abcx_bytes,
                    "size": human_size(abcx_bytes) if abcx_bytes else "plan-only",
                },
                "knowledge": {
                    "tokens": knowledge_tokens,
                    "target_tokens": cfg["knowledge_target"],
                    "records": len(knowledge_indices),
                    "bytes": knowledge_bytes,
                    "size": human_size(knowledge_bytes) if knowledge_bytes else "plan-only",
                },
                "midi": {
                    **midi_stats,
                    "records": len(midi_selected),
                    "bytes": midi_bytes,
                    "size": human_size(midi_bytes) if midi_bytes else "plan-only",
                },
            }
            if not args.plan_only:
                (setting_dir / "manifest.json").write_text(
                    json.dumps(summary["settings"][setting], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                if final_setting_dir.exists():
                    shutil.rmtree(final_setting_dir)
                shutil.move(str(setting_dir), str(final_setting_dir))
            print(
                f"  total={total/1_000_000:.1f}M, "
                f"ABCX={abcx_tokens/1_000_000:.1f}M, "
                f"knowledge={knowledge_tokens/1_000_000:.2f}M, "
                f"MIDI={midi_stats['selected_tokens']/1_000_000:.1f}M",
                flush=True,
            )

        write_summary(args.out_root, summary)
    finally:
        shutil.rmtree(args.work_dir, ignore_errors=True)

    print(f"\nWrote {args.out_root}")
    print(f"Done in {elapsed(start)}")


if __name__ == "__main__":
    main()
