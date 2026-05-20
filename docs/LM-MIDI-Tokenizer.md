# LM-MIDI Tokenizer Design Specification

## 1. Overview

This document defines a vocabulary-expanded MIDI tokenizer for LLM-based symbolic music modeling, especially for expressive performance rendering (EPR). The tokenizer is designed for models such as Qwen or LLaMA: the original natural-language vocabulary is preserved, and a compact set of MIDI-specific tokens is appended.

The core design is a fixed-width event representation:

```text
1 event = 4 MIDI tokens
```

The final unified layout is:

```text
<EVENT><SLOT2><SLOT3><SLOT4>
```

The main design constraint is that **each slot position has a fixed token-family meaning**:

- Slot 1:
  - one of `<Nxxx>`, `<P>`, `<P1>`, `<P2>`, `<M>`, `<H>`, `<EXD>`, `<EXO>`
- Slot 2:
  - either `<Vxxx>` or `<NIL>`
- Slot 3:
  - always `<Txxx>` or `<EXT>`
- Slot 4:
  - always `<Txxx>` or `<EXT>`

This gives the LLM a much more regular positional pattern than a looser event language.

The tokenizer is intended for both continued pretraining (CPT) and supervised fine-tuning (SFT). The same tokenizer and vocabulary must be used across both stages.

---

## 2. Design Motivation

Plain-text MIDI serialization, such as MIDI-TSV or compact strings like:

```text
0:60:480:64 0:64:480:62
```

is readable and easy to debug, but inefficient under general-purpose LLM tokenizers. Even fixed-width strings may be split into many sub-tokens. This leads to high token consumption, short effective musical context, and inefficient training.

Traditional MIDI tokenizers solve this by defining a specialized symbolic-music vocabulary. However, their token IDs cannot be directly used as Qwen/LLaMA token IDs, because those IDs already refer to natural-language tokens in the pretrained LLM vocabulary. To use such music tokens with an LLM, they must be added as new vocabulary tokens and their embeddings must be trained.

This tokenizer therefore adopts a compact LLM vocabulary-expansion route:

```text
Original LLM vocabulary + compact MIDI/event tokens
```

It keeps the pretrained LLM backbone while giving the model direct access to music-specific units.

---

## 3. Design Goals

### 3.1 Token Efficiency

Each note event is represented by exactly 4 tokens:

```text
<NOTE><VALUE><TIME><TIME>
```

This is much more efficient than plain-text serialization and avoids relying on the original text tokenizer to split numbers, colons, or free-form text.

### 3.2 Fixed-Width Events

Every event occupies exactly 4 tokens. This makes parsing, validation, truncation, batching, constrained decoding, and error detection easier.

### 3.3 Slot-Type Regularity

The final format fixes token-family meaning by slot:

- Slot 1 = event family
- Slot 2 = value family or explicit empty slot
- Slots 3-4 = timing family

This is a stronger inductive bias than merely using 4 tokens per event.

### 3.4 Small Vocabulary Expansion

The design still requires only a relatively small number of added tokens compared with tokenizers that add tens of thousands of music-specific entries.

### 3.5 Absolute Performance Pitch

Performance-side MIDI uses absolute note tokens, e.g. `<N060>`, rather than ABC pitch spelling. ABC pitch spelling is affected by key signatures and enharmonic notation, while performance MIDI needs the actual sounding pitch.

### 3.6 Note-Centered Timing

Note events form the main performance timeline. Note offset is measured relative to the previous note event, not relative to the previous global event, not relative to pedal events, and not relative to measure or phrase markers.

Pedal events are treated as control events attached to the note timeline.

---

## 4. Vocabulary Definition

### 4.1 Note / Event Tokens

```text
<N000> ... <N127>
<P> <P1> <P2>
<M> <H>
<EXD> <EXO>
<MIDI> </MIDI> <EOS_MIDI>
```

Note tokens represent absolute MIDI pitch values. Although piano performance normally uses MIDI pitches 21–108, the full MIDI range is retained for simplicity and extensibility.

Examples:

```text
<N060>  # C3 in Logic Pro note naming
<N064>  # E3 in Logic Pro note naming
<N067>  # G3 in Logic Pro note naming
```

### 4.2 Value Tokens

```text
<V000> ... <V127>
```

These are used for:

- note velocity
- pedal/control value
- phrase index
- measure-local index

Using `<Vxxx>` for phrase and measure index keeps slot 2 semantically stable:

```text
slot 2 = numeric/value family
```

### 4.3 Timing Tokens

```text
<T000> ... <T255>
```

For time values:

```text
<T000> = 0 ms
<T001> = 10 ms
<T048> = 480 ms
<T255> = 2550 ms
```

### 4.4 Empty / Extension Tokens

```text
<NIL>
<EXT>
```

Meanings:

| Token | Meaning |
|---|---|
| `<NIL>` | Explicitly empty slot |
| `<EXT>` | The actual value for this slot is provided by the immediately preceding extension event |

`<NIL>` is an LM-MIDI event-slot token. It must not be confused with the model or tokenizer `pad_token` used for batch padding and loss masking.

---

## 5. Event Format

All event types use the same 4-token layout:

```text
<EVENT><SLOT2><SLOT3><SLOT4>
```

The interpretation depends on event type, but token-family by slot is fixed.

---

## 6. MIDI-TSV Intermediate Format

LM-MIDI TSV is the human-readable intermediate representation of the token format. It is event-driven and uses exactly 4 tab-separated columns per event:

```text
event<TAB>value<TAB>duration<TAB>offset
```

Header/comment lines beginning with `#` are allowed. Event rows must have exactly four columns.

Recommended header:

```text
# midi-tsv v0.3
# unit=bin
# bin_ms=10
# columns=event	value	duration	offset
# pitch=logic-pro-note
# middle_c=C3
# nil=0
# note_offset=previous_note_onset
# pedal_offset=most_recent_note_onset
# structural_duration=u16_hi_lo
```

Column semantics:

| Event type | Column 1 `event` | Column 2 `value` | Column 3 `duration` | Column 4 `offset` |
|---|---|---:|---:|---:|
| Note | Logic Pro note name, sharp spelling only, e.g. `F#2`, `A#3` | velocity `0..127` | note duration in bins or `EXT` | onset offset in bins or `EXT` |
| Pedal | `P`, `P1`, or `P2` | control value `0..127` | `0` (`NIL`) | offset from most recent note onset or `EXT` |
| Phrase | `H` | zero-based phrase index | phrase duration high byte | phrase duration low byte |
| Measure | `M` | zero-based measure index within current phrase | measure duration high byte | measure duration low byte |
| Extension duration | `EXD` | `0` (`NIL`) | duration high byte | duration low byte |
| Extension offset | `EXO` | `0` (`NIL`) | offset high byte | offset low byte |

This matches the final slot discipline:

- slot 1 = event family
- slot 2 = value or explicit empty
- slots 3-4 = timing-related values

### 6.1 TSV Example

```tsv
# midi-tsv v0.3
# unit=bin
# bin_ms=10
# columns=event	value	duration	offset
# pitch=logic-pro-note
# middle_c=C3
# nil=0
# note_offset=previous_note_onset
# pedal_offset=most_recent_note_onset
# structural_duration=u16_hi_lo

H	0	2	41
M	0	0	127
F3	50	151	0
P	64	0	10
EXD	0	2	104
A#3	56	EXT	140
```

The TSV above converts to:

```text
<MIDI><H><V000><T002><T041><M><V000><T000><T127><N065><V050><T151><T000><P><V064><NIL><T010><EXD><NIL><T002><T104><N070><V056><EXT><T140></MIDI>
```

---

## 7. Note Events

A note event has the format:

```text
<Nxxx><Vvel><Tdur|EXT><Toffset|EXT>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<Nxxx>` | Absolute MIDI pitch |
| 2 | `<Vxxx>` | Velocity |
| 3 | `<Txxx>` or `<EXT>` | Duration in 10 ms bins |
| 4 | `<Txxx>` or `<EXT>` | Note offset in 10 ms bins |

Example:

```text
<N060><V072><T048><T000>
```

means:

```text
pitch       = 60
velocity    = 72
duration    = 480 ms
note_offset = 0 ms
```

### 7.1 Note Offset Definition

`note_offset` is defined as the onset difference between the current note and the previous note event.

```text
note_offset(current_note) = onset(current_note) - onset(previous_note)
```

Pedal events, measure events, and phrase events do not update the note-offset reference.

For simultaneous notes in a chord, subsequent notes use:

```text
<T000>
```

If these notes are simultaneous, their offsets after the first note are 0. A deterministic ordering rule should be used for simultaneous notes, such as sorting by ascending pitch.

---

## 8. Pedal Events

Pedal events follow the same 4-slot layout:

```text
<P|P1|P2><Vval><NIL><Toffset|EXT>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<P>`, `<P1>`, or `<P2>` | Pedal type |
| 2 | `<Vxxx>` | Pedal/control value |
| 3 | `<NIL>` | Unused slot |
| 4 | `<Txxx>` or `<EXT>` | Offset relative to the most recent note onset |

Example:

```text
<P><V064><NIL><T012>
```

means:

```text
sustain pedal value = 64
pedal offset = 120 ms after the most recent note onset
```

Pedal events do not update the note-offset reference.

The pedal anchor is the latest note onset that is less than or equal to the pedal onset:

```text
pedal_anchor = max(note_onset <= pedal_onset)
pedal_offset = pedal_onset - pedal_anchor
```

If multiple pedal events share the same anchor note, sort them by pedal onset, then by pedal type.

### 8.1 Pedal Before the First Note

If a pedal event originally occurs before the first note in a segment, force its offset to:

```text
<T000>
```

This makes the pedal event simultaneous with the first note anchor and avoids special pre-note timing cases.

---

## 9. Measure and Phrase Events

Structural events are also fixed-width 4-token events. They do not update the note-offset reference.

### 9.1 Phrase Event

Phrase events have the format:

```text
<H><Vphrase_id><Tdur_hi><Tdur_lo>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<H>` | Phrase boundary |
| 2 | `<Vxxx>` | Phrase index |
| 3 | `<Txxx>` | High byte of phrase duration |
| 4 | `<Txxx>` | Low byte of phrase duration |

Phrase duration is decoded as:

```text
duration_bin = dur_hi × 256 + dur_lo
duration_ms  = duration_bin × 10
```

### 9.2 Measure Event

Measure events have the format:

```text
<M><Vmeasure_local_id><Tdur_hi><Tdur_lo>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<M>` | Measure boundary |
| 2 | `<Vxxx>` | Measure index within the current phrase |
| 3 | `<Txxx>` | High byte of measure duration |
| 4 | `<Txxx>` | Low byte of measure duration |

The measure index is phrase-local and resets at each new phrase.

---

## 10. Extension Events

Note duration and note offset are normally encoded using one `<T000>...<T255>` token. With 10 ms bins, this covers 0–2550 ms. If a duration or offset exceeds this range, an extension event is inserted immediately before the affected note or pedal event.

### 10.1 Extended Duration

Format:

```text
<EXD><NIL><T_hi><T_lo>
```

The following note event uses `<EXT>` in the duration slot.

Example:

```text
<EXD><NIL><T002><T104><N060><V072><EXT><T012>
```

### 10.2 Extended Offset

Format:

```text
<EXO><NIL><T_hi><T_lo>
```

The following note or pedal event uses `<EXT>` in the offset slot.

Example:

```text
<EXO><NIL><T001><T104><N060><V072><T048><EXT>
```

### 10.3 Extension Scope

An extension event modifies the immediately following compatible event. If both duration and offset are extended, two extension events may precede the note:

```text
<EXD><NIL><T002><T104><EXO><NIL><T001><T104><N060><V072><EXT><EXT>
```

---

## 11. Sequence Format

A MIDI segment is wrapped by `<MIDI>` and `</MIDI>`.

Readable form:

```text
<MIDI>
<H><V000><T004><T128>
<M><V000><T001><T128>
<N060><V072><T048><T000>
<N064><V068><T048><T000>
<N067><V066><T048><T000>
</MIDI>
```

Actual training data may omit spaces and newlines unless they are deliberately part of the prompt format:

```text
<MIDI><H><V000><T004><T128><M><V000><T001><T128><N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000></MIDI>
```

Since all MIDI symbols are added as indivisible vocabulary tokens, the tokenizer should recognize adjacent tokens without needing separators.

---

## 12. Recommended Event Ordering

Events should be serialized in note-onset groups. For each quantized note onset:

```text
1. Phrase event, if a phrase starts at this onset
2. Measure event, if a measure starts at this onset
3. All note events at this onset, sorted by ascending pitch
4. Pedal/control events whose anchor is this onset, sorted by control onset and then by type
```

Then continue to the next note onset group.

Pedal events do not affect note offset. They are emitted before the next note onset group so that the decoder's "most recent note onset" remains the intended pedal anchor.

---

## 13. CPT Data Format

For continued pretraining, MIDI data can be used as plain language-modeling text.

Example JSONL:

```json
{"text": "<MIDI><H><V000><T004><T128><M><V000><T001><T128><N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000></MIDI>"}
```

CPT data may include:

1. standalone performance LM-MIDI sequences
2. score-derived mechanical MIDI sequences
3. mixed symbolic-music text and MIDI examples
4. format explanations and conversion rules

The same tokenizer must be used for CPT and SFT.

---

## 14. SFT Data Format

For EPR, the recommended supervised format is:

```text
Score ABCX -> Performance LM-MIDI tokens
```

Example messages format:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Render the following score into expressive performance MIDI.\n<ABCX>\nM:4/4\nK:C\n[V:1] C E G c | D F A d |\n</ABCX>"
    },
    {
      "role": "assistant",
      "content": "<MIDI><H><V000><T008><T000><M><V000><T001><T128><N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000></MIDI>"
    }
  ]
}
```

The assistant output should use only valid LM-MIDI tokens inside `<MIDI>...</MIDI>`.

---

## 15. Score Input vs Performance Output

This tokenizer defines the performance-side representation. Score input may remain in ABCX, because score notation contains musical structure such as measures, voices, slurs, articulations, dynamics, and notational durations.

Performance output should use absolute MIDI pitch:

```text
<N060>, <N061>, ...
```

rather than ABC pitch spelling:

```text
^C, _D, F, G,
```

because ABC pitch spelling can be affected by key signatures and enharmonic notation. For performance reconstruction, absolute pitch is more stable and unambiguous.

---

## 16. Tokenizer Implementation

All LM-MIDI symbols should be added as indivisible tokens. They do not need to be HuggingFace "special tokens"; adding them as ordinary `AddedToken` entries avoids accidental removal when calling `decode(skip_special_tokens=True)`.

If a training framework requires using `additional_special_tokens`, decoding and validation must use `skip_special_tokens=False` or operate directly on token IDs.

```python
from transformers import AddedToken

midi_tokens = []

# note/pitch tokens
midi_tokens += [f"<N{i:03d}>" for i in range(128)]

# velocity / value tokens
midi_tokens += [f"<V{i:03d}>" for i in range(128)]

# shared timing tokens
midi_tokens += [f"<T{i:03d}>" for i in range(256)]

# structural and control tokens
midi_tokens += [
    "<MIDI>", "</MIDI>", "<EOS_MIDI>",
    "<NIL>", "<EXT>",
    "<EXD>", "<EXO>",
    "<M>", "<H>",
    "<P>", "<P1>", "<P2>",
]

added_tokens = [
    AddedToken(
        token,
        single_word=False,
        lstrip=False,
        rstrip=False,
        normalized=False,
    )
    for token in midi_tokens
]

tokenizer.add_tokens(added_tokens)
model.resize_token_embeddings(len(tokenizer))
```

Do not set `<NIL>` as `tokenizer.pad_token`. Batch padding should keep using the model's normal pad token or a separately configured padding token.

Verification:

```python
ids = tokenizer.encode("<N060><V072><T048><T000>", add_special_tokens=False)
assert len(ids) == 4
```

---

## 17. Training Considerations

### 17.1 New Embeddings Must Be Trained

After adding new tokens, the model's embedding matrix and output head must be resized. The newly initialized LM-MIDI token embeddings must be trainable.

If LoRA is used, ensure that token embeddings and the language modeling head are saved and updated. In many frameworks this requires setting modules such as:

```text
embed_tokens
lm_head
```

as trainable or as `modules_to_save`.

### 17.2 CPT Before SFT

Because the new LM-MIDI tokens have no pretrained meaning, a CPT stage is recommended before task-specific SFT. CPT teaches the model the syntax and distribution of LM-MIDI sequences, while SFT teaches mappings such as score-to-performance rendering.

### 17.3 Consistent Tokenizer Across CPT and SFT

The same tokenizer and added vocabulary must be used for CPT and SFT. Changing the vocabulary after CPT would invalidate learned embeddings.

---

## 18. Decoding Rules

A decoder should process tokens inside `<MIDI>...</MIDI>` as 4-token events, ignoring wrappers.

### 18.1 Note Event Decoding

If the first token is `<Nxxx>`, decode:

```text
<Nxxx><Vvel><Tdur><Toffset>
```

or extension-based variants:

```text
<Nxxx><Vvel><EXT><Toffset>
<Nxxx><Vvel><Tdur><EXT>
```

### 18.2 Pedal Event Decoding

If the first token is `<P>`, `<P1>`, or `<P2>`, decode:

```text
<P|P1|P2><Vval><NIL><Toffset|EXT>
```

### 18.3 Structural Event Decoding

If the first token is `<H>`, decode:

```text
<H><Vphrase_id><Tdur_hi><Tdur_lo>
```

If the first token is `<M>`, decode:

```text
<M><Vmeasure_local_id><Tdur_hi><Tdur_lo>
```

### 18.4 Error Handling

Invalid generated sequences can be repaired or rejected using simple rules:

1. If the number of tokens inside `<MIDI>...</MIDI>` is not divisible by 4, truncate to the nearest valid boundary.
2. If a note or pedal uses `<EXT>` but no matching preceding extension exists, replace it with `<T255>` or reject the event.
3. If an extension event is not followed by a compatible event, discard the extension.
4. If an event has an invalid slot type, discard it or constrain decoding.

---

## 19. Quantization

Default timing resolution:

```text
1 timing bin = 10 ms
```

Thus:

```text
<T001> = 10 ms
<T010> = 100 ms
<T100> = 1000 ms
```

All MIDI input must be canonicalized to integer timing bins before producing LM-MIDI TSV or LM-MIDI tokens. The tokenizer does not mix ticks, milliseconds, and bins inside the same sequence.

Recommended canonicalization:

```text
bin = round(time_ms / 10)
```

After quantization, sort events deterministically and recompute offsets from the quantized note onsets. This keeps tokenization deterministic even when the source MIDI contains small timing jitter.

For note duration and note offset, one token covers up to 2550 ms. Longer values use extension events.

For phrase and measure durations, two timing tokens are used:

```text
duration_bin = hi × 256 + lo
```

This covers up to:

```text
65535 × 10 ms = 655.35 s
```

which is sufficient for measure and phrase durations.

---

## 20. Approximate Vocabulary Size

| Token group | Count |
|---|--:|
| Note `<N000>...<N127>` | 128 |
| Value `<V000>...<V127>` | 128 |
| Timing `<T000>...<T255>` | 256 |
| Structural/control/wrapper tokens | 10–30 |
| Total | about 530–550 |

This is much smaller than vocabulary-expansion approaches that add tens of thousands of MIDI tokens, while still achieving compact 4-token note events.

---

## 21. Summary

This tokenizer represents performance MIDI as fixed-width 4-token events using compact vocabulary expansion over a pretrained LLM tokenizer.

The final slot semantics are:

```text
Slot 1: event family
Slot 2: <V...> or <NIL>
Slot 3: <T...> or <EXT>
Slot 4: <T...> or <EXT>
```

Main event types:

```text
Note:    <Nxxx><Vxxx><Tdur|EXT><Toffset|EXT>
Pedal:   <P|P1|P2><Vval><NIL><Toffset|EXT>
Phrase:  <H><Vphrase_id><Tdur_hi><Tdur_lo>
Measure: <M><Vmeasure_local_id><Tdur_hi><Tdur_lo>
EXD:     <EXD><NIL><Tdur_hi><Tdur_lo>
EXO:     <EXO><NIL><Toff_hi><Toff_lo>
```

The representation is designed to be compact, deterministic, easy to decode, compatible with LLM vocabulary expansion, and suitable for score-to-performance EPR.

A typical EPR training pair is:

```text
Input:  score ABCX
Output: <MIDI>...LM-MIDI performance tokens...</MIDI>
```

This preserves rich score-side symbolic structure while representing performance-side pitch, velocity, duration, pedal, and note-relative timing in a compact LLM-friendly token language.
