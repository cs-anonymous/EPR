#!/usr/bin/env python3
"""Add previous performance context to existing EPR JSONL files.

For measure_epr:
  main/ending rows receive previous contiguous M target as `perf_context`.

For phrase_epr:
  main/ending rows receive previous contiguous H target as `perf_context`.

Cold-start rows receive an empty `perf_context`.

When `--context-source-dir` is provided, previous targets are looked up from
that directory instead of only the adjacent row in the input file. This is
needed for sampled subsets such as S1, where the previous measure/phrase may
not itself be present in the subset.
"""
import argparse
import json
import re
import shutil
from pathlib import Path

from tqdm import tqdm


EPR_FILES = ["measure_epr.jsonl", "phrase_epr.jsonl"]


def marker_index(text: str, prefix: str) -> int | None:
    first = text.split(None, 1)[0] if text else ""
    match = re.match(rf"^{prefix}(\d+)(?::|$)", first)
    return int(match.group(1)) if match else None


def target_marker(sample: dict, file_name: str) -> str:
    if file_name == "measure_epr.jsonl":
        return sample.get("target_measure_id", "")
    return sample.get("target_phrase_id", "")


def target_key(sample: dict, file_name: str) -> tuple[str, str]:
    return sample.get("piece_id", ""), target_marker(sample, file_name)


def previous_marker(sample: dict, file_name: str) -> str | None:
    prefix = "M" if file_name == "measure_epr.jsonl" else "H"
    current_idx = marker_index(target_marker(sample, file_name), prefix)
    if current_idx is None or current_idx <= 1:
        return None
    return f"{prefix}{current_idx - 1}"


def collect_required_context_keys(src: Path) -> set[tuple[str, str]]:
    required = set()
    with src.open("r", encoding="utf-8") as fin:
        for line in tqdm(fin, desc=f"Collect context keys {src.name}"):
            if not line.strip():
                continue
            sample = json.loads(line)
            if sample.get("task_type") == "coldstart":
                continue
            prev_marker = previous_marker(sample, src.name)
            if prev_marker:
                required.add((sample.get("piece_id", ""), prev_marker))
    return required


def load_context_lookup(source: Path, required: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    lookup = {}
    if not required:
        return lookup

    with source.open("r", encoding="utf-8") as fin:
        for line in tqdm(fin, desc=f"Index context source {source.name}"):
            if not line.strip():
                continue
            sample = json.loads(line)
            key = target_key(sample, source.name)
            if key in required:
                lookup[key] = sample.get("perf_target", "")
                if len(lookup) == len(required):
                    break
    return lookup


def transform_epr_file(
    src: Path,
    dst: Path,
    context_lookup: dict[tuple[str, str], str] | None = None,
) -> tuple[int, int, int]:
    """Return (rows, context_rows, missing_context_rows)."""
    prefix = "M" if src.name == "measure_epr.jsonl" else "H"
    rows = 0
    context_rows = 0
    missing_context_rows = 0
    prev_piece_id = None
    prev_target = None
    prev_marker_idx = None

    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in tqdm(fin, desc=f"Context {src.name}"):
            if not line.strip():
                continue
            sample = json.loads(line)
            piece_id = sample.get("piece_id")
            current_id = target_marker(sample, src.name)
            current_idx = marker_index(current_id, prefix)

            perf_context = ""
            if sample.get("task_type") != "coldstart":
                if context_lookup is not None:
                    prev_marker = previous_marker(sample, src.name)
                    perf_context = context_lookup.get((piece_id, prev_marker), "") if prev_marker else ""
                elif (
                    piece_id == prev_piece_id
                    and prev_target
                    and prev_marker_idx is not None
                    and current_idx is not None
                    and prev_marker_idx == current_idx - 1
                ):
                    perf_context = prev_target

                if perf_context:
                    context_rows += 1
                else:
                    missing_context_rows += 1

            sample["perf_context"] = perf_context
            target = sample.get("perf_target", "")
            prev_piece_id = piece_id
            prev_target = target
            prev_marker_idx = marker_index(target, prefix)

            fout.write(json.dumps(sample, ensure_ascii=False) + "\n")
            rows += 1

    return rows, context_rows, missing_context_rows


def process_dir(input_dir: Path, output_dir: Path, replace: bool, context_source_dir: Path | None) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    processed = set()
    for src in input_dir.iterdir():
        dst = output_dir / src.name
        if src.name in EPR_FILES:
            context_lookup = None
            if context_source_dir:
                source = context_source_dir / src.name
                if not source.exists():
                    raise FileNotFoundError(f"Missing context source: {source}")
                required = collect_required_context_keys(src)
                context_lookup = load_context_lookup(source, required)
                print(
                    f"{src.name}: required_context_keys={len(required):,} "
                    f"indexed={len(context_lookup):,}"
                )

            rows, context_rows, missing = transform_epr_file(src, dst, context_lookup)
            print(f"{src.name}: rows={rows:,} context={context_rows:,} missing_non_cold={missing:,}")
            processed.add(src.name)
        elif src.is_file():
            shutil.copyfile(src, dst)
        elif src.is_dir():
            shutil.copytree(src, dst)

    missing_files = [name for name in EPR_FILES if name not in processed]
    if missing_files:
        print(f"Missing EPR files in {input_dir}: {', '.join(missing_files)}")

    if replace:
        backup = input_dir.with_name(input_dir.name + ".pre_perf_context")
        if backup.exists():
            shutil.rmtree(backup)
        input_dir.rename(backup)
        output_dir.rename(input_dir)
        shutil.rmtree(backup)
        print(f"Replaced {input_dir}")
    else:
        print(f"Wrote {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--context-source-dir",
        type=Path,
        help="Optional full dataset directory to look up previous EPR targets from.",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    process_dir(args.input_dir, args.output_dir, args.replace, args.context_source_dir)


if __name__ == "__main__":
    main()
