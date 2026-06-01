# EPR Conditioning Tag Pipeline — README

## Overview

This project builds an **Expressive Performance Rendering (EPR)** conditioning layer for symbolic piano works. The pipeline extracts two compact tag fields from each piece's `piece_interpretation.json`:

- **α (piece_interpretation)**: Imagery, mood, narrative — *what emotional world this piece inhabits*
- **β (performance_concept)**: Texture, touch, articulation, dynamics — *how the performance should sound*

The tags are model-facing conditioning signals, styled like Stable Diffusion prompts rather than musicological summaries.

## Data Structure

```
data/miditsv/{composer}/{composition}/{movement}/piece_interpretation.json
```

Each file contains ~20 fields including:
- `mood`, `expressive_character`, `structural_narrative`, `stylistic_identity`
- `interpretive_priority`, `compressed_interpretation_short/full`
- `evidence_sources` (web-researched sources)
- **`piece_interpretation`** (α) — comma-separated tag phrases
- **`performance_concept`** (β) — comma-separated tag phrases

## Pipeline Steps

### Stage A: Evidence Collection (completed)

Web search evidence was collected via concurrent agents using `WebSearch` and `WebFetch` tools, stored as `data/piece_interpretations/composer_search_*.jsonl` (72 composer batches).

### Stage B: Tag Extraction (completed)

1,600 pieces processed in batches of 40-160 files per agent run. Each agent:
1. Reads the existing rich JSON content
2. Extracts α from expressive_character, narrative, stylistic_identity, mood
3. Extracts β from interpretive_priority, performance_gist, structural cues
4. Ensures zero word overlap between α and β
5. Ensures β contains no emotion words (expressive, dramatic, intense, lyrical)

## Script

The single retained script: `scripts/extract_epr_conditioning.py`

```bash
# Extract α+β for a range
python scripts/extract_epr_conditioning.py --start 0 --end 100

# Process all files
python scripts/extract_epr_conditioning.py
```

## Quality Rules

| Rule | Description |
|---|---|
| No overlap | Same word must never appear in both α and β |
| No emotion in β | β must not contain words like "expressive", "dramatic", "intense", "lyrical" |
| Tag format | 5-10 comma-separated phrases, each 1-3 words (prefer 2-word phrases) |
| Creative | Tags should be piece-specific, not generic descriptors |

## Coverage

- **1,600/1,600** files complete with both α and β fields
- Source: `data/piece_interpretations/all_file_paths.json`
- Index: `data/piece_interpretations/` (72 composer search JSONL files + metadata)

## SFT Format

For training, tags are formatted as:

```
<TASK>EPR</TASK>

<INTERPRETATION>
{piece_interpretation}
</INTERPRETATION>

<PERFORMANCE_CONCEPT>
{performance_concept}
</PERFORMANCE_CONCEPT>

<SCORE>
...
</SCORE>

->

<PERFORMANCE>
...
</PERFORMANCE>
```
