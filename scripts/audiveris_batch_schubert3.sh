#!/bin/bash
# Batch-convert PDFs under data/Schubert3/*.pdf to MusicXML using Audiveris.
# Usage: bash audiveris_batch_schubert3.sh [JOBS]

set -u
JOBS="${1:-6}"
PDF_ROOT="/home/sy/2026/Music/EPR/data/Schubert3"
AUDIVERIS="/home/sy/2026/Music/OMR/audiveris/bin/Audiveris"
JOBLOG="$PDF_ROOT/_audiveris_joblog.tsv"
PER_JOB_TIMEOUT="${PER_JOB_TIMEOUT:-7200}"  # 120 min per PDF cap

if [ ! -x "$AUDIVERIS" ]; then
    echo "ERROR: Audiveris not found at $AUDIVERIS" >&2; exit 1
fi

mapfile -t PDFS < <(find "$PDF_ROOT" -maxdepth 1 -name "*.pdf" | sort)
TOTAL=${#PDFS[@]}
echo "Found $TOTAL PDFs under $PDF_ROOT"
echo "Concurrency: $JOBS  Per-job timeout: ${PER_JOB_TIMEOUT}s"
echo ""

WRAPPER=$(mktemp /tmp/audiveris_job_XXXXXX.sh)
cat > "$WRAPPER" << 'INNER_EOF'
#!/bin/bash
pdf="$1"; audiveris="$2"; timeout_s="$3"
out_dir=$(dirname "$pdf"); name=$(basename "$pdf" .pdf)
existing=$(find "$out_dir" -maxdepth 1 -type f \( -name "${name}.mxl" -o -name "${name}.mvt*.mxl" -o -name "${name}.musicxml" -o -name "${name}.mvt*.musicxml" \) -size +100c 2>/dev/null | head -1)
if [ -n "$existing" ]; then echo "SKIP (exists): $pdf"; exit 0; fi
log_file="$out_dir/.audiveris_${name}.log"
echo "START: $pdf"
timeout "$timeout_s" "$audiveris" -batch -transcribe -export -save -output "$out_dir" -- "$pdf" > "$log_file" 2>&1
rc=$?
mxl_count=$(find "$out_dir" -maxdepth 2 -path "*${name}*" \( -name "*.mxl" -o -name "*.musicxml" \) 2>/dev/null | wc -l)
if [ "$mxl_count" -gt 0 ]; then echo "DONE: $pdf ($mxl_count file(s))"; exit 0
else echo "FAIL (rc=$rc): $pdf -> $log_file"; exit 1; fi
INNER_EOF
chmod +x "$WRAPPER"

printf '%s\n' "${PDFS[@]}" | parallel -j "$JOBS" --joblog "$JOBLOG" --line-buffer \
    "$WRAPPER" {} "$AUDIVERIS" "$PER_JOB_TIMEOUT"

rm -f "$WRAPPER"

echo ""
echo "=== Summary ==="
ok=0; fail=0
for pdf in "${PDFS[@]}"; do
    d=$(dirname "$pdf"); n=$(basename "$pdf" .pdf)
    if find "$d" -maxdepth 2 -path "*${n}*" \( -name "*.mxl" -o -name "*.musicxml" \) -size +100c 2>/dev/null | grep -q .; then
        ok=$((ok+1)); else fail=$((fail+1)); fi
done
echo "PDFs with MXL output: $ok / $TOTAL  (failed: $fail)"
echo "Job log: $JOBLOG"
