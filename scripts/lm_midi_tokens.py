#!/usr/bin/env python3
"""Utilities for LM-MIDI token vocabulary and TSV serialization."""

from __future__ import annotations

import re
from typing import Iterable

try:
    from transformers import AddedToken
except Exception:  # pragma: no cover - lets lightweight callers import helpers.
    AddedToken = None


NOTE_BASE = {
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
}


def lm_midi_vocabulary() -> list[str]:
    tokens: list[str] = []
    tokens += [f"<N{i:03d}>" for i in range(128)]
    tokens += [f"<V{i:03d}>" for i in range(128)]
    tokens += [f"<T{i:03d}>" for i in range(256)]
    tokens += [
        "<MIDI>",
        "</MIDI>",
        "<EOS_MIDI>",
        "<NIL>",
        "<EXT>",
        "<EXD>",
        "<EXO>",
        "<M>",
        "<H>",
        "<P>",
        "<P1>",
        "<P2>",
    ]
    return tokens


def add_lm_midi_tokens(tokenizer) -> int:
    """Add LM-MIDI symbols as indivisible ordinary added tokens."""
    tokens = lm_midi_vocabulary()
    if AddedToken is None:
        return tokenizer.add_tokens(tokens)
    return tokenizer.add_tokens(
        [
            AddedToken(
                token,
                single_word=False,
                lstrip=False,
                rstrip=False,
                normalized=False,
            )
            for token in tokens
        ]
    )


def load_lm_midi_tokenizer(tokenizer_path: str, trust_remote_code: bool = True):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=trust_remote_code)
    add_lm_midi_tokens(tokenizer)
    return tokenizer


def pitch_name_to_midi(name: str) -> int:
    match = re.fullmatch(r"([A-G]#?)(-?\d+)", name)
    if not match:
        raise ValueError(f"invalid LM-MIDI pitch name: {name!r}")
    pitch, octave_text = match.groups()
    # Project convention follows Logic Pro naming: C3 == MIDI 60.
    midi = 12 * (int(octave_text) + 2) + NOTE_BASE[pitch]
    if not 0 <= midi <= 127:
        raise ValueError(f"pitch outside MIDI range: {name!r} -> {midi}")
    return midi


def _time_token(value: int | str) -> str:
    if value == "EXT":
        return "<EXT>"
    ivalue = int(value)
    if not 0 <= ivalue <= 255:
        raise ValueError(f"time token outside one-byte range: {ivalue}")
    return f"<T{ivalue:03d}>"


def _value_token(value: int | str) -> str:
    ivalue = int(value)
    if not 0 <= ivalue <= 127:
        raise ValueError(f"value token outside range: {ivalue}")
    return f"<V{ivalue:03d}>"


def _u16_tokens(value: int | str) -> tuple[str, str]:
    ivalue = int(value)
    if not 0 <= ivalue <= 65535:
        raise ValueError(f"u16 time outside range: {ivalue}")
    return f"<T{ivalue // 256:03d}>", f"<T{ivalue % 256:03d}>"


def phrase_index_token(index: int) -> tuple[str, int]:
    if index < 0:
        raise ValueError(f"phrase index outside range: {index}")
    return "<H>", index % 128


def structural_event_tokens(kind: str, index: int, duration: int | str) -> str:
    hi, lo = _u16_tokens(duration)
    if kind == "H":
        event_token, local = phrase_index_token(index)
        return f"{event_token}{_value_token(local)}{hi}{lo}"
    return f"<{kind}>{_value_token(index)}{hi}{lo}"


def measure_event_tokens(local_index: int, duration: int | str) -> str:
    return structural_event_tokens("M", local_index, duration)


def phrase_event_tokens(index: int, duration: int | str) -> str:
    return structural_event_tokens("H", index, duration)


def tsv_event_to_tokens(line: str) -> str:
    parts = line.replace("\t", " ").split()
    if len(parts) < 4:
        return ""

    event, value, duration, offset = parts[:4]
    prefix = ""

    if duration != "EXT" and int(duration) > 255:
        hi, lo = _u16_tokens(duration)
        prefix += f"<EXD><NIL>{hi}{lo}"
        duration = "EXT"
    if offset != "EXT" and int(offset) > 255:
        hi, lo = _u16_tokens(offset)
        prefix += f"<EXO><NIL>{hi}{lo}"
        offset = "EXT"

    if event in {"P", "P1", "P2"}:
        body = f"<{event}>{_value_token(value)}<NIL>{_time_token(offset)}"
    else:
        pitch = pitch_name_to_midi(event)
        body = f"<N{pitch:03d}>{_value_token(value)}{_time_token(duration)}{_time_token(offset)}"

    return prefix + body


def event_lines_to_tokens(lines: Iterable[str]) -> str:
    return "".join(token_text for line in lines if (token_text := tsv_event_to_tokens(line)))
