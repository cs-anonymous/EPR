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
        align_file = self.pianocore_root / "refined" / align_path
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
        midi_file = self.pianocore_root / "refined" / midi_path
        if not midi_file.exists():
            raise FileNotFoundError(f"MIDI file not found: {midi_file}")
        return pretty_midi.PrettyMIDI(str(midi_file))

    def load_score_xml(self, xml_path: str) -> music21.stream.Score:
        """加载 MusicXML 文件"""
        xml_file = self.pianocore_root / "refined" / xml_path
        if not xml_file.exists():
            raise FileNotFoundError(f"XML file not found: {xml_file}")
        return music21.converter.parse(str(xml_file))

    def score_to_abcx(self, xml_path: str) -> str:
        """将 MusicXML 转换为 ABCX"""
        xml_file = self.pianocore_root / "refined" / xml_path
        if not xml_file.exists():
            raise FileNotFoundError(f"XML file not found: {xml_file}")

        try:
            abcx_content = xml_to_abcx(str(xml_file))
            return abcx_content
        except Exception as e:
            print(f"Error converting {xml_path} to ABCX: {e}")
            return None
