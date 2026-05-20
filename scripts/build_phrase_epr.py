#!/usr/bin/env python3
"""
生成 Phrase-level EPR 数据

新设计：
- score_snip: 上一小节乐谱 (M_prev) + 当前整句乐谱 (H_k) + 下一小节乐谱 (M_next)
- perf_context: 上一小节演奏 (M_prev)

相比原设计的改进：
- 原设计：score_snip 包含 H_{k-1} + H_k + H_{k+1}，perf_context 包含整个 H_{k-1}
- 新设计：只保留必要的上下文（上一小节和下一小节），大幅减少 token 数量
- 预期节约：平均 61.7% 的输入 token，使得 2048 覆盖率从 98.27% 提升到 99.74%
"""

import json
import argparse
import re
import pandas as pd
from pathlib import Path
from typing import List, Dict
from collections import defaultdict
from tqdm import tqdm


def performance_piece_id(perf_tsv_path: str) -> str:
    """Convert metadata performance_tsv_path to the JSONL piece_id format."""
    path = str(perf_tsv_path)
    if path.startswith('PianoCoReS/miditsv/'):
        path = path[len('PianoCoReS/miditsv/'):]
    elif path.startswith('PianoCoReS/aligned/'):
        path = path[len('PianoCoReS/aligned/'):]
    elif path.startswith('PianoCoRe_output/'):
        path = path[len('PianoCoRe_output/'):]
    elif path.startswith('PianoCoRe/aligned/'):
        path = path[len('PianoCoRe/aligned/'):]
    if path.endswith('.tsv'):
        path = path[:-len('.tsv')]
    return path


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
        strict_structural = False
        phrase_count = 0
        measure_count = 0
        pending_ext = {}

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue

            if line.startswith('#'):
                header_lines.append(line)
                if line.strip() == '# structural_duration=u16_hi_lo':
                    strict_structural = True
            elif line.startswith('H') and '\t' in line:
                parts = line.split('\t')
                if parts[0] == 'H' and len(parts) == 4:
                    phrase_count += 1
                    current_phrase = f'H{phrase_count}'
                    phrases[current_phrase] = []
                    if strict_structural:
                        phrase_durations[current_phrase] = int(parts[2]) * 256 + int(parts[3])
                    else:
                        phrase_durations[current_phrase] = int(parts[2])
                    current_measure = None
                    pending_ext.clear()
                else:
                    current_phrase = parts[0]
                    phrases[current_phrase] = []
                    if len(parts) >= 3:
                        start = int(parts[1])
                        end = int(parts[2])
                        phrase_durations[current_phrase] = end - start
            elif line.startswith('M') and '\t' in line:
                parts = line.split('\t')
                if parts[0] == 'M' and len(parts) == 4:
                    measure_count += 1
                    current_measure = f'M{measure_count}'
                    if current_phrase and current_measure not in phrases[current_phrase]:
                        phrases[current_phrase].append(current_measure)
                    if strict_structural:
                        measure_durations[current_measure] = int(parts[2]) * 256 + int(parts[3])
                    else:
                        measure_durations[current_measure] = int(parts[2])
                    pending_ext.clear()
                else:
                    current_measure = parts[0]
                    if current_phrase and current_measure not in phrases[current_phrase]:
                        phrases[current_phrase].append(current_measure)
                    if len(parts) >= 3:
                        start = int(parts[1])
                        end = int(parts[2])
                        measure_durations[current_measure] = end - start
            elif current_measure:
                parts = line.split('\t')
                if len(parts) == 4 and parts[0] in ('EXD', 'EXO'):
                    pending_ext[parts[0]] = int(parts[2]) * 256 + int(parts[3])
                    continue
                if len(parts) == 4:
                    event, value, duration, offset = parts
                    if duration == 'EXT':
                        duration = str(pending_ext.get('EXD', 255))
                    if offset == 'EXT':
                        offset = str(pending_ext.get('EXO', 255))
                    measures[current_measure].append('\t'.join([event, value, duration, offset]))
                    pending_ext.clear()
                else:
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
        phrase_display_ids = {}
        measure_display_ids = {}
        current_phrase = None
        phrase_count = 0
        measure_count = 0

        for line in lines:
            line = line.rstrip('\n')
            if not line:
                continue

            if line.startswith(('X:', 'T:', 'C:', '%%', 'L:', 'Q:', 'M:', 'K:')):
                header_lines.append(line)
            elif (phrase_token_id := _parse_score_phrase_token(line)) is not None:
                phrase_count += 1
                current_phrase = f'H{phrase_count}'
                phrase_display_ids[current_phrase] = f'<H><V{phrase_token_id:03d}>'
                phrases[current_phrase] = []
            elif (measure_token_id := _parse_score_measure_token(line)) is not None and '\t' in line:
                parts = line.split('\t', 1)
                measure_count += 1
                measure_id = f'M{measure_count}'
                measure_display_ids[measure_id] = f'<M><V{measure_token_id:03d}>'
                measure_content = parts[1] if len(parts) > 1 else ''
                measures[measure_id] = measure_content
                if current_phrase:
                    phrases[current_phrase].append(measure_id)

        return {
            'header': '\n'.join(header_lines),
            'measures': measures,
            'phrases': phrases,
            'phrase_display_ids': phrase_display_ids,
            'measure_display_ids': measure_display_ids,
        }


def _parse_score_phrase_token(line: str) -> int | None:
    stripped = line.strip()
    match = re.fullmatch(r"<H><V(\d{3})>", stripped)
    if match:
        return int(match.group(1))
    if stripped.startswith('H') and stripped[1:].isdigit():
        return int(stripped[1:])
    return None


def _parse_score_measure_token(line: str) -> int | None:
    stripped = line.strip()
    match = re.match(r"^<M><V(\d{3})>", stripped)
    if match:
        return int(match.group(1))
    token = stripped.split('\t', 1)[0].split(' ', 1)[0]
    if token.startswith('M') and token[1:].isdigit():
        return int(token[1:])
    return None


def compact_perf_event(line: str) -> str:
    """Serialize one semantic 4-column event as colon-separated text."""
    parts = line.replace('\t', ' ').split()
    if not parts:
        return ''
    if len(parts) >= 4:
        return ':'.join(parts[:4])
    if len(parts) == 1 and parts[0].count(':') >= 3:
        return parts[0]
    return ':'.join(parts)


def format_perf_measure(measure_id: str, duration, event_lines: List[str]) -> str:
    events = [compact_perf_event(line) for line in event_lines]
    events = [event for event in events if event]
    return ' '.join([f"{measure_id}:{duration}"] + events)


def format_perf_phrase(phrase_id: str, duration, measure_parts: List[str]) -> str:
    return '\n'.join([f"{phrase_id}:{duration}"] + [part for part in measure_parts if part])


def format_score_measure(measure_id: str, content: str, display_id: str | None = None) -> str:
    label = display_id
    if label is None:
        idx = int(measure_id[1:]) - 1
        label = f"<M><V{idx:03d}>"
    return f"{label}{content}"


def format_score_phrase(phrase_id: str, measure_lines: List[str], display_id: str | None = None) -> str:
    label = display_id
    if label is None:
        idx = int(phrase_id[1:]) - 1
        label = f"<H><V{idx:03d}>"
    return '\n'.join([label] + [line for line in measure_lines if line])


class PhraseEPRGenerator:
    """生成 Phrase-level EPR 训练样本

    新设计：
    - score_snip: M_prev + H_k + M_next
    - perf_context: M_prev 的演奏
    """

    def __init__(self, metadata_df: pd.DataFrame, base_dir: str, output_dir: str,
                 max_samples_per_piece: int = None):
        self.metadata_df = metadata_df
        self.base_dir = Path(base_dir)
        self.output_dir = Path(output_dir)
        self.max_samples_per_piece = max_samples_per_piece
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, suffix: str = ''):
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
                    score_data, perf_data, performance_piece_id(row['performance_tsv_path'])
                )
                samples.extend(piece_samples[:self.max_samples_per_piece])

        self._save_samples(samples, 'phrase_epr', suffix=suffix)
        return len(samples)

    def _generate_piece_samples(self, score_data: Dict, perf_data: Dict,
                                perf_id: str) -> List[Dict]:
        """为单个曲子生成乐句级样本（版本）

        新设计：
        - score_snip: M_prev + H_k + M_next
        - perf_context: M_prev 的演奏
        """
        samples = []

        # 获取所有乐句
        phrase_ids = sorted(score_data['phrases'].keys(),
                           key=lambda x: int(x[1:]))  # H1, H2, ...

        # 构建小节索引：measure_id -> phrase_id
        measure_to_phrase = {}
        for phrase_id, measure_ids in score_data['phrases'].items():
            for measure_id in measure_ids:
                measure_to_phrase[measure_id] = phrase_id

        for i, phrase_id in enumerate(phrase_ids):
            phrase_measures = score_data['phrases'][phrase_id]
            if not phrase_measures:
                continue

            # 获取当前 phrase 的所有小节（H_k）
            current_phrase_lines = []
            for m_id in phrase_measures:
                if m_id in score_data['measures']:
                    current_phrase_lines.append(
                        format_score_measure(
                            m_id, score_data['measures'][m_id], score_data['measure_display_ids'].get(m_id)
                        )
                    )

            if not current_phrase_lines:
                continue

            # 获取上一小节 (M_prev)：当前 phrase 的前一个小节
            prev_measure_line = None
            if i > 0:
                prev_phrase_id = phrase_ids[i - 1]
                prev_phrase_measures = score_data['phrases'][prev_phrase_id]
                if prev_phrase_measures:
                    # 取上一个 phrase 的最后一个小节
                    prev_m_id = prev_phrase_measures[-1]
                    if prev_m_id in score_data['measures']:
                        prev_measure_line = format_score_measure(
                            prev_m_id, score_data['measures'][prev_m_id], score_data['measure_display_ids'].get(prev_m_id)
                        )

            # 获取下一小节 (M_next)：当前 phrase 的后一个小节
            next_measure_line = None
            if i < len(phrase_ids) - 1:
                next_phrase_id = phrase_ids[i + 1]
                next_phrase_measures = score_data['phrases'][next_phrase_id]
                if next_phrase_measures:
                    # 取下一个 phrase 的第一个小节
                    next_m_id = next_phrase_measures[0]
                    if next_m_id in score_data['measures']:
                        next_measure_line = format_score_measure(
                            next_m_id, score_data['measures'][next_m_id], score_data['measure_display_ids'].get(next_m_id)
                        )

            # 构建 score_snip: M_prev + H_k + M_next
            score_snip_lines = []
            if prev_measure_line:
                score_snip_lines.append(prev_measure_line)
            score_snip_lines.append(
                format_score_phrase(phrase_id, current_phrase_lines, score_data['phrase_display_ids'].get(phrase_id))
            )
            if next_measure_line:
                score_snip_lines.append(next_measure_line)

            score_snip = '\n'.join(score_snip_lines)

            # 获取 perf_context: M_prev 的演奏
            perf_context = ''
            if i > 0:
                prev_phrase_id = phrase_ids[i - 1]
                prev_phrase_measures = score_data['phrases'][prev_phrase_id]
                if prev_phrase_measures:
                    prev_m_id = prev_phrase_measures[-1]
                    if prev_m_id in perf_data['measures'] and prev_m_id in perf_data['measure_durations']:
                        prev_duration = perf_data['measure_durations'][prev_m_id]
                        perf_context = format_perf_measure(
                            prev_m_id, prev_duration, perf_data['measures'][prev_m_id]
                        )

            # 获取 target performance phrase
            if phrase_id in perf_data['phrases'] and phrase_id in perf_data['phrase_durations']:
                phrase_duration = perf_data['phrase_durations'][phrase_id]

                # Compact phrase target: H<X>:<duration>\nM<X>:<duration> events ...
                perf_lines = []

                for m_id in perf_data['phrases'][phrase_id]:
                    if m_id in perf_data['measures'] and m_id in perf_data['measure_durations']:
                        m_duration = perf_data['measure_durations'][m_id]
                        perf_lines.append(
                            format_perf_measure(m_id, m_duration, perf_data['measures'][m_id])
                        )

                if perf_lines:
                    perf_target = format_perf_phrase(phrase_id, phrase_duration, perf_lines)

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
                        'score_snip': score_snip,
                        'perf_context': perf_context,
                        'perf_target': perf_target,
                        'target_phrase_id': phrase_id,
                        'piece_id': perf_id
                    }
                    samples.append(sample)

        return samples

    def _save_samples(self, samples: List[Dict], prefix: str, suffix: str = ''):
        """保存样本到 phrase-based 文件夹"""
        fname = f'{prefix}{suffix}.jsonl' if suffix else f'{prefix}.jsonl'
        output_file = self.output_dir / 'phrase-based-' / fname
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        print(f'✓ Saved {len(samples)} samples to {output_file}')


class MetadataReader:
    """读取和过滤 metadata.csv"""

    def __init__(self, metadata_path: str):
        self.df = pd.read_csv(metadata_path)

    @staticmethod
    def _interpolation_ratio(df: pd.DataFrame) -> pd.Series:
        return (
            df['refined_performance_interpolated_note_count'] /
            df['refined_performance_note_count']
        )

    def get_paired_data(self, min_recall: float = 0.7, quality_filter: bool = True):
        """获取高质量的配对数据"""
        filtered = self.df[
            (self.df['tier_a'] == True) &
            (self.df['refined_recall'] >= min_recall)
        ]

        if quality_filter:
            filtered = filtered[
                filtered['quality_label'].isin(['high quality', 'score'])
            ]

        return filtered

    def get_core_s_data(self, star: bool = False):
        """CoRe-S / CoRe-S* subset"""
        interpolation_ratio = self._interpolation_ratio(self.df)
        recall_threshold = 0.95 if star else 0.90
        interpolation_threshold = 0.05 if star else 0.10
        core_astar = (
            (self.df['tier_a_star'] == True) &
            (self.df['refined_recall'] >= recall_threshold) &
            (interpolation_ratio <= interpolation_threshold)
        )
        asap = self.df['is_transcription'] == False
        return self.df[core_astar | asap]


def main():
    parser = argparse.ArgumentParser(
        description='Build Phrase EPR data with compact context'
    )
    parser.add_argument('--metadata', type=str, default='PianoCoRe/metadata.csv',
                        help='Path to metadata.csv')
    parser.add_argument('--base_dir', type=str, default='.',
                        help='Base directory for resolving paths in metadata')
    parser.add_argument('--output_dir', type=str, default='sft_data',
                        help='Output directory for generated training data')
    parser.add_argument('--min_recall', type=float, default=0.7,
                        help='Minimum refined_recall for paired data')
    parser.add_argument('--quality_filter', action='store_true',
                        help='Optionally restrict tier A+ rows to high quality/score labels')
    parser.add_argument('--dataset-filter', type=str,
                        choices=['core-s', 'core-s-star'], default=None,
                        help='Override EPR paired rows')

    args = parser.parse_args()

    print("=" * 60)
    print("SPIRE Phrase EPR Data Generation")
    print("=" * 60)

    # 读取 metadata
    print(f"\nReading metadata from {args.metadata}...")
    reader = MetadataReader(args.metadata)

    # 获取配对数据
    if args.dataset_filter == 'core-s':
        paired_df = reader.get_core_s_data(star=False)
    elif args.dataset_filter == 'core-s-star':
        paired_df = reader.get_core_s_data(star=True)
    else:
        paired_df = reader.get_paired_data(
            min_recall=args.min_recall,
            quality_filter=args.quality_filter
        )
    print(f"✓ Found {len(paired_df)} high-quality paired samples")
    print(f"  - Unique pieces: {paired_df.groupby(['composer', 'composition', 'movement']).ngroups}")

    print("\nGenerating Phrase-level EPR data...")
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
