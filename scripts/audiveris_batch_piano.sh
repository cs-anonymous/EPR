#!/bin/bash
# Batch-convert PDFs/images under piano_scores/ to MusicXML using Audiveris
# Usage: bash audiveris_batch_piano.sh [JOBS]
# Default: 16 concurrent jobs.

set -u

JOBS="${1:-16}"
SCORE_DIR="/home/sy/2026/Music/EPR/piano_scores"
AUDIVERIS="/home/sy/2026/Music/OMR/audiveris/bin/Audiveris"
JOBLOG="/home/sy/2026/Music/EPR/data/piano_scores_audiveris_joblog.tsv"
RUN_LOG="/home/sy/2026/Music/EPR/data/piano_scores_audiveris_run.log"
PER_JOB_TIMEOUT="${PER_JOB_TIMEOUT:-5400}"

if [ ! -x "$AUDIVERIS" ]; then
    echo "ERROR: Audiveris not found at $AUDIVERIS" >&2
    exit 1
fi

# Find convertible PDFs (Audiveris batch mode works reliably with PDFs)
mapfile -t FILES < <(find "$SCORE_DIR" -type f -iname "*.pdf" | sort)
TOTAL=${#FILES[@]}
echo "Found $TOTAL convertible files under $SCORE_DIR"
echo "Concurrency: $JOBS  Per-job timeout: ${PER_JOB_TIMEOUT}s"
echo ""

WRAPPER=$(mktemp /tmp/audiveris_piano_XXXXXX.sh)
cat > "$WRAPPER" << 'INNER_EOF'
#!/bin/bash
file="$1"
audiveris="$2"
timeout_s="$3"
out_dir=$(dirname "$file")
name=$(basename "$file")
base="${name%.*}"

# Idempotent skip: if output MXL/musicxml already exists and non-trivial, skip.
existing=$(find "$out_dir" -maxdepth 1 -type f \( -name "${base}.mxl" -o -name "${base}.mvt*.mxl" -o -name "${base}.musicxml" -o -name "${base}.mvt*.musicxml" \) -size +100c 2>/dev/null | head -1)
if [ -n "$existing" ]; then
    echo "SKIP (exists): $file"
    exit 0
fi

log_file="$out_dir/.audiveris_${base}.log"

echo "START: $file"
timeout "$timeout_s" "$audiveris" \
    -batch -transcribe -export -save \
    -output "$out_dir" \
    -- "$file" \
    > "$log_file" 2>&1
rc=$?

mxl_count=$(find "$out_dir" -maxdepth 2 -path "*${base}*" \( -name "*.mxl" -o -name "*.musicxml" \) 2>/dev/null | wc -l)
if [ "$mxl_count" -gt 0 ]; then
    echo "DONE: $file  ($mxl_count file(s))"
    exit 0
else
    echo "FAIL (rc=$rc, no mxl): $file  -> see $log_file"
    exit 1
fi
INNER_EOF
chmod +x "$WRAPPER"

printf '%s\n' "${FILES[@]}" | parallel -j "$JOBS" --joblog "$JOBLOG" --line-buffer \
    "$WRAPPER" {} "$AUDIVERIS" "$PER_JOB_TIMEOUT" 2>&1 | tee -a "$RUN_LOG"

rm -f "$WRAPPER"

echo ""
echo "=== Summary ==="
ok=0; fail=0
for file in "${FILES[@]}"; do
    d=$(dirname "$file")
    base=$(basename "$file")
    base="${base%.*}"
    if find "$d" -maxdepth 2 -path "*${base}*" \( -name "*.mxl" -o -name "*.musicxml" \) -size +100c 2>/dev/null | grep -q .; then
        ok=$((ok+1))
    else
        fail=$((fail+1))
    fi
done
echo "Files with MXL output: $ok / $TOTAL   (failed: $fail)"
echo "Job log: $JOBLOG"
echo "Run log: $RUN_LOG"
