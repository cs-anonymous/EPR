#!/usr/bin/env python3
"""Utilities for the LM-MIDI TSV intermediate format.

The TSV format is a human-readable 4-column view of LM-MIDI events:

    event<TAB>value<TAB>duration<TAB>offset

Each row maps directly to one LM-MIDI event, with extension events inserted
automatically when converting to the compact token sequence.  TSV empty slots
are written as 0 and become <NIL> tokens.
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
TO_EXT = "EXT"

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
EXTENSION_EVENTS = {
    "EXD": "<EXD>",
    "EXO": "<EXO>",
}
ANNOTATION_EVENTS = {
    "A": "<A>",
    "AL": "<AL>",
    "OR": "<OR>",
    "ORL": "<ORL>",
    "D": "<D>",
    "DL": "<DL>",
    "RS": "<RS>",
    "RSL": "<RSL>",
    "RE": "<RE>",
    "REL": "<REL>",
    "EX": "<EX>",
    "EXL": "<EXL>",
    "FM": "<FM>",
    "PM": "<PM>",
    "TP": "<TP>",
    "MT": "<MT>",
    "KS": "<KS>",
}
NOTE_RE = re.compile(r"^([A-G])(#?)(-?\d+)(L?)$")


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
    """Parse a Logic Pro note name such as F#2, A#3, or C2L into MIDI pitch."""
    match = NOTE_RE.match(note_name)
    if not match:
        raise ValueError(f"Invalid Logic Pro note name: {note_name!r}")
    name = match.group(1) + match.group(2)
    octave = int(match.group(3))
    pitch = (octave + LOGIC_OCTAVE_OFFSET) * 12 + NOTE_TO_PC[name]
    if not 0 <= pitch <= 127:
        raise ValueError(f"Logic Pro note name out of MIDI range: {note_name!r} -> {pitch}")
    return pitch


def logic_note_is_lower_staff(note_name: str) -> bool:
    match = NOTE_RE.match(note_name)
    if not match:
        raise ValueError(f"Invalid Logic Pro note name: {note_name!r}")
    return match.group(4) == "L"


def t_token(value: int) -> str:
    _require_range(value, 0, MAX_U8, "T token value")
    return f"<T{value:03d}>"


def v_token(value: int) -> str:
    _require_range(value, 0, 127, "velocity/control value")
    return f"<V{value:03d}>"


def n_token(pitch: int, lower_staff: bool = False) -> str:
    _require_range(pitch, 0, 127, "pitch")
    prefix = "L" if lower_staff else "N"
    return f"<{prefix}{pitch:03d}>"


def nil_token() -> str:
    return "<NIL>"


def raw_symbol_token(value: str) -> str:
    if not value:
        raise ValueError("annotation symbol cannot be empty")
    return f"<{value}>"


def split_u16(value: int) -> tuple[int, int]:
    _require_range(value, 0, MAX_U16, "16-bit timing value")
    return divmod(value, 256)


def parse_lm_midi_tsv(text: str) -> list[tuple[str, str, str, str]]:
    """Parse event rows from LM-MIDI TSV text.

    Comment lines beginning with # and blank lines are ignored. Event rows must
    have exactly 4 tab-separated columns.
    """
    rows: list[tuple[str, str, str, str]] = []
    for line_idx, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw_line.rstrip("\n").split("\t")
        if len(parts) != 4:
            raise ValueError(f"Line {line_idx}: expected 4 tab-separated columns, got {len(parts)}")
        event = parts[0].strip()
        value = parts[1].strip()
        duration = parts[2].strip()
        offset = parts[3].strip()
        _validate_tsv_row(event, value, duration, offset, line_idx)
        rows.append((event, value, duration, offset))
    return rows


def lm_midi_tsv_to_tokens(text: str, wrap: bool = True, pretty: bool = False) -> str:
    """Convert LM-MIDI TSV text into a compact LM-MIDI token sequence."""
    token_events: list[str] = []
    for event, value, duration, offset in parse_lm_midi_tsv(text):
        token_events.extend(
            row_to_lm_midi_events(
                event,
                value,
                duration,
                offset,
            )
        )
    if wrap:
        token_events = ["<MIDI>", *token_events, "</MIDI>"]
    return "\n".join(token_events) if pretty else "".join(token_events)


def row_to_lm_midi_events(
    event: str,
    value: str,
    duration: str,
    offset: str,
) -> list[str]:
    """Convert one TSV row into one or more LM-MIDI token events."""
    if event in STRUCTURAL_EVENTS:
        value_u8 = _parse_required_int(value, f"{event} index")
        duration_val = _parse_required_int(duration, f"{event} duration")
        offset_val = _parse_required_int(offset, f"{event} offset")
        _require_range(value_u8, 0, 127, f"{event} index")
        _require_range(duration_val, 0, MAX_U8, f"{event} duration hi")
        _require_range(offset_val, 0, MAX_U8, f"{event} duration lo")
        return [f"{STRUCTURAL_EVENTS[event]}{v_token(value_u8)}{t_token(duration_val)}{t_token(offset_val)}"]

    if event in EXTENSION_EVENTS:
        pad_u8 = _parse_required_int(value, f"{event} pad")
        hi_u8 = _parse_required_int(duration, f"{event} hi")
        lo_u8 = _parse_required_int(offset, f"{event} lo")
        _require_pad(pad_u8, f"{event} pad")
        _require_range(hi_u8, 0, MAX_U8, f"{event} hi")
        _require_range(lo_u8, 0, MAX_U8, f"{event} lo")
        return [f"{EXTENSION_EVENTS[event]}{nil_token()}{t_token(hi_u8)}{t_token(lo_u8)}"]

    if event in ANNOTATION_EVENTS:
        if event == "FM":
            if value != "NIL" or duration != "NIL" or offset != "NIL":
                raise ValueError("FM event must use NIL in all trailing slots")
            return [f"{ANNOTATION_EVENTS[event]}{nil_token()}{nil_token()}{nil_token()}"]
        if event == "TP":
            if not re.fullmatch(r"V\d{3}", value):
                raise ValueError(f"TP value must be Vxxx, got {value!r}")
            if duration != "NIL" or offset != "NIL":
                raise ValueError("TP event must use NIL in duration/offset")
            return [f"{ANNOTATION_EVENTS[event]}<{value}>{nil_token()}{nil_token()}"]
        if value == "NIL":
            slot2 = nil_token()
        else:
            slot2 = raw_symbol_token(value)
        if duration != "NIL" or offset != "NIL":
            raise ValueError(f"{event} event must use NIL in duration/offset")
        return [f"{ANNOTATION_EVENTS[event]}{slot2}{nil_token()}{nil_token()}"]

    if event in PEDAL_EVENTS:
        value_u8 = _parse_required_int(value, f"{event} value")
        duration_u8 = _parse_required_int(duration, f"{event} duration")
        _require_range(value_u8, 0, 127, f"{event} value")
        _require_pad(duration_u8, f"{event} duration")
        events: list[str] = []
        offset_slot = _timing_slot_or_ext(offset, "EXO", events)
        events.append(f"{PEDAL_EVENTS[event]}{v_token(value_u8)}{nil_token()}{offset_slot}")
        return events

    pitch = logic_note_to_midi_pitch(event)
    lower_staff = logic_note_is_lower_staff(event)
    value_u8 = _parse_required_int(value, "note velocity")
    _require_range(value_u8, 0, 127, "note velocity")
    events = []
    duration_slot = _timing_slot_or_ext(duration, "EXD", events)
    offset_slot = _timing_slot_or_ext(offset, "EXO", events)
    events.append(f"{n_token(pitch, lower_staff=lower_staff)}{v_token(value_u8)}{duration_slot}{offset_slot}")
    return events


def semantic_event_to_tsv_rows(event: str, value: int, duration: int, offset: int) -> list[tuple[str, str, str, str]]:
    """Expand one semantic LM-MIDI event into strict 4-column TSV rows.

    All numeric TSV slots are kept in the 0..255 range. Long note durations
    and note/pedal offsets are emitted as explicit EX* rows, followed by a
    note/pedal row whose affected slot is set to EXT.
    """
    if event in STRUCTURAL_EVENTS:
        _require_range(value, 0, 127, f"{event} index")
        _require_range(duration, 0, MAX_U16, f"{event} duration")
        _require_pad(offset, f"{event} offset")
        hi, lo = split_u16(duration)
        return [(event, str(value), str(hi), str(lo))]

    if event in PEDAL_EVENTS:
        _require_range(value, 0, 127, f"{event} value")
        _require_pad(duration, f"{event} duration")
        rows: list[tuple[str, str, str, str]] = []
        offset_slot = _tsv_timing_slot_or_ext(offset, "EXO", rows)
        rows.append((event, str(value), "0", offset_slot))
        return rows

    if event in ANNOTATION_EVENTS:
        raise ValueError(f"semantic annotation event is not supported by semantic_event_to_tsv_rows: {event}")

    pitch = logic_note_to_midi_pitch(event)
    _require_range(pitch, 0, 127, "pitch")
    _require_range(value, 0, 127, "note velocity")
    rows = []
    duration_slot = _tsv_timing_slot_or_ext(duration, "EXD", rows)
    offset_slot = _tsv_timing_slot_or_ext(offset, "EXO", rows)
    rows.append((event, str(value), duration_slot, offset_slot))
    return rows


def tsv_row_to_line(row: tuple[str, str, str, str]) -> str:
    return "\t".join(row)


def _timing_slot_or_ext(value: str, ext_event: str, output_events: list[str]) -> str:
    if value == TO_EXT:
        return "<EXT>"
    value_int = _parse_required_int(value, f"{ext_event} timing value")
    _require_range(value_int, 0, MAX_U16, f"{ext_event} timing value")
    if value_int <= MAX_U8:
        return t_token(value_int)
    hi, lo = split_u16(value_int)
    output_events.append(f"<{ext_event}>{nil_token()}{t_token(hi)}{t_token(lo)}")
    return "<EXT>"


def _tsv_timing_slot_or_ext(value: int, ext_event: str, output_rows: list[tuple[str, str, str, str]]) -> str:
    _require_range(value, 0, MAX_U16, f"{ext_event} timing value")
    if value <= MAX_U8:
        return str(value)
    hi, lo = split_u16(value)
    output_rows.append((ext_event, "0", str(hi), str(lo)))
    return TO_EXT


def _parse_required_int(value: str, label: str) -> int:
    if value == TO_EXT:
        raise ValueError(f"{label} cannot be TO_EXT in this context")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer or TO_EXT, got {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be non-negative, got {parsed}")
    return parsed


def _validate_tsv_slot(value: str, label: str) -> None:
    if value == TO_EXT:
        return
    _parse_required_int(value, label)


def _validate_tsv_row(event: str, value: str, duration: str, offset: str, line_idx: int) -> None:
    label = f"Line {line_idx}"
    if event in ANNOTATION_EVENTS:
        if event == "FM":
            if value != "NIL" or duration != "NIL" or offset != "NIL":
                raise ValueError(f"{label}: FM must be FM\\tNIL\\tNIL\\tNIL")
            return
        if event == "TP":
            if not re.fullmatch(r"V\d{3}", value):
                raise ValueError(f"{label}: TP value must be Vxxx, got {value!r}")
            if duration != "NIL" or offset != "NIL":
                raise ValueError(f"{label}: TP must use NIL in duration/offset")
            return
        if duration != "NIL" or offset != "NIL":
            raise ValueError(f"{label}: {event} must use NIL in duration/offset")
        return

    if event in EXTENSION_EVENTS:
        _validate_tsv_slot(value, f"{label} value")
        _validate_tsv_slot(duration, f"{label} duration")
        _validate_tsv_slot(offset, f"{label} offset")
        return

    if event in STRUCTURAL_EVENTS:
        _validate_tsv_slot(value, f"{label} value")
        _validate_tsv_slot(duration, f"{label} duration")
        _validate_tsv_slot(offset, f"{label} offset")
        return

    if event in PEDAL_EVENTS:
        _validate_tsv_slot(value, f"{label} value")
        _validate_tsv_slot(duration, f"{label} duration")
        _validate_tsv_slot(offset, f"{label} offset")
        return

    _validate_tsv_slot(value, f"{label} value")
    _validate_tsv_slot(duration, f"{label} duration")
    _validate_tsv_slot(offset, f"{label} offset")


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
