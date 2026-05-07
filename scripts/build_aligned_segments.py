#!/usr/bin/env python3
"""Build aligned ABCX + MIDI-TSV segments on bar boundaries.

Default policy:
- 8–16 measures per segment
- 20–40 seconds per segment
- no overlap
- cut only at ABCX row boundaries

This script reads one ABCX file and one MIDI-TSV file from the same piece,
creates a shared segmentation manifest, and optionally writes per-segment
ABCX / MIDI-TSV files.

Usage:
    python build_aligned_segments.py \
        --abcx piece.abcx \
        --tsv piece.mid.tsv \
        --outdir out/segments
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).resolve().parent
ABCX_SCRIPT_DIR = SCRIPT_DIR.parent / "abcx" / "scripts"
if str(ABCX_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(ABCX_SCRIPT_DIR))

from abc2abcx import split_abc_measures, strip_comment  # type: ignore


FIELD_RE = re.compile(r"^[A-Za-z]:")
ABC_M_RE = re.compile(r"^M:\s*(.+)$")
ABC_Q_RE = re.compile(r"^Q:\s*([0-9]+(?:/[0-9]+)?)\s*=\s*([0-9.]+)\s*$")
TSV_META_RE = re.compile(r"^#\s*([A-Za-z_]+)=(.*)$")


@dataclass
class RowRecord:
    line_no: int
    text: str
    measures: int
    suffix: str


@dataclass
class Segment:
    id: int
    row_start: int
    row_end: int
    line_start: int
    line_end: int
    measure_start: int
    measure_end: int
    tick_start: int
    tick_end: int
    sec_start: float
    sec_end: float
    row_count: int
    measure_count: int
    note: str = ""


def parse_fraction(text: str) -> Fraction:
    match = re.match(r"^(\d+)\s*/\s*(\d+)$", text.strip())
    if not match:
        raise ValueError(f"Invalid fraction: {text}")
    return Fraction(int(match.group(1)), int(match.group(2)))


def parse_meter(text: str) -> Fraction:
    value = text.strip()
    if value == "C":
        return Fraction(4, 4)
    if value == "C|":
        return Fraction(2, 2)
    if "/" in value:
        return parse_fraction(value)
    raise ValueError(f"Unsupported meter: {text}")


def parse_abcx_header(lines: list[str]) -> tuple[Fraction, Fraction]:
    meter = Fraction(4, 4)
    quarter_seconds: Optional[Fraction] = None
    for line in lines:
        s = line.strip()
        if meter == Fraction(4, 4):
            m = ABC_M_RE.match(s)
            if m:
                meter = parse_meter(m.group(1))
        q = ABC_Q_RE.match(s)
        if q and quarter_seconds is None:
            beat_len = parse_fraction(q.group(1))
            bpm = Fraction(int(float(q.group(2)) * 1000), 1000)
            quarter_seconds = Fraction(60, 1) / bpm * (Fraction(1, 4) / beat_len)
    if quarter_seconds is None:
        quarter_seconds = Fraction(1, 2)
    return meter, quarter_seconds


def parse_tsv_meta(lines: list[str]) -> dict:
    meta = {
        "tpq": 480,
        "tick_scale": 1,
        "tempo_us_per_beat": 500_000,
        "time_signature": (4, 4),
    }
    for raw in lines:
        line = raw.strip()
        if not line.startswith("#"):
            continue
        m = TSV_META_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "tpq":
            meta["tpq"] = int(val)
        elif key == "tick_scale":
            meta["tick_scale"] = int(val)
        elif key == "tempo":
            parts = val.split(",")
            if len(parts) >= 2:
                meta["tempo_us_per_beat"] = int(parts[1])
        elif key == "time_signature":
            parts = val.split(",")
            if len(parts) >= 3:
                meta["time_signature"] = (int(parts[1]), int(parts[2]))
    return meta


def measure_seconds_from_meta(meta: dict) -> Fraction:
    numerator, denominator = meta["time_signature"]
    quarter_seconds = Fraction(meta["tempo_us_per_beat"], 1_000_000)
    return Fraction(numerator * 4, denominator) * quarter_seconds


def ticks_per_measure(meta: dict) -> Fraction:
    numerator, denominator = meta["time_signature"]
    return Fraction(meta["tpq"] * numerator * 4, denominator)


def is_music_row(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    if s.startswith("%") or s.startswith("%%"):
        return False
    if FIELD_RE.match(s):
        return False
    return "|" in s or ";" in s


def extract_rows(abcx_text: str) -> tuple[list[str], list[str], list[RowRecord]]:
    lines = abcx_text.replace("\r\n", "\n").split("\n")
    header: list[str] = []
    body: list[str] = []
    seen_k = False
    for line in lines:
        header.append(line)
        if line.strip().startswith("K:"):
            seen_k = True
            break
    if not seen_k:
        raise ValueError("ABCX file has no K: line")

    body = lines[len(header):]
    rows: list[RowRecord] = []
    for idx, line in enumerate(body, start=len(header) + 1):
        if not is_music_row(line):
            continue
        measures = split_abc_measures(strip_comment(line))
        if not measures:
            continue
        rows.append(
            RowRecord(
                line_no=idx,
                text=line,
                measures=len(measures),
                suffix=measures[-1].suffix,
            )
        )
    return header, body, rows


def phrase_bonus(row: RowRecord) -> int:
    score = 0
    if row.suffix in {":|", "|]", "||", ":||"}:
        score += 3
    if "!fermata!" in row.text:
        score += 2
    if row.text.rstrip().endswith("z") or " z" in row.text:
        score += 1
    return score


def choose_segments(
    rows: list[RowRecord],
    measure_sec: Fraction,
    measure_ticks: Fraction,
    min_measures: int,
    max_measures: int,
    target_seconds: float,
    min_seconds: float,
    max_seconds: float,
) -> list[Segment]:
    if not rows:
        return []

    total_measures = sum(r.measures for r in rows)
    target_sec = float(target_seconds)
    min_sec = float(min_seconds)
    max_sec = float(max_seconds)
    segment_min_measures = min_measures
    segment_max_measures = max_measures

    segments: list[Segment] = []
    start_idx = 0
    start_measure = 0

    while start_idx < len(rows):
        remaining_measures = sum(r.measures for r in rows[start_idx:])
        if remaining_measures <= segment_min_measures:
            end_idx = len(rows) - 1
            end_measure = total_measures
            sec_span = float(Fraction(remaining_measures, 1) * measure_sec)
            tick_span = int(Fraction(remaining_measures, 1) * measure_ticks)
            segments.append(
                Segment(
                    id=len(segments) + 1,
                    row_start=start_idx + 1,
                    row_end=end_idx + 1,
                    line_start=rows[start_idx].line_no,
                    line_end=rows[end_idx].line_no,
                    measure_start=start_measure + 1,
                    measure_end=end_measure,
                    tick_start=int(Fraction(start_measure, 1) * measure_ticks),
                    tick_end=int(Fraction(end_measure, 1) * measure_ticks),
                    sec_start=float(Fraction(start_measure, 1) * measure_sec),
                    sec_end=float(Fraction(end_measure, 1) * measure_sec),
                    row_count=len(rows) - start_idx,
                    measure_count=remaining_measures,
                    note="tail",
                )
            )
            break

        best: Optional[tuple[float, int, int]] = None
        cum_measures = 0
        for end_idx in range(start_idx, len(rows)):
            cum_measures += rows[end_idx].measures
            cum_sec = float(Fraction(cum_measures, 1) * measure_sec)

            if cum_measures < segment_min_measures or cum_sec < min_sec:
                continue
            if cum_measures > segment_max_measures and cum_sec > max_sec:
                break

            score = -abs(cum_sec - target_sec) - 0.25 * abs(cum_measures - (segment_min_measures + segment_max_measures) / 2)
            score += 0.35 * phrase_bonus(rows[end_idx])

            candidate = (score, end_idx, cum_measures)
            if best is None or candidate > best:
                best = candidate

        if best is None:
            # Fallback: cut at the largest boundary we can reach without
            # exceeding the hard limit too much.
            cum_measures = 0
            end_idx = start_idx
            for i in range(start_idx, len(rows)):
                cum_measures += rows[i].measures
                if cum_measures >= segment_max_measures:
                    end_idx = i
                    break
            else:
                end_idx = len(rows) - 1
            chosen_measures = sum(r.measures for r in rows[start_idx:end_idx + 1])
        else:
            _, end_idx, chosen_measures = best

        end_measure = start_measure + chosen_measures
        segments.append(
            Segment(
                id=len(segments) + 1,
                row_start=start_idx + 1,
                row_end=end_idx + 1,
                line_start=rows[start_idx].line_no,
                line_end=rows[end_idx].line_no,
                measure_start=start_measure + 1,
                measure_end=end_measure,
                tick_start=int(Fraction(start_measure, 1) * measure_ticks),
                tick_end=int(Fraction(end_measure, 1) * measure_ticks),
                sec_start=float(Fraction(start_measure, 1) * measure_sec),
                sec_end=float(Fraction(end_measure, 1) * measure_sec),
                row_count=end_idx - start_idx + 1,
                measure_count=chosen_measures,
                note="",
            )
        )
        start_idx = end_idx + 1
        start_measure = end_measure

    return segments


def parse_tsv_events(tsv_text: str) -> tuple[list[str], list[dict], list[dict], list[int]]:
    lines = tsv_text.replace("\r\n", "\n").split("\n")
    header: list[str] = []
    body_started = False
    current_slice_start = 0
    current_track: Optional[int] = None
    notes: list[dict] = []
    pedals: list[dict] = []
    all_tracks: set[int] = set()

    for line in lines:
        if not body_started:
            header.append(line)
            if not line.strip():
                body_started = True
            continue

        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            header.append(line)
            continue

        parts = line.split("\t")
        if parts[0] == "S" and len(parts) >= 4:
            current_slice_start = int(parts[2])
            continue
        if parts[0] == "T" and len(parts) >= 2:
            current_track = int(parts[1])
            all_tracks.add(current_track)
            continue
        if current_track is None:
            continue
        if parts[0] == "P" and len(parts) >= 3:
            pedals.append(
                {
                    "track": current_track,
                    "t": current_slice_start + int(parts[1]),
                    "val": int(parts[2]),
                }
            )
        elif len(parts) >= 4:
            notes.append(
                {
                    "track": current_track,
                    "pitch": parts[0],
                    "t": current_slice_start + int(parts[1]),
                    "dur": int(parts[2]),
                    "vel": int(parts[3]),
                }
            )

    return header, notes, pedals, sorted(all_tracks)


def slice_tsv(
    tsv_header: list[str],
    notes: list[dict],
    pedals: list[dict],
    tracks: list[int],
    seg_start_tick: int,
    seg_end_tick: int,
    tick_scale: int,
    source_name: str,
    seg: Segment,
) -> str:
    lines: list[str] = []
    for line in tsv_header:
        if line.startswith("# source="):
            lines.append(f"# source={source_name}")
        else:
            lines.append(line)
    lines.append(f"# segment_id={seg.id}")
    lines.append(f"# measure_range={seg.measure_start},{seg.measure_end}")
    lines.append(f"# tick_range={seg.tick_start},{seg.tick_end}")
    lines.append(f"# second_range={seg.sec_start:.3f},{seg.sec_end:.3f}")
    lines.append("")
    lines.append(f"S\t1\t0\t{(seg_end_tick - seg_start_tick) // tick_scale}")

    for track in tracks:
        records: list[tuple[int, int, str]] = []
        for note in notes:
            if note["track"] != track:
                continue
            if seg_start_tick <= note["t"] < seg_end_tick:
                local_t = note["t"] - seg_start_tick
                records.append((note["t"], 1, f"{note['pitch']}\t{local_t // tick_scale}\t{note['dur'] // tick_scale}\t{note['vel']}"))
        for pedal in pedals:
            if pedal["track"] != track:
                continue
            if seg_start_tick <= pedal["t"] < seg_end_tick:
                local_t = pedal["t"] - seg_start_tick
                records.append((pedal["t"], 0, f"P\t{local_t // tick_scale}\t{pedal['val']}"))
        if not records:
            continue
        lines.append(f"T\t{track}")
        for _, _, record in sorted(records, key=lambda item: (item[0], item[1])):
            lines.append(record)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_segment_abcx(full_lines: list[str], rows: list[RowRecord], seg: Segment, out_path: Path) -> None:
    header_end = 0
    for i, line in enumerate(full_lines):
        header_end = i + 1
        if line.strip().startswith("K:"):
            break
    segment_lines = full_lines[seg.line_start - 1:seg.line_end]
    out = full_lines[:header_end] + [f"% segment_id={seg.id}", f"% measure_range={seg.measure_start},{seg.measure_end}"] + segment_lines
    out_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Build aligned ABCX + MIDI-TSV segments.")
    ap.add_argument("--abcx", required=True, help="Input ABCX file")
    ap.add_argument("--tsv", required=True, help="Input MIDI-TSV file")
    ap.add_argument("--outdir", required=True, help="Output directory")
    ap.add_argument("--min-measures", type=int, default=8)
    ap.add_argument("--max-measures", type=int, default=16)
    ap.add_argument("--target-seconds", type=float, default=30.0)
    ap.add_argument("--min-seconds", type=float, default=20.0)
    ap.add_argument("--max-seconds", type=float, default=40.0)
    ap.add_argument("--write-files", action="store_true", help="Write per-segment files")
    args = ap.parse_args()

    abcx_path = Path(args.abcx).expanduser().resolve()
    tsv_path = Path(args.tsv).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    abcx_text = abcx_path.read_text(encoding="utf-8")
    tsv_text = tsv_path.read_text(encoding="utf-8")

    full_lines = abcx_text.replace("\r\n", "\n").split("\n")
    header_lines, body_lines, rows = extract_rows(abcx_text)
    if not rows:
        raise SystemExit("No music rows found in ABCX file")

    abc_meter, abc_quarter_seconds = parse_abcx_header(header_lines)
    tsv_meta = parse_tsv_meta(tsv_text.splitlines())
    if tsv_meta["time_signature"] == (4, 4):
        # Allow ABCX meter to override the default if TSV metadata is absent.
        pass
    meter_n, meter_d = tsv_meta["time_signature"]
    measure_sec = measure_seconds_from_meta(tsv_meta)
    measure_ticks = ticks_per_measure(tsv_meta)

    segments = choose_segments(
        rows=rows,
        measure_sec=measure_sec,
        measure_ticks=measure_ticks,
        min_measures=args.min_measures,
        max_measures=args.max_measures,
        target_seconds=args.target_seconds,
        min_seconds=args.min_seconds,
        max_seconds=args.max_seconds,
    )

    tsv_header, notes, pedals, tracks = parse_tsv_events(tsv_text)
    manifest = {
        "source_abcx": str(abcx_path),
        "source_tsv": str(tsv_path),
        "meter": f"{meter_n}/{meter_d}",
        "measure_seconds": float(measure_sec),
        "measure_ticks": float(measure_ticks),
        "segments": [asdict(seg) for seg in segments],
    }
    (outdir / "segments.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.write_files:
        source_stem = abcx_path.stem
        for seg in segments:
            seg_name = f"{source_stem}.seg{seg.id:04d}"
            seg_abcx = outdir / f"{seg_name}.abcx"
            seg_tsv = outdir / f"{seg_name}.mid.tsv"
            write_segment_abcx(full_lines, rows, seg, seg_abcx)
            seg_tsv.write_text(
                slice_tsv(
                    tsv_header=tsv_header,
                    notes=notes,
                    pedals=pedals,
                    tracks=tracks,
                    seg_start_tick=seg.tick_start,
                    seg_end_tick=seg.tick_end,
                    tick_scale=tsv_meta["tick_scale"],
                    source_name=tsv_path.name,
                    seg=seg,
                ),
                encoding="utf-8",
            )

    print(f"segments: {len(segments)}")
    print(f"manifest: {outdir / 'segments.json'}")
    if args.write_files:
        print(f"files: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())