#!/bin/bash
# Generate Language CPT Corpora V2
#
# This script generates language CPT training data with:
# - Tokenizer: Qwen3.5-0.8B-LM-MIDI-Resized
# - Workers: 32 threads
# - S-tier: split into 2 batches (round1, round2)
# - A*-tier: split into 3 batches (round3, round4, round5)
# - Token counting: via <XXX> regex pattern (bypasses tokenizer)

set -e

TOKENIZER="./Qwen3.5-0.8B-LM-MIDI-Resized"
WORKERS=32
MAX_TOKENS=2048
OUTPUT_DIR="data/CorporaV2"

echo "================================================================================"
echo "Language CPT Corpora Generation"
echo "================================================================================"
echo "Tokenizer: $TOKENIZER"
echo "Workers: $WORKERS"
echo "Max tokens: $MAX_TOKENS"
echo "Output: $OUTPUT_DIR"
echo ""

# Step 1: Generate measure-boundary JSON files
echo "================================================================================"
echo "STEP 1: Generate measure-boundary JSON files"
echo "================================================================================"
python scripts/build_language_cpt_measure_jsons.py \
  --tokenizer "$TOKENIZER" \
  --max-tokens $MAX_TOKENS \
  --workers $WORKERS \
  --datasets astar performance_s annotated_score \
  --output-dir "$OUTPUT_DIR/language_cpt"

echo ""
echo "✓ Step 1 completed"
echo ""

# Step 2: Build multi-round shuffled datasets
echo "================================================================================"
echo "STEP 2: Build multi-round shuffled datasets"
echo "================================================================================"
echo "Round plan:"
echo "  - round1: S-tier batch 1/2"
echo "  - round2: S-tier batch 2/2"
echo "  - round3: A*-tier batch 1/3"
echo "  - round4: A*-tier batch 2/3"
echo "  - round5: A*-tier batch 3/3"
echo ""

python scripts/build_language_cpt_rounds.py \
  --corpora-dir "$OUTPUT_DIR/language_cpt" \
  --output-dir "$OUTPUT_DIR/language_cpt_rounds" \
  --seed 42

echo ""
echo "✓ Step 2 completed"
echo ""

# Summary
echo "================================================================================"
echo "✓ LANGUAGE CPT CORPORA GENERATION COMPLETED"
echo "================================================================================"
echo ""
echo "Output directories:"
echo "  - $OUTPUT_DIR/language_cpt/"
echo "    • performance_Astar_midi.json"
echo "    • performance_S_midi.jsonl"
echo "    • annotated_score_midi.jsonl"
echo ""
echo "  - $OUTPUT_DIR/language_cpt_rounds/"
echo "    • round1.jsonl (S-tier 1/2)"
echo "    • round2.jsonl (S-tier 2/2)"
echo "    • round3.jsonl (A*-tier 1/3)"
echo "    • round4.jsonl (A*-tier 2/3)"
echo "    • round5.jsonl (A*-tier 3/3)"
echo ""
echo "Check summary:"
echo "  cat $OUTPUT_DIR/language_cpt/language_cpt_measure_summary.json"
echo ""
