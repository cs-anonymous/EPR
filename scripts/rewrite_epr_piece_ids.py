#!/usr/bin/env python3
"""Rewrite legacy EPR piece_id values to full performance piece IDs.

Older EPR JSONL files stored only metadata.performance_id. That identifier is
not globally unique across works, so split filtering by it can leak examples
across train/validation/test. This script rewrites measure_epr and phrase_epr
records to the same full path-like piece_id used by performance-language data.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_sft_data import AlignedABCXParser, MetadataReader, performance_piece_id


EPR_FILES = ["measure_epr.jsonl", "phrase_epr.jsonl"]


def score_aligned_path(score_abcx_path: str) -> str:
    path = str(score_abcx_path)
    if path.startswith("PianoCoRe/score/"):
        path = path[len("PianoCoRe/score/"):]
        path = path[: -len("/score.abcx")] if path.endswith("/score.abcx") else path
        return f"PianoCoRe/aligned/{path}/score_aligned.abcx"
    return path


def build_mapping(metadata_path: str, base_dir: str) -> dict:
    reader = MetadataReader(metadata_path)
    rows = reader.get_core_s_data(star=True)
    rows = rows[
        rows["performance_tsv_path"].notna()
        & rows["score_abcx_path"].notna()
    ].copy()

    by_perf = defaultdict(list)
    for row in rows.itertuples(index=False):
        by_perf[str(row.performance_id)].append(row)

    mapping = {}
    base = Path(base_dir)
    header_cache = {}
    for perf_id, candidates in tqdm(by_perf.items(), desc="Build EPR piece_id map"):
        full_ids = {
            performance_piece_id(row.performance_tsv_path)
            for row in candidates
        }
        if len(full_ids) == 1:
            mapping[(perf_id, None)] = next(iter(full_ids))
            continue

        for row in candidates:
            full_id = performance_piece_id(row.performance_tsv_path)
            score_path = score_aligned_path(row.score_abcx_path)
            if score_path not in header_cache:
                parsed = AlignedABCXParser.parse_aligned_abcx(str(base / score_path))
                header_cache[score_path] = parsed["header"]
            mapping[(perf_id, header_cache[score_path])] = full_id

    return mapping


def rewrite_file(path: Path, mapping: dict) -> tuple[int, int, int]:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    total = 0
    rewritten = 0
    unresolved = 0

    with path.open("r", encoding="utf-8") as fin, tmp_path.open("w", encoding="utf-8") as fout:
        for line in tqdm(fin, desc=f"Rewrite {path.name}"):
            total += 1
            sample = json.loads(line)
            old_piece_id = sample.get("piece_id", "")

            new_piece_id = None
            if "/" not in old_piece_id:
                new_piece_id = mapping.get((old_piece_id, None))
                if new_piece_id is None:
                    new_piece_id = mapping.get((old_piece_id, sample.get("score_header")))

            if new_piece_id:
                sample["piece_id"] = new_piece_id
                fout.write(json.dumps(sample, ensure_ascii=False) + "\n")
                rewritten += 1
            else:
                fout.write(line)
                if "/" not in old_piece_id:
                    unresolved += 1

    os.replace(tmp_path, path)
    return total, rewritten, unresolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", default="PianoCoRe/metadata.csv")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--input-dir", default="sft_data/core-s")
    args = parser.parse_args()

    mapping = build_mapping(args.metadata, args.base_dir)
    input_dir = Path(args.input_dir)
    for file_name in EPR_FILES:
        total, rewritten, unresolved = rewrite_file(input_dir / file_name, mapping)
        print(
            f"{file_name}: total={total:,}, rewritten={rewritten:,}, "
            f"unresolved_legacy_ids={unresolved:,}"
        )


if __name__ == "__main__":
    main()
