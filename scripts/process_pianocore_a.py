#!/usr/bin/env python3
"""
Process PianoCoRe-A into ABCX scores and measure-aligned MIDI-TSV files.

The output mirrors the original PianoCoRe piece layout while merging raw and
refined performances into the same piece directory:

    PianoCoRe_output/
      <composer>/<piece>/score.abcx
      <composer>/<piece>/<performance>.mid.tsv
      <composer>/<piece>/<performance>_refined.mid.tsv

No metadata.csv is used for discovery. The directory structure is the ID.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pretty_midi
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from xml_to_abcx import musicxml_to_abcx


_WORKER_PROCESSOR: "PianoCoreProcessor | None" = None


@dataclass(frozen=True)
class PianoCorePair:
    split: str
    piece_dir: Path
    score_xml: Path
    score_midi: Path
    perf_midi: Path
    align_file: Path


@dataclass(frozen=True)
class OrphanMidi:
    """A performance MIDI with no corresponding score — TSV via omnizart."""
    piece_dir: Path
    perf_midi: Path


class PianoCoreProcessor:
    def __init__(self, pianocore_root: str | Path, output_dir: str | Path):
        self.pianocore_root = Path(pianocore_root)
        self.output_dir = Path(output_dir)
        self.raw_root = self.pianocore_root / "raw"
        self.refined_root = self.pianocore_root / "refined"
        self.midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
        self.midi_tsv = self._load_midi_tsv_module()

    def _load_midi_tsv_module(self):
        spec = importlib.util.spec_from_file_location("midi_tsv", self.midi_tsv_script)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load midi_tsv.py from {self.midi_tsv_script}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def discover_pairs(self, splits: set[str], piece_filter: str | None = None) -> list[PianoCorePair]:
        """Discover pairs from metadata.csv.

        For each row, prefer refined alignment when available
        (is_refined=True and refined fields exist).  Fall back to raw alignment
        otherwise.  This avoids producing both raw and refined TSVs for the
        same performance.
        """
        import csv
        pairs: list[PianoCorePair] = []
        metadata = self.pianocore_root / "metadata.csv"
        if not metadata.exists():
            return self._discover_fallback(piece_filter)

        with open(metadata, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pair = self._row_to_pair(row)
                if pair is None:
                    continue
                rel_piece = pair.piece_dir.relative_to(self.raw_root)
                if piece_filter and piece_filter not in str(rel_piece):
                    continue
                pairs.append(pair)
        return pairs

    def _row_to_pair(self, row: dict[str, str]) -> PianoCorePair | None:
        """Convert one metadata.csv row into a PianoCorePair, preferring refined."""
        score_xml_rel = row.get("score_xml_path", "")
        if not score_xml_rel:
            return None

        # Try refined first
        refined_perf = row.get("refined_performance_midi_path", "")
        refined_align = row.get("refined_alignment_path", "")
        refined_score_midi = row.get("refined_score_midi_path", "")
        is_refined = row.get("is_refined", "False") == "True"

        if is_refined and refined_perf and refined_align and refined_score_midi:
            score_xml = self.raw_root / score_xml_rel
            perf_midi = self.refined_root / refined_perf
            score_midi = self.refined_root / refined_score_midi
            align_file = self.refined_root / refined_align
            if all(p.exists() for p in [score_xml, perf_midi, score_midi, align_file]):
                piece_dir = score_xml.parent
                return PianoCorePair("refined", piece_dir, score_xml, score_midi, perf_midi, align_file)

        # Fallback to raw
        raw_perf = row.get("performance_midi_path", "")
        raw_align = row.get("raw_alignment_path", "")
        raw_score_midi = row.get("score_midi_path", "")
        if raw_perf and raw_align and raw_score_midi:
            score_xml = self.raw_root / score_xml_rel
            perf_midi = self.raw_root / raw_perf
            score_midi = self.raw_root / raw_score_midi
            align_file = self.raw_root / raw_align
            if all(p.exists() for p in [score_xml, perf_midi, score_midi, align_file]):
                piece_dir = score_xml.parent
                return PianoCorePair("raw", piece_dir, score_xml, score_midi, perf_midi, align_file)

        return None

    def _discover_fallback(self, piece_filter: str | None) -> list[PianoCorePair]:
        """Fallback: discover pairs by scanning the filesystem."""
        pairs: list[PianoCorePair] = []
        seen_dirs: set[Path] = set()

        for ext in ("score.mxl", "score.musicxml"):
            for score_xml in self.raw_root.rglob(ext):
                piece_dir = score_xml.parent
                rel_piece = piece_dir.relative_to(self.raw_root)
                if piece_filter and piece_filter not in str(rel_piece):
                    continue
                if piece_dir in seen_dirs:
                    continue
                seen_dirs.add(piece_dir)

                # Check refined first
                for align_file in sorted(piece_dir.glob("*_refined_align.npz")):
                    perf_midi = piece_dir / align_file.name.replace("_refined_align.npz", "_refined.mid")
                    score_midi = piece_dir / "score_PDMX_refined.mid"
                    if perf_midi.exists() and score_midi.exists():
                        pairs.append(PianoCorePair("refined", piece_dir, score_xml, score_midi, perf_midi, align_file))

                # Fallback to raw
                for align_file in sorted(piece_dir.glob("*_align.npz")):
                    if "_refined_align.npz" in align_file.name:
                        continue
                    perf_midi = piece_dir / align_file.name.replace("_align.npz", ".mid")
                    if not perf_midi.exists():
                        continue
                    score_midi = self._raw_score_midi_for_alignment(align_file)
                    if score_midi and score_midi.exists():
                        pairs.append(PianoCorePair("raw", piece_dir, score_xml, score_midi, perf_midi, align_file))

        return pairs

    def _raw_score_midi_for_alignment(self, align_file: Path) -> Path | None:
        try:
            data = np.load(align_file, allow_pickle=True)
            score_name = str(data["score_name"].item())
        except Exception:
            fallback = align_file.parent / "score_PDMX.mid"
            return fallback if fallback.exists() else None
        return self.raw_root / f"{score_name}.mid"

    def discover_orphan_midis(self, piece_filter: str | None = None) -> list[OrphanMidi]:
        """Find performances that have no corresponding score XML."""
        import csv
        orphans: list[OrphanMidi] = []
        metadata = self.pianocore_root / "metadata.csv"
        if not metadata.exists():
            return []

        with open(metadata, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                score_xml_rel = row.get("score_xml_path", "")
                if score_xml_rel:
                    continue  # has a score, not an orphan
                perf_midi_rel = row.get("performance_midi_path", "")
                if not perf_midi_rel:
                    continue
                perf_midi = self.raw_root / perf_midi_rel
                if not perf_midi.exists():
                    continue
                piece_dir = perf_midi.parent
                rel_piece = piece_dir.relative_to(self.raw_root)
                if piece_filter and piece_filter not in str(rel_piece):
                    continue
                orphans.append(OrphanMidi(piece_dir, perf_midi))
        return orphans

    def output_piece_dir(self, pair: PianoCorePair) -> Path:
        # Always base output dir on the raw score path (score_xml is always under raw_root)
        return self.output_dir / pair.piece_dir.relative_to(self.raw_root)

    def process_all(self, pairs: list[PianoCorePair], limit: int | None = None) -> None:
        selected = pairs[:limit] if limit else pairs
        self.prepare_scores(selected, workers=1)
        success_count = 0

        for pair in tqdm(selected, total=len(selected)):
            if self.process_one_pair(pair):
                success_count += 1

        self.print_summary(success_count, len(selected))

    def process_all_parallel(
        self,
        pairs: list[PianoCorePair],
        workers: int,
        score_workers: int,
        limit: int | None = None,
    ) -> None:
        selected = pairs[:limit] if limit else pairs
        self.prepare_scores(selected, workers=score_workers)
        success_count = 0

        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=init_worker,
            initargs=(str(self.pianocore_root), str(self.output_dir)),
        ) as executor:
            results = executor.map(process_pair_worker, selected, chunksize=4)
            for ok in tqdm(results, total=len(selected)):
                if ok:
                    success_count += 1

        self.print_summary(success_count, len(selected))

    def process_all_pipeline(
        self,
        pairs: list[PianoCorePair],
        score_workers: int,
        midi_workers: int,
        limit: int | None = None,
    ) -> None:
        selected = pairs[:limit] if limit else pairs
        groups: dict[tuple[Path, Path], list[PianoCorePair]] = {}
        for pair in selected:
            abcx_file = self.output_piece_dir(pair) / "score.abcx"
            groups.setdefault((pair.score_xml, abcx_file), []).append(pair)

        success_count = 0
        max_pending_midi = max(1, midi_workers * 8)

        with (
            ProcessPoolExecutor(max_workers=score_workers) as score_executor,
            ProcessPoolExecutor(
                max_workers=midi_workers,
                initializer=init_worker,
                initargs=(str(self.pianocore_root), str(self.output_dir)),
            ) as midi_executor,
            tqdm(total=len(selected)) as progress,
        ):
            pending_midi = set()

            def drain_midi(block: bool) -> None:
                nonlocal success_count, pending_midi
                if not pending_midi:
                    return
                if block:
                    done, pending_midi = wait(pending_midi, return_when=FIRST_COMPLETED)
                else:
                    done = {future for future in pending_midi if future.done()}
                    pending_midi -= done

                for future in done:
                    if future.result():
                        success_count += 1
                    progress.update(1)

            def submit_piece_pairs(piece_pairs: list[PianoCorePair]) -> None:
                for pair in piece_pairs:
                    while len(pending_midi) >= max_pending_midi:
                        drain_midi(block=True)
                    pending_midi.add(midi_executor.submit(process_pair_worker, pair))
                    drain_midi(block=False)

            score_futures = {}
            for task, piece_pairs in groups.items():
                _, abcx_file = task
                if abcx_file.exists() and abcx_file.stat().st_size > 0:
                    submit_piece_pairs(piece_pairs)
                else:
                    abcx_file.parent.mkdir(parents=True, exist_ok=True)
                    score_futures[score_executor.submit(convert_score_worker, task)] = task

            for future in as_completed(score_futures):
                task = score_futures[future]
                if future.result():
                    submit_piece_pairs(groups[task])
                else:
                    progress.update(len(groups[task]))
                drain_midi(block=False)

            while pending_midi:
                drain_midi(block=True)

        self.print_summary(success_count, len(selected))

    def prepare_scores(self, pairs: list[PianoCorePair], workers: int) -> None:
        tasks = {}
        for pair in pairs:
            abcx_file = self.output_piece_dir(pair) / "score.abcx"
            if abcx_file.exists() and abcx_file.stat().st_size > 0:
                continue
            tasks[(pair.score_xml, abcx_file)] = (pair.score_xml, abcx_file)

        if not tasks:
            return

        print(f"准备 score.abcx: {len(tasks)} 个")
        for _, abcx_file in tasks.values():
            abcx_file.parent.mkdir(parents=True, exist_ok=True)

        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                results = executor.map(convert_score_worker, tasks.values(), chunksize=1)
                for ok in tqdm(results, total=len(tasks)):
                    if not ok:
                        pass
        else:
            for task in tqdm(tasks.values(), total=len(tasks)):
                convert_score_worker(task)

    def print_summary(self, success_count: int, total_count: int) -> None:
        print("\n处理完成！")
        print(f"成功处理: {success_count} / {total_count}")
        print(f"输出目录: {self.output_dir}")

    def process_one_pair(self, pair: PianoCorePair) -> bool:
        try:
            output_dir = self.output_piece_dir(pair)
            output_dir.mkdir(parents=True, exist_ok=True)

            abcx_file = output_dir / "score.abcx"
            if not abcx_file.exists() or abcx_file.stat().st_size == 0:
                return False

            tsv_file = output_dir / f"{pair.perf_midi.name}.tsv"
            if tsv_file.exists() and tsv_file.stat().st_size > 0:
                return True

            annotation = self.extract_downbeats(pair)
            if not annotation:
                return False

            return self.midi_to_tsv(pair.perf_midi, annotation, tsv_file)
        except Exception as exc:
            print(f"Error processing {pair.perf_midi}: {exc}")
            return False

    def extract_downbeats(self, pair: PianoCorePair) -> str | None:
        boundaries = self.score_measure_boundaries(pair.score_midi)
        if not boundaries:
            return None

        if pair.split == "raw":
            score_times, perf_times = self.raw_alignment_pairs(pair.align_file)
        else:
            score_times, perf_times = self.refined_alignment_pairs(pair.score_midi, pair.perf_midi, pair.align_file)

        return self.map_score_downbeats_to_performance(boundaries, score_times, perf_times)

    def score_measure_boundaries(self, score_midi_file: Path) -> list[tuple[float, str]]:
        """Return expanded score measure starts as (score_seconds, time_signature)."""
        tpq, tracks = self.midi_tsv.parse_midi(score_midi_file.read_bytes())
        tempos = []
        time_sigs = []
        end_tick = 0

        for events in tracks:
            tick = 0
            for evt in events:
                tick += evt["delta"]
                end_tick = max(end_tick, tick)
                if evt["type"] == "meta" and evt.get("meta_type") == 0x51:
                    tempos.append({"tick": tick, "microseconds_per_beat": evt["microseconds_per_beat"]})
                elif evt["type"] == "meta" and evt.get("meta_type") == 0x58:
                    time_sigs.append({
                        "tick": tick,
                        "numerator": evt["numerator"],
                        "denominator": evt["denominator"],
                    })

        if not time_sigs:
            time_sigs = [{"tick": 0, "numerator": 4, "denominator": 4}]
        time_sigs = sorted(time_sigs, key=lambda sig: sig["tick"])
        if time_sigs[0]["tick"] != 0:
            time_sigs.insert(0, {"tick": 0, "numerator": 4, "denominator": 4})

        tempo_map = self.midi_tsv.build_original_tempo_map(tpq, tempos)
        boundaries = []
        for idx, sig in enumerate(time_sigs):
            start_tick = sig["tick"]
            stop_tick = time_sigs[idx + 1]["tick"] if idx + 1 < len(time_sigs) else end_tick
            measure_ticks = round(tpq * sig["numerator"] * 4 / sig["denominator"])
            if measure_ticks <= 0:
                continue

            tick = start_tick
            while tick < stop_tick - measure_ticks * 0.25:
                if not boundaries or tick > boundaries[-1][0]:
                    boundaries.append((tick, f"{sig['numerator']}/{sig['denominator']}"))
                tick += measure_ticks

        return [(self.tick_to_seconds(tick, tempo_map), sig) for tick, sig in boundaries]

    @staticmethod
    def tick_to_seconds(tick: int, tempo_map: list[dict]) -> float:
        selected = tempo_map[0]
        for point in tempo_map:
            if point["tick"] <= tick:
                selected = point
            else:
                break
        return selected["seconds"] + (
            (tick - selected["tick"]) * selected["microseconds_per_beat"]
        ) / selected["tpq"] / 1_000_000

    @staticmethod
    def raw_alignment_pairs(align_file: Path) -> tuple[np.ndarray, np.ndarray]:
        data = np.load(align_file, allow_pickle=True)
        score_times = data["score_times"][:, 0]
        perf_times = data["perf_times"][:, 0]
        valid = (score_times >= 0) & (perf_times >= 0)
        return score_times[valid], perf_times[valid]

    @staticmethod
    def refined_alignment_pairs(
        score_midi_file: Path,
        perf_midi_file: Path,
        align_file: Path,
    ) -> tuple[np.ndarray, np.ndarray]:
        score_midi = pretty_midi.PrettyMIDI(str(score_midi_file))
        perf_midi = pretty_midi.PrettyMIDI(str(perf_midi_file))
        score_notes = sorted(
            [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
            key=lambda n: (n.start, n.pitch, n.end),
        )
        perf_notes = sorted(
            [n for inst in perf_midi.instruments if not inst.is_drum for n in inst.notes],
            key=lambda n: (n.start, n.pitch, n.end),
        )

        data = np.load(align_file, allow_pickle=True)
        perf_idx = data["perf_idx"]
        limit = min(len(score_notes), len(perf_idx))
        score_times = []
        perf_times = []
        for score_idx in range(limit):
            perf_idx_value = int(perf_idx[score_idx])
            if 0 <= perf_idx_value < len(perf_notes):
                score_times.append(score_notes[score_idx].start)
                perf_times.append(perf_notes[perf_idx_value].start)

        return np.array(score_times), np.array(perf_times)

    def map_score_downbeats_to_performance(
        self,
        boundaries: list[tuple[float, str]],
        score_times: np.ndarray,
        perf_times: np.ndarray,
        exact_eps: float = 0.035,
    ) -> str | None:
        unique_scores, median_perfs = self.median_by_score_time(score_times, perf_times)
        annotation_lines = []
        last_time = -1.0

        for score_time, time_sig in boundaries:
            exact = np.abs(score_times - score_time) <= exact_eps
            if np.any(exact):
                perf_time = float(np.min(perf_times[exact]))
            elif len(unique_scores) >= 2 and unique_scores[0] <= score_time <= unique_scores[-1]:
                perf_time = float(np.interp(score_time, unique_scores, median_perfs))
            else:
                continue

            if perf_time <= last_time + 0.02:
                continue
            annotation_lines.append(f"{perf_time:.6f}\t{perf_time:.6f}\tdb,{time_sig},0")
            last_time = perf_time

        return "\n".join(annotation_lines) if annotation_lines else None

    @staticmethod
    def median_by_score_time(score_times: np.ndarray, perf_times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        order = np.argsort(score_times)
        score_times = score_times[order]
        perf_times = perf_times[order]

        unique_scores = []
        median_perfs = []
        start = 0
        while start < len(score_times):
            end = start + 1
            while end < len(score_times) and abs(score_times[end] - score_times[start]) < 1e-6:
                end += 1
            unique_scores.append(score_times[start])
            median_perfs.append(float(np.median(perf_times[start:end])))
            start = end

        return np.array(unique_scores), np.array(median_perfs)

    def midi_to_tsv(self, midi_file: Path, annotation: str, output_tsv: Path) -> bool:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(annotation)
            annotation_file = handle.name

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.midi_tsv_script),
                    "midi2tsv",
                    str(midi_file),
                    "--out",
                    str(output_tsv),
                    "--annotation",
                    annotation_file,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                print(f"Error converting {midi_file}: {result.stderr}")
                return False
            return output_tsv.exists()
        finally:
            try:
                os.unlink(annotation_file)
            except OSError:
                pass

    def process_orphan_midi(self, orphan: OrphanMidi) -> bool:
        """Convert orphan MIDI to TSV using omnizart auto-downbeat detection."""
        try:
            output_dir = self.output_dir / orphan.piece_dir.relative_to(self.raw_root)
            output_dir.mkdir(parents=True, exist_ok=True)

            tsv_file = output_dir / f"{orphan.perf_midi.name}.tsv"
            if tsv_file.exists() and tsv_file.stat().st_size > 0:
                return True

            # Use omnizart38 conda environment for omnizart downbeat detection
            result = subprocess.run(
                [
                    "conda", "run", "-n", "omnizart38", "python",
                    str(self.midi_tsv_script),
                    "midi2tsv",
                    str(orphan.perf_midi),
                    "--out",
                    str(tsv_file),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                print(f"Error converting orphan MIDI {orphan.perf_midi}: {result.stderr}")
                return False
            return tsv_file.exists()
        except Exception as exc:
            print(f"Error processing orphan MIDI {orphan.perf_midi}: {exc}")
            return False


def process_orphan_worker(orphan: OrphanMidi) -> bool:
    if _WORKER_PROCESSOR is None:
        raise RuntimeError("Worker processor is not initialized")
    return _WORKER_PROCESSOR.process_orphan_midi(orphan)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process PianoCoRe-A into ABCX + MIDI-TSV")
    parser.add_argument("--pianocore-root", default="PianoCoRe", help="PianoCoRe root containing raw/ and refined/")
    parser.add_argument("--output-dir", default="PianoCoRe_output", help="Output root")
    parser.add_argument("--split", choices=["all", "raw", "refined"], default="all", help="Which split to process")
    parser.add_argument("--piece-filter", default=None, help="Substring filter on the piece relative path")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of performance pairs")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    parser.add_argument(
        "--score-workers",
        type=int,
        default=None,
        help="Number of score conversion workers. Defaults to min(workers, 2).",
    )
    parser.add_argument(
        "--skip-orphans",
        action="store_true",
        help="Skip processing orphan MIDI files (no corresponding score)",
    )
    return parser.parse_args()


def init_worker(pianocore_root: str, output_dir: str) -> None:
    global _WORKER_PROCESSOR
    _WORKER_PROCESSOR = PianoCoreProcessor(pianocore_root, output_dir)


def process_pair_worker(pair: PianoCorePair) -> bool:
    if _WORKER_PROCESSOR is None:
        raise RuntimeError("Worker processor is not initialized")
    return _WORKER_PROCESSOR.process_one_pair(pair)


def convert_score_worker(task: tuple[Path, Path]) -> bool:
    score_xml, abcx_file = task
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "__convert_score",
                str(score_xml),
                str(abcx_file),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
        stderr = result.stderr.strip()
        print(f"Error converting score {score_xml}: {stderr}")
        return False
    except Exception as exc:
        print(f"Error converting score {score_xml}: {exc}")
        return False


def convert_score_cli(score_xml: str, abcx_file: str) -> None:
    out_path = Path(abcx_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    try:
        content = musicxml_to_abcx(Path(score_xml), validate=False, drop_harmony=True)
        tmp_file.write_text(content, encoding="utf-8")
        os.replace(tmp_file, out_path)
    finally:
        if tmp_file.exists():
            tmp_file.unlink()


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "__convert_score":
        if len(sys.argv) != 4:
            raise SystemExit("Usage: process_pianocore_a.py __convert_score <score.mxl> <score.abcx>")
        convert_score_cli(sys.argv[2], sys.argv[3])
        return

    args = parse_args()
    splits = {"raw", "refined"} if args.split == "all" else {args.split}
    processor = PianoCoreProcessor(args.pianocore_root, args.output_dir)
    pairs = processor.discover_pairs(splits, args.piece_filter)
    print(f"找到 {len(pairs)} 对可处理数据")
    if args.workers > 1:
        score_workers = args.score_workers if args.score_workers is not None else min(args.workers, 2)
        processor.process_all_pipeline(
            pairs,
            score_workers=score_workers,
            midi_workers=args.workers,
            limit=args.limit,
        )
    else:
        processor.process_all(pairs, limit=args.limit)

    # Process orphan MIDI files (no corresponding score)
    if not args.skip_orphans and args.limit is None:
        orphans = processor.discover_orphan_midis(args.piece_filter)
        print(f"找到 {len(orphans)} 个无乐谱的 MIDI，使用 omnizart 自动节拍检测转换为 TSV")
        if orphans:
            success = 0
            with ProcessPoolExecutor(
                max_workers=args.workers,
                initializer=init_worker,
                initargs=(str(args.pianocore_root), str(args.output_dir)),
            ) as executor:
                results = executor.map(process_orphan_worker, orphans, chunksize=8)
                for ok in tqdm(results, total=len(orphans), desc="Orphan MIDI"):
                    if ok:
                        success += 1
            print(f"孤儿 MIDI 处理完成：{success} / {len(orphans)}")


if __name__ == "__main__":
    main()
