#!/usr/bin/env python3
"""Generate annotated score MIDI TSV files from ABCX and score MIDI.

This script:
1. Parses score.abcx to extract annotations (dynamics, articulation, expression, etc.)
2. Uses existing alignment logic to map ABCX measures to score MIDI measures
3. Generates/loads score MIDI TSV
4. Merges annotations into the TSV at appropriate positions
5. Outputs score.annotated_score.mid.tsv for each piece

The alignment reuses the logic from align_score_performance.py to ensure consistency.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import existing alignment module
try:
    from scripts import align_score_performance as asp
    from scripts.lm_midi_tsv import midi_pitch_to_logic_note
except ModuleNotFoundError:
    import align_score_performance as asp
    from lm_midi_tsv import midi_pitch_to_logic_note


DEFAULT_METADATA = ROOT / "data" / "score_metadata.csv"
DEFAULT_PIANOCORE_ROOT = ROOT / "PianoCoRe"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "miditsv"
SCORE_MIDI_CANDIDATE_PREFIXES = ("score_PDMX", "score_MS", "score_ASAP", "score_ATEPP")

# Annotation token mappings (from lm_midi_tokenizer.md)
ARTICULATION_MAP = {
    "!>!": "accent",
    "!wedge!": "staccato",
    "!tenuto!": "tenuto",
    "!sfz!": "sfz",
}

DYNAMIC_MAP = {
    "!pppp!": "pppp",
    "!ppp!": "ppp",
    "!pp!": "pp",
    "!p!": "p",
    "!mp!": "mp",
    "!mf!": "mf",
    "!f!": "f",
    "!ff!": "ff",
    "!fff!": "fff",
    "!ffff!": "ffff",
}

ORNAMENT_MAP = {
    "!arpeggio!": "arpeggio",
    "!turn!": "turn",
}

RANGE_START_MAP = {
    "!<(!": "cre",
    "!>(!": "dim",
    "!trill(!": "trill",
}

RANGE_END_MAP = {
    "!<)!": "cre",
    "!>)!": "dim",
    "!trill)!": "trill",
}

PEDAL_MAP = {
    "^Ped.": "down",
    "^*": "up",
}

# Expression terms (≥10 occurrences) - normalized
EXPRESSION_MAP = {
    "a tempo": "a_tempo",
    "cresc": "cresc",
    "dim": "dim",
    "rit": "rit",
    "dolce": "dolce",
    "loco": "loco",
    "tempo i": "tempo_i",
    "poco rit": "poco_rit",
    "rall": "rall",
    "ten": "ten",
    "espress": "espress",
    "ritard": "ritard",
    "legato": "legato",
    "accel": "accel",
    "subito": "subito",
    "sempre": "sempre",
    "una corda": "una_corda",
    "sec": "sec",
    "marcato": "marcato",
    "molto rall": "molto_rall",
    "cédez": "cédez",
    "calando": "calando",
    "stretto": "stretto",
    "in tempo": "in_tempo",
    "leggiero": "leggiero",
    "sotto voce": "sotto_voce",
    "riten": "riten",
    "cantabile": "cantabile",
    "mouvt": "mouvt",
    "crescendo": "crescendo",
    "espressivo": "espressivo",
    "piu": "piu",
    "sostenuto": "sostenuto",
    "tranquillo": "tranquillo",
    "allargando": "allargando",
    "colla parte": "colla_parte",
    "dimin": "dimin",
    "agitato": "agitato",
    "poco ritard": "poco_ritard",
    "colla voce": "colla_voce",
    "pesante": "pesante",
    "rubato": "rubato",
}

# Meter types (≥10 occurrences)
VALID_METERS = {
    "4/4", "3/4", "2/4", "6/8", "2/2", "3/8", "9/8", "6/4", "3/2", "12/8",
    "5/4", "5/8", "4/8", "1/4", "12/16", "7/4", "7/8", "6/16", "4/2", "2/8",
    "1/8", "9/16", "9/4", "1/2", "3/16", "11/8", "8/8", "1/16", "12/32",
    "2/16", "4/16", "5/16", "8/32", "10/4", "17/16", "3/1", "10/8", "11/16",
    "2/1", "8/4", "9/2",
}

# Key signatures
KEY_MAP = {
    # Major keys
    "C": "key_C", "G": "key_G", "D": "key_D", "A": "key_A", "E": "key_E",
    "B": "key_B", "F#": "key_F#", "Db": "key_Db", "Ab": "key_Ab",
    "Eb": "key_Eb", "Bb": "key_Bb", "F": "key_F",
    # Minor keys
    "Am": "key_Am", "Em": "key_Em", "Bm": "key_Bm", "F#m": "key_F#m",
    "C#m": "key_C#m", "G#m": "key_G#m", "D#m": "key_D#m", "Bbm": "key_Bbm",
    "Fm": "key_Fm", "Cm": "key_Cm", "Gm": "key_Gm", "Dm": "key_Dm",
}


_worker_midi_tsv = None


def _worker_init() -> None:
    """Initialize worker process."""
    global _worker_midi_tsv
    _worker_midi_tsv = asp.load_midi_tsv_module()


@dataclass
class Annotation:
    """A musical annotation extracted from ABCX."""
    measure_num: int  # ABCX measure number (1-indexed)
    position: int  # Position within measure (0 = start, 1+ = after nth note)
    type: str  # annotation type: dynamic, articulation, ornament, expression, etc.
    value: str  # annotation value (token name)
    staff: str | None  # "upper" or "lower" (None = both/global)
    pitch_anchor: tuple[int, ...] | None = None  # Target chord pitches for precise insertion


@dataclass
class LayerAnnotationState:
    """Track cross-measure state for one ABCX layer."""
    pending_slur_starts: int = 0
    active_slurs: int = 0
    last_note_measure_num: int | None = None
    last_note_onset: Fraction | None = None


@dataclass
class ABCXHeader:
    """ABCX header information."""
    titles: list[str]
    composer: str | None
    source: str | None
    tempo: int | None  # BPM
    meter: str | None  # e.g., "2/4"
    key: str | None  # e.g., "D"


class ABCXAnnotationParser:
    """Parse musical annotations from ABCX files."""

    def __init__(self, abcx_path: Path):
        self.abcx_path = abcx_path
        self.content = abcx_path.read_text(encoding='utf-8')
        self.lines = self.content.split('\n')
        self.unit_length = asp._parse_unit_length(self.lines)
        self.key_signature = asp._parse_key_signature(self.lines)
        self.score_layout = None
        try:
            self.score_layout = asp.parse_score_layout(self.lines)
        except Exception:
            self.score_layout = None

    def extract_header(self) -> ABCXHeader:
        """Extract header information (T:, C:, Z:, Q:, M:, K:)."""
        titles = []
        composer = None
        source = None
        tempo = None
        meter = None
        key = None

        for line in self.lines:
            if line.startswith("T:"):
                titles.append(line[2:].strip())
            elif line.startswith("C:"):
                composer = line[2:].strip()
            elif line.startswith("Z:"):
                source = line[2:].strip()
            elif line.startswith("Q:"):
                # Parse tempo: Q:1/4=80 -> 80 BPM
                match = re.search(r'=(\d+)', line)
                if match:
                    tempo = int(match.group(1))
            elif line.startswith("M:"):
                meter = line[2:].strip()
            elif line.startswith("K:"):
                key = line[2:].strip()
                break  # K: is last header line

        return ABCXHeader(
            titles=titles,
            composer=composer,
            source=source,
            tempo=tempo,
            meter=meter,
            key=key,
        )

    def extract_annotations(self) -> list[Annotation]:
        """Extract all annotations from ABCX content.

        Strategy: Parse measure-by-measure, extract annotations at measure level.
        For simplicity, we place all annotations at the start of their measure.
        """
        timed_annotations_by_measure: dict[int, list[tuple[Fraction, str, str, str | None, tuple[int, ...] | None]]] = defaultdict(list)
        onsets_by_measure: dict[int, list[Fraction]] = {}
        layer_states: dict[tuple[str, int], LayerAnnotationState] = defaultdict(LayerAnnotationState)

        # Parse ABCX measures using existing logic
        abcx_measures = asp._parse_abcx_measures(self.abcx_path)

        for measure_info in abcx_measures:
            measure_num = measure_info["num"]
            content = measure_info["content"]
            if self.score_layout is not None:
                content = asp.simplify_measure_content(content, self.score_layout)

            # Extract annotations from this measure while preserving cross-measure span state.
            onsets_by_measure[measure_num] = self._extract_from_measure(
                content,
                measure_num,
                layer_states,
                timed_annotations_by_measure,
            )

        annotations: list[Annotation] = []
        for measure_num, timed_annotations in timed_annotations_by_measure.items():
            all_onsets = onsets_by_measure.get(measure_num, [])
            if not all_onsets:
                continue
            for onset_time, ann_type, ann_value, ann_staff, pitch_anchor in timed_annotations:
                effective_staff = ann_staff
                if ann_staff == "upper_aux":
                    effective_staff = "upper"

                position = len(all_onsets) - 1
                for idx, onset in enumerate(all_onsets):
                    if onset >= onset_time:
                        position = idx
                        break

                annotations.append(
                    Annotation(
                        measure_num=measure_num,
                        position=position,
                        type=ann_type,
                        value=ann_value,
                        staff=effective_staff,
                        pitch_anchor=pitch_anchor,
                    )
                )
        return annotations

    def _append_timed_annotation(
        self,
        timed_annotations_by_measure: dict[int, list[tuple[Fraction, str, str, str | None, tuple[int, ...] | None]]],
        measure_num: int,
        onset_time: Fraction,
        ann_type: str,
        ann_value: str,
        ann_staff: str | None,
        pitch_anchor: tuple[int, ...] | None = None,
    ) -> None:
        timed_annotations_by_measure[measure_num].append(
            (onset_time, ann_type, ann_value, ann_staff, pitch_anchor)
        )

    def _extract_from_measure(
        self,
        content: str,
        measure_num: int,
        layer_states: dict[tuple[str, int], LayerAnnotationState],
        timed_annotations_by_measure: dict[int, list[tuple[Fraction, str, str, str | None, tuple[int, ...] | None]]],
    ) -> list[Fraction]:
        """Extract timed annotations and onsets from a single measure."""
        staff_parts = asp._split_top_level(content, ";")
        if len(staff_parts) < 2:
            staff_parts += ["."] * (2 - len(staff_parts))

        onset_sources: dict[str, set[Fraction]] = {
            "upper_main": set(),
            "upper_aux": set(),
            "lower": set(),
        }

        for voice_idx, staff_text in enumerate(staff_parts[:2]):
            staff = "upper" if voice_idx == 0 else "lower"
            for layer_idx, layer_text in enumerate(asp._split_top_level(staff_text, "&")):
                layer_text = layer_text.strip()
                if not layer_text or layer_text == ".":
                    continue
                source_name = "lower"
                if staff == "upper":
                    source_name = "upper_main" if layer_idx == 0 else "upper_aux"
                for onset, _pitches in asp._parse_staff_layer_events(layer_text, self.unit_length, self.key_signature):
                    onset_sources[source_name].add(onset)
                self._extract_timed_annotations_from_layer(
                    layer_text,
                    staff,
                    layer_idx,
                    measure_num,
                    layer_states[(staff, layer_idx)],
                    timed_annotations_by_measure,
                )

        return sorted(set().union(*onset_sources.values()))

    def _extract_timed_annotations_from_layer(
        self,
        layer_text: str,
        staff: str,
        layer_idx: int,
        measure_num: int,
        layer_state: LayerAnnotationState,
        timed_annotations_by_measure: dict[int, list[tuple[Fraction, str, str, str | None, tuple[int, ...] | None]]],
    ) -> None:
        """Extract timed annotations from one layer.

        Timings are tracked in ABC measure-time units so annotations can later
        be attached to the first note onset at or after their textual position.
        """
        layer_staff = "upper_aux" if staff == "upper" and layer_idx > 0 else staff
        cursor = Fraction(0, 1)
        tuplet_remaining = 0
        tuplet_factor = Fraction(1, 1)
        index = 0

        def emit_current(ann_type: str, ann_value: str, pitch_anchor: tuple[int, ...] | None = None) -> None:
            self._append_timed_annotation(
                timed_annotations_by_measure,
                measure_num,
                cursor,
                ann_type,
                ann_value,
                layer_staff,
                pitch_anchor,
            )

        def emit_slur_start_here() -> None:
            if layer_state.pending_slur_starts <= 0:
                return
            for _ in range(layer_state.pending_slur_starts):
                emit_current("range_start", "slur")
            layer_state.active_slurs += layer_state.pending_slur_starts
            layer_state.pending_slur_starts = 0

        def remember_note_onset() -> None:
            layer_state.last_note_measure_num = measure_num
            layer_state.last_note_onset = cursor

        def emit_slur_end() -> None:
            if layer_state.active_slurs > 0 and layer_state.last_note_measure_num is not None and layer_state.last_note_onset is not None:
                self._append_timed_annotation(
                    timed_annotations_by_measure,
                    layer_state.last_note_measure_num,
                    layer_state.last_note_onset,
                    "range_end",
                    "slur",
                    layer_staff,
                    None,
                )
                layer_state.active_slurs -= 1
                return
            if layer_state.pending_slur_starts > 0:
                layer_state.pending_slur_starts -= 1

        while index < len(layer_text):
            char = layer_text[index]
            if char.isspace() or char in "~<>":
                index += 1
                continue
            if char == '"':
                end = index + 1
                while end < len(layer_text) and layer_text[end] != '"':
                    end += 1
                expr_text = layer_text[index + 1:end].strip()
                expr_normalized = expr_text.lower().replace('^', '').replace('_', '').replace('.', '').strip()
                if expr_text in PEDAL_MAP:
                    self._append_timed_annotation(
                        timed_annotations_by_measure,
                        measure_num,
                        cursor,
                        "pedal",
                        PEDAL_MAP[expr_text],
                        None,
                    )
                elif expr_normalized in EXPRESSION_MAP:
                    emit_current("expression", EXPRESSION_MAP[expr_normalized])
                index = min(end + 1, len(layer_text))
                continue
            if char == "!":
                end = index + 1
                while end < len(layer_text) and layer_text[end] != "!":
                    end += 1
                marker = layer_text[index:min(end + 1, len(layer_text))]
                if marker in DYNAMIC_MAP:
                    emit_current("dynamic", DYNAMIC_MAP[marker])
                elif marker in ARTICULATION_MAP:
                    emit_current("articulation", ARTICULATION_MAP[marker])
                elif marker in ORNAMENT_MAP:
                    pitch_anchor = None
                    if ORNAMENT_MAP[marker] == "arpeggio":
                        pitch_anchor = self._next_chord_pitch_anchor(
                            layer_text,
                            min(end + 1, len(layer_text)),
                        )
                    emit_current("ornament", ORNAMENT_MAP[marker], pitch_anchor)
                elif marker in RANGE_START_MAP:
                    emit_current("range_start", RANGE_START_MAP[marker])
                elif marker in RANGE_END_MAP:
                    emit_current("range_end", RANGE_END_MAP[marker])
                elif marker == "!fermata!":
                    emit_current("fermata", "fermata")
                index = min(end + 1, len(layer_text))
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
                index = min(index + 1, len(layer_text))
                continue
            if char == "(":
                match = re.match(r"\((\d+)(?::(\d+))?(?::(\d+))?", layer_text[index:])
                if match:
                    count = int(match.group(1))
                    in_time = int(match.group(2)) if match.group(2) else None
                    notes_affected = int(match.group(3)) if match.group(3) else count
                    tuplet_factor = Fraction(in_time, count) if in_time else asp._default_tuplet_factor(count)
                    tuplet_remaining = notes_affected
                    index += len(match.group(0))
                    continue
                layer_state.pending_slur_starts += 1
                index += 1
                continue
            if char == ")":
                emit_slur_end()
                index += 1
                continue
            if char in "zx":
                index += 1
                duration_suffix = []
                while index < len(layer_text) and (layer_text[index].isdigit() or layer_text[index] == "/"):
                    duration_suffix.append(layer_text[index])
                    index += 1
                duration = asp._abc_duration_from_suffix("".join(duration_suffix), self.unit_length)
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
                duration_start = end
                while end < len(layer_text) and (layer_text[end].isdigit() or layer_text[end] == "/"):
                    end += 1
                tie_out = end < len(layer_text) and layer_text[end] == "-"
                if tie_out:
                    end += 1
                emit_slur_start_here()
                remember_note_onset()
                duration = asp._abc_duration_from_suffix(
                    layer_text[duration_start:end - (1 if tie_out else 0)],
                    self.unit_length,
                )
                if tuplet_remaining:
                    duration *= tuplet_factor
                    tuplet_remaining -= 1
                if tuplet_remaining == 0:
                    tuplet_factor = Fraction(1, 1)
                cursor += duration
                index = end
                continue

            parsed = asp._parse_note_atom(layer_text, index)
            if parsed is None:
                index += 1
                continue
            atom, index = parsed
            emit_slur_start_here()
            remember_note_onset()
            duration = asp._abc_duration_from_suffix(str(atom["duration"]), self.unit_length)
            if tuplet_remaining:
                duration *= tuplet_factor
                tuplet_remaining -= 1
            if tuplet_remaining == 0:
                tuplet_factor = Fraction(1, 1)
            cursor += duration
        return None

    def _next_chord_pitch_anchor(self, layer_text: str, index: int) -> tuple[int, ...] | None:
        """Return the next chord/note pitch tuple after an annotation marker."""
        while index < len(layer_text):
            char = layer_text[index]
            if char.isspace() or char in "~<>":
                index += 1
                continue
            if char == '"':
                end = index + 1
                while end < len(layer_text) and layer_text[end] != '"':
                    end += 1
                index = min(end + 1, len(layer_text))
                continue
            if char == "!":
                end = index + 1
                while end < len(layer_text) and layer_text[end] != "!":
                    end += 1
                index = min(end + 1, len(layer_text))
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
                index = min(index + 1, len(layer_text))
                continue
            if char in "zx()":
                index += 1
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
                    return None
                chord_text = layer_text[index:end]
                if chord_text.startswith("[K:") or chord_text.startswith("[M:") or chord_text.startswith("[Q:"):
                    index = end
                    continue
                pitches = asp._parse_chord_pitches(
                    chord_text,
                    {},
                    asp._key_signature_accidentals(self.key_signature),
                )
                return tuple(sorted(pitches)) if pitches else None
            parsed = asp._parse_note_atom(layer_text, index)
            if parsed is None:
                index += 1
                continue
            atom, _next = parsed
            pitch = asp._abc_note_to_midi(
                str(atom["accidental"]),
                str(atom["letter"]),
                str(atom["octave"]),
                {},
                asp._key_signature_accidentals(self.key_signature),
            )
            return (pitch,)
        return None


def generate_score_midi_tsv_if_needed(
    score_midi_path: Path,
    score_abcx_path: Path,
    output_dir: Path,
    midi_tsv_module,
) -> Path | None:
    """Generate score MIDI TSV if it doesn't exist.

    Returns the path to the TSV file, or None if generation failed.
    """
    # Determine output path
    tsv_filename = score_midi_path.name + ".tsv"
    tsv_path = output_dir / tsv_filename

    if tsv_path.exists() and not _staff_regeneration_needed(tsv_path, score_midi_path, score_abcx_path, midi_tsv_module):
        return tsv_path

    # Generate using existing logic from build_score_midi_tsv.py
    try:
        structure, ok = _build_score_structure(score_midi_path, score_abcx_path, midi_tsv_module)
        if not ok or structure is None:
            return None

        # Generate TSV
        success = asp.generate_score_tsv_with_phrases(
            score_midi_path,
            structure,
            score_abcx_path,
            tsv_path,
            midi_tsv_module,
        )
        if success:
            return tsv_path

    except Exception as e:
        print(f"Error generating TSV for {score_midi_path}: {e}")

    return None


def _piece_rel_from_score_abcx_path(score_abcx_path: Path) -> Path | None:
    parts = score_abcx_path.parts
    if "score" in parts:
        idx = parts.index("score")
        return Path(*parts[idx + 1 : -1])
    if "miditsv" in parts:
        idx = parts.index("miditsv")
        return Path(*parts[idx + 1 : -1])
    return None


def _resolve_score_midi_from_piece(score_abcx_path: Path, pianocore_root: Path) -> Path | None:
    piece_rel = _piece_rel_from_score_abcx_path(score_abcx_path)
    if piece_rel is None:
        return None

    candidates: list[Path] = []
    for prefix in SCORE_MIDI_CANDIDATE_PREFIXES:
        candidates.append(pianocore_root / "refined" / piece_rel / f"{prefix}_refined.mid")
    for prefix in SCORE_MIDI_CANDIDATE_PREFIXES:
        candidates.append(pianocore_root / "raw" / piece_rel / f"{prefix}.mid")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return None


def _staff_regeneration_needed(
    tsv_path: Path,
    score_midi_path: Path,
    score_abcx_path: Path,
    midi_tsv_module,
) -> bool:
    """Regenerate cached TSV when aligned ABCX contains lower-staff notes but TSV does not."""
    if not score_midi_path.exists() or not score_abcx_path.exists():
        return False
    try:
        structure, ok = _build_score_structure(score_midi_path, score_abcx_path, midi_tsv_module)
        if not ok or structure is None:
            return False
        aligned_content = asp.build_aligned_measure_content(score_abcx_path, structure.midi_measure_content)
        lower_has_pitches = any(
            re.search(r"[\^_=]?[A-Ga-g][,']*", content.split(";", 1)[1])
            for content in aligned_content.values()
            if ";" in content
        )
        if not lower_has_pitches:
            return False

        with tsv_path.open("r", encoding="utf-8") as f:
            for line in f:
                if "\t" not in line or line.startswith("#"):
                    continue
                event = line.split("\t", 1)[0]
                if re.fullmatch(r"[A-G]#?-?\d+L", event):
                    return False
        return True
    except Exception:
        return False


def _build_score_structure(score_midi_path, score_abcx_path, midi_tsv_module):
    """Build score structure via the main alignment pipeline."""
    try:
        return asp._build_score_structure(
            score_midi_path,
            score_abcx_path,
            score_midi_path.parent,
            midi_tsv_module,
        )

    except Exception as e:
        print(f"Error building structure: {e}")
        import traceback
        traceback.print_exc()
        return None, False


def generate_midi_from_abcx(abcx_path: Path, output_midi_path: Path) -> bool:
    """Convert ABCX to MIDI using abc2midi.

    Returns True if successful, False otherwise.
    """
    try:
        output_midi_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ['abc2midi', str(abcx_path), '-o', str(output_midi_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        return output_midi_path.exists() and output_midi_path.stat().st_size > 0

    except subprocess.TimeoutExpired:
        print(f"Timeout converting {abcx_path}")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error converting {abcx_path}: {e.stderr}")
        return False
    except Exception as e:
        print(f"Unexpected error converting {abcx_path}: {e}")
        return False


def generate_annotation_only_tsv(
    header: ABCXHeader,
    annotations: list[Annotation],
    output_path: Path,
) -> bool:
    """Generate TSV with only annotations (no note events) for scores without MIDI.

    This is useful for unpaired scores where we only have ABCX but no score MIDI.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = []

        # Header
        lines.append('# midi-tsv v0.4\n')
        lines.append('# source=annotation_only\n')
        lines.append('# columns=event\tvalue\tduration\toffset\n')
        lines.append('# note: This file contains only annotations extracted from ABCX\n')
        lines.append('# note: No score MIDI available, so no note events included\n')

        # Score header info as comments for strict TSV parsers.
        if header.titles:
            for title in header.titles:
                lines.append(f'# T:{title}\n')
        if header.composer:
            lines.append(f'# C:{header.composer}\n')
        lines.append('\n')

        # Global annotations
        if header.key and header.key in KEY_MAP:
            lines.append(f'KS\t{KEY_MAP[header.key]}\tNIL\tNIL\n')

        if header.tempo:
            quantized = round(header.tempo / 3)
            if quantized > 127:
                quantized = 127
            lines.append(f'TP\tV{quantized:03d}\tNIL\tNIL\n')

        if header.meter and header.meter in VALID_METERS:
            meter_token = f'meter_{header.meter}'
            lines.append(f'MT\t{meter_token}\tNIL\tNIL\n')

        # Group annotations by measure
        annotations_by_measure = defaultdict(list)
        for ann in annotations:
            annotations_by_measure[ann.measure_num].append(ann)

        # Write annotations measure by measure
        for measure_num in sorted(annotations_by_measure.keys()):
            lines.append(f'# Measure {measure_num}\n')
            for ann in annotations_by_measure[measure_num]:
                ann_line = _format_annotation(ann)
                if ann_line:
                    lines.append(ann_line)

        # Write output
        normalized_lines = [line if line.endswith('\n') else line + '\n' for line in lines]
        with output_path.open('w', encoding='utf-8') as f:
            f.writelines(normalized_lines)

        return True

    except Exception as e:
        print(f"Error generating annotation-only TSV: {e}")
        return False


def merge_annotations_into_tsv(
    tsv_path: Path,
    annotations: list[Annotation],
    header: ABCXHeader,
    output_path: Path,
    midi_to_abcx: dict[int, int],
) -> bool:
    """Merge annotations into existing score MIDI TSV.

    Strategy:
    1. Read existing TSV
    2. Group annotations by MIDI measure number (using midi_to_abcx mapping)
    3. Insert annotation events at the start of each measure
    4. Add global annotations (KS, TP, MT) at the very beginning
    5. Write annotated TSV
    """
    if not tsv_path.exists():
        return False

    try:
        # Read existing TSV
        with tsv_path.open('r', encoding='utf-8') as f:
            lines = f.readlines()

        # Separate header and data
        header_lines = []
        data_lines = []
        for line in lines:
            if line.startswith('#'):
                header_lines.append(line)
            else:
                data_lines.append(line)

        # Update header to v0.4
        updated_header = []
        for line in header_lines:
            if line.startswith('# midi-tsv v'):
                updated_header.append('# midi-tsv v0.4\n')
            else:
                updated_header.append(line)

        # Add score header info as comments for strict TSV parsers.
        if header.titles:
            for title in header.titles:
                updated_header.append(f'# T:{title}\n')
        if header.composer:
            updated_header.append(f'# C:{header.composer}\n')
        if header.source:
            updated_header.append(f'# Z:{header.source}\n')
        updated_header.append('\n')

        # Group annotations by MIDI measure number. One ABCX measure may map to
        # multiple expanded MIDI measures (repeats), so replicate annotations.
        annotations_by_measure = defaultdict(list)
        abcx_to_midi = defaultdict(list)
        for midi_measure, abcx_measure in midi_to_abcx.items():
            abcx_to_midi[abcx_measure].append(midi_measure)
        for ann in annotations:
            for midi_measure in abcx_to_midi.get(ann.measure_num, []):
                annotations_by_measure[midi_measure].append(ann)

        # Build output with annotations inserted
        output_lines = updated_header.copy()

        # Add global annotations at the beginning
        if header.key and header.key in KEY_MAP:
            output_lines.append(f'KS\t{KEY_MAP[header.key]}\tNIL\tNIL\n')

        if header.tempo:
            # Quantize tempo: divide by 3 and round
            quantized = round(header.tempo / 3)
            if quantized > 127:
                quantized = 127
            output_lines.append(f'TP\tV{quantized:03d}\tNIL\tNIL\n')

        if header.meter and header.meter in VALID_METERS:
            meter_token = f'meter_{header.meter}'
            output_lines.append(f'MT\t{meter_token}\tNIL\tNIL\n')

        current_measure_num = 0
        current_measure_lines: list[str] | None = None

        def flush_measure() -> None:
            nonlocal current_measure_lines
            if current_measure_lines is None:
                return
            anns = annotations_by_measure.get(current_measure_num, [])
            output_lines.extend(_insert_annotations_into_measure_lines(current_measure_lines, anns))
            current_measure_lines = None

        for line in data_lines:
            if line.startswith('M\t'):
                flush_measure()
                current_measure_num += 1
                current_measure_lines = [line]
            elif current_measure_lines is not None:
                current_measure_lines.append(line)
            else:
                output_lines.append(line)

        flush_measure()

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_lines = [line if line.endswith('\n') else line + '\n' for line in output_lines]
        with output_path.open('w', encoding='utf-8') as f:
            f.writelines(normalized_lines)

        return True

    except Exception as e:
        print(f"Error merging annotations: {e}")
        return False


def _format_annotation(ann: Annotation) -> str | None:
    """Format an annotation as a TSV line."""
    if ann.type == "dynamic":
        event_type = "DL" if ann.staff == "lower" else "D"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "articulation":
        event_type = "AL" if ann.staff == "lower" else "A"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "ornament":
        event_type = "ORL" if ann.staff == "lower" else "OR"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "range_start":
        event_type = "RSL" if ann.staff == "lower" else "RS"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "range_end":
        event_type = "REL" if ann.staff == "lower" else "RE"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "expression":
        event_type = "EXL" if ann.staff == "lower" else "EX"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "pedal":
        return f'PM\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "fermata":
        return f'FM\tNIL\tNIL\tNIL\n'

    return None


NOTE_EVENT_RE = re.compile(r'^[A-G]#?-?\d+L?$')


def _is_note_event(event: str) -> bool:
    return NOTE_EVENT_RE.fullmatch(event) is not None


def _is_extension_event(event: str) -> bool:
    return event in {"EXD", "EXO"}


def _parse_note_pitch(event: str) -> int | None:
    note = event[:-1] if event.endswith("L") else event
    match = re.fullmatch(r'([A-G]#?)(-?\d+)', note)
    if not match:
        return None
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


def _pitch_classes(pitches: set[int] | tuple[int, ...]) -> set[int]:
    return {pitch % 12 for pitch in pitches}


def _insert_annotations_into_measure_lines(
    measure_lines: list[str],
    annotations: list[Annotation],
) -> list[str]:
    if not measure_lines:
        return []
    if not annotations:
        return measure_lines

    priority = {
        "ornament": 0,
        "articulation": 1,
        "range_start": 2,
        "range_end": 3,
        "fermata": 4,
        "dynamic": 5,
        "expression": 6,
        "pedal": 7,
    }
    ordered_annotations = sorted(
        annotations,
        key=lambda ann: (ann.position, priority.get(ann.type, 99)),
    )
    body = measure_lines[1:]

    onset_group_ranges: list[tuple[int, int, int, set[int]]] = []
    current_group_start: int | None = None
    current_group_end: int | None = None
    current_insert_start: int | None = None
    current_group_insert_start: int | None = None
    current_group_pitches: set[int] = set()
    for idx, line in enumerate(body):
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 4:
            continue
        event, _value, _duration, offset = parts[:4]
        if _is_extension_event(event):
            current_insert_start = idx
            continue
        if not _is_note_event(event):
            continue
        if current_group_start is None or offset != '0':
            if current_group_start is not None and current_group_end is not None:
                insert_start = (
                    current_group_insert_start
                    if current_group_insert_start is not None
                    else current_group_start
                )
                onset_group_ranges.append((insert_start, current_group_start, current_group_end, current_group_pitches))
            current_group_start = idx
            current_group_insert_start = current_insert_start
            current_insert_start = None
            current_group_pitches = set()
        current_group_end = idx
        pitch = _parse_note_pitch(event)
        if pitch is not None:
            current_group_pitches.add(pitch)

    if current_group_start is not None and current_group_end is not None:
        insert_start = (
            current_group_insert_start
            if current_group_insert_start is not None
            else current_group_start
        )
        onset_group_ranges.append((insert_start, current_group_start, current_group_end, current_group_pitches))

    result = [measure_lines[0]]
    if not onset_group_ranges:
        for ann in ordered_annotations:
            ann_line = _format_annotation(ann)
            if ann_line:
                result.append(ann_line)
        result.extend(body)
        return result

    annotations_by_start: dict[int, list[str]] = defaultdict(list)
    annotations_by_end: dict[int, list[str]] = defaultdict(list)
    for ann in ordered_annotations:
        position = min(ann.position, len(onset_group_ranges) - 1)
        if ann.pitch_anchor:
            anchor_pitches = set(ann.pitch_anchor)
            anchor_pitch_classes = _pitch_classes(ann.pitch_anchor)
            for group_idx in range(position, len(onset_group_ranges)):
                _insert_start, _group_start, _group_end, group_pitches = onset_group_ranges[group_idx]
                if anchor_pitches.issubset(group_pitches):
                    position = group_idx
                    break
                if anchor_pitch_classes.issubset(_pitch_classes(group_pitches)):
                    position = group_idx
                    break
        insert_start, group_start, group_end, _group_pitches = onset_group_ranges[position]
        ann_line = _format_annotation(ann)
        if ann_line is None:
            continue
        has_extension_prefix = insert_start != group_start
        if has_extension_prefix:
            annotations_by_start[insert_start].append(ann_line)
        elif ann.type == "pedal":
            annotations_by_end[group_end].append(ann_line)
        else:
            annotations_by_start[insert_start].append(ann_line)

    for idx, line in enumerate(body):
        for ann_line in annotations_by_start.get(idx, []):
            result.append(ann_line)
        result.append(line)
        for ann_line in annotations_by_end.get(idx, []):
            result.append(ann_line)

    return result


def process_score(task: dict[str, str]) -> dict[str, Any]:
    """Process a single score file."""
    score_abcx_path = Path(task["score_abcx_path"])
    score_midi_path = Path(task["score_midi_path"]) if task.get("score_midi_path") else None
    output_path = Path(task["output_path"])

    if not score_abcx_path.exists():
        return {"ok": False, "error": "ABCX not found", "path": str(score_abcx_path)}

    # Parse ABCX
    try:
        parser = ABCXAnnotationParser(score_abcx_path)
        header = parser.extract_header()
        annotations = parser.extract_annotations()
    except Exception as e:
        return {"ok": False, "error": f"ABCX parse error: {e}", "path": str(score_abcx_path)}

    # If no score MIDI, generate it from ABCX
    if not score_midi_path or not score_midi_path.exists():
        # Generate MIDI from ABCX (use unique filename per ABCX)
        generated_midi_filename = score_abcx_path.stem + ".generated.mid"
        generated_midi_path = score_abcx_path.parent / generated_midi_filename
        success = generate_midi_from_abcx(score_abcx_path, generated_midi_path)

        if success:
            score_midi_path = generated_midi_path
        else:
            # If MIDI generation fails, create annotation-only TSV
            success = generate_annotation_only_tsv(header, annotations, output_path)
            if success:
                return {"ok": True, "output": str(output_path), "path": str(score_abcx_path), "type": "annotation_only"}
            else:
                return {"ok": False, "error": "Failed to generate MIDI and annotation-only TSV", "path": str(score_abcx_path)}

    # Generate or load score MIDI TSV. If the provided score MIDI is corrupt,
    # fall back to an abc2midi-rendered temporary MIDI so annotation coverage
    # is not blocked by broken source MIDI files.
    tsv_path = generate_score_midi_tsv_if_needed(
        score_midi_path,
        score_abcx_path,
        score_abcx_path.parent,
        _worker_midi_tsv,
    )

    if not tsv_path:
        generated_midi_filename = score_abcx_path.stem + ".fallback.generated.mid"
        generated_midi_path = score_abcx_path.parent / generated_midi_filename
        success = generate_midi_from_abcx(score_abcx_path, generated_midi_path)
        if success:
            score_midi_path = generated_midi_path
            tsv_path = generate_score_midi_tsv_if_needed(
                score_midi_path,
                score_abcx_path,
                score_abcx_path.parent,
                _worker_midi_tsv,
            )

    if not tsv_path:
        success = generate_annotation_only_tsv(header, annotations, output_path)
        if success:
            return {"ok": True, "output": str(output_path), "path": str(score_abcx_path), "type": "annotation_only_fallback"}
        return {"ok": False, "error": "Failed to generate/load TSV", "path": str(score_abcx_path)}

    # Build midi_to_abcx mapping
    try:
        structure, ok = _build_score_structure(
            score_midi_path,
            score_abcx_path,
            _worker_midi_tsv,
        )
        if not ok or structure is None:
            midi_to_abcx = {i: i for i in range(1, 1000)}  # fallback: 1:1 mapping
        else:
            midi_to_abcx = structure.midi_to_abcx
    except Exception:
        midi_to_abcx = {i: i for i in range(1, 1000)}

    # Merge annotations
    success = merge_annotations_into_tsv(
        tsv_path,
        annotations,
        header,
        output_path,
        midi_to_abcx,
    )

    if success:
        return {"ok": True, "output": str(output_path), "path": str(score_abcx_path), "type": "full"}
    else:
        return {"ok": False, "error": "Failed to merge annotations", "path": str(score_abcx_path)}


def build_tasks(metadata_csv: Path, pianocore_root: Path) -> list[dict[str, str]]:
    """Build task list from metadata."""
    tasks = []

    with metadata_csv.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            score_abcx_path = row.get("score_abcx_path", "").strip()
            if not score_abcx_path:
                continue

            # Resolve full paths
            abcx_full = Path(score_abcx_path)

            # Skip if ABCX doesn't exist
            if not abcx_full.exists():
                continue

            # Determine score MIDI path (prefer refined)
            score_midi_rel = row.get("refined_score_midi_path", "").strip()
            is_refined = True
            if not score_midi_rel:
                score_midi_rel = row.get("score_midi_path", "").strip()
                is_refined = False

            # Resolve MIDI path if available
            midi_full = None
            if score_midi_rel:
                # Score MIDI is in PianoCoRe/refined/ or PianoCoRe/raw/
                if is_refined:
                    midi_full = pianocore_root / "refined" / score_midi_rel
                else:
                    midi_full = pianocore_root / "raw" / score_midi_rel
                if midi_full and not midi_full.exists():
                    midi_full = None
            if midi_full is None:
                midi_full = _resolve_score_midi_from_piece(abcx_full, pianocore_root)

            # Output path: same directory as ABCX, with ABCX filename stem
            output_filename = abcx_full.stem + ".annotated_score.mid.tsv"
            output_path = abcx_full.parent / output_filename

            tasks.append({
                "score_abcx_path": str(abcx_full),
                "score_midi_path": str(midi_full) if midi_full else None,
                "output_path": str(output_path),
            })

    return tasks


def cleanup_legacy_annotated_tsvs(output_dir: Path) -> int:
    removed = 0
    for path in output_dir.rglob("annotated_score.mid.tsv"):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--pianocore-root", type=Path, default=DEFAULT_PIANOCORE_ROOT)
    parser.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() // 2))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, help="Limit number of files to process (for testing)")
    args = parser.parse_args()

    print("Building task list...")
    tasks = build_tasks(args.metadata, args.pianocore_root)

    if args.limit:
        tasks = tasks[:args.limit]

    print(f"Found {len(tasks)} scores to process")

    if not args.overwrite:
        # Filter out existing files
        tasks = [t for t in tasks if not Path(t["output_path"]).exists()]
        print(f"After filtering existing: {len(tasks)} tasks remaining")

    if not tasks:
        print("No tasks to process")
        return

    print(f"Processing with {args.jobs} workers...")

    results = []
    with mp.Pool(processes=args.jobs, initializer=_worker_init) as pool:
        for result in pool.imap_unordered(process_score, tasks):
            results.append(result)
            if result["ok"]:
                print(f"✓ {result['path']}")
            else:
                print(f"✗ {result['path']}: {result['error']}")

    # Summary
    success_count = sum(1 for r in results if r["ok"])
    print(f"\nCompleted: {success_count}/{len(results)} successful")
    removed_legacy = cleanup_legacy_annotated_tsvs(DEFAULT_OUTPUT_DIR)
    print(f"Legacy annotated TSVs removed: {removed_legacy}")


if __name__ == "__main__":
    main()
