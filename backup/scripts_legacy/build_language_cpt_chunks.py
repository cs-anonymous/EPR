#!/usr/bin/env python3
"""Build phrase-aware Language CPT chunks for CoReS.

Rules:
  - max text length is 1536 tokenizer tokens.
  - aligned ABCX chunks repeat the score header.
  - aligned ABCX and MIDI-TSV chunks use phrase boundaries.
  - oversized MIDI-TSV phrases are split inside the phrase by measure/event.
  - markdown chunks use heading/block boundaries, avoid cutting code fences,
    and are packed within each source file.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from transformers import AutoTokenizer

try:
    from lm_midi_tsv import lm_midi_tsv_to_tokens
except ImportError:
    from scripts.lm_midi_tsv import lm_midi_tsv_to_tokens


MAX_TOKENS = 1536
HEADING_RE = re.compile(r"^#{1,6}\s+")
SourceItem = tuple[Path, str]
_WORKER_COUNTER: TokenCounter | None = None


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
        return Path("data/aligned") / rel / "score_aligned.abcx"
    return Path(value)


def perf_path_from_metadata(value: str) -> Path | None:
    if not value or value == "nan":
        return None
    if value.startswith("PianoCoRe_output/"):
        return Path("data/aligned") / value.removeprefix("PianoCoRe_output/")
    if value.startswith("PianoCoRe/aligned/"):
        return Path("data/aligned") / value.removeprefix("PianoCoRe/aligned/")
    return Path(value)


def remap_to_miditsv_root(path: Path, miditsv_root: Path | None) -> Path:
    if miditsv_root is None:
        return path
    parts = path.parts
    try:
        idx = parts.index("aligned")
    except ValueError:
        return path
    candidate = Path(*parts[:idx], miditsv_root.name, *parts[idx + 1 :])
    return candidate if candidate.exists() else path


def source_split(value: str | None) -> str:
    return value if value else "unspecified"


def unique_metadata_paths(
    metadata_path: Path,
    miditsv_root: Path | None = None,
) -> tuple[list[SourceItem], list[SourceItem]]:
    score_paths = []
    perf_paths = []
    seen_scores = set()
    seen_perfs = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            split = source_split(row.get("split"))
            score_path = score_path_from_metadata(row.get("score_abcx_path", ""))
            if score_path and score_path.exists() and score_path not in seen_scores:
                seen_scores.add(score_path)
                score_paths.append((score_path, split))

            perf_path = perf_path_from_metadata(row.get("performance_tsv_path", ""))
            if perf_path:
                perf_path = remap_to_miditsv_root(perf_path, miditsv_root)
            if perf_path and perf_path.exists() and perf_path not in seen_perfs:
                seen_perfs.add(perf_path)
                perf_paths.append((perf_path, split))
    return score_paths, perf_paths


def score_paths_from_score_metadata(score_metadata_path: Path) -> list[SourceItem]:
    paths = []
    seen = set()
    with score_metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            split = source_split(row.get("split"))
            for key in ("score_aligned_path", "score_abcx_path"):
                value = row.get(key, "")
                if not value:
                    continue
                path = Path(value)
                if path.exists() and path not in seen:
                    seen.add(path)
                    paths.append((path, split))
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
    return (
        stripped.startswith("H\t")
        or bool(re.match(r"^H\d+\t", stripped))
        or bool(re.fullmatch(r"H\d+:?\d*", stripped))
    )


def is_midi_measure_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("M\t") or bool(re.match(r"^M\d+\t", stripped))


def normalize_midi_tsv_line(line: str) -> str:
    parts = line.rstrip("\n").split("\t")
    if len(parts) == 4 and re.fullmatch(r"H\d+", parts[0]):
        parts[0] = "H"
        return "\t".join(parts)
    if len(parts) == 4 and re.fullmatch(r"M\d+", parts[0]):
        parts[0] = "M"
        return "\t".join(parts)
    return line


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


def pack_midi_token_units(
    units: list[str],
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int]]:
    chunks: list[tuple[str, int]] = []
    current: list[str] = []

    def make_text(parts: list[str]) -> str:
        body = "".join(parts).rstrip()
        return f"<MIDI>{body}</MIDI>"

    current_tokens = 0
    for unit in units:
        candidate_parts = current + [unit]
        candidate = make_text(candidate_parts)
        candidate_tokens = counter.count(candidate)
        if current and candidate_tokens > max_tokens:
            text = make_text(current)
            chunks.append((text, current_tokens))
            current = [unit]
            current_tokens = counter.count(make_text(current))
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


def split_oversized_midi_phrase(
    phrase: str,
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int]]:
    lines = phrase.splitlines()
    if not lines:
        return []

    h_line = lines[0]
    measures = midi_measure_groups(lines[1:])
    chunks: list[tuple[str, int]] = []
    current_measures: list[list[str]] = []

    def make_text(measure_groups: list[list[str]]) -> str:
        body_lines = [line for group in measure_groups for line in group]
        tsv_text = "\n".join([h_line, *body_lines]).rstrip()
        return lm_midi_tsv_to_tokens(tsv_text, wrap=True, pretty=False)

    for measure in measures:
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
            chunks.extend(split_long_midi_measure(h_line, measure, counter, max_tokens))

    if current_measures:
        text = make_text(current_measures)
        chunks.append((text, counter.count(text)))

    if not measures:
        text = make_text([])
        chunks.append((text, counter.count(text)))

    return chunks


def split_long_midi_measure(
    h_line: str,
    measure_lines: list[str],
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int]]:
    chunks: list[tuple[str, int]] = []
    current_events: list[str] = []
    measure_header = measure_lines[0]
    events = measure_lines[1:]

    def make_text(events: list[str]) -> str:
        tsv_text = "\n".join([h_line, measure_header, *events]).rstrip()
        return lm_midi_tsv_to_tokens(tsv_text, wrap=True, pretty=False)

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
    else:
        text = make_text([])
        chunks.append((text, counter.count(text)))
    return chunks


def midi_measure_groups(lines: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if is_midi_measure_line(line):
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
        normalize_midi_tsv_line(line.rstrip("\n"))
        for line in path.open("r", encoding="utf-8")
        if line.strip() and not line.startswith("#")
    ]
    units = ["\n".join(group).rstrip() for group in phrase_groups(lines)]
    chunks = []
    current: list[str] = []

    def make_text(parts: list[str]) -> str:
        return f"<MIDI>{''.join(parts)}</MIDI>"

    def flush_current() -> None:
        nonlocal current
        if current:
            text = make_text(current)
            chunks.append((text, counter.count(text)))
            current = []

    for unit in units:
        if not unit.strip():
            continue
        token_unit = lm_midi_tsv_to_tokens(unit, wrap=False, pretty=False)
        candidate = make_text([*current, token_unit])
        if current and counter.count(candidate) > max_tokens:
            flush_current()

        single = make_text([token_unit])
        if counter.count(single) > max_tokens:
            flush_current()
            chunks.extend(split_oversized_midi_phrase(unit, counter, max_tokens))
        else:
            current.append(token_unit)

    flush_current()
    return chunks


def markdown_units(text: str) -> list[str]:
    lines = text.splitlines()
    units = []
    current = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            if not in_fence and HEADING_RE.match(line) and current:
                units.append("\n".join(current).rstrip())
                current = [line]
            else:
                current.append(line)
            in_fence = not in_fence
            continue
        if not in_fence and HEADING_RE.match(line) and current:
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
            if not in_fence and current:
                blocks.append("\n".join(current).rstrip())
                current = []
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


def split_markdown_fence_block(block: str, counter: TokenCounter, max_tokens: int) -> list[tuple[str, int]]:
    lines = block.splitlines()
    if len(lines) < 2 or not lines[0].strip().startswith("```") or not lines[-1].strip().startswith("```"):
        return [(block, counter.count(block))]

    open_fence = lines[0]
    close_fence = lines[-1]
    body_lines = lines[1:-1]
    chunks: list[tuple[str, int]] = []
    current: list[str] = []

    def make_text(parts: list[str]) -> str:
        if parts:
            return "\n".join([open_fence, *parts, close_fence]).rstrip()
        return "\n".join([open_fence, close_fence]).rstrip()

    for line in body_lines:
        candidate = make_text([*current, line])
        if current and counter.count(candidate) > max_tokens:
            text = make_text(current)
            chunks.append((text, counter.count(text)))
            current = [line]
        else:
            current.append(line)

        single = make_text([line])
        if counter.count(single) > max_tokens:
            if current == [line]:
                current = []
            chunks.extend(force_split_markdown_fence_line(open_fence, close_fence, line, counter, max_tokens))

    if current:
        text = make_text(current)
        chunks.append((text, counter.count(text)))

    if not body_lines:
        text = make_text([])
        chunks.append((text, counter.count(text)))

    return chunks


def force_split_markdown_fence_line(
    open_fence: str,
    close_fence: str,
    line: str,
    counter: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int]]:
    chunks: list[tuple[str, int]] = []
    words = line.split()
    if not words:
        text = "\n".join([open_fence, line, close_fence]).rstrip()
        return [(text, counter.count(text))]

    current: list[str] = []

    def split_long_fragment(fragment: str) -> list[tuple[str, int]]:
        outputs: list[tuple[str, int]] = []
        start = 0
        while start < len(fragment):
            low = start + 1
            high = len(fragment)
            best_end = start
            best_tokens = 0

            while low <= high:
                end = (low + high) // 2
                part = fragment[start:end]
                part_text = "\n".join([open_fence, part, close_fence]).rstrip()
                part_tokens = counter.count(part_text)
                if part_tokens <= max_tokens:
                    best_end = end
                    best_tokens = part_tokens
                    low = end + 1
                else:
                    high = end - 1

            if best_end == start:
                best_end = start + 1
                best_tokens = counter.count("\n".join([open_fence, fragment[start:best_end], close_fence]).rstrip())

            outputs.append((
                "\n".join([open_fence, fragment[start:best_end], close_fence]).rstrip(),
                best_tokens,
            ))
            start = best_end
        return outputs

    def make_text(parts: list[str]) -> str:
        body = " ".join(parts).rstrip()
        return "\n".join([open_fence, body, close_fence]).rstrip()

    for word in words:
        single_word = make_text([word])
        if counter.count(single_word) > max_tokens:
            if current:
                text = make_text(current)
                chunks.append((text, counter.count(text)))
                current = []
            chunks.extend(split_long_fragment(word))
            continue

        candidate = make_text([*current, word])
        if current and counter.count(candidate) > max_tokens:
            text = make_text(current)
            chunks.append((text, counter.count(text)))
            current = [word]
        else:
            current.append(word)

    if current:
        text = make_text(current)
        chunks.append((text, counter.count(text)))
    return chunks


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
        for text, tokens in pack_units("", blocks, counter, max_tokens):
            if tokens <= max_tokens:
                chunks.append((text, tokens))
                continue
            if text.strip().startswith("```") and text.strip().endswith("```"):
                chunks.extend(split_markdown_fence_block(text, counter, max_tokens))
            else:
                chunks.extend(force_split_to_limit(text, counter, max_tokens))
    return chunks


def pack_text_chunks(
    chunks: list[tuple[str, int]],
    counter: TokenCounter,
    max_tokens: int,
    separator: str = "\n\n",
) -> list[tuple[str, int]]:
    packed: list[tuple[str, int]] = []
    current_text = ""
    current_tokens = 0

    for text, tokens in chunks:
        if not text.strip():
            continue
        if not current_text:
            current_text = text
            current_tokens = tokens if tokens else counter.count(text)
            continue

        candidate = f"{current_text}{separator}{text}"
        candidate_tokens = counter.count(candidate)
        if candidate_tokens <= max_tokens:
            current_text = candidate
            current_tokens = candidate_tokens
            continue

        packed.append((current_text, current_tokens))
        current_text = text
        current_tokens = tokens if tokens else counter.count(text)

    if current_text:
        packed.append((current_text, current_tokens))
    return packed


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

    def split_long_fragment(fragment: str) -> list[tuple[str, int]]:
        """Split a no-whitespace fragment using the tokenizer count as the limit."""
        outputs: list[tuple[str, int]] = []
        start = 0
        while start < len(fragment):
            low = start + 1
            high = len(fragment)
            best_end = start
            best_tokens = 0

            while low <= high:
                end = (low + high) // 2
                part = fragment[start:end]
                part_tokens = counter.count(part)
                if part_tokens <= max_tokens:
                    best_end = end
                    best_tokens = part_tokens
                    low = end + 1
                else:
                    high = end - 1

            if best_end == start:
                best_end = start + 1
                best_tokens = counter.count(fragment[start:best_end])

            outputs.append((fragment[start:best_end], best_tokens))
            start = best_end
        return outputs

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
            if counter.count(word) > max_tokens:
                if word_run:
                    out = " ".join(word_run).rstrip()
                    chunks.append((out, counter.count(out)))
                    word_run = []
                chunks.extend(split_long_fragment(word))
                continue

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


def write_record(handle, corpus_type: str, source: Path, source_split_name: str, chunk_id: int, text: str) -> None:
    handle.write(json.dumps({
        "task": "language_cpt",
        "corpus_type": corpus_type,
        "source": str(source),
        "source_split": source_split_name,
        "chunk_id": chunk_id,
        "text": text,
    }, ensure_ascii=False) + "\n")


def init_worker(tokenizer_path: str) -> None:
    global _WORKER_COUNTER
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    _WORKER_COUNTER = TokenCounter(Path(tokenizer_path))


def process_source(task: tuple[str, str, str, str, int]) -> dict:
    corpus_type, chunker_name, path_str, split, max_tokens = task
    if _WORKER_COUNTER is None:
        raise RuntimeError("worker tokenizer is not initialized")
    path = Path(path_str)
    chunker = {
        "abcx": chunk_abcx,
        "midi": chunk_midi_tsv,
        "markdown": chunk_markdown,
    }[chunker_name]
    records = []
    chunk_id = 0
    chunks = chunker(path, _WORKER_COUNTER, max_tokens)
    if chunker_name == "markdown":
        final_chunks = pack_text_chunks(chunks, _WORKER_COUNTER, max_tokens)
        for final_text, final_tokens in final_chunks:
            chunk_id += 1
            records.append((chunk_id, final_text, final_tokens, len(final_text), final_tokens > max_tokens))
    else:
        for text, _tokens in chunks:
            final_chunks = force_split_to_limit(text, _WORKER_COUNTER, max_tokens)
            for final_text, final_tokens in final_chunks:
                chunk_id += 1
                records.append((chunk_id, final_text, final_tokens, len(final_text), final_tokens > max_tokens))
    return {
        "corpus_type": corpus_type,
        "source": path_str,
        "source_split": split,
        "records": records,
    }


def write_processed_source(fout, result: dict) -> dict:
    samples = 0
    all_tokens = 0
    all_chars = 0
    max_seen = 0
    over_limit = 0
    path = Path(result["source"])
    split = result["source_split"]
    for chunk_id, text, tokens, chars, is_over_limit in result["records"]:
        write_record(fout, result["corpus_type"], path, split, chunk_id, text)
        samples += 1
        all_tokens += tokens
        all_chars += chars
        max_seen = max(max_seen, tokens)
        over_limit += int(is_over_limit)
    return {
        "samples": samples,
        "all_tokens": all_tokens,
        "all_chars": all_chars,
        "max_tokens": max_seen,
        "over_limit": over_limit,
        "source_split": split,
    }


def build_corpus(
    name: str,
    items: list[SourceItem],
    output_path: Path,
    chunker_name: str,
    tokenizer_path: Path,
    max_tokens: int,
    workers: int,
) -> dict:
    start = time.time()
    samples = 0
    all_tokens = 0
    all_chars = 0
    max_seen = 0
    over_limit = 0
    split_counts: dict[str, int] = {}

    with output_path.open("w", encoding="utf-8") as fout:
        tasks = [
            (name, chunker_name, str(path), split, max_tokens)
            for path, split in items
        ]
        if workers <= 1:
            init_worker(str(tokenizer_path))
            results_iter = map(process_source, tasks)
        else:
            executor = ProcessPoolExecutor(
                max_workers=workers,
                initializer=init_worker,
                initargs=(str(tokenizer_path),),
            )
            results_iter = executor.map(process_source, tasks, chunksize=8)

        try:
            for path_index, result in enumerate(results_iter, 1):
                source_stats = write_processed_source(fout, result)
                samples += source_stats["samples"]
                all_tokens += source_stats["all_tokens"]
                all_chars += source_stats["all_chars"]
                max_seen = max(max_seen, source_stats["max_tokens"])
                over_limit += source_stats["over_limit"]
                split = source_stats["source_split"]
                split_counts[split] = split_counts.get(split, 0) + 1
                if path_index % 5000 == 0:
                    print(
                        f"  {name}: files={path_index:,}/{len(items):,}, "
                        f"chunks={samples:,}, max_tokens={max_seen}, {elapsed(start)}",
                        flush=True,
                    )
        finally:
            if workers > 1:
                executor.shutdown(wait=True)

        if items and len(items) % 5000 != 0:
            print(
                f"  {name}: files={len(items):,}/{len(items):,}, "
                f"chunks={samples:,}, max_tokens={max_seen}, {elapsed(start)}",
                flush=True,
            )

    return {
        "corpus_type": name,
        "file": str(output_path),
        "source_files": len(items),
        "source_splits": split_counts,
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
        "source_splits",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "avg_token": f"{row['avg_token']:.2f}",
                "avg_chars": f"{row['avg_chars']:.2f}",
                "source_splits": json.dumps(row["source_splits"], ensure_ascii=False, sort_keys=True),
            })

    json_path = out_dir / "cpt_dataset_summary.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--score-metadata", type=Path, default=None)
    parser.add_argument("--miditsv-root", type=Path, default=None)
    parser.add_argument("--knowledge-dir", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--out-dir", type=Path, default=Path("backup/legacy_CoReS/language_cpt"))
    parser.add_argument("--tokenizer", type=Path, default=Path("Qwen3.5-4B-LM-MIDI-Full"))
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--work-dir", type=Path, default=Path("data/.tmp_language_cpt"))
    args = parser.parse_args()

    start = time.time()
    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    args.work_dir.mkdir(parents=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="language_cpt_", dir=str(args.work_dir)))

    try:
        metadata_score_paths, perf_paths = unique_metadata_paths(args.metadata, args.miditsv_root)
        if args.score_metadata is not None:
            score_paths = score_paths_from_score_metadata(args.score_metadata)
        else:
            score_paths = metadata_score_paths
        knowledge_paths = [
            (path, "knowledge")
            for path in sorted(args.knowledge_dir.rglob("*.md"))
        ]
        print(f"Score files: {len(score_paths):,}")
        print(f"Performance TSV files: {len(perf_paths):,}")
        print(f"Knowledge markdown files: {len(knowledge_paths):,}")
        print(f"Workers: {args.workers:,}")

        rows = [
            build_corpus(
                "aligned_abcx",
                score_paths,
                temp_dir / "aligned_abcx.jsonl",
                "abcx",
                args.tokenizer,
                args.max_tokens,
                args.workers,
            ),
            build_corpus(
                "midi_tsv_no_header",
                perf_paths,
                temp_dir / "midi_tsv_no_header.jsonl",
                "midi",
                args.tokenizer,
                args.max_tokens,
                args.workers,
            ),
        ]
        format_items = [
            item for item in knowledge_paths
            if Path(item[0]).parent.name == "format"
        ]
        seeker_items = [
            item for item in knowledge_paths
            if Path(item[0]).parent.name == "Seeker38"
        ]
        if format_items:
            rows.append(
                build_corpus(
                    "knowledge_format",
                    format_items,
                    temp_dir / "knowledge_format.jsonl",
                    "markdown",
                    args.tokenizer,
                    args.max_tokens,
                    min(args.workers, max(1, len(format_items))),
                )
            )
        if seeker_items:
            rows.append(
                build_corpus(
                    "knowledge_Seeker38",
                    seeker_items,
                    temp_dir / "knowledge_Seeker38.jsonl",
                    "markdown",
                    args.tokenizer,
                    args.max_tokens,
                    min(args.workers, max(1, len(seeker_items))),
                )
            )
        write_summary(temp_dir, rows)

        args.out_dir.mkdir(parents=True, exist_ok=True)
        for path in temp_dir.iterdir():
            target = args.out_dir / path.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(path), str(target))
        for row in rows:
            row["file"] = str(args.out_dir / Path(row["file"]).name)
        write_summary(args.out_dir, rows)
    finally:
        shutil.rmtree(args.work_dir, ignore_errors=True)

    print(f"Wrote {args.out_dir}")
    print(f"Done in {elapsed(start)}")


if __name__ == "__main__":
    main()
