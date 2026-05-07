#!/usr/bin/env python3
"""
生成 ABCX-MIDI 配对数据集

数据结构：
- 一个 ABCX 对应多个 MIDI 演奏
- 每个 (ABCX, MIDI) pair 生成一个 JSON 文件
- 每个 JSON 包含多个 segments

输出文件命名：
- Composer_Work_Performer.json
"""

import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple
import subprocess

sys.path.insert(0, str(Path(__file__).parent))
from abcx_parser import ABCXParser, ABCXDocument
from score_based_segmentation import ScoreBasedSegmenter


class PairedDatasetGenerator:
    """配对数据集生成器"""

    def __init__(self, abcx_doc: ABCXDocument, midi_tsv_text: str, measure_ticks: List[Tuple[int, int]]):
        self.abcx_doc = abcx_doc
        self.midi_tsv_text = midi_tsv_text
        self.measure_ticks = measure_ticks

        # 解析 MIDI-TSV
        self.midi_tsv_header, self.midi_tsv_data = self._parse_midi_tsv(midi_tsv_text)

        # 从 MIDI-TSV 中提取实际的 Slice 范围，建立小节到 tick 的映射
        self.actual_measure_ticks = self._extract_actual_measure_ticks()

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

    def _extract_actual_measure_ticks(self) -> List[Tuple[int, int, int]]:
        """从 MIDI-TSV 的 Slice 行中提取所有 Slice 的信息

        Returns:
            List of (slice_id, start_tick, end_tick)
        """
        slices = []

        for line in self.midi_tsv_data:
            if not line.strip():
                continue

            fields = line.split('\t')
            if fields[0] == 'S' and len(fields) >= 4:
                slice_id = int(fields[1])
                slice_start = int(fields[2])
                slice_end = int(fields[3])
                slices.append((slice_id, slice_start, slice_end))

        return slices

    def generate_json(self, segments: List[Dict], performer: str = "") -> Dict:
        """
        生成 JSON 格式的配对数据

        Args:
            segments: 切割片段列表
            performer: 演奏者名称

        Returns:
            JSON 数据
        """
        result = {
            "metadata": {
                "title": self.abcx_doc.title,
                "composer": self.abcx_doc.composer,
                "performer": performer,
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

    def generate_json_by_slices(self, segments: List[Dict], performer: str = "") -> Dict:
        """
        基于 MIDI Slice 生成 JSON 格式的配对数据

        Args:
            segments: 切割片段列表（包含 start_slice 和 end_slice）
            performer: 演奏者名称

        Returns:
            JSON 数据
        """
        result = {
            "metadata": {
                "title": self.abcx_doc.title,
                "composer": self.abcx_doc.composer,
                "performer": performer,
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
                "midi_tsv_data": self._extract_midi_tsv_data_by_slices(seg['start_slice'], seg['end_slice'])
            }
            result["segments"].append(segment_data)

        return result

    def _extract_midi_tsv_data_by_slices(self, start_slice: int, end_slice: int) -> str:
        """基于 Slice ID 提取 MIDI-TSV 数据片段"""
        slice_ids_in_range = set(range(start_slice, end_slice + 1))

        # 过滤数据行
        filtered_lines = []
        current_slice_in_range = False

        for line in self.midi_tsv_data:
            if not line.strip():
                # 保留空行
                filtered_lines.append(line)
                continue

            fields = line.split('\t')
            if not fields:
                continue

            record_type = fields[0]

            if record_type == 'S':
                # Slice 行
                if len(fields) >= 2:
                    slice_id = int(fields[1])

                    # 检查这个 Slice 是否在我们的范围内
                    if slice_id in slice_ids_in_range:
                        current_slice_in_range = True
                        filtered_lines.append(line)
                    else:
                        current_slice_in_range = False

            elif record_type == 'T':
                # Track 行
                if current_slice_in_range:
                    filtered_lines.append(line)

            elif current_slice_in_range:
                # 音符或踏板行
                filtered_lines.append(line)

        return '\n'.join(filtered_lines)

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
        # 使用实际的 MIDI-TSV Slice 信息
        if not self.actual_measure_ticks:
            # 如果没有 Slice 信息，返回空
            return ""

        # 获取目标小节的 tick 范围
        measure_start_tick = self.measure_ticks[start_measure - 1][0]
        measure_end_tick = self.measure_ticks[end_measure - 1][1]

        # 找出与这个范围有重叠的所有 Slice
        slice_ids_in_range = set()
        for slice_id, slice_start, slice_end in self.actual_measure_ticks:
            # 检查是否有重叠：slice 的结束 > 小节开始 且 slice 的开始 < 小节结束
            if slice_end > measure_start_tick and slice_start < measure_end_tick:
                slice_ids_in_range.add(slice_id)

        if not slice_ids_in_range:
            # 没有找到对应的 Slice
            return ""

        # 过滤数据行
        filtered_lines = []
        current_slice_in_range = False

        for line in self.midi_tsv_data:
            if not line.strip():
                # 保留空行
                filtered_lines.append(line)
                continue

            fields = line.split('\t')
            if not fields:
                continue

            record_type = fields[0]

            if record_type == 'S':
                # Slice 行
                if len(fields) >= 2:
                    slice_id = int(fields[1])

                    # 检查这个 Slice 是否在我们的范围内
                    if slice_id in slice_ids_in_range:
                        current_slice_in_range = True
                        filtered_lines.append(line)
                    else:
                        current_slice_in_range = False

            elif record_type == 'T':
                # Track 行
                if current_slice_in_range:
                    filtered_lines.append(line)

            elif current_slice_in_range:
                # 音符或踏板行
                filtered_lines.append(line)

        return '\n'.join(filtered_lines)


def generate_midi_tsv(midi_path: Path) -> str:
    """生成 MIDI-TSV 文本"""
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


def process_abcx_midi_pair(
    abcx_path: Path,
    midi_path: Path,
    output_path: Path,
    min_measures: int = 8,
    max_measures: int = 16,
    target_seconds: float = 30.0
) -> Dict:
    """
    处理单个 ABCX-MIDI 配对

    Args:
        abcx_path: ABCX 文件路径
        midi_path: MIDI 文件路径（演奏 MIDI）
        output_path: 输出 JSON 文件路径
        min_measures: 最小小节数
        max_measures: 最大小节数
        target_seconds: 目标时长

    Returns:
        生成的 JSON 数据
    """
    # 提取演奏者名称
    performer = midi_path.stem  # 例如 "Denisova10M"

    print(f"  处理: {abcx_path.stem} - {performer}")

    # 1. 解析 ABCX
    parser = ABCXParser()
    abcx_text = abcx_path.read_text()
    abcx_doc = parser.parse(abcx_text)

    # 2. 生成 MIDI-TSV
    midi_tsv_text = generate_midi_tsv(midi_path)

    # 3. 提取 MIDI-TSV 中的所有 Slices
    lines = midi_tsv_text.split('\n')
    midi_slices = []
    for line in lines:
        if line.startswith('S'):
            fields = line.split('\t')
            if len(fields) >= 4:
                slice_id = int(fields[1])
                midi_slices.append(slice_id)

    if not midi_slices:
        print(f"    警告: 没有找到 MIDI Slices")
        return {}

    # 4. 基于 MIDI Slices 数量来切割
    # 每个 segment 包含若干个连续的 Slices
    total_slices = len(midi_slices)
    num_measures = len(abcx_doc.measures)

    # 估算每个 Slice 对应多少小节
    measures_per_slice = num_measures / total_slices if total_slices > 0 else 1

    # 目标：每个 segment 包含 min_measures 到 max_measures 个小节
    # 计算需要多少个 Slices
    target_measures = (min_measures + max_measures) / 2
    slices_per_segment = max(1, int(target_measures / measures_per_slice))

    # 生成 segments
    segments = []
    segment_id = 1
    slice_idx = 0

    while slice_idx < total_slices:
        # 确定这个 segment 包含的 Slices
        end_slice_idx = min(slice_idx + slices_per_segment, total_slices)
        start_slice = midi_slices[slice_idx]
        end_slice = midi_slices[end_slice_idx - 1]

        # 估算对应的小节范围
        start_measure = max(1, int(slice_idx * measures_per_slice) + 1)
        end_measure = min(num_measures, int(end_slice_idx * measures_per_slice))

        segments.append({
            'id': segment_id,
            'start_measure': start_measure,
            'end_measure': end_measure,
            'start_slice': start_slice,
            'end_slice': end_slice,
            'num_measures': end_measure - start_measure + 1,
            'duration_seconds': 0.0  # 暂时设为0，实际应该从 MIDI 计算
        })

        segment_id += 1
        slice_idx = end_slice_idx

    # 5. 生成 JSON（使用 Slice 范围而不是 tick 范围）
    generator = PairedDatasetGenerator(abcx_doc, midi_tsv_text, [])

    json_data = generator.generate_json_by_slices(segments, performer=performer)

    # 6. 保存 JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False))

    print(f"    → {len(segments)} 个片段，保存到: {output_path.name}")

    return json_data


def process_asap_dataset(
    data_dir: Path,
    output_dir: Path,
    min_measures: int = 8,
    max_measures: int = 16,
    target_seconds: float = 30.0
):
    """
    处理 ASAP 数据集

    数据结构：
    - 一个作品有一个 ABCX 文件
    - 一个作品有多个 MIDI 演奏文件
    - 每个 (ABCX, MIDI) pair 生成一个 JSON

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

    total_pairs = 0
    total_segments = 0
    success_count = 0

    for abcx_path in abcx_files:
        # 查找对应的 MIDI 目录
        # ABCX 路径: data/abc_from_xml/Composer/Work/SubWork/file.abcx
        # MIDI 路径: data/asap-dataset/Composer/Work/SubWork/*.mid

        # 获取相对于 abc_from_xml 的路径
        rel_path = abcx_path.parent.relative_to(abcx_dir)

        # 构建对应的 MIDI 目录
        midi_work_dir = midi_dir / rel_path

        if not midi_work_dir.exists():
            print(f"警告: 找不到 MIDI 目录: {midi_work_dir}")
            continue

        # 查找所有演奏 MIDI（排除 midi_score.mid）
        midi_files = [f for f in midi_work_dir.glob("*.mid")
                      if f.name != "midi_score.mid"]

        if not midi_files:
            print(f"警告: {rel_path} 没有演奏 MIDI 文件")
            continue

        print(f"\n处理作品: {rel_path} ({len(midi_files)} 个演奏)")

        # 为每个 MIDI 演奏生成一个 JSON
        for midi_path in midi_files:
            performer = midi_path.stem

            # 输出文件名: 使用完整路径构建文件名
            # 例如: Chopin_Etudes_op_25_12_Atzinger03.json
            output_filename = f"{str(rel_path).replace('/', '_')}_{performer}.json"

            # 输出到 composer 目录下
            composer = rel_path.parts[0]
            output_path = output_dir / composer / output_filename

            try:
                json_data = process_abcx_midi_pair(
                    abcx_path=abcx_path,
                    midi_path=midi_path,
                    output_path=output_path,
                    min_measures=min_measures,
                    max_measures=max_measures,
                    target_seconds=target_seconds
                )

                total_pairs += 1
                total_segments += json_data['metadata']['num_segments']
                success_count += 1

            except Exception as e:
                print(f"    错误: {e}")
                import traceback
                traceback.print_exc()

    # 保存全局统计
    stats = {
        'total_abcx_files': len(abcx_files),
        'total_pairs': total_pairs,
        'total_segments': total_segments,
        'avg_segments_per_pair': total_segments / total_pairs if total_pairs > 0 else 0
    }

    stats_path = output_dir / "dataset_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))

    print(f"\n数据集处理完成:")
    print(f"  总作品数: {stats['total_abcx_files']}")
    print(f"  总配对数: {stats['total_pairs']}")
    print(f"  总片段数: {stats['total_segments']}")
    print(f"  平均每配对片段数: {stats['avg_segments_per_pair']:.1f}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="生成 ABCX-MIDI 配对数据集")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="数据目录")
    parser.add_argument("--output-dir", type=Path, default=Path("output/paired_dataset"),
                        help="输出目录")
    parser.add_argument("--min-measures", type=int, default=8,
                        help="最小小节数")
    parser.add_argument("--max-measures", type=int, default=16,
                        help="最大小节数")
    parser.add_argument("--target-seconds", type=float, default=30.0,
                        help="目标时长（秒）")
    parser.add_argument("--test", action="store_true",
                        help="测试模式：只处理 Glinka/The_Lark")

    args = parser.parse_args()

    if args.test:
        # 测试模式：只处理一个作品
        print("测试模式：只处理 Glinka/The_Lark")
        abcx_path = args.data_dir / "abc_from_xml" / "Glinka" / "The_Lark" / "Glinka_The_Lark.abcx"
        midi_dir = args.data_dir / "asap-dataset" / "Glinka" / "The_Lark"

        if not abcx_path.exists():
            print(f"错误: 找不到 ABCX 文件: {abcx_path}")
            sys.exit(1)

        midi_files = [f for f in midi_dir.glob("*.mid") if f.name != "midi_score.mid"]

        for midi_path in midi_files:
            performer = midi_path.stem
            output_path = args.output_dir / "Glinka" / f"Glinka_The_Lark_{performer}.json"

            process_abcx_midi_pair(
                abcx_path=abcx_path,
                midi_path=midi_path,
                output_path=output_path,
                min_measures=args.min_measures,
                max_measures=args.max_measures,
                target_seconds=args.target_seconds
            )
    else:
        # 批量处理模式
        process_asap_dataset(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            min_measures=args.min_measures,
            max_measures=args.max_measures,
            target_seconds=args.target_seconds
        )


if __name__ == '__main__':
    main()
