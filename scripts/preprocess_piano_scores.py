#!/usr/bin/env python3
"""
Preprocess piano_scores:
1. Group images per directory into a single multi-page PDF
2. Downscale PDFs with pages > 15M pixels (Audiveris limit is 20M)
3. Clean up original images after successful PDF creation

Usage: python3 preprocess_piano_scores.py
"""
import os
import subprocess
import sys
from pathlib import Path
from PIL import Image

SCORE_DIR = "/home/sy/2026/Music/EPR/piano_scores"
MAX_PIXELS = 15_000_000  # Keep under Audiveris 20M limit
MAX_DIM = 4000  # Max width/height after resize
IMAGE_EXTS = {'.jpg', '.jpeg', '.gif', '.bmp', '.png'}

def resize_image(img_path, max_pixels=MAX_PIXELS, max_dim=MAX_DIM):
    """Resize image if too large, return PIL Image."""
    img = Image.open(img_path).convert('RGB')
    w, h = img.size
    pixels = w * h

    if pixels > max_pixels or w > max_dim or h > max_dim:
        ratio = min(max_pixels / pixels, max_dim / w, max_dim / h) ** 0.5
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, True
    return img, False

def images_to_pdf(dir_path):
    """Convert all images in a directory to a single multi-page PDF."""
    images = sorted([
        f for f in os.listdir(dir_path)
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS
    ])

    if not images:
        return 0

    pdf_path = os.path.join(dir_path, "_combined.pdf")
    if os.path.exists(pdf_path):
        print(f"SKIP {dir_path} (PDF exists)")
        return 0

    resized = 0
    pdf_images = []
    for img_name in images:
        img_path = os.path.join(dir_path, img_name)
        try:
            img, was_resized = resize_image(img_path)
            pdf_images.append(img)
            if was_resized:
                resized += 1
        except Exception as e:
            print(f"  WARN: skip {img_name}: {e}")

    if not pdf_images:
        return 0

    pdf_images[0].save(
        pdf_path, "PDF", save_all=True, append_images=pdf_images[1:],
        resolution=150
    )

    # Remove original images after successful PDF creation
    for img_name in images:
        os.remove(os.path.join(dir_path, img_name))

    print(f"  PDF: {len(pdf_images)} images ({resized} resized) -> {pdf_path}")
    return len(pdf_images)

def downscale_pdf(pdf_path):
    """Downscale a PDF if its pages exceed the pixel limit."""
    # Check page dimensions
    try:
        result = subprocess.run(
            ['gs', '-q', '-dNODISPLAY', '-c',
             f'({pdf_path}) (r) file runpdfbegin '
             '/pdfpagecount currentdict /PageCount get def '
             'pdfpagecount 1 eq { '
             '  pdfdict /MediaBox get dup 3 get exch 2 get dup mul mul = '
             '} { '
             '  pdfpagecount = '
             '} ifelse '
             'quit'],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
    except Exception:
        return

    try:
        pixels = int(output)
    except ValueError:
        return

    if pixels > MAX_PIXELS:
        tmp = pdf_path + ".tmp"
        try:
            subprocess.run([
                'gs', '-q', '-dNOPAUSE', '-dBATCH', '-sDEVICE=pdfwrite',
                '-dPDFSETTINGS=/ebook',
                '-dDownsampleColorImages=true', '-dColorImageResolution=150',
                '-dDownsampleGrayImages=true', '-dGrayImageResolution=150',
                '-dDownsampleMonoImages=true', '-dMonoImageResolution=150',
                '-sOutputFile=' + tmp, pdf_path
            ], timeout=120, capture_output=True)

            if os.path.exists(tmp) and os.path.getsize(tmp) > 100:
                os.replace(tmp, pdf_path)
                print(f"  DOWNSCALE: {pdf_path} ({pixels}px)")
            else:
                os.remove(tmp)
        except Exception as e:
            print(f"  FAIL downscale: {pdf_path}: {e}")

def main():
    print("=== Phase 1: Combine images into PDFs ===")
    total_images = 0
    for root, dirs, files in os.walk(SCORE_DIR):
        images = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
        if images:
            total_images += images_to_pdf(root)

    print(f"\nCombined {total_images} images into PDFs")

    print("\n=== Phase 2: Downscale large PDFs ===")
    pdfs = []
    for root, dirs, files in os.walk(SCORE_DIR):
        for f in files:
            if f.lower().endswith('.pdf'):
                pdfs.append(os.path.join(root, f))

    print(f"Checking {len(pdfs)} PDFs...")
    for pdf in pdfs:
        downscale_pdf(pdf)

    print("\n=== Done ===")
    pdf_count = sum(1 for r, d, f in os.walk(SCORE_DIR) for x in f if x.lower().endswith('.pdf'))
    img_count = sum(1 for r, d, f in os.walk(SCORE_DIR) for x in f if os.path.splitext(x)[1].lower() in IMAGE_EXTS)
    print(f"PDFs: {pdf_count}")
    print(f"Images remaining: {img_count}")

if __name__ == '__main__':
    main()
