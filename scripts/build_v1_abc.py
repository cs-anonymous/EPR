#!/usr/bin/env python3
"""Convert all maestro_score_v1 scores to ABC.

Output: data/maestro_score_v1_abc/<composer>/<work_id>.abc
For multi-tune outputs (e.g. multi-movement collections), xml2abc may write
several tunes into a single .abc file; we keep one .abc per work.

.ly inputs are converted to MusicXML first via music21, then to ABC.
"""
import json, re, subprocess, shutil, sys, traceback, zipfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT     = Path("/home/sy/2026/Music/EPR")
V1       = ROOT/"data/maestro_score_v1/works"
OUT      = ROOT/"data/maestro_score_v1_abc"
XML2ABC  = ROOT/"xml2abc/xml2abc.py"
LOG      = ROOT/"data/maestro_score_v1_abc/_build_log.json"
TMP      = Path("/tmp/v1_abc_tmp")

OUT.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)

# Strip char refs that are invalid in XML 1.0:
#   - control chars (0x00-0x08, 0x0B-0x0C, 0x0E-0x1F)
#   - surrogates (0xD800-0xDFFF) — appear in OMR-corrupted <text>
#   - non-characters (0xFFFE/0xFFFF, plane FDD0-FDEF)
INVALID_CHAR_REF = re.compile(
    r"&#x?(?:[dD][89aAbBcCdDeEfF][0-9a-fA-F]{2}"     # surrogates &#xD800-&#xDFFF (hex)
    r"|[fF][fF][fF][eEfF]"                            # &#xFFFE/&#xFFFF
    r"|[fF][dD][dD][0-9a-fA-F]"                       # FDD0-FDDF range subset
    r");"
)

def sanitize_xml_file(src: Path, dst: Path) -> bool:
    """Copy src→dst stripping invalid char refs. Returns True if any change made."""
    text = src.read_text(encoding="utf-8", errors="replace")
    cleaned = INVALID_CHAR_REF.sub("", text)
    dst.write_text(cleaned, encoding="utf-8")
    return cleaned != text

def find_scores():
    items = []
    for composer in sorted(V1.iterdir()):
        if not composer.is_dir(): continue
        for work in sorted(composer.iterdir()):
            if not work.is_dir(): continue
            scores = [p for p in work.iterdir()
                      if p.is_file() and p.name.startswith("score.")
                      and p.suffix.lower() in (".musicxml", ".mxl", ".xml", ".ly", ".krn")]
            if scores:
                items.append((composer.name, work.name, scores[0]))
    return items

def ly_to_musicxml(ly_path: Path, out_dir: Path) -> Path | None:
    """Convert .ly to MusicXML via music21."""
    out = out_dir / (ly_path.stem + ".converted.musicxml")
    code = (
        "import sys; from music21 import converter;"
        f"s = converter.parse(r'{ly_path}');"
        f"s.write('musicxml', fp=r'{out}')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode == 0 and out.exists() and out.stat().st_size > 200:
        return out
    return None

def convert_one(args):
    composer, work_id, score = args
    out_composer = OUT / composer
    out_composer.mkdir(parents=True, exist_ok=True)
    out_abc = out_composer / f"{work_id}.abc"

    # Skip if already done and non-trivial
    if out_abc.exists() and out_abc.stat().st_size > 200:
        return composer, work_id, "SKIP", str(score), str(out_abc), 0

    work_tmp = TMP / f"{composer}__{work_id}"
    if work_tmp.exists(): shutil.rmtree(work_tmp)
    work_tmp.mkdir(parents=True)

    src = score
    if score.suffix.lower() == ".ly":
        converted = ly_to_musicxml(score, work_tmp)
        if converted is None:
            return composer, work_id, "FAIL_LY", str(score), "", 0
        src = converted
    elif score.suffix.lower() == ".krn":
        return composer, work_id, "FAIL_KRN_UNSUPPORTED", str(score), "", 0
    elif score.suffix.lower() in (".xml", ".musicxml"):
        # Sanitize invalid XML char refs (surrogates, control chars) before xml2abc
        cleaned = work_tmp / ("sanitized" + score.suffix)
        if sanitize_xml_file(score, cleaned):
            src = cleaned

    try:
        r = subprocess.run(
            [sys.executable, str(XML2ABC), str(src), "-o", str(work_tmp)],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return composer, work_id, "TIMEOUT", str(score), "", 0

    abcs = sorted(work_tmp.glob("*.abc"))
    abcs = [p for p in abcs if p.stat().st_size > 100]
    if not abcs:
        return composer, work_id, f"FAIL_NO_ABC", str(score), (r.stderr[-300:] if r.stderr else r.stdout[-300:]), 0

    # Concatenate all .abc into one work file (multi-tune ABC supports this natively)
    parts = []
    for p in abcs:
        parts.append(p.read_text(errors="replace"))
    out_abc.write_text("\n\n".join(parts))

    return composer, work_id, "OK", str(score), str(out_abc), len(abcs)

def main():
    items = find_scores()
    print(f"Found {len(items)} works to convert")

    results = []
    workers = 16
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(convert_one, it): it for it in items}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                it = futs[fut]
                res = (it[0], it[1], "EXCEPTION", str(it[2]), str(e), 0)
            results.append(res)
            comp, wid, status, *_ = res
            print(f"[{i}/{len(items)}] {status:20} {comp}/{wid}")

    # Save log
    LOG.write_text(json.dumps([
        {"composer": c, "work_id": w, "status": s, "src": src, "info": info, "tunes": n}
        for (c, w, s, src, info, n) in results
    ], indent=2, ensure_ascii=False))

    # Summary
    from collections import Counter
    stats = Counter(r[2] for r in results)
    print("\n=== Summary ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:25} {v}")

    ok = stats.get("OK", 0) + stats.get("SKIP", 0)
    print(f"\nTotal usable ABC: {ok}/{len(items)}")
    print(f"Output: {OUT}")
    print(f"Log:    {LOG}")

if __name__ == "__main__":
    main()
