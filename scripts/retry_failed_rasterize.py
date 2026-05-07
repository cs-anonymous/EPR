#!/usr/bin/env python3
"""
Retry rasterization for PDFs that failed (decompression bomb / timeout).
Uses lower DPI (150) and raised PIL limit.
"""
import os
import subprocess
import sys
import tempfile
import shutil
import math
from pathlib import Path
from PIL import Image

# Disable PIL's decompression bomb check for trusted local files
Image.MAX_IMAGE_PIXELS = None

FAILED_PDFS = [
    "/home/sy/2026/Music/EPR/piano_scores/08 名曲总谱合集/[披头士爵士钢琴谱].__Book_-_Beatles_-_Beatles_For_Jazz_Piano.pdf",
    "/home/sy/2026/Music/EPR/piano_scores/1古典钢琴知名音乐家谱/普罗科菲耶夫 钢琴谱全集/Two_Pieces_Op45.pdf",
    "/home/sy/2026/Music/EPR/piano_scores/1古典钢琴知名音乐家谱/普罗科菲耶夫 钢琴谱全集/OP.54 小奏鸣曲.pdf",
    "/home/sy/2026/Music/EPR/piano_scores/1古典钢琴知名音乐家谱/拉赫玛尼诺夫 钢琴谱全集/拉赫小奏鸣曲.pdf",
    "/home/sy/2026/Music/EPR/piano_scores/08 名曲总谱合集/舞剧《白毛女》总谱.pdf",
]

TARGET_DPI = 150
MAX_PIXELS = 19_000_000


def rasterize_one(pdf_path: str) -> str:
    if not os.path.exists(pdf_path):
        return f"MISSING: {pdf_path}"

    tmpdir = tempfile.mkdtemp(prefix="retry_raster_")
    try:
        result = subprocess.run([
            "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
            "-sDEVICE=png16m",
            f"-r{TARGET_DPI}",
            f"-sOutputFile={tmpdir}/page_%05d.png",
            pdf_path
        ], capture_output=True, text=True, timeout=7200)

        png_files = sorted(Path(tmpdir).glob("page_*.png"))
        if not png_files:
            return f"FAIL_RENDER: {pdf_path}: {result.stderr[:200]}"

        # Downscale each oversized page
        downscaled = 0
        out_path = pdf_path + ".rasterized.pdf"
        images = []
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

        images[0].save(
            out_path, "PDF", save_all=True,
            append_images=images[1:], resolution=TARGET_DPI
        )
        for img in images:
            img.close()

        if not (os.path.exists(out_path) and os.path.getsize(out_path) > 1024):
            return f"FAIL_SAVE: {pdf_path}"

        os.replace(out_path, pdf_path)
        return f"OK: {os.path.basename(pdf_path)} ({len(png_files)} pages, {downscaled} downscaled)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT: {pdf_path}"
    except Exception as e:
        return f"EXCEPTION: {pdf_path}: {e}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    for pdf in FAILED_PDFS:
        print(f"Processing: {os.path.basename(pdf)}", flush=True)
        result = rasterize_one(pdf)
        print(f"  {result}", flush=True)


if __name__ == "__main__":
    main()
