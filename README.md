# EPR: Symbolic Piano Performance Rendering

EPR is a purely symbolic pipeline for learning how a written piano score is rendered as an expressive MIDI performance.

The project uses symbolic inputs and symbolic targets only. The working representation is:

- normalized aligned ABCX score
- annotated score MIDI-TSV
- aligned expressive performance MIDI-TSV
- piece-level musical interpretation text

The main learning problem is:

```text
score / score MIDI / musical context -> expressive performance MIDI
```

Here "expressive" means timing, velocity, duration, pedal, staff assignment, phrase structure, and score annotations represented in symbolic event streams.

This root README is the current workflow index. When older notes disagree with this file, treat this README as the current decision and the older document as historical context.

## Motivation And Bottlenecks

PianoCoRe provides a large paired symbolic dataset, so the current project does not treat data volume as the main bottleneck. The harder problem is controllable knowledge, rule, and style injection for symbolic performance rendering.

Existing EPR-style methods usually generate performance MIDI from score MIDI alone. This drops much of the information that performers actually read from the written score: articulation, dynamics, tempo markings, expression text, phrase marks, and other notation-level cues. Pedaling is a special case: explicit pedal markings appear in less than one percent of the available score material, while most pedaling choices are controlled by the performer. Modeling pedal therefore cannot be reduced to copying pedal marks from the score; it requires learning performer-controlled expressive behavior from symbolic context.

Another bottleneck is interpretive control. Prior methods either have no direct way to inject style and theme, or use vector-style conditioning that is difficult for the model to understand semantically. This project uses natural-language musical interpretation as a controllable input, so the same piece can be rendered under different style, character, and thematic descriptions.

The key innovation is therefore not just score-to-performance conversion. It is symbolic EPR with explicit score-notation knowledge and natural-language interpretive context, making generated performances more controllable.

## Repository References

The current summary is grounded in existing repository documentation:

| Reference | Use In This README | Status |
| --- | --- | --- |
| `data/README.md` | data dataset background, CoRe-S / A* split history, score metadata context. | Historical dataset overview; some paths still mention old `aligned/`. |
| `data/ASTAR_PROCESSING_SUMMARY.md` | A* performance processing counts and `process_astar_performances.py` role. | Useful processing report. Current code should regenerate into `miditsv/`. |
| `data/CorporaV2/README.md` | CorporaV2 language CPT file inventory and measure-boundary chunking rules. | CorporaV2 reference snapshot; root README records current preferred flow. |
| `backup/legacy_Corpora/README.md` | Old corpus statistics and task definitions. | Legacy reference only; moved out of the active data tree. |
| `docs/SCORE_PERFORMANCE_ALIGNMENT_PIPELINE.md` | Metadata-driven score-performance alignment principle. | Conceptually important, but output path examples are old. |
| `docs/lm_midi_tokenizer.md` | LM-MIDI fixed-width event/token semantics. | Active format reference. |
| `ANNOTATED_SCORE_GENERATION_REPORT.md` | Annotated score MIDI-TSV generation coverage and score metadata notes. | Active score-side report. |
| `docs/SPIRE SFT 设计.md` | EPR/SFT task framing and symbolic notation. | Design reference; current implementation is CorporaV2-focused. |
| `docs/CPT_LANGUAGE_TRAINING.md` | Older CPT training observations and FlashAttention notes. | Historical training notes; model/data paths may be outdated. |

## Data Foundation

The current data foundation has three sources.

| Source | Role | Main Files |
| --- | --- | --- |
| PianoCoRe | Paired score-performance data. This is the only source for aligned performance targets. | `PianoCoRe/`, `data/performance_S_metadata.csv`, `data/performance_Astar_metadata.csv` |
| Unpaired Score | Additional score-only symbolic data used for score-side language modeling. | `data/unpaired_abcx/`, `data/score_metadata.csv` |
| Piece-Level Musical Interpretations | Textual musical context at piece level. | `data/piece_interpretations/`, `data/knowledge/` when materialized |

`data/miditsv/` is the normalized working tree. It contains per-piece `score.abcx`, `score_aligned.abcx`, `score.mid.tsv`, `score.annotated_score.mid.tsv`, `score_structure.json`, and performance `*.mid.tsv` files.

## Current Pipeline

### 1. Source Acquisition

Current inputs are limited to:

- `PianoCoRe/`: raw/refined score MIDI, performance MIDI, alignment files, and source score material.
- `data/unpaired_abcx/`: score-only ABCX files.
- piece interpretation assets collected under `data/piece_interpretations/` or generated into `data/knowledge/`.

`data/README.md` describes the earlier CoRe-S selection and split background. The current source boundary is narrower: use PianoCoRe paired data, unpaired symbolic scores, and piece-level interpretation text only.

Relevant scripts:

- `scripts/download_pianocore_refined.py`: download PianoCoRe refined assets.
- `scripts/build_score_abcx.py`: build canonical `PianoCoRe/score/**/score.abcx` from PianoCoRe score sources.
- `scripts/convert_imslp_to_abcx.py`, `scripts/reconvert_imslp_with_metadata.py`: score-only ABCX conversion helpers for the unpaired-score bucket.
- `scripts/generate_unpaired_metadata.py`: metadata for unpaired score assets.
- `scripts/build_piece_interpretations.py`, `scripts/collect_piece_interpretations.py`, `scripts/search_piece_interpretations.py`: piece-level interpretation resources.

### 2. Symbolic Normalization And Alignment

This step builds the canonical symbolic assets:

- normalized aligned ABCX score
- score MIDI-TSV with staff labels
- annotated score MIDI-TSV
- aligned performance MIDI-TSV with staff labels
- metadata tables for `performance_S`, `performance_Astar`, and score-only data

Current entry points:

```bash
# Paired PianoCoRe S metadata -> data/miditsv
python scripts/build_pianocores_miditsv.py \
  --metadata data/performance_S_metadata.csv \
  --output-dir data/miditsv \
  --pianocore-root PianoCoRe \
  --jobs 16 \
  --overwrite-tsv

# A* performance metadata -> data/miditsv and updated TSV paths
python scripts/process_astar_performances.py \
  --metadata data/performance_Astar_metadata.csv \
  --output-dir data/miditsv \
  --output-metadata data/performance_Astar_metadata_updated.csv \
  --jobs 16 \
  --overwrite-tsv

# Score-only / paired score metadata -> annotated score MIDI-TSV
python scripts/build_annotated_score_tsv.py \
  --metadata data/score_metadata.csv \
  --pianocore-root PianoCoRe \
  --jobs 16 \
  --overwrite
```

Core implementation files:

- `scripts/align_score_performance.py`: current metadata-driven alignment engine.
- `scripts/aligned_abcx_format.py`: normalized aligned ABCX formatting.
- `scripts/lm_midi_tsv.py`: strict LM-MIDI TSV representation and validation.
- `scripts/lm_midi_tokens.py`: compact LM-MIDI token serialization.
- `scripts/build_annotated_score_tsv.py`: score annotation extraction and score MIDI annotation merge.

The metadata-driven rule comes from `docs/SCORE_PERFORMANCE_ALIGNMENT_PIPELINE.md`: do not discover score/performance pairs by directory scan when metadata provides the score MIDI, performance MIDI, and alignment paths. The old document still shows `PianoCoRe/aligned` examples; current output is `data/miditsv`.

Important current function path in `align_score_performance.py`:

```text
main()
  -> process_metadata_task()
     -> build_score_structure_from_paths()
     -> write_aligned_abcx()
     -> build_performance_measure_note_staffs()
     -> generate_performance_tsv_with_phrases(..., measure_note_staffs=...)
```

`process_metadata_task()` is the current path. It prefers refined PianoCoRe files, projects score staff labels onto performance notes through alignment files, and writes current `data/miditsv` outputs.

### 3. CorporaV2

The active corpus tree is:

```text
data/CorporaV2/
  language_cpt/
    performance_S_midi.jsonl
    performance_Astar_midi.jsonl
    annotated_score_midi.jsonl
    score_midi.jsonl
    language_cpt_measure_summary.json
    language_cpt_v2_summary.json
  language_cpt_rounds/
    round1_train.jsonl
    round2_train.jsonl
    round3_train.jsonl
    round4_train.jsonl
    round5_train.jsonl
    round_build_summary.json
  epr_sft/
    sm2pm_coldstart_train.jsonl
    sm2pm_coldstart_val.jsonl
    sm2pm_coldstart_test.jsonl
    sm2pm_main_train.jsonl
    sm2pm_main_val.jsonl
    sm2pm_main_test.jsonl
    epr_sft_v2_summary.json
```

`data/CorporaV2/README.md` records the generated language CPT inventory and measure-boundary chunking behavior. It is useful as a data snapshot. The root README defines the current regeneration path and keeps old `backup/legacy_Corpora/` products out of the active workflow.

Current corpus builders:

```bash
# Build measure-bounded language CPT sources from current metadata.
python scripts/build_language_cpt_measure_jsons.py \
  --tokenizer Qwen3.5-0.8B-LM-MIDI-Resized \
  --max-tokens 1536 \
  --workers 16

# Build shuffled staged CPT rounds.
python scripts/build_language_cpt_rounds.py \
  --input-dir data/CorporaV2/language_cpt \
  --output-dir data/CorporaV2/language_cpt_rounds

# Build active EPR SFT data from score MIDI and performance MIDI.
python scripts/build_span_epr_corpora.py \
  --metadata data/performance_S_metadata.csv \
  --corpora-root data/CorporaV2 \
  --tokenizer Qwen3.5-0.8B-LM-MIDI-Resized \
  --jobs 16
```

`performance_mask_reconstruction` may remain as an auxiliary diagnostic/reconstruction task. Other old `backup/legacy_Corpora/` flows should not be treated as active.

## Model And Training

Supported model families in the current repo:

- `Qwen3.5-0.8B`
- `Qwen3.5-2B`
- `Qwen3.5-4B`

`docs/lm_midi_tokenizer.md` is the active tokenizer/format reference. `docs/CPT_LANGUAGE_TRAINING.md` is useful for historical training decisions, especially the FlashAttention benchmark note, but its dataset paths are older than the CorporaV2 flow described here.

Each model should have:

- base model directory, for example `Qwen3.5-0.8B/`
- expanded tokenizer directory, for example `Qwen3.5-0.8B-LM-MIDI/`
- resized model directory, for example `Qwen3.5-0.8B-LM-MIDI-Resized/`

Prepare model/tokenizer variants:

```bash
scripts/prepare_qwen35_lm_midi_variants.sh \
  Qwen3.5-0.8B Qwen3.5-2B Qwen3.5-4B
```

Relevant tokenizer/model scripts:

- `scripts/extend_lm_midi_tokenizer.py`: add LM-MIDI vocabulary.
- `scripts/resize_qwen35_lm_midi_embeddings.py`: resize embeddings for expanded tokenizer.
- `scripts/prepare_qwen35_lm_midi_model.py`: single-model preparation helper.
- `scripts/prepare_qwen35_lm_midi_variants.sh`: batch preparation for Qwen3.5 variants.

Current training entry points:

```bash
# Full-parameter CPT
python scripts/train_cpt_hf_full.py \
  --model Qwen3.5-0.8B-LM-MIDI-Resized \
  --dataset data/CorporaV2/language_cpt_rounds/round1_train.jsonl \
  --output-dir output/cpt_qwen35_08b_full_rounds/round1 \
  --max-length 1536 \
  --bf16

# PEFT/LoRA CPT with trainable LM-MIDI tokens
python scripts/train_cpt_hf_peft.py \
  --model Qwen3.5-0.8B-LM-MIDI-Resized \
  --base-tokenizer Qwen3.5-0.8B \
  --expanded-tokenizer Qwen3.5-0.8B-LM-MIDI \
  --dataset data/CorporaV2/language_cpt_rounds/round1_train.jsonl \
  --output-dir output/cpt_qwen35_08b_lora_round1 \
  --max-length 1536 \
  --bf16
```

Current launch helpers:

- `scripts/launch_cpt_rounds_full_08b.sh`: staged full-parameter CPT for 0.8B.
- `scripts/launch_cpt_hf_peft_bg.py`: PEFT background launch helper.
- `scripts/log_gpu_metrics.sh`: GPU logging helper.

SFT is based on `data/CorporaV2/epr_sft`, not the old `language_sft`, `abcx2pm_sft`, or `sm2pm_sft` trees.

## Current Vs Legacy Paths

### Current Paths

These are the paths to use for the active workflow.

| Purpose | Current Path |
| --- | --- |
| Source score ABCX | `PianoCoRe/score/**/score.abcx` |
| Normalized working assets | `data/miditsv/**` |
| S performance metadata | `data/performance_S_metadata.csv` |
| A* performance metadata | `data/performance_Astar_metadata.csv` |
| Score metadata | `data/score_metadata.csv` |
| CorporaV2 language CPT | `data/CorporaV2/language_cpt/` |
| CorporaV2 staged CPT rounds | `data/CorporaV2/language_cpt_rounds/` |
| CorporaV2 EPR SFT | `data/CorporaV2/epr_sft/` |
| Qwen3.5 LM-MIDI models | `Qwen3.5-*-LM-MIDI-Resized/` |

### Legacy Or Compatibility Paths

These paths exist for compatibility or historical experiments. They are not the current source of truth.

| Path | Status |
| --- | --- |
| `PianoCoRe/aligned/` | Old output default from early alignment scripts. Use `data/miditsv/` instead. |
| `data/aligned/` | Old normalized output tree. Use `data/miditsv/` instead. |
| `PianoCoRe_output/` | Old path prefix handled by compatibility code only. |
| `backup/legacy_Corpora/` | Old corpus tree. Keep only for migration/reference. |
| `backup/data_legacy/` | Previous root `data/` tree, including old score conversion inputs and dataset experiments. |
| `backup/CorporaV2_legacy_language_cpt/` | Large single-file language-CPT artifact moved out of the active CorporaV2 tree. |
| `backup/log/` | Old training logs. |
| `backup/legacy_CoReS/` | Older CoRe-S training experiments. Not active for the current flow; should stay in backup if restored. |
| `sft_data/` | Older SFT staging area. Not active for CorporaV2. |
| `output/language-sft*` | Old language SFT experiments. |
| `output/abcx2pm-*`, `output/sm2pm-*` | Old task-specific SFT experiments. |

### Legacy Scripts Not On The Current Main Path

These scripts may still be useful for migration, analysis, or one-off experiments, but should not define the active pipeline.

| Script | Status |
| --- | --- |
| `generate_sft_data.py` | Older measure/phrase EPR generator. Superseded by CorporaV2 span EPR flow. |
| `prepare_sft_data.py`, `prepare_sampled_sft_data.py`, `sample_sft_data.py` | Old SFT preparation. |
| `generate_language_learning_data.py` | Old language-learning corpus path. |
| `backup/scripts_legacy/build_language_sft_s1_s2_parallel.py`, `backup/scripts_legacy/build_language_sft_val.py`, `backup/scripts_legacy/merge_and_shuffle_language_sft.py`, `backup/scripts_legacy/shuffle_and_split_language_sft.py` | Old language SFT flow. |
| `backup/scripts_legacy/build_cores_*`, `backup/scripts_legacy/create_core_s_*`, `scripts/prepare_core_s1_swift.py` | CoRe-S and conversion helpers. `prepare_core_s1_swift.py` remains in `scripts/` only because current `build_span_epr_corpora.py` imports its conversion helper. |
| `backup/scripts_legacy/shuffle_split_epr_s1_sft.py`, `backup/scripts_legacy/build_epr_s1_subsets.py`, `backup/scripts_legacy/build_epr_sample_datasets.py` | Old S1 sampling/shuffle path. |
| `backup/scripts_legacy/eval_abcx2pm_test.py`, `backup/scripts_legacy/vllm_abcx2pm_smoke.py`, `export_for_vllm.sh` | Old abcx2pm inference/export experiments. |
| `backup/scripts_legacy/process_orphan_abcx.py`, `backup/scripts_legacy/annotated_tsv_to_aligned_abcx.py` | Recovery/conversion utilities, not the normal data path. |
| `backup/scripts_legacy/asap_abcx_pipeline.py`, `backup/scripts_legacy/align_from_asap_annotations.py`, `backup/scripts_legacy/generate_asap_annotations.py`, `backup/scripts_legacy/copy_asap_originals.py` | Dataset-specific historical helpers, not current source acquisition. |
| `backup/scripts_legacy/build_astar_language_cpt.py`, `backup/scripts_legacy/build_astar_language_cpt_fast.py` | Earlier A* language CPT builders. Prefer `build_language_cpt_measure_jsons.py`. |
| `backup/scripts_legacy/build_corpora_v2.py` | V2 filtering wrapper over older `backup/legacy_Corpora` sources. Use the direct CorporaV2 builders above for current regeneration. |

## Notes On Score/Performance TSV Semantics

The TSV format has four columns:

```text
event    value    duration    offset
```

For note events, `offset` is relative to the previous note onset in the same serialized stream. It is not reset by `M` rows. This keeps timing semantics uniform across measure boundaries.

Staff labels are encoded by note suffix:

- `C3` means upper/default staff.
- `C3L` means lower staff.

Score TSV staff labels come from aligned ABCX. Performance TSV staff labels are projected from score notes through the score-performance alignment file.

## Repository Map

```text
PianoCoRe/                         # source paired data
data/
  miditsv/                         # current normalized symbolic working tree
  unpaired_abcx/                   # unpaired score-only ABCX
  performance_S_metadata.csv       # current paired S metadata
  performance_Astar_metadata.csv   # current paired A* metadata
  score_metadata.csv               # current score-only / annotated score metadata
  CorporaV2/                       # current training corpora
Qwen3.5-*/                         # base Qwen3.5 model dirs
Qwen3.5-*-LM-MIDI/                 # expanded tokenizers
Qwen3.5-*-LM-MIDI-Resized/         # resized LM-MIDI models
scripts/                           # pipeline, corpus, tokenizer, training scripts
backup/scripts_legacy/             # archived script entry points from old flows
output/                            # training runs and experiments
```

## Guiding Rule

If a task can be expressed with current metadata and `data/miditsv`, use the current metadata-driven path. Do not rebuild new work from `PianoCoRe/aligned`, `data/aligned`, `backup/legacy_Corpora`, `language_sft`, `abcx2pm_sft`, or `sm2pm_sft` unless the goal is explicitly migration or historical comparison.
