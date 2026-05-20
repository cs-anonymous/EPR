#!/usr/bin/env python3
"""Build language_sft_s1 and language_sft_s2 from raw train manifests in parallel.

This generator:
1. Reads paired train rows from PianoCoReS/metadata.csv.
2. Reads unpaired score train rows from PianoCoReS/unpaired_metadata.csv.
3. Generates the 6 language tasks directly from raw aligned ABCX / compact MIDI-TSV.
4. Converts each sample to Swift chat format and filters by exact max_length=512.
5. Builds:
   - S1: all score + ~=600M performance tokens
   - S2: all score + ~=300M performance tokens
   while trying to keep ASAP performance rows whenever possible and keeping
   at least one non-ASAP row per source.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing as mp
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
S2_PERF_TARGET = 300_000_000

TOKENIZER = None
PERF_META = None


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


def score_piece_id(path: Path, aligned_root: Path) -> str:
    if path.is_relative_to(aligned_root):
        rel = path.relative_to(aligned_root).with_suffix("")
        return rel.as_posix()
    parts = path.parts
    if "unpaired_abcx" in parts and "abcx_aligned" in parts:
        idx = parts.index("abcx_aligned")
        return Path(*parts[idx + 1:]).with_suffix("").as_posix()
    return path.with_suffix("").as_posix()


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


def load_manifests(metadata_csv: Path, unpaired_csv: Path, aligned_root: Path):
    perf_meta: dict[str, dict[str, object]] = {}
    perf_files: list[Path] = []
    score_files: set[Path] = set()

    with metadata_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split") != "train":
                continue
            perf_tsv = row.get("performance_tsv_path", "")
            if perf_tsv:
                pid = performance_piece_id(perf_tsv)
                perf_meta[pid] = {
                    "source_group": row.get("performance_dataset") or row.get("capture_model") or "unknown",
                    "is_asap": row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False",
                }
                p = aligned_root / f"{pid}.tsv"
                if p.exists():
                    perf_files.append(p)
            score_path = row.get("score_abcx_path", "")
            if score_path:
                parts = list(Path(score_path).parts)
                try:
                    idx = parts.index("aligned")
                    p = aligned_root.joinpath(*parts[idx + 1:]).with_name("score_aligned.abcx")
                    if p.exists():
                        score_files.add(p)
                except ValueError:
                    pass

    with unpaired_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split") != "train":
                continue
            p = Path(row.get("abcx_aligned_path", ""))
            if p.exists():
                score_files.add(p)

    return perf_meta, sorted(score_files), sorted(set(perf_files))


def init_worker(tokenizer_path: str, perf_meta: dict[str, dict[str, object]]):
    global TOKENIZER, PERF_META
    TOKENIZER = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
    PERF_META = perf_meta


def convert_and_filter_samples(task_file: str, samples: list[dict]) -> list[FilteredRow]:
    rows: list[FilteredRow] = []
    batch_meta: list[tuple[str, str, bool, str]] = []
    batch_texts: list[str] = []
    batch_records: list[dict] = []

    def flush():
        nonlocal batch_meta, batch_texts, batch_records
        if not batch_meta:
            return
        lengths = token_lengths(TOKENIZER, batch_texts)
        for (piece_id, source_group, is_asap, raw_line), tokens in zip(batch_meta, lengths):
            if tokens <= MAX_TOKENS:
                rows.append(
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
        batch_records = []

    for sample in samples:
        converted = convert_sample(sample)
        raw = json.dumps(converted, ensure_ascii=False) + "\n"
        raw_piece_id = str(sample.get("piece_id", ""))
        piece_id = performance_piece_id(raw_piece_id) if "perf_lang" in task_file else raw_piece_id
        meta = PERF_META.get(piece_id, {})
        source_group = str(meta.get("source_group", "score")) if "perf_lang" in task_file else "score"
        is_asap = bool(meta.get("is_asap", False)) if "perf_lang" in task_file else False
        batch_meta.append((piece_id, source_group, is_asap, raw))
        batch_texts.append(render_messages(TOKENIZER, converted["messages"]))
        batch_records.append(sample)
        if len(batch_meta) >= 256:
            flush()
    flush()
    return rows


def process_score_file(args: tuple[str, str]) -> dict[str, list[FilteredRow]]:
    score_path_str, aligned_root_str = args
    score_path = Path(score_path_str)
    aligned_root = Path(aligned_root_str)

    out: dict[str, list[FilteredRow]] = {task: [] for task in SCORE_TASK_FILES}
    try:
        score_data = gll.AlignedABCXParser.parse(str(score_path))
    except Exception:
        return out
    if not score_data["measures"]:
        return out

    piece_id = score_piece_id(score_path, aligned_root)
    measure_ids = sorted(score_data["measures"].keys(), key=lambda x: int(x[1:]))

    ms_cont = []
    ms_mask = []
    for i in range(len(measure_ids) - 1):
        curr_m_id = measure_ids[i]
        target_m_id = measure_ids[i + 1]
        ms_cont.append({
            "task": "measure_score_lang_continuation",
            "header": score_data["header"],
            "input": gll.format_score_measure(curr_m_id, score_data["measures"][curr_m_id]),
            "target": gll.format_score_measure(target_m_id, score_data["measures"][target_m_id]),
            "piece_id": piece_id,
        })
        curr_content = score_data["measures"][curr_m_id]
        for m_name in ("treble", "bass"):
            masked = gll.SCORE_MASKS[m_name](curr_content, score_data["header"])
            if masked != curr_content:
                ms_mask.append({
                    "task": "measure_score_lang_mask",
                    "mask_type": m_name,
                    "header": score_data["header"],
                    "input": gll.format_score_measure(curr_m_id, masked),
                    "target": gll.format_score_measure(curr_m_id, curr_content),
                    "piece_id": piece_id,
                })
        for m_name in ("acc", "label"):
            masked = gll.SCORE_MASKS[m_name](curr_content)
            if masked != curr_content:
                ms_mask.append({
                    "task": "measure_score_lang_mask",
                    "mask_type": m_name,
                    "header": score_data["header"],
                    "input": gll.format_score_measure(curr_m_id, masked),
                    "target": gll.format_score_measure(curr_m_id, curr_content),
                    "piece_id": piece_id,
                })

    phrase_ids = sorted(score_data["phrases"].keys(), key=lambda x: int(x[1:]))
    ps_cont = []
    ps_mask = []
    for i in range(len(phrase_ids) - 1):
        curr_p_id = phrase_ids[i]
        next_p_id = phrase_ids[i + 1]
        curr_content = [
            gll.format_score_measure(m_id, score_data["measures"][m_id])
            for m_id in score_data["phrases"][curr_p_id]
            if m_id in score_data["measures"]
        ]
        next_content = [
            gll.format_score_measure(m_id, score_data["measures"][m_id])
            for m_id in score_data["phrases"][next_p_id]
            if m_id in score_data["measures"]
        ]
        if curr_content and next_content:
            ps_cont.append({
                "task": "phrase_score_lang_continuation",
                "header": score_data["header"],
                "input": gll.format_score_phrase(curr_p_id, curr_content),
                "target": gll.format_score_phrase(next_p_id, next_content),
                "piece_id": piece_id,
            })
        full_content_body = "\n".join(curr_content)
        if full_content_body:
            for m_name, m_fn in gll.SCORE_MASKS.items():
                masked = m_fn(full_content_body, score_data["header"]) if m_name in ("treble", "bass") else m_fn(full_content_body)
                if masked != full_content_body:
                    ps_mask.append({
                        "task": "phrase_score_lang_mask",
                        "mask_type": m_name,
                        "header": score_data["header"],
                        "input": f"{curr_p_id}\n{masked}",
                        "target": f"{curr_p_id}\n{full_content_body}",
                        "piece_id": piece_id,
                    })

    out["measure_score_lang_continuation.jsonl"] = convert_and_filter_samples("measure_score_lang_continuation.jsonl", ms_cont)
    out["measure_score_lang_mask.jsonl"] = convert_and_filter_samples("measure_score_lang_mask.jsonl", ms_mask)
    out["phrase_score_lang_continuation.jsonl"] = convert_and_filter_samples("phrase_score_lang_continuation.jsonl", ps_cont)
    out["phrase_score_lang_mask.jsonl"] = convert_and_filter_samples("phrase_score_lang_mask.jsonl", ps_mask)
    return out


def process_perf_file(tsv_path_str: str) -> dict[str, list[FilteredRow]]:
    tsv_path = Path(tsv_path_str)
    out: dict[str, list[FilteredRow]] = {task: [] for task in PERF_TASK_FILES}
    try:
        perf_data = gll.TSVParser.parse(str(tsv_path))
    except Exception:
        return out
    if not perf_data["measures"]:
        return out

    piece_id = performance_piece_id(tsv_path)
    measure_ids = sorted(perf_data["measures"].keys(), key=lambda x: int(x[1:]))
    cont = []
    mask = []
    rng = random.Random(stable_seed(42, piece_id))

    for i in range(len(measure_ids) - 1):
        curr_m_id = measure_ids[i]
        next_m_id = measure_ids[i + 1]
        curr_duration = perf_data["measure_durations"].get(curr_m_id, "")
        next_duration = perf_data["measure_durations"].get(next_m_id, "")
        curr_lines = perf_data["measures"][curr_m_id]
        next_lines = perf_data["measures"][next_m_id]
        cont.append({
            "task": "measure_perf_lang_continuation",
            "input": gll.format_perf_measure(curr_m_id, curr_duration, curr_lines),
            "target": gll.format_perf_measure(next_m_id, next_duration, next_lines),
            "piece_id": piece_id,
        })
        mask_name = rng.choice(list(gll.PERF_MASKS.keys()))
        masked_lines = gll.PERF_MASKS[mask_name](curr_lines)
        mask_duration = "X" if mask_name == "duration" else curr_duration
        input_text = gll.format_perf_measure(curr_m_id, mask_duration, masked_lines)
        target_text = gll.format_perf_measure(curr_m_id, curr_duration, curr_lines)
        if input_text != target_text:
            mask.append({
                "task": "measure_perf_lang_mask",
                "mask_type": mask_name,
                "input": input_text,
                "target": target_text,
                "piece_id": piece_id,
            })

    out["measure_perf_lang_continuation.jsonl"] = convert_and_filter_samples("measure_perf_lang_continuation.jsonl", cont)
    out["measure_perf_lang_mask.jsonl"] = convert_and_filter_samples("measure_perf_lang_mask.jsonl", mask)
    return out


def merge_results(results: list[dict[str, list[FilteredRow]]], task_files: list[str]) -> dict[str, list[FilteredRow]]:
    merged = {task: [] for task in task_files}
    for result in results:
        for task in task_files:
            merged[task].extend(result.get(task, []))
    return merged


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


def choose_score_rows(all_rows: dict[str, list[FilteredRow]], setting: str, seed: int) -> dict[str, list[FilteredRow]]:
    m_cont = list(all_rows.get("measure_score_lang_continuation.jsonl", []))
    p_cont = list(all_rows.get("phrase_score_lang_continuation.jsonl", []))
    m_mask = list(all_rows.get("measure_score_lang_mask.jsonl", []))
    p_mask = list(all_rows.get("phrase_score_lang_mask.jsonl", []))
    return {
        "measure_score_lang_continuation.jsonl": m_cont,
        "phrase_score_lang_continuation.jsonl": p_cont,
        "measure_score_lang_mask.jsonl": sample_rows_to_count(m_mask, len(m_cont), seed, f"{setting}:measure_score_mask"),
        "phrase_score_lang_mask.jsonl": sample_rows_to_count(p_mask, len(p_cont), seed, f"{setting}:phrase_score_mask"),
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


def write_dataset(out_dir: Path, selected_rows: dict[str, list[FilteredRow]]) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for task_file in RAW_TASK_FILES:
        rows = selected_rows.get(task_file, [])
        with (out_dir / task_file).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(row.raw_line)
        counts[task_file] = len(rows)
    with (out_dir / "counts.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples"])
        writer.writeheader()
        for task_file in RAW_TASK_FILES:
            writer.writerow({"file": task_file, "kept_samples": counts[task_file]})
    with (out_dir / "sft_language_train.jsonl").open("w", encoding="utf-8") as fout:
        for task_file in RAW_TASK_FILES:
            with (out_dir / task_file).open("r", encoding="utf-8") as fin:
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


def replace_dataset(cores_root: Path, name: str, tmp_dir: Path):
    dst = cores_root / name
    backup = cores_root / f"{name}.bak_before_rebuild"
    if backup.exists() or backup.is_symlink():
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup)
        else:
            backup.unlink()
    if dst.exists() or dst.is_symlink():
        shutil.move(str(dst), str(backup))
    shutil.move(str(tmp_dir), str(dst))


def main():
    global MAX_TOKENS
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("PianoCoReS/metadata.csv"))
    parser.add_argument("--unpaired-metadata", type=Path, default=Path("PianoCoReS/unpaired_metadata.csv"))
    parser.add_argument("--aligned-root", type=Path, default=Path("PianoCoReS/aligned"))
    parser.add_argument("--cores-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=max(1, min(32, (mp.cpu_count() or 8) - 2)))
    args = parser.parse_args()
    MAX_TOKENS = args.max_tokens

    perf_meta, score_files, perf_files = load_manifests(args.metadata, args.unpaired_metadata, args.aligned_root)
    print(f"train score files: {len(score_files):,}")
    print(f"train perf files: {len(perf_files):,}")
    print(f"workers: {args.workers}")
    print(f"max_tokens: {MAX_TOKENS}")

    with mp.Pool(
        processes=args.workers,
        initializer=init_worker,
        initargs=(str(args.tokenizer), perf_meta),
    ) as pool:
        score_results = list(pool.imap_unordered(
            process_score_file,
            [(str(path), str(args.aligned_root)) for path in score_files],
            chunksize=8,
        ))
        perf_results = list(pool.imap_unordered(
            process_perf_file,
            [str(path) for path in perf_files],
            chunksize=16,
        ))

    filtered_rows = merge_results(score_results, SCORE_TASK_FILES)
    perf_filtered = merge_results(perf_results, PERF_TASK_FILES)
    filtered_rows.update(perf_filtered)

    for task_file in RAW_TASK_FILES:
        print(f"filtered {task_file}: rows={len(filtered_rows[task_file]):,}, tokens={total_tokens(filtered_rows[task_file]):,}")

    perf_filtered_total = sum(len(filtered_rows[task_file]) for task_file in PERF_TASK_FILES)
    if perf_files and perf_filtered_total == 0:
        raise RuntimeError(
            "Performance language filtering produced 0 rows. Refusing to replace language_sft_s1/language_sft_s2 with broken datasets."
        )

    s1_rows = {}
    s1_rows.update(choose_score_rows(filtered_rows, "s1", args.seed))
    s1_perf_rows = {task: filtered_rows[task] for task in PERF_TASK_FILES}
    s1_perf_targets = allocate_perf_targets(s1_perf_rows, S1_PERF_TARGET)
    for task_file in PERF_TASK_FILES:
        s1_rows[task_file] = sample_perf_task(s1_perf_rows[task_file], s1_perf_targets[task_file], args.seed, f"s1:{task_file}")
    s1_summary = summarize(s1_rows)
    print("\nS1 summary:")
    print(json.dumps(s1_summary, ensure_ascii=False, indent=2))

    s2_rows = {}
    s2_rows.update(choose_score_rows(filtered_rows, "s2", args.seed))
    s2_perf_rows = {task: filtered_rows[task] for task in PERF_TASK_FILES}
    s2_perf_targets = allocate_perf_targets(s2_perf_rows, S2_PERF_TARGET)
    for task_file in PERF_TASK_FILES:
        s2_rows[task_file] = sample_perf_task(s2_perf_rows[task_file], s2_perf_targets[task_file], args.seed, f"s2:{task_file}")
    s2_summary = summarize(s2_rows)
    print("\nS2 summary:")
    print(json.dumps(s2_summary, ensure_ascii=False, indent=2))

    tmp_s1 = args.cores_root / ".language_sft_s1_parallel_tmp"
    tmp_s2 = args.cores_root / ".language_sft_s2_parallel_tmp"
    for p in [tmp_s1, tmp_s2]:
        if p.exists():
            shutil.rmtree(p)
    s1_counts = write_dataset(tmp_s1, s1_rows)
    s2_counts = write_dataset(tmp_s2, s2_rows)
    replace_dataset(args.cores_root, "language_sft_s1", tmp_s1)
    replace_dataset(args.cores_root, "language_sft_s2", tmp_s2)

    (args.cores_root / "language_sft_s1_summary.json").write_text(
        json.dumps({"max_tokens": MAX_TOKENS, "counts": s1_counts, "summary": s1_summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.cores_root / "language_sft_s2_summary.json").write_text(
        json.dumps({"max_tokens": MAX_TOKENS, "counts": s2_counts, "summary": s2_summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
