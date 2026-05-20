#!/usr/bin/env python3
"""Build phrase-aware Language CPT chunks for CoReS.

Rules:
  - max text length is 2048 tokenizer tokens.
  - aligned ABCX chunks repeat the score header.
  - aligned ABCX and MIDI-TSV chunks use phrase boundaries.
  - oversized MIDI-TSV phrases are split inside the phrase by measure/event.
  - markdown chunks use heading/block boundaries and avoid cutting code fences.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from transformers import AutoTokenizer


MAX_TOKENS = 2048
HEADING_RE = re.compile(r"^#{1,6}\s+")


def elapsed(start: float) -> str:
    return f"{time.time() - start:.1f}s"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ["B", "K", "M", "G", "T"]:
        if value < 1024 or unit == "T":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{num_bytes}B"


def score_path_from_metadata(value: str) -> Path | None:
    if not value or value == "nan":
        return None
    if value.startswith("PianoCoRe/score/"):
        rel = value.removeprefix("PianoCoRe/score/").removesuffix("/score.abcx")
        return Path("PianoCoReS/aligned") / rel / "score_aligned.abcx"
    return Path(value)


def perf_path_from_metadata(value: str) -> Path | None:
    if not value or value == "nan":
        return None
    if value.startswith("PianoCoRe_output/"):
        return Path("PianoCoReS/aligned") / value.removeprefix("PianoCoRe_output/")
    if value.startswith("PianoCoRe/aligned/"):
        return Path("PianoCoReS/aligned") / value.removeprefix("PianoCoRe/aligned/")
    return Path(value)


def unique_metadata_paths(metadata_path: Path) -> tuple[list[Path], list[Path]]:
    score_paths = []
    perf_paths = []
    seen_scores = set()
    seen_perfs = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            score_path = score_path_from_metadata(row.get("score_abcx_path", ""))
            if score_path and score_path.exists() and score_path not in seen_scores:
                seen_scores.add(score_path)
                score_paths.append(score_path)

            perf_path = perf_path_from_metadata(row.get("performance_tsv_path", ""))
            if perf_path and perf_path.exists() and perf_path not in seen_perfs:
                seen_perfs.add(perf_path)
                perf_paths.append(perf_path)
    return score_paths, perf_paths


def score_paths_from_score_metadata(score_metadata_path: Path) -> list[Path]:
    paths = []
    seen = set()
    with score_metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split") not in ("", "train"):
                continue
            for key in ("score_aligned_path", "score_abcx_path"):
                value = row.get(key, "")
                if not value:
                    continue
                path = Path(value)
                if path.exists() and path not in seen:
                    seen.add(path)
                    paths.append(path)
                break
    return paths


class TokenCounter:
    def __init__(self, tokenizer_path: Path):
        self.tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path), trust_remote_code=True)

    def count(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])

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


def is_phrase_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.fullmatch(r"H\d+:?\d*", stripped))


def split_header_body_abcx(lines: list[str]) -> tuple[list[str], list[str]]:
    header = []
    body = []
    in_header = True
    for line in lines:
        if in_header:
            header.append(line)
            if line.startswith("K:"):
                in_header = False
        else:
            body.append(line)
    return header, body


def phrase_groups(lines: list[str]) -> list[list[str]]:
    groups = []
    current = []
    for line in lines:
        if is_phrase_line(line):
            if current:
                groups.append(current)
            current = [line]
        elif current:
            current.append(line)
        elif line.strip():
            current = [line]
    if current:
        groups.append(current)
    return groups


def pack_units(
    prefix: str,
    units: list[str],
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int]]:
    chunks: list[tuple[str, int]] = []
    current: list[str] = []

    def make_text(parts: list[str]) -> str:
        body = "\n".join(part.rstrip() for part in parts if part.strip()).rstrip()
        return f"{prefix.rstrip()}\n{body}".rstrip() if prefix else body

    current_tokens = 0
    for unit in units:
        candidate_parts = current + [unit]
        candidate = make_text(candidate_parts)
        candidate_tokens = counter.count(candidate)
        if current and candidate_tokens > max_tokens:
            text = make_text(current)
            chunks.append((text, current_tokens))
            current = [unit]
            current_text = make_text(current)
            current_tokens = counter.count(current_text)
        else:
            current = candidate_parts
            current_tokens = candidate_tokens

    if current:
        text = make_text(current)
        chunks.append((text, current_tokens))
    return chunks


def split_long_measure_line(
    prefix: str,
    h_line: str,
    measure_line: str,
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int]]:
    parts = measure_line.split()
    if not parts:
        text = f"{prefix.rstrip()}\n{h_line}\n{measure_line}".rstrip() if prefix else f"{h_line}\n{measure_line}"
        return [(text, counter.count(text))]

    marker = parts[0]
    events = parts[1:]
    chunks = []
    current_events: list[str] = []

    def make_text(evts: list[str]) -> str:
        line = " ".join([marker, *evts]).rstrip()
        body = f"{h_line}\n{line}".rstrip()
        return f"{prefix.rstrip()}\n{body}".rstrip() if prefix else body

    for event in events:
        candidate = make_text(current_events + [event])
        if current_events and counter.count(candidate) > max_tokens:
            text = make_text(current_events)
            chunks.append((text, counter.count(text)))
            current_events = [event]
        else:
            current_events.append(event)

    if current_events:
        text = make_text(current_events)
        chunks.append((text, counter.count(text)))
    elif not events:
        text = make_text([])
        chunks.append((text, counter.count(text)))
    return chunks


def split_oversized_phrase(
    prefix: str,
    phrase: str,
    counter: TokenCounter,
    max_tokens: int,
    split_events: bool,
) -> list[tuple[str, int]]:
    lines = phrase.splitlines()
    if not lines:
        return []

    h_line = lines[0]
    measure_lines = lines[1:] or []
    chunks: list[tuple[str, int]] = []
    current_measures: list[str] = []

    def make_text(measures: list[str]) -> str:
        body = "\n".join([h_line, *measures]).rstrip()
        return f"{prefix.rstrip()}\n{body}".rstrip() if prefix else body

    for measure in measure_lines:
        candidate = make_text(current_measures + [measure])
        if current_measures and counter.count(candidate) > max_tokens:
            text = make_text(current_measures)
            chunks.append((text, counter.count(text)))
            current_measures = [measure]
        else:
            current_measures.append(measure)

        single = make_text([measure])
        if counter.count(single) > max_tokens:
            if current_measures == [measure]:
                current_measures = []
            if split_events:
                chunks.extend(split_long_measure_line(prefix, h_line, measure, counter, max_tokens))
            else:
                chunks.append((single, counter.count(single)))

    if current_measures:
        text = make_text(current_measures)
        chunks.append((text, counter.count(text)))

    if not measure_lines:
        text = make_text([])
        chunks.append((text, counter.count(text)))

    return chunks


def chunk_abcx(path: Path, counter: TokenCounter, max_tokens: int) -> list[tuple[str, int]]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    header, body = split_header_body_abcx(raw_lines)
    header_text = "\n".join(header).rstrip()
    units = ["\n".join(group).rstrip() for group in phrase_groups(body)]

    chunks = []
    for text, tokens in pack_units(header_text, units, counter, max_tokens):
        if tokens <= max_tokens:
            chunks.append((text, tokens))
        else:
            # Rare fallback: split a very long phrase by measure/event boundaries.
            body_text = text.removeprefix(header_text).lstrip("\n")
            chunks.extend(split_oversized_phrase(header_text, body_text, counter, max_tokens, split_events=True))
    return chunks


def chunk_midi_tsv(path: Path, counter: TokenCounter, max_tokens: int) -> list[tuple[str, int]]:
    lines = [
        line.rstrip("\n")
        for line in path.open("r", encoding="utf-8")
        if line.strip() and not line.startswith("#")
    ]
    units = ["\n".join(group).rstrip() for group in phrase_groups(lines)]

    chunks = []
    for text, tokens in pack_units("", units, counter, max_tokens):
        if tokens <= max_tokens:
            chunks.append((text, tokens))
        else:
            # MIDI phrases may be longer than max length; split inside phrase.
            chunks.extend(split_oversized_phrase("", text, counter, max_tokens, split_events=True))
    return chunks


def markdown_units(text: str) -> list[str]:
    lines = text.splitlines()
    units = []
    current = []
    for line in lines:
        if HEADING_RE.match(line) and current:
            units.append("\n".join(current).rstrip())
            current = [line]
        else:
            current.append(line)
    if current:
        units.append("\n".join(current).rstrip())
    return [unit for unit in units if unit.strip()]


def markdown_blocks(section: str) -> list[str]:
    lines = section.splitlines()
    blocks = []
    current = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            current.append(line)
            in_fence = not in_fence
            if not in_fence:
                blocks.append("\n".join(current).rstrip())
                current = []
            continue
        if in_fence:
            current.append(line)
            continue
        if not line.strip():
            if current:
                blocks.append("\n".join(current).rstrip())
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).rstrip())
    return [block for block in blocks if block.strip()]


def chunk_markdown(path: Path, counter: TokenCounter, max_tokens: int) -> list[tuple[str, int]]:
    units = markdown_units(path.read_text(encoding="utf-8"))
    chunks = []
    for unit in units:
        tokens = counter.count(unit)
        if tokens <= max_tokens:
            chunks.append((unit, tokens))
            continue
        # Oversized section: split by paragraphs/tables/code blocks.
        blocks = markdown_blocks(unit)
        chunks.extend(pack_units("", blocks, counter, max_tokens))
    return chunks


def force_split_to_limit(text: str, counter: TokenCounter, max_tokens: int) -> list[tuple[str, int]]:
    if counter.count(text) <= max_tokens:
        return [(text, counter.count(text))]

    chunks: list[tuple[str, int]] = []
    current: list[str] = []

    def flush_current() -> None:
        nonlocal current
        if current:
            out = "\n".join(current).rstrip()
            chunks.append((out, counter.count(out)))
            current = []

    for line in text.splitlines():
        candidate = "\n".join([*current, line]).rstrip()
        if current and counter.count(candidate) > max_tokens:
            flush_current()

        if counter.count(line) <= max_tokens:
            current.append(line)
            continue

        words = line.split()
        word_run: list[str] = []
        for word in words:
            word_candidate = " ".join([*word_run, word]).rstrip()
            if word_run and counter.count(word_candidate) > max_tokens:
                flush_current()
                out = " ".join(word_run).rstrip()
                chunks.append((out, counter.count(out)))
                word_run = [word]
            else:
                word_run.append(word)
        if word_run:
            flush_current()
            out = " ".join(word_run).rstrip()
            chunks.append((out, counter.count(out)))

    flush_current()
    return chunks


def write_record(handle, corpus_type: str, source: Path, chunk_id: int, text: str) -> None:
    handle.write(json.dumps({
        "task": "language_cpt",
        "corpus_type": corpus_type,
        "source": str(source),
        "chunk_id": chunk_id,
        "text": text,
    }, ensure_ascii=False) + "\n")


def build_corpus(
    name: str,
    paths: list[Path],
    output_path: Path,
    chunker,
    counter: TokenCounter,
    max_tokens: int,
) -> dict:
    start = time.time()
    samples = 0
    all_tokens = 0
    all_chars = 0
    max_seen = 0
    over_limit = 0

    with output_path.open("w", encoding="utf-8") as fout:
        for path_index, path in enumerate(paths, 1):
            chunks = chunker(path, counter, max_tokens)
            chunk_id = 0
            for text, tokens in chunks:
                for final_text, final_tokens in force_split_to_limit(text, counter, max_tokens):
                    chunk_id += 1
                    write_record(fout, name, path, chunk_id, final_text)
                    samples += 1
                    all_tokens += final_tokens
                    all_chars += len(final_text)
                    max_seen = max(max_seen, final_tokens)
                    if final_tokens > max_tokens:
                        over_limit += 1
            if path_index % 5000 == 0:
                print(
                    f"  {name}: files={path_index:,}/{len(paths):,}, "
                    f"chunks={samples:,}, max_tokens={max_seen}, {elapsed(start)}",
                    flush=True,
                )

    return {
        "corpus_type": name,
        "file": str(output_path),
        "source_files": len(paths),
        "samples": samples,
        "bytes": output_path.stat().st_size,
        "size": human_size(output_path.stat().st_size),
        "all_tokens": all_tokens,
        "avg_token": all_tokens / samples if samples else 0.0,
        "all_chars": all_chars,
        "avg_chars": all_chars / samples if samples else 0.0,
        "max_tokens": max_seen,
        "over_limit": over_limit,
    }


def write_summary(out_dir: Path, rows: list[dict]) -> None:
    csv_path = out_dir / "cpt_dataset_summary.csv"
    fieldnames = [
        "corpus_type",
        "samples",
        "size",
        "bytes",
        "source_files",
        "all_tokens",
        "avg_token",
        "all_chars",
        "avg_chars",
        "max_tokens",
        "over_limit",
        "file",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "avg_token": f"{row['avg_token']:.2f}",
                "avg_chars": f"{row['avg_chars']:.2f}",
            })

    json_path = out_dir / "cpt_dataset_summary.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--score-metadata", type=Path, default=None)
    parser.add_argument("--knowledge-dir", type=Path, default=Path("PianoCoReS/knowledge"))
    parser.add_argument("--out-dir", type=Path, default=Path("PianoCoReS/CoReS/language_cpt"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B"))
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--work-dir", type=Path, default=Path("PianoCoReS/.tmp_language_cpt"))
    args = parser.parse_args()

    start = time.time()
    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="language_cpt_", dir=str(args.work_dir)))

    try:
        counter = TokenCounter(args.tokenizer)
        metadata_score_paths, perf_paths = unique_metadata_paths(args.metadata)
        if args.score_metadata is not None:
            score_paths = score_paths_from_score_metadata(args.score_metadata)
        else:
            score_paths = metadata_score_paths
        knowledge_paths = sorted(args.knowledge_dir.glob("*.md"))
        print(f"Score files: {len(score_paths):,}")
        print(f"Performance TSV files: {len(perf_paths):,}")
        print(f"Knowledge markdown files: {len(knowledge_paths):,}")

        rows = [
            build_corpus(
                "aligned_abcx",
                score_paths,
                temp_dir / "aligned_abcx.jsonl",
                chunk_abcx,
                counter,
                args.max_tokens,
            ),
            build_corpus(
                "midi_tsv_no_header",
                perf_paths,
                temp_dir / "midi_tsv_no_header.jsonl",
                chunk_midi_tsv,
                counter,
                args.max_tokens,
            ),
            build_corpus(
                "knowledge_markdown",
                knowledge_paths,
                temp_dir / "knowledge_markdown.jsonl",
                chunk_markdown,
                counter,
                args.max_tokens,
            ),
        ]
        write_summary(temp_dir, rows)

        if args.out_dir.exists():
            shutil.rmtree(args.out_dir)
        args.out_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_dir), str(args.out_dir))
        for row in rows:
            row["file"] = str(args.out_dir / Path(row["file"]).name)
        write_summary(args.out_dir, rows)
    finally:
        shutil.rmtree(args.work_dir, ignore_errors=True)

    print(f"Wrote {args.out_dir}")
    print(f"Done in {elapsed(start)}")


if __name__ == "__main__":
    main()
