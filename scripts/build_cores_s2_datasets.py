#!/usr/bin/env python3
"""Build CoReS S2 subsets from existing S1 datasets.

S2 policy:
  - Keep all S1 ASAP samples.
  - For every subtask, sample non-ASAP rows so that the final subtask size is
    about half of the S1 subtask size.
  - Non-ASAP sampling is balanced by piece_id/performance when possible.

The script also renames the current sampled EPR directories to *_s1 if needed:
  measure_epr_sft -> measure_epr_sft_s1
  phrase_epr_sft  -> phrase_epr_sft_s1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import Counter
from pathlib import Path

from prepare_core_s1_swift import convert_dataset


LANGUAGE_TASK_FILES = [
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
]

EPR_TASKS = {
    "measure_epr_sft": [
        "measure_epr_coldstart.jsonl",
        "measure_epr_main.jsonl",
        "measure_epr_ending.jsonl",
    ],
    "phrase_epr_sft": [
        "phrase_epr_coldstart.jsonl",
        "phrase_epr_main.jsonl",
        "phrase_epr_ending.jsonl",
    ],
}


def performance_piece_id(perf_tsv_path: str) -> str:
    path = Path(str(perf_tsv_path))
    parts = path.parts
    if "aligned" in parts:
        idx = parts.index("aligned")
        path_str = Path(*parts[idx + 1:]).as_posix()
    else:
        path_str = str(perf_tsv_path)
    if path_str.startswith("PianoCoRe_output/"):
        path_str = path_str[len("PianoCoRe_output/"):]
    elif path_str.startswith("PianoCoRe/aligned/"):
        path_str = path_str[len("PianoCoRe/aligned/"):]
    if path_str.endswith(".tsv"):
        path_str = path_str[: -len(".tsv")]
    return path_str


def load_asap_piece_ids(metadata_path: Path) -> set[str]:
    asap_ids = set()
    with metadata_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("performance_dataset") == "ASAP" or row.get("is_transcription") == "False":
                piece_id = performance_piece_id(row.get("performance_tsv_path", ""))
                if piece_id:
                    asap_ids.add(piece_id)
    return asap_ids


def stable_seed(seed: int, *parts: str) -> int:
    text = ":".join([str(seed), *parts])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def count_file(path: Path, asap_ids: set[str]) -> tuple[int, int, Counter[str]]:
    total = 0
    asap = 0
    non_asap_by_piece: Counter[str] = Counter()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            sample = json.loads(line)
            piece_id = performance_piece_id(sample.get("piece_id", ""))
            if piece_id in asap_ids:
                asap += 1
            else:
                non_asap_by_piece[piece_id] += 1
    return total, asap, non_asap_by_piece


def allocate_balanced_without_replacement(
    counts: Counter[str],
    target: int,
    rng: random.Random,
) -> dict[str, int]:
    if target <= 0 or not counts:
        return {}

    pids = list(counts)
    rng.shuffle(pids)
    target = min(target, sum(counts.values()))

    budgets = {pid: 0 for pid in pids}

    if target <= len(pids):
        for pid in pids[:target]:
            budgets[pid] = 1
        return budgets

    for pid in pids:
        budgets[pid] = 1
    remaining = target - len(pids)

    while remaining > 0:
        candidates = [pid for pid in pids if budgets[pid] < counts[pid]]
        if not candidates:
            break
        rng.shuffle(candidates)
        for pid in candidates:
            if remaining <= 0:
                break
            budgets[pid] += 1
            remaining -= 1

    return budgets


def sample_file_to_s2(
    input_path: Path,
    output_path: Path,
    asap_ids: set[str],
    seed: int,
) -> dict:
    total, asap, non_asap_by_piece = count_file(input_path, asap_ids)
    target_total = round(total * 0.5)
    target_non_asap = max(0, target_total - asap)
    rng = random.Random(stable_seed(seed, input_path.name))
    budgets = allocate_balanced_without_replacement(non_asap_by_piece, target_non_asap, rng)

    keep_positions: dict[str, set[int]] = {}
    for piece_id, count in non_asap_by_piece.items():
        budget = budgets.get(piece_id, 0)
        if budget >= count:
            keep_positions[piece_id] = set(range(count))
        elif budget > 0:
            keep_positions[piece_id] = set(rng.sample(range(count), budget))
        else:
            keep_positions[piece_id] = set()

    seen_non_asap: Counter[str] = Counter()
    output = 0
    sampled_non_asap = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            sample = json.loads(line)
            piece_id = performance_piece_id(sample.get("piece_id", ""))
            if piece_id in asap_ids:
                fout.write(line)
                output += 1
                continue

            index = seen_non_asap[piece_id]
            seen_non_asap[piece_id] += 1
            if index in keep_positions[piece_id]:
                fout.write(line)
                output += 1
                sampled_non_asap += 1

    return {
        "file": input_path.name,
        "input": total,
        "target": target_total,
        "asap": asap,
        "non_asap": sum(non_asap_by_piece.values()),
        "non_asap_groups": len(non_asap_by_piece),
        "sampled_non_asap": sampled_non_asap,
        "output": output,
    }


def write_counts_csv(output_dir: Path, results: list[dict]) -> None:
    with (output_dir / "counts.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples"])
        writer.writeheader()
        for result in results:
            writer.writerow({"file": result["file"], "kept_samples": result["output"]})


def ensure_epr_s1_dirs(cores_root: Path) -> None:
    for base in ["measure_epr_sft", "phrase_epr_sft"]:
        src = cores_root / base
        dst = cores_root / f"{base}_s1"
        if dst.exists():
            continue
        if not src.exists():
            raise FileNotFoundError(f"Neither {src} nor {dst} exists")
        shutil.move(str(src), str(dst))
        print(f"Renamed {src} -> {dst}")


def build_language_s2(cores_root: Path, asap_ids: set[str], seed: int) -> list[dict]:
    input_dir = cores_root / "language_sft_s1"
    output_dir = cores_root / "language_sft_s2"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    results = []
    for file_name in LANGUAGE_TASK_FILES:
        result = sample_file_to_s2(input_dir / file_name, output_dir / file_name, asap_ids, seed)
        results.append(result)
        print(
            f"language/{file_name}: input={result['input']:,}, asap={result['asap']:,}, "
            f"output={result['output']:,}"
        )

    write_counts_csv(output_dir, results)
    convert_dataset(
        input_dir=output_dir,
        output_path=output_dir / "sft_language_train.jsonl",
        examples_dir=output_dir / "examples",
        examples_per_task=0,
    )
    shutil.rmtree(output_dir / "examples", ignore_errors=True)
    return [{"dataset": "language_sft_s2", **result} for result in results]


def build_epr_s2(cores_root: Path, asap_ids: set[str], seed: int) -> list[dict]:
    results = []
    for family, file_names in EPR_TASKS.items():
        input_dir = cores_root / f"{family}_s1"
        output_dir = cores_root / f"{family}_s2"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)

        family_results = []
        for file_name in file_names:
            result = sample_file_to_s2(input_dir / file_name, output_dir / file_name, asap_ids, seed)
            family_results.append(result)
            results.append({"dataset": f"{family}_s2", **result})
            print(
                f"{family}/{file_name}: input={result['input']:,}, asap={result['asap']:,}, "
                f"output={result['output']:,}"
            )
        write_counts_csv(output_dir, family_results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cores-root", type=Path, default=Path("PianoCoReS/CoReS"))
    parser.add_argument("--metadata", type=Path, default=Path("sft_data/core-s-train/metadata_train.csv"))
    parser.add_argument("--seed", type=int, default=20260518)
    parser.add_argument(
        "--skip-language",
        action="store_true",
        help="Only build EPR S2 datasets; useful for EPR-only staging roots.",
    )
    args = parser.parse_args()

    asap_ids = load_asap_piece_ids(args.metadata)
    print(f"ASAP piece ids: {len(asap_ids):,}")

    ensure_epr_s1_dirs(args.cores_root)

    results = []
    if not args.skip_language:
        results.extend(build_language_s2(args.cores_root, asap_ids, args.seed))
    results.extend(build_epr_s2(args.cores_root, asap_ids, args.seed))

    summary_path = args.cores_root / "s2_sampling_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
