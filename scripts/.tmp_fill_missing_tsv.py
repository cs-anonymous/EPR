from __future__ import annotations

import csv
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METADATA = ROOT / "PianoCoRe" / "metadata.csv"
RAW_ROOT = ROOT / "PianoCoRe" / "raw"
OUTPUT_ROOT = ROOT / "PianoCoRe" / "orphan_tsv"
MIDI_TSV = ROOT / "wave-roll" / "midi_tsv.py"
WORKERS = 16


def convert(task: tuple[str, str]) -> tuple[bool, str]:
    perf_mid_str, out_tsv_str = task
    perf_mid = Path(perf_mid_str)
    out_tsv = Path(out_tsv_str)

    if out_tsv.exists() and out_tsv.stat().st_size > 0:
        return True, "exists"

    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [os.sys.executable, str(MIDI_TSV), "midi2tsv", str(perf_mid), "--out", str(out_tsv)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()

    return out_tsv.exists() and out_tsv.stat().st_size > 0, "ok"


def main() -> None:
    missing: list[tuple[str, str]] = []
    source_missing = 0

    with METADATA.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("performance_tsv_path"):
                continue
            perf_rel = row.get("performance_midi_path", "")
            if not perf_rel:
                continue
            perf_mid = RAW_ROOT / perf_rel
            if not perf_mid.exists():
                source_missing += 1
                continue
            out_tsv = OUTPUT_ROOT / Path(perf_rel).parent / f"{Path(perf_rel).name}.tsv"
            missing.append((str(perf_mid), str(out_tsv)))

    print(f"queued={len(missing)}")
    print(f"source_missing={source_missing}")

    success = 0
    failed = 0
    failures: list[str] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for ok, detail in pool.map(convert, missing, chunksize=4):
            if ok:
                success += 1
            else:
                failed += 1
                if len(failures) < 20:
                    failures.append(detail)

    print(f"success={success}")
    print(f"failed={failed}")
    if failures:
        print("failure_samples=")
        for item in failures:
            print(item)

    tmp = METADATA.with_suffix(".csv.tmp")
    filled = 0
    empty = 0
    with METADATA.open(newline="", encoding="utf-8") as src, tmp.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        fieldnames = list(reader.fieldnames or [])
        if "performance_tsv_path" not in fieldnames:
            fieldnames.append("performance_tsv_path")
        writer = csv.DictWriter(dst, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in reader:
            current = row.get("performance_tsv_path", "")
            if not current:
                perf_rel = row.get("performance_midi_path", "")
                if perf_rel:
                    candidate = OUTPUT_ROOT / Path(perf_rel).parent / f"{Path(perf_rel).name}.tsv"
                    if candidate.exists() and candidate.stat().st_size > 0:
                        current = str(candidate.relative_to(ROOT))
            row["performance_tsv_path"] = current
            if current:
                filled += 1
            else:
                empty += 1
            writer.writerow(row)

    shutil.move(tmp, METADATA)
    print(f"metadata_filled={filled}")
    print(f"metadata_empty={empty}")


if __name__ == "__main__":
    main()
