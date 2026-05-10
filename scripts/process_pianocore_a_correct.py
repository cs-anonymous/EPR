#!/usr/bin/env python3
"""
处理 PianoCoRe-A 数据集（正确版本）
1. 读取 Tier A 的 refined 配对数据
2. MusicXML → ABCX
3. MIDI + alignment → MIDI-TSV（使用 midi_tsv.py，按小节对齐）
4. 生成小节级配对数据集
"""

import os
import sys
import json
import pandas as pd
import subprocess
from pathlib import Path
from tqdm import tqdm
from typing import Dict, List, Optional

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from xml_to_abcx import musicxml_to_abcx


class PianoCoreProcessor:
    def __init__(self, pianocore_root: str, output_dir: str):
        self.pianocore_root = Path(pianocore_root)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # midi_tsv.py 路径
        self.midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
        if not self.midi_tsv_script.exists():
            raise FileNotFoundError(f"midi_tsv.py not found at {self.midi_tsv_script}")

        # 读取 metadata
        self.metadata = pd.read_csv(self.pianocore_root / "metadata.csv")

        # 筛选 Tier A refined 数据
        self.tier_a_data = self.metadata[
            (self.metadata['tier_a'] == True) &
            (self.metadata['is_refined'] == True)
        ].copy()

        print(f"找到 {len(self.tier_a_data)} 对 Tier A refined 数据")

    def score_to_abcx(self, xml_path: str) -> Optional[str]:
        """将 MusicXML 转换为 ABCX"""
        xml_file = self.pianocore_root / "PianoCoRe" / "raw" / xml_path
        if not xml_file.exists():
            raise FileNotFoundError(f"XML file not found: {xml_file}")

        try:
            abcx_content = musicxml_to_abcx(xml_file, validate=False, drop_harmony=True)
            return abcx_content
        except Exception as e:
            print(f"Error converting {xml_path} to ABCX: {e}")
            return None

    def midi_to_tsv_with_annotation(
        self,
        midi_path: str,
        annotation_path: Optional[str] = None
    ) -> Optional[str]:
        """
        使用 midi_tsv.py 将 MIDI 转换为 MIDI-TSV
        如果提供 annotation，使用 annotation 的 downbeat
        否则使用 Omnizart 自动识别 downbeat
        """
        midi_file = self.pianocore_root / "PianoCoRe" / "refined" / midi_path
        if not midi_file.exists():
            raise FileNotFoundError(f"MIDI file not found: {midi_file}")

        # 构建命令
        cmd = [
            sys.executable,
            str(self.midi_tsv_script),
            "midi2tsv",
            str(midi_file),
        ]

        # 如果有 annotation，添加参数
        if annotation_path:
            annotation_file = self.pianocore_root / "PianoCoRe" / "refined" / annotation_path
            if annotation_file.exists():
                cmd.extend(["--annotation", str(annotation_file)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                print(f"Error converting MIDI to TSV: {result.stderr}")
                return None
            
            return result.stdout
        except Exception as e:
            print(f"Error running midi_tsv.py: {e}")
            return None

    def parse_tsv_measures(self, tsv_content: str) -> List[Dict]:
        """
        解析 MIDI-TSV，按小节分组
        返回：[{measure_id, start_tick, end_tick, content}, ...]
        """
        measures = []
        current_measure = None
        lines = tsv_content.strip().split('\n')
        
        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            
            parts = line.split('\t')
            if not parts:
                continue
            
            record_type = parts[0]
            
            # Measure 记录
            if record_type.startswith('M') and not record_type.startswith('M\t'):
                # M1, M2, ... 格式
                if current_measure:
                    measures.append(current_measure)
                
                measure_id = record_type
                start_tick = int(parts[1])
                end_tick = int(parts[2])
                
                current_measure = {
                    'measure_id': measure_id,
                    'start_tick': start_tick,
                    'end_tick': end_tick,
                    'lines': []
                }
            elif current_measure:
                # 属于当前 measure 的事件
                current_measure['lines'].append(line)
        
        # 添加最后一个 measure
        if current_measure:
            measures.append(current_measure)
        
        return measures

    def process_one_pair(self, row: pd.Series) -> Optional[Dict]:
        """处理一对 score-performance 数据"""
        try:
            # 1. 加载数据路径
            score_xml_path = row['score_xml_path']
            perf_midi_path = row['refined_performance_midi_path']
            
            # 2. 转换 score 到 ABCX
            abcx_content = self.score_to_abcx(score_xml_path)
            if abcx_content is None:
                return None

            # 3. 转换 MIDI 到 MIDI-TSV（使用 midi_tsv.py）
            # 注意：PianoCoRe 可能没有 annotation 文件，会使用 Omnizart 自动识别
            tsv_content = self.midi_to_tsv_with_annotation(perf_midi_path)
            if tsv_content is None:
                return None

            # 4. 解析 MIDI-TSV，按小节分组
            measures = self.parse_tsv_measures(tsv_content)

            # 5. 构建输出
            measure_tsvs = []
            for measure in measures:
                # 重建该 measure 的 TSV 内容
                measure_tsv = f"{measure['measure_id']}\t{measure['start_tick']}\t{measure['end_tick']}\n"
                measure_tsv += '\n'.join(measure['lines'])
                measure_tsvs.append(measure_tsv)

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
    parser = argparse.ArgumentParser(description='Process PianoCoRe-A dataset (correct MIDI-TSV format)')
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
