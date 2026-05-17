#!/usr/bin/env python3
"""Create a CoRe-S* test subset aligned to PianistTransformer test pieces.

The split unit is a score/work key: (composer, composition, movement).
All CoRe-S* records sharing one of those keys are assigned to the test set.
"""
import argparse
import csv
import json
import warnings
from pathlib import Path

import pandas as pd
import pretty_midi
from tqdm import tqdm


TASK_FILES = [
    "measure_epr.jsonl",
    "phrase_epr.jsonl",
    "measure_perf_lang_continuation.jsonl",
    "measure_perf_lang_mask.jsonl",
    "measure_score_lang_continuation.jsonl",
    "measure_score_lang_mask.jsonl",
    "phrase_score_lang_continuation.jsonl",
    "phrase_score_lang_mask.jsonl",
]


def midi_features(path: Path) -> dict:
    pm = pretty_midi.PrettyMIDI(str(path))
    notes = sorted(
        [note for inst in pm.instruments for note in inst.notes],
        key=lambda note: (note.start, note.pitch, note.end),
    )
    hist = [0] * 128
    for note in notes:
        hist[note.pitch] += 1
    return {
        "count": len(notes),
        "duration": float(pm.get_end_time()),
        "pitch_sum": sum(note.pitch for note in notes),
        "hist": hist,
        "seq": [note.pitch for note in notes],
    }


def hist_distance(a: dict, b: dict) -> float:
    denom = max(1, a["count"] + b["count"])
    return sum(abs(x - y) for x, y in zip(a["hist"], b["hist"])) / denom


def sampled_sequence_match(a: dict, b: dict, k: int = 300) -> float:
    sa = a["seq"]
    sb = b["seq"]
    if not sa or not sb:
        return 0.0
    n = min(k, len(sa), len(sb))
    aa = [sa[int(i * len(sa) / n)] for i in range(n)]
    bb = [sb[int(i * len(sb) / n)] for i in range(n)]
    return sum(x == y for x, y in zip(aa, bb)) / n


def match_score(test_features: dict, candidate_features: dict) -> float:
    count_delta = abs(test_features["count"] - candidate_features["count"]) / max(
        test_features["count"], candidate_features["count"], 1
    )
    duration_delta = abs(test_features["duration"] - candidate_features["duration"]) / max(
        test_features["duration"], candidate_features["duration"], 1e-9
    )
    hist_delta = hist_distance(test_features, candidate_features)
    pitch_sum_delta = abs(test_features["pitch_sum"] - candidate_features["pitch_sum"]) / max(
        test_features["pitch_sum"], candidate_features["pitch_sum"], 1
    )
    seq_match = sampled_sequence_match(test_features, candidate_features)
    return (
        count_delta
        + 0.3 * duration_delta
        + 2.0 * hist_delta
        + 0.5 * pitch_sum_delta
        - 0.3 * seq_match
    )


def core_s_star_mask(df: pd.DataFrame) -> pd.Series:
    interpolation_ratio = (
        df["refined_performance_interpolated_note_count"]
        / df["refined_performance_note_count"]
    )
    asap = ~df["is_transcription"].astype(bool)
    clean_astar = (
        df["tier_a_star"].astype(bool)
        & (df["refined_recall"] >= 0.95)
        & (interpolation_ratio <= 0.05)
    )
    return clean_astar | asap


def work_key_frame(df: pd.DataFrame) -> pd.Series:
    return df[["composer", "composition", "movement"]].fillna("").apply(tuple, axis=1)


def score_piece_id(score_abcx_path: str) -> str:
    prefix = "PianoCoRe/score/"
    path = score_abcx_path
    if path.startswith(prefix):
        path = path[len(prefix):]
    if path.endswith("/score.abcx"):
        path = path[: -len("/score.abcx")]
    return f"{path}/score_aligned"


def performance_piece_id(perf_tsv_path: str) -> str:
    path = str(perf_tsv_path)
    if path.startswith("PianoCoRe_output/"):
        path = path[len("PianoCoRe_output/"):]
    elif path.startswith("PianoCoRe/aligned/"):
        path = path[len("PianoCoRe/aligned/"):]
    if path.endswith(".tsv"):
        path = path[: -len(".tsv")]
    return path


def task_filter(sample: dict, task_name: str, test_perf_piece_ids: set, test_score_piece_ids: set) -> bool:
    piece_id = sample.get("piece_id", "")
    if "score_lang" in task_name:
        return piece_id in test_score_piece_ids
    return piece_id in test_perf_piece_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", default="PianoCoRe/metadata.csv")
    parser.add_argument("--pianocore-raw", default="PianoCoRe/raw")
    parser.add_argument("--pt-test-score-dir", default="PianistTransformer/data/midis/testset/score")
    parser.add_argument("--input-dir", default="sft_data/core-s")
    parser.add_argument("--output-dir", default="sft_data/core-s-test")
    args = parser.parse_args()

    warnings.filterwarnings("ignore", category=RuntimeWarning)

    metadata = pd.read_csv(args.metadata)
    s_star = metadata[core_s_star_mask(metadata)].copy()
    asap = metadata[~metadata["is_transcription"].astype(bool)].copy()

    raw_root = Path(args.pianocore_raw)
    candidate_rows = (
        asap.drop_duplicates("score_midi_path")
        .sort_values("score_midi_path")
        .reset_index(drop=True)
    )
    candidates = []
    for row in tqdm(candidate_rows.itertuples(index=False), total=len(candidate_rows), desc="Index ASAP scores"):
        if pd.isna(row.score_midi_path):
            continue
        path = raw_root / str(row.score_midi_path)
        if not path.exists():
            continue
        candidates.append((row, midi_features(path)))

    matched_rows = []
    test_score_paths = sorted(Path(args.pt_test_score_dir).glob("*.mid"), key=lambda p: int(p.stem))
    for test_path in tqdm(test_score_paths, desc="Match PianistTransformer scores"):
        test_feat = midi_features(test_path)
        scored = [
            (match_score(test_feat, candidate_feat), row, candidate_feat)
            for row, candidate_feat in candidates
        ]
        scored.sort(key=lambda item: item[0])
        best_score, best_row, best_feat = scored[0]
        matched_rows.append(
            {
                "pt_score_index": int(test_path.stem),
                "pt_score_path": str(test_path),
                "matched_score_midi_path": best_row.score_midi_path,
                "match_score": best_score,
                "pt_note_count": test_feat["count"],
                "matched_note_count": best_feat["count"],
                "pt_duration": test_feat["duration"],
                "matched_duration": best_feat["duration"],
                "composer": best_row.composer,
                "composition": best_row.composition,
                "movement": "" if pd.isna(best_row.movement) else best_row.movement,
            }
        )

    matched_df = pd.DataFrame(matched_rows)
    selected_keys = set(
        matched_df[["composer", "composition", "movement"]].fillna("").apply(tuple, axis=1)
    )
    test_metadata = s_star[work_key_frame(s_star).isin(selected_keys)].copy()
    test_perf_ids = set(test_metadata["performance_id"].astype(str))
    test_perf_piece_ids = set(
        performance_piece_id(path)
        for path in test_metadata["performance_tsv_path"].dropna().astype(str)
    )
    test_score_piece_ids = set(
        score_piece_id(path)
        for path in test_metadata["score_abcx_path"].dropna().astype(str)
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "pianist_transformer_test_piece_manifest.csv"
    matched_df.to_csv(manifest_path, index=False)
    test_metadata.to_csv(output_dir / "metadata_test.csv", index=False)

    counts = []
    input_dir = Path(args.input_dir)
    for file_name in TASK_FILES:
        src = input_dir / file_name
        dst = output_dir / file_name
        kept = 0
        total = 0
        task_name = file_name.removesuffix(".jsonl")
        with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
            for line in tqdm(fin, desc=f"Filter {file_name}"):
                total += 1
                sample = json.loads(line)
                if task_filter(sample, task_name, test_perf_piece_ids, test_score_piece_ids):
                    fout.write(line)
                    kept += 1
        counts.append({"file": file_name, "kept_samples": kept, "source_samples": total})

    counts_path = output_dir / "counts.csv"
    with counts_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "kept_samples", "source_samples"])
        writer.writeheader()
        writer.writerows(counts)

    print(f"Matched PianistTransformer test scores: {len(matched_df):,}")
    print(f"Selected score/work keys: {len(selected_keys):,}")
    print(f"Selected CoRe-S* metadata rows: {len(test_metadata):,}")
    print(f"Selected performance_ids: {len(test_perf_ids):,}")
    print(f"Selected score piece_ids: {len(test_score_piece_ids):,}")
    print(f"Manifest: {manifest_path}")
    print(f"Counts: {counts_path}")


if __name__ == "__main__":
    main()
