#!/usr/bin/env python3
"""
Re-rasterize PDFs whose pages exceed Audiveris's 20M pixel limit.

Approach:
1. Use pdfinfo to determine per-page sizes.
2. If any page would render to >19M pixels at 300 DPI, render the whole
   PDF at 300 DPI to PNG, downscale any oversized PNG to fit within 19M
   pixels, then reassemble into a new PDF.

Usage: python3 rasterize_oversized_pdfs.py [JOBS]
"""
import os
import subprocess
import sys
import tempfile
import shutil
import math
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

SCORE_DIR = "/home/sy/2026/Music/EPR/piano_scores"
TARGET_DPI = 250
MAX_PIXELS = 19_000_000


def probe_max_pixels_at_dpi(pdf_path: str, dpi: int) -> int:
    try:
        out = subprocess.run(
            ["pdfinfo", "-l", "999999", pdf_path],
            capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return 0

    max_pts2 = 0
    for line in out.splitlines():
        line = line.strip()
        if "size:" in line.lower() and "pts" in line and "x" in line:
            try:
                parts = line.split("size:", 1)[1].strip().split("pts")[0]
                w_str, h_str = parts.split("x")
                w = float(w_str.strip())
                h = float(h_str.strip())
                if w * h > max_pts2:
                    max_pts2 = w * h
            except (ValueError, IndexError):
                continue

    if max_pts2 == 0:
        return 0
    return int(max_pts2 * (dpi / 72.0) ** 2)


def rasterize_pdf(pdf_path: str) -> str:
    try:
        max_pixels = probe_max_pixels_at_dpi(pdf_path, TARGET_DPI)
    except Exception as e:
        return f"PROBE_ERROR: {pdf_path}: {e}"

    if max_pixels == 0:
        return f"PROBE_ZERO: {pdf_path}"

    if max_pixels <= MAX_PIXELS:
        return f"OK: {os.path.basename(pdf_path)}"

    tmpdir = tempfile.mkdtemp(prefix="rasterize_")
    try:
        # Render all pages at TARGET_DPI
        result = subprocess.run([
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
            "-sDEVICE=png16m",
            f"-r{TARGET_DPI}",
            f"-sOutputFile={tmpdir}/page_%05d.png",
            pdf_path
        ], capture_output=True, text=True, timeout=3600)

        png_files = sorted(Path(tmpdir).glob("page_*.png"))
        if not png_files:
            return f"FAIL_RENDER: {pdf_path}: {result.stderr[:200]}"

        from PIL import Image
        images = []
        downscaled = 0
        for f in png_files:
            img = Image.open(f).convert("RGB")
            w, h = img.size
            if w * h > MAX_PIXELS:
                scale = math.sqrt(MAX_PIXELS / (w * h)) * 0.97
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                img = img.resize((new_w, new_h), Image.LANCZOS)
                downscaled += 1
            images.append(img)

        tmp_pdf = pdf_path + ".rasterized.pdf"
        images[0].save(
            tmp_pdf, "PDF", save_all=True,
            append_images=images[1:], resolution=TARGET_DPI
        )
        for img in images:
            img.close()

        if not (os.path.exists(tmp_pdf) and os.path.getsize(tmp_pdf) > 1024):
            return f"FAIL_SAVE: {pdf_path}"

        os.replace(tmp_pdf, pdf_path)
        return f"RASTERIZE: {os.path.basename(pdf_path)} ({len(png_files)} pages, {downscaled} downscaled)"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    pdfs = sorted(set(
        list(str(p) for p in Path(SCORE_DIR).rglob("*.pdf")) +
        list(str(p) for p in Path(SCORE_DIR).rglob("*.PDF"))
    ))

    print(f"Found {len(pdfs)} PDFs, processing with {jobs} workers", flush=True)

    ok = 0; rasterized = 0; failed = 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futures = {ex.submit(rasterize_pdf, p): p for p in pdfs}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                msg = fut.result()
            except Exception as e:
                msg = f"EXCEPTION: {futures[fut]}: {e}"
            if msg.startswith("OK"):
                ok += 1
            elif msg.startswith("RASTERIZE"):
                rasterized += 1
                print(msg, flush=True)
            else:
                failed += 1
                print(msg, flush=True)
            if i % 100 == 0:
                print(f"  [progress] {i}/{len(pdfs)} (OK={ok}, RAST={rasterized}, FAIL={failed})", flush=True)

    print(f"\n=== Done: {ok} OK, {rasterized} rasterized, {failed} failed ===")


if __name__ == "__main__":
    main()
