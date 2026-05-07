#!/bin/bash
# Retry a given list of PDFs. Cleans stale .omr/.log first so Audiveris doesn't
# short-circuit on cached failed state. Idempotent: skips PDFs that now have .mxl.
#
# Usage: bash audiveris_retry_list.sh <pdf_list_file> <JOBS>

set -u
LIST="${1:?Usage: $0 <pdf_list> <jobs>}"
JOBS="${2:-4}"
AUDIVERIS="/home/sy/2026/Music/OMR/audiveris/bin/Audiveris"
JOBLOG="/home/sy/2026/Music/EPR/data/IMSLP_Mannual/_audiveris_retry_joblog.tsv"
PER_JOB_TIMEOUT="${PER_JOB_TIMEOUT:-7200}"

mapfile -t PDFS < "$LIST"
TOTAL=${#PDFS[@]}
echo "Retrying $TOTAL PDFs with concurrency $JOBS, timeout ${PER_JOB_TIMEOUT}s"

# Clean stale .omr and old log; leave any pre-existing .mxl (idempotent skip handles those)
for pdf in "${PDFS[@]}"; do
    d=$(dirname "$pdf")
    n=$(basename "$pdf" .pdf)
    rm -f "$d/${n}.omr" "$d/.audiveris_${n}.log" 2>/dev/null
    # Remove any stale Audiveris timestamp log from last run
    find "$d" -maxdepth 1 -name "${n}-*T*.log" -delete 2>/dev/null
done
echo "Cleaned stale .omr and logs."

WRAPPER=$(mktemp /tmp/audiveris_retry_XXXXXX.sh)
cat > "$WRAPPER" << 'INNER_EOF'
#!/bin/bash
pdf="$1"; audiveris="$2"; timeout_s="$3"
out_dir=$(dirname "$pdf"); name=$(basename "$pdf" .pdf)
# Skip if MXL already appeared
existing=$(find "$out_dir" -maxdepth 1 -type f \( -name "${name}.mxl" -o -name "${name}.mvt*.mxl" -o -name "${name}.musicxml" -o -name "${name}.mvt*.musicxml" \) -size +100c 2>/dev/null | head -1)
if [ -n "$existing" ]; then echo "SKIP (exists): $pdf"; exit 0; fi
log_file="$out_dir/.audiveris_${name}.log"
echo "START: $pdf"
timeout "$timeout_s" "$audiveris" -batch -transcribe -export -save \
    -output "$out_dir" -- "$pdf" > "$log_file" 2>&1
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
echo "=== Retry summary ==="
ok=0; fail=0
for pdf in "${PDFS[@]}"; do
    d=$(dirname "$pdf"); n=$(basename "$pdf" .pdf)
    if find "$d" -maxdepth 2 -path "*${n}*" \( -name "*.mxl" -o -name "*.musicxml" \) -size +100c 2>/dev/null | grep -q .; then
        ok=$((ok+1)); else fail=$((fail+1)); fi
done
echo "OK: $ok / $TOTAL   FAIL: $fail"
