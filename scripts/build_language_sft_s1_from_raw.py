#!/usr/bin/env python3
"""Build language_sft_s1 directly from raw train manifests.

Source of truth:
- PianoCoReS/metadata.csv (paired train rows)
- PianoCoReS/unpaired_metadata.csv (unpaired score train rows)

Generation path:
1. Read train manifests.
2. Generate 6 language tasks directly from raw aligned ABCX / MIDI-TSV.
3. Convert to Swift chat format.
4. Filter by exact chat-template token length (max_length=512).
5. Keep all score tasks after filtering, with mask ~= continuation count.
6. Sample performance tasks to target ~600M tokens while keeping ASAP rows
   whenever possible and at least one row per non-ASAP source.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_language_learning_data as gll
from prepare_core_s1_swift import convert_sample


RAW_TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]

SCORE_TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
]

PERF_TASK_FILES = [
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]

MAX_TOKENS = 512
S1_PERF_TARGET = 600_000_000


@dataclass
class FilteredRow:
    raw_line: str
    task_file: str
    piece_id: str
    source_group: str
    is_asap: bool
    tokens: int


def stable_seed(seed: int, *parts: str) -> int:
    text = ":".join([str(seed), *parts])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def performance_piece_id(perf_tsv_path: str) -> str:
    path = Path(str(perf_tsv_path))
    parts = path.parts
    if "aligned" in parts:
        idx = parts.index("aligned")
        path_str = Path(*parts[idx + 1:]).as_posix()
    elif "orphan_tsv" in parts:
        idx = parts.index("orphan_tsv")
        path_str = Path(*parts[idx + 1:]).as_posix()
    else:
        path_str = str(perf_tsv_path)
    if path_str.endswith(".tsv"):
        path_str = path_str[:-4]
    return path_str


def score_piece_id_from_aligned_path(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    return rel.as_posix()


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


def load_train_manifests(metadata_csv: Path, unpaired_csv: Path, aligned_root: Path) -> tuple[dict[str, dict[str, object]], list[Path]]:
    perf_meta: dict[str, dict[str, object]] = {}
    paired_score_files: set[Path] = set()

    with metadata_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split") != "train":
                continue
            perf_tsv = row.get("performance_tsv_path", "")
            if perf_tsv:
                perf_id = performance_piece_id(perf_tsv)
                perf_meta[perf_id] = {
                    "source_group": row.get("performance_dataset") or row.get("capture_model") or "unknown",
                    "is_asap": row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False",
                }
            score_path = row.get("score_abcx_path", "")
            if score_path:
                score_rel = Path(score_path)
                if score_rel.name == "score.abcx":
                    parts = list(score_rel.parts)
                    try:
                        idx = parts.index("aligned")
                        candidate = aligned_root.joinpath(*parts[idx + 1:]).with_name("score_aligned.abcx")
                        if candidate.exists():
                            paired_score_files.add(candidate)
                    except ValueError:
                        pass

    unpaired_score_files: list[Path] = []
    with unpaired_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split") != "train":
                continue
            aligned_path = row.get("abcx_aligned_path", "")
            if aligned_path:
                p = Path(aligned_path)
                if p.exists():
                    unpaired_score_files.append(p)

    all_scores = sorted(paired_score_files | set(unpaired_score_files))
    return perf_meta, all_scores


def generate_raw_language_tasks(
    metadata_csv: Path,
    unpaired_csv: Path,
    aligned_root: Path,
    tmp_root: Path,
) -> dict[str, Path]:
    perf_meta, score_files = load_train_manifests(metadata_csv, unpaired_csv, aligned_root)
    perf_files = []
    for piece_id in perf_meta:
        p = aligned_root / f"{piece_id}.tsv"
        if p.exists():
            perf_files.append(p)
    perf_files = sorted(perf_files)

    tmp_root.mkdir(parents=True, exist_ok=True)
    measure_dir = tmp_root / "measure-based"
    phrase_dir = tmp_root / "phrase-based"
    measure_dir.mkdir(parents=True, exist_ok=True)
    phrase_dir.mkdir(parents=True, exist_ok=True)

    score_valid_dirs = set()
    for score_path in score_files:
        try:
            rel_parts = tuple(score_path.relative_to(aligned_root).parts[:-1])
            score_valid_dirs.add(rel_parts)
        except Exception:
            continue

    ms = gll.MeasureScoreLangGenerator(score_files, str(tmp_root), max_samples_per_piece=None, valid_abcx_dirs=score_valid_dirs, allow_orphan=True)
    ps = gll.PhraseScoreLangGenerator(score_files, str(tmp_root), max_samples_per_piece=None, valid_abcx_dirs=score_valid_dirs, allow_orphan=True)
    # perf_files are already selected by the train manifest, so do not re-filter
    # them with the legacy performance_id-based check inside the generator.
    mp = gll.MeasurePerfLangGenerator(perf_files, str(tmp_root), max_samples_per_piece=None, valid_perf_ids=set())

    ms.generate()
    ps.generate()
    mp.generate()

    return {
        "measure_score_lang_continuation.jsonl": measure_dir / "measure_score_lang_continuation.jsonl",
        "measure_score_lang_mask.jsonl": measure_dir / "measure_score_lang_mask.jsonl",
        "phrase_score_lang_continuation.jsonl": phrase_dir / "phrase_score_lang_continuation.jsonl",
        "phrase_score_lang_mask.jsonl": phrase_dir / "phrase_score_lang_mask.jsonl",
        "measure_perf_lang_continuation.jsonl": measure_dir / "measure_perf_lang_continuation.jsonl",
        "measure_perf_lang_mask.jsonl": measure_dir / "measure_perf_lang_mask.jsonl",
    }


def convert_and_filter_task(
    tokenizer,
    input_path: Path,
    output_path: Path,
    perf_meta: dict[str, dict[str, object]],
    batch_size: int,
) -> list[FilteredRow]:
    task_file = input_path.name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    kept_rows: list[FilteredRow] = []
    batch_meta: list[tuple[str, str, bool, str]] = []
    batch_texts: list[str] = []

    with input_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        def flush() -> None:
            nonlocal batch_meta, batch_texts
            if not batch_meta:
                return
            lengths = token_lengths(tokenizer, batch_texts)
            for (piece_id, source_group, is_asap, raw_line), tokens in zip(batch_meta, lengths):
                if tokens <= MAX_TOKENS:
                    fout.write(raw_line)
                    kept_rows.append(
                        FilteredRow(
                            raw_line=raw_line,
                            task_file=task_file,
                            piece_id=piece_id,
                            source_group=source_group,
                            is_asap=is_asap,
                            tokens=tokens,
                        )
                    )
            batch_meta = []
            batch_texts = []

        for line in fin:
            if not line.strip():
                continue
            sample = json.loads(line)
            converted = convert_sample(sample)
            raw = json.dumps(converted, ensure_ascii=False) + "\n"
            raw_piece_id = str(sample.get("piece_id", ""))
            piece_id = performance_piece_id(raw_piece_id) if "perf_lang" in task_file else raw_piece_id
            meta = perf_meta.get(piece_id, {})
            source_group = str(meta.get("source_group", "score")) if "perf_lang" in task_file else "score"
            is_asap = bool(meta.get("is_asap", False)) if "perf_lang" in task_file else False
            batch_meta.append((piece_id, source_group, is_asap, raw))
            batch_texts.append(render_messages(tokenizer, converted["messages"]))
            if len(batch_meta) >= batch_size:
                flush()
        flush()
    return kept_rows


def total_tokens(rows: list[FilteredRow]) -> int:
    return sum(row.tokens for row in rows)


def sample_rows_to_count(rows: list[FilteredRow], target_count: int, seed: int, label: str) -> list[FilteredRow]:
    if target_count >= len(rows):
        return list(rows)
    if target_count <= 0:
        return []
    rng = random.Random(stable_seed(seed, label, "count"))
    pool = list(rows)
    rng.shuffle(pool)
    pool.sort(key=lambda row: row.tokens)
    return pool[:target_count]


def choose_score_rows(all_rows: dict[str, list[FilteredRow]], seed: int) -> dict[str, list[FilteredRow]]:
    m_cont = list(all_rows.get("measure_score_lang_continuation.jsonl", []))
    p_cont = list(all_rows.get("phrase_score_lang_continuation.jsonl", []))
    m_mask = list(all_rows.get("measure_score_lang_mask.jsonl", []))
    p_mask = list(all_rows.get("phrase_score_lang_mask.jsonl", []))
    return {
        "measure_score_lang_continuation.jsonl": m_cont,
        "phrase_score_lang_continuation.jsonl": p_cont,
        "measure_score_lang_mask.jsonl": sample_rows_to_count(m_mask, len(m_cont), seed, "s1:measure_score_mask"),
        "phrase_score_lang_mask.jsonl": sample_rows_to_count(p_mask, len(p_cont), seed, "s1:phrase_score_mask"),
    }


def allocate_perf_targets(perf_rows: dict[str, list[FilteredRow]], total_target_tokens: int) -> dict[str, int]:
    totals = {task_file: total_tokens(rows) for task_file, rows in perf_rows.items()}
    total_perf_tokens = sum(totals.values())
    if total_perf_tokens == 0:
        return {task_file: 0 for task_file in perf_rows}
    tasks = list(perf_rows)
    targets = {}
    assigned = 0
    for task_file in tasks[:-1]:
        part = round(total_target_tokens * totals[task_file] / total_perf_tokens)
        targets[task_file] = part
        assigned += part
    targets[tasks[-1]] = max(0, total_target_tokens - assigned)
    return targets


def sample_perf_task(rows: list[FilteredRow], target_tokens: int, seed: int, label: str) -> list[FilteredRow]:
    if target_tokens <= 0 or not rows:
        return []
    rng = random.Random(stable_seed(seed, label, "perf"))
    asap = [row for row in rows if row.is_asap]
    non_asap = [row for row in rows if not row.is_asap]

    selected: list[FilteredRow] = []
    used = 0

    asap_sorted = sorted(asap, key=lambda row: row.tokens)
    for row in asap_sorted:
        if used + row.tokens <= target_tokens:
            selected.append(row)
            used += row.tokens

    if used >= target_tokens:
        return selected

    by_source: dict[str, list[FilteredRow]] = defaultdict(list)
    for row in non_asap:
        by_source[row.source_group].append(row)

    source_names = list(by_source)
    rng.shuffle(source_names)
    remaining_by_source: dict[str, deque[FilteredRow]] = {}
    for source in source_names:
        pool = list(by_source[source])
        rng.shuffle(pool)
        pool = deque(sorted(pool, key=lambda row: row.tokens))
        first = pool.popleft()
        if used + first.tokens <= target_tokens:
            selected.append(first)
            used += first.tokens
        if pool:
            remaining_by_source[source] = pool

    active = [source for source in source_names if source in remaining_by_source]
    while active and used < target_tokens:
        rng.shuffle(active)
        next_active = []
        for source in active:
            pool = remaining_by_source[source]
            if not pool:
                continue
            row = pool.popleft()
            if used + row.tokens <= target_tokens:
                selected.append(row)
                used += row.tokens
            if pool:
                next_active.append(source)
            if used >= target_tokens:
                break
        active = next_active
    return selected


def write_task_dir(output_dir: Path, selected_rows: dict[str, list[FilteredRow]]) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for task_file in RAW_TASK_FILES:
        rows = selected_rows.get(task_file, [])
        with (output_dir / task_file).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(row.raw_line)
        counts[task_file] = len(rows)
    with (output_dir / "counts.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples"])
        writer.writeheader()
        for task_file in RAW_TASK_FILES:
            writer.writerow({"file": task_file, "kept_samples": counts[task_file]})
    with (output_dir / "sft_language_train.jsonl").open("w", encoding="utf-8") as fout:
        for task_file in RAW_TASK_FILES:
            with (output_dir / task_file).open("r", encoding="utf-8") as fin:
                for line in fin:
                    if line.strip():
                        fout.write(line)
    return counts


def summarize(selected_rows: dict[str, list[FilteredRow]]) -> dict[str, int]:
    score_tokens = sum(total_tokens(rows) for task, rows in selected_rows.items() if "score_lang" in task)
    perf_tokens = sum(total_tokens(rows) for task, rows in selected_rows.items() if "perf_lang" in task)
    score_rows = sum(len(rows) for task, rows in selected_rows.items() if "score_lang" in task)
    perf_rows = sum(len(rows) for task, rows in selected_rows.items() if "perf_lang" in task)
    return {
        "score_rows": score_rows,
        "perf_rows": perf_rows,
        "score_tokens": score_tokens,
        "perf_tokens": perf_tokens,
        "total_rows": score_rows + perf_rows,
        "total_tokens": score_tokens + perf_tokens,
    }


def main() -> None:
    global MAX_TOKENS
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoReS/metadata.csv"))
    parser.add_argument("--unpaired-metadata", type=Path, default=Path("PianoCoReS/unpaired_metadata.csv"))
    parser.add_argument("--aligned-root", type=Path, default=Path("PianoCoReS/aligned"))
    parser.add_argument("--cores-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    MAX_TOKENS = args.max_tokens

    raw_tmp = args.cores_root / ".language_s1_raw_tmp"
    filtered_tmp = args.cores_root / ".language_s1_filtered_tmp"
    final_tmp = args.cores_root / ".language_sft_s1_tmp"
    for path in [raw_tmp, filtered_tmp, final_tmp]:
        if path.exists():
            shutil.rmtree(path)

    perf_meta, _ = load_train_manifests(args.metadata, args.unpaired_metadata, args.aligned_root)
    generated = generate_raw_language_tasks(args.metadata, args.unpaired_metadata, args.aligned_root, raw_tmp)

    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), trust_remote_code=True)

    filtered_rows: dict[str, list[FilteredRow]] = {}
    for task_file in RAW_TASK_FILES:
        filtered_rows[task_file] = convert_and_filter_task(
            tokenizer=tokenizer,
            input_path=generated[task_file],
            output_path=filtered_tmp / task_file,
            perf_meta=perf_meta,
            batch_size=args.batch_size,
        )
        print(
            f"filtered {task_file}: rows={len(filtered_rows[task_file]):,}, tokens={total_tokens(filtered_rows[task_file]):,}",
            flush=True,
        )

    perf_filtered_total = sum(len(filtered_rows[task_file]) for task_file in PERF_TASK_FILES)
    if perf_files and perf_filtered_total == 0:
        raise RuntimeError(
            "Performance language filtering produced 0 rows. Refusing to replace language_sft_s1 with a broken dataset."
        )

    selected: dict[str, list[FilteredRow]] = {}
    selected.update(choose_score_rows(filtered_rows, args.seed))

    perf_rows = {task_file: filtered_rows[task_file] for task_file in PERF_TASK_FILES}
    perf_targets = allocate_perf_targets(perf_rows, S1_PERF_TARGET)
    for task_file in PERF_TASK_FILES:
        selected[task_file] = sample_perf_task(perf_rows[task_file], perf_targets[task_file], args.seed, f"s1:{task_file}")

    summary = summarize(selected)
    print("\nS1 summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    counts = write_task_dir(final_tmp, selected)
    (args.cores_root / "language_sft_s1_summary.json").write_text(
        json.dumps({"max_tokens": MAX_TOKENS, "counts": counts, "summary": summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    dst = args.cores_root / "language_sft_s1"
    backup = args.cores_root / "language_sft_s1.bak_before_rebuild"
    if backup.exists() or backup.is_symlink():
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup)
        else:
            backup.unlink()
    if dst.exists() or dst.is_symlink():
        shutil.move(str(dst), str(backup))
    shutil.move(str(final_tmp), str(dst))
    shutil.rmtree(raw_tmp, ignore_errors=True)
    shutil.rmtree(filtered_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
