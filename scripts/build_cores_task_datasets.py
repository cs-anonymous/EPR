#!/usr/bin/env python3
"""Build task-specific CoRe-S train datasets under PianoCoReS/CoReS.

This script reorganizes the already generated full CoRe-S train JSONL files
into four task families:

1. Language SFT reference to existing S1
2. Language CPT
3. Phrase-based EPR SFT
4. Measure-based EPR SFT

It intentionally reuses sft_data/core-s-train as the source of truth so the
output matches the existing sft_data/README.md generation flow.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import os
import shutil
import time
from collections import Counter
from pathlib import Path


EPR_TASK_TYPES = ["coldstart", "main", "ending"]


def line_count(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def apparent_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ["B", "K", "M", "G", "T"]:
        if value < 1024 or unit == "T":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{num_bytes}B"


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def hardlink_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_language_sft_reference(s1_dir: Path, out_root: Path) -> list[dict]:
    """Create a language_sft symlink pointing at the existing S1 dataset."""
    link = out_root / "language_sft"
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    rel_target = os.path.relpath(s1_dir, start=out_root)
    link.symlink_to(rel_target, target_is_directory=True)

    train_file = s1_dir / "sft_language_train.jsonl"
    return [{
        "family": "language_sft",
        "file": str(link),
        "samples": line_count(train_file) if train_file.exists() else 0,
        "bytes": apparent_size(train_file) if train_file.exists() else 0,
        "note": f"symlink_to_existing_s1:{train_file}",
    }]


def split_epr(source_file: Path, out_dir: Path, prefix: str) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    counts = Counter()
    try:
        for task_type in EPR_TASK_TYPES:
            path = out_dir / f"{prefix}_{task_type}.jsonl"
            handles[task_type] = path.open("w", encoding="utf-8")
        with source_file.open("r", encoding="utf-8") as fin:
            for line in fin:
                if not line.strip():
                    continue
                sample = json.loads(line)
                task_type = sample.get("task_type", "main")
                if task_type not in handles:
                    task_type = "main"
                handles[task_type].write(line)
                counts[task_type] += 1
    finally:
        for handle in handles.values():
            handle.close()

    stats = []
    for task_type in EPR_TASK_TYPES:
        path = out_dir / f"{prefix}_{task_type}.jsonl"
        stats.append({
            "family": f"{prefix}_sft",
            "file": str(path),
            "samples": counts[task_type],
            "bytes": apparent_size(path),
            "note": "split_by_task_type",
        })
    return stats


def score_path_from_metadata(value: str) -> Path | None:
    if not value or value == "nan":
        return None
    path = value
    if path.startswith("PianoCoRe/score/"):
        rel = path.removeprefix("PianoCoRe/score/").removesuffix("/score.abcx")
        return Path("PianoCoReS/aligned") / rel / "score_aligned.abcx"
    if path.startswith("PianoCoReS/"):
        return Path(path)
    return Path(path)


def perf_path_from_metadata(value: str) -> Path | None:
    if not value or value == "nan":
        return None
    path = value
    if path.startswith("PianoCoRe_output/"):
        rel = path.removeprefix("PianoCoRe_output/")
        return Path("PianoCoReS/aligned") / rel
    if path.startswith("PianoCoRe/aligned/"):
        rel = path.removeprefix("PianoCoRe/aligned/")
        return Path("PianoCoReS/aligned") / rel
    if path.startswith("PianoCoReS/"):
        return Path(path)
    return Path(path)


def line_chunks(lines: list[str], max_chars: int) -> list[str]:
    """Legacy character-based chunking (kept for backward compatibility)."""
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        add_len = len(line) + 1
        if current and current_len + add_len > max_chars:
            chunks.append("\n".join(current).rstrip())
            current = []
            current_len = 0
        current.append(line)
        current_len += add_len
    if current:
        chunks.append("\n".join(current).rstrip())
    return [chunk for chunk in chunks if chunk]


# ---------------------------------------------------------------------------
# Phrase-aware chunking helpers for CPT data
# ---------------------------------------------------------------------------
# Each chunker returns list[str] of text blocks.  The caller wraps them into
# JSONL records.  Token budget is measured by an approximate chars-per-token
# ratio (~2.0 chars/token for ABCX / MIDI-TSV) since we want to avoid
# requiring a tokenizer in the multiprocessing workers.
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 2.0


def token_budget(max_tokens: int, chars_per_token: float = 2.0) -> int:
    return int(max_tokens * chars_per_token)


def _phrase_lines(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group lines into (H_label, M_lines) pairs."""
    phrases: list[tuple[str, list[str]]] = []
    current_label = ""
    current_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped[0] == "H" and len(stripped) <= 5:
            if current_label and current_lines:
                phrases.append((current_label, current_lines))
            current_label = stripped
            current_lines = []
        else:
            current_lines.append(line)
    if current_label and current_lines:
        phrases.append((current_label, current_lines))
    return phrases


def abcx_chunks(lines: list[str], max_tokens: int) -> list[str]:
    """Chunk aligned ABCX by phrase boundaries.

    - The header (up to K:) is collected; every chunk repeats it.
    - Tabs are normalised to 4 spaces.
    - Each phrase (H label + its M lines) is one chunk.
    - If a single phrase exceeds max_tokens, split at M line boundaries.
    """
    budget = token_budget(max_tokens, chars_per_token=1.5)

    # Split into header and body
    header_lines: list[str] = []
    body_lines: list[str] = []
    in_header = True
    for line in lines:
        if in_header:
            header_lines.append(line.replace("\t", "    "))
            if line.startswith("K:"):
                in_header = False
        else:
            body_lines.append(line.replace("\t", "    "))

    # Group body into phrases
    phrases = _abcx_phrase_lines(body_lines)

    header_text = "\n".join(header_lines).rstrip()

    chunks: list[str] = []
    for phrase_lines in phrases:
        phrase_text = "\n".join(phrase_lines).rstrip()
        phrase_len = len(phrase_text) + 1

        # If a single phrase alone exceeds budget, split it
        if len(header_text) + 1 + phrase_len > budget:
            sub_chunks = _split_oversized_phrase(phrase_lines, budget, header_text)
            chunks.extend(sub_chunks)
        else:
            chunks.append(header_text + "\n" + phrase_text)

    return [c.rstrip() for c in chunks if c.strip()]


def _abcx_phrase_lines(body_lines: list[str]) -> list[list[str]]:
    """Split body lines into phrase groups (H label + M lines)."""
    phrases: list[list[str]] = []
    current_phrase: list[str] = []
    for line in body_lines:
        stripped = line.strip()
        if stripped and stripped[0] == "H" and len(stripped) <= 5:
            if current_phrase:
                phrases.append(current_phrase)
            current_phrase = [line]
        else:
            current_phrase.append(line)
    if current_phrase:
        phrases.append(current_phrase)
    return phrases


def _split_oversized_phrase(phrase_lines: list[str], budget: int, header_text: str) -> list[str]:
    """Split a single oversized ABCX phrase into sub-chunks at M line boundaries."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in phrase_lines:
        add_len = len(line) + 1
        if current and current_len + add_len > budget:
            chunks.append(header_text + "\n" + "\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += add_len

    if current:
        chunks.append(header_text + "\n" + "\n".join(current))

    return [c.rstrip() for c in chunks if c.strip()]


def midi_tsv_chunks(lines: list[str], max_tokens: int) -> list[str]:
    """Chunk MIDI-TSV by phrase boundaries.

    - Phrase records are lines matching H<n>:<digits>.
    - Measure records between two phrases stay with their preceding phrase.
    - A single phrase that exceeds budget gets split at measure (M<n>) boundaries.
    """
    budget = token_budget(max_tokens, chars_per_token=1.15)

    # Group into phrases
    phrases: list[list[str]] = []
    current_phrase: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[0] == "H" and ":" in stripped:
            if current_phrase:
                phrases.append(current_phrase)
            current_phrase = [line]
        else:
            current_phrase.append(line)
    if current_phrase:
        phrases.append(current_phrase)

    chunks: list[str] = []

    for phrase in phrases:
        phrase_text = "\n".join(phrase).rstrip()
        phrase_len = len(phrase_text) + 1

        # If this phrase alone exceeds budget, split at measure boundaries
        if phrase_len > budget:
            sub_chunks = _split_oversized_midi_tsv_phrase(phrase, budget)
            chunks.extend(sub_chunks)
            continue

        chunks.append(phrase_text)

    return [c for c in chunks if c.strip()]


def _split_oversized_midi_tsv_phrase(phrase_lines: list[str], budget: int) -> list[str]:
    """Split a single oversized MIDI-TSV phrase at measure (M<n>...) lines."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in phrase_lines:
        add_len = len(line) + 1
        if current and current_len + add_len > budget:
            chunks.append("\n".join(current).rstrip())
            current = []
            current_len = 0
        current.append(line)
        current_len += add_len

    if current:
        chunks.append("\n".join(current).rstrip())

    return [c for c in chunks if c.strip()]


def knowledge_chunks(lines: list[str], max_tokens: int) -> list[str]:
    """Chunk knowledge markdown by semantic boundaries (## headings).

    Each chunk is a relatively independent semantic entry.  If a section
    exceeds max_tokens, it is further split at ### subheadings or
    blank-line boundaries.
    """
    budget = token_budget(max_tokens, chars_per_token=1.5)

    # Group lines into sections delimited by ## headings
    sections: list[list[str]] = [[]]
    for line in lines:
        if line.startswith("## "):
            if sections[-1]:
                sections.append([])
        sections[-1].append(line)
    sections = [s for s in sections if s]

    chunks: list[str] = []
    for section in sections:
        section_text = "\n".join(section).rstrip()
        section_len = len(section_text) + 1

        if section_len > budget:
            sub_chunks = _split_large_section(section, budget)
            chunks.extend(sub_chunks)
        else:
            chunks.append(section_text)

    return [c for c in chunks if c.strip()]


def _split_large_section(lines: list[str], budget: int) -> list[str]:
    """Split a single oversized markdown section into smaller chunks."""
    # Try splitting at ### sub-headings
    sub_sections: list[list[str]] = [[]]
    for line in lines:
        if line.startswith("### "):
            if sub_sections[-1]:
                sub_sections.append([])
        sub_sections[-1].append(line)
    sub_sections = [s for s in sub_sections if s]

    # If sub-sections are small enough, aggregate them
    if all(len("\n".join(s)) + 1 <= budget for s in sub_sections):
        return ["\n".join(s).rstrip() for s in sub_sections]

    # Fallback: split at blank-line boundaries
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        add_len = len(line) + 1
        if current and current_len + add_len > budget:
            # Flush at nearest blank line boundary
            # Find last blank line in current and split there
            blank_idx = None
            for i in range(len(current) - 1, -1, -1):
                if not current[i].strip():
                    blank_idx = i
                    break
            if blank_idx is not None and blank_idx > 0:
                chunks.append("\n".join(current[:blank_idx]).rstrip())
                current = current[blank_idx:]
                current_len = sum(len(l) + 1 for l in current)
            else:
                chunks.append("\n".join(current).rstrip())
                current = []
                current_len = 0
        current.append(line)
        current_len += add_len
    if current:
        chunks.append("\n".join(current).rstrip())
    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Multiprocessing worker helpers
# ---------------------------------------------------------------------------


def _process_abcx_file(args_tuple):
    """Process a single ABCX file into chunks.  Returns (source, chunks_list)."""
    path_str, max_tokens = args_tuple
    path = Path(path_str)
    lines = path.read_text(encoding="utf-8").splitlines()
    chunks = abcx_chunks(lines, max_tokens)
    return (str(path), chunks)


def _process_tsv_file(args_tuple):
    """Process a single MIDI-TSV file into chunks.  Returns (source, chunks_list)."""
    path_str, max_tokens = args_tuple
    path = Path(path_str)
    with path.open("r", encoding="utf-8") as fin:
        lines = [
            line.rstrip("\n")
            for line in fin
            if line.strip() and not line.startswith("#")
        ]
    chunks = midi_tsv_chunks(lines, max_tokens)
    return (str(path), chunks)


def _process_knowledge_file(args_tuple):
    """Process a single knowledge markdown file into chunks."""
    path_str, max_tokens = args_tuple
    path = Path(path_str)
    lines = path.read_text(encoding="utf-8").splitlines()
    chunks = knowledge_chunks(lines, max_tokens)
    return (str(path), chunks)


def write_cpt_record(fout, corpus_type: str, source: str, chunk_id: int, text: str) -> None:
    row = {
        "task": "language_cpt",
        "corpus_type": corpus_type,
        "source": source,
        "chunk_id": chunk_id,
        "text": text,
    }
    fout.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def build_language_cpt(
    metadata_path: Path,
    knowledge_dir: Path,
    out_dir: Path,
    max_tokens: int,
    n_workers: int,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = []
    score_paths, perf_paths = unique_metadata_paths(metadata_path)

    # -- ABCX --
    abcx_out = out_dir / "aligned_abcx.jsonl"
    count = 0
    with abcx_out.open("w", encoding="utf-8") as fout:
        work = [(str(p), max_tokens) for p in score_paths]
        with multiprocessing.Pool(n_workers) as pool:
            for source, chunks in pool.imap(_process_abcx_file, work):
                for idx, chunk in enumerate(chunks, 1):
                    write_cpt_record(fout, "aligned_abcx", source, idx, chunk)
                    count += 1
    stats.append({
        "family": "language_cpt",
        "file": str(abcx_out),
        "samples": count,
        "bytes": apparent_size(abcx_out),
        "note": f"{len(score_paths)} unique aligned ABCX files",
    })

    # -- MIDI-TSV --
    tsv_out = out_dir / "midi_tsv_no_header.jsonl"
    count = 0
    with tsv_out.open("w", encoding="utf-8") as fout:
        work = [(str(p), max_tokens) for p in perf_paths]
        with multiprocessing.Pool(n_workers) as pool:
            for source, chunks in pool.imap(_process_tsv_file, work):
                for idx, chunk in enumerate(chunks, 1):
                    write_cpt_record(fout, "midi_tsv_no_header", source, idx, chunk)
                    count += 1
    stats.append({
        "family": "language_cpt",
        "file": str(tsv_out),
        "samples": count,
        "bytes": apparent_size(tsv_out),
        "note": f"{len(perf_paths)} unique performance TSV files",
    })

    # -- Knowledge markdown --
    knowledge_out = out_dir / "knowledge_markdown.jsonl"
    count = 0
    with knowledge_out.open("w", encoding="utf-8") as fout:
        md_files = sorted(knowledge_dir.glob("*.md"))
        work = [(str(p), max_tokens) for p in md_files]
        with multiprocessing.Pool(min(n_workers, len(md_files))) as pool:
            for source, chunks in pool.imap(_process_knowledge_file, work):
                for idx, chunk in enumerate(chunks, 1):
                    write_cpt_record(fout, "knowledge_markdown", source, idx, chunk)
                    count += 1
    stats.append({
        "family": "language_cpt",
        "file": str(knowledge_out),
        "samples": count,
        "bytes": apparent_size(knowledge_out),
        "note": "knowledge markdown chunks",
    })

    return stats


def write_stats(out_root: Path, stats: list[dict]) -> None:
    stats_path = out_root / "stats.csv"
    fieldnames = ["family", "file", "samples", "bytes", "size", "note"]
    with stats_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in stats:
            out = dict(row)
            out["size"] = human_size(int(out["bytes"]))
            writer.writerow(out)

    family_totals = {}
    for row in stats:
        family = row["family"]
        family_totals.setdefault(family, {"samples": 0, "bytes": 0})
        family_totals[family]["samples"] += int(row["samples"])
        family_totals[family]["bytes"] += int(row["bytes"])

    readme = out_root / "SUMMARY.generated.md"
    lines = [
        "# CoRe-S Train Task Datasets",
        "",
        "Generated from `sft_data/core-s-train` and `PianoCoReS/knowledge`.",
        "",
        "## Families",
        "",
        "- `language_sft/`: symlink to the existing S1 Language SFT dataset.",
        "- `language_cpt/`: aligned ABCX, MIDI-TSV without headers, and knowledge markdown chunks.",
        "- `phrase_epr_sft/`: phrase EPR split into coldstart, main, and ending.",
        "- `measure_epr_sft/`: measure EPR split into coldstart, main, and ending.",
        "",
        "## Totals",
        "",
        "| Family | Samples | Apparent size |",
        "|---|---:|---:|",
    ]
    for family in sorted(family_totals):
        total = family_totals[family]
        lines.append(
            f"| `{family}` | {total['samples']:,} | {human_size(total['bytes'])} |"
        )
    lines.extend([
        "",
        "Detailed per-file statistics are in `stats.csv`.",
        "",
        "Language SFT is not built here; it uses the existing S1 dataset.",
    ])
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=Path("sft_data/core-s-train"))
    parser.add_argument("--s1-dir", type=Path, default=Path("sft_data/core-s1"))
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--knowledge-dir", type=Path, default=Path("PianoCoReS/knowledge"))
    parser.add_argument("--out-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--cpt-max-tokens", type=int, default=2048)
    parser.add_argument("--workers", type=int, default=multiprocessing.cpu_count())
    args = parser.parse_args()

    if not args.source_dir.exists():
        raise FileNotFoundError(args.source_dir)
    if not args.metadata.exists():
        raise FileNotFoundError(args.metadata)

    clean_dir(args.out_root)
    stats: list[dict] = []

    print("Linking existing S1 Language SFT...")
    stats.extend(build_language_sft_reference(args.s1_dir, args.out_root))

    print("Building phrase-based EPR SFT...")
    stats.extend(split_epr(
        args.source_dir / "phrase_epr.jsonl",
        args.out_root / "phrase_epr_sft",
        "phrase_epr",
    ))

    print("Building measure-based EPR SFT...")
    stats.extend(split_epr(
        args.source_dir / "measure_epr.jsonl",
        args.out_root / "measure_epr_sft",
        "measure_epr",
    ))

    print(f"Building Language CPT (max_tokens={args.cpt_max_tokens}, workers={args.workers})...")
    stats.extend(build_language_cpt(
        args.metadata,
        args.knowledge_dir,
        args.out_root / "language_cpt",
        args.cpt_max_tokens,
        args.workers,
    ))

    write_stats(args.out_root, stats)
    print(f"Wrote {args.out_root}")
    print(f"Stats: {args.out_root / 'stats.csv'}")


if __name__ == "__main__":
    main()
