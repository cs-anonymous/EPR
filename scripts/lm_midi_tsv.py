#!/usr/bin/env python3
"""Utilities for the LM-MIDI TSV intermediate format.

The TSV format is a human-readable 4-column view of LM-MIDI events:

    event<TAB>value<TAB>duration<TAB>offset

Each row maps directly to one LM-MIDI event, with extension events inserted
automatically when converting to the compact token sequence.  TSV PAD slots
are written as 0 and become <SLOT_PAD> tokens.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_TO_PC = {name: idx for idx, name in enumerate(NOTE_NAMES_SHARP)}
LOGIC_MIDDLE_C_OCTAVE = 3
LOGIC_OCTAVE_OFFSET = 2  # MIDI 60 -> C3, so octave = pitch // 12 - 2.
MAX_U8 = 255
MAX_U16 = 65535

STRUCTURAL_EVENTS = {
    "H": "<H>",
    "M": "<M>",
    # Backward-compatible aliases for v0.3 drafts.
    "PHRASE": "<H>",
    "BAR": "<M>",
}
PEDAL_EVENTS = {
    "P": "<P>",
    "P1": "<P1>",
    "P2": "<P2>",
    # Backward-compatible aliases for v0.3 drafts.
    "PED_SUS": "<P>",
    "PED_SOFT": "<P1>",
    "PED_SOS": "<P2>",
}
NOTE_RE = re.compile(r"^([A-G])(#?)(-?\d+)$")


def midi_pitch_to_logic_note(pitch: int) -> str:
    """Return Logic Pro note spelling for a MIDI pitch number.

    Logic Pro's default MIDI terminology names MIDI note 60 as C3.
    Accidentals are spelled with sharps only to keep one absolute name per
    pitch class.
    """
    if not 0 <= pitch <= 127:
        raise ValueError(f"MIDI pitch out of range: {pitch}")
    return f"{NOTE_NAMES_SHARP[pitch % 12]}{pitch // 12 - LOGIC_OCTAVE_OFFSET}"


def logic_note_to_midi_pitch(note_name: str) -> int:
    """Parse a Logic Pro note name such as F#2 or A#3 into MIDI pitch."""
    match = NOTE_RE.match(note_name)
    if not match:
        raise ValueError(f"Invalid Logic Pro note name: {note_name!r}")
    name = match.group(1) + match.group(2)
    octave = int(match.group(3))
    pitch = (octave + LOGIC_OCTAVE_OFFSET) * 12 + NOTE_TO_PC[name]
    if not 0 <= pitch <= 127:
        raise ValueError(f"Logic Pro note name out of MIDI range: {note_name!r} -> {pitch}")
    return pitch


def t_token(value: int) -> str:
    _require_range(value, 0, MAX_U8, "T token value")
    return f"<T{value:03d}>"


def v_token(value: int) -> str:
    _require_range(value, 0, 127, "velocity/control value")
    return f"<V{value:03d}>"


def n_token(pitch: int) -> str:
    _require_range(pitch, 0, 127, "pitch")
    return f"<N{pitch:03d}>"


def split_u16(value: int) -> tuple[int, int]:
    _require_range(value, 0, MAX_U16, "16-bit timing value")
    return divmod(value, 256)


def parse_lm_midi_tsv(text: str) -> list[tuple[str, int, int, int]]:
    """Parse event rows from LM-MIDI TSV text.

    Comment lines beginning with # and blank lines are ignored. Event rows must
    have exactly 4 tab-separated columns.
    """
    rows: list[tuple[str, int, int, int]] = []
    for line_idx, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw_line.rstrip("\n").split("\t")
        if len(parts) != 4:
            raise ValueError(f"Line {line_idx}: expected 4 tab-separated columns, got {len(parts)}")
        event = parts[0].strip()
        try:
            value = int(parts[1])
            duration = int(parts[2])
            offset = int(parts[3])
        except ValueError as exc:
            raise ValueError(f"Line {line_idx}: value/duration/offset must be integers") from exc
        if value < 0 or duration < 0 or offset < 0:
            raise ValueError(f"Line {line_idx}: negative values are not allowed")
        rows.append((event, value, duration, offset))
    return rows


def lm_midi_tsv_to_tokens(text: str, wrap: bool = True, pretty: bool = False) -> str:
    """Convert LM-MIDI TSV text into a compact LM-MIDI token sequence."""
    token_events: list[str] = []
    for event, value, duration, offset in parse_lm_midi_tsv(text):
        token_events.extend(row_to_lm_midi_events(event, value, duration, offset))
    if wrap:
        token_events = ["<MIDI>", *token_events, "</MIDI>"]
    return "\n".join(token_events) if pretty else "".join(token_events)


def row_to_lm_midi_events(event: str, value: int, duration: int, offset: int) -> list[str]:
    """Convert one TSV row into one or more LM-MIDI token events."""
    if event in STRUCTURAL_EVENTS:
        _require_range(value, 0, MAX_U8, f"{event} index")
        _require_pad(offset, f"{event} offset")
        hi, lo = split_u16(duration)
        return [f"{STRUCTURAL_EVENTS[event]}{t_token(value)}{t_token(hi)}{t_token(lo)}"]

    if event in PEDAL_EVENTS:
        _require_range(value, 0, 127, f"{event} value")
        _require_pad(duration, f"{event} duration")
        events: list[str] = []
        offset_slot = _timing_slot_or_ext(offset, "EXT_OFF", events)
        events.append(f"{PEDAL_EVENTS[event]}{v_token(value)}<SLOT_PAD>{offset_slot}")
        return events

    pitch = logic_note_to_midi_pitch(event)
    _require_range(value, 0, 127, "note velocity")
    events = []
    duration_slot = _timing_slot_or_ext(duration, "EXT_DUR", events)
    offset_slot = _timing_slot_or_ext(offset, "EXT_OFF", events)
    events.append(f"{n_token(pitch)}{v_token(value)}{duration_slot}{offset_slot}")
    return events


def _timing_slot_or_ext(value: int, ext_event: str, output_events: list[str]) -> str:
    _require_range(value, 0, MAX_U16, f"{ext_event} timing value")
    if value <= MAX_U8:
        return t_token(value)
    hi, lo = split_u16(value)
    output_events.append(f"<{ext_event}>{t_token(hi)}{t_token(lo)}<SLOT_PAD>")
    return "<TO_EXT>"


def _require_range(value: int, low: int, high: int, label: str) -> None:
    if not low <= value <= high:
        raise ValueError(f"{label} out of range: {value} (expected {low}..{high})")


def _require_pad(value: int, label: str) -> None:
    if value != 0:
        raise ValueError(f"{label} is a PAD slot and must be 0, got {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert LM-MIDI TSV to LM-MIDI tokens")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tsv2tokens = subparsers.add_parser("tsv2tokens", help="Convert a 4-column TSV file to tokens")
    tsv2tokens.add_argument("tsv", type=Path, help="Input LM-MIDI TSV path")
    tsv2tokens.add_argument("--out", type=Path, default=None, help="Output token text path")
    tsv2tokens.add_argument("--no-wrap", action="store_true", help="Do not add <MIDI>...</MIDI>")
    tsv2tokens.add_argument("--pretty", action="store_true", help="Write one LM-MIDI event per line")

    args = parser.parse_args()

    if args.command == "tsv2tokens":
        text = args.tsv.read_text(encoding="utf-8")
        tokens = lm_midi_tsv_to_tokens(text, wrap=not args.no_wrap, pretty=args.pretty)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(tokens, encoding="utf-8")
        else:
            sys.stdout.write(tokens)


if __name__ == "__main__":
    main()
