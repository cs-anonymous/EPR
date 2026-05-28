#!/usr/bin/env python3
"""Prepare and post-process abcx2pm independent test inference.

The raw abcx2pm test files store task fields, while SWIFT inference expects
`messages`. This helper creates a small messages JSONL for inference and then
decodes compact LM-MIDI predictions into readable MIDI-TSV.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from scripts.lm_midi_tsv import midi_pitch_to_logic_note, semantic_event_to_tsv_rows, tsv_row_to_line


SYSTEM_PROMPT = "You are a music score and performance language model."
TOKEN_RE = re.compile(r"<[^>]+>")


@dataclass
class DecodeStats:
    raw_token_count: int = 0
    used_token_count: int = 0
    truncated_tokens: int = 0
    decoded_events: int = 0
    decoded_rows: int = 0
    notes: int = 0
    pedals: int = 0
    structural: int = 0
    extensions: int = 0
    invalid_events: int = 0
    repairs: list[str] = field(default_factory=list)


def build_user_prompt(record: dict[str, Any]) -> str:
    body = record["score_header"].rstrip() + "\n" + record["score_snip"].rstrip()
    parts = [
        record["instruction"].strip(),
        f"Task type: {record['task_type']}",
        "abcx:",
        body,
    ]
    perf_context = record.get("perf_context") or ""
    if perf_context:
        parts.extend(["performance context:", perf_context.strip()])
    return "\n".join(parts)


def select_records(input_path: Path, count: int, distinct_works: bool) -> list[tuple[int, dict[str, Any]]]:
    selected: list[tuple[int, dict[str, Any]]] = []
    seen_works: set[str] = set()
    with input_path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            record = json.loads(line)
            work_key = "/".join(str(record.get("piece_id", "")).split("/")[:2])
            if distinct_works and work_key in seen_works:
                continue
            seen_works.add(work_key)
            selected.append((idx, record))
            if count > 0 and len(selected) >= count:
                break
    return selected


def cmd_prepare(args: argparse.Namespace) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    infer_path = args.out_dir / "infer_messages.jsonl"
    manifest_path = args.out_dir / "manifest.jsonl"

    selected = select_records(args.input, args.count, args.distinct_works)
    with infer_path.open("w", encoding="utf-8") as infer_out, manifest_path.open("w", encoding="utf-8") as manifest:
        for local_id, (source_index, record) in enumerate(selected):
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(record)},
            ]
            infer_out.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
            manifest.write(
                json.dumps(
                    {
                        "sample_id": f"{local_id:03d}",
                        "source_index": source_index,
                        "piece_id": record.get("piece_id"),
                        "task_type": record.get("task_type"),
                        "target_start_measure_id": record.get("target_start_measure_id"),
                        "target_end_measure_id": record.get("target_end_measure_id"),
                        "target_measure_count": record.get("target_measure_count"),
                        "crosses_phrase_boundary": record.get("crosses_phrase_boundary"),
                        "score_header": record.get("score_header"),
                        "score_snip": record.get("score_snip"),
                        "reference_tokens": record.get("perf_target"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(f"wrote {len(selected)} samples")
    print(f"infer_messages={infer_path}")
    print(f"manifest={manifest_path}")


def token_value(token: str, prefix: str, low: int, high: int) -> int | None:
    if not (token.startswith(prefix) and token.endswith(">")):
        return None
    try:
        value = int(token[len(prefix) : -1])
    except ValueError:
        return None
    if not low <= value <= high:
        return None
    return value


def parse_v(token: str) -> int | None:
    return token_value(token, "<V", 0, 127)


def parse_t(token: str) -> int | None:
    return token_value(token, "<T", 0, 255)


def parse_n(token: str) -> int | None:
    return token_value(token, "<N", 0, 127)


def extract_lm_tokens(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(text or "")
    ignored = {"<MIDI>", "</MIDI>", "<EOS_MIDI>", "<think>", "</think>"}
    return [token for token in tokens if token not in ignored]


def timing_from_token(token: str, pending: int | None, kind: str, stats: DecodeStats) -> tuple[int | None, int | None]:
    if token == "<EXT>":
        if pending is None:
            stats.repairs.append(f"missing {kind} extension replaced with 255")
            return 255, None
        return pending, None
    value = parse_t(token)
    return value, pending


def decode_lm_midi_to_tsv(text: str) -> tuple[str, DecodeStats]:
    tokens = extract_lm_tokens(text)
    stats = DecodeStats(raw_token_count=len(tokens))
    usable_len = len(tokens) - (len(tokens) % 4)
    stats.used_token_count = usable_len
    stats.truncated_tokens = len(tokens) - usable_len
    if stats.truncated_tokens:
        stats.repairs.append(f"truncated {stats.truncated_tokens} dangling token(s)")

    rows: list[tuple[str, str, str, str]] = []
    pending_duration: int | None = None
    pending_offset: int | None = None

    for i in range(0, usable_len, 4):
        event, value_token, duration_token, offset_token = tokens[i : i + 4]
        try:
            if event in {"<EXD>", "<EXO>"}:
                hi = parse_t(duration_token)
                lo = parse_t(offset_token)
                if value_token != "<NIL>" or hi is None or lo is None:
                    raise ValueError("invalid extension event")
                value = hi * 256 + lo
                if event == "<EXD>":
                    pending_duration = value
                else:
                    pending_offset = value
                stats.extensions += 1
                stats.decoded_events += 1
                continue

            value = parse_v(value_token)
            if value is None:
                raise ValueError("invalid value token")

            if event in {"<H>", "<M>"}:
                hi = parse_t(duration_token)
                lo = parse_t(offset_token)
                if hi is None or lo is None:
                    raise ValueError("invalid structural duration")
                duration = hi * 256 + lo
                rows.extend(semantic_event_to_tsv_rows(event.strip("<>"), value, duration, 0))
                stats.structural += 1
            elif event in {"<P>", "<P1>", "<P2>"}:
                if duration_token != "<NIL>":
                    raise ValueError("invalid pedal duration slot")
                offset, pending_offset = timing_from_token(offset_token, pending_offset, "offset", stats)
                if offset is None:
                    raise ValueError("invalid pedal offset")
                rows.extend(semantic_event_to_tsv_rows(event.strip("<>"), value, 0, offset))
                stats.pedals += 1
            else:
                pitch = parse_n(event)
                if pitch is None:
                    raise ValueError("invalid event token")
                duration, pending_duration = timing_from_token(duration_token, pending_duration, "duration", stats)
                offset, pending_offset = timing_from_token(offset_token, pending_offset, "offset", stats)
                if duration is None or offset is None:
                    raise ValueError("invalid note timing")
                rows.extend(semantic_event_to_tsv_rows(midi_pitch_to_logic_note(pitch), value, duration, offset))
                stats.notes += 1

            stats.decoded_events += 1
        except Exception as exc:
            stats.invalid_events += 1
            stats.repairs.append(f"group {i // 4}: {exc}")

    stats.decoded_rows = len(rows)
    header = [
        "# midi-tsv v0.3",
        "# unit=bin",
        "# bin_ms=10",
        "# columns=event\tvalue\tduration\toffset",
        "# pitch=logic-pro-note",
        "# middle_c=C3",
    ]
    return "\n".join([*header, *(tsv_row_to_line(row) for row in rows), ""]), stats


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cmd_postprocess(args: argparse.Namespace) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_jsonl(args.manifest)
    results = load_jsonl(args.results)
    if len(results) != len(manifest):
        raise ValueError(f"result/manifest length mismatch: {len(results)} != {len(manifest)}")

    summary: list[dict[str, Any]] = []
    for meta, result in zip(manifest, results):
        sample_id = meta["sample_id"]
        sample_dir = args.out_dir / sample_id
        response = result.get("response", "")
        reference = meta.get("reference_tokens", "")

        pred_tsv, pred_stats = decode_lm_midi_to_tsv(response)
        ref_tsv, ref_stats = decode_lm_midi_to_tsv(reference)

        write_text(sample_dir / "score.abcx", meta["score_header"].rstrip() + "\n" + meta["score_snip"].rstrip() + "\n")
        write_text(sample_dir / "prediction.lm-midi.txt", response + "\n")
        write_text(sample_dir / "prediction.mid.tsv", pred_tsv)
        write_text(sample_dir / "reference.lm-midi.txt", reference + "\n")
        write_text(sample_dir / "reference.mid.tsv", ref_tsv)

        pred_event_total = pred_stats.notes + pred_stats.pedals + pred_stats.structural
        ref_event_total = ref_stats.notes + ref_stats.pedals + ref_stats.structural
        summary.append(
            {
                "sample_id": sample_id,
                "piece_id": meta.get("piece_id"),
                "source_index": meta.get("source_index"),
                "target": f"{meta.get('target_start_measure_id')}..{meta.get('target_end_measure_id')}",
                "target_measure_count": meta.get("target_measure_count"),
                "prediction_tsv": str(sample_dir / "prediction.mid.tsv"),
                "reference_tsv": str(sample_dir / "reference.mid.tsv"),
                "pred": pred_stats.__dict__,
                "ref": ref_stats.__dict__,
                "pred_ref_event_ratio": (pred_event_total / ref_event_total) if ref_event_total else None,
            }
        )

    summary_path = args.summary_path or (args.out_dir / "summary.json")
    write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote decoded samples: {args.out_dir}")
    print(f"summary={summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    prepare.add_argument("--count", type=int, default=4)
    prepare.add_argument("--distinct-works", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

    post = subparsers.add_parser("postprocess")
    post.add_argument("--manifest", type=Path, required=True)
    post.add_argument("--results", type=Path, required=True)
    post.add_argument("--out-dir", type=Path, required=True)
    post.add_argument("--summary-path", type=Path)
    post.set_defaults(func=cmd_postprocess)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
