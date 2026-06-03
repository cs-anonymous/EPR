#!/usr/bin/env python3
"""Build EPR SFT corpora from S and Astar performance metadata.

The generated task is:

    annotated score MIDI + interpretation/performance concept -> performance MIDI

Samples are packed by consecutive measures with input_tokens + output_tokens
bounded by MAX_LENGTH. Astar metadata is normalized to the same schema as
performance_S_metadata.csv before dataset construction.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lm_midi_tokens import add_lm_midi_tokens
from scripts.lm_midi_tsv import lm_midi_tsv_to_tokens


MAX_LENGTH = 4096
DEFAULT_SEED = 42
TOKEN_RE = re.compile(r"<[^>]+>")
MEASURE_RE = re.compile(r"^M\d*$")
PHRASE_RE = re.compile(r"^H\d*$")

TASK_TEXT = "Generate an expressive performance MIDI from the given annotated score MIDI."


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def normalize_piece_text(value: str) -> str:
    return (value or "").replace("_", " ").strip()


def as_root_path(value: str) -> Path:
    path = Path((value or "").strip())
    if path.is_absolute():
        return path
    return ROOT / path


def existing_path(value: str) -> Path | None:
    if not value:
        return None
    candidates = [as_root_path(value)]
    if not value.startswith("data/"):
        candidates.append(ROOT / "data" / value)
    for path in candidates:
        if path.exists():
            return path
    return None


def resolve_score_tsv(row: dict[str, str]) -> Path | None:
    """Resolve the annotated score TSV, preferring the score variant in metadata."""
    base = existing_path(row.get("score_midi_tsv_path", ""))
    abcx = existing_path(row.get("score_abcx_path", ""))
    candidates: list[Path] = []
    if abcx is not None:
        if abcx.name == "score_aligned_mini.abcx":
            candidates.append(abcx.parent / "score_aligned_mini.annotated_score.mid.tsv")
        elif abcx.name == "score_aligned.abcx":
            candidates.append(abcx.parent / "score_aligned.annotated_score.mid.tsv")
            candidates.append(abcx.parent / "score.annotated_score.mid.tsv")
        elif abcx.name == "score.abcx":
            candidates.append(abcx.parent / "score.annotated_score.mid.tsv")
    if base is not None:
        candidates.append(base)
        candidates.append(base.parent / "score.annotated_score.mid.tsv")

    perf = existing_path(row.get("performance_tsv_path", ""))
    if perf is not None:
        if abcx is not None and abcx.name == "score_aligned_mini.abcx":
            candidates.append(perf.parent / "score_aligned_mini.annotated_score.mid.tsv")
        else:
            candidates.append(perf.parent / "score_aligned.annotated_score.mid.tsv")
            candidates.append(perf.parent / "score.annotated_score.mid.tsv")
        candidates.append(perf.parent / "score.mid.tsv")

    for path in candidates:
        if path.exists():
            return path
    return None


def root_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_astar_metadata(s_metadata: Path, astar_metadata: Path) -> dict:
    s_header, _ = read_csv(s_metadata)
    astar_header, rows = read_csv(astar_metadata)

    already_matching_header = astar_header == s_header
    if not already_matching_header and "tsv_path" not in astar_header:
        raise RuntimeError(f"{astar_metadata} has no tsv_path column; cannot normalize Astar paths")
    if "score_midi_tsv_path" not in s_header or "interpolation_ratio" not in s_header:
        raise RuntimeError(f"{s_metadata} is missing expected S metadata columns")

    backup = astar_metadata.with_suffix(astar_metadata.suffix + ".bak_before_sft_schema_sync")
    if not backup.exists():
        shutil.copy2(astar_metadata, backup)

    normalized_rows = []
    stats = defaultdict(int)
    for row in rows:
        new_row = {field: row.get(field, "") for field in s_header}

        perf_path = existing_path(row.get("tsv_path", ""))
        if perf_path is None:
            perf_path = existing_path(row.get("performance_tsv_path", ""))
        if perf_path is not None:
            new_row["performance_tsv_path"] = root_relative(perf_path)
            piece_dir = perf_path.parent
        else:
            piece_dir = existing_path(row.get("performance_tsv_path", "")) or Path()
            piece_dir = piece_dir.parent
            stats["missing_performance_tsv_path"] += 1

        score_rel = (row.get("refined_score_midi_path") or row.get("score_midi_path") or "").strip()
        is_mini = "_mini" in score_rel or "_mini" in (row.get("performance_id") or "")
        score_candidates = []
        if is_mini:
            score_candidates.append(piece_dir / "score_aligned_mini.annotated_score.mid.tsv")
        else:
            score_candidates.append(piece_dir / "score_aligned.annotated_score.mid.tsv")
        score_candidates.extend(
            [
                piece_dir / "score.annotated_score.mid.tsv",
                piece_dir / "score.mid.tsv",
            ]
        )
        score_path = next((p for p in score_candidates if p.exists()), None)
        if score_path is not None:
            new_row["score_midi_tsv_path"] = root_relative(score_path)
        else:
            stats["missing_score_midi_tsv_path"] += 1

        interp_path = existing_path(row.get("interpretation_path", ""))
        if interp_path is None and piece_dir:
            candidate = piece_dir / "piece_interpretation.json"
            if candidate.exists():
                interp_path = candidate
        if interp_path is not None:
            new_row["interpretation_path"] = root_relative(interp_path)
        else:
            stats["missing_interpretation_path"] += 1

        score_abcx = None
        preferred_abcx_names = ("score_aligned_mini.abcx", "score.abcx") if is_mini else ("score_aligned.abcx", "score.abcx")
        if piece_dir:
            for name in preferred_abcx_names:
                candidate = piece_dir / name
                if candidate.exists():
                    score_abcx = candidate
                    break
        if score_abcx is None:
            score_abcx = existing_path(row.get("score_abcx_path", ""))
        if score_abcx is not None:
            new_row["score_abcx_path"] = root_relative(score_abcx)

        if not new_row.get("interpolation_ratio"):
            note_count = parse_float(row.get("refined_performance_note_count", ""))
            interp_count = parse_float(row.get("refined_performance_interpolated_note_count", ""))
            if note_count and interp_count is not None:
                new_row["interpolation_ratio"] = str(interp_count / note_count)

        normalized_rows.append(new_row)

    write_csv(astar_metadata, s_header, normalized_rows)
    new_header, _ = read_csv(astar_metadata)
    if new_header != s_header:
        raise RuntimeError("Astar metadata normalization failed: headers still differ from S metadata")

    return {
        "path": root_relative(astar_metadata),
        "backup": root_relative(backup),
        "rows": len(normalized_rows),
        "already_normalized": already_matching_header,
        "stats": dict(stats),
    }


def parse_float(value: str) -> float | None:
    try:
        if value == "":
            return None
        return float(value)
    except ValueError:
        return None


def load_tokenizer(tokenizer_path: str):
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True, local_files_only=True)
    add_lm_midi_tokens(tokenizer, mode="full")
    return tokenizer


def count_tokens(tokenizer, text: str) -> int:
    tag_count = len(TOKEN_RE.findall(text))
    plain = TOKEN_RE.sub("", text)
    return tag_count + len(tokenizer(plain, add_special_tokens=False)["input_ids"])


def is_measure_line(line: str) -> bool:
    return bool(MEASURE_RE.fullmatch(line.split("\t", 1)[0].strip()))


def is_phrase_line(line: str) -> bool:
    return bool(PHRASE_RE.fullmatch(line.split("\t", 1)[0].strip()))


def normalize_structural_line(line: str) -> str:
    parts = line.rstrip("\n").split("\t")
    if len(parts) == 4 and re.fullmatch(r"[HM]\d+", parts[0]):
        parts[0] = parts[0][0]
        return "\t".join(parts)
    return line.rstrip("\n")


def read_event_lines(path: Path) -> list[str]:
    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(normalize_structural_line(raw_line))
    return lines


def extract_score_header_groups(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    header = []
    body_start = 0
    for idx, line in enumerate(lines):
        if is_phrase_line(line) or is_measure_line(line):
            body_start = idx
            break
        header.append(line)
    else:
        body_start = len(lines)
    return header, split_measure_groups(lines[body_start:])


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
    normalized = []
    for line in group:
        if is_measure_line(line):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 4:
                parts[1] = str(safe_measure_idx)
                normalized.append("\t".join(parts))
                continue
        normalized.append(line)
    return normalized


def render_midi(groups: list[list[str]], header_lines: list[str] | None = None) -> str:
    lines = list(header_lines or [])
    for idx, group in enumerate(groups):
        lines.extend(with_measure_index(group, idx))
    return lm_midi_tsv_to_tokens("\n".join(lines), wrap=True, pretty=False)


@lru_cache(maxsize=4096)
def load_interpretation_fields_cached(path_str: str) -> tuple[str, str]:
    path = Path(path_str)
    if not path.exists():
        return "", ""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "", ""
    interpretation = (obj.get("piece_interpretation") or "").strip()
    performance = (obj.get("performance_concept") or "").strip()
    return interpretation, performance


def load_interpretation_fields(path: Path | None) -> tuple[str, str]:
    if path is None:
        return "", ""
    return load_interpretation_fields_cached(str(path))


@lru_cache(maxsize=4096)
def load_score_parts(path_str: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    header, groups = extract_score_header_groups(read_event_lines(Path(path_str)))
    return tuple(header), tuple(tuple(group) for group in groups)


def load_score(path: Path) -> tuple[list[str], list[list[str]]]:
    header, groups = load_score_parts(str(path))
    return list(header), [list(group) for group in groups]


@lru_cache(maxsize=4096)
def load_score_token_parts(path_str: str) -> tuple[int, tuple[int, ...]]:
    header, groups = load_score(Path(path_str))
    return header_token_count(header), tuple(group_token_count(group) for group in groups)


def load_performance(path: Path) -> list[list[str]]:
    return split_measure_groups(read_event_lines(path))


def group_token_count(group: list[str]) -> int:
    text = lm_midi_tsv_to_tokens("\n".join(with_measure_index(group, 0)), wrap=False, pretty=False)
    return len(TOKEN_RE.findall(text))


def header_token_count(header_lines: list[str]) -> int:
    if not header_lines:
        return 0
    text = lm_midi_tsv_to_tokens("\n".join(header_lines), wrap=False, pretty=False)
    return len(TOKEN_RE.findall(text))


def make_input_prefix(row: dict[str, str], interpretation: str, performance: str) -> str:
    return "\n".join(
        [
            "[task]",
            TASK_TEXT,
            "",
            "[score head]",
            f"Composer: {normalize_piece_text(row.get('composer', ''))}",
            f"Composition: {normalize_piece_text(row.get('composition', ''))}",
            f"Movement: {normalize_piece_text(row.get('movement', ''))}",
            f"Interpretation: {interpretation}",
            f"Performance: {performance}",
            "",
        ]
    )


def build_samples_for_row(
    row: dict[str, str],
    source_name: str,
    tokenizer,
    max_length: int,
) -> tuple[list[dict], list[dict]]:
    errors = []
    score_path = resolve_score_tsv(row)
    perf_path = existing_path(row.get("performance_tsv_path", ""))
    interp_path = existing_path(row.get("interpretation_path", ""))
    if score_path is None:
        return [], [{"id": row.get("id", ""), "error": "missing score_midi_tsv_path"}]
    if perf_path is None:
        return [], [{"id": row.get("id", ""), "error": "missing performance_tsv_path"}]

    try:
        score_header, score_groups = load_score(score_path)
        perf_groups = load_performance(perf_path)
    except Exception as exc:
        return [], [{"id": row.get("id", ""), "error": repr(exc)}]

    if not score_groups or not perf_groups:
        return [], [{"id": row.get("id", ""), "error": "empty score or performance measures"}]

    if len(score_groups) != len(perf_groups):
        return [], [
            {
                "id": row.get("id", ""),
                "score_measures": len(score_groups),
                "performance_measures": len(perf_groups),
                "error": "measure_count_mismatch",
            }
        ]

    n_measures = len(score_groups)
    interpretation, performance = load_interpretation_fields(interp_path)
    if not interpretation or not performance:
        return [], [
            {
                "id": row.get("id", ""),
                "interpretation_path": root_relative(interp_path) if interp_path else "",
                "has_piece_interpretation": bool(interpretation),
                "has_performance_concept": bool(performance),
                "error": "missing_interpretation_or_performance_concept",
            }
        ]
    prefix = make_input_prefix(row, interpretation, performance)
    prefix_tokens = count_tokens(tokenizer, prefix)
    score_header_tokens, score_group_tokens_tuple = load_score_token_parts(str(score_path))
    score_group_tokens = list(score_group_tokens_tuple)
    perf_group_tokens = [group_token_count(group) for group in perf_groups[:n_measures]]
    samples = []
    measure_idx = 0
    while measure_idx < n_measures:
        current_score = []
        current_perf = []
        current_score_tokens = 2 + score_header_tokens
        current_perf_tokens = 2
        last_good = None
        cursor = measure_idx
        while cursor < n_measures:
            current_score.append(score_groups[cursor])
            current_perf.append(perf_groups[cursor])
            current_score_tokens += score_group_tokens[cursor]
            current_perf_tokens += perf_group_tokens[cursor]
            input_tokens = prefix_tokens + current_score_tokens
            output_tokens = current_perf_tokens
            total_tokens = input_tokens + output_tokens
            if total_tokens <= max_length:
                last_good = (cursor + 1, input_tokens, output_tokens, total_tokens)
                cursor += 1
                continue
            break

        if last_good is None:
            # Single measure is too large; skip it to satisfy the hard filter.
            one_score = [score_groups[measure_idx]]
            one_perf = [perf_groups[measure_idx]]
            input_text = prefix + render_midi(one_score, score_header)
            output_text = render_midi(one_perf)
            errors.append(
                {
                    "id": row.get("id", ""),
                    "measure": measure_idx,
                    "input_tokens": count_tokens(tokenizer, input_text),
                    "output_tokens": count_tokens(tokenizer, output_text),
                    "error": "single_measure_exceeds_max_length",
                }
            )
            measure_idx += 1
            continue

        end_idx, input_tokens, output_tokens, total_tokens = last_good
        num_measures = end_idx - measure_idx
        input_text = prefix + render_midi(score_groups[measure_idx:end_idx], score_header)
        output_text = render_midi(perf_groups[measure_idx:end_idx])
        sample_id = f"{row.get('id', '')}_{row.get('performance_id', '')}_m{measure_idx:04d}_m{end_idx - 1:04d}"
        if input_text and output_text and total_tokens <= max_length and num_measures > 0:
            samples.append(
                {
                    "sample_id": sample_id,
                    "source": source_name,
                    "piece_id": row.get("score_id") or row.get("id", ""),
                    "performance_id": row.get("performance_id", ""),
                    "composer": normalize_piece_text(row.get("composer", "")),
                    "composition": normalize_piece_text(row.get("composition", "")),
                    "movement": normalize_piece_text(row.get("movement", "")),
                    "measure_start": measure_idx,
                    "measure_end": end_idx - 1,
                    "num_measures": num_measures,
                    "input": input_text,
                    "output": output_text,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "split": row.get("split") or "train",
                }
            )
        measure_idx = end_idx

    return samples, errors


def build_raw(metadata_path: Path, output_path: Path, source_name: str, tokenizer, max_length: int) -> dict:
    _, rows = read_csv(metadata_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    stats = {
        "metadata": root_relative(metadata_path),
        "output": root_relative(output_path),
        "source": source_name,
        "rows": len(rows),
        "samples": 0,
        "token_lengths": [],
        "splits": defaultdict(int),
        "pieces": set(),
    }
    with output_path.open("w", encoding="utf-8") as f:
        for idx, row in enumerate(rows, 1):
            samples, row_errors = build_samples_for_row(row, source_name, tokenizer, max_length)
            errors.extend(row_errors)
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                stats["samples"] += 1
                stats["token_lengths"].append(sample["total_tokens"])
                stats["splits"][sample["split"]] += 1
                stats["pieces"].add(sample["piece_id"])
            if idx % 5000 == 0:
                print(f"  {source_name}: processed {idx:,}/{len(rows):,} rows, samples={stats['samples']:,}")

    error_path = output_path.with_suffix(".errors.jsonl")
    with error_path.open("w", encoding="utf-8") as f:
        for error in errors:
            f.write(json.dumps(error, ensure_ascii=False) + "\n")

    lengths = sorted(stats.pop("token_lengths"))
    pieces = stats.pop("pieces")
    stats["unique_pieces"] = len(pieces)
    stats["splits"] = dict(stats["splits"])
    stats["errors"] = len(errors)
    stats["error_path"] = root_relative(error_path)
    stats["token_stats"] = token_stats(lengths)
    return stats


def token_stats(lengths: list[int]) -> dict:
    if not lengths:
        return {}
    return {
        "min": lengths[0],
        "max": lengths[-1],
        "avg": round(sum(lengths) / len(lengths), 2),
        "p50": percentile(lengths, 0.50),
        "p95": percentile(lengths, 0.95),
        "p99": percentile(lengths, 0.99),
    }


def percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    idx = min(len(values) - 1, int(len(values) * q))
    return values[idx]


def read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def shuffle_file(input_path: Path, output_path: Path, seed: int) -> dict:
    records = read_jsonl(input_path)
    random.Random(seed).shuffle(records)
    count = write_jsonl(output_path, records)
    return {"input": root_relative(input_path), "output": root_relative(output_path), "samples": count}


def write_rounds(s_shuffled: Path, astar_shuffled: Path, rounds_dir: Path) -> dict:
    rounds_dir.mkdir(parents=True, exist_ok=True)
    s_records = read_jsonl(s_shuffled)
    astar_records = read_jsonl(astar_shuffled)

    val_records = [r for r in s_records + astar_records if r.get("split") == "val"][:3000]
    test_records = [r for r in s_records + astar_records if r.get("split") == "test"]
    s_train = [r for r in s_records if r.get("split") == "train"]
    astar_train = [r for r in astar_records if r.get("split") == "train"]

    summary = {}
    for name, part in split_evenly(s_train, 2, "train_S"):
        summary[f"{name}.jsonl"] = write_jsonl(rounds_dir / f"{name}.jsonl", part)
    for name, part in split_evenly(astar_train, 2, "train_Astar"):
        summary[f"{name}.jsonl"] = write_jsonl(rounds_dir / f"{name}.jsonl", part)
    summary["val.jsonl"] = write_jsonl(rounds_dir / "val.jsonl", val_records)
    summary["test.jsonl"] = write_jsonl(rounds_dir / "test.jsonl", test_records)
    return summary


def split_evenly(records: list[dict], n: int, prefix: str) -> Iterable[tuple[str, list[dict]]]:
    base, extra = divmod(len(records), n)
    start = 0
    for idx in range(n):
        size = base + (1 if idx < extra else 0)
        yield f"{prefix}{idx + 1}", records[start : start + size]
        start += size


def validate_headers(s_metadata: Path, astar_metadata: Path) -> None:
    s_header, _ = read_csv(s_metadata)
    astar_header, _ = read_csv(astar_metadata)
    if s_header != astar_header:
        only_s = [c for c in s_header if c not in astar_header]
        only_astar = [c for c in astar_header if c not in s_header]
        raise RuntimeError(
            "metadata headers differ after normalization: "
            f"only_s={only_s}, only_astar={only_astar}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s-metadata", type=Path, default=ROOT / "data" / "performance_S_metadata.csv")
    parser.add_argument(
        "--astar-metadata",
        type=Path,
        default=ROOT / "data" / "performance_Astar_metadata_updated.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "CorporaV2" / "sft")
    parser.add_argument("--tokenizer", default=str(ROOT / "Qwen3.5-0.8B-LM-MIDI-Resized"))
    parser.add_argument("--max-length", type=int, default=MAX_LENGTH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--skip-normalize-astar", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "max_length": args.max_length,
        "seed": args.seed,
        "tokenizer": args.tokenizer,
    }

    if not args.skip_normalize_astar:
        print("Normalizing Astar metadata schema...")
        summary["astar_metadata_normalization"] = normalize_astar_metadata(args.s_metadata, args.astar_metadata)

    validate_headers(args.s_metadata, args.astar_metadata)

    print("Loading tokenizer...")
    tokenizer = load_tokenizer(args.tokenizer)

    raw_s = args.output_dir / "epr_S_4096_raw.jsonl"
    raw_astar = args.output_dir / "epr_Astar_4096_raw.jsonl"
    print("Building S raw pool...")
    summary["epr_S_4096_raw.jsonl"] = build_raw(args.s_metadata, raw_s, "S", tokenizer, args.max_length)
    print("Building Astar raw pool...")
    summary["epr_Astar_4096_raw.jsonl"] = build_raw(args.astar_metadata, raw_astar, "Astar", tokenizer, args.max_length)

    print("Shuffling raw pools...")
    shuffled_s = args.output_dir / "epr_S_4096_shuffled.jsonl"
    shuffled_astar = args.output_dir / "epr_Astar_4096_shuffled.jsonl"
    summary["epr_S_4096_shuffled.jsonl"] = shuffle_file(raw_s, shuffled_s, args.seed)
    summary["epr_Astar_4096_shuffled.jsonl"] = shuffle_file(raw_astar, shuffled_astar, args.seed + 1)

    print("Writing round splits...")
    rounds_dir = args.output_dir / "sft_rounds"
    summary["sft_rounds"] = write_rounds(shuffled_s, shuffled_astar, rounds_dir)

    summary_path = args.output_dir / "build_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. Summary: {root_relative(summary_path)}")


if __name__ == "__main__":
    main()
