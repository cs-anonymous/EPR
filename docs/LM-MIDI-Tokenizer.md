# LM-MIDI Tokenizer Design Specification

## 1. Overview

This document defines a vocabulary-expanded MIDI tokenizer for LLM-based symbolic music modeling, especially for expressive performance rendering (EPR). The tokenizer is designed for models such as Qwen or LLaMA: the original natural-language vocabulary is preserved, and a compact set of MIDI-specific tokens is appended.

The core design is a fixed-width event representation:

```text
1 event = 4 MIDI tokens
```

The unified event layout is:

```text
<EVENT><VELOCITY_OR_VALUE><DURATION><NOTE_OFFSET>
```

For note events, `<EVENT>` is an absolute MIDI pitch token. For example:

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

where `<T048>` means `48 × 10 ms = 480 ms`.

The tokenizer is intended for both continued pretraining (CPT) and supervised fine-tuning (SFT). The same tokenizer and vocabulary must be used across both stages.

---

## 2. Design Motivation

Plain-text MIDI serialization, such as MIDI-TSV or compact strings like:

```text
0:60:480:64 0:64:480:62
```

is readable and easy to debug, but inefficient under general-purpose LLM tokenizers. Even fixed-width hexadecimal strings may be split into many sub-tokens. This leads to high token consumption, short effective musical context, and inefficient training.

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
<NOTE><VELOCITY><DURATION><NOTE_OFFSET>
```

This is much more efficient than plain-text serialization and avoids relying on the original text tokenizer to split numbers, colons, or hex strings.

### 3.2 Fixed-Width Events

Every event occupies exactly 4 tokens. This makes parsing, validation, truncation, batching, constrained decoding, and error detection easier.

### 3.3 Small Vocabulary Expansion

The first version requires roughly 530–560 new tokens, far smaller than approaches that add tens of thousands of MIDI tokens.

### 3.4 Absolute Performance Pitch

Performance-side MIDI uses absolute note tokens, e.g. `<N060>`, rather than ABC pitch spelling. ABC pitch spelling is affected by key signatures and enharmonic notation, while performance MIDI needs the actual sounding pitch.

### 3.5 Note-Centered Timing

Note events form the main performance timeline. Note offset is measured relative to the previous note event, not relative to the previous global event, not relative to pedal events, and not relative to measure or phrase markers.

Pedal events are treated as control events attached to the note timeline.

---

## 4. Vocabulary Definition

### 4.1 Note / Event Tokens

Note tokens represent absolute MIDI pitch values:

```text
<N000> ... <N127>
```

Although piano performance normally uses MIDI pitches 21–108, the full MIDI range is retained for simplicity and extensibility.

Examples:

```text
<N060>  # C3 in Logic Pro note naming
<N064>  # E3 in Logic Pro note naming
<N067>  # G3 in Logic Pro note naming
```

The first slot of an event can also contain non-note event tokens, such as `<P>`, `<M>`, or `<H>`.

### 4.2 Velocity / Value Tokens

Velocity tokens represent 7-bit MIDI velocity or control values:

```text
<V000> ... <V127>
```

For note events, `<Vxxx>` is note velocity. For pedal events, `<Vxxx>` is pedal/control value.

Examples:

```text
<V000>  # zero value
<V064>  # medium value
<V127>  # maximum value
```

### 4.3 Numeric / Timing Tokens

Timing tokens encode 8-bit numeric values:

```text
<T000> ... <T255>
```

For note events, `<Txxx>` is a 10 ms time bin:

```text
<T000> = 0 ms
<T001> = 10 ms
<T048> = 480 ms
<T255> = 2550 ms
```

For measure and phrase events, the same `<Txxx>` tokens can encode local indices or high/low duration bytes. Thus, `<Txxx>` should be understood as a shared 8-bit numeric token whose meaning depends on event type and slot position.

### 4.4 Structural and Control Tokens

Recommended structural and control tokens:

```text
<MIDI>
</MIDI>
<EOS_MIDI>
<SLOT_PAD>
<TO_EXT>
<EXT_DUR>
<EXT_OFF>
<M>
<H>
<P>
<P1>
<P2>
```

Meanings:

|Token|Meaning|
|---|---|
|`<MIDI>`|Start of an LM-MIDI sequence|
|`</MIDI>`|End of an LM-MIDI sequence|
|`<EOS_MIDI>`|Optional explicit end marker|
|`<SLOT_PAD>`|Empty slot in a fixed-width event|
|`<TO_EXT>`|The value in this slot is provided by a preceding extension event|
|`<EXT_DUR>`|Extension event for duration|
|`<EXT_OFF>`|Extension event for note offset|
|`<M>`|Measure boundary event|
|`<H>`|Phrase boundary event|
|`<P>`|Sustain pedal event|
|`<P1>`|Soft pedal event|
|`<P2>`|Sostenuto pedal event|

`<SLOT_PAD>` is an LM-MIDI event-slot token. It must not be confused with the
model or tokenizer `pad_token` used for batch padding and loss masking.

If backward compatibility with older names is needed, `<EXT_IOI>` can be kept as an alias of `<EXT_OFF>`, but the preferred semantic name is `<EXT_OFF>`.

---

## 5. Event Format

All event types use the same 4-token layout:

```text
<EVENT><VELOCITY_OR_VALUE><DURATION><NOTE_OFFSET>
```

The interpretation of each slot depends on the event type.

---

## 5.1 MIDI-TSV Intermediate Format

LM-MIDI TSV is the human-readable intermediate representation of the token
format. It is event-driven and uses exactly 4 tab-separated columns per event:

```text
event<TAB>value<TAB>duration<TAB>offset
```

Header/comment lines beginning with `#` are allowed. Event rows must have
exactly four columns. Any unused/PAD slot is written explicitly as `0` in TSV
and converted to `<SLOT_PAD>` in the token stream.

Recommended header:

```text
# midi-tsv v0.3
# unit=bin
# bin_ms=10
# columns=event	value	duration	offset
# pitch=logic-pro-note
# middle_c=C3
# slot_pad=0
# note_offset=previous_note_onset
# pedal_offset=most_recent_note_onset
```

Column semantics:

|Event type|Column 1 `event`|Column 2 `value`|Column 3 `duration`|Column 4 `offset`|
|---|---|---:|---:|---:|
|Note|Logic Pro note name, sharp spelling only, e.g. `F#2`, `A#3`|velocity `0..127`|note duration in 10 ms bins|onset offset from previous note onset|
|Pedal|`P`, `P1`, or `P2`|control value `0..127`|`0` PAD|offset from most recent note onset|
|Phrase|`H`|zero-based phrase index|phrase duration in 10 ms bins|`0` PAD|
|Measure|`M`|zero-based measure index within current phrase|measure duration in 10 ms bins|`0` PAD|

Logic Pro note naming uses MIDI note 60 as `C3`. Accidentals are spelled only
with sharps so that every MIDI pitch has one canonical text name:

```text
60 -> C3
65 -> F3
66 -> F#3
70 -> A#3
```

Example:

```text
# midi-tsv v0.3
# columns=event	value	duration	offset
# pitch=logic-pro-note
# middle_c=C3
H	0	1967	0
M	0	513	0
F3	50	151	0
P	64	0	10
A#3	56	146	140
G#3	58	159	136
F#3	48	181	151
```

The TSV above converts to:

```text
<MIDI><H><T000><T007><T175><M><T000><T002><T001><N065><V050><T151><T000><P><V064><SLOT_PAD><T010><N070><V056><T146><T140><N068><V058><T159><T136><N066><V048><T181><T151></MIDI>
```

---

## 6. Note Events

A note event has the format:

```text
<Nxxx><Vvel><Tdur><Toffset>
```

|Slot|Token type|Meaning|
|---|---|---|
|1|`<Nxxx>`|Absolute MIDI pitch|
|2|`<Vxxx>`|Velocity|
|3|`<Txxx>` or `<TO_EXT>`|Duration in 10 ms bins|
|4|`<Txxx>` or `<TO_EXT>`|Note offset in 10 ms bins|

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

### 6.1 Note Offset Definition

`note_offset` is defined as the onset difference between the current note and the previous note event.

```text
note_offset(current_note) = onset(current_note) - onset(previous_note)
```

Pedal events, measure events, and phrase events do not update the note-offset reference.

For simultaneous notes in a chord, subsequent notes use:

```text
<T000>
```

Example C-major chord:

```text
<N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000>
```

If these notes are simultaneous, their offsets after the first note are 0. A deterministic ordering rule should be used for simultaneous notes, such as sorting by ascending pitch.

---

## 7. Pedal Events

Pedal events follow the same 4-slot layout:

```text
<P|P1|P2><Vval><SLOT_PAD><Toffset>
```

|Slot|Token type|Meaning|
|---|---|---|
|1|`<P>`, `<P1>`, or `<P2>`|Pedal type|
|2|`<Vxxx>`|Pedal/control value|
|3|`<SLOT_PAD>`|Unused duration slot|
|4|`<Txxx>` or `<TO_EXT>`|Offset relative to the most recent note onset|

Example:

```text
<P><V064><SLOT_PAD><T012>
```

means:

```text
sustain pedal value = 64
pedal offset = 120 ms after the most recent note onset
```

Pedal events do not update the note-offset reference. This prevents pedal events from disrupting the score-aligned note timeline.

The pedal anchor is the latest note onset that is less than or equal to the
pedal onset:

```text
pedal_anchor = max(note_onset <= pedal_onset)
pedal_offset = pedal_onset - pedal_anchor
```

If multiple pedal events share the same anchor note, sort them by pedal onset,
then by pedal type. Pedal ordering never changes note ordering.

### 7.1 Pedal Before the First Note

If a pedal event originally occurs before the first note in a segment, force its offset to:

```text
<T000>
```

This makes the pedal event simultaneous with the first note anchor. For the first version, this is acceptable because it preserves the intended initial pedal state while avoiding special pre-note timing cases.

Example:

```text
<P><V127><SLOT_PAD><T000><N060><V072><T048><T000>
```

The decoder treats this as an initial control state at the segment start or
first-note onset. It does not create or update a note anchor.

---

## 8. Measure and Phrase Events

Structural events are also fixed-width 4-token events. They do not update the note-offset reference.

### 8.1 Phrase Event

Phrase events have the format:

```text
<H><Tphrase_id><Tdur_hi><Tdur_lo>
```

|Slot|Token type|Meaning|
|---|---|---|
|1|`<H>`|Phrase boundary|
|2|`<Txxx>`|Phrase index|
|3|`<Txxx>`|High byte of phrase duration|
|4|`<Txxx>`|Low byte of phrase duration|

Phrase duration is decoded as:

```text
duration_bin = dur_hi × 256 + dur_lo
duration_ms  = duration_bin × 10
```

Example:

```text
<H><T003><T004><T128>
```

means:

```text
phrase_id = 3
duration_bin = 4 × 256 + 128 = 1152
duration_ms = 11520 ms
```

### 8.2 Measure Event

Measure events have the format:

```text
<M><Tmeasure_local_id><Tdur_hi><Tdur_lo>
```

|Slot|Token type|Meaning|
|---|---|---|
|1|`<M>`|Measure boundary|
|2|`<Txxx>`|Measure index within the current phrase|
|3|`<Txxx>`|High byte of measure duration|
|4|`<Txxx>`|Low byte of measure duration|

The measure index is phrase-local. If phrase segmentation enforces short phrases, this index usually remains below 10 and easily fits into `<T000>...<T255>`.

Example:

```text
<M><T002><T001><T128>
```

means:

```text
measure_local_id = 2
duration_bin = 1 × 256 + 128 = 384
duration_ms = 3840 ms
```

---

## 9. Extension Events

Note duration and note offset are normally encoded using one `<T000>...<T255>` token. With 10 ms bins, this covers 0–2550 ms. If a duration or offset exceeds this range, an extension event is inserted immediately before the affected note or pedal event.

### 9.1 Extended Duration

Format:

```text
<EXT_DUR><T_hi><T_lo><SLOT_PAD>
```

The following note event uses `<TO_EXT>` in the duration slot.

Example:

```text
<EXT_DUR><T002><T104><SLOT_PAD><N060><V072><TO_EXT><T012>
```

Decoding:

```text
duration_bin = 2 × 256 + 104 = 616
duration_ms = 6160 ms
pitch = 60
velocity = 72
note_offset = 120 ms
```

### 9.2 Extended Note Offset

Format:

```text
<EXT_OFF><T_hi><T_lo><SLOT_PAD>
```

The following note or pedal event uses `<TO_EXT>` in the note-offset slot.

Example:

```text
<EXT_OFF><T001><T104><SLOT_PAD><N060><V072><T048><TO_EXT>
```

Decoding:

```text
note_offset_bin = 1 × 256 + 104 = 360
note_offset_ms = 3600 ms
pitch = 60
velocity = 72
duration = 480 ms
```

### 9.3 Extension Scope

An extension event modifies the immediately following compatible event. If both duration and note offset are extended, two extension events may precede the note:

```text
<EXT_DUR><T002><T104><SLOT_PAD><EXT_OFF><T001><T104><SLOT_PAD><N060><V072><TO_EXT><TO_EXT>
```

---

## 10. Sequence Format

A MIDI segment is wrapped by `<MIDI>` and `</MIDI>`.

Readable form:

```text
<MIDI>
<H><T000><T004><T128>
<M><T000><T001><T128>
<N060><V072><T048><T000>
<N064><V068><T048><T000>
<N067><V066><T048><T000>
</MIDI>
```

Actual training data should omit spaces and newlines unless they are deliberately part of the prompt format:

```text
<MIDI><H><T000><T004><T128><M><T000><T001><T128><N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000></MIDI>
```

Since all MIDI symbols are added as indivisible vocabulary tokens, the tokenizer should recognize adjacent tokens without needing separators.

---

## 11. Recommended Event Ordering

Events should be serialized in note-onset groups. For each quantized note onset:

```text
1. Phrase event, if a phrase starts at this onset
2. Measure event, if a measure starts at this onset
3. All note events at this onset, sorted by ascending pitch
4. Pedal/control events whose anchor is this onset, sorted by control onset and then by type
```

Then continue to the next note onset group.

Pedal events do not affect note offset. They are emitted before the next note
onset group so that the decoder's "most recent note onset" remains the intended
pedal anchor.

---

## 12. CPT Data Format

For continued pretraining, MIDI data can be used as plain language-modeling text.

Example JSONL:

```json
{"text": "<MIDI><H><T000><T004><T128><M><T000><T001><T128><N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000></MIDI>"}
```

CPT data may include:

1. standalone performance LM-MIDI sequences;
    
2. score-derived mechanical MIDI sequences;
    
3. mixed symbolic-music text and MIDI examples;
    
4. format explanations and conversion rules.
    

The same tokenizer must be used for CPT and SFT.

---

## 13. SFT Data Format

For EPR, the recommended supervised format is:

```text
Score ABCX → Performance LM-MIDI tokens
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
      "content": "<MIDI><H><T000><T008><T000><M><T000><T001><T128><N060><V072><T048><T000><N064><V068><T048><T000><N067><V066><T048><T000><N072><V078><T048><T024><M><T001><T001><T128><N062><V070><T048><T030><N065><V067><T048><T000><N069><V064><T048><T000><N074><V075><T048><T026></MIDI>"
    }
  ]
}
```

The assistant output should use only valid LM-MIDI tokens inside `<MIDI>...</MIDI>`.

---

## 14. Score Input vs Performance Output

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

## 15. Tokenizer Implementation

All LM-MIDI symbols should be added as indivisible tokens. They do not need to
be HuggingFace "special tokens"; adding them as ordinary `AddedToken` entries
avoids accidental removal when calling `decode(skip_special_tokens=True)`.

If a training framework requires using `additional_special_tokens`, decoding
and validation must use `skip_special_tokens=False` or operate directly on token
IDs.

```python
from transformers import AddedToken

midi_tokens = []

# note/pitch tokens
midi_tokens += [f"<N{i:03d}>" for i in range(128)]

# velocity / control-value tokens
midi_tokens += [f"<V{i:03d}>" for i in range(128)]

# shared numeric / timing tokens
midi_tokens += [f"<T{i:03d}>" for i in range(256)]

# structural and event tokens
midi_tokens += [
    "<MIDI>", "</MIDI>", "<EOS_MIDI>",
    "<SLOT_PAD>", "<TO_EXT>",
    "<EXT_DUR>", "<EXT_OFF>",
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

Do not set `<SLOT_PAD>` as `tokenizer.pad_token`. Batch padding should keep
using the model's normal pad token or a separately configured padding token.

Verification:

```python
ids = tokenizer.encode("<N060><V072><T048><T000>", add_special_tokens=False)
assert len(ids) == 4
```

---

## 16. Training Considerations

### 16.1 New Embeddings Must Be Trained

After adding new tokens, the model's embedding matrix and output head must be resized. The newly initialized MIDI token embeddings must be trainable.

If LoRA is used, ensure that token embeddings and the language modeling head are saved and updated. In many frameworks this requires setting modules such as:

```text
embed_tokens
lm_head
```

as trainable or as `modules_to_save`.

### 16.2 CPT Before SFT

Because the new MIDI tokens have no pretrained meaning, a CPT stage is recommended before task-specific SFT. CPT teaches the model the syntax and distribution of LM-MIDI sequences, while SFT teaches mappings such as score-to-performance rendering.

### 16.3 Consistent Tokenizer Across CPT and SFT

The same tokenizer and added vocabulary must be used for CPT and SFT. Changing the vocabulary after CPT would invalidate learned embeddings.

---

## 17. Decoding Rules

A decoder should process tokens inside `<MIDI>...</MIDI>` as 4-token events, ignoring wrappers.

### 17.1 Note Event Decoding

If the first token is `<Nxxx>`, decode:

```text
<Nxxx><Vvel><Tdur><Toffset>
```

or extension-based variants:

```text
<Nxxx><Vvel><TO_EXT><Toffset>
<Nxxx><Vvel><Tdur><TO_EXT>
```

### 17.2 Pedal Event Decoding

If the first token is `<P>`, `<P1>`, or `<P2>`, decode:

```text
<P|P1|P2><Vval><SLOT_PAD><Toffset>
```

### 17.3 Structural Event Decoding

If the first token is `<H>`, decode:

```text
<H><Tphrase_id><Tdur_hi><Tdur_lo>
```

If the first token is `<M>`, decode:

```text
<M><Tmeasure_local_id><Tdur_hi><Tdur_lo>
```

### 17.4 Error Handling

Invalid generated sequences can be repaired or rejected using simple rules:

1. If the number of tokens inside `<MIDI>...</MIDI>` is not divisible by 4, truncate to the nearest valid boundary.
    
2. If a note uses `<TO_EXT>` but no matching preceding extension exists, replace it with `<T255>` or reject the event.
    
3. If an extension event is not followed by a compatible event, discard the extension.
    
4. If an event has an invalid slot type, discard it or constrain decoding.
    

---

## 18. Quantization

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

All MIDI input must be canonicalized to integer timing bins before producing
LM-MIDI TSV or LM-MIDI tokens. The tokenizer does not mix ticks, milliseconds,
and bins inside the same sequence.

Recommended canonicalization:

```text
bin = round(time_ms / 10)
```

After quantization, sort events deterministically and recompute offsets from
the quantized note onsets. This keeps tokenization deterministic even when the
source MIDI contains small timing jitter.

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

## 19. Approximate Vocabulary Size

|Token group|Count|
|---|--:|
|Note `<N000>...<N127>`|128|
|Velocity `<V000>...<V127>`|128|
|Numeric/timing `<T000>...<T255>`|256|
|Structural/control/wrapper tokens|10–30|
|Total|about 530–550|

This is much smaller than vocabulary-expansion approaches that add tens of thousands of MIDI tokens, while still achieving compact 4-token note events.

---

## 20. Comparison with Other Representations

|Representation|Vocabulary strategy|Typical note cost|Notes|
|---|---|--:|---|
|Plain MIDI-TSV|Original LLM tokenizer|Very high|Human-readable but inefficient|
|Compact text / hex|Original LLM tokenizer|Still high|Tokenizer may split characters inefficiently|
|Traditional MIDI tokenizer|Custom music vocabulary|Low|Cannot use token IDs directly in a pretrained LLM; must be mapped to added LLM tokens|
|MIDI-LLM-style expansion|Append many MIDI tokens|About 3 tokens/note|High compression but large MIDI vocabulary and may omit performance attributes|
|Proposed LM-MIDI|Append compact event tokens|4 tokens/note|Small vocabulary, explicit velocity, duration, and note offset|

---

## 21. Summary

This tokenizer represents performance MIDI as fixed-width 4-token events using compact vocabulary expansion over a pretrained LLM tokenizer.

The core layout is:

```text
<EVENT><VELOCITY_OR_VALUE><DURATION><NOTE_OFFSET>
```

Main event types:

```text
Note:    <Nxxx><Vxxx><Tdur><Toffset>
Pedal:   <P|P1|P2><Vval><SLOT_PAD><Toffset>
Phrase:  <H><Tphrase_id><Tdur_hi><Tdur_lo>
Measure: <M><Tmeasure_local_id><Tdur_hi><Tdur_lo>
```

The representation is designed to be compact, deterministic, easy to decode, compatible with LLM vocabulary expansion, and suitable for score-to-performance EPR.

A typical EPR training pair is:

```text
Input:  score ABCX
Output: <MIDI>...LM-MIDI performance tokens...</MIDI>
```

This preserves rich score-side symbolic structure while representing performance-side pitch, velocity, duration, pedal, and note-relative timing in a compact LLM-friendly token language.
