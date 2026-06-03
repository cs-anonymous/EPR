#!/usr/bin/env python3
"""Convert ABCX files to MIDI using a native Python parser.

ABCX semantics:
- `;` separates voices within a measure/system
- `&` separates layers within one voice
- `|` separates measures within a visual line
- Visual lines are continuations: each voice's cursor carries across lines

Output: 2-track MIDI (Upper / Lower) with all notes at correct time offsets.
"""
from __future__ import annotations

import multiprocessing as mp
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pretty_midi

try:
    from scripts.align_score_performance import (
        _abc_duration_from_suffix,
        _default_tuplet_factor,
        _key_signature_accidentals,
        _parse_key_signature,
        _parse_unit_length,
        _split_top_level,
        parse_score_layout,
    )
except ModuleNotFoundError:
    from align_score_performance import (
        _abc_duration_from_suffix,
        _default_tuplet_factor,
        _key_signature_accidentals,
        _parse_key_signature,
        _parse_unit_length,
        _split_top_level,
        parse_score_layout,
    )

# ---------------------------------------------------------------------------
# ABC note-to-MIDI helpers
# ---------------------------------------------------------------------------

def _abc_note_to_midi(letter, accidental, octave_marks, state, key_accs):
    base_pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter.upper()]
    midi = 60 + base_pc
    if letter.islower():
        midi += 12
    for mark in octave_marks:
        midi += 12 if mark == "'" else -12
    key = f"{letter}{octave_marks}"
    if accidental:
        if accidental.startswith("^"):
            state[key] = accidental.count("^")
        elif accidental.startswith("_"):
            state[key] = -accidental.count("_")
        else:
            state[key] = 0
    offset = state.get(key, key_accs.get(letter.upper(), 0))
    return midi + offset


def _parse_note_atom(text, index):
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
            "letter": letter,
            "octave": "".join(octave),
            "accidental": "".join(accidental),
            "duration": "".join(duration),
            "tie_out": tie_out,
        },
        index,
    )


def _parse_chord_pitches(text, state, key_accs):
    inner = text[1:-1]
    pitches = []
    index = 0
    while index < len(inner):
        parsed = _parse_note_atom(inner, index)
        if parsed is None:
            index += 1
            continue
        atom, index = parsed
        pitches.append(_abc_note_to_midi(atom["letter"], atom["accidental"],
                                          atom["octave"], state, key_accs))
    return pitches


def _parse_layer_at_cursor(layer_text, cursor, unit_length, key_accs):
    """Parse one ABCX layer starting at the given cursor (in unit beats).
    Returns (end_cursor, list of (start_cursor, duration, midi_pitch))."""
    events = []
    pos = cursor
    tuplet_remaining = 0
    tuplet_factor = Fraction(1, 1)
    state = {}
    index = 0

    while index < len(layer_text):
        ch = layer_text[index]
        if ch.isspace() or ch in "~<>":
            index += 1
            continue
        if ch == '"':
            while index < len(layer_text) and layer_text[index] != '"':
                index += 1
            index += 1
            continue
        if ch == '!':
            while index < len(layer_text) and layer_text[index] != '!':
                index += 1
            index += 1
            continue
        if ch == '{':
            depth = 1
            index += 1
            while index < len(layer_text) and depth:
                if layer_text[index] == '{':
                    depth += 1
                elif layer_text[index] == '}':
                    depth -= 1
                index += 1
            continue
        if layer_text.startswith("[Q:", index) or layer_text.startswith("[M:", index) or layer_text.startswith("[K:", index):
            index += 1
            while index < len(layer_text) and layer_text[index] != ']':
                index += 1
            index += 1
            continue
        if ch == '(':
            m = re.match(r"\((\d+)(?::(\d+))?(?::(\d+))?", layer_text[index:])
            if m:
                count = int(m.group(1))
                in_time = int(m.group(2)) if m.group(2) else None
                notes_affected = int(m.group(3)) if m.group(3) else count
                tuplet_factor = Fraction(in_time, count) if in_time else _default_tuplet_factor(count)
                tuplet_remaining = notes_affected
                index += len(m.group(0))
                continue
            index += 1
            continue
        if ch == ')':
            index += 1
            continue
        if ch in "zx":
            index += 1
            suffix = []
            while index < len(layer_text) and (layer_text[index].isdigit() or layer_text[index] == "/"):
                suffix.append(layer_text[index])
                index += 1
            dur = _abc_duration_from_suffix("".join(suffix), unit_length)
            if tuplet_remaining:
                dur *= tuplet_factor
                tuplet_remaining -= 1
            if tuplet_remaining == 0:
                tuplet_factor = Fraction(1, 1)
            pos += dur
            continue
        if ch == '[':
            end = index + 1
            depth = 1
            while end < len(layer_text) and depth:
                if layer_text[end] == '[':
                    depth += 1
                elif layer_text[end] == ']':
                    depth -= 1
                end += 1
            if depth:
                break
            dur_start = end
            while end < len(layer_text) and (layer_text[end].isdigit() or layer_text[end] == "/"):
                end += 1
            tie = end < len(layer_text) and layer_text[end] == "-"
            if tie:
                end += 1
            pitches = _parse_chord_pitches(layer_text[index:end], state, key_accs)
            dur = _abc_duration_from_suffix(
                layer_text[dur_start:end - (1 if tie else 0)], unit_length,
            )
            if tuplet_remaining:
                dur *= tuplet_factor
                tuplet_remaining -= 1
            if tuplet_remaining == 0:
                tuplet_factor = Fraction(1, 1)
            for p in pitches:
                events.append((pos, dur, p))
            pos += dur
            index = end
            continue

        parsed = _parse_note_atom(layer_text, index)
        if parsed is None:
            index += 1
            continue
        atom, index = parsed
        pitch = _abc_note_to_midi(atom["letter"], atom["accidental"],
                                   atom["octave"], state, key_accs)
        dur = _abc_duration_from_suffix(atom["duration"], unit_length)
        if tuplet_remaining:
            dur *= tuplet_factor
            tuplet_remaining -= 1
        if tuplet_remaining == 0:
            tuplet_factor = Fraction(1, 1)
        events.append((pos, dur, pitch))
        pos += dur

    return pos, events


def _parse_tempo(lines):
    for line in lines:
        if line.startswith("Q:"):
            m = re.search(r'=(\d+)', line)
            if m:
                return int(m.group(1))
    return 120


def _parse_body_lines(lines, body_start):
    """Return list of non-empty, non-comment body lines."""
    body_lines = []
    for line in lines[body_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%") or stripped.startswith("V:") or stripped.startswith("%%"):
            continue
        body_lines.append(stripped)
    return body_lines


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_one(abcx_path_str: str, midi_out_str: str) -> tuple[str, bool, str]:
    abcx_path = Path(abcx_path_str)
    midi_out = Path(midi_out_str)

    try:
        text = abcx_path.read_text(encoding='utf-8')
    except Exception as e:
        return (abcx_path.name, False, f"read error: {e}")

    try:
        lines = text.split('\n')
    except Exception as e:
        return (abcx_path.name, False, f"split error: {e}")

    unit_length = _parse_unit_length(lines)
    key = _parse_key_signature(lines)
    key_accs = _key_signature_accidentals(key)
    tempo = _parse_tempo(lines)

    # Find body start (after K:)
    body_start = None
    for i, line in enumerate(lines):
        if line.startswith("K:"):
            body_start = i + 1
            break
    if body_start is None:
        return (abcx_path.name, False, "no K: line found")

    # Parse voice layout
    # layout.voice_order maps slot position → voice number.
    # E.g. %%score { (1 2 6) | (3 4 5) } → voice_order = [1, 2, 6, 3, 4, 5]
    # layout.staves maps [[upper_voices], [lower_voices]]
    try:
        layout = parse_score_layout(lines)
        voice_order = layout.voice_order  # e.g. [1, 2, 6, 3, 4, 5]
        upper_voice_indices = set(layout.staves[0])  # e.g. {1, 2, 6}
        lower_voice_indices = set(layout.staves[1])  # e.g. {3, 4, 5}
    except Exception:
        voice_order = None
        upper_voice_indices = {1}
        lower_voice_indices = {2}

    # Use layout voice count or fallback to body line max
    num_voices = len(voice_order) if voice_order else 2

    # Parse body lines and split into measures
    body_lines = _parse_body_lines(lines, body_start)
    if not body_lines:
        return (abcx_path.name, False, "empty body")

    # Each body line may contain multiple measures separated by `|`.
    # For each voice, we track a cursor that carries across ALL measures.
    voice_cursors = [Fraction(0, 1)] * (num_voices + 1)
    # Collect (start_beats, duration_beats, pitch, is_upper) for each note
    all_notes = []

    for visual_line in body_lines:
        # Split the visual line by `|` to get measure segments.
        # Within each segment, `;` separates voices.
        # `|` is guaranteed NOT to appear inside quotes/brackets/bangs.
        segments = [s.strip() for s in visual_line.split('|') if s.strip()]

        for segment in segments:
            # Split by `;` to get voice slots for this measure
            voice_parts = _split_top_level(segment, ';')

            for v_idx, v_text in enumerate(voice_parts):
                if voice_order is not None:
                    if v_idx < len(voice_order):
                        voice_num = voice_order[v_idx]
                    else:
                        continue
                else:
                    voice_num = v_idx + 1
                cursor = voice_cursors[voice_num]
                is_upper = voice_num in upper_voice_indices

                # Split by `&` for layers within this voice
                layer_parts = _split_top_level(v_text, '&')
                for layer_text in layer_parts:
                    layer_text = layer_text.strip()
                    if not layer_text or layer_text == '.':
                        continue
                    try:
                        end_cursor, events = _parse_layer_at_cursor(
                            layer_text, cursor, unit_length, key_accs,
                        )
                        for start_beats, dur_beats, pitch in events:
                            all_notes.append((start_beats, dur_beats, pitch, is_upper))
                    except Exception:
                        pass
                    if end_cursor > cursor:
                        # Don't advance cursor for `&` layers — they share the same cursor
                        pass

                # Advance the voice cursor only for the FIRST layer (primary voice content)
                # All layers are independent timelines from measure start
                # The measure's total duration is the max duration across all layers
                max_dur = Fraction(0, 1)
                for layer_text in layer_parts:
                    lt = layer_text.strip()
                    if not lt or lt == '.':
                        continue
                    try:
                        end_c, _events = _parse_layer_at_cursor(
                            lt, Fraction(0, 1), unit_length, key_accs,
                        )
                        if end_c > max_dur:
                            max_dur = end_c
                    except Exception:
                        pass
                if max_dur > 0:
                    voice_cursors[voice_num] += max_dur

    # Create MIDI
    # The ABC parser returns onsets/durations in WHOLE NOTE units (L: fraction of whole).
    # Q:1/4=120 means quarter note = 120 BPM = 0.5s.
    # 1 whole note = 4 quarter notes, so seconds_per_whole_note = 60/bpm * 4.
    seconds_per_whole = (60.0 / tempo) * 4.0
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    upper_inst = pretty_midi.Instrument(program=0, name="Upper")
    lower_inst = pretty_midi.Instrument(program=0, name="Lower")

    for start_beats, dur_beats, pitch, is_upper in all_notes:
        start_sec = float(start_beats) * seconds_per_whole
        dur_sec = float(dur_beats) * seconds_per_whole
        if dur_sec < 0.01:
            dur_sec = 0.05
        target = upper_inst.notes if is_upper else lower_inst.notes
        target.append(pretty_midi.Note(
            start=start_sec,
            end=start_sec + dur_sec,
            pitch=pitch,
            velocity=80,
        ))

    upper_inst.notes.sort(key=lambda n: n.start)
    lower_inst.notes.sort(key=lambda n: n.start)

    midi.instruments.append(upper_inst)
    midi.instruments.append(lower_inst)

    try:
        midi.write(str(midi_out))
    except Exception as e:
        return (abcx_path.name, False, f"write error: {e}")

    return (abcx_path.name, True, "")


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=32)
    parser.add_argument("--base", type=str, default="/home/sy/EPR/data/unpaired_abcx")
    args = parser.parse_args()

    base = Path(args.base)
    files = sorted(base.rglob("abcx/*.abcx"))

    # Only convert files that don't already have a .midi (or overwrite)
    tasks = []
    for f in files:
        midi_out = f.with_suffix(".midi")
        tasks.append((str(f), str(midi_out)))

    print(f"Found {len(tasks):,} .abcx files to convert")

    if not tasks:
        print("Nothing to do")
        return

    ok = 0
    fail = 0
    with mp.Pool(args.jobs) as pool:
        for name, success, msg in pool.starmap(convert_one, tasks):
            if success:
                ok += 1
            else:
                fail += 1
                if fail <= 10:
                    print(f"  FAIL {name}: {msg}")
            total = ok + fail
            if total % 500 == 0:
                print(f"  [{total}/{len(tasks)}] ok={ok} fail={fail}")

    print(f"Done: ok={ok:,} fail={fail:,} total={ok+fail:,}")


if __name__ == "__main__":
    main()
