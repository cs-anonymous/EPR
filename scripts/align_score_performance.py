#!/usr/bin/env python3
"""
Complete score-performance alignment pipeline with repeat detection.

Step 1: Extract logical measures from Score MIDI (output JSON)
Step 2: Parse ABCX phrase structure and align with Score MIDI measures
Step 3: Align Performance MIDI with Score structure, auto-detect repeats, assign measures and phrases
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from fractions import Fraction
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pretty_midi
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from scripts.aligned_abcx_format import (
        AlignedAbcxError,
        build_aligned_abcx,
        parse_score_layout,
        read_abcx_lines,
        simplify_measure_content,
    )
    from scripts.lm_midi_tsv import midi_pitch_to_logic_note, semantic_event_to_tsv_rows, tsv_row_to_line
except ModuleNotFoundError:
    from aligned_abcx_format import (
        AlignedAbcxError,
        build_aligned_abcx,
        parse_score_layout,
        read_abcx_lines,
        simplify_measure_content,
    )
    from lm_midi_tsv import midi_pitch_to_logic_note, semantic_event_to_tsv_rows, tsv_row_to_line


@dataclass
class ScoreMeasure:
    """A logical measure from Score MIDI."""
    measure_num: int  # 1-indexed
    start_note_idx: int  # inclusive
    end_note_idx: int  # exclusive
    start_time: float
    end_time: float
    time_signature: str


@dataclass
class Phrase:
    """A phrase containing multiple measures."""
    phrase_id: str  # e.g., "H1", "H2"
    measures: list[int]  # measure numbers in this phrase
    has_linebreak: bool  # whether phrase ends with linebreak


@dataclass
class ScoreStructure:
    """Complete score structure with measures and phrases.

    Canonical unit: Score MIDI measures (expanded with repeats).
    """
    measures: list[ScoreMeasure]  # Score MIDI measures (e.g. 1-41)
    phrases: list[Phrase]  # phrases with MIDI measure numbers, one entry per pass
    measure_to_phrase: dict[int, str]  # midi_measure_num -> phrase_id
    abcx_measures: dict[int, str]  # original abcx_measure_num -> ABC content
    midi_to_abcx: dict[int, int]  # midi_measure_num -> abcx_measure_num
    midi_measure_content: dict[int, str]  # midi_measure_num -> ABC content (expanded from ABCX)


def _abc_measure_duration(text: str) -> float:
    """Approximate beat duration of an ABC measure fragment.

    Only counts actual notes/rests with duration numbers, not bare pitches.
    """
    cleaned = re.sub(r'![^!]*!|"[^"]*"|%\{[^\}]*\}|\\[a-z]+', '', text)
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    total = 0.0
    for match in re.finditer(r"(\d+)(/(\d+))?", cleaned):
        num = int(match.group(1))
        denom = int(match.group(3)) if match.group(3) else 1
        total += num / denom
    # Also count bare rests (z without number = 1 beat)
    for match in re.finditer(r'(?<![A-Ga-g0-9])z(?![A-Ga-g0-9/])', cleaned):
        total += 1.0
    return total


def _is_marker_only(content: str) -> bool:
    """Check if an ABCX measure contains ONLY structural markers (no musical content).

    Volta markers like '1', '2', ':', '::', 'O' etc. without any notes or rests.
    This happens when the score MIDI puts the volta bracket in its own measure
    with notes, while ABCX puts the bracket as a separate empty measure.
    """
    # Strip volta/repeat/ottava markers and structural symbols
    cleaned = re.sub(r'(?<![A-Ga-g])\d+(?![A-Ga-g\'/,])', '', content)  # bare numbers (volta)
    cleaned = re.sub(r':', '', cleaned)  # repeat markers
    cleaned = re.sub(r'\bO\b', '', cleaned)  # ottava
    cleaned = re.sub(r'[\[\]{}]', '', cleaned)  # brackets
    cleaned = re.sub(r'![^!]*!', '', cleaned)  # ornaments
    cleaned = re.sub(r'"[^"]*"', '', cleaned)  # annotations
    cleaned = re.sub(r'\s+', '', cleaned)  # whitespace
    # After stripping, only voice separators (;) should remain
    cleaned = cleaned.replace(';', '')
    return len(cleaned) == 0


def _parse_abcx_measures(abcx_path: Path) -> list[dict]:
    """Parse ABCX body into measures, splitting on `::` repeat markers.

    Returns list of {num, content, is_phrase_closer, is_phrase_starter} dicts.
    - is_phrase_closer: measure ends a phrase (first-ending material, or ends with `:`)
    - is_phrase_starter: measure starts a new phrase (second-ending material)
    """
    with open(abcx_path, encoding="utf-8") as f:
        lines = [line.rstrip() for line in f]

    body_start = None
    for i, line in enumerate(lines):
        if line.startswith("K:"):
            body_start = i + 1
            break
    if body_start is None:
        return []

    body_text = " ".join(
        line for line in lines[body_start:]
        if line.strip() and not line.strip().startswith(("%%", "V:", "w:"))
    )

    # Split by `|` first
    segments = [s.strip() for s in body_text.split("|") if s.strip()]

    # Within each segment, split on `::` and classify parts
    # Skip `w:` lyrics-only segments — they are not musical measures
    raw_measures = []
    for seg in segments:
        if seg.startswith("w:"):
            continue
        if "::" in seg:
            parts = seg.split("::")
            for i, p in enumerate(parts):
                p = p.strip()
                if not p:
                    continue
                if i == 0:
                    # First part before `::` = first ending material → phrase closer
                    raw_measures.append((p, True, False))
                else:
                    # Everything after first `::` = second ending / post-repeat material
                    # → phrase starter
                    raw_measures.append((p, False, True))
        else:
            clean = seg.strip()
            if clean:
                has_end_colon = bool(re.search(r':\s*$', clean))
                raw_measures.append((clean, has_end_colon, False))

    # Filter out marker-only measures (volta brackets with no notes)
    # These cause mismatches when the score MIDI encodes the volta bracket
    # as a measure WITH notes but ABCX has it as a separate empty measure.
    filtered_measures = []
    for content, is_closer, is_starter in raw_measures:
        if _is_marker_only(content):
            continue  # skip phantom measures
        filtered_measures.append((content, is_closer, is_starter))

    # Build measure list with numbering (renumbered after filtering)
    measures = []
    for idx, (content, is_closer, is_starter) in enumerate(filtered_measures, 1):
        measures.append({
            "num": idx,
            "content": content,
            "is_phrase_closer": is_closer,
            "is_phrase_starter": is_starter,
        })

    return measures


def load_midi_tsv_module():
    """Load midi_tsv.py module."""
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load midi_tsv.py from {midi_tsv_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_aligned_measure_content(
    score_abcx: Path,
    midi_measure_content: dict[int, str],
) -> dict[int, str]:
    """Project expanded raw ABCX measure content into aligned `StaffU ; StaffL` rows."""
    lines = read_abcx_lines(score_abcx)
    if any(line.lstrip().startswith("%%score") for line in lines):
        layout = parse_score_layout(lines)
        return {
            measure_num: simplify_measure_content(content, layout)
            for measure_num, content in midi_measure_content.items()
        }

    aligned_rows = [line.strip() for line in lines if line.strip().startswith("<M><V")]
    if aligned_rows:
        measure_nums = sorted(midi_measure_content)
        result: dict[int, str] = {}
        for measure_num, row in zip(measure_nums, aligned_rows):
            content = re.sub(r"^<M><V\d{3}>", "", row).strip()
            result[measure_num] = content or ". ; ."
        return result

    raise AlignedAbcxError(f"cannot derive aligned staff layout from {score_abcx}")


def _parse_unit_length(lines: list[str]) -> Fraction:
    for line in lines:
        if line.startswith("L:"):
            match = re.match(r"L:\s*(\d+)/(\d+)", line)
            if match:
                return Fraction(int(match.group(1)), int(match.group(2)))
    return Fraction(1, 8)


def _parse_key_signature(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("K:"):
            return line[2:].strip().split()[0]
    return "C"


def _key_signature_accidentals(key: str) -> dict[str, int]:
    return {
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
    }.get(key, {})


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    bang_open = False
    bracket_depth = 0
    brace_depth = 0

    for char in text:
        if char == '"' and not bang_open:
            in_quote = not in_quote
            current.append(char)
            continue
        if char == "!" and not in_quote:
            bang_open = not bang_open
            current.append(char)
            continue
        if not in_quote and not bang_open:
            if char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth:
                bracket_depth -= 1
            elif char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth:
                brace_depth -= 1
            elif char == separator and bracket_depth == 0 and brace_depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(char)

    parts.append("".join(current).strip())
    return parts


def _abc_duration_from_suffix(duration_suffix: str, unit_length: Fraction) -> Fraction:
    if not duration_suffix:
        return unit_length
    if duration_suffix.startswith("/"):
        return unit_length / (2 ** len(duration_suffix))
    if "/" in duration_suffix:
        num, denom = duration_suffix.split("/", 1)
        return unit_length * Fraction(int(num), int(denom))
    return unit_length * int(duration_suffix)


def _default_tuplet_factor(count: int) -> Fraction:
    defaults = {
        2: Fraction(3, 2),
        3: Fraction(2, 3),
        4: Fraction(3, 4),
        5: Fraction(4, 5),
        6: Fraction(4, 6),
        7: Fraction(4, 7),
        8: Fraction(6, 8),
        9: Fraction(6, 9),
    }
    return defaults.get(count, Fraction(1, 1))


def _parse_note_atom(text: str, index: int) -> tuple[dict[str, object], int] | None:
    start = index
    accidental = []
    while index < len(text) and text[index] in "^=_":
        accidental.append(text[index])
        index += 1
    if index >= len(text) or text[index] not in "ABCDEFGabcdefg":
        return None
    letter = text[index]
    index += 1
    octave = []
    while index < len(text) and text[index] in "',":
        octave.append(text[index])
        index += 1
    duration = []
    while index < len(text) and (text[index].isdigit() or text[index] == "/"):
        duration.append(text[index])
        index += 1
    tie_out = index < len(text) and text[index] == "-"
    if tie_out:
        index += 1
    return (
        {
            "text": text[start:index],
            "accidental": "".join(accidental),
            "letter": letter,
            "octave": "".join(octave),
            "duration": "".join(duration),
            "tie_out": tie_out,
        },
        index,
    )


def _abc_note_to_midi(
    accidental: str,
    letter: str,
    octave_marks: str,
    state: dict[str, int],
    key_accidentals: dict[str, int],
) -> int:
    base_pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter.upper()]
    midi_pitch = 60 + base_pc
    if letter.islower():
        midi_pitch += 12
    for mark in octave_marks:
        midi_pitch += 12 if mark == "'" else -12

    accidental_key = f"{letter}{octave_marks}"
    if accidental:
        if accidental.startswith("^"):
            state[accidental_key] = accidental.count("^")
        elif accidental.startswith("_"):
            state[accidental_key] = -accidental.count("_")
        else:
            state[accidental_key] = 0
    offset = state.get(accidental_key, key_accidentals.get(letter.upper(), 0))
    return midi_pitch + offset


def _parse_chord_pitches(
    chord_text: str,
    state: dict[str, int],
    key_accidentals: dict[str, int],
) -> list[int]:
    inner = chord_text[1:-1]
    pitches: list[int] = []
    index = 0
    while index < len(inner):
        parsed = _parse_note_atom(inner, index)
        if parsed is None:
            index += 1
            continue
        atom, index = parsed
        pitches.append(
            _abc_note_to_midi(
                str(atom["accidental"]),
                str(atom["letter"]),
                str(atom["octave"]),
                state,
                key_accidentals,
            )
        )
    return pitches


def _parse_staff_layer_events(
    layer_text: str,
    unit_length: Fraction,
    key_signature: str,
) -> list[tuple[Fraction, list[int]]]:
    key_accidentals = _key_signature_accidentals(key_signature)
    accidentals_state: dict[str, int] = {}
    events: list[tuple[Fraction, list[int]]] = []
    cursor = Fraction(0, 1)
    tuplet_remaining = 0
    tuplet_factor = Fraction(1, 1)
    tied_pitches: set[int] = set()
    index = 0

    while index < len(layer_text):
        char = layer_text[index]
        if char.isspace() or char in "~<>":
            index += 1
            continue
        if char == '"':
            index += 1
            while index < len(layer_text) and layer_text[index] != '"':
                index += 1
            index += 1
            continue
        if char == "!":
            index += 1
            while index < len(layer_text) and layer_text[index] != "!":
                index += 1
            index += 1
            continue
        if char == "{":
            depth = 1
            index += 1
            while index < len(layer_text) and depth:
                if layer_text[index] == "{":
                    depth += 1
                elif layer_text[index] == "}":
                    depth -= 1
                index += 1
            continue
        if layer_text.startswith("[Q:", index) or layer_text.startswith("[M:", index) or layer_text.startswith("[K:", index):
            index += 1
            while index < len(layer_text) and layer_text[index] != "]":
                index += 1
            index += 1
            continue
        if char == "(":
            match = re.match(r"\((\d+)(?::(\d+))?(?::(\d+))?", layer_text[index:])
            if match:
                count = int(match.group(1))
                in_time = int(match.group(2)) if match.group(2) else None
                notes_affected = int(match.group(3)) if match.group(3) else count
                tuplet_factor = Fraction(in_time, count) if in_time else _default_tuplet_factor(count)
                tuplet_remaining = notes_affected
                index += len(match.group(0))
                continue
            index += 1
            continue
        if char in ")":
            index += 1
            continue
        if char in "zx":
            index += 1
            duration_suffix = []
            while index < len(layer_text) and (layer_text[index].isdigit() or layer_text[index] == "/"):
                duration_suffix.append(layer_text[index])
                index += 1
            duration = _abc_duration_from_suffix("".join(duration_suffix), unit_length)
            if tuplet_remaining:
                duration *= tuplet_factor
                tuplet_remaining -= 1
            if tuplet_remaining == 0:
                tuplet_factor = Fraction(1, 1)
            cursor += duration
            continue
        if char == "[":
            end = index + 1
            bracket_depth = 1
            while end < len(layer_text) and bracket_depth:
                if layer_text[end] == "[":
                    bracket_depth += 1
                elif layer_text[end] == "]":
                    bracket_depth -= 1
                end += 1
            if bracket_depth:
                break
            chord_text = layer_text[index:end]
            duration_start = end
            while end < len(layer_text) and (layer_text[end].isdigit() or layer_text[end] == "/"):
                end += 1
            tie_out = end < len(layer_text) and layer_text[end] == "-"
            if tie_out:
                end += 1
            pitches = _parse_chord_pitches(chord_text, accidentals_state, key_accidentals)
            duration = _abc_duration_from_suffix(layer_text[duration_start:end - (1 if tie_out else 0)], unit_length)
            if tuplet_remaining:
                duration *= tuplet_factor
                tuplet_remaining -= 1
            if tuplet_remaining == 0:
                tuplet_factor = Fraction(1, 1)
            emitted = [pitch for pitch in pitches if pitch not in tied_pitches]
            if emitted:
                events.append((cursor, sorted(emitted)))
            next_ties = {pitch for pitch in pitches if tie_out}
            tied_pitches = next_ties
            cursor += duration
            index = end
            continue

        parsed = _parse_note_atom(layer_text, index)
        if parsed is None:
            index += 1
            continue
        atom, index = parsed
        pitch = _abc_note_to_midi(
            str(atom["accidental"]),
            str(atom["letter"]),
            str(atom["octave"]),
            accidentals_state,
            key_accidentals,
        )
        duration = _abc_duration_from_suffix(str(atom["duration"]), unit_length)
        if tuplet_remaining:
            duration *= tuplet_factor
            tuplet_remaining -= 1
        if tuplet_remaining == 0:
            tuplet_factor = Fraction(1, 1)
        if pitch not in tied_pitches:
            events.append((cursor, [pitch]))
        tied_pitches = {pitch} if atom["tie_out"] else set()
        cursor += duration

    return events


def _parse_aligned_measure_events(
    aligned_content: str,
    unit_length: Fraction,
    key_signature: str,
) -> list[dict[str, Counter[int]]]:
    staff_parts = _split_top_level(aligned_content, ";")
    if len(staff_parts) < 2:
        staff_parts += ["."] * (2 - len(staff_parts))

    grouped: dict[Fraction, dict[str, Counter[int]]] = {}
    for staff_name, staff_text in (("upper", staff_parts[0]), ("lower", staff_parts[1])):
        cleaned_staff = staff_text.strip()
        if not cleaned_staff or cleaned_staff == ".":
            continue
        for layer_idx, layer in enumerate(_split_top_level(cleaned_staff, "&")):
            layer = layer.strip()
            if not layer or layer == ".":
                continue
            bucket_name = "lower"
            if staff_name == "upper":
                bucket_name = "upper_main" if layer_idx == 0 else "upper_aux"
            for onset, pitches in _parse_staff_layer_events(layer, unit_length, key_signature):
                bucket = grouped.setdefault(
                    onset,
                    {
                        "upper_main": Counter(),
                        "upper_aux": Counter(),
                        "lower": Counter(),
                    },
                )
                counter = Counter(pitches)
                bucket[bucket_name].update(counter)

    normalized: list[dict[str, Counter[int]]] = []
    for onset in sorted(grouped.keys()):
        raw_bucket = grouped[onset]
        upper = raw_bucket["upper_main"].copy()
        lower = raw_bucket["lower"].copy()

        # Auxiliary layers before `;` still belong to the upper staff.
        # Keeping them on the upper side avoids misclassifying notes such as
        # right-hand inner voices as left-hand material merely because the
        # onset lacks a simultaneous primary upper voice.
        upper.update(raw_bucket["upper_aux"])

        all_counter = Counter()
        all_counter.update(upper)
        all_counter.update(lower)
        normalized.append({"upper": upper, "lower": lower, "all": all_counter})

    return normalized


def _group_measure_notes(notes: list[pretty_midi.Note]) -> list[list[pretty_midi.Note]]:
    groups: list[list[pretty_midi.Note]] = []
    for note in sorted(notes, key=lambda n: (round(n.start, 6), n.pitch, round(n.end, 6), n.velocity)):
        if not groups or abs(groups[-1][0].start - note.start) > 1e-6:
            groups.append([note])
        else:
            groups[-1].append(note)
    return groups


def _assign_group_staffs(
    midi_group: list[pretty_midi.Note],
    abc_group: dict[str, Counter[int]] | None,
    remaining_upper: Counter[int],
    remaining_lower: Counter[int],
    upper_pitch_space: set[int],
    lower_pitch_space: set[int],
) -> list[str | None]:
    if abc_group is None and len(midi_group) > 1 and (upper_pitch_space or lower_pitch_space):
        lower_overlap = sum(1 for note in midi_group if note.pitch in lower_pitch_space)
        upper_overlap = sum(1 for note in midi_group if note.pitch in upper_pitch_space)
        if lower_overlap > upper_overlap and lower_overlap:
            return ["lower"] * len(midi_group)
        if upper_overlap > lower_overlap and upper_overlap:
            return ["upper"] * len(midi_group)

    group_upper = abc_group["upper"].copy() if abc_group else Counter()
    group_lower = abc_group["lower"].copy() if abc_group else Counter()
    assigned: list[str | None] = []

    for note in sorted(midi_group, key=lambda n: (n.pitch, round(n.end, 6), n.velocity)):
        pitch = note.pitch
        if group_lower[pitch] and not group_upper[pitch]:
            staff = "lower"
            group_lower[pitch] -= 1
            remaining_lower[pitch] -= 1
        elif group_upper[pitch] and not group_lower[pitch]:
            staff = "upper"
            group_upper[pitch] -= 1
            remaining_upper[pitch] -= 1
        elif group_lower[pitch] or group_upper[pitch]:
            if group_lower[pitch] >= group_upper[pitch]:
                staff = "lower"
                group_lower[pitch] -= 1
                remaining_lower[pitch] -= 1
            else:
                staff = "upper"
                group_upper[pitch] -= 1
                remaining_upper[pitch] -= 1
        elif remaining_lower[pitch] and not remaining_upper[pitch]:
            staff = "lower"
            remaining_lower[pitch] -= 1
        elif remaining_upper[pitch] and not remaining_lower[pitch]:
            staff = "upper"
            remaining_upper[pitch] -= 1
        elif remaining_lower[pitch] or remaining_upper[pitch]:
            if remaining_lower[pitch] >= remaining_upper[pitch]:
                staff = "lower"
                remaining_lower[pitch] -= 1
            else:
                staff = "upper"
                remaining_upper[pitch] -= 1
        elif upper_pitch_space or lower_pitch_space:
            if not upper_pitch_space:
                staff = "lower"
            elif not lower_pitch_space:
                staff = "upper"
            else:
                lower_dist = min(abs(pitch - abc_pitch) for abc_pitch in lower_pitch_space)
                upper_dist = min(abs(pitch - abc_pitch) for abc_pitch in upper_pitch_space)
                staff = "lower" if lower_dist <= upper_dist else "upper"
        else:
            staff = None
        assigned.append(staff)

    return assigned


def build_measure_note_staffs_from_aligned_abcx(
    score_midi_path: Path,
    score_structure: ScoreStructure,
    score_abcx: Path,
) -> dict[int, list[str | None]]:
    """Assign each score MIDI note to upper/lower staff using aligned ABCX note rows."""
    lines = read_abcx_lines(score_abcx)
    unit_length = _parse_unit_length(lines)
    key_signature = _parse_key_signature(lines)
    aligned_measure_content = build_aligned_measure_content(score_abcx, score_structure.midi_measure_content)

    score_midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    score_notes = sorted(
        [note for inst in score_midi.instruments if not inst.is_drum for note in inst.notes],
        key=lambda note: (note.start, note.pitch, note.end),
    )

    result: dict[int, list[str | None]] = {}
    note_index = 0
    for measure in score_structure.measures:
        measure_notes: list[pretty_midi.Note] = []
        while note_index < len(score_notes) and score_notes[note_index].start < measure.end_time - 0.01:
            note = score_notes[note_index]
            if note.start >= measure.start_time - 0.01:
                measure_notes.append(note)
            note_index += 1

        midi_groups = _group_measure_notes(measure_notes)
        abc_groups = _parse_aligned_measure_events(
            aligned_measure_content.get(measure.measure_num, ". ; ."),
            unit_length,
            key_signature,
        )
        remaining_upper = Counter()
        remaining_lower = Counter()
        for group in abc_groups:
            remaining_upper.update(group["upper"])
            remaining_lower.update(group["lower"])
        upper_pitch_space = set(remaining_upper)
        lower_pitch_space = set(remaining_lower)

        assignments: list[str | None] = []
        abc_index = 0
        for midi_group in midi_groups:
            midi_counter = Counter(note.pitch for note in midi_group)
            best_index = None
            best_score = -1
            for candidate in range(abc_index, min(len(abc_groups), abc_index + 8)):
                overlap = sum((midi_counter & abc_groups[candidate]["all"]).values())
                size_penalty = abs(sum(midi_counter.values()) - sum(abc_groups[candidate]["all"].values()))
                score = overlap * 8 - size_penalty - (candidate - abc_index)
                if score > best_score:
                    best_score = score
                    best_index = candidate
            abc_group = abc_groups[best_index] if best_index is not None else None
            if best_index is not None:
                abc_index = best_index + 1
            assignments.extend(
                _assign_group_staffs(
                    midi_group,
                    abc_group,
                    remaining_upper,
                    remaining_lower,
                    upper_pitch_space,
                    lower_pitch_space,
                )
            )

        result[measure.measure_num] = assignments

    return result


def flatten_measure_note_staffs(
    score_structure: ScoreStructure,
    measure_note_staffs: dict[int, list[str | None]],
) -> list[str | None]:
    """Flatten per-measure staff labels into score-note index order."""
    score_note_staffs: list[str | None] = [None] * (
        score_structure.measures[-1].end_note_idx if score_structure.measures else 0
    )
    for measure in score_structure.measures:
        note_count = max(0, measure.end_note_idx - measure.start_note_idx)
        staffs = list(measure_note_staffs.get(measure.measure_num, []))
        if len(staffs) < note_count:
            staffs.extend([None] * (note_count - len(staffs)))
        for offset in range(note_count):
            score_note_staffs[measure.start_note_idx + offset] = staffs[offset]
    return score_note_staffs


def build_performance_measure_note_staffs(
    score_midi_path: Path,
    perf_midi_path: Path,
    align_file: Path,
    score_structure: ScoreStructure,
    score_abcx: Path,
    perf_entries: list[tuple[int | None, str, int, int]],
) -> dict[int, list[str | None]]:
    """Project score-side upper/lower staff labels onto aligned performance notes."""
    score_measure_note_staffs = build_measure_note_staffs_from_aligned_abcx(
        score_midi_path,
        score_structure,
        score_abcx,
    )
    score_note_staffs = flatten_measure_note_staffs(score_structure, score_measure_note_staffs)

    perf_midi = pretty_midi.PrettyMIDI(str(perf_midi_path))
    perf_notes = sorted(
        [n for inst in perf_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    perf_note_staffs: list[str | None] = [None] * len(perf_notes)
    data = np.load(align_file, allow_pickle=True)
    perf_idx = data["perf_idx"]

    limit = min(len(score_note_staffs), len(perf_idx))
    for score_idx in range(limit):
        perf_idx_value = int(perf_idx[score_idx])
        if not (0 <= perf_idx_value < len(perf_note_staffs)):
            continue
        score_staff = score_note_staffs[score_idx]
        existing = perf_note_staffs[perf_idx_value]
        if existing is None:
            perf_note_staffs[perf_idx_value] = score_staff
        elif existing != score_staff and score_staff == "lower":
            # Prefer keeping a lower-staff assignment on ambiguous many-to-one matches.
            perf_note_staffs[perf_idx_value] = "lower"

    result: dict[int, list[str | None]] = {}
    note_idx = 0
    for mnum_or_none, _phrase_id, start_tick, end_tick in perf_entries:
        if mnum_or_none is None:
            continue
        measure_staffs: list[str | None] = []
        while note_idx < len(perf_notes):
            note_tick = round(perf_notes[note_idx].start * 100)
            if note_tick < start_tick:
                note_idx += 1
                continue
            if note_tick >= end_tick:
                break
            measure_staffs.append(perf_note_staffs[note_idx])
            note_idx += 1
        result[mnum_or_none] = measure_staffs

    return result


def extract_score_measures(score_midi_path: Path, midi_tsv) -> list[ScoreMeasure]:
    """
    Step 1: Extract logical measures from Score MIDI.

    Returns a list of ScoreMeasure objects with note index ranges.
    """
    # Load Score MIDI
    score_midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    # Parse MIDI to get tempo and time signature info
    tpq, tracks = midi_tsv.parse_midi(score_midi_path.read_bytes())
    tempos = []
    time_sigs = []
    end_tick = 0

    for events in tracks:
        tick = 0
        for evt in events:
            tick += evt["delta"]
            end_tick = max(end_tick, tick)
            if evt["type"] == "meta" and evt.get("meta_type") == 0x51:
                tempos.append({"tick": tick, "microseconds_per_beat": evt["microseconds_per_beat"]})
            elif evt["type"] == "meta" and evt.get("meta_type") == 0x58:
                time_sigs.append({
                    "tick": tick,
                    "numerator": evt["numerator"],
                    "denominator": evt["denominator"],
                })

    if not time_sigs:
        time_sigs = [{"tick": 0, "numerator": 4, "denominator": 4}]
    time_sigs = sorted(time_sigs, key=lambda sig: sig["tick"])
    if time_sigs[0]["tick"] != 0:
        time_sigs.insert(0, {"tick": 0, "numerator": 4, "denominator": 4})

    tempo_map = midi_tsv.build_original_tempo_map(tpq, tempos)

    # Calculate measure boundaries
    measure_boundaries = []
    for idx, sig in enumerate(time_sigs):
        start_tick = sig["tick"]
        stop_tick = time_sigs[idx + 1]["tick"] if idx + 1 < len(time_sigs) else end_tick
        measure_ticks = round(tpq * sig["numerator"] * 4 / sig["denominator"])
        if measure_ticks <= 0:
            continue

        tick = start_tick
        while tick < stop_tick - measure_ticks * 0.25:
            if not measure_boundaries or tick > measure_boundaries[-1][0]:
                measure_boundaries.append((tick, f"{sig['numerator']}/{sig['denominator']}"))
            tick += measure_ticks

    # Convert ticks to seconds
    def tick_to_seconds(tick: int) -> float:
        selected = tempo_map[0]
        for point in tempo_map:
            if point["tick"] <= tick:
                selected = point
            else:
                break
        return selected["seconds"] + (
            (tick - selected["tick"]) * selected["microseconds_per_beat"]
        ) / selected["tpq"] / 1_000_000

    measure_times = [(tick_to_seconds(tick), sig) for tick, sig in measure_boundaries]

    # Assign notes to measures
    measures = []
    for measure_num, (measure_time, time_sig) in enumerate(measure_times, 1):
        start_time = measure_time
        end_time = measure_times[measure_num][0] if measure_num < len(measure_times) else score_notes[-1].end + 1.0

        # Find notes in this measure
        start_idx = None
        end_idx = None
        for i, note in enumerate(score_notes):
            if start_idx is None and note.start >= start_time - 0.01:
                start_idx = i
            if note.start < end_time - 0.01:
                end_idx = i + 1

        if start_idx is not None and end_idx is not None:
            measures.append(ScoreMeasure(
                measure_num=measure_num,
                start_note_idx=start_idx,
                end_note_idx=end_idx,
                start_time=start_time,
                end_time=end_time,
                time_signature=time_sig,
            ))

    return measures


def parse_abcx_structure(abcx_path: Path, score_measures: list[ScoreMeasure]) -> tuple[list[Phrase], dict[int, str]]:
    """
    Step 2: Parse ABCX phrase structure and align with Score MIDI measures.

    Properly handles:
    - `::` repeat markers that split ABCX measures
    - Pickup (incomplete) measures at the beginning
    - Repeat-marker measures closing phrases
    - 4-measure phrase chunks (pickup measures don't count toward the 4)
    """
    abcx_measures_info = _parse_abcx_measures(abcx_path)
    if not abcx_measures_info:
        return [], {}

    n = len(abcx_measures_info)
    if n == 0:
        return [], {}

    # Get time signature info
    with open(abcx_path, encoding="utf-8") as f:
        abcx_lines = [line.rstrip() for line in f]
    expected_beats = 4.0
    for line in abcx_lines:
        if line.startswith("M:"):
            m = re.match(r'M:(\d+)/(\d+)', line)
            if m:
                expected_beats = int(m.group(1)) / int(m.group(2)) * 4
            break

    # Identify pickup measures: first measure(s) with duration < expected_beats
    pickup_set = set()
    for i, m_info in enumerate(abcx_measures_info):
        dur = _abc_measure_duration(m_info["content"])
        if dur < expected_beats * 0.6:
            pickup_set.add(m_info["num"])
        else:
            break  # only check from start

    # Identify phrase-closer measures (first-endings, or measures ending with `:`)
    phrase_closer_set = {m["num"] for m in abcx_measures_info if m.get("is_phrase_closer")}
    # Identify phrase-starter measures (second-endings, material after repeat)
    phrase_starter_set = {m["num"] for m in abcx_measures_info if m.get("is_phrase_starter")}

    # Build phrase groups: aim for ~4 full measures per phrase (4-8 range).
    # - Pickup measures: skip during main loop, attach to first phrase at end
    # - Phrase-closer measures: trigger close once we have >= target measures
    # - Phrase-starter measures: always start a new phrase
    # - Force close at max_phrase measures

    phrases = []
    phrase_num = 1
    current_phrase_measures = []
    full_count = 0
    target = 4
    max_phrase = 8

    for idx, mnum in enumerate(abcx_measures_info):
        num = mnum["num"]
        if num in pickup_set:
            continue  # pickups handled separately

        is_closer = num in phrase_closer_set
        is_starter = num in phrase_starter_set

        current_phrase_measures.append(num)
        full_count += 1

        # Determine if we should close this phrase
        should_close = False

        # Phrase-starter: close current phrase, but not if it only contains starters
        # (consecutive starters from `::` splits should stay grouped)
        if is_starter and full_count > 1:
            has_non_starter = any(
                m not in phrase_starter_set for m in current_phrase_measures
            )
            if has_non_starter:
                should_close = True
        # Phrase-closer with enough measures
        elif is_closer and full_count >= 2:
            should_close = True
        # Force close at max_phrase
        elif full_count >= max_phrase:
            should_close = True
        # Close at target+ if no closer/starter ahead
        elif full_count >= target:
            # Look ahead: if next measure is a closer, include it
            # If next measure is a starter, close now (starter begins new phrase)
            next_idx = idx + 1
            if next_idx < len(abcx_measures_info):
                next_num = abcx_measures_info[next_idx]["num"]
                next_is_closer = next_num in phrase_closer_set
                next_is_starter = next_num in phrase_starter_set
                if next_is_starter:
                    should_close = True  # close before starter
                elif next_is_closer:
                    pass  # wait for closer
                else:
                    should_close = True  # no structural boundary ahead
            else:
                should_close = True

        if should_close:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))
            phrase_num += 1
            current_phrase_measures = []
            full_count = 0

    if current_phrase_measures:
        phrases.append(Phrase(
            phrase_id=f"H{phrase_num}",
            measures=current_phrase_measures.copy(),
            has_linebreak=False,
        ))

    # Handle pickups: attach each pickup to the first non-pickup phrase
    if pickup_set and phrases:
        pickup_nums = sorted(pickup_set)
        first_full_idx = None
        for i, p in enumerate(phrases):
            if any(m not in pickup_set for m in p.measures):
                first_full_idx = i
                break

        if first_full_idx is not None:
            new_measures = pickup_nums + phrases[first_full_idx].measures
            phrases[first_full_idx] = Phrase(
                phrase_id=phrases[first_full_idx].phrase_id,
                measures=new_measures,
                has_linebreak=phrases[first_full_idx].has_linebreak,
            )

    abcx_measures = {m["num"]: m["content"] for m in abcx_measures_info}
    return phrases, abcx_measures


def build_midi_to_abcx_mapping(
    score_measures: list[ScoreMeasure],
    abcx_measures: dict[int, str],
    score_midi_path: Path,
    key: str = "G",
) -> dict[int, int]:
    """Build mapping from score MIDI measure number → ABCX measure number.

    Strategy:
    1. Extract content signatures (note count + pitch classes) for both MIDI and ABCX.
    2. Detect the repeat split point by comparing MIDI measure content.
    3. Map first-pass MIDI measures sequentially to ABCX measures.
    4. Map second-pass MIDI measures to the same ABCX as corresponding first-pass.
    5. If no repeat is detected, use content-based matching as fallback.
    """
    if not score_measures or not abcx_measures:
        return {}

    import pretty_midi as _pm
    from collections import defaultdict

    # Load Score MIDI to get actual note data
    score_midi = _pm.PrettyMIDI(str(score_midi_path))
    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    midi_nums = [m.measure_num for m in score_measures]
    num_midi = len(midi_nums)
    abcx_nums = sorted(abcx_measures.keys())
    num_abcx = len(abcx_nums)

    # Pitch class helpers
    pc_map = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    KEY_ACC: dict[str, dict[str, int]] = {
        "G": {"F": 1}, "D": {"F": 1, "C": 1}, "A": {"F": 1, "C": 1, "G": 1},
        "E": {"F": 1, "C": 1, "G": 1, "D": 1},
        "B": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1},
        "F#": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1},
        "F": {"B": -1}, "Bb": {"B": -1, "E": -1}, "Eb": {"B": -1, "E": -1, "A": -1},
        "Ab": {"B": -1, "E": -1, "A": -1, "D": -1},
    }
    key_acc = KEY_ACC.get(key, {})

    # Build measure lookup by measure number (not index-based)
    measure_by_num = {m.measure_num: m for m in score_measures}

    def midi_sig(mnum: int) -> tuple[int, frozenset[int]]:
        m = measure_by_num[mnum]
        notes_in_m = [n for n in score_notes if m.start_time <= n.start < m.end_time]
        count = len(notes_in_m)
        pcs = frozenset(n.pitch % 12 for n in notes_in_m)
        return count, pcs

    def abcx_sig(mnum: int) -> tuple[int, frozenset[int]]:
        text = abcx_measures[mnum]
        letters = re.findall(r'[A-Ga-g]', text)
        count = len(letters)
        all_pitches = re.findall(r'[\^=_]?[A-Ga-g]', text)
        pcs = set()
        for p in all_pitches:
            base = p[-1].upper()
            accidental = p[:-1]
            pc = pc_map.get(base, 0)
            if '^' in accidental:
                pc += 1
            elif '_' in accidental:
                pc -= 1
            elif base in key_acc:
                pc += key_acc[base]
            pcs.add(pc % 12)
        return count, frozenset(pcs)

    midi_sigs = {mnum: midi_sig(mnum) for mnum in midi_nums}
    abcx_sigs = {mnum: abcx_sig(mnum) for mnum in abcx_nums}

    def jaccard(a: frozenset, b: frozenset) -> float:
        if not a and not b:
            return 1.0
        return len(a & b) / len(a | b) if a | b else 0.0

    def match_score(mnum: int, abnum: int) -> float:
        """Score a MIDI→ABCX match. Higher is better."""
        mc, mp = midi_sigs[mnum]
        ac, ap = abcx_sigs[abnum]
        count_diff = abs(mc - ac)
        sim = jaccard(mp, ap)
        if count_diff == 0:
            return 1.0 + sim * 0.5
        return sim * 0.5 - count_diff * 0.1

    def match_score(mnum: int, abnum: int) -> float:
        """Score a MIDI→ABCX match. Higher is better."""
        mc, mp = midi_sigs[mnum]
        ac, ap = abcx_sigs[abnum]
        count_diff = abs(mc - ac)
        if count_diff == 0:
            jac = jaccard(mp, ap)
            return 10.0 + jac
        return -count_diff * 2.0 + jaccard(mp, ap) * 0.5

    # Use full-sequence content-based matching to find the best starting offset.
    # Slide a window of ALL MIDI measures across the ABCX and pick the offset
    # that maximizes total match score.
    mapping: dict[int, int] = {}

    best_start_idx = 0
    best_total = -999.0
    for offset in range(num_abcx - num_midi + 1):
        total = 0.0
        for k in range(num_midi):
            mnum = midi_nums[k]
            abnum = abcx_nums[offset + k]
            total += match_score(mnum, abnum)
        if total > best_total:
            best_total = total
            best_start_idx = offset

    # Map sequentially from the best offset; wrap for excess MIDI measures.
    for i in range(num_midi):
        mapping[midi_nums[i]] = abcx_nums[(best_start_idx + i) % num_abcx]

    return mapping


def build_midi_measure_content(
    score_measures: list[ScoreMeasure],
    abcx_measures: dict[int, str],
    midi_to_abcx: dict[int, int],
) -> dict[int, str]:
    """Expand ABCX measure content to each Score MIDI measure.

    Each MIDI measure gets the ABCX content of its mapped ABCX measure.
    When a MIDI measure maps to an ABCX measure that spans multiple MIDI
    measures, each gets the same content (the ABC notation is the same,
    just performed at different times).
    """
    content = {}
    for m in score_measures:
        abcx_num = midi_to_abcx.get(m.measure_num)
        if abcx_num is not None and abcx_num in abcx_measures:
            raw = abcx_measures[abcx_num]
            # Strip repeat markers: `::` becomes space
            cleaned = raw.replace("::", " ").strip()
            # Strip trailing `:` (leftover from `:|`)
            cleaned = re.sub(r':\s*$', '', cleaned).strip()
            # Strip leading `:` (leftover from `|:` where `|` was consumed)
            cleaned = cleaned.lstrip(':').strip()
            # Strip leading volta numbers like `1 ` or `2 ` (from `|1`, `|2`)
            cleaned = re.sub(r'^\d+\s+', '', cleaned).strip()
            content[m.measure_num] = cleaned
    return content


def _group_score_notes_by_onset(
    score_midi_path: Path,
    onset_epsilon: float = 1e-6,
) -> tuple[list[pretty_midi.Note], list[dict[str, float | int]]]:
    """Return score notes and contiguous note-index groups sharing an onset."""
    score_midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )
    groups: list[dict[str, float | int]] = []
    group_start = 0
    while group_start < len(score_notes):
        onset = score_notes[group_start].start
        group_end = group_start + 1
        note_end = score_notes[group_start].end
        while (
            group_end < len(score_notes)
            and abs(score_notes[group_end].start - onset) <= onset_epsilon
        ):
            note_end = max(note_end, score_notes[group_end].end)
            group_end += 1
        groups.append(
            {
                "start_idx": group_start,
                "end_idx": group_end,
                "start_time": onset,
                "end_time": note_end,
            }
        )
        group_start = group_end
    return score_notes, groups


def _abcx_onset_group_count(
    aligned_content: str,
    unit_length: Fraction,
    key_signature: str,
) -> int:
    """Count note-bearing onset groups in one simplified aligned ABCX measure."""
    groups = _parse_aligned_measure_events(aligned_content, unit_length, key_signature)
    return sum(1 for group in groups if group["all"])


def refine_score_measures_from_abcx_onsets(
    score_midi_path: Path,
    score_abcx: Path,
    score_measures: list[ScoreMeasure],
    midi_measure_content: dict[int, str],
) -> list[ScoreMeasure]:
    """Refine score-MIDI measure note ranges using ABCX onset-group counts.

    Some score MIDI files contain no bar markers and have measures whose note
    material is shifted by cross-voice rests or ties.  A pure time-signature
    grid then splits a musical measure in the middle.  The simplified ABCX
    layout gives a more stable per-measure onset count, so use it to place note
    ranges and let each measure duration grow to contain the assigned notes.
    """
    if not score_measures or not midi_measure_content:
        return score_measures

    try:
        lines = read_abcx_lines(score_abcx)
        unit_length = _parse_unit_length(lines)
        key_signature = _parse_key_signature(lines)
        aligned_content = build_aligned_measure_content(score_abcx, midi_measure_content)
        expected_group_counts = {
            measure.measure_num: _abcx_onset_group_count(
                aligned_content.get(measure.measure_num, ""),
                unit_length,
                key_signature,
            )
            for measure in score_measures
        }
    except Exception:
        return score_measures

    total_expected = sum(expected_group_counts.values())
    if total_expected <= 0:
        return score_measures

    score_notes, onset_groups = _group_score_notes_by_onset(score_midi_path)
    nominal_durations = [
        max(0.0, measure.end_time - measure.start_time)
        for measure in score_measures
    ]

    refined: list[ScoreMeasure] = []
    group_cursor = 0
    current_start_time = score_measures[0].start_time
    changed = False

    for index, measure in enumerate(score_measures):
        group_count = expected_group_counts.get(measure.measure_num, 0)
        nominal_duration = nominal_durations[index] if index < len(nominal_durations) else 0.0
        if group_count <= 0 or group_cursor + group_count > len(onset_groups):
            start_idx = measure.start_note_idx
            end_idx = measure.end_note_idx
            note_end_time = measure.end_time
        else:
            first_group = onset_groups[group_cursor]
            last_group = onset_groups[group_cursor + group_count - 1]
            start_idx = int(first_group["start_idx"])
            end_idx = int(last_group["end_idx"])
            group_starts = [
                float(onset_groups[group_cursor + offset]["start_time"])
                for offset in range(group_count)
            ]
            onset_steps = [
                b - a
                for a, b in zip(group_starts, group_starts[1:])
                if b > a
            ]
            if onset_steps:
                onset_steps.sort()
                final_step = onset_steps[len(onset_steps) // 2]
            else:
                final_step = nominal_duration
            note_end_time = group_starts[-1] + final_step
            group_cursor += group_count

        end_time = max(current_start_time + nominal_duration, note_end_time)
        if start_idx != measure.start_note_idx or end_idx != measure.end_note_idx:
            changed = True

        refined.append(
            ScoreMeasure(
                measure_num=measure.measure_num,
                start_note_idx=start_idx,
                end_note_idx=end_idx,
                start_time=current_start_time,
                end_time=end_time,
                time_signature=measure.time_signature,
            )
        )
        current_start_time = end_time

    return refined if changed else score_measures


def build_midi_phrases(
    score_measures: list[ScoreMeasure],
    midi_to_abcx: dict[int, int],
    midi_measure_content: dict[int, str],
    abcx_path: Path,
    expected_beats: float = 4.0,
) -> list[Phrase]:
    """Build phrases from expanded MIDI measures.

    Strategy: group consecutive measures into ~4-measure phrases.
    Use pickup detection from ABCX and `::`/`:` markers from the **original**
    ABCX structure to identify phrase boundaries, but only when they appear
    at natural structural points (not from cyclic repeats).
    """
    if not score_measures or not midi_measure_content:
        return []

    # Build the expanded measure list in MIDI order
    expanded = []
    for m in score_measures:
        mnum = m.measure_num
        content = midi_measure_content.get(mnum, "")
        if not content:
            continue
        expanded.append({"mnum": mnum, "content": content})

    if not expanded:
        return []

    # Get expected beats from ABCX header
    with open(abcx_path, encoding="utf-8") as f:
        abcx_lines = [line.rstrip() for line in f]
    for line in abcx_lines:
        if line.startswith("M:"):
            m = re.match(r'M:(\d+)/(\d+)', line)
            if m:
                expected_beats = int(m.group(1)) / int(m.group(2)) * 4
            break

    # Identify pickup measures from the **start** of the expanded list
    pickup_set = set()
    for i, m_info in enumerate(expanded):
        dur = _abc_measure_duration(m_info["content"])
        if dur < expected_beats * 0.6:
            pickup_set.add(m_info["mnum"])
        else:
            break

    # Build phrase groups: aim for 4 measures per phrase, force close at 8.
    # No `::`/`:` marker detection — just the 4-measure heuristic.
    phrases = []
    phrase_num = 1
    current_phrase_measures = []
    full_count = 0
    target = 4
    max_phrase = 8
    total = len(expanded)

    for idx, m_info in enumerate(expanded):
        mnum = m_info["mnum"]
        if mnum in pickup_set:
            continue

        current_phrase_measures.append(mnum)
        full_count += 1

        should_close = False
        remaining = total - idx - 1

        # Force close at max_phrase
        if full_count >= max_phrase:
            should_close = True
        # Close at target if there are enough remaining measures for another phrase
        elif full_count >= target and remaining >= target:
            should_close = True

        if should_close:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))
            phrase_num += 1
            current_phrase_measures = []
            full_count = 0

    # Handle trailing measures
    if current_phrase_measures:
        if len(current_phrase_measures) >= target:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))
        elif phrases:
            # Fewer than 4 measures left — merge into the last phrase
            phrases[-1].measures.extend(current_phrase_measures)
        else:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))

    # Attach pickups to first full phrase
    if pickup_set and phrases:
        pickup_nums = sorted(pickup_set)
        first_full_idx = None
        for i, p in enumerate(phrases):
            if any(m not in pickup_set for m in p.measures):
                first_full_idx = i
                break

        if first_full_idx is not None:
            new_measures = pickup_nums + phrases[first_full_idx].measures
            phrases[first_full_idx] = Phrase(
                phrase_id=phrases[first_full_idx].phrase_id,
                measures=new_measures,
                has_linebreak=phrases[first_full_idx].has_linebreak,
            )

    # Post-process: merge any phrase with fewer than `target` measures
    # into the previous phrase (or next if it's the first one).
    i = 0
    while i < len(phrases):
        if len(phrases[i].measures) < target:
            if i > 0:
                phrases[i - 1].measures.extend(phrases[i].measures)
            elif len(phrases) > 1:
                phrases[1].measures = phrases[i].measures + phrases[1].measures
            phrases.pop(i)
            if i > 0:
                i -= 1
        else:
            i += 1

    # Re-number phrases
    for i, p in enumerate(phrases, 1):
        p.phrase_id = f"H{i}"

    return phrases


def align_performance_with_score(
    score_midi_path: Path,
    perf_midi_path: Path,
    align_file: Path,
    score_structure: ScoreStructure,
) -> list[tuple[int, str, float, float]]:
    """
    Step 3: Align Performance MIDI with Score structure.

    Uses Score MIDI measures as the canonical unit. Each performance note is
    mapped to its corresponding Score MIDI measure via the alignment file.
    When the performer repeats a section, all performance notes for the same
    MIDI measure are merged into a single time range.

    Returns list of (midi_measure_num, phrase_id, start_time, end_time) tuples.
    """
    score_midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    perf_midi = pretty_midi.PrettyMIDI(str(perf_midi_path))

    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )
    perf_notes = sorted(
        [n for inst in perf_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    data = np.load(align_file, allow_pickle=True)
    perf_idx = data["perf_idx"]

    # Build score_times -> perf_times mapping
    score_times_arr = []
    perf_times_arr = []
    limit = min(len(score_notes), len(perf_idx))
    for score_idx in range(limit):
        perf_idx_value = int(perf_idx[score_idx])
        if 0 <= perf_idx_value < len(perf_notes):
            score_times_arr.append(score_notes[score_idx].start)
            perf_times_arr.append(perf_notes[perf_idx_value].start)

    score_times_arr = np.array(score_times_arr)
    perf_times_arr = np.array(perf_times_arr)

    # Build note-to-MIDI-measure mapping using the score structure
    note_to_midi_measure = {}
    for measure in score_structure.measures:
        for note_idx in range(measure.start_note_idx, measure.end_note_idx):
            note_to_midi_measure[note_idx] = measure.measure_num

    # Collect per-measure performance times
    perf_measure_times: dict[int, list[float]] = {}

    for score_idx in range(limit):
        perf_idx_value = int(perf_idx[score_idx])
        if not (0 <= perf_idx_value < len(perf_notes)):
            continue

        midi_mnum = note_to_midi_measure.get(score_idx)
        if midi_mnum is None:
            continue

        perf_time = perf_notes[perf_idx_value].start
        if midi_mnum not in perf_measure_times:
            perf_measure_times[midi_mnum] = []
        perf_measure_times[midi_mnum].append(perf_time)

    # Build contiguous time ranges for each MIDI measure.
    # The perf_measure_times gives us a distribution of performance times per
    # measure. We use min/max of these times, then merge gaps between
    # consecutive measures so that M[i].end == M[i+1].start.
    sorted_mnums = sorted(perf_measure_times.keys())
    if not sorted_mnums:
        return []

    # Step 1: compute raw per-measure time boundaries
    raw_bounds: dict[int, tuple[float, float]] = {}
    for mnum in sorted_mnums:
        times = perf_measure_times[mnum]
        raw_bounds[mnum] = (min(times), max(times))

    # Step 2: make measures contiguous — each measure's end becomes the next
    # measure's start, using the midpoint between max of current and min of next.
    contiguous: list[tuple[int, float, float]] = []
    for i, mnum in enumerate(sorted_mnums):
        raw_start, raw_end = raw_bounds[mnum]
        if i < len(sorted_mnums) - 1:
            next_mnum = sorted_mnums[i + 1]
            next_raw_start, _ = raw_bounds[next_mnum]
            contiguous_end = (raw_end + next_raw_start) / 2
        else:
            # Last measure: use raw end + small buffer
            contiguous_end = raw_end + 0.1
        contiguous_start = raw_start if i == 0 else contiguous[-1][2]
        contiguous.append((mnum, contiguous_start, contiguous_end))

    # Step 3: compute phrase-level contiguous time ranges
    phrase_bounds: dict[str, tuple[int, float, float]] = {}
    for _, mnum, start, end in [(i,) + c for i, c in enumerate(contiguous)]:
        phrase_id = score_structure.measure_to_phrase.get(mnum, "H1")
        if phrase_id not in phrase_bounds:
            phrase_bounds[phrase_id] = (mnum, start, end)
        else:
            _, ps, _ = phrase_bounds[phrase_id]
            phrase_bounds[phrase_id] = (mnum, ps, end)

    # Build result: phrase starts only when phrase changes
    result = []
    current_phrase = None
    for mnum, start, end in contiguous:
        phrase_id = score_structure.measure_to_phrase.get(mnum, "H1")
        if phrase_id != current_phrase:
            # Emit phrase header
            ps, pe = phrase_bounds[phrase_id][1], phrase_bounds[phrase_id][2]
            result.append((None, phrase_id, round(ps * 100), round(pe * 100)))
            current_phrase = phrase_id
        result.append((mnum, phrase_id, round(start * 100), round(end * 100)))

    return result


def write_aligned_abcx(
    original_abcx: Path,
    output_abcx: Path,
    phrases: list[Phrase],
    measure_content: dict[int, str],
) -> bool:
    """Write expanded ABCX file with H/M markers based on MIDI measure structure.

    Unlike the compact ABCX (which has one entry per score measure),
    this expanded version has one entry per Score MIDI measure (including repeats).
    """
    phrase_groups = [
        (phrase.phrase_id, phrase.measures, phrase.has_linebreak)
        for phrase in phrases
    ]
    measures = sorted(measure_content.items())

    try:
        text = build_aligned_abcx(original_abcx, measures, phrase_groups)
    except AlignedAbcxError:
        if output_abcx.exists():
            output_abcx.unlink()
        return False

    output_abcx.parent.mkdir(parents=True, exist_ok=True)
    with open(output_abcx, "w", encoding="utf-8") as f:
        f.write(text)
    return True

def generate_performance_tsv_with_phrases(
    perf_midi_path: Path,
    perf_entries: list[tuple[int | None, str, int, int]],
    output_tsv: Path,
    midi_tsv,
    measure_note_staffs: dict[int, list[str | None]] | None = None,
) -> bool:
    """Generate LM-MIDI TSV v0.3 with fixed 4-column event rows.

    perf_entries: list of (mnum|None, phrase_id, start_tick, end_tick)
    - (None, phrase_id, start, end) → phrase header
    - (mnum, phrase_id, start, end) → measure entry
    All times are already in integer ticks (100 ticks = 1 second).

    TSV columns are:
        event, value, duration, offset

    Note events use Logic Pro note names (MIDI 60 = C3).  Durations and
    offsets are 10 ms bins.  Structural and pedal PAD slots are written as 0.
    """
    def structural_row(event: str, value: int, duration: int) -> str:
        duration = max(0, min(65535, int(duration)))
        if event == "H":
            value %= 128
        return f"{event}\t{value}\t{duration // 256}\t{duration % 256}"

    perf_midi = pretty_midi.PrettyMIDI(str(perf_midi_path))

    all_notes = []
    for inst_idx, inst in enumerate(perf_midi.instruments):
        if inst.is_drum:
            continue
        for note in inst.notes:
            all_notes.append({
                "pitch": note.pitch,
                "start": note.start,
                "end": note.end,
                "dur": note.end - note.start,
                "vel": note.velocity,
            })
    all_notes.sort(key=lambda note: (note["start"], note["pitch"], note["end"], note["vel"]))

    all_pedals = []
    for inst in perf_midi.instruments:
        if inst.is_drum:
            continue
        for cc in inst.control_changes:
            if cc.number == 64:
                all_pedals.append({"t": cc.time, "val": cc.value})

    lines = [
        "# midi-tsv v0.3",
        f"# source={perf_midi_path.name}",
        "# unit=bin",
        "# bin_ms=10",
        "# columns=event\tvalue\tduration\toffset",
        "# pitch=logic-pro-note",
        "# middle_c=C3",
        "# nil=0",
        "# note_offset=previous_note_onset",
        "# pedal_offset=most_recent_note_onset",
        "# structural_duration=u16_hi_lo",
        "# slice_type=measure",
    ]

    # Build measure boundaries for pedal quantization
    measure_bounds = []
    for mnum_or_none, phrase_id, start_tick, end_tick in perf_entries:
        if mnum_or_none is not None:
            measure_bounds.append({
                "id": mnum_or_none,
                "start": start_tick,
                "end": end_tick,
            })

    # Quantize pedals across all notes
    pedal_dicts = [
        {"t": round(p["t"] * 100), "val": p["val"], "type": "sustain"}
        for p in all_pedals
    ]
    note_dicts = [
        {"t": round(n["start"] * 100), "end": round(n["end"] * 100)}
        for n in all_notes
    ]
    quantized_pedals = midi_tsv.smart_quantize_pedals_between_notes(
        pedal_dicts, note_dicts, measure_bounds
    )

    # Iterate through entries: phrase headers and measure entries are already ordered
    phrase_index = -1
    measure_global_index = -1
    last_note_tick: int | None = None
    note_cursor = 0
    quantized_pedals.sort(key=lambda pedal: int(pedal["t"]))
    pedal_cursor = 0

    for mnum_or_none, phrase_id, start_tick, end_tick in perf_entries:
        if mnum_or_none is None:
            phrase_index += 1
            lines.append(structural_row("H", phrase_index, end_tick - start_tick))
            continue

        # Find notes in this measure
        events = []
        while note_cursor < len(all_notes) and round(all_notes[note_cursor]["start"] * 100) < start_tick:
            note_cursor += 1
        note_scan = note_cursor
        while note_scan < len(all_notes):
            n = all_notes[note_scan]
            abs_start_tick = round(n["start"] * 100)
            if abs_start_tick >= end_tick:
                break
            dur_tick = round(n["dur"] * 100)
            events.append((abs_start_tick, 0, n["pitch"], dur_tick, n["vel"], n.get("staff")))
            note_scan += 1
        note_cursor = note_scan

        # Find quantized pedals in this measure
        while pedal_cursor < len(quantized_pedals) and int(quantized_pedals[pedal_cursor]["t"]) < start_tick:
            pedal_cursor += 1
        pedal_scan = pedal_cursor
        while pedal_scan < len(quantized_pedals):
            p = quantized_pedals[pedal_scan]
            p_tick = int(p["t"])
            if p_tick >= end_tick:
                break
            events.append((p_tick, 1, None, 0, p["val"], None))
            pedal_scan += 1
        pedal_cursor = pedal_scan

        # Structural rows do not affect note-offset reference.
        measure_global_index += 1
        lines.append(structural_row("M", measure_global_index % 128, end_tick - start_tick))

        note_staff_iter = iter(measure_note_staffs.get(mnum_or_none, [])) if measure_note_staffs else None

        # Notes establish the timing anchor.  Pedals at the same timestamp are
        # emitted after notes so they can attach to that note onset.
        events.sort(key=lambda e: (e[0], e[1], e[2] if e[2] is not None else 128))

        for abs_tick, kind, pitch, duration, value, _staff in events:
            if kind == 0:
                note_offset = 0 if last_note_tick is None else max(0, abs_tick - last_note_tick)
                last_note_tick = abs_tick
                note_name = midi_pitch_to_logic_note(int(pitch))
                event_staff = next(note_staff_iter, None) if note_staff_iter is not None else None
                if event_staff == "lower":
                    note_name += "L"
                for row in semantic_event_to_tsv_rows(
                    note_name,
                    int(value),
                    int(duration),
                    note_offset,
                ):
                    lines.append(tsv_row_to_line(row))
            else:
                pedal_offset = 0 if last_note_tick is None else max(0, abs_tick - last_note_tick)
                for row in semantic_event_to_tsv_rows("P", int(value), 0, pedal_offset):
                    lines.append(tsv_row_to_line(row))

    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_tsv, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return True


def build_score_entries(score_structure: ScoreStructure) -> list[tuple[int | None, str, int, int]]:
    """Build phrase/measure time entries directly from Score MIDI structure.

    The returned format matches `generate_performance_tsv_with_phrases()`:
    - `(None, phrase_id, start_tick, end_tick)` for phrase headers
    - `(measure_num, phrase_id, start_tick, end_tick)` for measure spans
    """
    if not score_structure.measures:
        return []

    measure_map = {measure.measure_num: measure for measure in score_structure.measures}
    phrase_bounds: dict[str, tuple[int, int]] = {}
    for phrase in score_structure.phrases:
        if not phrase.measures:
            continue
        first = measure_map.get(phrase.measures[0])
        last = measure_map.get(phrase.measures[-1])
        if first is None or last is None:
            continue
        phrase_bounds[phrase.phrase_id] = (
            round(first.start_time * 100),
            round(last.end_time * 100),
        )

    entries: list[tuple[int | None, str, int, int]] = []
    current_phrase = None
    for measure in score_structure.measures:
        phrase_id = score_structure.measure_to_phrase.get(measure.measure_num, "H1")
        if phrase_id != current_phrase:
            start_tick, end_tick = phrase_bounds.get(
                phrase_id,
                (round(measure.start_time * 100), round(measure.end_time * 100)),
            )
            entries.append((None, phrase_id, start_tick, end_tick))
            current_phrase = phrase_id
        entries.append(
            (
                measure.measure_num,
                phrase_id,
                round(measure.start_time * 100),
                round(measure.end_time * 100),
            )
        )
    return entries


def generate_score_tsv_with_phrases(
    score_midi_path: Path,
    score_structure: ScoreStructure,
    score_abcx_path: Path,
    output_tsv: Path,
    midi_tsv,
) -> bool:
    """Generate aligned score MIDI-TSV using score-derived phrase/measure spans."""
    score_entries = build_score_entries(score_structure)
    if not score_entries:
        return False
    measure_note_staffs = build_measure_note_staffs_from_aligned_abcx(
        score_midi_path,
        score_structure,
        score_abcx_path,
    )
    return generate_performance_tsv_with_phrases(
        score_midi_path,
        score_entries,
        output_tsv,
        midi_tsv,
        measure_note_staffs=measure_note_staffs,
    )


def build_score_structure_from_paths(
    score_midi: Path,
    score_abcx: Path,
    midi_tsv,
    mapping_source: Path | None = None,
) -> ScoreStructure | None:
    """Build ScoreStructure from explicit score MIDI and ABCX paths."""
    score_measures = extract_score_measures(score_midi, midi_tsv)
    if not score_measures:
        return None

    _, abcx_measures = parse_abcx_structure(score_abcx, score_measures)
    mapping_base = mapping_source if mapping_source is not None and mapping_source.exists() else score_midi
    midi_to_abcx = build_midi_to_abcx_mapping(score_measures, abcx_measures, mapping_base)

    midi_measure_content = build_midi_measure_content(score_measures, abcx_measures, midi_to_abcx)
    score_measures = refine_score_measures_from_abcx_onsets(
        score_midi,
        score_abcx,
        score_measures,
        midi_measure_content,
    )
    midi_phrases = build_midi_phrases(score_measures, midi_to_abcx, midi_measure_content, score_abcx)

    measure_to_phrase = {}
    for phrase in midi_phrases:
        for measure_num in phrase.measures:
            measure_to_phrase[measure_num] = phrase.phrase_id

    return ScoreStructure(
        measures=score_measures,
        phrases=midi_phrases,
        measure_to_phrase=measure_to_phrase,
        abcx_measures=abcx_measures,
        midi_to_abcx=midi_to_abcx,
        midi_measure_content=midi_measure_content,
    )


def _build_score_structure(
    score_midi: Path,
    score_abcx: Path,
    piece_dir: Path,
    midi_tsv,
) -> tuple[ScoreStructure, bool]:
    """Build ScoreStructure from a Score MIDI file. Returns (structure, success)."""
    # For content-based matching, prefer the raw full Score MIDI
    # to get pitch data for all measures including repeats
    raw_score_midi = piece_dir.parent.parent / piece_dir.relative_to(piece_dir.parent.parent) / "score_PDMX.mid"
    if not raw_score_midi.exists():
        raw_score_midi = None
    score_structure = build_score_structure_from_paths(
        score_midi,
        score_abcx,
        midi_tsv,
        mapping_source=raw_score_midi,
    )
    return score_structure, score_structure is not None


def _process_score_midi(
    score_midi: Path,
    score_abcx: Path,
    piece_dir: Path,
    refined_piece_dir: Path,
    output_piece_dir: Path,
    midi_tsv,
    suffix: str = "",
) -> int:
    """Process one Score MIDI version (main or mini).

    Generates:
    - score_structure{suffix}.json
    - score_aligned{suffix}.abcx
    - For each align file matching the score type: {perf}_refined.mid{suffix}.tsv

    suffix is "" for main, "_mini" for mini.
    """
    struct, ok = _build_score_structure(score_midi, score_abcx, piece_dir, midi_tsv)
    if not ok:
        return 0

    # Write score_structure.json (or _mini variant)
    json_path = output_piece_dir / f"score_structure{suffix}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "measures": [asdict(m) for m in struct.measures],
            "phrases": [asdict(p) for p in struct.phrases],
            "measure_to_phrase": struct.measure_to_phrase,
            "abcx_measures": struct.abcx_measures,
            "midi_to_abcx": struct.midi_to_abcx,
            "midi_measure_content": {str(k): v for k, v in sorted(struct.midi_measure_content.items())},
        }, f, indent=2, ensure_ascii=False)

    # Write score_aligned.abcx (or _mini variant)
    write_aligned_abcx(score_abcx, output_piece_dir / f"score_aligned{suffix}.abcx", struct.phrases, struct.midi_measure_content)

    # Step 3: Align performance MIDI files
    # Match align files to score type:
    #   main: *_refined_align.npz (not mini)
    #   mini: *_mini_refined_align.npz
    if suffix == "_mini":
        align_pattern = "*_mini_refined_align.npz"
    else:
        align_pattern = "*_refined_align.npz"
        # Exclude mini align files from main processing

    success_count = 0
    for align_file in refined_piece_dir.glob(align_pattern):
        if suffix != "_mini" and "_mini_" in align_file.name:
            continue

        # Determine corresponding perf MIDI name
        if suffix == "_mini":
            perf_midi_name = align_file.name.replace("_mini_refined_align.npz", "_mini_refined.mid")
        else:
            perf_midi_name = align_file.name.replace("_refined_align.npz", "_refined.mid")

        perf_midi = refined_piece_dir / perf_midi_name
        if not perf_midi.exists():
            continue

        perf_measures = align_performance_with_score(score_midi, perf_midi, align_file, struct)

        # Determine TSV output name
        if suffix == "_mini":
            # perf_midi_name is e.g. Aria_xxx_mini_refined.mid
            # TSV name should be Aria_xxx_mini_refined.tsv
            tsv_name = perf_midi_name + ".tsv"
        else:
            tsv_name = perf_midi_name + ".tsv"

        output_tsv = output_piece_dir / tsv_name
        perf_measure_note_staffs = build_performance_measure_note_staffs(
            score_midi,
            perf_midi,
            align_file,
            struct,
            score_abcx,
            perf_measures,
        )
        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_measures,
            output_tsv,
            midi_tsv,
            measure_note_staffs=perf_measure_note_staffs,
        ):
            success_count += 1

    return success_count


def process_piece(
    piece_dir: Path,
    refined_root: Path,
    output_dir: Path,
    midi_tsv,
) -> bool:
    """Main pipeline: run all three steps for one piece.

    DEPRECATED: use process_metadata_task() instead, which uses metadata.csv
    as the source of truth rather than directory scanning.
    """
    import shutil

    try:
        # Find required files
        score_abcx = piece_dir / "score.abcx"
        if not score_abcx.exists():
            return False

        # Map piece_dir (under PianoCoRe_output) to refined_piece_dir
        refined_piece_dir = None
        for base in [piece_dir.parent, piece_dir.parent.parent, piece_dir.parent.parent.parent]:
            try:
                rel_path = piece_dir.relative_to(base)
                candidate = refined_root / rel_path
                if (candidate / "score_PDMX_refined.mid").exists() or (candidate / "score_PDMX_mini_refined.mid").exists():
                    refined_piece_dir = candidate
                    break
            except ValueError:
                continue

        if refined_piece_dir is None:
            return False

        # Determine output directory
        output_piece_dir = output_dir / refined_piece_dir.relative_to(refined_root)
        output_piece_dir.mkdir(parents=True, exist_ok=True)

        # Copy original score.abcx (only once)
        shutil.copy2(score_abcx, output_piece_dir / "score.abcx")

        any_success = False

        # Main Score MIDI
        main_score = refined_piece_dir / "score_PDMX_refined.mid"
        if main_score.exists():
            count = _process_score_midi(
                main_score, score_abcx, piece_dir, refined_piece_dir,
                output_piece_dir, midi_tsv, suffix="",
            )
            any_success = any_success or count > 0

        # Mini Score MIDI (if exists)
        mini_score = refined_piece_dir / "score_PDMX_mini_refined.mid"
        if mini_score.exists():
            count = _process_score_midi(
                mini_score, score_abcx, piece_dir, refined_piece_dir,
                output_piece_dir, midi_tsv, suffix="_mini",
            )
            any_success = any_success or count > 0

        return any_success

    except Exception as exc:
        print(f"Error processing {piece_dir}: {exc}")
        return False


def process_metadata_task_legacy(
    task: dict,
    midi_tsv,
    refined_root: Path,
    abcx_root: Path,
    output_dir: Path,
) -> int:
    """Process one score file + its performances, driven by metadata.

    task: {
        'score_path': str,       # relative to refined_root, e.g. 'Composer/Piece/score_PDMX_refined.mid'
        'piece_path': str,       # relative to abcx_root, e.g. 'Composer/Piece'
        'suffix': str,           # '' or '_mini'
        'performances': [        # list of (perf_midi_path, align_path) relative to refined_root
            ('Composer/Piece/Aria_xxx_refined.mid', 'Composer/Piece/Aria_xxx_refined_align.npz'),
            ...
        ]
    }

    Returns number of successful TSV generations.
    """
    import shutil

    score_midi = refined_root / task['score_path']
    abcx_path = abcx_root / task['piece_path'] / 'score.abcx'
    piece_rel = task['piece_path']
    suffix = task['suffix']

    if not score_midi.exists() or not abcx_path.exists():
        return 0

    # Build score structure
    score_measures = extract_score_measures(score_midi, midi_tsv)
    if not score_measures:
        return 0

    _, abcx_measures = parse_abcx_structure(abcx_path, score_measures)

    # Use raw score MIDI for content matching fallback
    raw_score_midi = refined_root / task['score_path'].replace('_refined.mid', '.mid')
    mapping_source = raw_score_midi if raw_score_midi.exists() else score_midi
    midi_to_abcx = build_midi_to_abcx_mapping(score_measures, abcx_measures, mapping_source)

    midi_measure_content = build_midi_measure_content(score_measures, abcx_measures, midi_to_abcx)
    score_measures = refine_score_measures_from_abcx_onsets(
        score_midi,
        abcx_path,
        score_measures,
        midi_measure_content,
    )
    midi_phrases = build_midi_phrases(score_measures, midi_to_abcx, midi_measure_content, abcx_path)

    measure_to_phrase = {}
    for phrase in midi_phrases:
        for measure_num in phrase.measures:
            measure_to_phrase[measure_num] = phrase.phrase_id

    score_structure = ScoreStructure(
        measures=score_measures,
        phrases=midi_phrases,
        measure_to_phrase=measure_to_phrase,
        abcx_measures=abcx_measures,
        midi_to_abcx=midi_to_abcx,
        midi_measure_content=midi_measure_content,
    )

    # Output directory
    output_piece_dir = output_dir / piece_rel
    output_piece_dir.mkdir(parents=True, exist_ok=True)

    # Write score_structure.json (write once, skip if exists)
    json_path = output_piece_dir / f"score_structure{suffix}.json"
    if not json_path.exists():
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "measures": [asdict(m) for m in score_structure.measures],
                "phrases": [asdict(p) for p in score_structure.phrases],
                "measure_to_phrase": score_structure.measure_to_phrase,
                "abcx_measures": score_structure.abcx_measures,
                "midi_to_abcx": score_structure.midi_to_abcx,
                "midi_measure_content": {str(k): v for k, v in sorted(score_structure.midi_measure_content.items())},
            }, f, indent=2, ensure_ascii=False)

    aligned_abcx = output_piece_dir / f"score_aligned{suffix}.abcx"
    # Write score_aligned.abcx. Scores that cannot be projected to the two-staff
    # aligned format are removed/skipped by write_aligned_abcx.
    write_aligned_abcx(abcx_path, aligned_abcx, score_structure.phrases, score_structure.midi_measure_content)

    # Copy original score.abcx (write once)
    orig_abcx = output_piece_dir / "score.abcx"
    if not orig_abcx.exists():
        shutil.copy2(abcx_path, orig_abcx)

    # Process each performance
    success_count = 0
    for perf_midi_rel, align_rel in task['performances']:
        perf_midi = refined_root / perf_midi_rel
        align_file = refined_root / align_rel

        if not perf_midi.exists() or not align_file.exists():
            continue

        perf_measures = align_performance_with_score(score_midi, perf_midi, align_file, score_structure)

        # TSV output name: same as perf MIDI but with .tsv extension
        tsv_name = Path(perf_midi_rel).name + ".tsv"
        output_tsv = output_piece_dir / tsv_name

        perf_measure_note_staffs = build_performance_measure_note_staffs(
            score_midi,
            perf_midi,
            align_file,
            score_structure,
            aligned_abcx if aligned_abcx.exists() else abcx_path,
            perf_measures,
        )
        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_measures,
            output_tsv,
            midi_tsv,
            measure_note_staffs=perf_measure_note_staffs,
        ):
            success_count += 1

    return success_count


def process_metadata_task(
    task: dict,
    midi_tsv,
    pianocore_root: Path,
    output_dir: Path,
    overwrite_tsv: bool = False,
) -> int:
    """Process one score file + its performances, driven by metadata with refined priority.

    task: {
        'score_path': str,       # relative path from metadata, e.g. 'Composer/Piece/score_PDMX_refined.mid'
        'piece_path': str,       # piece identifier, e.g. 'Composer/Piece'
        'suffix': str,           # '' or '_mini'
        'performances': [        # list of (perf_midi_path, align_path) from metadata
            ('Composer/Piece/Aria_xxx_refined.mid', 'Composer/Piece/Aria_xxx_refined_align.npz'),
            ...
        ],
        'abcx_path': str,        # full path from metadata, e.g. 'PianoCoRe/score/Composer/Piece/score.abcx'
    }

    Returns number of successful TSV generations.
    """
    import shutil

    # Metadata paths for refined files live under `refined/`, while the
    # non-refined assets used by legacy ASAP rows live under `raw/`.
    score_path = task['score_path']
    if '_refined' in score_path or '_mini' in score_path:
        score_midi = pianocore_root / 'refined' / score_path
    else:
        score_midi = pianocore_root / 'raw' / score_path

    abcx_path = Path(task['abcx_path'])
    piece_rel = task['piece_path']
    suffix = task['suffix']

    if not score_midi.exists() or not abcx_path.exists():
        return 0

    # Use raw score MIDI for content matching fallback
    raw_score_path = task['score_path'].replace('_refined.mid', '.mid')
    if '_refined' in raw_score_path or '_mini' in raw_score_path:
        raw_score_midi = pianocore_root / 'refined' / raw_score_path
    else:
        raw_score_midi = pianocore_root / 'raw' / raw_score_path
    score_structure = build_score_structure_from_paths(
        score_midi,
        abcx_path,
        midi_tsv,
        mapping_source=raw_score_midi if raw_score_midi.exists() else score_midi,
    )
    if score_structure is None:
        return 0

    # Output directory
    output_piece_dir = output_dir / piece_rel
    output_piece_dir.mkdir(parents=True, exist_ok=True)

    # Write score_structure.json (write once, skip if exists)
    json_path = output_piece_dir / f"score_structure{suffix}.json"
    if not json_path.exists():
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "measures": [asdict(m) for m in score_structure.measures],
                "phrases": [asdict(p) for p in score_structure.phrases],
                "measure_to_phrase": score_structure.measure_to_phrase,
                "abcx_measures": score_structure.abcx_measures,
                "midi_to_abcx": score_structure.midi_to_abcx,
                "midi_measure_content": {str(k): v for k, v in sorted(score_structure.midi_measure_content.items())},
            }, f, indent=2, ensure_ascii=False)

    # Write score_aligned.abcx. Scores that cannot be projected to the two-staff
    # aligned format are removed/skipped by write_aligned_abcx.
    aligned_abcx = output_piece_dir / f"score_aligned{suffix}.abcx"
    write_aligned_abcx(abcx_path, aligned_abcx, score_structure.phrases, score_structure.midi_measure_content)

    # Copy original score.abcx (write once)
    orig_abcx = output_piece_dir / "score.abcx"
    if not orig_abcx.exists():
        shutil.copy2(abcx_path, orig_abcx)

    # Process each performance
    success_count = 0
    for perf_midi_rel, align_rel in task['performances']:
        # Metadata paths for refined files live under `refined/`, while the
        # non-refined assets used by legacy ASAP rows live under `raw/`.
        if '_refined' in perf_midi_rel or '_mini' in perf_midi_rel:
            perf_midi = pianocore_root / 'refined' / perf_midi_rel
            align_file = pianocore_root / 'refined' / align_rel
        else:
            perf_midi = pianocore_root / 'raw' / perf_midi_rel
            align_file = pianocore_root / 'raw' / align_rel

        if not perf_midi.exists() or not align_file.exists():
            continue

        perf_measures = align_performance_with_score(score_midi, perf_midi, align_file, score_structure)

        # TSV output name: same as perf MIDI but with .tsv extension
        tsv_name = Path(perf_midi_rel).name + ".tsv"
        output_tsv = output_piece_dir / tsv_name

        # Skip TSV generation if already exists and non-empty, unless the user
        # is intentionally building after a serialization fix.
        if not overwrite_tsv and output_tsv.exists() and output_tsv.stat().st_size > 0:
            success_count += 1
            continue

        perf_measure_note_staffs = build_performance_measure_note_staffs(
            score_midi,
            perf_midi,
            align_file,
            score_structure,
            aligned_abcx if aligned_abcx.exists() else abcx_path,
            perf_measures,
        )
        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_measures,
            output_tsv,
            midi_tsv,
            measure_note_staffs=perf_measure_note_staffs,
        ):
            success_count += 1

    return success_count


# Global references for worker processes (set by _worker_init)
_worker_refined_root = None
_worker_output_dir = None
_worker_abcx_root = None


def _worker_init_legacy(refined_root, output_dir, abcx_root):
    """Initialize worker process with required modules and paths."""
    global _worker_midi_tsv, _worker_refined_root, _worker_output_dir, _worker_abcx_root
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    _worker_midi_tsv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_worker_midi_tsv)
    _worker_refined_root = refined_root
    _worker_output_dir = output_dir
    _worker_abcx_root = abcx_root


def _worker_process_legacy(task):
    """Worker function for metadata-driven multiprocessing."""
    return process_metadata_task_legacy(task, _worker_midi_tsv, _worker_refined_root, _worker_abcx_root, _worker_output_dir)


# Worker functions for metadata-driven processing with refined priority
_worker_pianocore_root = None
_worker_overwrite_tsv = False


def _worker_init(pianocore_root, output_dir, overwrite_tsv=False):
    """Initialize worker process for metadata-driven processing with refined priority."""
    global _worker_midi_tsv, _worker_pianocore_root, _worker_output_dir, _worker_overwrite_tsv
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    _worker_midi_tsv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_worker_midi_tsv)
    _worker_pianocore_root = pianocore_root
    _worker_output_dir = output_dir
    _worker_overwrite_tsv = overwrite_tsv


def _worker_process(task):
    """Worker function for metadata-driven multiprocessing."""
    return process_metadata_task(
        task,
        _worker_midi_tsv,
        _worker_pianocore_root,
        _worker_output_dir,
        overwrite_tsv=_worker_overwrite_tsv,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete score-performance alignment with repeat detection"
    )
    parser.add_argument(
        "--metadata",
        default="PianoCoRe/metadata.csv",
        help="Path to metadata.csv",
    )
    parser.add_argument(
        "--pianocore-root",
        default="PianoCoRe",
        help="PianoCoRe root directory",
    )
    parser.add_argument(
        "--output-dir",
        default="PianoCoRe/aligned",
        help="Output directory (default: PianoCoRe/aligned)",
    )
    parser.add_argument(
        "--tier",
        default="all",
        choices=["a", "a_star", "b", "all"],
        help="Which tier to process (default: all)",
    )
    parser.add_argument(
        "--piece-filter",
        default=None,
        help="Process only pieces matching this substring",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of score files to process",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=16,
        help="Number of parallel workers (default: 16, use 0 for CPU count)",
    )
    parser.add_argument(
        "--overwrite-tsv",
        action="store_true",
        help="Regenerate TSV files even when the output path already exists",
    )
    args = parser.parse_args()

    import pandas as pd

    pianocore_root = Path(args.pianocore_root)
    output_dir = Path(args.output_dir)

    # ---- Step 1: Load metadata and filter ----
    meta = pd.read_csv(args.metadata)

    # Filter by tier
    if args.tier == 'a_star':
        meta = meta[meta['tier_a_star'] == True]
    elif args.tier == 'a':
        meta = meta[meta['tier_a'] == True]
    elif args.tier == 'b':
        meta = meta[meta['tier_b'] == True]
    # 'all' keeps everything

    # Filter: must have score_abcx_path
    meta = meta[meta['score_abcx_path'].notna()]

    # Filter: must have either refined or non-refined paths (prefer refined)
    # For score: refined_score_midi_path OR score_midi_path
    # For performance: refined_performance_midi_path OR performance_midi_path
    # For alignment: refined_alignment_path OR raw_alignment_path
    has_score = meta['refined_score_midi_path'].notna() | meta['score_midi_path'].notna()
    has_perf = meta['refined_performance_midi_path'].notna() | meta['performance_midi_path'].notna()
    has_align = meta['refined_alignment_path'].notna() | meta['raw_alignment_path'].notna()
    meta = meta[has_score & has_perf & has_align]

    # Apply piece filter
    if args.piece_filter:
        meta = meta[meta['score_abcx_path'].str.contains(args.piece_filter, na=False)]

    # ---- Step 2: Build tasks with refined priority ----
    # For each row, pick refined if available, otherwise use non-refined
    def get_paths(row):
        """Extract paths with refined priority."""
        score_midi = row['refined_score_midi_path'] if pd.notna(row['refined_score_midi_path']) else row['score_midi_path']
        perf_midi = row['refined_performance_midi_path'] if pd.notna(row['refined_performance_midi_path']) else row['performance_midi_path']
        align_path = row['refined_alignment_path'] if pd.notna(row['refined_alignment_path']) else row['raw_alignment_path']

        # Determine suffix based on score path
        suffix = '_mini' if '_mini' in str(score_midi) else ''

        return {
            'score_midi': score_midi,
            'perf_midi': perf_midi,
            'align_path': align_path,
            'abcx_path': row['score_abcx_path'],
            'suffix': suffix,
        }

    # Build task list
    tasks_dict = {}  # key: (score_midi, abcx_path, suffix), value: list of (perf_midi, align_path)

    for _, row in meta.iterrows():
        paths = get_paths(row)
        key = (paths['score_midi'], paths['abcx_path'], paths['suffix'])

        if key not in tasks_dict:
            tasks_dict[key] = []

        tasks_dict[key].append((paths['perf_midi'], paths['align_path']))

    # Convert to task list
    tasks = []
    for (score_midi, abcx_path, suffix), perfs in tasks_dict.items():
        # Extract piece_path from abcx_path (remove 'PianoCoRe/score/' prefix and '/score.abcx' suffix)
        abcx_rel = abcx_path.replace('PianoCoRe/score/', '').replace('/score.abcx', '')

        tasks.append({
            'score_path': score_midi,
            'piece_path': abcx_rel,
            'suffix': suffix,
            'performances': perfs,
            'abcx_path': abcx_path,
        })

    if args.limit:
        tasks = tasks[:args.limit]

    total_perfs = sum(len(t['performances']) for t in tasks)
    print(f"Found {len(tasks)} score files, {total_perfs} performances to process")

    # ---- Step 3: Process ----
    jobs = args.jobs
    if jobs == 0:
        import multiprocessing
        jobs = multiprocessing.cpu_count()

    if jobs <= 1:
        midi_tsv = load_midi_tsv_module()
        success_count = 0
        tsv_count = 0
        for task in tqdm(tasks):
            n = process_metadata_task(
                task,
                midi_tsv,
                pianocore_root,
                output_dir,
                overwrite_tsv=args.overwrite_tsv,
            )
            success_count += 1 if n > 0 else 0
            tsv_count += n
    else:
        from multiprocessing import Pool, cpu_count

        n_workers = min(jobs, len(tasks), cpu_count())
        init_args = (pianocore_root, output_dir, args.overwrite_tsv)

        with Pool(n_workers, initializer=_worker_init, initargs=init_args) as pool:
            results = list(tqdm(
                pool.imap(_worker_process, tasks),
                total=len(tasks),
            ))
        success_count = sum(1 for r in results if r > 0)
        tsv_count = sum(results)

    print(f"\n处理完成: {success_count} / {len(tasks)} 个 score 成功")
    print(f"生成 {tsv_count} 个 TSV 文件")
    print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    main()
