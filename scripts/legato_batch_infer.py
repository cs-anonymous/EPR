#!/usr/bin/env python3
"""LEGATO batch convert: rasterize PDFs → ABC for P0 and/or P1.

Usage:
    python scripts/legato_batch_infer.py --batch both     # P0 + P1
    python scripts/legato_batch_infer.py --batch P0       # P0 only
    python scripts/legato_batch_infer.py --batch P1       # P1 only
    python scripts/legato_batch_infer.py --batch both --resume  # skip done works

Each PDF is rasterized page-by-page, then LEGATO inference runs on all pages
of that work, and outputs are concatenated into a single .abc file.
"""
import json, os, subprocess, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

PDF_ROOT = Path("/home/sy/2026/Music/EPR/data/IMSLP_Mannual")
OUT_DIR = Path("/home/sy/2026/Music/EPR/data/maestro_score_v1_abc_legato")
PNG_DIR = Path("/tmp/legato_png_batch")
MODEL = Path("/home/sy/2026/Music/EPR/legato/checkpoints/legato")
INFERENCE = Path("/home/sy/2026/Music/EPR/scripts/legato_inference.py")
LOG_FILE = OUT_DIR / "_build_log.json"
DPI = 200

OUT_DIR.mkdir(parents=True, exist_ok=True)
PNG_DIR.mkdir(parents=True, exist_ok=True)


def load_mapping(batch: str):
    """Load P0 or P1 mapping.json, return list of (composer, work_id, short_pdf, pdf_path)."""
    d = PDF_ROOT / f"_pending_manual_{batch}"
    mpath = d / "_mapping.json"
    if not mpath.exists():
        return []
    m = json.load(open(mpath))
    items = []
    for short, orig in sorted(m.items()):
        parts = orig.split("__")
        composer = parts[0] if len(parts) > 0 else "unknown"
        work = parts[1] if len(parts) > 1 else "unknown"
        pdf = d / short
        items.append((composer, work, short, str(pdf)))
    return items


def rasterize_pdf(pdf_path: str, work_key: str) -> list[str]:
    """Rasterize a PDF to PNGs. Returns list of PNG paths, or [] on failure."""
    prefix = str(PNG_DIR / work_key)
    result = subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), pdf_path, prefix],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  rasterize FAILED: {result.stderr[:200]}")
        return []
    pngs = sorted(str(p) for p in PNG_DIR.glob(f"{work_key}-*.png"))
    return pngs


def run_legato(png_dir: str, output_json: str) -> bool:
    """Run LEGATO inference on all PNGs in directory."""
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(Path.cwd() / "legato")
    result = subprocess.run(
        [sys.executable, str(INFERENCE),
         "--model_path", str(MODEL),
         "--image_path", png_dir,
         "--output_path", output_json,
         "--beam_size", "3", "--fp16"],
        capture_output=True, text=True, timeout=7200,  # 2h max per work
        cwd=str(Path.cwd()),
        env=env,
    )
    return result.returncode == 0


def process_work(composer: str, work_id: str, short: str, pdf: str, resume: bool) -> dict:
    """Process one work: rasterize → infer → save ABC."""
    work_key = f"{composer}__{work_id}"
    out_abc = OUT_DIR / f"{composer}__{work_id}.abc"
    out_json = OUT_DIR / f"{composer}__{work_id}.json"

    if resume and out_abc.exists() and out_abc.stat().st_size > 100:
        return {"composer": composer, "work_id": work_id, "status": "SKIP", "short": short}

    t0 = time.time()

    # Rasterize
    pngs = rasterize_pdf(pdf, work_key)
    if not pngs:
        elapsed = time.time() - t0
        return {"composer": composer, "work_id": work_id, "status": "FAIL_RASTERIZE",
                "short": short, "time_s": round(elapsed, 1)}

    page_count = len(pngs)

    # Run LEGATO - all PNGs for this work in PNG_DIR
    # Need to point inference to the PNG_DIR (which may have other pages too,
    # but we only care about ones starting with work_key)
    # Actually, inference processes ALL pngs in the dir. So we need to isolate.
    # Create a temp dir for this work's PNGs only.
    work_png_dir = PNG_DIR / work_key
    work_png_dir.mkdir(parents=True, exist_ok=True)
    for png in pngs:
        subprocess.run(["cp", png, str(work_png_dir / os.path.basename(png))],
                      capture_output=True)

    success = run_legato(str(work_png_dir), str(out_json))
    elapsed = time.time() - t0

    if not success or not out_json.exists():
        return {"composer": composer, "work_id": work_id, "status": "FAIL_INFERENCE",
                "short": short, "pages": page_count, "time_s": round(elapsed, 1)}

    # Concatenate ABC outputs
    try:
        d = json.load(open(out_json))
        abcs = d.get("abc_transcription", [])
        if not abcs:
            return {"composer": composer, "work_id": work_id, "status": "FAIL_NO_ABC",
                    "short": short, "pages": page_count, "time_s": round(elapsed, 1)}
        out_abc.write_text("\n\n".join(abcs))
        total_chars = sum(len(a) for a in abcs)
        return {"composer": composer, "work_id": work_id, "status": "OK",
                "short": short, "pages": page_count, "tunes": len(abcs),
                "chars": total_chars, "time_s": round(elapsed, 1)}
    except Exception as e:
        return {"composer": composer, "work_id": work_id, "status": "FAIL_PARSE",
                "short": short, "pages": page_count, "time_s": round(elapsed, 1), "error": str(e)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["P0", "P1", "both"], default="both")
    ap.add_argument("--resume", action="store_true", help="Skip already-done works")
    args = ap.parse_args()

    # Get all works
    items = []
    if args.batch in ("P0", "both"):
        items.extend(load_mapping("P0"))
    if args.batch in ("P1", "both"):
        items.extend(load_mapping("P1"))

    print(f"Total works: {len(items)}")
    total_pages = 0
    for _, _, _, pdf in items:
        if os.path.exists(pdf):
            try:
                info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, timeout=5)
                for line in info.stdout.split('\n'):
                    if line.startswith('Pages:'):
                        total_pages += int(line.split(':')[1].strip())
                        break
            except:
                pass
    print(f"Total PDF pages: ~{total_pages}")
    print(f"Estimated time: ~{total_pages * 50 // 60} minutes at 50s/page (beam=3)")
    print(f"Output: {OUT_DIR}")
    print()

    results = []
    # Load existing results if resuming
    if args.resume and LOG_FILE.exists():
        try:
            existing = json.load(open(LOG_FILE))
            done = {r['composer'] + '/' + r['work_id'] for r in existing if r.get('status') == 'OK'}
            items = [(c, w, s, p) for c, w, s, p in items if f"{c}/{w}" not in done]
            print(f"Skipping {len(done)} already-done works, {len(items)} remaining")
            results = existing
        except:
            pass

    for i, (composer, work_id, short, pdf) in enumerate(items):
        if not os.path.exists(pdf):
            print(f"[{i+1}/{len(items)}] MISSING: {composer}/{work_id} ({short})")
            results.append({"composer": composer, "work_id": work_id, "status": "MISSING", "short": short})
            continue

        result = process_work(composer, work_id, short, pdf, resume=False)
        status = result["status"]
        pages = result.get("pages", "?")
        elapsed = result.get("time_s", "?")
        print(f"[{i+1}/{len(items)}] {status:20} {composer}/{work_id}  pages={pages}  {elapsed:.0f}s")
        results.append(result)

        # Save log after each work
        LOG_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Summary
    from collections import Counter
    stats = Counter(r["status"] for r in results)
    print(f"\n=== Summary ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:20} {v}")
    ok = stats.get("OK", 0)
    print(f"\nTotal ABC: {ok}/{len(results)}")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
