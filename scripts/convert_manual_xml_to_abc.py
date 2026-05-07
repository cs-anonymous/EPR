#!/usr/bin/env python3
"""Convert uploaded manual OMR XML files (pNNN.xml) to ABC.

Each pNNN.xml corresponds to a PDF in P0 or P1, mapped via
IMSLP_Mannual/_pending_manual_P{0,1}/_mapping.json.

Output: data/maestro_score_v1_abc/<composer>__<work_id>.abc
        Also updates v1 works dir with the new XML as score.xml if needed.

Usage: python scripts/convert_manual_xml_to_abc.py [--batch both]
"""
import json, subprocess, sys, os
from pathlib import Path

SCAN_DIR = Path("/home/sy/2026/Music/EPR/data/Scanned Music")
PDF_ROOT = Path("/home/sy/2026/Music/EPR/data/IMSLP_Mannual")
OUT_DIR = Path("/home/sy/2026/Music/EPR/data/maestro_score_v1_abc_legato")
V1_DIR = Path("/home/sy/2026/Music/EPR/data/maestro_score_v1/works")
XML2ABC = Path("/home/sy/2026/Music/EPR/xml2abc/xml2abc.py")
TMP = Path("/tmp/abc_manual")

OUT_DIR.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)

# Load mappings
def load_all_mappings():
    """Returns {short_pdf: (composer, work_id, batch, mapping_dict)}"""
    result = {}
    for batch in ["P0", "P1"]:
        mpath = PDF_ROOT / f"_pending_manual_{batch}" / "_mapping.json"
        if mpath.exists():
            m = json.load(open(mpath))
            for short, orig in m.items():
                parts = orig.split("__")
                composer = parts[0] if len(parts) > 0 else "unknown"
                work = parts[1] if len(parts) > 1 else "unknown"
                result[short] = (composer, work, batch, orig)
    return result

def pnnn_to_pdf(pnnn: str, mappings: dict) -> tuple:
    """Given pNNN.pdf, return (composer, work_id, batch, orig_name)."""
    key = pnnn
    if key in mappings:
        return mappings[key]
    return ("unknown", "unknown", "?", pnnn)

def convert_xml_to_abc(xml_path: str, out_dir: Path) -> tuple:
    """Run xml2abc on XML. Returns (success, abc_text_or_error)."""
    result = subprocess.run(
        [sys.executable, str(XML2ABC), xml_path, "-o", str(out_dir)],
        capture_output=True, text=True, timeout=600,
    )
    abcs = sorted(out_dir.glob("*.abc"))
    if abcs:
        text = "\n\n".join(p.read_text(errors="replace") for p in abcs)
        if len(text) > 100:
            return True, text
    stderr = result.stderr[-500:] if result.stderr else result.stdout[-500:]
    return False, stderr

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["P0", "P1", "both"], default="both")
    args = ap.parse_args()

    mappings = load_all_mappings()

    # Find all pNNN.xml files in scan dir
    xml_files = sorted(SCAN_DIR.glob("p*.xml"))
    print(f"Found {len(xml_files)} uploaded XML files")

    results = []
    ok_count = 0
    fail_count = 0
    skip_count = 0

    for xml_path in xml_files:
        pnnn = xml_path.name
        short_pdf = pnnn.replace(".xml", ".pdf")
        composer, work_id, batch, orig = pnnn_to_pdf(short_pdf, mappings)
        out_abc = OUT_DIR / f"{composer}__{work_id}.abc"

        # Check if already done (file exists and non-trivial)
        if out_abc.exists() and out_abc.stat().st_size > 100:
            print(f"SKIP  {pnnn:12} -> {composer}/{work_id} ({batch})")
            skip_count += 1
            results.append({"pnnn": pnnn, "composer": composer, "work_id": work_id,
                            "batch": batch, "status": "SKIP", "orig": orig})
            continue

        work_tmp = TMP / f"{composer}__{work_id}"
        if work_tmp.exists():
            import shutil; shutil.rmtree(work_tmp)
        work_tmp.mkdir(parents=True)

        success, content = convert_xml_to_abc(str(xml_path), work_tmp)

        if success:
            out_abc.write_text(content)
            print(f"OK    {pnnn:12} -> {composer}/{work_id} ({batch})  {len(content)} chars")
            ok_count += 1
            results.append({"pnnn": pnnn, "composer": composer, "work_id": work_id,
                            "batch": batch, "status": "OK", "chars": len(content), "orig": orig})
        else:
            print(f"FAIL  {pnnn:12} -> {composer}/{work_id} ({batch})  {content[:200]}")
            fail_count += 1
            results.append({"pnnn": pnnn, "composer": composer, "work_id": work_id,
                            "batch": batch, "status": "FAIL", "error": str(content)[:500], "orig": orig})

    # Summary
    print(f"\n=== Summary ===")
    print(f"OK: {ok_count}, FAIL: {fail_count}, SKIP: {skip_count}, Total: {len(xml_files)}")
    print(f"Output: {OUT_DIR}")

    # Save log
    log_file = OUT_DIR / "_manual_convert_log.json"
    log_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # List missing
    all_pnnns = set(mappings.keys())
    present = {f.name.replace(".xml", ".pdf") for f in xml_files}
    missing = sorted(all_pnnns - present)
    if missing:
        print(f"\n=== Missing ({len(missing)}) ===")
        for m in missing:
            comp, work, batch, orig = pnnn_to_pdf(m, mappings)
            print(f"  {m:12} -> {comp}/{work} ({batch})")


if __name__ == "__main__":
    main()
