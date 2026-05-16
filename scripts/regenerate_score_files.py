#!/usr/bin/env python3
"""Regenerate score-dependent files in PianoCoRe/aligned.

Reads PianoCoRe/metadata.csv to get score_midi_path and score_xml_path.

Only produces:
  - score.abcx  (copy from PianoCoRe/score)
  - score_structure.json / score_structure_mini.json
  - score_aligned.abcx / score_aligned_mini.abcx

Does NOT process any performance MIDI or regenerate TSV files.

Usage:
    python scripts/regenerate_score_files.py --jobs 16
    python scripts/regenerate_score_files.py --jobs 16 --force
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from tqdm import tqdm

_HERE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_HERE / "scripts"))
sys.path.insert(0, str(_HERE / "wave-roll"))

import align_score_performance as align_mod

extract_score_measures = align_mod.extract_score_measures
parse_abcx_structure = align_mod.parse_abcx_structure
build_midi_to_abcx_mapping = align_mod.build_midi_to_abcx_mapping
build_midi_measure_content = align_mod.build_midi_measure_content
build_midi_phrases = align_mod.build_midi_phrases
write_aligned_abcx = align_mod.write_aligned_abcx
ScoreStructure = align_mod.ScoreStructure

WORKER_MIDI_TSV = None

def init_worker(raw_root: str):
    global WORKER_MIDI_TSV
    project_root = _HERE
    midi_tsv_path = str(project_root / "wave-roll" / "midi_tsv.py")
    midi_tsv_spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_path)
    WORKER_MIDI_TSV = importlib.util.module_from_spec(midi_tsv_spec)
    midi_tsv_spec.loader.exec_module(WORKER_MIDI_TSV)

def build_struct(score_midi: Path, abcx_path: Path, midi_root: Path) -> ScoreStructure | None:
    score_measures = extract_score_measures(score_midi, WORKER_MIDI_TSV)
    if not score_measures:
        return None

    _, abcx_measures = parse_abcx_structure(abcx_path, score_measures)

    # Use the score MIDI itself as mapping source (consistent with metadata)
    midi_to_abcx = build_midi_to_abcx_mapping(score_measures, abcx_measures, score_midi)
    midi_measure_content = build_midi_measure_content(score_measures, abcx_measures, midi_to_abcx)
    midi_phrases = build_midi_phrases(score_measures, midi_to_abcx, midi_measure_content, abcx_path)

    measure_to_phrase = {}
    for phrase in midi_phrases:
        for m in phrase.measures:
            measure_to_phrase[m] = phrase.phrase_id

    return ScoreStructure(
        measures=score_measures,
        phrases=midi_phrases,
        measure_to_phrase=measure_to_phrase,
        abcx_measures=abcx_measures,
        midi_to_abcx=midi_to_abcx,
        midi_measure_content=midi_measure_content,
    )

def write_struct_json(struct: ScoreStructure, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "measures": [asdict(m) for m in struct.measures],
            "phrases": [asdict(p) for p in struct.phrases],
            "measure_to_phrase": struct.measure_to_phrase,
            "abcx_measures": struct.abcx_measures,
            "midi_to_abcx": struct.midi_to_abcx,
            "midi_measure_content": {str(k): v for k, v in sorted(struct.midi_measure_content.items())},
        }, f, indent=2, ensure_ascii=False)

def process_one(xml_rel: str, main_midi_rel: str, mini_midi_rel: str | None,
                pianocore_root: Path, output_dir: Path, raw_root: Path, force: bool) -> str:
    try:
        abcx_path = pianocore_root / "score" / xml_rel / "score.abcx"
        if not abcx_path.exists():
            return "no_abcx"

        main_midi = raw_root / main_midi_rel
        if not main_midi.exists():
            return f"no_main_midi:{main_midi_rel}"

        out_dir = output_dir / xml_rel
        out_dir.mkdir(parents=True, exist_ok=True)

        # Copy score.abcx
        dest_abcx = out_dir / "score.abcx"
        if force or not dest_abcx.exists():
            shutil.copy2(abcx_path, dest_abcx)

        # Build and write main structure
        main_struct = build_struct(main_midi, abcx_path, raw_root)
        if main_struct is None:
            return "build_struct_failed"

        json_path = out_dir / "score_structure.json"
        if force or not json_path.exists():
            write_struct_json(main_struct, json_path)

        aligned_path = out_dir / "score_aligned.abcx"
        if force or not aligned_path.exists():
            if not write_aligned_abcx(abcx_path, aligned_path, main_struct.phrases, main_struct.midi_measure_content):
                stale_mini = out_dir / "score_aligned_mini.abcx"
                if stale_mini.exists():
                    stale_mini.unlink()
                return "not_two_staff"

        # Mini version
        if mini_midi_rel:
            mini_midi = raw_root / mini_midi_rel
            if mini_midi.exists():
                mini_struct = build_struct(mini_midi, abcx_path, raw_root)
                if mini_struct is not None:
                    mini_json = out_dir / "score_structure_mini.json"
                    if force or not mini_json.exists():
                        write_struct_json(mini_struct, mini_json)

                    mini_aligned = out_dir / "score_aligned_mini.abcx"
                    if force or not mini_aligned.exists():
                        write_aligned_abcx(abcx_path, mini_aligned, mini_struct.phrases, mini_struct.midi_measure_content)

        return "ok"
    except Exception as e:
        return f"exception:{e}"

def load_metadata(metadata_path: Path) -> list[dict]:
    """Load metadata.csv and group by score_xml_path.
    Returns list of {xml_rel, main_midi_rel, mini_midi_rel}.
    """
    scores: dict[str, dict] = {}
    with open(metadata_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            xml = row["score_xml_path"]
            midi = row["score_midi_path"]
            if not xml or not midi:
                continue
            xml_rel = str(Path(xml).parent)  # e.g. "Bach,.../BWV_54"
            if xml_rel not in scores:
                scores[xml_rel] = {"xml_rel": xml_rel, "main_midi": None, "mini_midi": None}
            if "mini" in midi:
                if scores[xml_rel]["mini_midi"] is None:
                    scores[xml_rel]["mini_midi"] = midi
            else:
                if scores[xml_rel]["main_midi"] is None:
                    scores[xml_rel]["main_midi"] = midi
    return list(scores.values())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--piece-filter", default=None)
    args = parser.parse_args()

    pianocore_root = Path("PianoCoRe")
    output_dir = Path("PianoCoRe/aligned")
    raw_root = Path("PianoCoRe/raw")
    metadata_path = pianocore_root / "metadata.csv"

    score_entries = load_metadata(metadata_path)

    if args.piece_filter:
        score_entries = [e for e in score_entries if args.piece_filter in e["xml_rel"]]

    # Only process pieces that have a score.abcx
    score_dir = pianocore_root / "score"
    abcx_set = {str(p.parent.relative_to(score_dir)) for p in score_dir.rglob("score.abcx")}

    to_do = []
    for entry in score_entries:
        xml_rel = entry["xml_rel"]
        if xml_rel not in abcx_set:
            continue
        if entry["main_midi"] is None:
            continue

        if args.force:
            to_do.append(entry)
        else:
            out = output_dir / xml_rel
            if not (out / "score.abcx").exists() or \
               not (out / "score_structure.json").exists() or \
               not (out / "score_aligned.abcx").exists():
                to_do.append(entry)

    print(f"Total scores in metadata with ABCX: {len(abcx_set & {e['xml_rel'] for e in score_entries})}")
    print(f"With main MIDI: {sum(1 for e in score_entries if e['main_midi'] and e['xml_rel'] in abcx_set)}")
    print(f"Need regeneration: {len(to_do)} (force={args.force})")

    if not to_do:
        print("Nothing to do.")
        return

    with ProcessPoolExecutor(
        max_workers=args.jobs,
        initializer=init_worker,
        initargs=(str(raw_root),),
    ) as executor:
        futures = {
            executor.submit(
                process_one,
                e["xml_rel"], e["main_midi"], e["mini_midi"],
                pianocore_root, output_dir, raw_root, args.force,
            ): e["xml_rel"]
            for e in to_do
        }
        ok = 0
        fail_reasons: dict[str, int] = {}
        for fut in tqdm(as_completed(futures), total=len(futures)):
            result = fut.result()
            if result == "ok":
                ok += 1
            else:
                fail_reasons[result] = fail_reasons.get(result, 0) + 1

    fail_summary = ", ".join(f"{k}={v}" for k, v in sorted(fail_reasons.items()))
    print(f"\nDone: {ok} regenerated, {sum(fail_reasons.values())} failed ({fail_summary})")

if __name__ == "__main__":
    main()
