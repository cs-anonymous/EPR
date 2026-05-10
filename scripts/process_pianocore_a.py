#!/usr/bin/env python3
"""
处理 PianoCoRe-A 数据集：
1. 读取 Tier A 的配对数据（使用 raw alignment 提取 downbeat）
2. MusicXML → ABCX
3. raw MIDI + downbeat annotation → MIDI-TSV（raw alignment 对应 raw MIDI 的时间轴）
4. 保持原始 PianoCoRe 文件夹结构
"""

import os
import sys
import subprocess
import tempfile
import importlib.util
import pandas as pd
import numpy as np
import music21
import pretty_midi
from pathlib import Path
from tqdm import tqdm
from typing import Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from xml_to_abcx import musicxml_to_abcx


class PianoCoreProcessor:
    def __init__(self, pianocore_root: str, output_dir: str, use_refined: bool = True):
        self.pianocore_root = Path(pianocore_root)
        self.output_dir = Path(output_dir)
        self.use_refined = use_refined
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
        self.midi_tsv = self._load_midi_tsv_module()

        # 读取 metadata
        self.metadata = pd.read_csv(self.pianocore_root / "metadata.csv")

        if self.use_refined:
            self.tier_a_data = self.metadata[
                (self.metadata['tier_a'] == True) &
                (self.metadata['is_refined'] == True) &
                (self.metadata['refined_performance_midi_path'].notna()) &
                (self.metadata['refined_alignment_path'].notna())
            ].copy()
            print(f"找到 {len(self.tier_a_data)} 对 Tier A refined 数据")
        else:
            self.tier_a_data = self.metadata[
                (self.metadata['tier_a'] == True) &
                (self.metadata['raw_alignment_path'].notna())
            ].copy()
            print(f"找到 {len(self.tier_a_data)} 对 Tier A raw 数据")

    def _load_midi_tsv_module(self):
        spec = importlib.util.spec_from_file_location("midi_tsv", self.midi_tsv_script)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load midi_tsv.py from {self.midi_tsv_script}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _tick_to_seconds(self, tick: int, tempo_map: list[dict]) -> float:
        selected = tempo_map[0]
        for point in tempo_map:
            if point["tick"] <= tick:
                selected = point
            else:
                break
        return selected["seconds"] + (
            (tick - selected["tick"]) * selected["microseconds_per_beat"]
        ) / selected["tpq"] / 1_000_000

    def _score_measure_boundaries(self, score_midi_file: Path) -> list[tuple[float, str]]:
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
                    tempos.append({
                        "tick": tick,
                        "microseconds_per_beat": evt["microseconds_per_beat"],
                    })
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
        boundaries: list[tuple[int, str, int]] = []
        for idx, sig in enumerate(time_sigs):
            start_tick = sig["tick"]
            stop_tick = time_sigs[idx + 1]["tick"] if idx + 1 < len(time_sigs) else end_tick
            measure_ticks = round(tpq * sig["numerator"] * 4 / sig["denominator"])
            if measure_ticks <= 0:
                continue

            tick = start_tick
            # Do not add a near-empty final measure caused by end-of-track rounding.
            while tick < stop_tick - measure_ticks * 0.25:
                if not boundaries or tick > boundaries[-1][0]:
                    boundaries.append((tick, f"{sig['numerator']}/{sig['denominator']}", measure_ticks))
                tick += measure_ticks

        return [(self._tick_to_seconds(tick, tempo_map), sig) for tick, sig, _ in boundaries]

    def _score_midi_for_alignment(self, row: pd.Series, align_file: Path) -> Path:
        if self.use_refined:
            piece_dir = Path(row["score_xml_path"]).parent
            return self.pianocore_root / "refined" / piece_dir / "score_PDMX_refined.mid"

        data = np.load(align_file, allow_pickle=True)
        score_name = str(data["score_name"].item())
        return self.pianocore_root / "raw" / f"{score_name}.mid"

    def _median_by_score_time(self, score_times: np.ndarray, perf_times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
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

    def _refined_alignment_pairs(
        self,
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
            pidx = int(perf_idx[score_idx])
            if 0 <= pidx < len(perf_notes):
                score_times.append(score_notes[score_idx].start)
                perf_times.append(perf_notes[pidx].start)

        return np.array(score_times), np.array(perf_times)

    def _raw_alignment_pairs(self, align_file: Path) -> tuple[np.ndarray, np.ndarray]:
        data = np.load(align_file, allow_pickle=True)
        score_times = data["score_times"][:, 0]
        perf_times = data["perf_times"][:, 0]
        valid = (score_times >= 0) & (perf_times >= 0)
        return score_times[valid], perf_times[valid]

    def _map_score_downbeats_to_performance(
        self,
        boundaries: list[tuple[float, str]],
        score_times: np.ndarray,
        perf_times: np.ndarray,
        exact_eps: float = 0.035,
    ) -> str:
        unique_scores, median_perfs = self._median_by_score_time(score_times, perf_times)
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

        return "\n".join(annotation_lines)

    def extract_downbeats_from_alignment(
        self,
        align_path: str,
        xml_path: str,
        midi_path: str,
        row: pd.Series,
    ) -> Optional[str]:
        """Use expanded score-PDMX measure starts and alignment to create downbeat annotations."""
        split = "refined" if self.use_refined else "raw"
        align_file = self.pianocore_root / split / align_path
        if not align_file.exists():
            print(f"Alignment file not found: {align_file}")
            return None

        midi_file = self.pianocore_root / split / midi_path
        if not midi_file.exists():
            print(f"MIDI file not found: {midi_file}")
            return None

        score_midi_file = self._score_midi_for_alignment(row, align_file)
        if not score_midi_file.exists():
            print(f"Score MIDI file not found: {score_midi_file}")
            return None

        boundaries = self._score_measure_boundaries(score_midi_file)
        if not boundaries:
            return None

        if self.use_refined:
            score_times, perf_times = self._refined_alignment_pairs(score_midi_file, midi_file, align_file)
        else:
            score_times, perf_times = self._raw_alignment_pairs(align_file)

        annotation = self._map_score_downbeats_to_performance(boundaries, score_times, perf_times)
        return annotation or None

    def score_to_abcx(self, xml_path: str) -> Optional[str]:
        """将 MusicXML 转换为 ABCX"""
        xml_file = self.pianocore_root / "raw" / xml_path
        if not xml_file.exists():
            return None

        try:
            abcx_content = musicxml_to_abcx(xml_file, validate=False, drop_harmony=True)
            return abcx_content
        except Exception as e:
            print(f"Error converting {xml_path} to ABCX: {e}")
            return None

    def midi_to_tsv_with_annotation(
        self,
        midi_path: str,
        annotation_content: str,
        output_tsv_path: str
    ) -> bool:
        """使用 midi_tsv.py 将 MIDI 转换为完整的 MIDI-TSV
        annotation_content contains performance-time downbeats in seconds.
        """
        split = "refined" if self.use_refined else "raw"
        midi_file = self.pianocore_root / split / midi_path
        if not midi_file.exists():
            return False

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(annotation_content)
            annotation_file = f.name

        try:
            cmd = [
                sys.executable,
                str(self.midi_tsv_script),
                "midi2tsv",
                str(midi_file),
                "--out", output_tsv_path,
                "--annotation", annotation_file
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"Error converting MIDI to TSV: {result.stderr}")
                return False

            return Path(output_tsv_path).exists()

        except Exception as e:
            print(f"Error running midi_tsv.py: {e}")
            return False
        finally:
            try:
                os.unlink(annotation_file)
            except:
                pass

    def process_one_pair(self, row: pd.Series) -> bool:
        """处理一对 score-performance 数据"""
        try:
            # 解析路径结构：Composer/Piece/filename.ext
            score_xml = row['score_xml_path']
            if self.use_refined:
                perf_midi_path = row['refined_performance_midi_path']
                align_path = row['refined_alignment_path']
            else:
                perf_midi_path = row['performance_midi_path']
                align_path = row['raw_alignment_path']

            # 输出目录保持原始结构（不区分 raw/refined）
            piece_dir = self.output_dir / Path(score_xml).parent
            piece_dir.mkdir(parents=True, exist_ok=True)

            # 1. 提取 downbeat annotation
            annotation_content = self.extract_downbeats_from_alignment(
                align_path,
                row['score_xml_path'],
                perf_midi_path,
                row,
            )
            if annotation_content is None:
                return False

            # 2. 转换 score 到 ABCX → Composer/Piece/score.abcx
            abcx_content = self.score_to_abcx(row['score_xml_path'])
            if abcx_content is None:
                return False

            with open(piece_dir / "score.abcx", 'w') as f:
                f.write(abcx_content)

            # 3. 转换 raw MIDI 到 MIDI-TSV → Composer/Piece/xxx.mid.tsv
            tsv_output = str(piece_dir / f"{Path(perf_midi_path).name}.tsv")
            if not self.midi_to_tsv_with_annotation(
                perf_midi_path,
                annotation_content,
                tsv_output
            ):
                return False

            return True

        except Exception as e:
            print(f"Error processing {row['id']}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def process_all(self, limit: Optional[int] = None):
        """批量处理所有 Tier A 数据"""
        data_to_process = self.tier_a_data.head(limit) if limit else self.tier_a_data

        success_count = 0
        for idx, row in tqdm(data_to_process.iterrows(), total=len(data_to_process)):
            if self.process_one_pair(row):
                success_count += 1

        print(f"\n处理完成！")
        print(f"成功处理: {success_count} / {len(data_to_process)}")
        print(f"输出目录: {self.output_dir}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Process PianoCoRe-A dataset')
    parser.add_argument('--pianocore-root', type=str, required=True,
                        help='PianoCoRe 数据集根目录')
    parser.add_argument('--output-dir', type=str, required=True,
                        help='输出目录')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制处理数量（用于测试）')
    parser.add_argument('--raw', action='store_true',
                        help='使用 raw MIDI/raw alignment；默认使用 refined MIDI/refined alignment')
    parser.add_argument('--piece-filter', type=str, default=None,
                        help='只处理 score_xml_path 中包含该字符串的条目')

    args = parser.parse_args()

    processor = PianoCoreProcessor(args.pianocore_root, args.output_dir, use_refined=not args.raw)
    if args.piece_filter:
        processor.tier_a_data = processor.tier_a_data[
            processor.tier_a_data['score_xml_path'].astype(str).str.contains(args.piece_filter, regex=False)
        ].copy()
        print(f"piece-filter 后剩余 {len(processor.tier_a_data)} 对")
    processor.process_all(limit=args.limit)


if __name__ == '__main__':
    main()
