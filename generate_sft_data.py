#!/usr/bin/env python3
"""
SPIRE SFT 数据生成脚本
基于 metadata.csv 生成 EPR 训练数据

数据来源：
1. 已配对数据（is_refined=True）：用于生成 EPR 样本
2. 输出 measure/phrase 两种 EPR 粒度
"""

import json
import os
import argparse
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import random
from tqdm import tqdm


class MetadataReader:
    """读取和过滤 metadata.csv"""

    def __init__(self, metadata_path: str):
        self.df = pd.read_csv(metadata_path)

    def get_paired_data(self, min_recall: float = 0.7, quality_filter: bool = True):
        """获取高质量的配对数据"""
        # Paired EPR data uses PianoCoRe tier A and above only.
        filtered = self.df[
            (self.df['tier_a'] == True) &
            (self.df['refined_recall'] >= min_recall)
        ]

        if quality_filter:
            # 进一步过滤：quality_label 为 'high quality' 或 'score'
            filtered = filtered[
                filtered['quality_label'].isin(['high quality', 'score'])
            ]

        return filtered

    def get_orphan_scores(self):
        """获取未配对的 score（有 score_abcx_path 但 is_refined=False）"""
        return self.df[
            (self.df['score_abcx_path'].notna()) &
            (self.df['is_refined'] == False)
        ]

    def get_orphan_performances(self):
        """获取未配对的 performance（有 performance_tsv_path 但 score_abcx_path 为空）"""
        return self.df[
            (self.df['performance_tsv_path'].notna()) &
            (self.df['score_abcx_path'].isna())
        ]


class ABCXAligner:
    """将原始 ABCX 转换为 aligned ABCX 格式（添加 H 和 M 标记）"""

    @staticmethod
    def parse_original_abcx(abcx_path: str) -> Dict:
        """解析原始 ABCX 文件"""
        with open(abcx_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        header_lines = []
        body_lines = []
        in_body = False

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue

            # Header lines
            if line.startswith(('X:', 'T:', 'C:', '%%', 'L:', 'Q:', 'M:', 'K:')):
                header_lines.append(line)
                if line.startswith('K:'):
                    in_body = True
            elif in_body:
                body_lines.append(line)

        return {
            'header': header_lines,
            'body': body_lines
        }

    @staticmethod
    def split_into_measures(body_lines: List[str]) -> List[str]:
        """将 body 按 | 分割成小节"""
        # 合并所有行
        full_body = ' '.join(body_lines)

        # 按 | 分割（保留 repeat 标记 |: 和 :|）
        measures = []
        current = ''
        i = 0
        while i < len(full_body):
            char = full_body[i]
            if char == '|':
                # 检查是否是 repeat 标记
                if i + 1 < len(full_body) and full_body[i + 1] == ':':
                    current += '|:'
                    i += 2
                    continue
                elif i > 0 and full_body[i - 1] == ':':
                    i += 1
                    continue
                else:
                    # 普通小节分隔符
                    if current.strip():
                        measures.append(current.strip())
                    current = ''
                    i += 1
                    continue
            current += char
            i += 1

        # 添加最后一个小节
        if current.strip():
            measures.append(current.strip())

        return measures

    @staticmethod
    def create_aligned_abcx(header: List[str], measures: List[str],
                           phrase_size: int = 4) -> str:
        """创建 aligned ABCX 格式"""
        lines = []

        # 添加 header
        lines.extend(header)

        # 按 phrase_size 分组添加小节
        num_measures = len(measures)
        phrase_id = 1

        for i in range(0, num_measures, phrase_size):
            # 添加 phrase 标记
            lines.append(f'H{phrase_id}')

            # 添加该 phrase 的所有小节
            phrase_measures = measures[i:i + phrase_size]
            for j, measure in enumerate(phrase_measures):
                measure_id = i + j + 1
                lines.append(f'M{measure_id}\t{measure}')

            phrase_id += 1

        return '\n'.join(lines)


class TSVParser:
    """解析 MIDI-TSV 文件"""

    @staticmethod
    def parse_tsv(tsv_path: str) -> Dict:
        """解析 TSV 文件，包含 duration 信息"""
        with open(tsv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        header_lines = []
        measures = defaultdict(list)
        measure_durations = {}  # M1 -> duration
        phrases = {}
        phrase_durations = {}  # H1 -> duration
        current_phrase = None
        current_measure = None

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue

            if line.startswith('#'):
                header_lines.append(line)
            elif line.startswith('H') and '\t' in line:
                parts = line.split('\t')
                current_phrase = parts[0]
                phrases[current_phrase] = []
                if len(parts) >= 3:
                    start = int(parts[1])
                    end = int(parts[2])
                    phrase_durations[current_phrase] = end - start
            elif line.startswith('M') and '\t' in line:
                parts = line.split('\t')
                current_measure = parts[0]
                if current_phrase and current_measure not in phrases[current_phrase]:
                    phrases[current_phrase].append(current_measure)
                if len(parts) >= 3:
                    # M1	0	104 -> duration = 104 - 0 = 104
                    start = int(parts[1])
                    end = int(parts[2])
                    measure_durations[current_measure] = end - start
            elif current_measure:
                measures[current_measure].append(line)

        return {
            'header': '\n'.join(header_lines),
            'measures': measures,
            'measure_durations': measure_durations,
            'phrases': phrases,
            'phrase_durations': phrase_durations
        }


class AlignedABCXParser:
    """解析 aligned ABCX 文件"""

    @staticmethod
    def parse_aligned_abcx(abcx_path: str) -> Dict:
        """解析 aligned ABCX 文件"""
        with open(abcx_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        header_lines = []
        measures = {}
        phrases = {}
        current_phrase = None

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue

            if line.startswith(('X:', 'T:', 'C:', '%%', 'L:', 'Q:', 'M:', 'K:')):
                header_lines.append(line)
            elif line.startswith('H') and '\t' not in line:
                current_phrase = line.strip()
                phrases[current_phrase] = []
            elif line.startswith('M') and '\t' in line:
                parts = line.split('\t', 1)
                measure_id = parts[0]
                measure_content = parts[1] if len(parts) > 1 else ''
                measures[measure_id] = measure_content
                if current_phrase:
                    phrases[current_phrase].append(measure_id)

        return {
            'header': '\n'.join(header_lines),
            'measures': measures,
            'phrases': phrases
        }


class MeasureEPRGenerator:
    """生成 Measure-level EPR 训练样本"""

    def __init__(self, metadata_df: pd.DataFrame, base_dir: str, output_dir: str,
                 max_samples_per_piece: int = 50):
        self.metadata_df = metadata_df
        self.base_dir = Path(base_dir)
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self):
        """生成 Measure-level EPR 数据"""
        samples = []

        # 按曲子分组（同一个 score 可能有多个 performance）
        grouped = self.metadata_df.groupby(['composer', 'composition', 'movement'])

        for (composer, composition, movement), group in tqdm(grouped, desc="Generating Measure EPR"):
            # 获取 score 路径（同一组的 score 相同）
            score_abcx_path = group.iloc[0]['score_abcx_path']
            if pd.isna(score_abcx_path):
                continue

            # 转换为 aligned 路径
            # 从 PianoCoRe/score/Composer/Composition/score.abcx
            # 到 PianoCoRe/aligned/Composer/Composition/score_aligned.abcx
            if score_abcx_path.startswith('PianoCoRe/score/'):
                # 提取 Composer/Composition 部分
                relative_path = score_abcx_path.replace('PianoCoRe/score/', '')
                # 移除 /score.abcx 后缀，得到 Composer/Composition
                composition_path = relative_path.replace('/score.abcx', '')
                # 构建 aligned 路径
                aligned_path = f'PianoCoRe/aligned/{composition_path}/score_aligned.abcx'
            else:
                aligned_path = score_abcx_path

            score_full_path = self.base_dir / aligned_path
            if not score_full_path.exists():
                continue

            # 解析 score
            score_data = AlignedABCXParser.parse_aligned_abcx(str(score_full_path))

            # 为每个 performance 生成样本
            for _, row in group.iterrows():
                perf_tsv_path = row['performance_tsv_path']
                if pd.isna(perf_tsv_path):
                    continue

                # 转换为 aligned 路径
                if perf_tsv_path.startswith('PianoCoRe_output/'):
                    perf_relative = perf_tsv_path.replace('PianoCoRe_output/', '')
                    aligned_tsv_path = f'PianoCoRe/aligned/{perf_relative}'
                else:
                    aligned_tsv_path = perf_tsv_path

                perf_full_path = self.base_dir / aligned_tsv_path
                if not perf_full_path.exists():
                    continue

                perf_data = TSVParser.parse_tsv(str(perf_full_path))
                piece_samples = self._generate_piece_samples(
                    score_data, perf_data, row['performance_id']
                )
                samples.extend(piece_samples[:self.max_samples_per_piece])

        # 保存样本
        self._save_samples(samples, 'measure_epr')
        return len(samples)

    def _generate_piece_samples(self, score_data: Dict, perf_data: Dict,
                                perf_id: str) -> List[Dict]:
        """为单个曲子生成样本（统一 coldstart/main/ending）"""
        samples = []

        # 获取所有小节
        measure_ids = sorted(score_data['measures'].keys(),
                            key=lambda x: int(x[1:]))  # M1, M2, ...

        for i, measure_id in enumerate(measure_ids):
            # 获取 score_snip: 包含前后 context 的所有小节
            score_snip = []
            for offset in [-1, 0, 1]:
                idx = i + offset
                if 0 <= idx < len(measure_ids):
                    m_id = measure_ids[idx]
                    if m_id in score_data['measures']:
                        score_snip.append(f"{m_id}\t{score_data['measures'][m_id]}")

            # 获取 target performance
            if measure_id in perf_data['measures'] and measure_id in perf_data['measure_durations']:
                duration = perf_data['measure_durations'][measure_id]
                perf_events = '\n'.join(perf_data['measures'][measure_id])
                perf_target = f"{measure_id}:{duration}\n{perf_events}"

                # 确定任务类型
                if i == 0:
                    task_type = 'coldstart'
                elif i == len(measure_ids) - 1:
                    task_type = 'ending'
                else:
                    task_type = 'main'

                sample = {
                    'task': 'measure_epr',
                    'task_type': task_type,
                    'instruction': f'Generate performance for {measure_id}',
                    'score_header': score_data['header'],
                    'score_snip': '\n'.join(score_snip),
                    'perf_target': perf_target,
                    'target_measure_id': measure_id,
                    'piece_id': perf_id
                }
                samples.append(sample)

        return samples

    def _save_samples(self, samples: List[Dict], prefix: str):
        """保存样本到 measure-based 文件夹"""
        output_file = self.output_dir / 'measure-based' / f'{prefix}.jsonl'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


class PhraseEPRGenerator:
    """生成 Phrase-level EPR 训练样本"""

    def __init__(self, metadata_df: pd.DataFrame, base_dir: str, output_dir: str,
                 max_samples_per_piece: int = 20):
        self.metadata_df = metadata_df
        self.base_dir = Path(base_dir)
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self):
        """生成 Phrase-level EPR 数据"""
        samples = []

        grouped = self.metadata_df.groupby(['composer', 'composition', 'movement'])

        for (composer, composition, movement), group in tqdm(grouped, desc="Generating Phrase EPR"):
            score_abcx_path = group.iloc[0]['score_abcx_path']
            if pd.isna(score_abcx_path):
                continue

            # 转换为 aligned 路径
            if score_abcx_path.startswith('PianoCoRe/score/'):
                relative_path = score_abcx_path.replace('PianoCoRe/score/', '')
                composition_path = relative_path.replace('/score.abcx', '')
                aligned_path = f'PianoCoRe/aligned/{composition_path}/score_aligned.abcx'
            else:
                aligned_path = score_abcx_path

            score_full_path = self.base_dir / aligned_path
            if not score_full_path.exists():
                continue

            score_data = AlignedABCXParser.parse_aligned_abcx(str(score_full_path))

            for _, row in group.iterrows():
                perf_tsv_path = row['performance_tsv_path']
                if pd.isna(perf_tsv_path):
                    continue

                # 转换为 aligned 路径
                if perf_tsv_path.startswith('PianoCoRe_output/'):
                    perf_relative = perf_tsv_path.replace('PianoCoRe_output/', '')
                    aligned_tsv_path = f'PianoCoRe/aligned/{perf_relative}'
                else:
                    aligned_tsv_path = perf_tsv_path

                perf_full_path = self.base_dir / aligned_tsv_path
                if not perf_full_path.exists():
                    continue

                perf_data = TSVParser.parse_tsv(str(perf_full_path))
                piece_samples = self._generate_piece_samples(
                    score_data, perf_data, row['performance_id']
                )
                samples.extend(piece_samples[:self.max_samples_per_piece])

        self._save_samples(samples, 'phrase_epr')
        return len(samples)

    def _generate_piece_samples(self, score_data: Dict, perf_data: Dict,
                                perf_id: str) -> List[Dict]:
        """为单个曲子生成乐句级样本（统一 coldstart/main/ending）"""
        samples = []

        # 获取所有乐句
        phrase_ids = sorted(score_data['phrases'].keys(),
                           key=lambda x: int(x[1:]))  # H1, H2, ...

        for i, phrase_id in enumerate(phrase_ids):
            # 获取 score_snip: 包含前后 context 的所有乐句
            score_snip = []
            for offset in [-1, 0, 1]:
                idx = i + offset
                if 0 <= idx < len(phrase_ids):
                    p_id = phrase_ids[idx]
                    phrase_measures = score_data['phrases'][p_id]

                    # 收集该乐句的所有小节
                    phrase_content = []
                    for m_id in phrase_measures:
                        if m_id in score_data['measures']:
                            phrase_content.append(f"{m_id}\t{score_data['measures'][m_id]}")

                    if phrase_content:
                        score_snip.append(f"{p_id}\t{' '.join(phrase_measures)}\n" + '\n'.join(phrase_content))

            # 获取 target performance phrase
            if phrase_id in perf_data['phrases'] and phrase_id in perf_data['phrase_durations']:
                phrase_duration = perf_data['phrase_durations'][phrase_id]

                # 构建 performance target: H<X>:<duration>\n + M<X>:<duration>\n + events
                perf_lines = [f"{phrase_id}:{phrase_duration}"]

                for m_id in perf_data['phrases'][phrase_id]:
                    if m_id in perf_data['measures'] and m_id in perf_data['measure_durations']:
                        m_duration = perf_data['measure_durations'][m_id]
                        perf_events = '\n'.join(perf_data['measures'][m_id])
                        perf_lines.append(f"{m_id}:{m_duration}\n{perf_events}")

                if len(perf_lines) > 1:  # 至少有 H 和一个 M
                    perf_target = '\n'.join(perf_lines)

                    # 确定任务类型
                    if i == 0:
                        task_type = 'coldstart'
                    elif i == len(phrase_ids) - 1:
                        task_type = 'ending'
                    else:
                        task_type = 'main'

                    sample = {
                        'task': 'phrase_epr',
                        'task_type': task_type,
                        'instruction': f'Generate performance for {phrase_id}',
                        'score_header': score_data['header'],
                        'score_snip': '\n'.join(score_snip),
                        'perf_target': perf_target,
                        'target_phrase_id': phrase_id,
                        'piece_id': perf_id
                    }
                    samples.append(sample)

        return samples

    def _save_samples(self, samples: List[Dict], prefix: str):
        """保存样本到 phrase-based 文件夹"""
        output_file = self.output_dir / 'phrase-based' / f'{prefix}.jsonl'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


def main():
    parser = argparse.ArgumentParser(
        description='Generate SPIRE EPR SFT data from tier A+ paired metadata rows'
    )
    parser.add_argument('--metadata', type=str, default='PianoCoRe/metadata.csv',
                        help='Path to metadata.csv')
    parser.add_argument('--base_dir', type=str, default='.',
                        help='Base directory for resolving paths in metadata')
    parser.add_argument('--output_dir', type=str, default='sft_data',
                        help='Output directory for generated training data')
    parser.add_argument('--task', type=str,
                        choices=['measure_epr', 'phrase_epr', 'all'],
                        default='all', help='Which task to generate data for')
    parser.add_argument('--min_recall', type=float, default=0.7,
                        help='Minimum refined_recall for paired data')
    parser.add_argument('--quality_filter', action='store_true',
                        help='Optionally restrict tier A+ rows to high quality/score labels')

    args = parser.parse_args()

    print("=" * 60)
    print("SPIRE SFT Data Generation")
    print("=" * 60)

    # 读取 metadata
    print(f"\nReading metadata from {args.metadata}...")
    reader = MetadataReader(args.metadata)

    # 获取配对数据
    paired_df = reader.get_paired_data(
        min_recall=args.min_recall,
        quality_filter=args.quality_filter
    )
    print(f"✓ Found {len(paired_df)} high-quality paired samples")
    print(f"  - Unique pieces: {paired_df.groupby(['composer', 'composition', 'movement']).ngroups}")

    if args.task in ['measure_epr', 'all']:
        print("\n[1/2] Generating Measure-level EPR data...")
        generator = MeasureEPRGenerator(
            paired_df, args.base_dir, args.output_dir
        )
        count = generator.generate()
        print(f"✓ Generated {count} Measure-level EPR samples")

    if args.task in ['phrase_epr', 'all']:
        print("\n[2/2] Generating Phrase-level EPR data...")
        generator = PhraseEPRGenerator(
            paired_df, args.base_dir, args.output_dir
        )
        count = generator.generate()
        print(f"✓ Generated {count} Phrase-level EPR samples")

    print("\n" + "=" * 60)
    print("Data generation complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
