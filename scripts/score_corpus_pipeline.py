#!/usr/bin/env python3
"""Prepare external score corpora for SPIRE score-language training.

This script intentionally keeps the heavy conversion step separate from
`xml_to_abcx.py`. It builds manifests, filters PianoCoRe duplicates, and
extracts MusicXML/MXL files that can be converted directly.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCORE_ROOT = ROOT / "data" / "score"
DEFAULT_WORK_ROOT = ROOT / "data" / "score_work"
DEFAULT_PROCESSED_ROOT = ROOT / "data" / "score_processed"
PIANOCORE_METADATA = ROOT / "PianoCoRe" / "metadata.csv"


PIANO_RE = re.compile(
    r"\b(piano|pianoforte|fortepiano|klavier|clavier|keyboard|harpsichord|clavecin)\b",
    re.I,
)
CLASSICAL_RE = re.compile(
    r"\b(bach|beethoven|mozart|haydn|chopin|liszt|schubert|schumann|brahms|"
    r"debussy|ravel|rachmaninoff|scriabin|scarlatti|clementi|czerny|alkan|"
    r"mendelssohn|grieg|satie|prokofiev|rameau|purcell|faur|faure)\b",
    re.I,
)


def read_pianocore_pdmx_ids(path: Path = PIANOCORE_METADATA) -> set[str]:
    used: set[str] = set()
    if not path.exists():
        return used
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            score_id = row.get("score_id", "")
            if score_id.startswith("PDMX_"):
                used.add(score_id.removeprefix("PDMX_"))
    return used


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def safe_int(value: str | None, default: int = 0) -> int:
    try:
        if value is None or value == "" or value.lower() == "nan":
            return default
        return int(float(value))
    except Exception:
        return default


def pdmx_id_from_metadata_path(path: str) -> str:
    return Path(path).stem


def build_pdmx_manifest(score_root: Path, work_root: Path, max_items: int | None) -> Path:
    pdmx_csv = score_root / "PDMX" / "PDMX.csv"
    if not pdmx_csv.exists():
        raise SystemExit(f"Missing {pdmx_csv}")

    used_pdmx = read_pianocore_pdmx_ids()
    out_dir = work_root / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pdmx_piano_candidates.jsonl"

    selected = 0
    seen_best_paths: set[str] = set()
    with pdmx_csv.open(newline="", encoding="utf-8") as f, out_path.open("w", encoding="utf-8") as out:
        reader = csv.DictReader(f)
        for row in reader:
            metadata_id = pdmx_id_from_metadata_path(row.get("metadata", ""))
            if not metadata_id or metadata_id in used_pdmx:
                continue

            text = " ".join(
                row.get(k, "") or ""
                for k in ("title", "song_name", "subtitle", "artist_name", "composer_name", "genres", "groups", "tags")
            )
            piano_like = bool(PIANO_RE.search(text))
            classical_like = bool(CLASSICAL_RE.search(text)) or "classical" in (row.get("genres", "") or "").lower()
            if not piano_like:
                continue

            if not truthy(row.get("subset:deduplicated")):
                continue
            if not truthy(row.get("subset:all_valid")):
                continue

            n_tracks = safe_int(row.get("n_tracks"))
            n_notes = safe_int(row.get("n_notes"))
            bars = safe_int(row.get("song_length.bars"))
            if not (1 <= n_tracks <= 4 and 40 <= n_notes <= 20000 and 4 <= bars <= 1200):
                continue

            # Prefer public-domain/classical records, but do not require the
            # conservative license-conflict flag because PDMX is already a
            # public-domain score corpus and that flag is noisy in practice.
            score = 0
            score += 4 if classical_like else 0
            score += 2 if (row.get("license", "") or "").lower() in {"publicdomain", "cc0"} else 0
            score += 1 if not truthy(row.get("has_lyrics")) else 0
            score += min(safe_int(row.get("n_ratings")), 10)
            try:
                score += float(row.get("rating") or 0)
            except Exception:
                pass

            best_path = row.get("best_unique_arrangement") or row.get("best_arrangement") or row.get("best_path") or row.get("path", "")
            if best_path in seen_best_paths:
                continue
            seen_best_paths.add(best_path)

            item = {
                "source": "PDMX",
                "pdmx_id": metadata_id,
                "mxl": row.get("mxl", "").lstrip("./"),
                "metadata": row.get("metadata", "").lstrip("./"),
                "title": row.get("title") or row.get("song_name") or "",
                "composer": row.get("composer_name") or row.get("artist_name") or "",
                "n_tracks": n_tracks,
                "n_notes": n_notes,
                "bars": bars,
                "license": row.get("license", ""),
                "classical_like": classical_like,
                "score": score,
            }
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            selected += 1
            if max_items is not None and selected >= max_items:
                break

    return out_path


def load_manifest(path: Path) -> list[dict]:
    items = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def extract_pdmx_mxl(score_root: Path, work_root: Path, max_items: int | None) -> Path:
    manifest = work_root / "manifests" / "pdmx_piano_candidates.jsonl"
    if not manifest.exists():
        manifest = build_pdmx_manifest(score_root, work_root, max_items)
    items = load_manifest(manifest)
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    if max_items is not None:
        items = items[:max_items]

    wanted = {item["mxl"]: item for item in items if item.get("mxl")}
    tar_path = score_root / "PDMX" / "mxl.tar.gz"
    if not tar_path.exists():
        raise SystemExit(f"Missing {tar_path}")

    out_root = score_root / "PDMX" / "selected_mxl"
    out_root.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf:
            name = member.name.lstrip("./")
            item = wanted.get(name)
            if not item or not member.isfile():
                continue
            dest = out_root / item["pdmx_id"] / Path(name).name
            if dest.exists():
                extracted += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            with dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            meta = dest.with_suffix(".json")
            meta.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            extracted += 1

    summary = work_root / "manifests" / "pdmx_extract_summary.json"
    summary.write_text(
        json.dumps({"requested": len(items), "extracted": extracted, "out_root": str(out_root)}, indent=2),
        encoding="utf-8",
    )
    return summary


def inventory(score_root: Path, processed_root: Path, work_root: Path) -> Path:
    rows = []
    for name, root, patterns, status in [
        ("PDMX", score_root / "PDMX", ["*.mxl"], "musicxml_ready"),
        ("OpenScore_Lieder", score_root / "OpenScore_Lieder", ["*.mxl"], "musicxml_ready"),
        ("MutopiaProject", score_root / "MutopiaProject", ["*.ly"], "piano_lilypond_manifest_ready"),
        ("DCMLab", score_root / "DCMLab", ["*.mscx"], "musescore_exported_to_mxl"),
        ("KernScores_sonatas", score_root / "humdrum-data" / "sonatas", ["*.krn"], "music21_exported_to_musicxml"),
    ]:
        count = 0
        for pat in patterns:
            count += sum(1 for _ in root.rglob(pat)) if root.exists() else 0
        processed = sum(1 for _ in (processed_root / name).rglob("*.abcx")) if (processed_root / name).exists() else 0
        rows.append({"dataset": name, "raw_count": count, "processed_abcx": processed, "status": status})

    out = work_root / "manifests" / "score_inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return out


def processed_path_for(src_root: Path, xml_path: Path, out_root: Path, suffix: str = "abcx") -> Path:
    rel = xml_path.parent.relative_to(src_root)
    flat_name = str(rel).replace("/", "_")
    sibling_count = sum(1 for p in xml_path.parent.glob(f"*{xml_path.suffix}") if p.is_file())
    if flat_name in {"", "."}:
        flat_name = xml_path.stem
    elif sibling_count > 1:
        flat_name = f"{flat_name}_{xml_path.stem}"
    else:
        # Backward-compatible with the original one-score-per-directory layout
        # used by PDMX/OpenScore exports.
        flat_name = flat_name
    return out_root / rel / f"{flat_name}.{suffix}"


def convert_mxl_files(
    src_root: Path,
    out_root: Path,
    work_root: Path,
    *,
    pattern: str,
    timeout_s: int,
    limit: int | None,
    no_validate: bool,
    drop_harmony: bool,
    jobs: int,
) -> Path:
    files = sorted(src_root.rglob(pattern))
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit(f"No files matching {pattern!r} under {src_root}")

    log_dir = work_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    dataset_name = out_root.name
    log_path = log_dir / f"{dataset_name}_convert_mxl.jsonl"

    skipped_paths: set[Path] = set()
    pending: list[tuple[int, Path, Path]] = []
    for i, xml_path in enumerate(files, 1):
        out_path = processed_path_for(src_root, xml_path, out_root)
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped_paths.add(xml_path)
        else:
            pending.append((i, xml_path, out_path))

    ok = 0
    failed = 0
    timed_out = 0
    script = ROOT / "xml_to_abcx.py"

    def _convert_one(task: tuple[int, Path, Path]) -> dict:
        i, xml_path, out_path = task
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["python3", str(script), str(xml_path), "-o", str(out_path)]
        if no_validate:
            cmd.append("--no-validate")
        if drop_harmony:
            cmd.append("--drop-harmony")
        record = {
            "index": i,
            "source": str(xml_path),
            "output": str(out_path),
            "status": None,
            "returncode": None,
            "stderr_tail": "",
        }
        try:
            proc = subprocess.run(
                cmd,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            record["status"] = "timeout"
            record["stderr_tail"] = (e.stderr or "")[-1000:] if isinstance(e.stderr, str) else ""
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
            return record

        record["returncode"] = proc.returncode
        record["stderr_tail"] = proc.stderr[-1000:]
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            record["status"] = "ok"
        else:
            record["status"] = "failed"
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
        return record

    processed = len(skipped_paths)
    skipped = len(skipped_paths)
    print(
        f"Found {len(files)} files; skipped_existing={skipped}; "
        f"pending={len(pending)}; jobs={jobs}; timeout_s={timeout_s}",
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as log:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futures = [ex.submit(_convert_one, task) for task in pending]
            for fut in as_completed(futures):
                record = fut.result()
                status = record["status"]
                if status == "ok":
                    ok += 1
                elif status == "timeout":
                    timed_out += 1
                else:
                    failed += 1
                processed += 1
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()

                if processed % 20 == 0 or processed == len(files):
                    print(
                        f"[{processed}/{len(files)}] ok={ok} skipped={skipped} "
                        f"failed={failed} timeout={timed_out}",
                        flush=True,
                    )

    summary = work_root / "manifests" / f"{dataset_name}_convert_mxl_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        json.dumps(
            {
                "source_root": str(src_root),
                "out_root": str(out_root),
                "pattern": pattern,
                "total": len(files),
                "ok": ok,
                "skipped_existing": skipped,
                "failed": failed,
                "timed_out": timed_out,
                "timeout_s": timeout_s,
                "jobs": jobs,
                "log": str(log_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(summary)
    return summary


def export_with_musescore(
    src_root: Path,
    out_root: Path,
    work_root: Path,
    *,
    pattern: str,
    timeout_s: int,
    limit: int | None,
    jobs: int,
    suffix: str,
) -> Path:
    files = sorted(src_root.rglob(pattern))
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit(f"No files matching {pattern!r} under {src_root}")

    log_dir = work_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    dataset_name = out_root.name
    log_path = log_dir / f"{dataset_name}_musescore_export.jsonl"

    tasks: list[tuple[int, Path, Path]] = []
    skipped = 0
    for i, src_path in enumerate(files, 1):
        rel = src_path.relative_to(src_root)
        out_path = (out_root / rel).with_suffix(suffix)
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1
        else:
            tasks.append((i, src_path, out_path))

    def _export_one(task: tuple[int, Path, Path]) -> dict:
        i, src_path, out_path = task
        out_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        record = {
            "index": i,
            "source": str(src_path),
            "output": str(out_path),
            "status": None,
            "returncode": None,
            "stderr_tail": "",
        }
        try:
            proc = subprocess.run(
                ["musescore3", "-f", "-o", str(out_path), str(src_path)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            record["status"] = "timeout"
            record["stderr_tail"] = (e.stderr or "")[-1000:] if isinstance(e.stderr, str) else ""
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
            return record

        record["returncode"] = proc.returncode
        record["stderr_tail"] = proc.stderr[-1000:]
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            record["status"] = "ok"
        else:
            record["status"] = "failed"
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
        return record

    ok = failed = timed_out = 0
    processed = skipped
    print(
        f"Found {len(files)} files; skipped_existing={skipped}; "
        f"pending={len(tasks)}; jobs={jobs}; timeout_s={timeout_s}",
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as log:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futures = [ex.submit(_export_one, task) for task in tasks]
            for fut in as_completed(futures):
                record = fut.result()
                if record["status"] == "ok":
                    ok += 1
                elif record["status"] == "timeout":
                    timed_out += 1
                else:
                    failed += 1
                processed += 1
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                if processed % 20 == 0 or processed == len(files):
                    print(
                        f"[{processed}/{len(files)}] ok={ok} skipped={skipped} "
                        f"failed={failed} timeout={timed_out}",
                        flush=True,
                    )

    summary = work_root / "manifests" / f"{dataset_name}_musescore_export_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        json.dumps(
            {
                "source_root": str(src_root),
                "out_root": str(out_root),
                "pattern": pattern,
                "total": len(files),
                "ok": ok,
                "skipped_existing": skipped,
                "failed": failed,
                "timed_out": timed_out,
                "timeout_s": timeout_s,
                "jobs": jobs,
                "log": str(log_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(summary)
    return summary


def export_kern_with_music21(
    src_root: Path,
    out_root: Path,
    work_root: Path,
    *,
    pattern: str,
    timeout_s: int,
    limit: int | None,
    jobs: int,
) -> Path:
    files = sorted(src_root.rglob(pattern))
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit(f"No files matching {pattern!r} under {src_root}")

    log_dir = work_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    dataset_name = out_root.name
    log_path = log_dir / f"{dataset_name}_kern_export.jsonl"

    tasks: list[tuple[int, Path, Path]] = []
    skipped = 0
    for i, src_path in enumerate(files, 1):
        rel = src_path.relative_to(src_root)
        out_path = (out_root / rel).with_suffix(".musicxml")
        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1
        else:
            tasks.append((i, src_path, out_path))

    code = (
        "from music21 import converter; "
        "from pathlib import Path; "
        "import sys; "
        "src=Path(sys.argv[1]); out=Path(sys.argv[2]); "
        "out.parent.mkdir(parents=True, exist_ok=True); "
        "converter.parse(src).write('musicxml', fp=out)"
    )

    def _export_one(task: tuple[int, Path, Path]) -> dict:
        i, src_path, out_path = task
        out_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "index": i,
            "source": str(src_path),
            "output": str(out_path),
            "status": None,
            "returncode": None,
            "stderr_tail": "",
        }
        try:
            proc = subprocess.run(
                ["python3", "-c", code, str(src_path), str(out_path)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            record["status"] = "timeout"
            record["stderr_tail"] = (e.stderr or "")[-1000:] if isinstance(e.stderr, str) else ""
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
            return record

        record["returncode"] = proc.returncode
        record["stderr_tail"] = proc.stderr[-1000:]
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            record["status"] = "ok"
        else:
            record["status"] = "failed"
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink()
        return record

    ok = failed = timed_out = 0
    processed = skipped
    print(
        f"Found {len(files)} files; skipped_existing={skipped}; "
        f"pending={len(tasks)}; jobs={jobs}; timeout_s={timeout_s}",
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as log:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futures = [ex.submit(_export_one, task) for task in tasks]
            for fut in as_completed(futures):
                record = fut.result()
                if record["status"] == "ok":
                    ok += 1
                elif record["status"] == "timeout":
                    timed_out += 1
                else:
                    failed += 1
                processed += 1
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                if processed % 20 == 0 or processed == len(files):
                    print(
                        f"[{processed}/{len(files)}] ok={ok} skipped={skipped} "
                        f"failed={failed} timeout={timed_out}",
                        flush=True,
                    )

    summary = work_root / "manifests" / f"{dataset_name}_kern_export_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        json.dumps(
            {
                "source_root": str(src_root),
                "out_root": str(out_root),
                "pattern": pattern,
                "total": len(files),
                "ok": ok,
                "skipped_existing": skipped,
                "failed": failed,
                "timed_out": timed_out,
                "timeout_s": timeout_s,
                "jobs": jobs,
                "log": str(log_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build-pdmx-manifest", "extract-pdmx", "inventory", "convert-mxl", "export-musescore", "export-kern"])
    ap.add_argument("--score-root", type=Path, default=DEFAULT_SCORE_ROOT)
    ap.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    ap.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    ap.add_argument("--max-items", type=int, default=None)
    ap.add_argument("--src-root", type=Path)
    ap.add_argument("--out-root", type=Path)
    ap.add_argument("--pattern", default="*.mxl")
    ap.add_argument("--timeout-s", type=int, default=90)
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--drop-harmony", action="store_true")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--suffix", default=".mxl")
    args = ap.parse_args()

    if args.command == "build-pdmx-manifest":
        print(build_pdmx_manifest(args.score_root, args.work_root, args.max_items))
    elif args.command == "extract-pdmx":
        print(extract_pdmx_mxl(args.score_root, args.work_root, args.max_items))
    elif args.command == "inventory":
        print(inventory(args.score_root, args.processed_root, args.work_root))
    elif args.command == "convert-mxl":
        if args.src_root is None or args.out_root is None:
            raise SystemExit("convert-mxl requires --src-root and --out-root")
        print(
            convert_mxl_files(
                args.src_root.resolve(),
                args.out_root.resolve(),
                args.work_root,
                pattern=args.pattern,
                timeout_s=args.timeout_s,
                limit=args.max_items,
                no_validate=args.no_validate,
                drop_harmony=args.drop_harmony,
                jobs=args.jobs,
            )
        )
    elif args.command == "export-musescore":
        if args.src_root is None or args.out_root is None:
            raise SystemExit("export-musescore requires --src-root and --out-root")
        print(
            export_with_musescore(
                args.src_root.resolve(),
                args.out_root.resolve(),
                args.work_root,
                pattern=args.pattern,
                timeout_s=args.timeout_s,
                limit=args.max_items,
                jobs=args.jobs,
                suffix=args.suffix,
            )
        )
    elif args.command == "export-kern":
        if args.src_root is None or args.out_root is None:
            raise SystemExit("export-kern requires --src-root and --out-root")
        print(
            export_kern_with_music21(
                args.src_root.resolve(),
                args.out_root.resolve(),
                args.work_root,
                pattern=args.pattern,
                timeout_s=args.timeout_s,
                limit=args.max_items,
                jobs=args.jobs,
            )
        )


if __name__ == "__main__":
    main()
