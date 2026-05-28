#!/usr/bin/env python3
"""
ABCX 乐句切割工具
根据乐理启发式算法将 ABCX 文件按乐句切割
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Bar:
    """小节数据结构"""
    content: str  # 原始内容
    index: int  # 小节编号（从1开始）
    voices: List[str] = field(default_factory=list)  # 按 ; 分割的声部列表
    chords: List[str] = field(default_factory=list)  # 和弦标记
    dynamics: List[str] = field(default_factory=list)  # 力度标记
    tempo_changes: List[str] = field(default_factory=list)  # 速度变化
    meter_changes: List[str] = field(default_factory=list)  # 拍号变化
    has_repeat: bool = False  # 反复记号
    has_double_bar: bool = False  # 双小节线
    has_ending: bool = False  # 终止线
    has_fermata: bool = False  # 延长记号
    max_rest_duration: float = 0.0  # 最长休止时值
    max_note_duration: float = 0.0  # 最长音符时值
    has_unclosed_slur: bool = False  # 未闭合圆滑线
    has_unclosed_range: bool = False  # 未闭合范围标记
    rest_voices_count: int = 0  # 有长休止的声部数


@dataclass
class Phrase:
    """乐句数据结构"""
    phrase_id: int
    bar_range: Tuple[int, int]
    bar_count: int
    header: str
    previous_bar: Optional[str]
    content: str


class ABCXParser:
    """ABCX 文件解析器"""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.header = ""
        self.bars: List[Bar] = []
        self.key = "C"  # 默认 C 大调
        self.time_sig = "4/4"  # 默认 4/4 拍
        self.unit_length = "1/8"  # 默认八分音符
        self.total_voices = 0

    def parse(self):
        """解析 ABCX 文件"""
        with open(self.file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 分离头部和曲体
        header_lines = []
        body_lines = []
        in_body = False

        for line in lines:
            line = line.rstrip('\n')
            if not line.strip():
                continue

            # 检测头部字段
            if re.match(r'^[A-Z]:', line):
                if line.startswith('K:'):
                    header_lines.append(line)
                    in_body = True
                    self.key = line.split(':')[1].strip().split()[0]
                elif not in_body:
                    header_lines.append(line)
                    if line.startswith('M:'):
                        self.time_sig = line.split(':')[1].strip()
                    elif line.startswith('L:'):
                        self.unit_length = line.split(':')[1].strip()
            elif line.startswith('%%'):
                header_lines.append(line)
                # 从 %%score 推断声部数
                if '%%score' in line:
                    self.total_voices = self._count_voices_from_score(line)
            elif in_body:
                body_lines.append(line)

        self.header = '\n'.join(header_lines)

        # 解析曲体，按小节分割
        self._parse_body(body_lines)

    def _count_voices_from_score(self, score_line: str) -> int:
        """从 %%score 行推断声部数量"""
        # 提取所有 V 或数字
        voices = re.findall(r'[Vv]?\d+', score_line)
        return len(voices) if voices else 2  # 默认2声部

    def _parse_body(self, body_lines: List[str]):
        """解析曲体，按小节分割"""
        # 合并所有行
        full_body = ' '.join(body_lines)

        # 按 | 分割小节
        bar_contents = re.split(r'(\|[:\]|]?)', full_body)

        current_bar_content = ""
        bar_index = 0

        for i, part in enumerate(bar_contents):
            if part.strip() in ['|', '||', '|:', ':|', '::', '|]', '|1', '|2']:
                # 小节线
                if current_bar_content.strip():
                    bar_index += 1
                    bar = self._parse_bar(current_bar_content.strip(), bar_index)

                    # 检查小节线类型
                    if part in ['|:', ':|', '::']:
                        bar.has_repeat = True
                    elif part == '||':
                        bar.has_double_bar = True
                    elif part == '|]':
                        bar.has_ending = True

                    self.bars.append(bar)
                    current_bar_content = ""
            else:
                current_bar_content += part

        # 处理最后一个小节
        if current_bar_content.strip():
            bar_index += 1
            bar = self._parse_bar(current_bar_content.strip(), bar_index)
            self.bars.append(bar)

    def _parse_bar(self, content: str, index: int) -> Bar:
        """解析单个小节"""
        bar = Bar(content=content, index=index)

        # 按 ; 分割声部
        bar.voices = content.split(';')

        # 提取和弦标记
        bar.chords = re.findall(r'"([^"]+)"', content)

        # 提取力度标记
        bar.dynamics = re.findall(r'!(pp|p|mp|mf|f|ff|fff)!', content)

        # 检测速度变化
        bar.tempo_changes = re.findall(r'\[Q:[^\]]+\]', content)

        # 检测拍号变化
        bar.meter_changes = re.findall(r'\[M:[^\]]+\]', content)

        # 检测 fermata（延长记号）
        bar.has_fermata = 'fermata' in content

        # 检测未闭合的圆滑线
        open_slurs = content.count('(') - content.count(')')
        bar.has_unclosed_slur = open_slurs > 0

        # 检测未闭合的范围标记
        open_crescendo = content.count('!crescendo(!') - content.count('!crescendo)!')
        open_diminuendo = content.count('!diminuendo(!') - content.count('!diminuendo)!')
        bar.has_unclosed_range = (open_crescendo > 0 or open_diminuendo > 0)

        # 分析每个声部的休止和音符时值
        bar.rest_voices_count = 0
        for voice in bar.voices:
            # 计算该声部的休止时值和音符时值
            rest_dur = self._estimate_rest_duration(voice)
            note_dur = self._estimate_max_note_duration(voice)

            bar.max_rest_duration = max(bar.max_rest_duration, rest_dur)
            bar.max_note_duration = max(bar.max_note_duration, note_dur)

            # 估算该声部的总休止时值和总音符时值
            total_rest = self._estimate_total_rest_duration(voice)
            total_note = self._estimate_total_note_duration(voice)

            # 如果休止时值占比 >= 75%，认为该声部主要是休止
            total_duration = total_rest + total_note
            if total_duration > 0 and total_rest / total_duration >= 0.75:
                bar.rest_voices_count += 1

        return bar

    def _estimate_total_rest_duration(self, voice: str) -> float:
        """估算声部中所有休止符的总时值"""
        rests = re.findall(r'z(\d+)?(/\d+)?', voice)
        total = 0.0
        for num, div in rests:
            duration = float(num) if num else 1.0
            if div:
                duration /= float(div[1:])
            total += duration
        return total

    def _estimate_total_note_duration(self, voice: str) -> float:
        """估算声部中所有音符的总时值"""
        notes = re.findall(r'[A-Ga-g][,\']*([\d]+)?(/\d+)?', voice)
        total = 0.0
        for num, div in notes:
            duration = float(num) if num else 1.0
            if div:
                duration /= float(div[1:])
            total += duration
        return total

    def _estimate_rest_duration(self, voice: str) -> float:
        """估算声部中最长的休止时值"""
        # 查找所有休止符 z
        rests = re.findall(r'z(\d+)?(/\d+)?', voice)
        if not rests:
            return 0.0

        max_duration = 0.0
        for num, div in rests:
            duration = float(num) if num else 1.0
            if div:
                duration /= float(div[1:])
            max_duration = max(max_duration, duration)

        return max_duration

    def _estimate_max_note_duration(self, voice: str) -> float:
        """估算声部中最长的音符时值"""
        # 简化：查找数字修饰符
        notes = re.findall(r'[A-Ga-g][,\']*([\d]+)?(/\d+)?', voice)
        if not notes:
            return 0.0

        max_duration = 0.0
        for num, div in notes:
            duration = float(num) if num else 1.0
            if div:
                duration /= float(div[1:])
            max_duration = max(max_duration, duration)

        return max_duration

    def _get_beats_per_bar(self) -> float:
        """获取每小节拍数"""
        if '/' in self.time_sig:
            numerator, _ = self.time_sig.split('/')
            return float(numerator)
        elif self.time_sig == 'C':
            return 4.0
        elif self.time_sig == 'C|':
            return 2.0
        return 4.0


class HarmonicAnalyzer:
    """和声分析器"""

    # 音名到音高类别的映射
    NOTE_TO_PITCH = {
        'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11,
        'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11
    }

    @staticmethod
    def detect_cadence(bar1: Bar, bar2: Bar, key: str) -> Tuple[Optional[str], float]:
        """
        检测终止式
        返回: (类型, 置信度)
        """
        # 优先使用和弦标记
        if bar1.chords and bar2.chords:
            cadence_type = HarmonicAnalyzer._analyze_chord_progression(
                bar1.chords, bar2.chords, key
            )
            return cadence_type, 0.9

        # 和弦标记缺失，进行音高统计分析
        pitches1 = HarmonicAnalyzer._extract_all_pitches(bar1)
        pitches2 = HarmonicAnalyzer._extract_all_pitches(bar2)

        if pitches1 and pitches2:
            chord1 = HarmonicAnalyzer._infer_chord(pitches1, key)
            chord2 = HarmonicAnalyzer._infer_chord(pitches2, key)

            if chord1 and chord2:
                cadence_type = HarmonicAnalyzer._analyze_chord_progression(
                    [chord1], [chord2], key
                )
                return cadence_type, 0.5

        return None, 0.0

    @staticmethod
    def _analyze_chord_progression(chords1: List[str], chords2: List[str], key: str) -> Optional[str]:
        """分析和弦进行"""
        if not chords1 or not chords2:
            return None

        last_chord = chords2[-1]
        prev_chord = chords1[-1]

        # 简化分析：检测 V-I 和 I-V
        tonic = key[0].upper()

        # V-I (完全终止)
        if HarmonicAnalyzer._is_dominant(prev_chord, key) and \
           HarmonicAnalyzer._is_tonic(last_chord, tonic):
            return "perfect"

        # I-V (半终止)
        if HarmonicAnalyzer._is_tonic(prev_chord, tonic) and \
           HarmonicAnalyzer._is_dominant(last_chord, key):
            return "half"

        return None

    @staticmethod
    def _is_tonic(chord: str, tonic: str) -> bool:
        """判断是否为主和弦"""
        return chord.startswith(tonic) and 'm' not in chord.lower()

    @staticmethod
    def _is_dominant(chord: str, key: str) -> bool:
        """判断是否为属和弦"""
        tonic_pitch = HarmonicAnalyzer.NOTE_TO_PITCH.get(key[0].upper(), 0)
        dominant_pitch = (tonic_pitch + 7) % 12

        # 查找对应的音名
        for note, pitch in HarmonicAnalyzer.NOTE_TO_PITCH.items():
            if pitch == dominant_pitch and note.isupper():
                return chord.startswith(note)
        return False

    @staticmethod
    def _extract_all_pitches(bar: Bar) -> List[int]:
        """提取小节中所有声部的音高"""
        pitches = []
        for voice in bar.voices:
            pitches.extend(HarmonicAnalyzer._extract_pitches_from_voice(voice))
        return pitches

    @staticmethod
    def _extract_pitches_from_voice(voice: str) -> List[int]:
        """从声部提取音高序列（忽略装饰音）"""
        pitches = []

        # 移除装饰音
        voice = re.sub(r'[~{}]', '', voice)

        # 提取音符
        notes = re.findall(r'([A-Ga-g])([,\']*)', voice)

        for note, octave_mod in notes:
            base_pitch = HarmonicAnalyzer.NOTE_TO_PITCH.get(note, 0)

            # 计算八度
            if note.isupper():
                octave = 4  # 大写字母默认第4八度
                octave -= octave_mod.count(',')
                octave += octave_mod.count("'")
            else:
                octave = 5  # 小写字母默认第5八度
                octave -= octave_mod.count(',')
                octave += octave_mod.count("'")

            pitch = base_pitch + octave * 12
            pitches.append(pitch)

        return pitches

    @staticmethod
    def _infer_chord(pitches: List[int], key: str) -> Optional[str]:
        """从音高集合推断和弦"""
        if not pitches:
            return None

        # 统计音高类别
        pitch_classes = [p % 12 for p in pitches]
        pitch_counts = Counter(pitch_classes)

        # 获取主音和属音
        tonic_pitch = HarmonicAnalyzer.NOTE_TO_PITCH.get(key[0].upper(), 0)
        dominant_pitch = (tonic_pitch + 7) % 12

        # 检查主和弦 (I)
        if HarmonicAnalyzer._matches_triad(pitch_classes, tonic_pitch):
            return "I"

        # 检查属和弦 (V)
        if HarmonicAnalyzer._matches_triad(pitch_classes, dominant_pitch):
            return "V"

        return None

    @staticmethod
    def _matches_triad(pitch_classes: List[int], root: int) -> bool:
        """检查是否匹配三和弦"""
        third = (root + 4) % 12  # 大三度
        fifth = (root + 7) % 12  # 纯五度

        has_root = root in pitch_classes
        has_third = third in pitch_classes or (root + 3) % 12 in pitch_classes  # 大三度或小三度
        has_fifth = fifth in pitch_classes

        return has_root and (has_third or has_fifth)


class MelodicAnalyzer:
    """旋律分析器"""

    @staticmethod
    def analyze_contour(bar: Bar, key: str) -> Dict:
        """分析旋律轮廓（主要分析最高声部）"""
        if not bar.voices:
            return {}

        # 提取第一声部（最高声部）的音高
        pitches = HarmonicAnalyzer._extract_pitches_from_voice(bar.voices[0])

        if not pitches:
            return {}

        result = {
            "range": max(pitches) - min(pitches),
            "last_note": pitches[-1],
            "direction": "down" if pitches[-1] < pitches[0] else "up",
            "has_leap": False
        }

        # 检测跳进（> 八度）
        for i in range(len(pitches) - 1):
            if abs(pitches[i+1] - pitches[i]) > 12:
                result["has_leap"] = True
                break

        # 检查是否结束在主音
        tonic_pitch = HarmonicAnalyzer.NOTE_TO_PITCH.get(key[0].upper(), 0)
        result["ends_on_tonic"] = (pitches[-1] % 12) == tonic_pitch

        return result


class PhraseSegmenter:
    """乐句切割器"""

    def __init__(self, parser: ABCXParser, config: Dict = None):
        self.parser = parser
        self.config = config or {
            "min_length": 4,
            "max_length": 8,
            "merge_threshold": 10
        }

    def segment(self) -> List[Phrase]:
        """执行乐句切割"""
        if not self.parser.bars:
            return []

        # 计算每个小节的边界得分
        scores = self._compute_boundary_scores()

        # 自适应切割
        segments = self._adaptive_segmentation(scores)

        # 孤段合并
        segments = self._merge_short_segments(segments)

        # 生成乐句对象
        phrases = self._generate_phrases(segments)

        return phrases

    def _compute_boundary_scores(self) -> List[float]:
        """计算每个小节的边界得分"""
        scores = []
        bars = self.parser.bars

        for i in range(len(bars)):
            bar = bars[i]
            next_bar = bars[i + 1] if i + 1 < len(bars) else None

            score = 0.0

            # 规则 1：强制边界
            if bar.has_repeat or bar.has_double_bar or bar.has_ending:
                score += 100

            # fermata（延长记号）是强边界
            if bar.has_fermata:
                score += 100  # 提高 fermata 权重

            # 声部休止比例（动态得分）
            if self.parser.total_voices > 0:
                rest_ratio = bar.rest_voices_count / self.parser.total_voices
                # 全部休止: 150分
                # 大部分休止（80%以上）: 130分
                # 多数休止（60%以上）: 100分
                # 一半休止（50%以上）: 50分
                if rest_ratio >= 1.0:
                    score += 150
                elif rest_ratio >= 0.8:
                    score += 130
                elif rest_ratio >= 0.6:
                    score += 100
                elif rest_ratio >= 0.5:
                    score += 50

            if bar.tempo_changes or bar.meter_changes:
                score += 100

            # 规则 2：强乐句边界
            if next_bar:
                cadence_type, confidence = HarmonicAnalyzer.detect_cadence(
                    bar, next_bar, self.parser.key
                )
                if cadence_type == "perfect":
                    score += 40 * confidence
                elif cadence_type == "half":
                    score += 30 * confidence

            # 长时值音符
            beats_per_bar = self.parser._get_beats_per_bar()
            if bar.max_note_duration >= beats_per_bar:
                score += 50

            # 力度突变
            if next_bar:
                dynamics_jump = self._compute_dynamics_jump(bar, next_bar)
                if dynamics_jump >= 2:
                    score += 50

            # 旋律分析
            melody = MelodicAnalyzer.analyze_contour(bar, self.parser.key)
            if melody.get("direction") == "down" and melody.get("ends_on_tonic"):
                score += 40

            # 规则 3：弱乐句边界
            if melody.get("has_leap"):
                score += 20

            # 动机重复检测
            if next_bar and i > 0:
                if self._detect_motif_repetition(next_bar, bars[0]):
                    score += 60  # 新动机开始

            # 规则 4：避免切割（软约束）
            # fermata 是强边界标志，可以覆盖未闭合标记
            if bar.has_fermata:
                # 有 fermata 时，未闭合标记不惩罚（fermata 表示明确的停顿）
                pass
            else:
                # 没有 fermata 时，未闭合标记才惩罚
                if bar.has_unclosed_slur or bar.has_unclosed_range:
                    score -= 50

            scores.append(score)

        return scores

    def _compute_dynamics_jump(self, bar1: Bar, bar2: Bar) -> int:
        """计算力度跳跃级数"""
        dynamics_order = ['pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff']

        if not bar1.dynamics or not bar2.dynamics:
            return 0

        try:
            level1 = dynamics_order.index(bar1.dynamics[-1])
            level2 = dynamics_order.index(bar2.dynamics[0])
            return abs(level2 - level1)
        except (ValueError, IndexError):
            return 0

    def _adaptive_segmentation(self, scores: List[float]) -> List[Tuple[int, int]]:
        """自适应切割策略"""
        segments = []
        start = 0

        # 检测弱起小节
        first_bar_is_pickup = self._is_pickup_bar(self.parser.bars[0]) if self.parser.bars else False

        while start < len(self.parser.bars):
            # 在 min_length 到 max_length 范围内寻找最佳切割点
            min_len = self.config["min_length"]
            max_len = self.config["max_length"]

            # 如果是第一个乐句且有弱起，允许 min_length + 1
            if start == 0 and first_bar_is_pickup:
                min_len += 1
                max_len += 1

            end = min(start + max_len, len(self.parser.bars))

            if end - start < min_len:
                # 剩余小节不足 min_length，全部作为一个乐句
                segments.append((start, end))
                break

            # 在 [start + min_length - 1, end - 1] 范围内找最高得分
            best_cut = start + min_len - 1
            best_score = scores[best_cut] if best_cut < len(scores) else 0

            for i in range(start + min_len, end):
                if i - 1 < len(scores):
                    candidate_score = scores[i - 1]

                    # 4小节和8小节偏好（古典音乐常见）
                    phrase_length = i - start
                    if phrase_length == 4:
                        candidate_score += 40  # 4小节偏好
                    elif phrase_length == 8:
                        candidate_score += 35  # 8小节偏好

                    if candidate_score > best_score:
                        best_score = candidate_score
                        best_cut = i - 1

            # 切割点在 best_cut 之后
            segments.append((start, best_cut + 1))
            start = best_cut + 1

        return segments

    def _is_pickup_bar(self, bar: Bar) -> bool:
        """检测是否为弱起小节（时值明显少于一个完整小节）"""
        if not bar.voices:
            return False

        # 估算第一声部的总时值
        voice = bar.voices[0].strip()

        # 移除所有标记和装饰
        clean_voice = re.sub(r'![^!]*!', '', voice)  # 移除 !xxx!
        clean_voice = re.sub(r'"[^"]*"', '', clean_voice)  # 移除 "xxx"
        clean_voice = re.sub(r'\^[^\s]*', '', clean_voice)  # 移除 ^xxx

        # 如果第一声部主要是休止符，不是弱起
        if clean_voice.strip().startswith('z'):
            return False

        # 提取所有音符和休止符的时值
        notes_and_rests = re.findall(r'[A-Ga-gz](\d+)?(/\d+)?', clean_voice)

        if not notes_and_rests:
            return False

        # 计算总时值（以单位音符计）
        total_duration = 0.0
        for num, div in notes_and_rests:
            duration = float(num) if num else 1.0
            if div:
                duration /= float(div[1:])
            total_duration += duration

        # 获取完整小节的时值
        beats_per_bar = self.parser._get_beats_per_bar()

        # 解析 L: 字段获取单位音符长度
        # 例如 L:1/16 表示默认是十六分音符，即 1 个单位 = 1/16 全音符
        # 在 4/4 拍中，1 拍 = 1/4 全音符 = 4 个十六分音符
        unit_parts = self.parser.unit_length.split('/')
        if len(unit_parts) == 2:
            unit_denominator = float(unit_parts[1])  # 例如 16
        else:
            unit_denominator = 8.0  # 默认八分音符

        # 完整小节的时值（以单位音符计）
        # 例如：4/4 拍，L:1/16，则完整小节 = 4 拍 * 4 个十六分音符/拍 = 16 个单位
        full_bar_duration = beats_per_bar * (unit_denominator / 4.0)

        # 如果实际时值少于完整小节的 30%，认为是弱起
        # 例如：Chopin Op.25 No.1 第一小节 e4 = 4 个单位，完整小节 = 16 个单位，4/16 = 25% < 30%
        return total_duration < full_bar_duration * 0.3

    def _detect_motif_repetition(self, bar1: Bar, bar2: Bar) -> bool:
        """检测两个小节是否有相同的动机（旋律模式）"""
        if not bar1.voices or not bar2.voices:
            return False

        # 提取第一声部的音高序列
        pitches1 = HarmonicAnalyzer._extract_pitches_from_voice(bar1.voices[0])
        pitches2 = HarmonicAnalyzer._extract_pitches_from_voice(bar2.voices[0])

        if not pitches1 or not pitches2:
            return False

        # 取前4个音符比较（动机通常在开头）
        motif1 = pitches1[:min(4, len(pitches1))]
        motif2 = pitches2[:min(4, len(pitches2))]

        if len(motif1) < 2 or len(motif2) < 2:
            return False

        # 计算音程序列（相对音高）
        intervals1 = [motif1[i+1] - motif1[i] for i in range(len(motif1)-1)]
        intervals2 = [motif2[i+1] - motif2[i] for i in range(len(motif2)-1)]

        # 如果音程序列相同或非常相似，认为是相同动机
        if len(intervals1) == len(intervals2):
            matches = sum(1 for i, j in zip(intervals1, intervals2) if i == j)
            similarity = matches / len(intervals1)
            return similarity >= 0.75  # 75%相似度

        return False

    def _merge_short_segments(self, segments: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """合并短乐句"""
        if not segments:
            return segments

        merged = []
        i = 0

        while i < len(segments):
            start, end = segments[i]
            length = end - start

            if length < self.config["min_length"]:
                # 尝试与前一段合并
                if merged and (end - merged[-1][0]) <= self.config["merge_threshold"]:
                    merged[-1] = (merged[-1][0], end)
                # 尝试与后一段合并
                elif i + 1 < len(segments):
                    next_start, next_end = segments[i + 1]
                    if (next_end - start) <= self.config["merge_threshold"]:
                        merged.append((start, next_end))
                        i += 1  # 跳过下一段
                    else:
                        merged.append((start, end))
                else:
                    merged.append((start, end))
            else:
                merged.append((start, end))

            i += 1

        return merged

    def _generate_phrases(self, segments: List[Tuple[int, int]]) -> List[Phrase]:
        """生成乐句对象"""
        phrases = []

        for phrase_id, (start, end) in enumerate(segments, 1):
            # 提取小节内容
            bars_content = []
            for i in range(start, end):
                if i < len(self.parser.bars):
                    bars_content.append(self.parser.bars[i].content)

            content = ' | '.join(bars_content)
            if content:
                content += ' |'

            # 上一个小节
            previous_bar = None
            if start > 0:
                prev_bar = self.parser.bars[start - 1]
                previous_bar = prev_bar.content + ' |'

            phrase = Phrase(
                phrase_id=phrase_id,
                bar_range=(start + 1, end),  # 小节编号从1开始
                bar_count=end - start,
                header=self.parser.header,
                previous_bar=previous_bar,
                content=content
            )

            phrases.append(phrase)

        return phrases


def process_abcx_file(file_path: str) -> List[Dict]:
    """处理单个 ABCX 文件"""
    parser = ABCXParser(file_path)
    parser.parse()

    segmenter = PhraseSegmenter(parser)
    phrases = segmenter.segment()

    # 转换为字典
    result = []
    for phrase in phrases:
        result.append({
            "phrase_id": phrase.phrase_id,
            "bar_range": list(phrase.bar_range),
            "bar_count": phrase.bar_count,
            "header": phrase.header,
            "previous_bar": phrase.previous_bar,
            "content": phrase.content
        })

    return result


def process_directory(input_dir: str, output_file: str = None):
    """处理整个目录的 ABCX 文件"""
    input_path = Path(input_dir)
    all_results = {}

    # 递归查找所有 .abcx 文件
    abcx_files = list(input_path.rglob("*.abcx"))

    print(f"找到 {len(abcx_files)} 个 ABCX 文件")

    for file_path in abcx_files:
        try:
            print(f"处理: {file_path.relative_to(input_path)}")
            phrases = process_abcx_file(str(file_path))

            # 为每个 ABCX 文件生成独立的 JSON
            output_json = file_path.with_suffix('.phrases.json')
            result = {
                "file": str(file_path.relative_to(input_path)),
                "phrase_count": len(phrases),
                "phrases": phrases
            }

            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # 使用相对路径作为键
            rel_path = str(file_path.relative_to(input_path))
            all_results[rel_path] = result

        except Exception as e:
            print(f"  错误: {e}")
            continue

    # 如果指定了汇总文件，也保存一份汇总
    if output_file:
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        print(f"\n汇总结果已保存到: {output_path}")

    print(f"共处理 {len(all_results)} 个文件，每个文件旁边生成了 .phrases.json")


if __name__ == "__main__":
    input_dir = "/home/sy/2026/Music/EPR/data/abc_from_xml"
    output_file = "/home/sy/2026/Music/EPR/data/abc_from_xml/phrase_segmentation.json"

    process_directory(input_dir, output_file)
