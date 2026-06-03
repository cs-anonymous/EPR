#!/usr/bin/env python3
"""Build measure-boundary language CPT corpora from data metadata.

Optimized: <XXX> tokens are counted via regex (1 match = 1 token) instead of
calling the full tokenizer, which is orders of magnitude faster.
Only the plain-text segments are passed to the tokenizer.

Annotated score format:
- No T:/C:/Z: header comments
- Each chunk starts with KS/TP/MT config lines (the 3 events before first H)
- Every chunk is capped at max_tokens; oversized ones are split at measure boundaries.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Iterable

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tokens import add_lm_midi_tokens
from scripts.lm_midi_tsv import lm_midi_tsv_to_tokens


_WORKER_TOKENIZER = None
TOKEN_RE = re.compile(r"<[^>]+>")


def init_worker(tokenizer_path: str) -> None:
    global _WORKER_TOKENIZER
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
    add_lm_midi_tokens(tokenizer, mode="full")
    _WORKER_TOKENIZER = tokenizer


def count_tokens(text: str) -> int:
    """Count tokens: <XXX> tags = 1 each via regex; remaining text via tokenizer."""
    tag_count = len(TOKEN_RE.findall(text))
    plain = TOKEN_RE.sub("", text)
    token_count = len(_WORKER_TOKENIZER(plain, add_special_tokens=False)["input_ids"])
    return token_count + tag_count


def is_measure_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("M\t") or bool(re.match(r"^M\d+\t", stripped))


def is_phrase_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("H\t") or bool(re.match(r"^H\d+\t", stripped))


def normalize_structural_line(line: str) -> str:
    parts = line.rstrip("\n").split("\t")
    if len(parts) == 4 and re.fullmatch(r"H\d+", parts[0]):
        parts[0] = "H"
        return "\t".join(parts)
    if len(parts) == 4 and re.fullmatch(r"M\d+", parts[0]):
        parts[0] = "M"
        return "\t".join(parts)
    return line.rstrip("\n")


def split_measure_groups(lines: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if is_phrase_line(line):
            continue
        if is_measure_line(line):
            if current:
                groups.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        groups.append(current)
    return groups


def with_measure_index(group: list[str], measure_idx: int) -> list[str]:
    safe_measure_idx = measure_idx % 128
    normalized: list[str] = []
    for line in group:
        if is_measure_line(line):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 4:
                parts[1] = str(safe_measure_idx)
                normalized.append("\t".join(parts))
                continue
        normalized.append(line)
    return normalized


def render_chunk_midi(groups: list[list[str]]) -> str:
    chunk_lines: list[str] = []
    for measure_idx, group in enumerate(groups):
        chunk_lines.extend(with_measure_index(group, measure_idx))
    return lm_midi_tsv_to_tokens("\n".join(chunk_lines), wrap=True, pretty=False)


def extract_score_config_lines(tsv_path: Path) -> str:
    """Extract KS/TP/MT lines that appear before the first H line."""
    ks, tp, mt = None, None, None
    for raw_line in tsv_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("H"):
            break
        if stripped.startswith("KS\t"):
            ks = stripped
        elif stripped.startswith("TP\t"):
            tp = stripped
        elif stripped.startswith("MT\t"):
            mt = stripped
    parts = []
    for v in (ks, tp, mt):
        if v is not None:
            parts.append(v)
    return "\n".join(parts)


def resolve_perf_tsv(row: dict[str, str]) -> Path | None:
    value = (row.get("performance_tsv_path") or "").strip()
    if value.startswith("data/"):
        path = ROOT / value
        return path if path.exists() else None
    rel = (row.get("tsv_path") or "").strip()
    if rel:
        path = ROOT / "data" / rel
        return path if path.exists() else None
    if value:
        path = ROOT / value
        return path if path.exists() else None
    return None


def resolve_score_tsv(row: dict[str, str]) -> Path | None:
    value = (row.get("annotated_score_midi_path") or "").strip()
    if not value:
        return None
    path = ROOT / value
    return path if path.exists() else None


def resolve_score_abcx(row: dict[str, str]) -> Path | None:
    for key in ("score_abcx_path", "score_aligned_path"):
        value = (row.get(key) or "").strip()
        if value:
            path = ROOT / value
            if path.exists():
                return path
    return None


def group_tokens_estimate(group: list[str]) -> int:
    """Fast estimate of token count for one measure group (regex only)."""
    group_tsv = "\n".join(with_measure_index(group, 0))
    group_midi_text = lm_midi_tsv_to_tokens(group_tsv, wrap=False, pretty=False)
    return len(TOKEN_RE.findall(group_midi_text))


def make_chunk_text(groups: list[list[str]], config_lines: str) -> str:
    midi_text = render_chunk_midi(groups)
    if config_lines:
        return f"{config_lines}\n{midi_text}"
    return midi_text


def build_measure_chunks(
    tsv_path: Path,
    max_tokens: int,
    config_lines: str = "",
) -> list[tuple[str, int]]:
    body_lines = [
        normalize_structural_line(line)
        for line in tsv_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    measure_groups = split_measure_groups(body_lines)
    chunks: list[tuple[str, int]] = []
    config_tokens = count_tokens(f"{config_lines}\n") if config_lines else 0

    # Standard accumulation at measure boundaries
    current_groups: list[list[str]] = []
    current_tokens = config_tokens + 2 if measure_groups else 0

    for group in measure_groups:
        g_tok = group_tokens_estimate(group)
        candidate_tokens = current_tokens + g_tok
        if current_groups and candidate_tokens > max_tokens:
            text = make_chunk_text(current_groups, config_lines)
            chunks.append((text, current_tokens))
            current_groups = [group]
            current_tokens = config_tokens + 2 + g_tok
        else:
            current_groups.append(group)
            current_tokens = candidate_tokens

    if current_groups:
        text = make_chunk_text(current_groups, config_lines)
        chunks.append((text, current_tokens))

    # Final pass: split any chunk that still exceeds max_tokens
    final_chunks: list[tuple[str, int]] = []
    for text, num_tokens in chunks:
        if num_tokens <= max_tokens:
            final_chunks.append((text, num_tokens))
            continue
        # Split at measure boundaries within the chunk text.
        # Re-parse the chunk to find measure groups, then binary-search for the
        # largest prefix that fits.
        # Simpler: re-split the body_lines for this source and re-accumulate
        # with a tighter bound. But that's expensive. Instead, split the token
        # string at <M> boundaries.
        mid_pos = text.find("<M>", len(config_lines) + 2 if config_lines else 0)
        if mid_pos < 0:
            # No measure found; emit as-is (extreme single-measure case)
            final_chunks.append((text, num_tokens))
            continue

        # Binary search: find the best split point at an <M> boundary
        m_positions = [m.start() for m in re.finditer(r"<M>", text)]
        # We need the config prefix to be included in both parts
        prefix_len = len(config_lines) + 1 if config_lines else 0  # +1 for \n
        best_split = None
        for pos in m_positions:
            if pos <= prefix_len:
                continue
            part1 = text[:pos]
            t1 = count_tokens(part1)
            if t1 <= max_tokens:
                best_split = pos

        if best_split is not None:
            part1_text = text[:best_split]
            part2_text = config_lines + "\n" + text[best_split:] if config_lines else text[best_split:]
            final_chunks.append((part1_text, count_tokens(part1_text)))
            final_chunks.append((part2_text, count_tokens(part2_text)))
        else:
            # All split points exceed max_tokens; the first measure alone is too big.
            # Emit as-is (cannot split further at measure boundary).
            final_chunks.append((text, num_tokens))

    return final_chunks


def process_performance_source(task: tuple[str, str, int]) -> dict:
    path_str, split, max_tokens = task
    try:
        path = Path(path_str)
        chunks = build_measure_chunks(path, max_tokens=max_tokens)
        records = [
            {
                "task": "language_cpt",
                "corpus_type": "midi_tsv_no_header",
                "source": str(path),
                "source_split": split,
                "chunk_id": chunk_id,
                "text": text,
                "num_tokens": num_tokens,
            }
            for chunk_id, (text, num_tokens) in enumerate(chunks, 1)
        ]
        return {"records": records, "errors": []}
    except Exception as exc:
        return {
            "records": [],
            "errors": [{"source": path_str, "source_split": split, "error": repr(exc)}],
        }


def process_annotated_score_source(task: tuple[str, str, int]) -> dict:
    path_str, split, max_tokens = task
    try:
        path = Path(path_str)
        config_lines = extract_score_config_lines(path)
        chunks = build_measure_chunks(path, max_tokens=max_tokens, config_lines=config_lines)
        records = [
            {
                "task": "language_cpt",
                "corpus_type": "annotated_score_midi_tsv",
                "source": str(path),
                "source_split": split,
                "chunk_id": chunk_id,
                "text": text,
                "num_tokens": num_tokens,
            }
            for chunk_id, (text, num_tokens) in enumerate(chunks, 1)
        ]
        return {"records": records, "errors": []}
    except Exception as exc:
        return {
            "records": [],
            "errors": [{"source": path_str, "source_split": split, "error": repr(exc)}],
        }


def load_perf_tasks(metadata_path: Path, max_tokens: int, key: str = "performance") -> list[tuple[str, str, int]]:
    tasks: list[tuple[str, str, int]] = []
    seen = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = resolve_perf_tsv(row)
            if path is None or path in seen:
                continue
            seen.add(path)
            split = (row.get("split") or "").strip() or "unspecified"
            tasks.append((str(path), split, max_tokens))
    return tasks


def load_score_tasks(metadata_path: Path, max_tokens: int) -> list[tuple[str, str, int]]:
    tasks: list[tuple[str, str, int]] = []
    seen = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = resolve_score_tsv(row)
            if path is None or path in seen:
                continue
            seen.add(path)
            split = (row.get("split") or "").strip() or "unspecified"
            tasks.append((str(path), split, max_tokens))
    return tasks


def choose_tokenizer(preferred: str) -> str:
    candidates = [preferred, "Qwen/Qwen2.5-0.5B", "Qwen/Qwen2.5-1.5B"]
    for candidate in candidates:
        try:
            tokenizer = AutoTokenizer.from_pretrained(candidate, trust_remote_code=True)
            add_lm_midi_tokens(tokenizer, mode="full")
            return candidate
        except Exception:
            continue
    raise RuntimeError(f"could not load any tokenizer from candidates: {candidates}")


def iter_results(tasks, worker_fn, tokenizer_path: str, workers: int):
    if workers <= 1:
        init_worker(tokenizer_path)
        for task in tasks:
            yield worker_fn(task)
        return
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker, initargs=(tokenizer_path,)) as executor:
        yield from executor.map(worker_fn, tasks, chunksize=16)


def write_errors(path: Path, errors: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for error in errors:
            f.write(json.dumps(error, ensure_ascii=False) + "\n")


def write_jsonl_from_results(path: Path, results) -> tuple[int, list[dict]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    total_tokens = 0
    errors: list[dict] = []
    unique_sources: set[str] = set()
    token_lengths = []
    with path.open("w", encoding="utf-8") as f:
        for result in results:
            errors.extend(result.get("errors", []))
            for record in result["records"]:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
                total_tokens += record["num_tokens"]
                unique_sources.add(record["source"])
                token_lengths.append(record["num_tokens"])
    return count, errors, total_tokens, unique_sources, token_lengths


def write_json_array_from_results(path: Path, results) -> tuple[int, list[dict]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    total_tokens = 0
    errors: list[dict] = []
    unique_sources: set[str] = set()
    token_lengths = []
    first = True
    with path.open("w", encoding="utf-8") as f:
        f.write("[")
        for result in results:
            errors.extend(result.get("errors", []))
            for record in result["records"]:
                if not first:
                    f.write(",")
                f.write(json.dumps(record, ensure_ascii=False))
                first = False
                count += 1
                total_tokens += record["num_tokens"]
                unique_sources.add(record["source"])
                token_lengths.append(record["num_tokens"])
        f.write("]")
    return count, errors, total_tokens, unique_sources, token_lengths


def token_stats(lengths: list[int]) -> dict:
    if not lengths:
        return {}
    lengths.sort()
    return {
        "total_tokens": sum(lengths),
        "avg_tokens": round(sum(lengths) / len(lengths), 2),
        "max_tokens": lengths[-1],
        "p50": lengths[len(lengths) // 2],
        "p95": lengths[int(len(lengths) * 0.95)],
        "p99": lengths[int(len(lengths) * 0.99)],
        "over_2048": sum(1 for x in lengths if x > 2048),
    }


def selected(datasets: Iterable[str], name: str) -> bool:
    return name in set(datasets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=str, default="./Qwen3.5-0.8B-LM-MIDI-Resized")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=["astar", "performance_s", "annotated_score"],
        default=["astar", "performance_s", "annotated_score"],
    )
    parser.add_argument(
        "--astar-metadata",
        type=Path,
        default=ROOT / "data" / "performance_Astar_metadata.csv",
    )
    parser.add_argument(
        "--perf-s-metadata",
        type=Path,
        default=ROOT / "data" / "performance_S_metadata.csv",
    )
    parser.add_argument(
        "--score-metadata",
        type=Path,
        default=ROOT / "data" / "score_metadata.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "CorporaV2" / "language_cpt",
    )
    args = parser.parse_args()

    tokenizer_path = choose_tokenizer(args.tokenizer)
    print(f"Using tokenizer: {tokenizer_path}")
    print(f"Max tokens: {args.max_tokens}")
    print(f"Workers: {args.workers}")
    print(f"Datasets: {', '.join(args.datasets)}")

    astar_count = 0; astar_tokens = 0; astar_sources = set(); astar_lengths = []
    perf_s_count = 0; perf_s_tokens = 0; perf_s_sources = set(); perf_s_lengths = []
    score_count = 0; score_tokens = 0; score_sources = set(); score_lengths = []
    all_errors: dict[str, list[dict]] = {}

    if selected(args.datasets, "astar"):
        astar_tasks = load_perf_tasks(args.astar_metadata, args.max_tokens)
        print(f"A* performance sources: {len(astar_tasks)}")
        astar_count, astar_errors, astar_tokens, astar_sources, astar_lengths = write_json_array_from_results(
            args.output_dir / "performance_Astar_midi.json",
            iter_results(astar_tasks, process_performance_source, tokenizer_path, args.workers),
        )
        all_errors["astar"] = astar_errors

    if selected(args.datasets, "performance_s"):
        perf_s_tasks = load_perf_tasks(args.perf_s_metadata, args.max_tokens)
        print(f"S performance sources: {len(perf_s_tasks)}")
        perf_s_count, perf_s_errors, perf_s_tokens, perf_s_sources, perf_s_lengths = write_jsonl_from_results(
            args.output_dir / "performance_S_midi.jsonl",
            iter_results(perf_s_tasks, process_performance_source, tokenizer_path, args.workers),
        )
        all_errors["performance_s"] = perf_s_errors

    if selected(args.datasets, "annotated_score"):
        score_tasks = load_score_tasks(args.score_metadata, args.max_tokens)
        print(f"Annotated score sources: {len(score_tasks)}")
        score_count, score_errors, score_tokens, score_sources, score_lengths = write_jsonl_from_results(
            args.output_dir / "annotated_score_midi.jsonl",
            iter_results(score_tasks, process_annotated_score_source, tokenizer_path, args.workers),
        )
        all_errors["annotated_score"] = score_errors

    error_summary = {name: len(errors) for name, errors in all_errors.items()}
    for name, errors in all_errors.items():
        if errors:
            write_errors(args.output_dir / f"{name}_measure_errors.jsonl", errors)

    summary = {
        "tokenizer": tokenizer_path,
        "max_tokens": args.max_tokens,
        "datasets": args.datasets,
        "performance_Astar_midi.json": {
            "samples": astar_count,
            "unique_sources": len(astar_sources),
            "total_tokens": astar_tokens,
            "stats": token_stats(astar_lengths),
        },
        "performance_S_midi.jsonl": {
            "samples": perf_s_count,
            "unique_sources": len(perf_s_sources),
            "total_tokens": perf_s_tokens,
            "stats": token_stats(perf_s_lengths),
        },
        "annotated_score_midi.jsonl": {
            "samples": score_count,
            "unique_sources": len(score_sources),
            "total_tokens": score_tokens,
            "stats": token_stats(score_lengths),
        },
        "totals": {
            "samples": astar_count + perf_s_count + score_count,
            "unique_sources": len(astar_sources | perf_s_sources | score_sources),
            "total_tokens": astar_tokens + perf_s_tokens + score_tokens,
            "avg_tokens": round((astar_tokens + perf_s_tokens + score_tokens) / max(1, astar_count + perf_s_count + score_count), 2),
        },
        "errors": error_summary,
    }
    (args.output_dir / "language_cpt_measure_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
