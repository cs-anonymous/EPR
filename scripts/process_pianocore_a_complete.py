#!/usr/bin/env python3
"""
处理 PianoCoRe-A 数据集：
1. 读取 Tier A 的 refined 配对数据
2. MusicXML → ABCX
3. MIDI + alignment → MIDI-TSV（按小节对齐）
4. 生成小节级配对数据集
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
import pretty_midi
import music21
from typing import Dict, List, Tuple, Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from xml_to_abcx import xml_to_abcx


class PianoCoreProcessor:
    def __init__(self, pianocore_root: str, output_dir: str):
        self.pianocore_root = Path(pianocore_root)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 读取 metadata
        self.metadata = pd.read_csv(self.pianocore_root / "metadata.csv")

        # 筛选 Tier A refined 数据
        self.tier_a_data = self.metadata[
            (self.metadata['tier_a'] == True) &
            (self.metadata['is_refined'] == True)
        ].copy()

        print(f"找到 {len(self.tier_a_data)} 对 Tier A refined 数据")

    def load_alignment(self, align_path: str) -> Dict:
        """加载 alignment 文件（.npz 格式）"""
        align_file = self.pianocore_root / "PianoCoRe" / "refined" / align_path
        if not align_file.exists():
            raise FileNotFoundError(f"Alignment file not found: {align_file}")

        data = np.load(align_file, allow_pickle=True)
        return {
            'score_to_perf': data.get('score_to_performance', None),
            'perf_to_score': data.get('performance_to_score', None),
            'score_notes': data.get('score_notes', None),
            'perf_notes': data.get('performance_notes', None),
        }

    def load_midi(self, midi_path: str) -> pretty_midi.PrettyMIDI:
        """加载 MIDI 文件"""
        midi_file = self.pianocore_root / "PianoCoRe" / "refined" / midi_path
        if not midi_file.exists():
            raise FileNotFoundError(f"MIDI file not found: {midi_file}")
        return pretty_midi.PrettyMIDI(str(midi_file))

    def load_score_xml(self, xml_path: str) -> music21.stream.Score:
        """加载 MusicXML 文件"""
        xml_file = self.pianocore_root / "PianoCoRe" / "raw" / xml_path
        if not xml_file.exists():
            raise FileNotFoundError(f"XML file not found: {xml_file}")
        return music21.converter.parse(str(xml_file))

    def score_to_abcx(self, xml_path: str) -> str:
        """将 MusicXML 转换为 ABCX"""
        xml_file = self.pianocore_root / "PianoCoRe" / "raw" / xml_path
        if not xml_file.exists():
            raise FileNotFoundError(f"XML file not found: {xml_file}")

        try:
            abcx_content = xml_to_abcx(str(xml_file))
            return abcx_content
        except Exception as e:
            print(f"Error converting {xml_path} to ABCX: {e}")
            return None

    def extract_measures_from_score(self, score: music21.stream.Score) -> List[Dict]:
        """从 score 中提取小节信息"""
        measures = []

        for part in score.parts:
            for measure in part.getElementsByClass('Measure'):
                measure_info = {
                    'number': measure.number,
                    'offset': measure.offset,
                    'duration': measure.duration.quarterLength,
                    'notes': []
                }

                for note in measure.flatten().notes:
                    if note.isNote:
                        measure_info['notes'].append({
                            'pitch': note.pitch.midi,
                            'offset': note.offset,
                            'duration': note.duration.quarterLength,
                        })
                    elif note.isChord:
                        for pitch in note.pitches:
                            measure_info['notes'].append({
                                'pitch': pitch.midi,
                                'offset': note.offset,
                                'duration': note.duration.quarterLength,
                            })

                measures.append(measure_info)

        return measures

    def midi_to_tsv_with_alignment(
        self,
        midi: pretty_midi.PrettyMIDI,
        alignment: Dict,
        score_measures: List[Dict]
    ) -> List[str]:
        """
        将 MIDI + alignment 转换为 MIDI-TSV 格式，按小节对齐
        返回：按小节分组的 MIDI-TSV 字符串列表
        """
        # 获取所有 piano notes
        piano_notes = []
        for instrument in midi.instruments:
            if not instrument.is_drum:
                for note in instrument.notes:
                    piano_notes.append({
                        'pitch': note.pitch,
                        'start': note.start,
                        'end': note.end,
                        'velocity': note.velocity,
                    })

        # 按 start time 排序
        piano_notes.sort(key=lambda x: x['start'])

        # 使用 alignment 将 performance notes 映射到 score measures
        perf_to_score = alignment.get('perf_to_score', None)
        score_notes = alignment.get('score_notes', None)

        if perf_to_score is None or score_notes is None:
            print("Warning: No alignment data")
            return []

        # 将 performance notes 按 measure 分组
        measure_groups = {}

        for perf_idx, note in enumerate(piano_notes):
            if perf_idx < len(perf_to_score):
                score_idx = perf_to_score[perf_idx]
                if score_idx >= 0 and score_idx < len(score_notes):
                    # 找到对应的 measure
                    score_note = score_notes[score_idx]
                    measure_num = self._find_measure_for_note(score_note, score_measures)

                    if measure_num not in measure_groups:
                        measure_groups[measure_num] = []
                    measure_groups[measure_num].append(note)

        # 生成每个 measure 的 MIDI-TSV
        measure_tsvs = []
        for measure_num in sorted(measure_groups.keys()):
            notes = measure_groups[measure_num]
            if not notes:
                continue

            # 计算相对时间（相对于 measure 开始）
            measure_start = min(n['start'] for n in notes)

            tsv_lines = []
            tsv_lines.append("M\t0")  # Measure marker

            for note in notes:
                rel_start = (note['start'] - measure_start) * 1000  # 转换为毫秒
                rel_end = (note['end'] - measure_start) * 1000
                duration = rel_end - rel_start

                tsv_lines.append(
                    f"N\t{int(rel_start)}\t{note['pitch']}\t{int(duration)}\t{note['velocity']}"
                )

            measure_tsvs.append('\n'.join(tsv_lines))

        return measure_tsvs

    def _find_measure_for_note(self, score_note: Dict, measures: List[Dict]) -> int:
        """根据 score note 的 offset 找到对应的 measure"""
        note_offset = score_note.get('offset', 0)

        for measure in measures:
            measure_start = measure['offset']
            measure_end = measure_start + measure['duration']

            if measure_start <= note_offset < measure_end:
                return measure['number']

        # 如果找不到，返回最后一个 measure
        return measures[-1]['number'] if measures else 0

    def process_one_pair(self, row: pd.Series) -> Optional[Dict]:
        """处理一对 score-performance 数据"""
        try:
            # 1. 加载数据
            score_xml_path = row['score_xml_path']
            perf_midi_path = row['refined_performance_midi_path']
            align_path = row['refined_alignment_path']

            # 2. 转换 score 到 ABCX
            abcx_content = self.score_to_abcx(score_xml_path)
            if abcx_content is None:
                return None

            # 3. 加载 alignment 和 MIDI
            alignment = self.load_alignment(align_path)
            perf_midi = self.load_midi(perf_midi_path)
            score = self.load_score_xml(score_xml_path)

            # 4. 提取 score measures
            score_measures = self.extract_measures_from_score(score)

            # 5. 生成 MIDI-TSV（按小节）
            measure_tsvs = self.midi_to_tsv_with_alignment(
                perf_midi, alignment, score_measures
            )

            return {
                'id': row['id'],
                'composer': row['composer'],
                'composition': row['composition'],
                'abcx': abcx_content,
                'measure_tsvs': measure_tsvs,
                'num_measures': len(measure_tsvs),
            }

        except Exception as e:
            print(f"Error processing {row['id']}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def process_all(self, limit: Optional[int] = None):
        """批量处理所有 Tier A 数据"""
        data_to_process = self.tier_a_data.head(limit) if limit else self.tier_a_data

        results = []
        for idx, row in tqdm(data_to_process.iterrows(), total=len(data_to_process)):
            result = self.process_one_pair(row)
            if result:
                results.append(result)

        # 保存结果
        output_file = self.output_dir / "pianocore_a_processed.jsonl"
        with open(output_file, 'w') as f:
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False) + '\n')

        print(f"\n处理完成！")
        print(f"成功处理: {len(results)} / {len(data_to_process)}")
        print(f"输出文件: {output_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Process PianoCoRe-A dataset')
    parser.add_argument('--pianocore-root', type=str, required=True,
                        help='PianoCoRe 数据集根目录')
    parser.add_argument('--output-dir', type=str, required=True,
                        help='输出目录')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制处理数量（用于测试）')

    args = parser.parse_args()

    processor = PianoCoreProcessor(args.pianocore_root, args.output_dir)
    processor.process_all(limit=args.limit)


if __name__ == '__main__':
    main()
