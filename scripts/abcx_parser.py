#!/usr/bin/env python3
"""
ABCX Parser - 解析 ABCX 格式，提取小节和乐句结构

支持：
- 多声部（; 分隔）
- 多轨（& 分隔）
- 时值计算
- 乐句标记识别
- 小节线类型识别
"""

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class TimeSignature:
    """拍号"""
    numerator: int
    denominator: int

    def beats_per_measure(self) -> float:
        """每小节的拍数（以四分音符为单位）"""
        return (self.numerator / self.denominator) * 4


@dataclass
class Measure:
    """小节信息"""
    number: int  # 小节号（从1开始）
    time_sig: TimeSignature  # 拍号
    voices: Dict[int, str] = field(default_factory=dict)  # {voice_id: content}

    # 小节线类型
    bar_type: str = '|'  # |, |:, :|, ||, |], |1, |2

    # 结构标记
    has_repeat_start: bool = False  # |:
    has_repeat_end: bool = False  # :|
    has_double_bar: bool = False  # ||
    has_final_bar: bool = False  # |]
    is_first_ending: bool = False  # |1
    is_second_ending: bool = False  # |2

    # 乐句标记
    phrase_end: bool = False  # 圆滑线结束 )
    has_fermata: bool = False  # 延长记号
    has_long_rest: bool = False  # 长休止（>=2拍）

    # 时值信息
    duration_ql: float = 0.0  # 小节时值（quarter notes）


@dataclass
class ABCXDocument:
    """ABCX 文档"""
    # 头部信息
    index: int = 1
    title: str = ""
    composer: str = ""
    time_sig: TimeSignature = field(default_factory=lambda: TimeSignature(4, 4))
    unit_length: float = 1/16  # L:1/16
    tempo_bpm: float = 120.0  # Q:1/4=120
    key: str = "C"

    # 声部信息
    num_voices: int = 1
    voice_names: Dict[int, str] = field(default_factory=dict)

    # 小节列表
    measures: List[Measure] = field(default_factory=list)

    # 原始文本
    header_text: str = ""
    body_text: str = ""


class ABCXParser:
    """ABCX 解析器"""

    # ABC 音符正则
    NOTE_PATTERN = re.compile(
        r"[_^=]*[A-Ga-g][',]*"  # 音高
        r"(?:\d+(?:/\d+)?|/+)?"  # 时值
    )

    # 休止符正则
    REST_PATTERN = re.compile(r"z(?:\d+(?:/\d+)?|/+)?")

    # 和弦正则
    CHORD_PATTERN = re.compile(r"\[[^\]]+\](?:\d+(?:/\d+)?|/+)?")

    def __init__(self):
        self.doc = ABCXDocument()

    def parse(self, text: str) -> ABCXDocument:
        """解析 ABCX 文本"""
        lines = text.split('\n')

        # 分离头部和曲体
        header_lines, body_lines = self._split_header_body(lines)

        # 解析头部
        self._parse_header(header_lines)

        # 解析曲体
        self._parse_body(body_lines)

        return self.doc

    def _split_header_body(self, lines: List[str]) -> Tuple[List[str], List[str]]:
        """分离头部和曲体"""
        header_lines = []
        body_lines = []
        in_body = False

        for line in lines:
            stripped = line.strip()

            # 空行或注释
            if not stripped or stripped.startswith('%'):
                if in_body:
                    body_lines.append(line)
                else:
                    header_lines.append(line)
                continue

            # 头部字段
            if stripped.startswith(('X:', 'T:', 'C:', 'M:', 'L:', 'Q:', 'K:', 'V:', '%%')):
                header_lines.append(line)
                # K: 是最后一个头部字段
                if stripped.startswith('K:'):
                    in_body = True
            else:
                in_body = True
                body_lines.append(line)

        return header_lines, body_lines

    def _parse_header(self, lines: List[str]):
        """解析头部"""
        for line in lines:
            line = line.strip()

            if line.startswith('X:'):
                self.doc.index = int(line[2:].strip())

            elif line.startswith('T:'):
                self.doc.title = line[2:].strip()

            elif line.startswith('C:'):
                self.doc.composer = line[2:].strip()

            elif line.startswith('M:'):
                # 拍号
                m = re.match(r'M:\s*(\d+)/(\d+)', line)
                if m:
                    self.doc.time_sig = TimeSignature(int(m.group(1)), int(m.group(2)))

            elif line.startswith('L:'):
                # 单位长度
                m = re.match(r'L:\s*(\d+)/(\d+)', line)
                if m:
                    self.doc.unit_length = int(m.group(1)) / int(m.group(2))

            elif line.startswith('Q:'):
                # 速度
                m = re.match(r'Q:\s*(\d+)/(\d+)\s*=\s*(\d+)', line)
                if m:
                    beat_unit = int(m.group(1)) / int(m.group(2))
                    bpm = int(m.group(3))
                    # 转换为四分音符速度
                    self.doc.tempo_bpm = bpm * (beat_unit / 0.25)

            elif line.startswith('K:'):
                # 调号
                self.doc.key = line[2:].strip().split()[0]

            elif line.startswith('V:'):
                # 声部定义
                m = re.match(r'V:\s*(\d+)', line)
                if m:
                    voice_id = int(m.group(1))
                    # 提取声部名称
                    name_match = re.search(r'name="([^"]+)"', line)
                    if name_match:
                        self.doc.voice_names[voice_id] = name_match.group(1)

            elif line.startswith('%%score'):
                # 声部分组
                # %%score (V1) (V2) 或 %%score (V1 V2) (V3 V4)
                voices = re.findall(r'V(\d+)', line)
                self.doc.num_voices = len(voices)

        self.doc.header_text = '\n'.join(lines)

    def _parse_body(self, lines: List[str]):
        """解析曲体"""
        measure_num = 0
        current_time_sig = self.doc.time_sig

        for line in lines:
            line = line.strip()

            # 空行或注释
            if not line or line.startswith('%'):
                continue

            # 检查 inline 拍号变化
            m = re.search(r'\[M:\s*(\d+)/(\d+)\]', line)
            if m:
                current_time_sig = TimeSignature(int(m.group(1)), int(m.group(2)))

            # 分割小节
            measures_in_line = self._split_measures(line)

            for measure_content, bar_type in measures_in_line:
                if not measure_content.strip():
                    continue

                measure_num += 1

                # 解析小节内容
                measure = self._parse_measure(
                    measure_num,
                    measure_content,
                    bar_type,
                    current_time_sig
                )

                self.doc.measures.append(measure)

        self.doc.body_text = '\n'.join(lines)

    def _split_measures(self, line: str) -> List[Tuple[str, str]]:
        """
        分割小节，返回 (小节内容, 小节线类型) 列表

        小节线类型：
        - | : 普通小节线
        - |: : 重复开始
        - :| : 重复结束
        - || : 双小节线
        - |] : 终止线
        - |1, |2 : 不同结尾
        """
        # 匹配小节线
        bar_pattern = r'(\|\:|\:\||\|\||:\||:\||\|\]|\|1|\|2|\|)'

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

    def _parse_measure(
        self,
        measure_num: int,
        content: str,
        bar_type: str,
        time_sig: TimeSignature
    ) -> Measure:
        """解析单个小节"""
        measure = Measure(
            number=measure_num,
            time_sig=time_sig,
            bar_type=bar_type
        )

        # 识别小节线类型
        measure.has_repeat_start = '|:' in bar_type or bar_type.startswith(':')
        measure.has_repeat_end = ':|' in bar_type or bar_type.endswith(':')
        measure.has_double_bar = '||' in bar_type
        measure.has_final_bar = '|]' in bar_type
        measure.is_first_ending = '|1' in bar_type
        measure.is_second_ending = '|2' in bar_type

        # 分割声部（; 分隔）
        voices = content.split(';')
        for voice_id, voice_content in enumerate(voices, start=1):
            measure.voices[voice_id] = voice_content.strip()

        # 计算小节时值
        measure.duration_ql = self._calculate_duration(voices[0] if voices else '', time_sig)

        # 识别乐句标记
        measure.phrase_end = ')' in content
        measure.has_fermata = '!fermata!' in content
        measure.has_long_rest = self._has_long_rest(content)

        return measure

    def _calculate_duration(self, voice_content: str, time_sig: TimeSignature) -> float:
        """
        计算声部内容的时值（单位：quarter notes）

        简化实现：直接使用拍号计算
        完整实现需要解析所有音符和休止符
        """
        # 移除装饰和标记
        content = re.sub(r'![\w()]+!', '', voice_content)  # 移除 !pp! !fermata! 等
        content = re.sub(r'"[^"]*"', '', content)  # 移除和弦标记 "Cm"
        content = re.sub(r'\[M:[^\]]+\]', '', content)  # 移除 inline 拍号
        content = re.sub(r'\[Q:[^\]]+\]', '', content)  # 移除 inline 速度

        # 分割多轨（& 分隔）
        tracks = content.split('&')

        # 计算第一轨的时值
        if tracks:
            duration = self._calculate_track_duration(tracks[0])
            if duration > 0:
                return duration

        # 如果无法计算，使用拍号
        return time_sig.beats_per_measure()

    def _calculate_track_duration(self, track_content: str) -> float:
        """计算单轨时值"""
        total_ql = 0.0

        # 移除圆滑线和连音线
        track_content = re.sub(r'[()]', '', track_content)

        # 查找所有音符、休止符、和弦
        tokens = []
        tokens.extend(self.NOTE_PATTERN.findall(track_content))
        tokens.extend(self.REST_PATTERN.findall(track_content))
        tokens.extend(self.CHORD_PATTERN.findall(track_content))

        for token in tokens:
            duration = self._parse_duration(token)
            total_ql += duration

        return total_ql

    def _parse_duration(self, token: str) -> float:
        """
        解析音符/休止符的时值

        ABC 时值规则（假设 L:1/16）：
        - 无数字：1 个单位 = 1/16 = 0.25 quarter notes
        - 2: 2 个单位 = 2/16 = 0.5 quarter notes
        - 4: 4 个单位 = 4/16 = 1.0 quarter notes
        - /: 减半 = 1/32 = 0.125 quarter notes
        - //: 减半再减半 = 1/64 = 0.0625 quarter notes
        - 3/2: 1.5 个单位 = 1.5/16 = 0.375 quarter notes
        """
        # 提取时值部分
        duration_match = re.search(r'(\d+(?:/\d+)?|/+)$', token)

        if not duration_match:
            # 无时值标记，使用单位长度
            return self.doc.unit_length * 4  # 转换为 quarter notes

        duration_str = duration_match.group(1)

        # 处理 / 和 //
        if duration_str.startswith('/'):
            slash_count = len(duration_str)
            return (self.doc.unit_length * 4) / (2 ** slash_count)

        # 处理分数 3/2
        if '/' in duration_str:
            parts = duration_str.split('/')
            multiplier = int(parts[0]) / int(parts[1])
        else:
            multiplier = int(duration_str)

        return (self.doc.unit_length * 4) * multiplier

    def _has_long_rest(self, content: str) -> bool:
        """检测是否有长休止（>=2拍）"""
        # 查找 z2, z4, z8 等
        rests = self.REST_PATTERN.findall(content)
        for rest in rests:
            duration = self._parse_duration(rest)
            if duration >= 2.0:  # >= 2 个四分音符
                return True
        return False


def main():
    """测试"""
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage: python abcx_parser.py <abcx_file>")
        sys.exit(1)

    abcx_path = Path(sys.argv[1])
    text = abcx_path.read_text()

    parser = ABCXParser()
    doc = parser.parse(text)

    print(f"标题: {doc.title}")
    print(f"作曲家: {doc.composer}")
    print(f"拍号: {doc.time_sig.numerator}/{doc.time_sig.denominator}")
    print(f"速度: {doc.tempo_bpm:.1f} BPM")
    print(f"调号: {doc.key}")
    print(f"声部数: {doc.num_voices}")
    print(f"小节数: {len(doc.measures)}")
    print()

    # 显示前10个小节
    print("前10个小节:")
    for measure in doc.measures[:10]:
        print(f"  小节 {measure.number}: {measure.bar_type} "
              f"({measure.duration_ql:.2f} ql, "
              f"phrase_end={measure.phrase_end}, "
              f"fermata={measure.has_fermata})")


if __name__ == '__main__':
    main()
