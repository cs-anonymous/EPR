#!/usr/bin/env python3
"""Two-stage ASAP pipeline for ABCX-aligned EPR data.

Stage 1: generate one JSON manifest per ABCX score file.
Stage 2: use those manifests to project ASAP metadata/annotations onto
         score/performance aligned piece JSONs.

The design is intentionally simple:
- segment only on ABCX bar boundaries
- aim for 8-16 measures and 20-40 seconds
- no overlap

Usage examples:
  # Stage 1
  python asap_abcx_pipeline.py manifest \
    --abcx-root /home/sy/2026/Music/EPR/data/abc_from_xml \
    --outdir /home/sy/2026/Music/EPR/data/abcx_manifests

  # Stage 2
  python asap_abcx_pipeline.py asap \
    --manifests-root /home/sy/2026/Music/EPR/data/abcx_manifests \
    --asap-root /home/sy/2026/Music/data/audio_symbolic_alignment/asap-dataset \
    --outdir /home/sy/2026/Music/EPR/data/asap_aligned_json
"""

from __future__ import annotations

import argparse
import csv
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
M_RE = re.compile(r"^M:\s*(.+)$")
Q_RE = re.compile(r"^Q:\s*([0-9]+(?:/[0-9]+)?)\s*=\s*([0-9.]+)\s*$")
TSV_META_RE = re.compile(r"^#\s*([A-Za-z_]+)=(.*)$")


@dataclass
class RowRecord:
    line_no: int
    text: str
    measures: int
    suffix: str


@dataclass
class MeasureRecord:
    measure_no: int
    row_line_no: int
    row_text: str
    suffix: str
    is_row_end: bool


@dataclass
class SegmentRecord:
    id: int
    measure_start: int
    measure_end: int
    sec_start: float
    sec_end: float
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


def parse_abcx_header(lines: list[str]) -> tuple[Fraction, float, str]:
    meter = Fraction(4, 4)
    qpm = 120.0
    key = ""
    for line in lines:
        s = line.strip()
        m = M_RE.match(s)
        if m:
            meter = parse_meter(m.group(1))
        q = Q_RE.match(s)
        if q:
            beat_len = parse_fraction(q.group(1))
            bpm = float(q.group(2))
            # Convert the printed beat unit to quarter-note seconds.
            qpm = bpm * float(beat_len / Fraction(1, 4))
        if s.startswith("K:") and not key:
            key = s[2:].strip()
    return meter, qpm, key


def measure_seconds(meter: Fraction, qpm: float) -> float:
    beats_per_measure = float(meter.numerator * 4 / meter.denominator)
    quarter_seconds = 60.0 / qpm
    return beats_per_measure * quarter_seconds


def is_music_row(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    if s.startswith("%") or s.startswith("%%"):
        return False
    if FIELD_RE.match(s):
        return False
    return "|" in s or ";" in s


def extract_rows_and_measures(abcx_text: str) -> tuple[list[str], list[RowRecord], list[MeasureRecord]]:
    lines = abcx_text.replace("\r\n", "\n").split("\n")
    header: list[str] = []
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
    measures: list[MeasureRecord] = []
    measure_no = 1
    for idx, line in enumerate(body, start=len(header) + 1):
        if not is_music_row(line):
            continue
        row_measures = split_abc_measures(strip_comment(line))
        if not row_measures:
            continue
        row_measure_count = len(row_measures)
        rows.append(
            RowRecord(
                line_no=idx,
                text=line,
                measures=row_measure_count,
                suffix=row_measures[-1].suffix,
            )
        )
        for local_index, measure in enumerate(row_measures, start=1):
            measures.append(
                MeasureRecord(
                    measure_no=measure_no,
                    row_line_no=idx,
                    row_text=line,
                    suffix=measure.suffix if local_index == row_measure_count else "",
                    is_row_end=local_index == row_measure_count,
                )
            )
            measure_no += 1
    return header, rows, measures


def phrase_bonus(measure: MeasureRecord) -> int:
    score = 0
    if measure.suffix in {":|", "|]", "||", ":||"}:
        score += 3
    if "!fermata!" in measure.row_text:
        score += 2
    if measure.row_text.rstrip().endswith("z") or " z" in measure.row_text:
        score += 1
    return score


def select_segments(
    measures: list[MeasureRecord],
    sec_per_measure: float,
    min_measures: int,
    max_measures: int,
    target_seconds: float,
    min_seconds: float,
    max_seconds: float,
) -> list[SegmentRecord]:
    if not measures:
        return []

    segments: list[SegmentRecord] = []
    start_idx = 0
    target_mid_measures = (min_measures + max_measures) / 2

    while start_idx < len(measures):
        remaining_measures = len(measures) - start_idx
        if remaining_measures <= min_measures:
            end_idx = len(measures) - 1
            chosen_measures = remaining_measures
            note = "tail"
        else:
            best: Optional[tuple[float, int, int]] = None
            for end_idx in range(start_idx, len(measures)):
                cumulative = end_idx - start_idx + 1
                cumulative_sec = cumulative * sec_per_measure
                if cumulative < min_measures or cumulative_sec < min_seconds:
                    continue
                if cumulative > max_measures and cumulative_sec > max_seconds:
                    break
                score = -abs(cumulative_sec - target_seconds)
                score -= 0.25 * abs(cumulative - target_mid_measures)
                score += 0.35 * phrase_bonus(measures[end_idx])
                candidate = (score, end_idx, cumulative)
                if best is None or candidate > best:
                    best = candidate

            if best is None:
                end_idx = start_idx
                for i in range(start_idx, len(measures)):
                    if i - start_idx + 1 >= max_measures:
                        end_idx = i
                        break
                else:
                    end_idx = len(measures) - 1
                chosen_measures = end_idx - start_idx + 1
                note = "fallback"
            else:
                _, end_idx, chosen_measures = best
                note = ""

        segment_measures = measures[start_idx:end_idx + 1]
        segments.append(
            SegmentRecord(
                id=len(segments) + 1,
                measure_start=segment_measures[0].measure_no,
                measure_end=segment_measures[-1].measure_no,
                sec_start=(segment_measures[0].measure_no - 1) * sec_per_measure,
                sec_end=segment_measures[-1].measure_no * sec_per_measure,
                measure_count=chosen_measures,
                note=note,
            )
        )
        start_idx = end_idx + 1

    return segments


def expand_measure_map(value: object) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, int):
        return {value}
    if isinstance(value, str):
        items = []
        for token in value.split("-"):
            token = token.strip()
            if token:
                try:
                    items.append(int(token))
                except ValueError:
                    pass
        return set(items)
    if isinstance(value, list):
        out = set()
        for item in value:
            out |= expand_measure_map(item)
        return out
    return set()


def read_annotations(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_metadata(metadata_csv: Path) -> list[dict]:
    with metadata_csv.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_score_downbeats(annotation: dict, aligned_key: str) -> tuple[list[float], list[float], list[object]]:
    score_downbeats = annotation.get("midi_score_downbeats", []) or []
    perf_downbeats = annotation.get("performance_downbeats", []) or []
    score_map = annotation.get("downbeats_score_map", []) or []
    if aligned_key not in annotation:
        raise KeyError(f"Missing ASAP annotation entry for {aligned_key}")
    return score_downbeats, perf_downbeats, score_map


def find_time_for_measure(
    downbeats: list[float],
    measure_map: list[object],
    measure_no_zero_based: int,
    fallback_sec_per_measure: float,
) -> float:
    if measure_no_zero_based == 0 and downbeats:
        return float(downbeats[0])
    for idx, item in enumerate(measure_map):
        if measure_no_zero_based in expand_measure_map(item):
            if idx < len(downbeats):
                return float(downbeats[idx])
    if measure_no_zero_based < len(downbeats):
        return float(downbeats[measure_no_zero_based])
    if downbeats:
        return float(downbeats[-1] + fallback_sec_per_measure)
    return measure_no_zero_based * fallback_sec_per_measure


def build_piece_manifest(abcx_path: Path, outdir: Path, min_measures: int, max_measures: int,
                         target_seconds: float, min_seconds: float, max_seconds: float) -> Path:
    abcx_text = abcx_path.read_text(encoding="utf-8")
    header, rows, measures = extract_rows_and_measures(abcx_text)
    meter, qpm, key = parse_abcx_header(header)
    sec_per_measure = measure_seconds(meter, qpm)
    segments = select_segments(measures, sec_per_measure, min_measures, max_measures, target_seconds, min_seconds, max_seconds)

    rel_piece = abcx_path.parent.relative_to(Path(abcx_root_global)).as_posix()
    manifest = {
        "source_abcx": str(abcx_path),
        "source_abc": str(abcx_path.with_suffix(".abc")),
        "piece_relpath": rel_piece,
        "composer": rel_piece.split("/")[0] if "/" in rel_piece else rel_piece,
        "piece_name": abcx_path.stem,
        "meter": f"{meter.numerator}/{meter.denominator}",
        "qpm": qpm,
        "key": key,
        "measure_seconds_est": sec_per_measure,
        "segments": [asdict(s) for s in segments],
    }

    piece_out = outdir / rel_piece / f"{abcx_path.stem}.json"
    piece_out.parent.mkdir(parents=True, exist_ok=True)
    piece_out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return piece_out


def stage_manifest(args: argparse.Namespace) -> int:
    global abcx_root_global
    abcx_root_global = str(Path(args.abcx_root).expanduser().resolve())
    root = Path(abcx_root_global)
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    files = sorted(root.rglob("*.abcx"))
    if args.limit:
        files = files[: args.limit]

    count = 0
    for path in files:
        build_piece_manifest(
            path,
            outdir,
            min_measures=args.min_measures,
            max_measures=args.max_measures,
            target_seconds=args.target_seconds,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
        )
        count += 1
        if count % 20 == 0 or count == len(files):
            print(f"[{count}/{len(files)}] manifest written", flush=True)

    index = {
        "abcx_root": str(root),
        "count": len(files),
        "outdir": str(outdir),
    }
    (outdir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"done: {len(files)} manifests -> {outdir}")
    return 0


def stage_asap(args: argparse.Namespace) -> int:
    manifests_root = Path(args.manifests_root).expanduser().resolve()
    asap_root = Path(args.asap_root).expanduser().resolve()
    metadata_csv = Path(args.metadata).expanduser().resolve()
    annotations_json = Path(args.annotations).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    metadata_rows = load_metadata(metadata_csv)
    metadata_by_folder: dict[str, list[dict]] = {}
    for row in metadata_rows:
        metadata_by_folder.setdefault(row["folder"], []).append(row)

    annotations = read_annotations(annotations_json)
    manifest_files = sorted(manifests_root.rglob("*.json"))
    manifest_files = [p for p in manifest_files if p.name not in {"index.json"}]
    if args.limit:
        manifest_files = manifest_files[: args.limit]

    processed = 0
    matched = 0
    skipped = 0

    for manifest_path in manifest_files:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        piece_relpath = manifest.get("piece_relpath")
        if not piece_relpath or piece_relpath not in metadata_by_folder:
            skipped += 1
            continue

        piece_rows = metadata_by_folder[piece_relpath]
        score_midi_rel = piece_rows[0]["midi_score"]
        score_annotations_rel = piece_rows[0]["midi_score_annotations"]

        aligned_performances: list[dict] = []
        for row in piece_rows:
            perf_rel = row["midi_performance"]
            ann = annotations.get(perf_rel)
            if ann is None:
                continue
            if str(ann.get("score_and_performance_aligned", True)).lower() not in {"true", "1"}:
                continue

            score_downbeats = ann.get("midi_score_downbeats", []) or []
            perf_downbeats = ann.get("performance_downbeats", []) or []
            score_map = ann.get("downbeats_score_map", []) or []
            if not score_downbeats or not perf_downbeats:
                continue

            perf_entry = {
                "midi_performance": perf_rel,
                "performance_annotations": row["performance_annotations"],
                "audio_performance": row.get("audio_performance", ""),
                "maestro_midi_performance": row.get("maestro_midi_performance", ""),
                "maestro_audio_performance": row.get("maestro_audio_performance", ""),
                "start": row.get("start", ""),
                "end": row.get("end", ""),
                "segments": [],
            }

            for seg in manifest["segments"]:
                s0 = seg["measure_start"] - 1
                e0 = seg["measure_end"]
                score_start = find_time_for_measure(score_downbeats, score_map, s0, manifest["measure_seconds_est"])
                score_end = find_time_for_measure(score_downbeats, score_map, e0, manifest["measure_seconds_est"])
                perf_start = find_time_for_measure(perf_downbeats, score_map, s0, manifest["measure_seconds_est"])
                perf_end = find_time_for_measure(perf_downbeats, score_map, e0, manifest["measure_seconds_est"])

                perf_entry["segments"].append({
                    "segment_id": seg["id"],
                    "measure_start": seg["measure_start"],
                    "measure_end": seg["measure_end"],
                    "score_start_sec": score_start,
                    "score_end_sec": score_end,
                    "performance_start_sec": perf_start,
                    "performance_end_sec": perf_end,
                })

            aligned_performances.append(perf_entry)

        if not aligned_performances:
            skipped += 1
            continue

        out_piece = outdir / piece_relpath / f"{manifest['piece_name']}.json"
        out_piece.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "score": {
                "abcx_manifest": str(manifest_path),
                "abcx_path": manifest["source_abcx"],
                "abc_path": manifest["source_abc"],
                "midi_score": score_midi_rel,
                "midi_score_annotations": score_annotations_rel,
                "piece_relpath": piece_relpath,
                "meter": manifest["meter"],
                "qpm": manifest["qpm"],
                "measure_seconds_est": manifest["measure_seconds_est"],
                "segments": manifest["segments"],
            },
            "performances": aligned_performances,
        }
        out_piece.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        processed += 1
        matched += len(aligned_performances)
        if processed % 20 == 0:
            print(f"[{processed}] piece json written", flush=True)

    summary = {
        "manifests_root": str(manifests_root),
        "asap_root": str(asap_root),
        "processed_pieces": processed,
        "matched_performances": matched,
        "skipped_pieces": skipped,
    }
    (outdir / "index.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ABCX manifests and ASAP alignment JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser("manifest", help="Generate per-ABCX piece manifests")
    p_manifest.add_argument("--abcx-root", required=True, help="Root directory containing .abcx files")
    p_manifest.add_argument("--outdir", required=True, help="Output directory for manifests")
    p_manifest.add_argument("--min-measures", type=int, default=8)
    p_manifest.add_argument("--max-measures", type=int, default=16)
    p_manifest.add_argument("--target-seconds", type=float, default=30.0)
    p_manifest.add_argument("--min-seconds", type=float, default=20.0)
    p_manifest.add_argument("--max-seconds", type=float, default=40.0)
    p_manifest.add_argument("--limit", type=int, default=0, help="Limit number of files for testing")
    p_manifest.set_defaults(func=stage_manifest)

    p_asap = sub.add_parser("asap", help="Project manifests onto ASAP metadata/annotations")
    p_asap.add_argument("--manifests-root", required=True, help="Directory containing piece manifest JSON files")
    p_asap.add_argument("--asap-root", required=True, help="ASAP dataset root")
    p_asap.add_argument("--metadata", default=None, help="ASAP metadata.csv")
    p_asap.add_argument("--annotations", default=None, help="ASAP asap_annotations.json")
    p_asap.add_argument("--outdir", required=True, help="Output directory for aligned piece JSON")
    p_asap.add_argument("--limit", type=int, default=0, help="Limit number of piece manifests for testing")
    p_asap.set_defaults(func=stage_asap)

    args = parser.parse_args()
    if args.command == "asap":
        asap_root = Path(args.asap_root).expanduser().resolve()
        args.metadata = args.metadata or str(asap_root / "metadata.csv")
        args.annotations = args.annotations or str(asap_root / "asap_annotations.json")

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())