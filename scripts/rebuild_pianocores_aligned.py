#!/usr/bin/env python3
"""Rebuild PianoCoReS/aligned from PianoCoRe/aligned and metadata manifests.

Rules:
1. Copy every score-side file from PianoCoRe/aligned:
   - *.abcx
   - *.json
2. Copy performance TSV files only when the exact relative TSV path appears in
   PianoCoReS/metadata.csv.
3. Keep score-only piece directories even if they have no performance rows in
   PianoCoReS/metadata.csv.
4. Generate PianoCoReS/score_metadata.csv covering:
   - all scores under PianoCoReS/aligned
   - all scores from PianoCoReS/unpaired_abcx
"""

from __future__ import annotations

import argparse
import csv
import shutil
from dataclasses import dataclass
from pathlib import Path


SCORE_SUFFIXES = {".abcx", ".json"}


@dataclass(frozen=True)
class ScoreRow:
    source: str
    split: str
    composer: str
    composition: str
    movement: str
    score_dataset: str
    score_id: str
    score_xml_path: str
    score_midi_path: str
    refined_score_midi_path: str
    score_abcx_path: str
    score_aligned_path: str
    score_aligned_mini_path: str
    score_json_path: str
    score_json_mini_path: str
    original_path: str


def rel_str(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_allowed_tsvs(metadata_csv: Path, aligned_root: Path) -> set[str]:
    allowed: set[str] = set()
    with metadata_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value = (row.get("performance_tsv_path") or "").strip()
            if not value:
                continue
            path = Path(value)
            if value.startswith("PianoCoReS/aligned/"):
                rel = value[len("PianoCoReS/aligned/"):]
            elif "aligned" in path.parts:
                idx = path.parts.index("aligned")
                rel = Path(*path.parts[idx + 1 :]).as_posix()
            else:
                rel = path.name
            allowed.add(rel)
    return allowed


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def copy_tree(
    source_root: Path,
    dest_root: Path,
    allowed_tsvs: set[str],
) -> dict[str, int]:
    stats = {
        "score_files_copied": 0,
        "tsv_files_copied": 0,
        "tsv_files_skipped": 0,
    }

    for src in sorted(source_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(source_root)
        dst = dest_root / rel

        if src.suffix in SCORE_SUFFIXES:
            ensure_parent(dst)
            shutil.copy2(src, dst)
            stats["score_files_copied"] += 1
            continue

        if src.suffix == ".tsv":
            rel_key = rel.as_posix()
            if rel_key in allowed_tsvs:
                ensure_parent(dst)
                shutil.copy2(src, dst)
                stats["tsv_files_copied"] += 1
            else:
                stats["tsv_files_skipped"] += 1

    return stats


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def load_paired_score_index(metadata_csv: Path) -> dict[str, dict[str, str]]:
    by_score: dict[str, dict[str, str]] = {}
    with metadata_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            score_abcx_path = normalize_text(row.get("score_abcx_path"))
            if not score_abcx_path:
                continue
            score_rel = score_abcx_path
            if score_rel.startswith("PianoCoReS/aligned/"):
                score_rel = score_rel[len("PianoCoReS/aligned/"):]
            by_score.setdefault(score_rel, row)
    return by_score


def build_paired_score_rows(
    metadata_csv: Path,
    aligned_root: Path,
) -> list[ScoreRow]:
    by_score = load_paired_score_index(metadata_csv)
    rows: list[ScoreRow] = []

    for score_path in sorted(aligned_root.rglob("score.abcx")):
        score_rel = score_path.relative_to(aligned_root).as_posix()
        row = by_score.get(score_rel, {})
        score_aligned = score_path.with_name("score_aligned.abcx")
        score_aligned_mini = score_path.with_name("score_aligned_mini.abcx")
        score_json = score_path.with_name("score_structure.json")
        score_json_mini = score_path.with_name("score_structure_mini.json")

        rel_parts = score_path.relative_to(aligned_root).parts[:-1]
        composer = normalize_text(row.get("composer")) if row else ""
        composition = normalize_text(row.get("composition")) if row else ""
        movement = normalize_text(row.get("movement")) if row else ""

        if not composer and rel_parts:
            composer = rel_parts[0]
        if not composition and len(rel_parts) >= 2:
            composition = rel_parts[1]
        if not movement and len(rel_parts) >= 3:
            movement = "/".join(rel_parts[2:])

        rows.append(
            ScoreRow(
                source="paired",
                split=normalize_text(row.get("split")) if row else "",
                composer=composer,
                composition=composition,
                movement=movement,
                score_dataset=normalize_text(row.get("score_dataset")) if row else "",
                score_id=normalize_text(row.get("score_id")) if row else "",
                score_xml_path=normalize_text(row.get("score_xml_path")) if row else "",
                score_midi_path=normalize_text(row.get("score_midi_path")) if row else "",
                refined_score_midi_path=normalize_text(row.get("refined_score_midi_path")) if row else "",
                score_abcx_path=f"PianoCoReS/aligned/{score_rel}",
                score_aligned_path=(
                    f"PianoCoReS/aligned/{score_aligned.relative_to(aligned_root).as_posix()}"
                    if score_aligned.exists()
                    else ""
                ),
                score_aligned_mini_path=(
                    f"PianoCoReS/aligned/{score_aligned_mini.relative_to(aligned_root).as_posix()}"
                    if score_aligned_mini.exists()
                    else ""
                ),
                score_json_path=(
                    f"PianoCoReS/aligned/{score_json.relative_to(aligned_root).as_posix()}"
                    if score_json.exists()
                    else ""
                ),
                score_json_mini_path=(
                    f"PianoCoReS/aligned/{score_json_mini.relative_to(aligned_root).as_posix()}"
                    if score_json_mini.exists()
                    else ""
                ),
                original_path=normalize_text(row.get("score_xml_path")) if row else "",
            )
        )
    return rows


def build_unpaired_score_rows(
    unpaired_metadata_csv: Path,
) -> list[ScoreRow]:
    rows: list[ScoreRow] = []
    with unpaired_metadata_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            abcx_path = normalize_text(row.get("abcx_path"))
            aligned_path = normalize_text(row.get("abcx_aligned_path"))
            rows.append(
                ScoreRow(
                    source=normalize_text(row.get("source")) or "unpaired",
                    split=normalize_text(row.get("split")),
                    composer=normalize_text(row.get("composer")),
                    composition=normalize_text(row.get("composition")),
                    movement=normalize_text(row.get("movement")),
                    score_dataset=normalize_text(row.get("source")),
                    score_id=normalize_text(row.get("filename")),
                    score_xml_path="",
                score_midi_path="",
                refined_score_midi_path="",
                score_abcx_path=abcx_path,
                score_aligned_path=aligned_path,
                score_aligned_mini_path="",
                score_json_path="",
                score_json_mini_path="",
                original_path=normalize_text(row.get("original_path")),
            )
        )
    return rows


def write_score_metadata(output_csv: Path, rows: list[ScoreRow]) -> None:
    ensure_parent(output_csv)
    fieldnames = [
        "source",
        "split",
        "composer",
        "composition",
        "movement",
        "score_dataset",
        "score_id",
        "score_xml_path",
        "score_midi_path",
        "refined_score_midi_path",
        "score_abcx_path",
        "score_aligned_path",
        "score_aligned_mini_path",
        "score_json_path",
        "score_json_mini_path",
        "original_path",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "source": row.source,
                    "split": row.split,
                    "composer": row.composer,
                    "composition": row.composition,
                    "movement": row.movement,
                    "score_dataset": row.score_dataset,
                    "score_id": row.score_id,
                    "score_xml_path": row.score_xml_path,
                    "score_midi_path": row.score_midi_path,
                    "refined_score_midi_path": row.refined_score_midi_path,
                    "score_abcx_path": row.score_abcx_path,
                    "score_aligned_path": row.score_aligned_path,
                    "score_aligned_mini_path": row.score_aligned_mini_path,
                    "score_json_path": row.score_json_path,
                    "score_json_mini_path": row.score_json_mini_path,
                    "original_path": row.original_path,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-aligned",
        type=Path,
        default=Path("PianoCoRe/aligned"),
        help="Source aligned directory",
    )
    parser.add_argument(
        "--dest-aligned",
        type=Path,
        default=Path("PianoCoReS/aligned"),
        help="Destination aligned directory",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("PianoCoReS/metadata.csv"),
        help="Paired metadata CSV used as TSV whitelist",
    )
    parser.add_argument(
        "--unpaired-metadata",
        type=Path,
        default=Path("PianoCoReS/unpaired_metadata.csv"),
        help="Unpaired score metadata CSV",
    )
    parser.add_argument(
        "--score-metadata-out",
        type=Path,
        default=Path("PianoCoReS/score_metadata.csv"),
        help="Output CSV for all score metadata",
    )
    args = parser.parse_args()

    allowed_tsvs = load_allowed_tsvs(args.metadata, args.dest_aligned)

    safe_rmtree(args.dest_aligned)
    args.dest_aligned.mkdir(parents=True, exist_ok=True)

    stats = copy_tree(args.source_aligned, args.dest_aligned, allowed_tsvs)

    paired_rows = build_paired_score_rows(args.metadata, args.dest_aligned)
    unpaired_rows = build_unpaired_score_rows(args.unpaired_metadata)
    write_score_metadata(args.score_metadata_out, paired_rows + unpaired_rows)

    print(f"Rebuilt {args.dest_aligned}")
    print(f"  Score files copied: {stats['score_files_copied']}")
    print(f"  TSV files copied:   {stats['tsv_files_copied']}")
    print(f"  TSV files skipped:  {stats['tsv_files_skipped']}")
    print(f"  Paired scores:      {len(paired_rows)}")
    print(f"  Unpaired scores:    {len(unpaired_rows)}")
    print(f"  score_metadata.csv: {args.score_metadata_out}")


if __name__ == "__main__":
    main()
