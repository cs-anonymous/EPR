# Score-Performance Alignment Pipeline

Complete pipeline for generating aligned score and performance data from raw MusicXML/MIDI files.

## Overview

This pipeline processes piano music scores and performances through multiple stages:

1. **Raw Score Processing**: Convert MusicXML/MXL to ABCX format
2. **Score Structure Alignment**: Build hierarchical measure/phrase structure
3. **Score MIDI TSV Generation**: Generate tokenized score representations
4. **Annotated Score TSV**: Add performance annotations (dynamics, articulation, etc.)
5. **Performance TSV Generation**: Align and tokenize performance MIDI

## Pipeline Stages

### Stage 1: Build Raw Score ABCX

**Input**: `PianoCoRe/raw/Composer/Piece/score.mxl`  
**Output**: `data/miditsv/Composer/Piece/score.abcx`  
**Script**: `scripts/build_score_abcx.py`

Converts MusicXML/MXL files to ABCX (ABC notation extended) format directly to the final output directory.

```bash
python scripts/build_score_abcx.py \
  --raw-dir PianoCoRe/raw \
  --output-dir data/miditsv \
  --jobs 32 \
  --force
```

**Key Features**:
- Validates ABCX syntax
- Preserves voice structure
- Handles multi-staff piano scores
- Extracts annotations (dynamics, articulation, expression)
- Outputs directly to final location (no intermediate copy needed)

---

### Stage 2: Build H/M Structure

**Input**: 
- `data/miditsv/Composer/Piece/score.abcx` (source, from Stage 1)
- `PianoCoRe/raw/Composer/Piece/score_*.mid` (score MIDI)

**Output**:
- H/M structure (in-memory, used by Stage 3)

**Script**: `scripts/rebuild_score_assets_from_metadata.py` (internal step)

This stage builds the hierarchical measure/phrase structure:

1. **Extract Measures from Score MIDI** (`ψ → M grid`):
   - Parse time signatures and measure boundaries
   - Create logical measure grid from MIDI timing

2. **Map ABCX Content to MIDI Measures** (`σ + M grid → H/M`):
   - Match ABCX measures to MIDI measures
   - Group measures into phrases (H)
   - Handle repeats and expansions

**Key Algorithms**:
- **Measure Detection**: Uses time signatures and note timing
- **Phrase Mapping**: Matches ABCX content to MIDI measures
- **Repeat Expansion**: Automatically detects and expands repeats

---

### Stage 3a: Write Aligned ABCX

**Input**:
- H/M structure (from Stage 2)
- `data/miditsv/Composer/Piece/score.abcx` (source)

**Output**:
- `data/miditsv/Composer/Piece/score_aligned.abcx` (aligned score)
- `data/miditsv/Composer/Piece/score_structure.json` (H/M hierarchy)

**Script**: `scripts/rebuild_score_assets_from_metadata.py`

Generates aligned ABCX with H/M structural markers:

- Insert phrase markers: `<H><V000>`
- Insert measure markers: `<M><V000>`
- Expand repeated sections
- Maintain voice structure

**Aligned ABCX Format**:
```
<H><V000>
<M><V000>
[G3 A3 B3]
<M><V000>
[C4 D4 E4]
```

---

### Stage 3b: Write Score MIDI TSV

**Input**:
- H/M structure (from Stage 2)
- `PianoCoRe/raw/Composer/Piece/score_*.mid` (score MIDI events)

**Output**:
- `data/miditsv/Composer/Piece/score.mid.tsv` (ψ*)

**Script**: `scripts/rebuild_score_assets_from_metadata.py`

Generates tokenized score MIDI with structural markers (ψ → ψ*):

1. **Tokenize MIDI Events**:
   - Notes: pitch, velocity, duration, voice
   - Pedal events
   - Time signatures

2. **Add Structural Markers**:
   - H rows: `H phrase_id start_tick duration_tick`
   - M rows: `M measure_id start_tick duration_tick`

```bash
python scripts/rebuild_score_assets_from_metadata.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32
```

**TSV Format**:
```
H 0 0 1940
M 0 0 480
G3 80 480 0
A3 75 240 0
```

---

### Stage 3c: Build Annotated Score MIDI TSV

**Input**:
- `data/miditsv/Composer/Piece/score.abcx` (with annotations)
- `data/miditsv/Composer/Piece/score.mid.tsv` (ψ*, base TSV)
- `data/miditsv/Composer/Piece/score_structure.json` (structure)

**Output**:
- `data/miditsv/Composer/Piece/score.annotated_score.mid.tsv` (ψ**)

**Script**: `scripts/build_annotated_score_tsv.py`

Extracts performance annotations from ABCX and merges them into the score MIDI TSV (ψ* → ψ**):

**Annotation Types**:
- **Dynamics**: `pppp`, `ppp`, `pp`, `p`, `mp`, `mf`, `f`, `ff`, `fff`, `ffff`
- **Articulation**: `accent`, `staccato`, `tenuto`, `sfz`
- **Ornaments**: `arpeggio`, `turn`, `trill`
- **Range Markers**: `cre` (crescendo), `dim` (diminuendo), `trill`
- **Pedal**: `down`, `up`
- **Expression**: `a_tempo`, `dolce`, `rit`, `rall`, etc.

```bash
python scripts/build_annotated_score_tsv.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 32 \
  --overwrite
```

**TSV Format**:
```
H 0 0 1940
M 0 0 480
dynamic p
G3 80 480 0
accent
A3 75 240 0
```

---

### Stage 4: Project H/M Structure to Performance MIDI

**Input**:
- `data/miditsv/Composer/Piece/score_structure.json` (H/M structure)
- `PianoCoRe/refined/Composer/Piece/performance_refined.mid` (performance MIDI)
- `PianoCoRe/refined/Composer/Piece/performance_refined_align.npz` (alignment)

**Output**:
- `data/miditsv/Composer/Piece/performance_refined.mid.tsv`

**Scripts**: 
- S-tier: `scripts/build_pianocores_miditsv.py`
- A*-tier: `scripts/process_astar_performances.py`

Projects the H/M structure onto performance MIDI using alignment data:

1. **Load Alignment** (`ψ ↔ φ`):
   - Read NPZ alignment mapping score → performance
   - Map score note indices to performance note indices

2. **Project Structure** (`H/M + alignment → φ*`):
   - Assign H/M IDs to performance notes
   - Interpolate structure for unaligned notes
   - Preserve performance timing and dynamics

3. **Generate Performance TSV**:
   - Same format as score TSV
   - Uses actual performance timing and velocities
   - Includes H/M structural markers

```bash
python scripts/build_pianocores_miditsv.py \
  --metadata data/performance_S_metadata.csv \
  --pianocore-root PianoCoRe \
  --output-dir data/miditsv \
  --jobs 32 \
  --tier all \
  --overwrite-tsv
```

---

### Stage 4b: Build Performance MIDI TSV (A*-tier)

**Input**: Same as Stage 4a, but for A*-tier performances  
**Output**: `data/miditsv/Composer/Piece/performance_refined.mid.tsv`  
**Script**: `scripts/process_astar_performances.py`

Same process as Stage 4a, but processes A*-tier performances (high-quality subset).

```bash
python scripts/process_astar_performances.py \
  --metadata data/performance_Astar_metadata.csv \
  --pianocore-root PianoCoRe \
  --output-dir data/miditsv \
  --jobs 32 \
  --overwrite-tsv
```

---

## Complete Pipeline Execution

Run all stages in sequence:

```bash
python scripts/regenerate_all_pipeline.py --jobs 32
```

This master script executes all stages:
1. Build score.abcx from XML/MXL
2. Copy score.abcx to output directory
3. Build score_aligned.abcx, structure.json, score.mid.tsv
4. Build annotated score MIDI TSV
5. Build S-tier performance TSV
6. Build A*-tier performance TSV

**Options**:
- `--jobs N`: Number of parallel workers (default: 32)
- `--skip-score-abcx`: Skip Stage 1 (if already done)
- `--skip-score-assets`: Skip Stages 2-3.5
- `--skip-performance-s`: Skip Stage 4a
- `--skip-performance-astar`: Skip Stage 4b

---

## Data Flow Diagram

```
Raw Score (σ₀)                    Score MIDI (ψ)
XML/MXL                           score_*.mid
    │                                  │
    │ [1] build_score_abcx            │
    ↓                                  │
Source ABCX (σ)                       │
data/miditsv/.../score.abcx          │
    │                                  │
    │ [2] build H/M structure         │
    ├──────────────────────────────────┤
    │                                  │
    ↓                                  ↓
    │                            H/M Structure
    │                                  │
    │ [3a] write aligned ABCX          │
    ↓                                  │
Aligned ABCX (σ*)                     │
score_aligned.abcx                    │
                                      │
                              [3b] write score TSV
                                      ↓
                              Score TSV (ψ*)
                              score.mid.tsv
                                      │
    σ (annotations)                   │
    │ [3c] merge annotations          │
    └──────────────────────────────────┤
                                       ↓
                            Annotated Score TSV (ψ**)
                            score.annotated_score.mid.tsv
                                       │
                                       │
    Performance MIDI (φ)               │
    performance_refined.mid            │
            │                          │
            │ [4] project H/M via NPZ  │
            ├──────────────────────────┘
            │
            ↓
    Performance TSV (φ*)
    performance_refined.mid.tsv
```

---

## Output File Structure

```
data/miditsv/
└── Composer/
    └── Piece/
        ├── score.abcx                          # Source ABCX
        ├── score_aligned.abcx                  # Aligned with H/M markers
        ├── score_structure.json                # H/M hierarchy
        ├── score.mid.tsv                       # Score MIDI tokenized
        ├── score.annotated_score.mid.tsv       # Score with annotations
        ├── performance_1.mid.tsv               # Performance 1 tokenized
        ├── performance_2.mid.tsv               # Performance 2 tokenized
        └── piece_interpretation.json           # Piece metadata
```

---

## TSV Format Specification

### Structural Markers

```
H phrase_id start_tick duration_tick
M measure_id start_tick duration_tick
```

### Note Events

```
pitch velocity duration voice_id
```

- `pitch`: MIDI pitch (e.g., `C4`, `G#3`)
- `velocity`: 0-127 (performance) or quantized (score)
- `duration`: in ticks
- `voice_id`: 0-based voice index

### Annotations (Annotated Score TSV only)

```
dynamic <level>          # pppp, ppp, pp, p, mp, mf, f, ff, fff, ffff
articulation <type>      # accent, staccato, tenuto, sfz
ornament <type>          # arpeggio, turn
range_start <type>       # cre, dim, trill
range_end <type>         # cre, dim, trill
pedal <action>           # down, up
expression <term>        # a_tempo, dolce, rit, rall, etc.
```

---

## Metadata Files

### score_metadata.csv

Tracks all score files and their outputs:

- `score_abcx_path`: Source ABCX location
- `score_aligned_path`: Aligned ABCX output
- `score_json_path`: Structure JSON output
- `score_midi_tsv_path`: Score MIDI TSV output
- `annotated_score_midi_path`: Annotated score TSV output

### performance_S_metadata.csv / performance_Astar_metadata.csv

Tracks all performance files:

- `refined_performance_midi_path`: Performance MIDI
- `refined_alignment_path`: Alignment NPZ
- `performance_tsv_path`: Performance TSV output
- `score_abcx_path`: Corresponding score

---

## Quality Metrics

### Stage 1: Score ABCX
- **Success Rate**: ~99.6% (1600/1607)
- **Common Failures**: Corrupted ZIP files

### Stage 2-3: Score Assets
- **Success Rate**: 100% (7252/7252)
- **Paired Scores**: 1344 (with MIDI)
- **Orphan Scores**: 5908 (ABCX only)

### Stage 3.5: Annotated Score TSV
- **Coverage**: All paired scores with annotations
- **Annotation Types**: 6 categories, 50+ terms

### Stage 4: Performance TSV
- **S-tier**: 1587 scores, 62969 performances
- **A*-tier**: High-quality subset
- **Alignment Quality**: Median recall >95%

---

## Troubleshooting

### Missing Source Files

If `score.abcx` is missing in `PianoCoRe/score/`:
```bash
python scripts/build_score_abcx.py --raw-dir PianoCoRe/raw --output-dir PianoCoRe/score --jobs 32 --force
```

### Metadata Path Issues

Ensure metadata points to correct paths:
- `score_abcx_path` should point to `data/miditsv/.../score.abcx`
- Source files are in `PianoCoRe/score/.../score.abcx`

### Alignment Failures

Check alignment quality in metadata:
- `refined_recall`: Should be >0.90
- `refined_alignment_path`: Must exist

---

## Performance Optimization

- **Parallel Processing**: Use `--jobs 32` for 32-core systems
- **Incremental Updates**: Skip completed stages with `--skip-*` flags
- **Memory Usage**: ~2GB per worker for large scores
- **Disk I/O**: SSD recommended for large datasets

---

## References

- **ABCX Format**: Extended ABC notation with voice markers
- **H/M Structure**: Hierarchical (phrase) / Measure structure
- **Alignment**: DTW-based score-performance alignment
- **Tokenization**: LM-MIDI format for language modeling
