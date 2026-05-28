#!/usr/bin/env python3
"""Reconstruct normalized aligned ABCX from annotated score MIDI-TSV v0.4.

This is a best-effort inverse for the aligned-score serialization pipeline:

    raw/aligned ABCX -> score.mid.tsv -> score.annotated_score.mid.tsv

The goal is not byte-identical recovery. Instead, it rebuilds a usable,
normalized aligned ABCX with:

- score header fields (T/C/Z/L/Q/M/K when available)
- phrase / measure markers: <H><Vxxx> and <M><Vxxx>
- two-staff layout: StaffU ; StaffL
- optional multi-layer tracks within one staff joined by &
- core score annotations: dynamics, articulations, ornaments, range spans,
  pedal, fermata, expression
- note/chord durations quantized onto a fixed musical grid
- simple tuplet detection for common triplets

The output is intended to round-trip reasonably back through the forward
pipeline, not to reproduce the exact original notation.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path


BIN_MS = 10
DEFAULT_ABC_UNIT = "1/8"
DEFAULT_UNIT_QL = Fraction(1, 2)  # L:1/8 equals an eighth note = 0.5 quarterLength
DEFAULT_METER = "4/4"
DEFAULT_KEY = "C"
DEFAULT_TEMPO_BPM = 120
GRID_QL = Fraction(1, 24)

# Duration candidates in quarterLength units.
STANDARD_QL = [
    Fraction(1, 8),   # 32nd
    Fraction(1, 4),   # 16th
    Fraction(1, 3),   # triplet 8th
    Fraction(1, 2),   # 8th
    Fraction(2, 3),   # triplet quarter
    Fraction(3, 4),   # dotted 8th
    Fraction(1, 1),   # quarter
    Fraction(3, 2),   # dotted quarter
    Fraction(2, 1),   # half
    Fraction(3, 1),   # dotted half
    Fraction(4, 1),   # whole
]

PITCH_CLASS_TO_SHARP = {
    0: "C",
    1: "^C",
    2: "D",
    3: "^D",
    4: "E",
    5: "F",
    6: "^F",
    7: "G",
    8: "^G",
    9: "A",
    10: "^A",
    11: "B",
}

DYNAMIC_TO_ABC = {
    "pppp": "!pppp!",
    "ppp": "!ppp!",
    "pp": "!pp!",
    "p": "!p!",
    "mp": "!mp!",
    "mf": "!mf!",
    "f": "!f!",
    "ff": "!ff!",
    "fff": "!fff!",
    "ffff": "!ffff!",
}

ARTICULATION_TO_ABC = {
    "accent": "!>!",
    "staccato": "!wedge!",
    "tenuto": "!tenuto!",
    "sfz": "!sfz!",
}

ORNAMENT_TO_ABC = {
    "arpeggio": "!arpeggio!",
    "turn": "!turn!",
}

RANGE_START_TO_ABC = {
    "cre": "!<(!",
    "dim": "!>(!",
    "trill": "!trill(!",
}

RANGE_END_TO_ABC = {
    "cre": "!<)!",
    "dim": "!>)!",
    "trill": "!trill)!",
}

PEDAL_TO_ABC = {
    "down": '"^Ped."',
    "up": '"^*"',
}

EXPRESSION_TO_ABC = {
    "a_tempo": '"a tempo"',
    "accel": '"accel"',
    "calando": '"calando"',
    "cantabile": '"cantabile"',
    "cédez": '"cédez"',
    "cresc": '"cresc"',
    "dim": '"dim"',
    "dolce": '"dolce"',
    "espress": '"espress"',
    "in_tempo": '"in tempo"',
    "legato": '"legato"',
    "leggiero": '"leggiero"',
    "loco": '"loco"',
    "marcato": '"marcato"',
    "molto_rall": '"molto rall"',
    "mouvt": '"mouvt"',
    "poco_rit": '"poco rit"',
    "rall": '"rall"',
    "rit": '"rit"',
    "ritard": '"ritard"',
    "riten": '"riten"',
    "sec": '"sec"',
    "sempre": '"sempre"',
    "sotto_voce": '"sotto voce"',
    "stretto": '"stretto"',
    "subito": '"subito"',
    "ten": '"ten"',
    "tempo_i": '"tempo i"',
    "una_corda": '"una corda"',
}

KEY_TOKEN_TO_ABC = {
    "key_C": "C",
    "key_G": "G",
    "key_D": "D",
    "key_A": "A",
    "key_E": "E",
    "key_B": "B",
    "key_F#": "F#",
    "key_C#": "C#",
    "key_F": "F",
    "key_Bb": "Bb",
    "key_Eb": "Eb",
    "key_Ab": "Ab",
    "key_Db": "Db",
    "key_Gb": "Gb",
    "key_Cb": "Cb",
    "key_Am": "Am",
    "key_Em": "Em",
    "key_Bm": "Bm",
    "key_F#m": "F#m",
    "key_C#m": "C#m",
    "key_G#m": "G#m",
    "key_D#m": "D#m",
    "key_A#m": "A#m",
    "key_Dm": "Dm",
    "key_Gm": "Gm",
    "key_Cm": "Cm",
    "key_Fm": "Fm",
    "key_Bbm": "Bbm",
    "key_Ebm": "Ebm",
    "key_Abm": "Abm",
}

KEY_SIGNATURE_ACCIDENTALS = {
    "G": {"F": 1},
    "D": {"F": 1, "C": 1},
    "A": {"F": 1, "C": 1, "G": 1},
    "E": {"F": 1, "C": 1, "G": 1, "D": 1},
    "B": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1},
    "F#": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1},
    "C#": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1, "B": 1},
    "F": {"B": -1},
    "Bb": {"B": -1, "E": -1},
    "Eb": {"B": -1, "E": -1, "A": -1},
    "Ab": {"B": -1, "E": -1, "A": -1, "D": -1},
    "Db": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1},
    "Gb": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1, "C": -1},
    "Cb": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1, "C": -1, "F": -1},
    "Am": {},
    "Em": {"F": 1},
    "Bm": {"F": 1, "C": 1},
    "F#m": {"F": 1, "C": 1, "G": 1},
    "C#m": {"F": 1, "C": 1, "G": 1, "D": 1},
    "G#m": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1},
    "D#m": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1},
    "A#m": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1, "B": 1},
    "Dm": {"B": -1},
    "Gm": {"B": -1, "E": -1},
    "Cm": {"B": -1, "E": -1, "A": -1},
    "Fm": {"B": -1, "E": -1, "A": -1, "D": -1},
    "Bbm": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1},
    "Ebm": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1, "C": -1},
    "Abm": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1, "C": -1, "F": -1},
}

LETTER_TO_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass
class HeaderInfo:
    titles: list[str] = field(default_factory=list)
    composer: str | None = None
    source: str | None = None
    meter: str = DEFAULT_METER
    key: str = DEFAULT_KEY
    tempo_bpm: int = DEFAULT_TEMPO_BPM


@dataclass
class NoteEvent:
    onset_bin: int
    duration_bin: int
    pitch: int
    staff: str


@dataclass
class QuantizedNoteEvent:
    onset_grid: int
    duration_grid: int
    onset_ql: Fraction
    duration_ql: Fraction
    pitch: int
    staff: str


@dataclass
class AnnotationEvent:
    onset_bin: int
    kind: str
    value: str | None
    staff: str | None


@dataclass
class MeasureData:
    measure_index: int
    duration_bin: int
    phrase_index: int | None = None
    notes_upper: list[NoteEvent] = field(default_factory=list)
    notes_lower: list[NoteEvent] = field(default_factory=list)
    annotations: list[AnnotationEvent] = field(default_factory=list)


class AnnotatedTSVParser:
    def __init__(self, path: Path):
        self.path = path
        self.header = HeaderInfo()

    def parse(self) -> list[MeasureData]:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        measures: list[MeasureData] = []
        current_measure: MeasureData | None = None
        current_phrase_index: int | None = None
        pending_exd: int | None = None
        pending_exo: int | None = None
        onset_cursor = 0

        for line in lines:
            if not line:
                continue
            if line.startswith("#"):
                self._parse_header_comment(line)
                continue

            parts = line.split("\t")
            if len(parts) != 4:
                continue
            event, value, duration, offset = parts

            if event == "KS":
                self.header.key = KEY_TOKEN_TO_ABC.get(value, DEFAULT_KEY)
                continue
            if event == "TP":
                if value.startswith("V") and value[1:].isdigit():
                    self.header.tempo_bpm = int(value[1:]) * 3
                continue
            if event == "MT":
                if value.startswith("meter_"):
                    self.header.meter = value.removeprefix("meter_")
                continue
            if event == "H":
                if value.isdigit():
                    current_phrase_index = int(value)
                continue
            if event == "M":
                if current_measure is not None:
                    measures.append(current_measure)
                onset_cursor = 0
                pending_exd = None
                pending_exo = None
                current_measure = MeasureData(
                    measure_index=int(value) if value.isdigit() else len(measures),
                    duration_bin=int(duration) * 256 + int(offset),
                    phrase_index=current_phrase_index,
                )
                continue

            if current_measure is None:
                continue

            if event == "EXD":
                pending_exd = int(duration) * 256 + int(offset)
                continue
            if event == "EXO":
                pending_exo = int(duration) * 256 + int(offset)
                continue

            if self._is_note_event(event):
                actual_duration = pending_exd if duration == "EXT" and pending_exd is not None else int(duration)
                actual_offset = pending_exo if offset == "EXT" and pending_exo is not None else int(offset)
                onset_cursor += actual_offset
                note = NoteEvent(
                    onset_bin=onset_cursor,
                    duration_bin=actual_duration,
                    pitch=self._event_to_midi_pitch(event),
                    staff="lower" if event.endswith("L") else "upper",
                )
                if note.staff == "upper":
                    current_measure.notes_upper.append(note)
                else:
                    current_measure.notes_lower.append(note)
                pending_exd = None
                pending_exo = None
                continue

            annotation = self._parse_annotation(event, value, current_measure, onset_cursor)
            if annotation is not None:
                current_measure.annotations.append(annotation)

        if current_measure is not None:
            measures.append(current_measure)
        return measures

    def _parse_header_comment(self, line: str) -> None:
        if line.startswith("# T:"):
            self.header.titles.append(line[4:].strip())
        elif line.startswith("# C:"):
            self.header.composer = line[4:].strip()
        elif line.startswith("# Z:"):
            self.header.source = line[4:].strip()

    def _parse_annotation(
        self,
        event: str,
        value: str,
        measure: MeasureData,
        onset_cursor: int,
    ) -> AnnotationEvent | None:
        onset = self._next_staff_onset(measure, onset_cursor, event.endswith("L"))
        if event in {"D", "DL"}:
            return AnnotationEvent(onset, "dynamic", value, "lower" if event == "DL" else "upper")
        if event in {"A", "AL"}:
            return AnnotationEvent(onset, "articulation", value, "lower" if event == "AL" else "upper")
        if event in {"OR", "ORL"}:
            return AnnotationEvent(onset, "ornament", value, "lower" if event == "ORL" else "upper")
        if event in {"RS", "RSL"}:
            return AnnotationEvent(onset, "range_start", value, "lower" if event == "RSL" else "upper")
        if event in {"RE", "REL"}:
            return AnnotationEvent(onset, "range_end", value, "lower" if event == "REL" else "upper")
        if event in {"EX", "EXL"}:
            return AnnotationEvent(onset, "expression", value, "lower" if event == "EXL" else "upper")
        if event == "PM":
            return AnnotationEvent(onset_cursor, "pedal", value, None)
        if event == "FM":
            return AnnotationEvent(onset, "fermata", None, None)
        return None

    @staticmethod
    def _is_note_event(event: str) -> bool:
        return re.fullmatch(r"[A-G]#?-?\d+L?", event) is not None

    @staticmethod
    def _event_to_midi_pitch(event: str) -> int:
        note = event[:-1] if event.endswith("L") else event
        match = re.fullmatch(r"([A-G]#?)(-?\d+)", note)
        if not match:
            raise ValueError(f"Invalid note event: {event}")
        pitch_name, octave_text = match.groups()
        octave = int(octave_text)
        semitone = {
            "C": 0,
            "C#": 1,
            "D": 2,
            "D#": 3,
            "E": 4,
            "F": 5,
            "F#": 6,
            "G": 7,
            "G#": 8,
            "A": 9,
            "A#": 10,
            "B": 11,
        }[pitch_name]
        return (octave + 2) * 12 + semitone

    @staticmethod
    def _next_staff_onset(measure: MeasureData, onset_cursor: int, lower: bool) -> int:
        notes = measure.notes_lower if lower else measure.notes_upper
        for note in notes:
            if note.onset_bin >= onset_cursor:
                return note.onset_bin
        return onset_cursor


def quantize_bin_to_ql(duration_bin: int, measure_duration_bin: int, meter: str) -> Fraction:
    beats_num, beats_den = parse_meter(meter)
    measure_ql = Fraction(beats_num * 4, beats_den)
    ql = Fraction(duration_bin, measure_duration_bin) * measure_ql
    return min(STANDARD_QL, key=lambda cand: abs(float(cand - ql)))


def quantize_ql(value: Fraction) -> Fraction:
    return round_fraction_to_grid(value, GRID_QL)


def round_fraction_to_grid(value: Fraction, step: Fraction) -> Fraction:
    return round(float(value / step)) * step


def quantize_measure_notes(notes: list[NoteEvent], measure_duration_bin: int, meter: str) -> list[QuantizedNoteEvent]:
    if not notes:
        return []
    beats_num, beats_den = parse_meter(meter)
    measure_ql = Fraction(beats_num * 4, beats_den)
    result: list[QuantizedNoteEvent] = []
    for note in notes:
        raw_onset_ql = Fraction(note.onset_bin, measure_duration_bin) * measure_ql
        raw_end_ql = Fraction(note.onset_bin + note.duration_bin, measure_duration_bin) * measure_ql
        onset_ql = quantize_ql(raw_onset_ql)
        end_ql = quantize_ql(raw_end_ql)
        if end_ql <= onset_ql:
            end_ql = onset_ql + GRID_QL
        duration_ql = min(STANDARD_QL, key=lambda cand: abs(float(cand - (end_ql - onset_ql))))
        duration_ql = max(duration_ql, GRID_QL)
        onset_grid = int(onset_ql / GRID_QL)
        duration_grid = max(1, int(duration_ql / GRID_QL))
        result.append(
            QuantizedNoteEvent(
                onset_grid=onset_grid,
                duration_grid=duration_grid,
                onset_ql=onset_ql,
                duration_ql=duration_ql,
                pitch=note.pitch,
                staff=note.staff,
            )
        )
    return result


def parse_meter(meter: str) -> tuple[int, int]:
    try:
        num, den = meter.split("/", 1)
        return int(num), int(den)
    except Exception:
        return 4, 4


def abc_duration_suffix(ql: Fraction) -> str:
    units = ql / DEFAULT_UNIT_QL
    if units == 1:
        return ""
    if units.denominator == 1:
        return str(units.numerator)
    if units.numerator == 1:
        return f"/{units.denominator}"
    return f"{units.numerator}/{units.denominator}"


def midi_pitch_to_abc(pitch: int, key: str) -> str:
    desired_pc = pitch % 12
    key_accidentals = KEY_SIGNATURE_ACCIDENTALS.get(key, {})
    prefer_flats = "b" in key and "#" not in key
    prefer_sharps = "#" in key
    candidates: list[tuple[float, str, int, int]] = []
    for letter, base_pc in LETTER_TO_PC.items():
        for final_acc in (-2, -1, 0, 1, 2):
            if (base_pc + final_acc) % 12 != desired_pc:
                continue
            key_acc = key_accidentals.get(letter, 0)
            if final_acc == key_acc:
                accidental = ""
                cost = 0.0
            elif final_acc == 0:
                accidental = "="
                cost = 1.0
            elif final_acc > 0:
                accidental = "^" * final_acc
                cost = 1.0 + 0.25 * (final_acc - 1)
            else:
                accidental = "_" * (-final_acc)
                cost = 1.0 + 0.25 * ((-final_acc) - 1)
            if accidental.startswith("_") and prefer_flats:
                cost -= 0.1
            if accidental.startswith("^") and prefer_sharps:
                cost -= 0.1
            delta = pitch - (60 + base_pc + final_acc)
            if delta % 12 != 0:
                continue
            octave_shift = delta // 12
            candidates.append((cost, accidental + letter, final_acc, octave_shift))
    if not candidates:
        # Fallback to the sharp-only spelling.
        pitch_class = pitch % 12
        base = PITCH_CLASS_TO_SHARP[pitch_class]
        accidental = ""
        letter = base
        if base.startswith("^"):
            accidental = "^"
            letter = base[1:]
        octave_shift = (pitch - (60 + pitch_class)) // 12
        spelling = accidental + letter
    else:
        _, spelling, final_acc, octave_shift = min(candidates, key=lambda item: item[0])
    accidental = ""
    letter = spelling
    if spelling and spelling[0] in "^_=":
        accidental = re.match(r"^[\^_=]+", spelling).group(0)
        letter = spelling[len(accidental):]
    scientific_octave = 4 + octave_shift
    if scientific_octave >= 5:
        return accidental + letter.lower() + ("'" * (scientific_octave - 5))
    if scientific_octave == 4:
        return accidental + letter.upper()
    return accidental + letter.upper() + ("," * (4 - scientific_octave))


def detect_triplet_groups(events: list[QuantizedNoteEvent]) -> dict[int, int]:
    """Return onset bins that look like triplet starts.

    MVP heuristic:
    - three consecutive note onsets in one track
    - nearly equal onset gaps
    - each gap close to one triplet eighth or one triplet quarter
    """
    if len(events) < 3:
        return {}
    starts: dict[int, int] = {}
    for i in range(len(events) - 2):
        a, b, c = events[i:i + 3]
        gap1 = b.onset_grid - a.onset_grid
        gap2 = c.onset_grid - b.onset_grid
        if gap1 <= 0 or gap2 <= 0:
            continue
        if gap1 != gap2:
            continue
        if gap1 in {8, 16}:
            starts[a.onset_grid] = gap1
    return starts


def assign_layers(notes: list[QuantizedNoteEvent]) -> list[list[QuantizedNoteEvent]]:
    """Greedy interval partitioning inside one staff."""
    layers: list[list[QuantizedNoteEvent]] = []
    layer_end_bins: list[int] = []
    for note in sorted(notes, key=lambda n: (n.onset_grid, n.pitch, n.duration_grid)):
        end_bin = note.onset_grid + max(1, note.duration_grid)
        placed = False
        for idx, layer in enumerate(layers):
            if note.onset_grid >= layer_end_bins[idx]:
                layer.append(note)
                layer_end_bins[idx] = end_bin
                placed = True
                break
        if not placed:
            layers.append([note])
            layer_end_bins.append(end_bin)
    return layers


def track_to_abc(
    notes: list[QuantizedNoteEvent],
    annotations: list[AnnotationEvent],
    measure_duration_grid: int,
    meter: str,
    key: str,
) -> str:
    if not notes:
        return "."

    notes_sorted = sorted(notes, key=lambda n: (n.onset_grid, n.pitch))
    triplet_starts = detect_triplet_groups(notes_sorted)
    grouped_notes: dict[int, list[QuantizedNoteEvent]] = defaultdict(list)
    for note in notes_sorted:
        grouped_notes[note.onset_grid].append(note)

    ann_by_onset: dict[int, list[str]] = defaultdict(list)
    for ann in sorted(annotations, key=lambda a: (a.onset_bin, a.kind)):
        marker = annotation_to_abc(ann)
        if marker:
            ann_grid = int(quantize_ql(Fraction(ann.onset_bin, 1) * Fraction(1, 1) / 1 / 1) / GRID_QL)
            ann_by_onset[ann_grid].append(marker)

    cursor_grid = 0
    parts: list[str] = []
    ordered_onsets = sorted(grouped_notes)
    onset_index = 0
    while onset_index < len(ordered_onsets):
        onset_grid = ordered_onsets[onset_index]
        if onset_grid > cursor_grid:
            rest_ql = min(STANDARD_QL, key=lambda cand: abs(float(cand - (onset_grid - cursor_grid) * GRID_QL)))
            parts.append("z" + abc_duration_suffix(rest_ql))
            cursor_grid = onset_grid

        prefix = ann_by_onset.get(onset_grid, [])
        if onset_grid in triplet_starts and onset_index + 2 < len(ordered_onsets):
            gap = triplet_starts[onset_grid]
            parts.extend(prefix)
            parts.append("(3")
            suffix = "" if gap == 8 else "2"
            for local_idx in range(3):
                tuplet_onset = ordered_onsets[onset_index + local_idx]
                chord = grouped_notes[tuplet_onset]
                parts.append(chord_to_abc(chord, key, suffix_override=suffix))
            cursor_grid = ordered_onsets[onset_index + 2] + max(1, max(n.duration_grid for n in grouped_notes[ordered_onsets[onset_index + 2]]))
            onset_index += 3
            continue

        parts.extend(prefix)
        chord = grouped_notes[onset_grid]
        parts.append(chord_to_abc(chord, key))
        cursor_grid = onset_grid + max(1, max(n.duration_grid for n in chord))
        onset_index += 1

    if cursor_grid < measure_duration_grid:
        rest_ql = min(STANDARD_QL, key=lambda cand: abs(float(cand - (measure_duration_grid - cursor_grid) * GRID_QL)))
        parts.append("z" + abc_duration_suffix(rest_ql))
    return " ".join(part for part in parts if part)


def chord_to_abc(chord: list[QuantizedNoteEvent], key: str, suffix_override: str | None = None) -> str:
    pitches = [midi_pitch_to_abc(note.pitch, key) for note in sorted(chord, key=lambda n: n.pitch)]
    duration = max(note.duration_ql for note in chord)
    dur_suffix = suffix_override if suffix_override is not None else abc_duration_suffix(duration)
    if len(pitches) == 1:
        return pitches[0] + dur_suffix
    return "[" + "".join(pitches) + "]" + dur_suffix


def annotation_to_abc(ann: AnnotationEvent) -> str:
    if ann.kind == "dynamic" and ann.value:
        return DYNAMIC_TO_ABC.get(ann.value, "")
    if ann.kind == "articulation" and ann.value:
        return ARTICULATION_TO_ABC.get(ann.value, "")
    if ann.kind == "ornament" and ann.value:
        return ORNAMENT_TO_ABC.get(ann.value, "")
    if ann.kind == "range_start" and ann.value:
        return RANGE_START_TO_ABC.get(ann.value, "")
    if ann.kind == "range_end" and ann.value:
        return RANGE_END_TO_ABC.get(ann.value, "")
    if ann.kind == "expression" and ann.value:
        return EXPRESSION_TO_ABC.get(ann.value, "")
    if ann.kind == "pedal" and ann.value:
        return PEDAL_TO_ABC.get(ann.value, "")
    if ann.kind == "fermata":
        return "!fermata!"
    return ""


def measures_to_aligned_abcx(header: HeaderInfo, measures: list[MeasureData]) -> str:
    out: list[str] = []
    out.append("X:1")
    for title in header.titles:
        out.append(f"T:{title}")
    if header.composer:
        out.append(f"C:{header.composer}")
    if header.source:
        out.append(f"Z:{header.source}")
    out.append(f"L:{DEFAULT_ABC_UNIT}")
    out.append(f"Q:1/4={header.tempo_bpm}")
    out.append(f"M:{header.meter}")
    out.append(f"K:{header.key}")

    current_phrase = None
    for measure in measures:
        if measure.phrase_index != current_phrase:
            current_phrase = measure.phrase_index
            phrase_label = current_phrase if current_phrase is not None else 0
            out.append(f"<H><V{phrase_label % 128:03d}>")

        upper_notes = quantize_measure_notes(measure.notes_upper, measure.duration_bin, header.meter)
        lower_notes = quantize_measure_notes(measure.notes_lower, measure.duration_bin, header.meter)
        upper_layers = assign_layers(upper_notes)
        lower_layers = assign_layers(lower_notes)
        measure_duration_grid = max(1, int(quantize_ql(Fraction(parse_meter(header.meter)[0] * 4, parse_meter(header.meter)[1])) / GRID_QL))

        upper_annotations = [ann for ann in measure.annotations if ann.staff in {"upper", None}]
        lower_annotations = [ann for ann in measure.annotations if ann.staff in {"lower", None}]

        upper_tracks = [
            track_to_abc(layer, upper_annotations if idx == 0 else [], measure_duration_grid, header.meter, header.key)
            for idx, layer in enumerate(upper_layers or [[]])
        ]
        lower_tracks = [
            track_to_abc(layer, lower_annotations if idx == 0 else [], measure_duration_grid, header.meter, header.key)
            for idx, layer in enumerate(lower_layers or [[]])
        ]

        upper_text = " & ".join(track for track in upper_tracks if track) or "."
        lower_text = " & ".join(track for track in lower_tracks if track) or "."
        out.append(f"<M><V{measure.measure_index % 128:03d}>{upper_text} ; {lower_text}")

    return "\n".join(out) + "\n"


def default_output_path(input_path: Path) -> Path:
    if input_path.name.endswith(".annotated_score.mid.tsv"):
        return input_path.with_name(input_path.name.replace(".annotated_score.mid.tsv", ".reconstructed_aligned.abcx"))
    return input_path.with_suffix(input_path.suffix + ".reconstructed_aligned.abcx")


def reconstruct_file(input_path: Path, output_path: Path) -> None:
    parser = AnnotatedTSVParser(input_path)
    measures = parser.parse()
    text = measures_to_aligned_abcx(parser.header, measures)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="Annotated score MIDI-TSV file")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Output aligned ABCX path")
    ap.add_argument("--metadata", type=Path, default=None, help="Optional metadata CSV; reconstruct all annotated paths")
    args = ap.parse_args()

    if args.metadata is not None:
        with args.metadata.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ann_path = (row.get("annotated_score_midi_path") or "").strip()
                if not ann_path:
                    continue
                ann_full = Path("/home/sy/EPR") / ann_path if not Path(ann_path).is_absolute() else Path(ann_path)
                if not ann_full.exists():
                    continue
                out_path = default_output_path(ann_full)
                reconstruct_file(ann_full, out_path)
                print(out_path)
        return

    output_path = args.output or default_output_path(args.input)
    reconstruct_file(args.input, output_path)
    print(output_path)


if __name__ == "__main__":
    main()
