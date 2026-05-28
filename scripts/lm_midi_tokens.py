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

ANNOTATED_EVENT_TOKENS = [
    "<A>",
    "<AL>",
    "<OR>",
    "<ORL>",
    "<D>",
    "<DL>",
    "<RS>",
    "<RSL>",
    "<RE>",
    "<REL>",
    "<EX>",
    "<EXL>",
    "<FM>",
    "<PM>",
    "<TP>",
    "<MT>",
    "<KS>",
]

ANNOTATED_SUBTYPE_TOKENS = [
    "<a_tempo>",
    "<accel>",
    "<accent>",
    "<agitato>",
    "<allargando>",
    "<arpeggio>",
    "<calando>",
    "<cantabile>",
    "<colla_parte>",
    "<colla_voce>",
    "<cre>",
    "<cresc>",
    "<crescendo>",
    "<cédez>",
    "<dim>",
    "<dimin>",
    "<dolce>",
    "<down>",
    "<espress>",
    "<espressivo>",
    "<f>",
    "<ff>",
    "<fff>",
    "<ffff>",
    "<in_tempo>",
    "<key_A>",
    "<key_Ab>",
    "<key_Am>",
    "<key_B>",
    "<key_Bb>",
    "<key_Bbm>",
    "<key_Bm>",
    "<key_C#m>",
    "<key_C>",
    "<key_Cm>",
    "<key_D#m>",
    "<key_D>",
    "<key_Db>",
    "<key_Dm>",
    "<key_E>",
    "<key_Eb>",
    "<key_Em>",
    "<key_F#>",
    "<key_F#m>",
    "<key_F>",
    "<key_Fm>",
    "<key_G#m>",
    "<key_G>",
    "<key_Gm>",
    "<legato>",
    "<leggiero>",
    "<loco>",
    "<marcato>",
    "<meter_1/16>",
    "<meter_1/2>",
    "<meter_1/4>",
    "<meter_1/8>",
    "<meter_10/4>",
    "<meter_10/8>",
    "<meter_11/16>",
    "<meter_11/8>",
    "<meter_12/16>",
    "<meter_12/32>",
    "<meter_12/8>",
    "<meter_17/16>",
    "<meter_2/16>",
    "<meter_2/1>",
    "<meter_2/2>",
    "<meter_2/4>",
    "<meter_2/8>",
    "<meter_3/16>",
    "<meter_3/1>",
    "<meter_3/2>",
    "<meter_3/4>",
    "<meter_3/8>",
    "<meter_4/16>",
    "<meter_4/2>",
    "<meter_4/4>",
    "<meter_4/8>",
    "<meter_5/16>",
    "<meter_5/4>",
    "<meter_5/8>",
    "<meter_6/16>",
    "<meter_6/4>",
    "<meter_6/8>",
    "<meter_7/4>",
    "<meter_7/8>",
    "<meter_8/32>",
    "<meter_8/4>",
    "<meter_8/8>",
    "<meter_9/16>",
    "<meter_9/2>",
    "<meter_9/4>",
    "<meter_9/8>",
    "<mf>",
    "<molto_rall>",
    "<mouvt>",
    "<mp>",
    "<p>",
    "<pesante>",
    "<piu>",
    "<poco_rit>",
    "<poco_ritard>",
    "<pp>",
    "<ppp>",
    "<pppp>",
    "<rall>",
    "<rit>",
    "<ritard>",
    "<riten>",
    "<rubato>",
    "<sec>",
    "<sempre>",
    "<sfz>",
    "<slur>",
    "<sostenuto>",
    "<sotto_voce>",
    "<staccato>",
    "<stretto>",
    "<subito>",
    "<tempo_i>",
    "<ten>",
    "<tenuto>",
    "<tranquillo>",
    "<trill>",
    "<turn>",
    "<una_corda>",
    "<up>",
]


def lm_midi_performance_vocabulary() -> list[str]:
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


def lm_midi_full_vocabulary() -> list[str]:
    tokens = lm_midi_performance_vocabulary()
    tokens += [f"<L{i:03d}>" for i in range(128)]
    tokens += ANNOTATED_EVENT_TOKENS
    tokens += ANNOTATED_SUBTYPE_TOKENS
    return tokens


def lm_midi_vocabulary(mode: str = "full") -> list[str]:
    """Return the LM-MIDI vocabulary for the requested mode.

    Modes:
    - ``performance``: legacy performance-only vocabulary (524 tokens)
    - ``full``: performance + annotated-score vocabulary (797 tokens)
    """
    if mode == "performance":
        return lm_midi_performance_vocabulary()
    if mode == "full":
        return lm_midi_full_vocabulary()
    raise ValueError(f"unsupported LM-MIDI vocabulary mode: {mode}")


def add_lm_midi_tokens(tokenizer, mode: str = "full") -> int:
    """Add LM-MIDI symbols as indivisible ordinary added tokens."""
    tokens = lm_midi_vocabulary(mode=mode)
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


def load_lm_midi_tokenizer(tokenizer_path: str, trust_remote_code: bool = True, mode: str = "full"):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=trust_remote_code)
    add_lm_midi_tokens(tokenizer, mode=mode)
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
