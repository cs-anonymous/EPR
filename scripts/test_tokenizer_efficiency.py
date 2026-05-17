#!/usr/bin/env python3
"""Compare MIDI performance serialization formats with a Qwen tokenizer.

The current adopted SFT performance format is compact and one-line:

    M<id>:<duration> <note>:<duration>:<timing>:<velocity> P:<timing>:<value>

The parser also accepts the legacy newline/tab-heavy form so the script can
compare old and new layouts on the same sampled musical events. It samples
measure_perf_lang_continuation inputs and reports token counts normalized by
musical note count and event count.
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm
from transformers import AutoTokenizer


def parse_current(text: str) -> dict:
    measures = []
    current = None

    def add_event_from_parts(parts: list[str]) -> None:
        nonlocal current
        if current is None:
            current = {"id": "M0", "duration": "0", "events": []}
            measures.append(current)
        if not parts:
            return
        if parts[0] == "P" and len(parts) >= 3:
            current["events"].append({
                "kind": "pedal",
                "timing": parts[1],
                "velocity": parts[2],
            })
        elif len(parts) == 1 and parts[0].startswith("P:"):
            fields = parts[0].split(":")
            if len(fields) >= 3:
                current["events"].append({
                    "kind": "pedal",
                    "timing": fields[1],
                    "velocity": fields[2],
                })
        elif ":" in parts[0] and len(parts) >= 3:
            pitch, duration = parts[0].split(":", 1)
            current["events"].append({
                "kind": "note",
                "pitch": pitch,
                "duration": duration,
                "timing": parts[1],
                "velocity": parts[2],
            })
        elif len(parts) == 1 and parts[0].count(":") >= 3:
            pitch, duration, timing, velocity = parts[0].split(":", 3)
            current["events"].append({
                "kind": "note",
                "pitch": pitch,
                "duration": duration,
                "timing": timing,
                "velocity": velocity,
            })

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        tokens = line.split()
        if tokens and tokens[0].startswith("M") and ":" in tokens[0]:
            measure_id, duration = tokens[0].split(":", 1)
            current = {"id": measure_id, "duration": duration, "events": []}
            measures.append(current)
            for token in tokens[1:]:
                if token.startswith("M") and ":" in token:
                    measure_id, duration = token.split(":", 1)
                    current = {"id": measure_id, "duration": duration, "events": []}
                    measures.append(current)
                else:
                    add_event_from_parts([token])
            continue

        add_event_from_parts(tokens)

    return {"measures": measures}


def iter_events(measure: dict):
    return measure["events"]


def fmt_event(event: dict, field: str, note_pair: str | None = None) -> str:
    if event["kind"] == "pedal":
        values = ["P", event["timing"], event["velocity"]]
    else:
        if note_pair == "colon":
            values = [f"{event['pitch']}:{event['duration']}", event["timing"], event["velocity"]]
        elif note_pair == "joined":
            values = [f"{event['pitch']}{event['duration']}", event["timing"], event["velocity"]]
        else:
            values = [event["pitch"], event["duration"], event["timing"], event["velocity"]]
    return field.join(values)


def fmt_measure(measure: dict, field: str, note_pair: str | None = None) -> str:
    if note_pair == "colon":
        return f"{measure['id']}:{measure['duration']}"
    return field.join([measure["id"], measure["duration"]])


def line_format(field: str, note_pair: str | None = None) -> str:
    def _format(data: dict) -> str:
        lines = []
        for measure in data["measures"]:
            lines.append(fmt_measure(measure, field, note_pair))
            lines.extend(fmt_event(event, field, note_pair) for event in iter_events(measure))
        return "\n".join(lines)
    return _format


def grouped_format(field: str, event_sep: str, note_pair: str | None = None) -> str:
    def _format(data: dict) -> str:
        chunks = []
        for measure in data["measures"]:
            parts = [fmt_measure(measure, field, note_pair)]
            parts.extend(fmt_event(event, field, note_pair) for event in iter_events(measure))
            chunks.append(event_sep.join(parts))
        return "\n".join(chunks)
    return _format


def one_line_format(field: str, event_sep: str, note_pair: str | None = None) -> str:
    def _format(data: dict) -> str:
        parts = []
        for measure in data["measures"]:
            parts.append(fmt_measure(measure, field, note_pair))
            parts.extend(fmt_event(event, field, note_pair) for event in iter_events(measure))
        return event_sep.join(parts)
    return _format


def legacy_format(data: dict) -> str:
    return line_format(" ", note_pair="colon")(data)


FORMATS = {
    "legacy_colon_space_newline": ("legacy: note colon + spaces, newline events", legacy_format),
    "space_fields_newline": ("spaces for all fields, newline events", line_format(" ")),
    "colon_fields_newline": ("colons for all fields, newline events", line_format(":")),
    "tab_fields_newline": ("tabs for all fields, newline events", line_format("\t")),
    "colon_tab_newline": ("note colon + tabs, newline events", line_format("\t", note_pair="colon")),
    "pipe_fields_newline": ("pipes for all fields, newline events", line_format("|")),
    "semicolon_fields_newline": ("semicolons for all fields, newline events", line_format(";")),
    "comma_fields_newline": ("commas for all fields, newline events", line_format(",")),
    "space_fields_space_events": ("spaces for fields and events, one line", one_line_format(" ", " ")),
    "colon_fields_space_events": ("colon fields, space events, one line", one_line_format(":", " ")),
    "colon_fields_pipe_events": ("colon fields, pipe events, one line", one_line_format(":", "|")),
    "colon_fields_semicolon_events": ("colon fields, semicolon events, one line", one_line_format(":", ";")),
    "tab_fields_pipe_events": ("tab fields, pipe events, one line", one_line_format("\t", "|")),
    "pipe_fields_pipe_events": ("pipes for fields and events, one line", one_line_format("|", "|")),
    "pipe_fields_semicolon_events": ("pipe fields, semicolon events, one line", one_line_format("|", ";")),
    "colon_pair_space_events": ("note colon pair + spaces, one line", one_line_format(" ", " ", note_pair="colon")),
    "colon_pair_pipe_events": ("note colon pair + pipe events, one line", one_line_format(" ", "|", note_pair="colon")),
    "colon_pair_semicolon_events": ("note colon pair + semicolon events, one line", one_line_format(" ", ";", note_pair="colon")),
    "joined_pitch_duration_newline": ("pitch+duration joined, spaces, newline events", line_format(" ", note_pair="joined")),
    "joined_pitch_duration_space_events": ("pitch+duration joined, spaces, one line", one_line_format(" ", " ", note_pair="joined")),
}


def reservoir_sample(path: Path, n: int, rng: random.Random) -> list[dict]:
    sample = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(tqdm(f, desc="Reservoir sample")):
            if i < n:
                sample.append(json.loads(line))
            else:
                j = rng.randint(0, i)
                if j < n:
                    sample[j] = json.loads(line)
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="sft_data/core-s1/measure_perf_lang_continuation.jsonl")
    parser.add_argument("--n-samples", type=int, default=2000)
    parser.add_argument("--tokenizer", default="./Qwen3.5-4B")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="sft_data/tokenizer_efficiency_qwen.csv")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)
    samples = reservoir_sample(Path(args.input), args.n_samples, rng)

    stats = defaultdict(lambda: {
        "tokens": 0,
        "chars": 0,
        "notes": 0,
        "events": 0,
        "pedals": 0,
        "samples": 0,
    })

    for sample in tqdm(samples, desc="Tokenize variants"):
        data = parse_current(sample.get("input", ""))
        notes = sum(1 for m in data["measures"] for e in m["events"] if e["kind"] == "note")
        pedals = sum(1 for m in data["measures"] for e in m["events"] if e["kind"] == "pedal")
        events = notes + pedals
        if notes == 0:
            continue

        for key, (_, formatter) in FORMATS.items():
            text = formatter(data)
            n_tokens = len(tokenizer.encode(text, add_special_tokens=False))
            stats[key]["tokens"] += n_tokens
            stats[key]["chars"] += len(text)
            stats[key]["notes"] += notes
            stats[key]["events"] += events
            stats[key]["pedals"] += pedals
            stats[key]["samples"] += 1

    rows = []
    for key, (desc, _) in FORMATS.items():
        s = stats[key]
        if not s["samples"]:
            continue
        rows.append({
            "format": key,
            "description": desc,
            "samples": s["samples"],
            "tokens": s["tokens"],
            "chars": s["chars"],
            "notes": s["notes"],
            "events": s["events"],
            "pedals": s["pedals"],
            "tokens_per_note": s["tokens"] / s["notes"],
            "tokens_per_event": s["tokens"] / s["events"],
            "chars_per_note": s["chars"] / s["notes"],
        })

    rows.sort(key=lambda row: row["tokens_per_note"])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        header = [
            "rank", "format", "description", "samples", "tokens", "chars",
            "notes", "events", "pedals", "tokens_per_note",
            "tokens_per_event", "chars_per_note",
        ]
        f.write(",".join(header) + "\n")
        for rank, row in enumerate(rows, 1):
            values = [
                rank,
                row["format"],
                json.dumps(row["description"], ensure_ascii=False),
                row["samples"],
                row["tokens"],
                row["chars"],
                row["notes"],
                row["events"],
                row["pedals"],
                f"{row['tokens_per_note']:.6f}",
                f"{row['tokens_per_event']:.6f}",
                f"{row['chars_per_note']:.6f}",
            ]
            f.write(",".join(map(str, values)) + "\n")

    print(f"\nTokenizer: {args.tokenizer}")
    print(f"Input: {args.input}")
    print(f"Samples: {rows[0]['samples'] if rows else 0:,}")
    print(f"Notes: {rows[0]['notes'] if rows else 0:,}")
    print(f"Events: {rows[0]['events'] if rows else 0:,}")
    print(f"Pedals: {rows[0]['pedals'] if rows else 0:,}")
    print(f"CSV: {output}")
    print()
    print(f"{'Rank':>4}  {'Format':<36} {'Tok/Note':>9} {'Tok/Event':>9} {'Chars/Note':>10} {'Tokens':>10}")
    print("-" * 90)
    for rank, row in enumerate(rows, 1):
        print(
            f"{rank:>4}  {row['format']:<36} "
            f"{row['tokens_per_note']:>9.3f} "
            f"{row['tokens_per_event']:>9.3f} "
            f"{row['chars_per_note']:>10.3f} "
            f"{row['tokens']:>10,}"
        )


if __name__ == "__main__":
    main()
