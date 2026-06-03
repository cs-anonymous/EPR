#!/bin/bash
# Generate Language CPT Corpora V2
#
# This script generates language CPT training data with:
# - Tokenizer: Qwen3.5-0.8B-LM-MIDI-Resized
# - Workers: 32 threads
# - S-tier: shuffle, split into train_S1/train_S2
# - A*-tier: shuffle, split into train_Astar1/train_Astar2/train_Astar3
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
echo "  - train_S1: S-tier shuffled split 1/2 + full annotated score"
echo "  - train_S2: S-tier shuffled split 2/2 + full annotated score"
echo "  - train_Astar1: A*-tier shuffled split 1/3 + full annotated score"
echo "  - train_Astar2: A*-tier shuffled split 2/3 + full annotated score"
echo "  - train_Astar3: A*-tier shuffled split 3/3 + full annotated score"
echo ""

python scripts/build_language_cpt_rounds.py \
  --corpora-dir "$OUTPUT_DIR/language_cpt" \
  --output-dir "$OUTPUT_DIR/language_cpt/rounds" \
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
echo "  - $OUTPUT_DIR/language_cpt/rounds/"
echo "    • train_S1.jsonl (S-tier 1/2 + annotated score)"
echo "    • train_S2.jsonl (S-tier 2/2 + annotated score)"
echo "    • train_Astar1.jsonl (A*-tier 1/3 + annotated score)"
echo "    • train_Astar2.jsonl (A*-tier 2/3 + annotated score)"
echo "    • train_Astar3.jsonl (A*-tier 3/3 + annotated score)"
echo ""
echo "Check summary:"
echo "  cat $OUTPUT_DIR/language_cpt/language_cpt_measure_summary.json"
echo ""
