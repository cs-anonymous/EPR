#!/usr/bin/env python3
"""
Score-based MIDI-ABCX Segmentation

基于谱子乐句结构的 MIDI-ABCX 切割方案。
与启发式切割不同，此方案根据乐谱的小节边界、乐句标记、重复记号等结构信息进行切割。

核心思路：
1. 解析 ABCX，提取小节边界、乐句标记（slur、phrase）、重复记号
2. 解析 MIDI，建立 tick 到小节号的映射
3. 根据乐句结构确定切割点（优先在句末、重复记号、长休止后）
4. 生成配对的 ABCX 片段和 MIDI-TSV 片段
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class Measure:
    """小节信息"""
    number: int  # 小节号（从1开始）
    start_tick: int  # 起始 tick
    end_tick: int  # 结束 tick
    time_sig: Tuple[int, int]  # 拍号 (numerator, denominator)
    has_repeat_start: bool = False  # 是否有重复开始记号 |:
    has_repeat_end: bool = False  # 是否有重复结束记号 :|
    has_double_bar: bool = False  # 是否有双小节线 ||
    has_final_bar: bool = False  # 是否有终止线 |]
    phrase_end: bool = False  # 是否是乐句结束
    has_long_rest: bool = False  # 是否包含长休止（>=2拍）


@dataclass
class Segment:
    """切割片段"""
    id: int
    start_measure: int  # 起始小节号
    end_measure: int  # 结束小节号（包含）
    start_tick: int
    end_tick: int
    duration_seconds: float
    num_measures: int


class ABCXParser:
    """ABCX 解析器，提取小节和乐句结构"""

    def __init__(self):
        self.measures: List[Measure] = []
        self.time_sig = (4, 4)  # 默认拍号
        self.unit_length = 1/16  # 默认单位长度
        self.tempo_bpm = 120  # 默认速度

    def parse_header(self, lines: List[str]) -> Dict:
        """解析 ABCX 头部"""
        header = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith('%'):
                continue
            if line.startswith('M:'):
                # 拍号
                m = re.match(r'M:\s*(\d+)/(\d+)', line)
                if m:
                    self.time_sig = (int(m.group(1)), int(m.group(2)))
                    header['time_sig'] = self.time_sig
            elif line.startswith('L:'):
                # 单位长度
                m = re.match(r'L:\s*(\d+)/(\d+)', line)
                if m:
                    self.unit_length = int(m.group(1)) / int(m.group(2))
                    header['unit_length'] = self.unit_length
            elif line.startswith('Q:'):
                # 速度
                m = re.match(r'Q:\s*(\d+)/(\d+)\s*=\s*(\d+)', line)
                if m:
                    beat_unit = int(m.group(1)) / int(m.group(2))
                    bpm = int(m.group(3))
                    # 转换为四分音符速度
                    self.tempo_bpm = bpm * (beat_unit / 0.25)
                    header['tempo_bpm'] = self.tempo_bpm
        return header

    def parse_body(self, body_text: str) -> List[Measure]:
        """解析 ABCX 曲体，提取小节信息"""
        # 移除注释
        body_text = re.sub(r'%.*$', '', body_text, flags=re.MULTILINE)

        # 按行处理
        lines = body_text.strip().split('\n')
        measure_num = 0
        current_tick = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否有 inline 拍号变化
            m = re.search(r'\[M:\s*(\d+)/(\d+)\]', line)
            if m:
                self.time_sig = (int(m.group(1)), int(m.group(2)))

            # 分割小节（按 | 分隔）
            # 注意：需要处理 |: :| || |] 等特殊小节线
            measures_in_line = self._split_measures(line)

            for measure_content, bar_type in measures_in_line:
                if not measure_content.strip():
                    continue

                measure_num += 1

                # 计算小节时值（单位：quarter notes）
                duration_ql = self._calculate_measure_duration(measure_content)

                # 转换为 ticks（假设 tpq=480）
                tpq = 480
                duration_ticks = int(duration_ql * tpq)

                measure = Measure(
                    number=measure_num,
                    start_tick=current_tick,
                    end_tick=current_tick + duration_ticks,
                    time_sig=self.time_sig,
                    has_repeat_start='|:' in bar_type or ':' in bar_type and bar_type.startswith(':'),
                    has_repeat_end=':|' in bar_type or ':' in bar_type and bar_type.endswith(':'),
                    has_double_bar='||' in bar_type,
                    has_final_bar='|]' in bar_type,
                    phrase_end=self._detect_phrase_end(measure_content),
                    has_long_rest=self._has_long_rest(measure_content)
                )

                self.measures.append(measure)
                current_tick += duration_ticks

        return self.measures

    def _split_measures(self, line: str) -> List[Tuple[str, str]]:
        """分割小节，返回 (小节内容, 小节线类型) 列表"""
        # 匹配小节线：|: :| || |] | 等
        bar_pattern = r'(\|\:|\:\||\|\||\|\]|\|)'

        parts = re.split(bar_pattern, line)
        measures = []

        i = 0
        while i < len(parts):
            content = parts[i]
            bar_type = parts[i+1] if i+1 < len(parts) else '|'

            if content.strip():
                measures.append((content, bar_type))

            i += 2

        return measures

    def _calculate_measure_duration(self, content: str) -> float:
        """计算小节时值（单位：quarter notes）"""
        # 简化实现：根据拍号计算
        # 实际应该解析所有音符和休止符的时值
        numerator, denominator = self.time_sig
        return (numerator / denominator) * 4  # 转换为 quarter notes

    def _detect_phrase_end(self, content: str) -> bool:
        """检测是否是乐句结束"""
        # 检查是否有圆滑线结束标记 )
        # 检查是否有 fermata 延长记号
        # 检查是否有长时值音符（>=2拍）
        if ')' in content or '!fermata!' in content:
            return True
        return False

    def _has_long_rest(self, content: str) -> bool:
        """检测是否有长休止"""
        # 检查是否有 z2 z4 z8 等长休止
        if re.search(r'z[2-9]|z1[0-9]', content):
            return True
        return False


class MIDIScoreAligner:
    """MIDI 与乐谱对齐器"""

    def __init__(self, midi_path: Path, abcx_measures: List[Measure]):
        self.midi_path = midi_path
        self.abcx_measures = abcx_measures
        self.measure_tick_map: Dict[int, Tuple[int, int]] = {}

    def align(self) -> Dict[int, Tuple[int, int]]:
        """
        对齐 MIDI 和 ABCX，建立小节号到 tick 范围的映射

        返回: {measure_number: (start_tick, end_tick)}
        """
        # 从 ASAP 数据集的 midi_score.mid 中提取拍号变化
        # 然后根据拍号计算每个小节的 tick 范围

        # 简化实现：假设 MIDI 和 ABCX 的小节对齐是准确的
        # 实际应该使用 ASAP 数据集提供的对齐信息

        for measure in self.abcx_measures:
            self.measure_tick_map[measure.number] = (measure.start_tick, measure.end_tick)

        return self.measure_tick_map


class ScoreBasedSegmenter:
    """基于乐谱结构的切割器"""

    def __init__(
        self,
        measures: List[Measure],
        measure_ticks: List[Tuple[int, int]],
        min_measures: int = 8,
        max_measures: int = 16,
        target_seconds: float = 30.0,
        tempo_bpm: float = 120.0
    ):
        self.measures = measures
        self.measure_ticks = measure_ticks
        self.min_measures = min_measures
        self.max_measures = max_measures
        self.target_seconds = target_seconds
        self.tempo_bpm = tempo_bpm

    def segment(self) -> List[Segment]:
        """执行切割"""
        segments = []
        segment_id = 1
        start_idx = 0

        while start_idx < len(self.measures):
            # 寻找最佳切割点
            end_idx = self._find_best_cut_point(start_idx)

            if end_idx is None:
                # 剩余小节不足，全部作为最后一个片段
                end_idx = len(self.measures) - 1

            # 创建片段
            start_measure = self.measures[start_idx]
            end_measure = self.measures[end_idx]

            start_tick = self.measure_ticks[start_idx][0]
            end_tick = self.measure_ticks[end_idx][1]

            duration_ticks = end_tick - start_tick
            duration_seconds = self._ticks_to_seconds(duration_ticks)

            segment = Segment(
                id=segment_id,
                start_measure=start_measure.number,
                end_measure=end_measure.number,
                start_tick=start_tick,
                end_tick=end_tick,
                duration_seconds=duration_seconds,
                num_measures=end_idx - start_idx + 1
            )

            segments.append(segment)
            segment_id += 1
            start_idx = end_idx + 1

        return segments

    def _find_best_cut_point(self, start_idx: int) -> Optional[int]:
        """
        寻找最佳切割点

        优先级：
        1. 重复记号结束 :|
        2. 终止线 |]
        3. 双小节线 ||
        4. 乐句结束（圆滑线、fermata）
        5. 长休止后
        6. 达到目标长度
        """
        min_idx = start_idx + self.min_measures - 1
        max_idx = min(start_idx + self.max_measures - 1, len(self.measures) - 1)

        if min_idx >= len(self.measures):
            return None

        # 在 [min_idx, max_idx] 范围内寻找最佳切割点
        candidates = []

        for idx in range(min_idx, max_idx + 1):
            measure = self.measures[idx]
            score = 0

            # 计算切割点得分（分数越高越好）
            if measure.has_repeat_end:
                score += 100
            if measure.has_final_bar:
                score += 90
            if measure.has_double_bar:
                score += 80
            if measure.phrase_end:
                score += 70
            if measure.has_long_rest:
                score += 60

            # 考虑时长接近目标
            start_tick = self.measure_ticks[start_idx][0]
            end_tick = self.measure_ticks[idx][1]
            duration_ticks = end_tick - start_tick
            duration_seconds = self._ticks_to_seconds(duration_ticks)
            time_diff = abs(duration_seconds - self.target_seconds)
            time_score = max(0, 50 - time_diff)
            score += time_score

            candidates.append((idx, score))

        # 选择得分最高的切割点
        if candidates:
            best_idx, best_score = max(candidates, key=lambda x: x[1])
            return best_idx

        return max_idx

    def _ticks_to_seconds(self, ticks: int, tpq: int = 480) -> float:
        """将 ticks 转换为秒"""
        beats = ticks / tpq
        seconds = beats / (self.tempo_bpm / 60)
        return seconds


def segment_abcx_midi_pair(
    abcx_path: Path,
    midi_path: Path,
    output_dir: Path,
    min_measures: int = 8,
    max_measures: int = 16,
    target_seconds: float = 30.0
) -> List[Dict]:
    """
    对 ABCX 和 MIDI 进行配对切割

    Args:
        abcx_path: ABCX 文件路径
        midi_path: MIDI 文件路径（通常是 midi_score.mid）
        output_dir: 输出目录
        min_measures: 最小小节数
        max_measures: 最大小节数
        target_seconds: 目标时长（秒）

    Returns:
        切割信息列表
    """
    # 1. 解析 ABCX
    parser = ABCXParser()
    abcx_text = abcx_path.read_text()

    # 分离头部和曲体
    lines = abcx_text.split('\n')
    header_end = 0
    for i, line in enumerate(lines):
        if line.strip() and not line.startswith(('X:', 'T:', 'C:', 'M:', 'L:', 'Q:', 'K:', 'V:', '%%', '%')):
            header_end = i
            break

    header_lines = lines[:header_end]
    body_text = '\n'.join(lines[header_end:])

    header = parser.parse_header(header_lines)
    measures = parser.parse_body(body_text)

    print(f"解析 ABCX: {len(measures)} 个小节")

    # 2. 对齐 MIDI 和 ABCX
    aligner = MIDIScoreAligner(midi_path, measures)
    measure_tick_map = aligner.align()

    # 3. 执行切割
    segmenter = ScoreBasedSegmenter(
        measures=measures,
        min_measures=min_measures,
        max_measures=max_measures,
        target_seconds=target_seconds,
        tempo_bpm=header.get('tempo_bpm', 120.0)
    )
    segments = segmenter.segment()

    print(f"生成 {len(segments)} 个片段")

    # 4. 输出切割信息
    output_dir.mkdir(parents=True, exist_ok=True)

    segment_info = []
    for seg in segments:
        info = {
            'id': seg.id,
            'start_measure': seg.start_measure,
            'end_measure': seg.end_measure,
            'start_tick': seg.start_tick,
            'end_tick': seg.end_tick,
            'duration_seconds': seg.duration_seconds,
            'num_measures': seg.num_measures
        }
        segment_info.append(info)

    # 保存切割信息
    info_path = output_dir / 'segments.json'
    info_path.write_text(json.dumps(segment_info, indent=2))

    print(f"切割信息已保存到: {info_path}")

    return segment_info


def main():
    """测试"""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python score_based_segmentation.py <abcx_file> <midi_file> [output_dir]")
        sys.exit(1)

    abcx_path = Path(sys.argv[1])
    midi_path = Path(sys.argv[2])
    output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path('./output')

    segment_info = segment_abcx_midi_pair(
        abcx_path=abcx_path,
        midi_path=midi_path,
        output_dir=output_dir
    )

    print("\n切割结果:")
    for info in segment_info:
        print(f"  片段 {info['id']}: 小节 {info['start_measure']}-{info['end_measure']} "
              f"({info['num_measures']} 小节, {info['duration_seconds']:.1f}秒)")


if __name__ == '__main__':
    main()
