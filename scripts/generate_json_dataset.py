#!/usr/bin/env python3
"""
生成 JSON 格式的 ABCX-MIDI 配对数据集

输出格式：每个作品一个 JSON 文件，包含：
- 完整的 ABCX header 和 MIDI-TSV header
- 多个 segments，每个 segment 包含 ABCX 和 MIDI-TSV 片段
"""

import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple
import subprocess

sys.path.insert(0, str(Path(__file__).parent))
from abcx_parser import ABCXParser, ABCXDocument, Measure


class JSONDatasetGenerator:
    """JSON 格式数据集生成器"""

    def __init__(self, abcx_doc: ABCXDocument, midi_tsv_text: str, measure_ticks: List[Tuple[int, int]]):
        self.abcx_doc = abcx_doc
        self.midi_tsv_text = midi_tsv_text
        self.measure_ticks = measure_ticks

        # 解析 MIDI-TSV
        self.midi_tsv_header, self.midi_tsv_data = self._parse_midi_tsv(midi_tsv_text)

    def _parse_midi_tsv(self, text: str) -> Tuple[List[str], List[str]]:
        """分离 MIDI-TSV 的 header 和 data"""
        lines = text.split('\n')
        header_lines = []
        data_lines = []
        in_header = True

        for line in lines:
            if line.startswith('#'):
                header_lines.append(line)
            elif not line.strip() and in_header:
                in_header = False
            else:
                data_lines.append(line)

        return header_lines, data_lines

    def generate_json(self, segments: List[Dict]) -> Dict:
        """
        生成 JSON 格式的数据集

        返回格式：
        {
            "metadata": {
                "title": "...",
                "composer": "...",
                "num_measures": 76,
                "num_segments": 5
            },
            "abcx_header": "X:1\\nT:...\\n...",
            "midi_tsv_header": ["# midi-tsv v0.1", "# source=...", ...],
            "segments": [
                {
                    "id": 1,
                    "start_measure": 1,
                    "end_measure": 12,
                    "num_measures": 12,
                    "duration_seconds": 28.5,
                    "abcx_body": "...",
                    "midi_tsv_data": "..."
                },
                ...
            ]
        }
        """
        result = {
            "metadata": {
                "title": self.abcx_doc.title,
                "composer": self.abcx_doc.composer,
                "key": self.abcx_doc.key,
                "time_signature": f"{self.abcx_doc.time_sig.numerator}/{self.abcx_doc.time_sig.denominator}",
                "tempo_bpm": self.abcx_doc.tempo_bpm,
                "num_voices": self.abcx_doc.num_voices,
                "num_measures": len(self.abcx_doc.measures),
                "num_segments": len(segments)
            },
            "abcx_header": self.abcx_doc.header_text,
            "midi_tsv_header": self.midi_tsv_header,
            "segments": []
        }

        for seg in segments:
            segment_data = {
                "id": seg['id'],
                "start_measure": seg['start_measure'],
                "end_measure": seg['end_measure'],
                "num_measures": seg['num_measures'],
                "duration_seconds": seg['duration_seconds'],
                "abcx_body": self._extract_abcx_body(seg['start_measure'], seg['end_measure']),
                "midi_tsv_data": self._extract_midi_tsv_data(seg['start_measure'], seg['end_measure'])
            }
            result["segments"].append(segment_data)

        return result

    def _extract_abcx_body(self, start_measure: int, end_measure: int) -> str:
        """提取 ABCX 曲体片段"""
        measures = [m for m in self.abcx_doc.measures
                    if start_measure <= m.number <= end_measure]

        lines = []
        for measure in measures:
            if not measure.voices:
                continue

            # 多声部用 ; 分隔
            voice_contents = []
            for voice_id in sorted(measure.voices.keys()):
                voice_contents.append(measure.voices[voice_id])

            measure_line = ' ; '.join(voice_contents) + ' ' + measure.bar_type
            lines.append(measure_line)

        return '\n'.join(lines)

    def _extract_midi_tsv_data(self, start_measure: int, end_measure: int) -> str:
        """提取 MIDI-TSV 数据片段"""
        # 获取 tick 范围
        start_tick = self.measure_ticks[start_measure - 1][0]
        end_tick = self.measure_ticks[end_measure - 1][1]

        # 过滤数据行
        filtered_lines = []
        in_range = False

        for line in self.midi_tsv_data:
            if not line.strip():
                if in_range:
                    filtered_lines.append(line)
                continue

            fields = line.split('\t')
            if not fields:
                continue

            record_type = fields[0]

            if record_type == 'S':
                # Slice 行
                if len(fields) >= 4:
                    slice_start = int(fields[2])
                    slice_end = int(fields[3])

                    # 检查是否在范围内（允许部分重叠）
                    if slice_start < end_tick and slice_end > start_tick:
                        in_range = True
                        filtered_lines.append(line)
                    else:
                        in_range = False

            elif record_type == 'T':
                # Track 行
                if in_range:
                    filtered_lines.append(line)

            elif in_range:
                # 音符或踏板行
                filtered_lines.append(line)

        return '\n'.join(filtered_lines)


def process_piece_to_json(
    abcx_path: Path,
    midi_path: Path,
    output_path: Path,
    min_measures: int = 8,
    max_measures: int = 16,
    target_seconds: float = 30.0
) -> Dict:
    """
    处理单个作品，生成 JSON 格式数据

    Args:
        abcx_path: ABCX 文件路径
        midi_path: MIDI 文件路径
        output_path: 输出 JSON 文件路径
        min_measures: 最小小节数
        max_measures: 最大小节数
        target_seconds: 目标时长

    Returns:
        生成的 JSON 数据
    """
    print(f"\n处理: {abcx_path.stem}")

    # 1. 解析 ABCX
    parser = ABCXParser()
    abcx_text = abcx_path.read_text()
    abcx_doc = parser.parse(abcx_text)

    print(f"  ABCX: {len(abcx_doc.measures)} 个小节")

    # 2. 生成 MIDI-TSV
    midi_tsv_text = _generate_midi_tsv(midi_path)

    # 3. 计算小节 ticks
    from score_based_segmentation import MIDIScoreAligner
    aligner = MIDIScoreAligner(midi_path, abcx_doc.measures)
    measure_ticks = [(m.start_tick, m.end_tick) for m in abcx_doc.measures]

    # 4. 执行切割
    from score_based_segmentation import ScoreBasedSegmenter

    segmenter = ScoreBasedSegmenter(
        measures=abcx_doc.measures,
        min_measures=min_measures,
        max_measures=max_measures,
        target_seconds=target_seconds,
        tempo_bpm=abcx_doc.tempo_bpm
    )
    segments = segmenter.segment()

    print(f"  切割: {len(segments)} 个片段")

    # 5. 生成 JSON
    generator = JSONDatasetGenerator(abcx_doc, midi_tsv_text, measure_ticks)

    segment_dicts = [
        {
            'id': seg.id,
            'start_measure': seg.start_measure,
            'end_measure': seg.end_measure,
            'num_measures': seg.num_measures,
            'duration_seconds': seg.duration_seconds
        }
        for seg in segments
    ]

    json_data = generator.generate_json(segment_dicts)

    # 6. 保存 JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False))

    print(f"  保存到: {output_path}")

    return json_data


def _generate_midi_tsv(midi_path: Path) -> str:
    """生成 MIDI-TSV 文本"""
    # 使用 wave-roll-studio 的 midi_tsv.py
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll-studio" / "midi_tsv.py"

    if not midi_tsv_script.exists():
        raise FileNotFoundError(f"找不到 midi_tsv.py: {midi_tsv_script}")

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as f:
        temp_path = Path(f.name)

    try:
        subprocess.run([
            sys.executable,
            str(midi_tsv_script),
            "midi2tsv",
            str(midi_path),
            "--out", str(temp_path)
        ], check=True, capture_output=True)

        midi_tsv_text = temp_path.read_text()
        return midi_tsv_text

    finally:
        if temp_path.exists():
            temp_path.unlink()


def process_dataset_to_json(
    data_dir: Path,
    output_dir: Path,
    min_measures: int = 8,
    max_measures: int = 16,
    target_seconds: float = 30.0
):
    """
    处理整个数据集，每个作品生成一个 JSON 文件

    Args:
        data_dir: 数据目录
        output_dir: 输出目录
        min_measures: 最小小节数
        max_measures: 最大小节数
        target_seconds: 目标时长
    """
    abcx_dir = data_dir / "abc_from_xml"
    midi_dir = data_dir / "asap-dataset"

    output_dir.mkdir(parents=True, exist_ok=True)

    # 遍历所有 ABCX 文件
    abcx_files = list(abcx_dir.rglob("*.abcx"))

    print(f"找到 {len(abcx_files)} 个 ABCX 文件")

    total_segments = 0
    success_count = 0

    for abcx_path in abcx_files:
        # 查找对应的 MIDI 文件
        work_dir = abcx_path.parent
        midi_path = work_dir.parent.parent / "asap-dataset" / work_dir.parent.name / work_dir.name / "midi_score.mid"

        if not midi_path.exists():
            print(f"警告: 找不到 MIDI 文件: {midi_path}")
            continue

        # 输出 JSON 文件路径
        output_path = output_dir / work_dir.parent.name / f"{work_dir.name}.json"

        try:
            json_data = process_piece_to_json(
                abcx_path=abcx_path,
                midi_path=midi_path,
                output_path=output_path,
                min_measures=min_measures,
                max_measures=max_measures,
                target_seconds=target_seconds
            )

            total_segments += json_data['metadata']['num_segments']
            success_count += 1

        except Exception as e:
            print(f"错误: 处理 {abcx_path.stem} 时出错: {e}")
            import traceback
            traceback.print_exc()

    # 保存全局统计
    stats = {
        'total_pieces': len(abcx_files),
        'success_pieces': success_count,
        'total_segments': total_segments,
        'avg_segments_per_piece': total_segments / success_count if success_count > 0 else 0
    }

    stats_path = output_dir / "dataset_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))

    print(f"\n数据集处理完成:")
    print(f"  总作品数: {stats['total_pieces']}")
    print(f"  成功处理: {stats['success_pieces']}")
    print(f"  总片段数: {stats['total_segments']}")
    print(f"  平均每作品片段数: {stats['avg_segments_per_piece']:.1f}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="生成 JSON 格式的 ABCX-MIDI 配对数据集")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="数据目录")
    parser.add_argument("--output-dir", type=Path, default=Path("output/json_dataset"),
                        help="输出目录")
    parser.add_argument("--min-measures", type=int, default=8,
                        help="最小小节数")
    parser.add_argument("--max-measures", type=int, default=16,
                        help="最大小节数")
    parser.add_argument("--target-seconds", type=float, default=30.0,
                        help="目标时长（秒）")
    parser.add_argument("--single", type=Path,
                        help="只处理单个 ABCX 文件（用于测试）")

    args = parser.parse_args()

    if args.single:
        # 单文件模式
        abcx_path = args.single
        work_dir = abcx_path.parent
        midi_path = work_dir.parent.parent / "asap-dataset" / work_dir.parent.name / work_dir.name / "midi_score.mid"

        if not midi_path.exists():
            print(f"错误: 找不到 MIDI 文件: {midi_path}")
            sys.exit(1)

        output_path = args.output_dir / work_dir.parent.name / f"{work_dir.name}.json"

        process_piece_to_json(
            abcx_path=abcx_path,
            midi_path=midi_path,
            output_path=output_path,
            min_measures=args.min_measures,
            max_measures=args.max_measures,
            target_seconds=args.target_seconds
        )
    else:
        # 批量处理模式
        process_dataset_to_json(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            min_measures=args.min_measures,
            max_measures=args.max_measures,
            target_seconds=args.target_seconds
        )


if __name__ == '__main__':
    main()
