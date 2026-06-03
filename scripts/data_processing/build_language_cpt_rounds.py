#!/usr/bin/env python3
"""Build shuffled language CPT rounds for CorporaV2.

Performance corpora are shuffled first, then split into S/Astar rounds. Each
round is mixed with a full copy of annotated score MIDI records and shuffled
again before writing the final train_*.jsonl file.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path
from typing import Iterator


PERFORMANCE_PLANS = [
    ("S", "performance_S_midi.jsonl", 2, 0),
    ("Astar", "performance_Astar_midi.json", 3, 1),
]


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def iter_json_array(path: Path) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buf = ""
        in_array = False
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            pos = 0
            length = len(buf)
            while True:
                while pos < length and buf[pos].isspace():
                    pos += 1
                if pos >= length:
                    break
                if not in_array:
                    if buf[pos] != "[":
                        raise ValueError(f"{path}: expected '[' at array start")
                    in_array = True
                    pos += 1
                    continue
                if buf[pos] == ",":
                    pos += 1
                    continue
                if buf[pos] == "]":
                    return
                try:
                    obj, next_pos = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    break
                yield obj
                pos = next_pos
            buf = buf[pos:]
    if buf.strip() not in {"", "]"}:
        raise ValueError(f"{path}: trailing JSON content after array parse")


def iter_records(path: Path) -> Iterator[dict]:
    if path.suffix == ".jsonl":
        yield from iter_jsonl(path)
    else:
        yield from iter_json_array(path)


def write_records_as_jsonl(input_path: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for record in iter_records(input_path):
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def shuffle_jsonl(temp_path: Path, output_path: Path, seed: int) -> None:
    keyed_path = temp_path.with_suffix(temp_path.suffix + ".keyed")
    rng = random.Random(seed)

    try:
        with temp_path.open("rb") as source, keyed_path.open("wb") as keyed:
            for line in source:
                keyed.write(f"{rng.getrandbits(128):032x}\t".encode("ascii"))
                keyed.write(line)

        with output_path.open("wb") as out_handle:
            sort_proc = subprocess.Popen(
                ["sort", "-S", "50%", "-t", "\t", "-k1,1", str(keyed_path)],
                stdout=subprocess.PIPE,
            )
            assert sort_proc.stdout is not None
            for raw_line in sort_proc.stdout:
                _, payload = raw_line.split(b"\t", 1)
                out_handle.write(payload)
            return_code = sort_proc.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, sort_proc.args)
    finally:
        keyed_path.unlink(missing_ok=True)


def file_size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def count_lines(path: Path) -> int:
    count = 0
    with path.open("rb") as handle:
        for _ in handle:
            count += 1
    return count


def split_jsonl_evenly(input_path: Path, output_dir: Path, prefix: str, parts: int) -> list[dict]:
    total = count_lines(input_path)
    base, extra = divmod(total, parts)
    summaries = []
    output_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as source:
        for idx in range(parts):
            part_size = base + (1 if idx < extra else 0)
            round_name = f"train_{prefix}{idx + 1}"
            output_path = output_dir / f"{round_name}.performance.tmp.jsonl"
            written = 0
            with output_path.open("w", encoding="utf-8") as target:
                for _ in range(part_size):
                    line = source.readline()
                    if not line:
                        break
                    target.write(line)
                    written += 1
            summaries.append(
                {
                    "round": round_name,
                    "performance_part_path": str(output_path),
                    "performance_records": written,
                    "performance_part_index": idx + 1,
                    "performance_part_count": parts,
                }
            )
    return summaries


def append_file(src: Path, dst_handle) -> int:
    written = 0
    with src.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                dst_handle.write(line)
                written += 1
    return written


def build_final_round(
    *,
    round_spec: dict,
    annotated_path: Path,
    annotated_count: int,
    output_dir: Path,
    seed: int,
) -> dict:
    round_name = round_spec["round"]
    perf_part_path = Path(round_spec["performance_part_path"])
    tmp_path = output_dir / f"{round_name}.mixed.tmp.jsonl"
    final_path = output_dir / f"{round_name}.jsonl"

    with tmp_path.open("w", encoding="utf-8") as handle:
        copied_annotated = append_file(annotated_path, handle)
        copied_perf = append_file(perf_part_path, handle)

    if copied_annotated != annotated_count:
        raise RuntimeError(
            f"annotated count changed while building {round_name}: "
            f"expected {annotated_count}, got {copied_annotated}"
        )
    if copied_perf != round_spec["performance_records"]:
        raise RuntimeError(
            f"performance count changed while building {round_name}: "
            f"expected {round_spec['performance_records']}, got {copied_perf}"
        )

    shuffle_jsonl(tmp_path, final_path, seed=seed)
    tmp_path.unlink(missing_ok=True)
    perf_part_path.unlink(missing_ok=True)

    return {
        **{k: v for k, v in round_spec.items() if k != "performance_part_path"},
        "output_path": str(final_path),
        "output_size_mb": round(file_size_mb(final_path), 2),
        "final_shuffle_seed": seed,
        "annotated_score_file": str(annotated_path),
        "annotated_score_records": annotated_count,
        "total_records": annotated_count + round_spec["performance_records"],
    }


def build_performance_rounds(
    *,
    corpora_dir: Path,
    output_dir: Path,
    tier: str,
    perf_file: str,
    parts: int,
    seed: int,
    annotated_path: Path,
    annotated_count: int,
) -> list[dict]:
    perf_path = corpora_dir / perf_file
    if not perf_path.exists():
        raise FileNotFoundError(perf_path)

    normalized_path = output_dir / f"performance_{tier}_midi.jsonl.tmp"
    shuffled_path = corpora_dir / f"performance_{tier}_midi_shuffled.jsonl"

    performance_records = write_records_as_jsonl(perf_path, normalized_path)
    shuffle_jsonl(normalized_path, shuffled_path, seed=seed)
    normalized_path.unlink(missing_ok=True)

    part_specs = split_jsonl_evenly(shuffled_path, output_dir, tier, parts)
    summaries = []
    for part_spec in part_specs:
        part_index = part_spec["performance_part_index"]
        round_seed = seed + 1000 + part_index
        summary = build_final_round(
            round_spec=part_spec,
            annotated_path=annotated_path,
            annotated_count=annotated_count,
            output_dir=output_dir,
            seed=round_seed,
        )
        summary.update(
            {
                "performance_file": str(perf_path),
                "performance_shuffled_file": str(shuffled_path),
                "performance_shuffle_seed": seed,
                "performance_total_records": performance_records,
            }
        )
        summaries.append(summary)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpora-dir",
        type=Path,
        default=Path("data/CorporaV2/language_cpt"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    corpora_dir = args.corpora_dir
    output_dir = args.output_dir or corpora_dir / "rounds"
    output_dir.mkdir(parents=True, exist_ok=True)

    annotated_path = corpora_dir / "annotated_score_midi.jsonl"
    if not annotated_path.exists():
        raise FileNotFoundError(annotated_path)
    annotated_count = count_lines(annotated_path)

    summaries = []
    for tier, perf_file, parts, seed_offset in PERFORMANCE_PLANS:
        summaries.extend(
            build_performance_rounds(
                corpora_dir=corpora_dir,
                output_dir=output_dir,
                tier=tier,
                perf_file=perf_file,
                parts=parts,
                seed=args.seed + seed_offset,
                annotated_path=annotated_path,
                annotated_count=annotated_count,
            )
        )

    summary_path = output_dir / "round_build_summary.json"
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
