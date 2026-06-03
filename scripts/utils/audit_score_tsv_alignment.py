#!/usr/bin/env python3
"""Audit score MIDI-TSV alignment against score MIDI, ABCX, and MusicXML."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pretty_midi

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import align_score_performance as asp
from scripts.lm_midi_tsv import logic_note_is_lower_staff, logic_note_to_midi_pitch


NOTE_EVENT_RE = re.compile(r"^[A-G]#?-?\d+L?$")


def read_score_structure(path: Path) -> asp.ScoreStructure:
    data = json.loads(path.read_text(encoding="utf-8"))
    return asp.ScoreStructure(
        measures=[asp.ScoreMeasure(**item) for item in data["measures"]],
        phrases=[asp.Phrase(**item) for item in data["phrases"]],
        measure_to_phrase={int(k): v for k, v in data["measure_to_phrase"].items()},
        abcx_measures={int(k): v for k, v in data["abcx_measures"].items()},
        midi_to_abcx={int(k): int(v) for k, v in data["midi_to_abcx"].items()},
        midi_measure_content={int(k): v for k, v in data["midi_measure_content"].items()},
    )


def note_rows_by_measure(tsv_path: Path) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    current_measure = -1
    for line in tsv_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        event = parts[0]
        if event == "M":
            current_measure += 1
            result[current_measure + 1] = []
        elif NOTE_EVENT_RE.fullmatch(event) and current_measure >= 0:
            result[current_measure + 1].append(event)
    return result


def midi_notes_by_measure(
    score_midi_path: Path,
    structure: asp.ScoreStructure,
) -> dict[int, list[pretty_midi.Note]]:
    midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    notes = sorted(
        [note for inst in midi.instruments if not inst.is_drum for note in inst.notes],
        key=asp._score_note_sort_key,
    )
    result: dict[int, list[pretty_midi.Note]] = {}
    for measure in structure.measures:
        result[measure.measure_num] = [
            note for note in notes
            if measure.start_time - 0.01 <= note.start < measure.end_time - 0.01
        ]
    return result


def audit(args: argparse.Namespace) -> int:
    structure = read_score_structure(args.structure)
    tsv_rows = note_rows_by_measure(args.tsv)
    midi_rows = midi_notes_by_measure(args.score_midi, structure)
    expected_staffs = asp.build_measure_note_staffs_from_aligned_abcx(
        args.score_midi,
        structure,
        args.score_abcx,
    )

    errors: list[str] = []
    warnings: list[str] = []
    note_count = 0
    staff_checked = 0
    staff_errors = 0

    for measure in structure.measures:
        mnum = measure.measure_num
        tsv_notes = tsv_rows.get(mnum, [])
        midi_notes = midi_rows.get(mnum, [])
        expected = expected_staffs.get(mnum, [])
        if len(tsv_notes) != len(midi_notes):
            errors.append(
                f"M{mnum}: note count mismatch TSV={len(tsv_notes)} MIDI={len(midi_notes)}"
            )
            continue
        for idx, (event, note) in enumerate(zip(tsv_notes, midi_notes)):
            note_count += 1
            pitch = logic_note_to_midi_pitch(event)
            if pitch != note.pitch:
                errors.append(
                    f"M{mnum} note {idx}: pitch mismatch TSV={event}/{pitch} MIDI={note.pitch}"
                )
            if idx < len(expected) and expected[idx] is not None:
                staff_checked += 1
                got_lower = logic_note_is_lower_staff(event)
                want_lower = expected[idx] == "lower"
                if got_lower != want_lower:
                    staff_errors += 1
                    errors.append(
                        f"M{mnum} note {idx}: staff mismatch TSV={event} expected={expected[idx]}"
                    )

    if args.annotated_tsv and args.annotated_tsv.exists():
        staccato_count = 0
        for line in args.annotated_tsv.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 4 and parts[0] in {"A", "AL"} and parts[1] == "staccato":
                staccato_count += 1
        if staccato_count == 0:
            warnings.append("annotated TSV contains no staccato annotations")
        else:
            print(f"staccato_annotations={staccato_count}")

    print(f"notes_checked={note_count}")
    print(f"staff_checked={staff_checked}")
    print(f"staff_errors={staff_errors}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors[: args.max_errors]:
        print(f"ERROR: {error}")
    if len(errors) > args.max_errors:
        print(f"ERROR: ... {len(errors) - args.max_errors} more")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-midi", type=Path, required=True)
    parser.add_argument("--score-abcx", type=Path, required=True)
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--annotated-tsv", type=Path)
    parser.add_argument("--max-errors", type=int, default=50)
    return audit(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
