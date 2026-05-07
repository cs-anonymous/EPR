#!/usr/bin/env python3
"""LEGATO inference for missing/failed PDF files — single-process sequential."""
import json, os, subprocess, shutil, time
from pathlib import Path

PROJECT = Path("/home/sy/2026/Music/EPR")
PDF_ROOT = Path("/home/sy/2026/Music/EPR/data/IMSLP_Mannual")
OUT_DIR = Path("/home/sy/2026/Music/EPR/data/maestro_score_v1_abc_legato")
PNG_DIR = Path("/tmp/legato_missing")
MODEL = PROJECT / "legato/checkpoints/legato"
INFERENCE = PROJECT / "scripts/legato_inference.py"
LOG_FILE = OUT_DIR / "_missing_convert_log.json"
DPI = 200
CONDA_PYTHON = "/home/sy/anaconda3/envs/legato/bin/python3"

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
    return pngs


def run_legato(work_png_dir: str, output_json: str, err_log_path: str) -> bool:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(PROJECT / "legato")
    with open(err_log_path, "w") as err_f:
        result = subprocess.run(
            [CONDA_PYTHON, str(INFERENCE),
             "--model_path", str(MODEL),
             "--image_path", work_png_dir,
             "--output_path", output_json,
             "--beam_size", "3", "--fp16"],
            stdout=subprocess.PIPE, stderr=err_f,
            text=True, timeout=7200,
            cwd=str(PROJECT),
            env=env,
        )
    return result.returncode == 0


def main():
    # Load existing results
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

    # Count total pages
    total_pages = 0
    for c, w, b, p in pending:
        total_pages += get_page_count(p)
    print(f"Total pages: {total_pages}")
    print(f"Est time (50s/page): ~{total_pages * 50 // 60} min")
    print()

    for i, (composer, work_id, batch, pdf) in enumerate(pending):
        work_key = f"{composer}__{work_id}"
        out_abc = OUT_DIR / f"{composer}__{work_id}.abc"
        out_json = OUT_DIR / f"{composer}__{work_id}.json"
        err_log = OUT_DIR / f"{work_key}.stderr.log"
        work_png_dir = PNG_DIR / work_key

        if not os.path.exists(pdf):
            print(f"[{i+1}/{len(pending)}] MISSING PDF: {composer}/{work_id}", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch, "status": "MISSING"})
            LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
            continue

        print(f"[{i+1}/{len(pending)}] {batch} {composer}/{work_id}", flush=True)
        t0 = time.time()

        # Rasterize
        pngs = rasterize_pdf(pdf, work_key)
        if not pngs:
            elapsed = time.time() - t0
            print(f"  FAIL_RASTER ({elapsed:.0f}s)", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                "status": "FAIL_RASTER", "time_s": round(elapsed, 1)})
            LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
            continue

        page_count = len(pngs)
        print(f"  {page_count} pages rasterized", flush=True)

        # Run LEGATO
        success = run_legato(str(work_png_dir), str(out_json), str(err_log))
        elapsed = time.time() - t0

        if not success or not out_json.exists():
            print(f"  FAIL_INFERENCE ({elapsed:.0f}s) — see {err_log}", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                "status": "FAIL_INFERENCE", "pages": page_count,
                                "time_s": round(elapsed, 1)})
            LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
            if work_png_dir.exists():
                shutil.rmtree(work_png_dir)
            continue

        # Parse ABC
        try:
            d = json.load(open(out_json))
            abcs = d.get("abc_transcription", [])
            if not abcs:
                print(f"  FAIL_NO_ABC ({elapsed:.0f}s)", flush=True)
                all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                    "status": "FAIL_NO_ABC", "pages": page_count,
                                    "time_s": round(elapsed, 1)})
            else:
                out_abc.write_text("\n\n".join(abcs))
                total_chars = sum(len(a) for a in abcs)
                print(f"  OK  {page_count}p  {total_chars} chars  ({elapsed:.0f}s)", flush=True)
                all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                    "status": "OK", "pages": page_count,
                                    "chars": total_chars, "time_s": round(elapsed, 1)})
        except Exception as e:
            print(f"  FAIL_PARSE ({elapsed:.0f}s): {e}", flush=True)
            all_results.append({"composer": composer, "work_id": work_id, "batch": batch,
                                "status": "FAIL_PARSE", "pages": page_count,
                                "time_s": round(elapsed, 1), "error": str(e)})

        if work_png_dir.exists():
            shutil.rmtree(work_png_dir)

        LOG_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))

    # Summary
    from collections import Counter
    stats = Counter(r["status"] for r in all_results)
    print(f"\n=== Summary ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:20} {v}")
    ok = stats.get("OK", 0)
    print(f"\nTotal ABC: {ok}/{len(all_results)}")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
