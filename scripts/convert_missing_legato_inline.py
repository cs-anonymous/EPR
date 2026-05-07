#!/usr/bin/env python3
"""LEGATO inference for missing/failed PDF files.
Model loaded ONCE, processes all files sequentially.
Run with: /home/sy/anaconda3/envs/legato/bin/python3 scripts/convert_missing_legato_inline.py
"""
import json, os, shutil, subprocess, sys, time, re
from pathlib import Path

PROJECT = Path("/home/sy/2026/Music/EPR")
PDF_ROOT = Path("/home/sy/2026/Music/EPR/data/IMSLP_Mannual")
OUT_DIR = Path("/home/sy/2026/Music/EPR/data/maestro_score_v1_abc_legato")
PNG_DIR = Path("/tmp/legato_missing")
MODEL_PATH = PROJECT / "legato/checkpoints/legato"
LOG_FILE = OUT_DIR / "_missing_convert_log.json"
DPI = 200

OUT_DIR.mkdir(parents=True, exist_ok=True)
PNG_DIR.mkdir(parents=True, exist_ok=True)

ALL_ITEMS = [
    ("franz_liszt", "s0139", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p027.pdf")),
    ("franz_liszt", "s0141", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p029.pdf")),
    ("franz_liszt", "s0159", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p030.pdf")),
    ("johann_sebastian_bach", "_franz_liszt", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p041.pdf")),
    ("johann_sebastian_bach", "bwv0857", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p046.pdf")),
    ("johannes_brahms", "k0002", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p049.pdf")),
    ("johannes_brahms", "op0001", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p050.pdf")),
    ("johannes_brahms", "op0005", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p051.pdf")),
    ("johannes_brahms", "op0116", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p052.pdf")),
    ("johannes_brahms", "op0116", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p053.pdf")),
    ("johannes_brahms", "op0119", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p054.pdf")),
    ("johannes_brahms", "op0119", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p055.pdf")),
    ("ludwig_van_beethoven", "op0077", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p058.pdf")),
    ("ludwig_van_beethoven", "op0126", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p059.pdf")),
    ("robert_schumann", "op0001", "P0", str(PDF_ROOT / "_pending_manual_P0" / "p061.pdf")),
    ("ludwig_van_beethoven", "op0035", "P1", str(PDF_ROOT / "_pending_manual_P1" / "p082.pdf")),
    ("wolfgang_amadeus_mozart", "k0281", "P1", str(PDF_ROOT / "_pending_manual_P1" / "p087.pdf")),
    ("johannes_brahms", "op0002", "P1", str(PDF_ROOT / "_pending_manual_P1" / "p090.pdf")),
    ("alexander_scriabin", "op0053", "P1", str(PDF_ROOT / "_pending_manual_P1" / "p091.pdf")),
    ("edvard_grieg", "op0047", "P1", str(PDF_ROOT / "_pending_manual_P1" / "p104.pdf")),
]

# Set env before imports
os.environ["PYTHONNOUSERSITE"] = "1"
sys.path.insert(0, str(PROJECT / "legato"))

import torch
from PIL import Image
from transformers import AutoProcessor, GenerationConfig
from legato.models import LegatoModel


def strip_text_placeholders(abc: str) -> str:
    out = abc.replace('"<|text|>"', '')
    out = re.sub(r'"[\^_@<>][^"]*<\|text\|>[^"]*"', '', out)
    out = re.sub(r'\b(nm|snm)=<\|text\|>\s*', '', out)
    out = out.replace('<|text|>', '')
    out = re.sub(r'""', '', out)
    out = re.sub(r'[ \t]+\n', '\n', out)
    return out


def get_page_count(pdf: str) -> int:
    try:
        r = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split('\n'):
            if line.startswith('Pages:'):
                return int(line.split(':')[1].strip())
    except Exception:
        pass
    return 0


def rasterize_pdf(pdf_path: str, work_key: str) -> list[str]:
    work_png_dir = PNG_DIR / work_key
    if work_png_dir.exists():
        shutil.rmtree(work_png_dir)
    work_png_dir.mkdir(parents=True, exist_ok=True)
    prefix = str(work_png_dir / work_key)
    result = subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), pdf_path, prefix],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"    pdftoppm error: {result.stderr[:200]}", flush=True)
        return []
    pngs = sorted(work_png_dir.glob(f"{work_key}-*.png"))
    return [str(p) for p in pngs]


def infer_page(model, processor, img_path: str, gen_cfg) -> str:
    img = Image.open(img_path).convert("RGB")
    inputs = processor(images=[img], truncation=True, return_tensors="pt")
    inputs = {k: v.to("cuda") for k, v in inputs.items()}
    with torch.no_grad():
        out_ids = model.generate(**inputs, generation_config=gen_cfg, use_model_defaults=False)
    decoded = processor.batch_decode(out_ids.tolist(), skip_special_tokens=True)[0]
    return strip_text_placeholders(decoded)


def main():
    done_keys = set()
    all_results = []
    if LOG_FILE.exists():
        try:
            all_results = json.load(open(LOG_FILE))
            done_keys = {r['composer'] + '/' + r['work_id'] for r in all_results if r.get('status') in ('OK', 'SKIP')}
        except Exception:
            pass

    pending = [(c, w, b, p) for c, w, b, p in ALL_ITEMS if f"{c}/{w}" not in done_keys]
    print(f"Already done: {len(done_keys)}, pending: {len(pending)}, total: {len(ALL_ITEMS)}")

    if not pending:
        print("Nothing to do!")
        return

    total_pages = sum(get_page_count(p) for _, _, _, p in pending)
    print(f"Total pages: {total_pages}")
    print(f"Est time (50s/page): ~{total_pages * 50 // 60} min")

    print("\nLoading model...")
    t_load = time.time()
    model = LegatoModel.from_pretrained(str(MODEL_PATH))
    processor = AutoProcessor.from_pretrained(str(MODEL_PATH))
    model = model.to("cuda").half()
    print(f"Model loaded in {time.time() - t_load:.0f}s")

    gen_cfg = GenerationConfig(max_length=2048, num_beams=3, repetition_penalty=1.3)

    ok_count = 0
    for i, (composer, work_id, batch, pdf) in enumerate(pending):
        work_key = f"{composer}__{work_id}"
        out_abc = OUT_DIR / f"{composer}__{work_id}.abc"
        work_png_dir = PNG_DIR / work_key

        if not os.path.exists(pdf):
            print(f"\n[{i+1}/{len(pending)}] MISSING PDF: {composer}/{work_id}", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch, "status": "MISSING"})
            LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
            continue

        print(f"\n[{i+1}/{len(pending)}] {batch} {composer}/{work_id}", flush=True)
        t0 = time.time()

        pngs = rasterize_pdf(pdf, work_key)
        if not pngs:
            elapsed = time.time() - t0
            print(f"  FAIL_RASTER ({elapsed:.0f}s)", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                "status": "FAIL_RASTER", "time_s": round(elapsed, 1)})
            LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
            continue

        page_count = len(pngs)
        print(f"  {page_count} pages, starting inference...", flush=True)

        abcs = []
        fail = False
        for j, png in enumerate(pngs):
            try:
                abc = infer_page(model, processor, png, gen_cfg)
                abcs.append(abc)
                if (j + 1) % 5 == 0 or (j + 1) == page_count:
                    print(f"  page {j+1}/{page_count}: {len(abc)} chars", flush=True)
            except Exception as e:
                print(f"  FAIL page {j+1}: {e}", flush=True)
                fail = True
                break

        elapsed = time.time() - t0

        if fail or not abcs:
            print(f"  FAIL_INFERENCE ({elapsed:.0f}s)", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                "status": "FAIL_INFERENCE", "pages": page_count,
                                "time_s": round(elapsed, 1)})
        else:
            out_abc.write_text("\n\n".join(abcs))
            total_chars = sum(len(a) for a in abcs)
            print(f"  OK  {page_count}p  {total_chars} chars  ({elapsed:.0f}s)", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                "status": "OK", "pages": page_count,
                                "chars": total_chars, "time_s": round(elapsed, 1)})
            ok_count += 1

        if work_png_dir.exists():
            shutil.rmtree(work_png_dir)
        torch.cuda.empty_cache()
        LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))

    from collections import Counter
    stats = Counter(r["status"] for r in all_results)
    print(f"\n=== Summary ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:20} {v}")
    print(f"\nTotal ABC: {ok_count}/{len(all_results)}")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
