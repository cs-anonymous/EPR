#!/bin/bash
# LEGATO batch: rasterize PDFs + infer ABC for all works.
# Usage: bash scripts/legato_batch_convert.sh [P0|P1|both] [GPU_WAIT_SECONDS]
# Default: both batches, wait 0s.

set -e

BATCH="${1:-both}"
WAIT="${2:-0}"

PDF_ROOT="/home/sy/2026/Music/EPR/data/IMSLP_Mannual"
OUT_ROOT="/home/sy/2026/Music/EPR/data/maestro_score_v1_abc_legato"
PNG_ROOT="/tmp/legato_png_batch"
MODEL="/home/sy/2026/Music/EPR/legato/checkpoints/legato"
INFERENCE="/home/sy/2026/Music/EPR/scripts/legato_inference.py"
LOG="/home/sy/2026/Music/EPR/data/maestro_score_v1_abc_legato/_build_log.json"

conda activate legato
export PYTHONNOUSERSITE=1

mkdir -p "$OUT_ROOT" "$PNG_ROOT"

# Build list of (work_dir_name, pdf_path, pNNN.pdf, composer_work) from mappings
get_pdfs() {
  local batch=$1
  local dir="${PDF_ROOT}/_pending_manual_${batch}"
  local map_file="${dir}/_mapping.json"
  [ -f "$map_file" ] || return 1
  python3 -c "
import json
m = json.load(open('$map_file'))
for short, orig in sorted(m.items()):
    # extract composer/work from orig name
    parts = orig.split('__')
    composer = parts[0] if len(parts) > 0 else 'unknown'
    work = parts[1] if len(parts) > 1 else 'unknown'
    pdf = f'$dir/{short}'
    print(f'{composer}\t{work}\t{short}\t{pdf}')
"
}

process_one() {
  local composer=$1 work_id=$2 short_pdf=$3 pdf_path=$4 out_dir=$5 png_dir=$6
  local out_abc="$out_dir/${composer}__${work_id}.abc"
  local out_log="$out_dir/${composer}__${work_id}.json"
  local png_prefix="$png_dir/${composer}__${work_id}"

  # Skip if already done
  if [ -f "$out_abc" ] && [ -s "$out_abc" ]; then
    echo "SKIP (exists): $composer/$work_id"
    return 0
  fi

  # Rasterize
  mkdir -p "$png_dir"
  pdftoppm -png -r 200 "$pdf_path" "${png_prefix}" 2>/dev/null || {
    echo "FAIL (rasterize): $composer/$work_id"
    return 1
  }
  local png_count=$(ls ${png_prefix}-*.png 2>/dev/null | wc -l)
  if [ "$png_count" -eq 0 ]; then
    echo "FAIL (no pngs): $composer/$work_id"
    return 1
  fi

  # Run LEGATO
  PYTHONPATH=/home/sy/2026/Music/EPR/legato python "$INFERENCE" \
    --model_path "$MODEL" \
    --image_path "$png_dir" \
    --output_path "$out_log" \
    --beam_size 3 --fp16 2>&1 | tail -3 || {
    echo "FAIL (legato): $composer/$work_id"
    return 1
  }

  # Concatenate ABC outputs from JSON into one file
  python3 -c "
import json
d = json.load(open('$out_log'))
with open('$out_abc', 'w') as f:
    for i, abc in enumerate(d['abc_transcription']):
        if i > 0:
            f.write('\n\n')
        f.write(abc)
print(f'OK: $composer/$work_id  ($png_count pages)')
"

  # Clean PNGs for this work
  rm -f ${png_prefix}-*.png
  return 0
}

# Main
WORKS=()
COMPOSERS=()
SHORTS=()
PDFS=()

if [ "$BATCH" = "both" ] || [ "$BATCH" = "P0" ]; then
  while IFS=$'\t' read -r composer work_id short pdf; do
    COMPOSERS+=("$composer")
    WORKS+=("$work_id")
    SHORTS+=("$short")
    PDFS+=("$pdf")
  done < <(get_pdfs P0)
fi
if [ "$BATCH" = "both" ] || [ "$BATCH" = "P1" ]; then
  while IFS=$'\t' read -r composer work_id short pdf; do
    COMPOSERS+=("$composer")
    WORKS+=("$work_id")
    SHORTS+=("$short")
    PDFS+=("$pdf")
  done < <(get_pdfs P1)
fi

total=${#WORKS[@]}
echo "Total works to process: $total"
echo "PNG output: $PNG_ROOT"
echo "ABC output: $OUT_ROOT"
echo ""

for i in $(seq 0 $((total-1))); do
  composer="${COMPOSERS[$i]}"
  work_id="${WORKS[$i]}"
  short="${SHORTS[$i]}"
  pdf="${PDFS[$i]}"
  echo "[$((i+1))/$total] $composer/$work_id ($short)"
  process_one "$composer" "$work_id" "$short" "$pdf" \
    "$OUT_ROOT" "$PNG_ROOT"
  echo ""
done

echo "=== Summary ==="
total_abc=$(find "$OUT_ROOT" -name "*.abc" -size +0c | wc -l)
echo "ABC files produced: $total_abc / $total"
echo "Output: $OUT_ROOT"
