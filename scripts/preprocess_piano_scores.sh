#!/bin/bash
# Preprocess piano_scores: convert images to PDF and downscale large PDFs
# so Audiveris can handle them (max ~20M pixels per page).
# Target: max ~3500x5000 per page (~17.5M pixels) at 150 DPI.
# Usage: bash preprocess_piano_scores.sh [JOBS]

set -u
JOBS="${1:-16}"
SCORE_DIR="/home/sy/2026/Music/EPR/piano_scores"
# Max pixels per page: reduce to ~3500x5000 by setting max dimension
GS_DPI=150

echo "=== Phase 1: Convert images to PDF ==="
mapfile -t IMAGES < <(find "$SCORE_DIR" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.gif" -o -iname "*.bmp" -o -iname "*.png" \) | sort)
echo "Found ${#IMAGES[@]} images to convert"

WRAPPER_IMG=$(mktemp /tmp/preprocess_img_XXXXXX.sh)
cat > "$WRAPPER_IMG" << 'INNER_EOF'
#!/bin/bash
img="$1"
pdf="${img%.*}.pdf"

# Skip if PDF already exists and is newer
if [ -f "$pdf" ] && [ "$pdf" -nt "$img" ]; then
    echo "SKIP: $img"
    exit 0
fi

# Convert image to PDF
if command -v img2pdf &>/dev/null; then
    img2pdf "$img" -o "$pdf" 2>/dev/null
elif command -v convert &>/dev/null; then
    convert "$img" "$pdf" 2>/dev/null
else
    # Use gs to create PDF from image
    gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -sOutputFile="$pdf" -c "<< /PageSize [612 792] >> setpagedevice" -f "$img" 2>/dev/null
fi

if [ -f "$pdf" ]; then
    rm -f "$img"
    echo "CONVERTED: $img -> $pdf"
    exit 0
else
    echo "FAIL: $img"
    exit 1
fi
INNER_EOF
chmod +x "$WRAPPER_IMG"

printf '%s\n' "${IMAGES[@]}" | parallel -j "$JOBS" --line-buffer "$WRAPPER_IMG" {}
rm -f "$WRAPPER_IMG"

echo ""
echo "=== Phase 2: Downscale large PDFs ==="
mapfile -t PDFS < <(find "$SCORE_DIR" -type f -iname "*.pdf" | sort)
echo "Found ${#PDFS[@]} PDFs to check"

WRAPPER_PDF=$(mktemp /tmp/preprocess_pdf_XXXXXX.sh)
cat > "$WRAPPER_PDF" << 'INNER_EOF'
#!/bin/bash
pdf="$1"
gs_dpi="$2"

# Get page dimensions from gs
info=$(gs -q -dNODISPLAY -c "
($pdf) (r) file runpdfbegin
/pdfpagecount currentdict /PageCount get def
pdfpagecount 1 eq {
  1 pdfdict /MediaBox get dup 3 get exch 2 get dup mul mul
  = (pixels) =
} {
  pdfpagecount = (pages) =
} ifelse
" 2>/dev/null)

# If single page and over 15M pixels, downscale
pixels=$(echo "$info" | grep -oP '^\d+' | head -1)
if [ -n "$pixels" ] && [ "$pixels" -gt 15000000 ] 2>/dev/null; then
    tmp="${pdf}.tmp.pdf"
    gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite \
       -dPDFSETTINGS=/ebook \
       -dDownsampleColorImages=true -dColorImageResolution="$gs_dpi" \
       -dDownsampleGrayImages=true -dGrayImageResolution="$gs_dpi" \
       -dDownsampleMonoImages=true -dMonoImageResolution="$gs_dpi" \
       -sOutputFile="$tmp" "$pdf" 2>/dev/null
    if [ -f "$tmp" ]; then
        mv "$tmp" "$pdf"
        echo "DOWNSCALE: $pdf (${pixels}px)"
    fi
fi
exit 0
INNER_EOF
chmod +x "$WRAPPER_PDF"

printf '%s\n' "${PDFS[@]}" | parallel -j "$JOBS" --line-buffer "$WRAPPER_PDF" {} "$GS_DPI"
rm -f "$WRAPPER_PDF"

echo ""
echo "=== Preprocessing complete ==="
echo "PDFs: $(find "$SCORE_DIR" -iname "*.pdf" | wc -l)"
echo "Images remaining: $(find "$SCORE_DIR" -type f \( -iname "*.jpg" -o -iname "*.gif" -o -iname "*.bmp" -o -iname "*.png" \) | wc -l)"
