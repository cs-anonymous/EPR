#!/bin/bash
# Downscale large PDFs for Audiveris (max 20M pixels/page)
# Usage: bash downscale_large_pdfs.sh [JOBS]
set -u
JOBS="${1:-8}"
SCORE_DIR="/home/sy/2026/Music/EPR/piano_scores"

mapfile -t PDFS < <(find "$SCORE_DIR" -type f \( -iname "*.pdf" \) -size +5M | sort)
echo "Found ${#PDFS[@]} large PDFs to downscale"

WRAPPER=$(mktemp /tmp/downscale_pdf_XXXXXX.sh)
cat > "$WRAPPER" << 'INNER_EOF'
#!/bin/bash
pdf="$1"
tmp="${pdf}.tmp.pdf"
gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite \
   -dPDFSETTINGS=/ebook \
   -dDownsampleColorImages=true -dColorImageResolution=200 \
   -dDownsampleGrayImages=true -dGrayImageResolution=200 \
   -dDownsampleMonoImages=true -dMonoImageResolution=200 \
   -sOutputFile="$tmp" "$pdf" 2>/dev/null
if [ -f "$tmp" ] && [ "$(stat -c%s "$tmp")" -gt 100 ]; then
    mv "$tmp" "$pdf"
    echo "DOWNSCALE: $(basename "$pdf")"
else
    rm -f "$tmp"
    echo "SKIP: $(basename "$pdf")"
fi
INNER_EOF
chmod +x "$WRAPPER"

printf '%s\n' "${PDFS[@]}" | parallel -j "$JOBS" --line-buffer "$WRAPPER" {}
rm -f "$WRAPPER"

echo "Done. PDF sizes:"
find "$SCORE_DIR" -type f \( -iname "*.pdf" \) -size +5M | wc -l | xargs -I{} echo "  Still >5MB: {}"
