# LM-MIDI Tokenizer Format Specification

LM-MIDI is a vocabulary-expanded MIDI tokenizer designed for LLM-based symbolic music modeling, especially for Expressive Performance Rendering (EPR). It extends pretrained LLM vocabularies (Qwen, LLaMA) with compact MIDI-specific tokens.

## Core Design

### Fixed-Width Event Representation

```text
1 event = 4 MIDI tokens
```

Every event uses the same layout:

```text
<EVENT><SLOT2><SLOT3><SLOT4>
```

### Slot-Type Regularity

Each slot position has a fixed token-family meaning:

- **Slot 1**: Event family
  - `<Nxxx>`, `<P>`, `<P1>`, `<P2>`, `<M>`, `<H>`, `<EXD>`, `<EXO>`
- **Slot 2**: Value family or explicit empty
  - `<Vxxx>` or `<NIL>`
- **Slot 3**: Timing family
  - `<Txxx>` or `<EXT>`
- **Slot 4**: Timing family
  - `<Txxx>` or `<EXT>`

This gives the LLM a much more regular positional pattern than a looser event language.

## Design Motivation

Plain-text MIDI serialization (e.g., MIDI-TSV or compact strings like `0:60:480:64`) is readable but inefficient under general-purpose LLM tokenizers. Even fixed-width strings may be split into many sub-tokens, leading to:

- High token consumption
- Short effective musical context
- Inefficient training

LM-MIDI solves this by adding a compact set of music-specific tokens to the LLM vocabulary:

```text
Original LLM vocabulary + compact MIDI/event tokens
```

This keeps the pretrained LLM backbone while giving the model direct access to music-specific units.

## Design Goals

### 1. Token Efficiency

Each note event is exactly 4 tokens:

```text
<NOTE><VALUE><TIME><TIME>
```

Much more efficient than plain-text serialization.

### 2. Fixed-Width Events

Every event occupies exactly 4 tokens, making parsing, validation, truncation, batching, constrained decoding, and error detection easier.

### 3. Slot-Type Regularity

Token-family meaning is fixed by slot position, providing a stronger inductive bias than merely using 4 tokens per event.

### 4. Small Vocabulary Expansion

Requires only a relatively small number of added tokens compared with tokenizers that add tens of thousands of music-specific entries.

### 5. Absolute Performance Pitch

Performance-side MIDI uses absolute note tokens (e.g., `<N060>`) rather than ABC pitch spelling. ABC pitch is affected by key signatures and enharmonic notation, while performance MIDI needs the actual sounding pitch.

### 6. Note-Centered Timing

Note events form the main performance timeline. Note offset is measured relative to the previous note event, not relative to pedal events or structural markers.

## Vocabulary Definition

### Note / Event Tokens

```text
<N000> ... <N127>      # MIDI pitches 0-127
<P> <P1> <P2>          # Pedal types
<M> <H> # Structural markers
<EXD> <EXO>            # Extension events
<MIDI> </MIDI> <EOS_MIDI>  # Delimiters
```

**Note tokens** represent absolute MIDI pitch values. Although piano performance normally uses MIDI pitches 21–108, the full MIDI range is retained for simplicity and extensibility.

**Examples**:
```text
<N060>  # C3 in Logic Pro note naming (middle C)
<N064>  # E3
<N067>  # G3
```

### Value Tokens

```text
<V000> ... <V127>
```

Used for:
- Note velocity (0..127)
- Pedal/control value
- Phrase page-local index
- Measure-local index

Using `<Vxxx>` for phrase and measure index keeps slot 2 semantically stable.

### Timing Tokens

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

Each timing token represents a 10ms bin.

### Empty / Extension Tokens

```text
<NIL>  # Explicitly empty slot
<EXT>  # Value provided by preceding extension event
```

**Important**: `<NIL>` is an LM-MIDI event-slot token, not the model's `pad_token` used for batch padding.

## Event Format

All event types use the same 4-token layout:

```text
<EVENT><SLOT2><SLOT3><SLOT4>
```

The interpretation depends on event type, but token-family by slot is fixed.

## LM-MIDI TSV Intermediate Format

LM-MIDI TSV is the human-readable intermediate representation. It uses exactly 4 tab-separated columns per event:

```text
event<TAB>value<TAB>duration<TAB>offset
```

### Header Format

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

### Column Semantics

| Event type | Column 1 `event` | Column 2 `value` | Column 3 `duration` | Column 4 `offset` |
|---|---|---:|---:|---:|
| Note | Logic Pro note name (e.g., `F#2`, `A#3`) | velocity `0..127` | note duration in bins or `EXT` | onset offset in bins or `EXT` |
| Pedal | `P`, `P1`, or `P2` | control value `0..127` | `0` (`NIL`) | offset from most recent note onset or `EXT` |
| Phrase | `H` | phrase index modulo 128 | phrase duration high byte | phrase duration low byte |
| Measure | `M` | measure index modulo 128 (global absolute) | measure duration high byte | measure duration low byte |
| Extension duration | `EXD` | `0` (`NIL`) | duration high byte | duration low byte |
| Extension offset | `EXO` | `0` (`NIL`) | offset high byte | offset low byte |

### TSV Example

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

This converts to tokens:

```text
<MIDI><H><V000><T002><T041><M><V000><T000><T127><N065><V050><T151><T000><P><V064><NIL><T010><EXD><NIL><T002><T104><N070><V056><EXT><T140></MIDI>
```

## Note Events

### Format

```text
<Nxxx><Vvel><Tdur|EXT><Toffset|EXT>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<Nxxx>` | Absolute MIDI pitch |
| 2 | `<Vxxx>` | Velocity |
| 3 | `<Txxx>` or `<EXT>` | Duration in 10ms bins |
| 4 | `<Txxx>` or `<EXT>` | Note offset in 10ms bins |

### Example

```text
<N060><V072><T048><T000>
```

Means:
```text
pitch       = 60 (C3)
velocity    = 72
duration    = 480 ms
note_offset = 0 ms
```

### Note Offset Definition

`note_offset` is the onset difference between the current note and the previous note event:

```text
note_offset(current_note) = onset(current_note) - onset(previous_note)
```

**Key points**:
- Pedal events, measure events, and phrase events do NOT update the note-offset reference
- For simultaneous notes in a chord, subsequent notes use `<T000>`
- Simultaneous notes should be sorted by ascending pitch for deterministic ordering

### Extension Events for Large Values

When duration or offset exceeds 255 bins (2550ms), use extension events:

**Duration extension**:
```text
<EXD><NIL><Tdur_hi><Tdur_lo>
<Nxxx><Vvel><EXT><Toffset>
```

**Offset extension**:
```text
<EXO><NIL><Toffset_hi><Toffset_lo>
<Nxxx><Vvel><Tdur><EXT>
```

**Both extensions**:
```text
<EXD><NIL><Tdur_hi><Tdur_lo>
<EXO><NIL><Toffset_hi><Toffset_lo>
<Nxxx><Vvel><EXT><EXT>
```

Decoding:
```text
actual_value = hi_byte × 256 + lo_byte
actual_ms = actual_value × 10
```

## Pedal Events

### Format

```text
<P|P1|P2><Vval><NIL><Toffset|EXT>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<P>`, `<P1>`, or `<P2>` | Pedal type |
| 2 | `<Vxxx>` | Pedal/control value |
| 3 | `<NIL>` | Unused slot |
| 4 | `<Txxx>` or `<EXT>` | Offset relative to most recent note onset |

### Example

```text
<P><V064><NIL><T012>
```

Means:
```text
sustain pedal value = 64
pedal offset = 120 ms after the most recent note onset
```

### Pedal Offset Definition

The pedal anchor is the latest note onset that is less than or equal to the pedal onset:

```text
pedal_anchor = max(note_onset <= pedal_onset)
pedal_offset = pedal_onset - pedal_anchor
```

If multiple pedal events share the same anchor note, sort them by pedal onset, then by pedal type.

### Pedal Before First Note

If a pedal event occurs before the first note in a segment, force its offset to `<T000>`, making it simultaneous with the first note anchor.

## Measure and Phrase Events

Structural events are also fixed-width 4-token events. They do NOT update the note-offset reference.

### Phrase Event Format

```text
<H><Vphrase_id_mod_128><Tdur_hi><Tdur_lo>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<H>` | Phrase boundary |
| 2 | `<Vxxx>` | Phrase index modulo 128 |
| 3 | `<Txxx>` | High byte of phrase duration |
| 4 | `<Txxx>` | Low byte of phrase duration |

Phrase slot 2 is a modulo id, not a globally unique id for very long pieces:
```text
<H><V000> ... <H><V127>
```

**Duration decoding**:
```text
duration_bin = dur_hi × 256 + dur_lo
duration_ms  = duration_bin × 10
```

### Measure Event Format

```text
<M><Vmeasure_id_mod_128><Tdur_hi><Tdur_lo>
```

| Slot | Token type | Meaning |
|---|---|---|
| 1 | `<M>` | Measure marker |
| 2 | `<Vxxx>` | **Global** measure index modulo 128 |
| 3 | `<Txxx>` | High byte of measure duration |
| 4 | `<Txxx>` | Low byte of measure duration |

**Important**: Measure ID is a **global absolute index modulo 128**, not relative to the current phrase. This matches the design of phrase events and avoids overflow in long phrases.

Example:
```text
<M><V000>  # Measure 0, 128, 256, ...
<M><V001>  # Measure 1, 129, 257, ...
<M><V127>  # Measure 127, 255, 383, ...
```

For pieces with more than 128 measures, the ID wraps around. The model can still distinguish measures by their position in the sequence and their duration values.

## Complete Example

### LM-MIDI TSV

```tsv
# midi-tsv v0.3
# unit=bin
# bin_ms=10

H	0	1	200
M	0	0	100
C3	60	48	0
E3	65	48	48
G3	70	96	0
P	80	0	10
P	0	0	96
M	1	0	100
D3	62	48	0
F3	68	48	48
```

### Token Sequence

```text
<MIDI>
<H><V000><T001><T200>
<M><V000><T000><T100>
<N060><V060><T048><T000>
<N064><V065><T048><T048>
<N067><V070><T096><T000>
<P><V080><NIL><T010>
<P><V000><NIL><T096>
<M><V001><T000><T100>
<N062><V062><T048><T000>
<N065><V068><T048><T048>
</MIDI>
```

## Pitch Naming Convention

LM-MIDI uses **Logic Pro note naming**:

```text
C-2 = MIDI 0
C-1 = MIDI 12
C0  = MIDI 24
C1  = MIDI 36
C2  = MIDI 48
C3  = MIDI 60  (middle C)
C4  = MIDI 72
C5  = MIDI 84
C6  = MIDI 96
C7  = MIDI 108
C8  = MIDI 120
G8  = MIDI 127
```

Piano range: A0 (MIDI 21) to C8 (MIDI 108)

## Advantages for LLM Training

1. ✅ **Fixed-width**: Every event is exactly 4 tokens
2. ✅ **Slot regularity**: Token family fixed by position
3. ✅ **Efficient**: Much fewer tokens than text serialization
4. ✅ **Parseable**: Easy validation and constrained decoding
5. ✅ **Extensible**: Extension events handle large values
6. ✅ **Vocabulary-friendly**: Small vocabulary expansion (performance-only: 524 tokens; full annotated-score: 796 tokens)

## Conversion Tools

- **Performance MIDI → MIDI-TSV v0.3**: `wave-roll/midi_tsv.py`
- **MIDI-TSV v0.3 → LM-MIDI tokens**: tokenize the fixed four-column rows
- **LM-MIDI tokens → MIDI-TSV v0.3**: decode fixed four-slot events
- **MIDI-TSV v0.3 → MIDI**: parse the current four-column intermediate

## Related Formats

- **MIDI-TSV v0.3**: Human-readable fixed four-column performance intermediate
- **ABCX**: Score notation format for symbolic music representation
- **EPR Task**: Score (ABCX) → Performance (LM-MIDI tokens)

---

# Annotated Score MIDI (TSV) Design

This section describes the extended LM-MIDI format for **score MIDI** with musical annotations (dynamics, articulation, expression, etc.). This format is designed for training models on score-to-performance tasks where the input includes rich musical notation beyond just notes and timing.

## Design Principles

1. **Staff-aware notation**: Piano scores have upper and lower staves with independent annotations
2. **Explicit token vocabulary**: Use meaningful tokens (e.g., `<dolce>`, `<accent>`) instead of numeric codes
3. **Fixed 4-token width**: Maintain compatibility with performance MIDI format
4. **Frequency-based inclusion**: Only encode annotations that appear ≥10 times in the corpus
5. **Lossless where practical**: Preserve high-frequency musical information that MIDI alone cannot express

## Vocabulary Extensions

### Staff-Aware Note Tokens

```python
# Upper staff (default)
<N000> ... <N127>

# Lower staff (with L suffix in TSV)
<L000> ... <L127>
```

**TSV notation**:
```tsv
C3	85	10	0      # Upper staff: C3 (MIDI 60)
C2L	75	10	5      # Lower staff: C2 (MIDI 48)
```

Note: TSV format uses plain text without angle brackets. Tokens like `<N060>` and `<L048>` are only used in the tokenized sequence.

The `L` suffix in the TSV note name indicates lower staff. During tokenization:
- `C3` → `<N060>`
- `C2L` → `<L048>`

### Event Type Tokens (Slot 1)

```python
# Per-note annotations
<A>, <AL>       # Articulation (upper/lower)
<OR>, <ORL>     # Ornament (upper/lower)

# Per-staff annotations
<D>, <DL>       # Dynamic (upper/lower)
<RS>, <RSL>     # Range Start (upper/lower)
<RE>, <REL>     # Range End (upper/lower)
<EX>, <EXL>     # Expression text (upper/lower)

# Global annotations
<FM>            # Fermata
<PM>            # Pedal Mark
<TP>            # Tempo
<MT>            # Meter
<KS>            # Key Signature
```

### Articulation Subtypes (Slot 2 for A/AL)

Based on 7257 score files in PianoCoReS corpus:

```python
<accent>        # !>! (119356 occurrences)
<staccato>      # !wedge! (59704)
<tenuto>        # !tenuto! (38281)
<sfz>           # !sfz! (531)
```

### Ornament Subtypes (Slot 2 for OR/ORL)

```python
<arpeggio>      # !arpeggio! (27790)
<turn>          # !turn! (2212)
<trill>         # !trill(! / !trill)! (1520 / 1065)
```

Note: Trill is handled as a range marker (see Range Subtypes), not a per-note ornament.

### Dynamic Subtypes (Slot 2 for D/DL)

```python
<pppp>          # pianississimo (55)
<ppp>           # pianissimo (1680)
<pp>            # pianissimo (20285)
<p>             # piano (59502)
<mp>            # mezzo-piano (10024)
<mf>            # mezzo-forte (16308)
<f>             # forte (41608)
<ff>            # fortissimo (14266)
<fff>           # fortississimo (1455)
<ffff>          # (36)
```

### Range Subtypes (Slot 2 for RS/RE/RSL/REL)

Range markers indicate musical spans with explicit start and end points:

```python
<cre>           # Crescendo (symbol form: !<(! ... !<)!)
<dim>           # Diminuendo (symbol form: !>(! ... !>)!)
<trill>         # Trill (!trill(! ... !trill)!)
<slur>          # Slur/legato line
```

Frequencies from 7257 score files:
- Crescendo: 42832 starts (!<(!), 42348 ends (!<)!)
- Diminuendo: 37700 starts (!>(!), 37251 ends (!>)!)
- Trill: 1520 starts (!trill(!), 1065 ends (!trill)!)

### Expression Text Subtypes (Slot 2 for EX/EXL)

Expression terms with ≥10 occurrences (44 total, from 7257 score files):

```python
<a_tempo>       # 587
<cresc>         # 541
<dim>           # 272
<rit>           # 196
<dolce>         # 97
<loco>          # 94
<tempo_i>       # 91
<poco_rit>      # 69
<rall>          # 68
<ten>           # 48
<espress>       # 43
<ritard>        # 40
<legato>        # 39
<accel>         # 36
<subito>        # 32
<sempre>        # 30
<una_corda>     # 30
<sec>           # 27
<marcato>       # 26
<molto_rall>    # 25
<cédez>         # 23
<calando>       # 21
<stretto>       # 21
<in_tempo>      # 20
<leggiero>      # 20
<sotto_voce>    # 20
<riten>         # 19
<cantabile>     # 16
<mouvt>         # 16
<crescendo>     # 14
<espressivo>    # 14
<piu>           # 14
<sostenuto>     # 14
<tranquillo>    # 13
<allargando>    # 12
<colla_parte>   # 12
<dimin>         # 12
<agitato>       # 11
<poco_ritard>   # 11
<colla_voce>    # 10
<pesante>       # 10
<rubato>        # 10
```

### Pedal Mark Subtypes (Slot 2 for PM)

```python
<down>          # Pedal down ("^Ped." - 3790)
<up>            # Pedal up ("^*" - 757)
```

Note: These are score pedal markings (notated pedal), distinct from performance pedal events (`<P>`, `<P1>`, `<P2>`).

### Tempo (TP)

Tempo is **quantized** to fit in `<V000>`-`<V127>`:

```python
quantized_value = round(bpm / 3)
actual_bpm = quantized_value * 3
```

**Examples**:
- 120 BPM → `<V040>` (40 × 3 = 120)
- 144 BPM → `<V048>` (48 × 3 = 144)
- 300 BPM → `<V100>` (100 × 3 = 300)

Tempos exceeding 381 BPM are clamped to 127 (381 BPM).

**TSV format**:
```tsv
TP	V040	NIL	NIL      # tempo = 120 BPM
TP	V048	NIL	NIL      # tempo = 144 BPM
```

Note: TSV uses plain text (`V040`, `NIL`) without angle brackets. Angle brackets (`<V040>`, `<NIL>`) are only added during tokenization.

### Meter (MT)

Only high-frequency meters (≥10 occurrences) are encoded. Others are discarded.

```python
# 41 meter tokens (≥10 occurrences, from 7257 score files)
<meter_4/4>     # 13091
<meter_3/4>     # 9642
<meter_2/4>     # 9266
<meter_6/8>     # 4914
<meter_2/2>     # 2120
<meter_3/8>     # 1833
<meter_9/8>     # 1361
<meter_6/4>     # 1150
<meter_3/2>     # 1015
<meter_12/8>    # 988
<meter_5/4>     # 825
<meter_5/8>     # 494
<meter_4/8>     # 458
<meter_1/4>     # 443
<meter_12/16>   # 226
<meter_7/4>     # 195
<meter_7/8>     # 167
<meter_6/16>    # 135
<meter_4/2>     # 133
<meter_2/8>     # 127
<meter_1/8>     # 124
<meter_9/16>    # 101
<meter_9/4>     # 87
<meter_1/2>     # 64
<meter_3/16>    # 58
<meter_11/8>    # 48
<meter_8/8>     # 31
<meter_1/16>    # 24
<meter_12/32>   # 24
<meter_2/16>    # 19
<meter_4/16>    # 17
<meter_5/16>    # 17
<meter_8/32>    # 16
<meter_10/4>    # 15
<meter_17/16>   # 15
<meter_3/1>     # 13
<meter_10/8>    # 12
<meter_11/16>   # 12
<meter_2/1>     # 11
<meter_8/4>     # 10
<meter_9/2>     # 10
```

**TSV format**:
```tsv
MT	meter_4/4	NIL	NIL
MT	meter_3/4	NIL	NIL
MT	meter_6/8	NIL	NIL
```

### Key Signature (KS)

All 24 major and minor keys (from 7257 score files):

```python
# Major keys (12)
<key_C>         # C major (6499)
<key_G>         # G major (6192)
<key_D>         # D major (6407)
<key_A>         # A major (3700)
<key_E>         # E major (4002)
<key_B>         # B major (2684)
<key_F#>        # F# major (1796)
<key_Db>        # Db major (3469)
<key_Ab>        # Ab major (4291)
<key_Eb>        # Eb major (6131)
<key_Bb>        # Bb major (6135)
<key_F>         # F major (5867)

# Minor keys (12)
<key_Am>        # A minor (12)
<key_Em>        # E minor (17)
<key_Bm>        # B minor (9)
<key_F#m>       # F# minor (4)
<key_C#m>       # C# minor (13)
<key_G#m>       # G# minor (3)
<key_D#m>       # D# minor (enharmonic Ebm) (0)
<key_Bbm>       # Bb minor (6)
<key_Fm>        # F minor (16)
<key_Cm>        # C minor (34)
<key_Gm>        # G minor (11)
<key_Dm>        # D minor (20)
```

Note: The corpus is heavily skewed toward major keys. Minor keys have very low frequencies but are included for completeness.

**TSV format**:
```tsv
KS	key_E	NIL	NIL      # E major
KS	key_C#m	NIL	NIL    # C# minor
```

## Annotation Scope

### Per-Note Annotations

Applied to the immediately following note:

```tsv
A	accent	NIL	NIL     # accent on next note
C3	85	10	0
OR	arpeggio	NIL	NIL   # arpeggio on next chord
C3	85	50	0
E3	85	50	0
G3	85	50	0
```

### Per-Staff Annotations

Applied to all following notes on the same staff until changed:

```tsv
D	p	NIL	NIL          # upper staff: piano
DL	f	NIL	NIL         # lower staff: forte
C3	85	10	0         # upper: p
C2L	100	10	0       # lower: f
E3	85	10	5         # upper: still p
G2L	100	10	5       # lower: still f
D	ff	NIL	NIL         # upper changes to ff
A3	95	10	5         # upper: now ff
```

### Range Annotations

Indicate spans with explicit start and end:

```tsv
RS	cre	NIL	NIL       # crescendo start
C3	85	10	0
D3	87	10	5
E3	90	10	5
F3	93	10	5
G3	95	10	5
RE	cre	NIL	NIL       # crescendo end

RS	trill	NIL	NIL     # trill start
E4	100	50	0
RE	trill	NIL	NIL     # trill end
```

### Global Annotations

Apply to the entire piece from the point of occurrence:

```tsv
KS	key_E	NIL	NIL      # E major
TP	V033	NIL	NIL       # tempo = 99 BPM
MT	meter_2/4	NIL	NIL   # 2/4 time
FM	NIL	NIL	NIL        # fermata on next note
C3	85	50	0
PM	down	NIL	NIL      # pedal down
PM	up	NIL	NIL        # pedal up
```

## Complete TSV Example

```tsv
# midi-tsv v0.4
# source=score_refined.mid
# columns=event	value	duration	offset
# pitch=logic-pro-note
# staff=suffix-L-for-lower
# unit=bin
# bin_ms=10
# nil=NIL
# note_offset=previous_note_onset
# pedal_offset=most_recent_note_onset
# structural_duration=u16_hi_lo
# tempo=quantized (value*3 = actual BPM)
T:Almería
C:Isaac Albéniz
Z:CC Carlos Márquez

KS	key_D	NIL	NIL      # D major
TP	V027	NIL	NIL       # tempo = 80 BPM (27*3=81, rounded)
MT	meter_2/4	NIL	NIL   # 2/4 time
H	0	10	200       # Phrase 0
M	0	0	100       # Measure 0 (global)
D	p	NIL	NIL          # piano
EX	dolce	NIL	NIL      # dolce
EX	legato	NIL	NIL     # legato
B2	85	10	0        # Upper staff
E3	85	10	0
D3	85	5	5
E3	85	5	5
G2L	80	40	0       # Lower staff
B2L	80	40	0
M	1	0	100       # Measure 1 (global)
RS	cre	NIL	NIL       # crescendo start
F3	90	20	5
F3	90	5	10
G3	92	5	5
G3	94	5	5
F3	96	5	5
RE	cre	NIL	NIL       # crescendo end
A2L	85	50	0
C3L	85	50	0
M	2	0	100       # Measure 2 (global)
EX	rit	NIL	NIL       # rit.
TP	V030	NIL	NIL       # tempo = 90 BPM (30*3)
G3	95	10	0
A3	93	5	5
F3	90	5	5
G3	88	5	5
M	3	0	100       # Measure 3 (global)
EX	a_tempo	NIL	NIL   # a tempo
TP	V027	NIL	NIL       # back to 80 BPM
D	ff	NIL	NIL        # fortissimo
RS	trill	NIL	NIL     # trill start
E4	100	50	0
RE	trill	NIL	NIL     # trill end
G4	100	10	5
A	accent	NIL	NIL    # accent
F4	98	10	5
E4	96	10	5
E2L	95	100	0
B2L	95	100	0
M	4	0	100       # Measure 4 (global)
MT	meter_3/4	NIL	NIL   # change to 3/4
RS	dim	NIL	NIL       # diminuendo start
D4	95	10	0
C4	90	10	5
B3	85	10	5
A3	80	10	5
RE	dim	NIL	NIL       # diminuendo end
D	p	NIL	NIL          # back to piano
PM	down	NIL	NIL      # pedal down
E2L	85	100	0
B2L	85	100	0
PM	up	NIL	NIL        # pedal up
```

## Token Sequence Example

The above TSV converts to:

```text
<MIDI>
<H><V000><T010><T200>
<M><V000><T000><T100>
<KS><key_E><NIL><NIL>
<TP><V033><NIL><NIL>
<MT><meter_2/4><NIL><NIL>
<D><p><NIL><NIL>
<EX><dolce><NIL><NIL>
<EX><legato><NIL><NIL>
<N071><V085><T010><T000>
<N076><V085><T010><T000>
<N074><V085><T005><T005>
<N076><V085><T005><T005>
<L055><V080><T040><T000>
<L071><V080><T040><T000>
<M><V001><T000><T100>
<RS><cre><NIL><NIL>
<N077><V090><T020><T005>
<N077><V090><T005><T010>
<N079><V092><T005><T005>
<N079><V094><T005><T005>
<N077><V096><T005><T005>
<RE><cre><NIL><NIL>
<L057><V085><T050><T000>
<L060><V085><T050><T000>
...
</MIDI>
```

## Vocabulary Size Summary

The repository now uses the exact tokenizer counts derived from the code path that
generates LM-MIDI and annotated score TSVs.

```text
Performance-only LM-MIDI vocabulary:
- 524 added tokens
  - Note: 128 (<N000>-<N127>)
  - Value: 128 (<V000>-<V127>)
  - Timing: 256 (<T000>-<T255>)
  - Structural / control: 12

Full LM-MIDI vocabulary (performance + annotated score):
- 796 added tokens
  - Performance-only core: 524
  - Lower-staff notes: 128 (<L000>-<L127>)
  - Annotated-score event types: 17
  - Annotated-score subtype tokens: 127
```

Notes:
- The earlier `~803` figure was approximate and did not match the exact token set
  implemented in the repository.
- The exact full-vocabulary count is lower because several subtype labels are
  shared across categories, e.g. `<dim>`, `<cre>`, and `<trill>`.

## Design Rationale

### Why Staff-Aware Notes?

Piano scores have two staves with independent musical information. Annotations like dynamics, articulation, and expression can differ between hands. Using `<N>` for upper and `<L>` for lower allows the model to learn staff-specific patterns.

### Why Explicit Tokens Instead of Numeric Codes?

Compare:
- Numeric: `EX <V005> 0 0` (requires lookup table)
- Explicit: `EX <dolce> 0 0` (self-documenting)

Explicit tokens improve:
- **Readability**: Humans can understand TSV files directly
- **Debuggability**: Errors are easier to spot
- **Model interpretability**: Token embeddings have semantic meaning
- **Extensibility**: Adding new terms doesn't require renumbering

### Why Frequency Threshold ≥10?

Low-frequency annotations (<10 occurrences in 7257 score files) provide minimal training signal while increasing vocabulary size. The threshold balances coverage and efficiency:
- **42 expression terms** are currently present in the repository token set
- **41 meter types** cover ~99% of meter changes
- **24 keys** provide 100% coverage

### Why Quantize Tempo?

Piano tempos range from 20-400+ BPM, exceeding the `<V000>`-`<V127>` range. Quantizing by dividing by 3:
- Covers 0-381 BPM (99% of real music)
- Maintains 3 BPM resolution (sufficient for musical purposes)
- Avoids multi-token encoding complexity

### Why Not Encode Tuplets and Octave Shifts?

- **Tuplets** (`!3!`, `!5!`): Rhythm information is already encoded in MIDI timing
- **Octave shifts** (`!8va!`, `!8vb!`): Pitch information is already in MIDI note numbers

These annotations are redundant with performance MIDI data.

## Conversion Pipeline

```
ABCX (score notation)
    ↓
Score MIDI (with meta events)
    ↓
Annotated MIDI-TSV v0.4 (this format)
    ↓
LM-MIDI tokens (for training)
```

Tools:
- **ABCX → Score MIDI**: `abc2midi` or custom parser
- **Score MIDI → Annotated TSV**: Extract notes, pedal, and annotations
- **Annotated TSV → Tokens**: Fixed 4-token encoding
- **Tokens → TSV**: Decode 4-token events
- **TSV → Performance MIDI**: Render with learned expression
