#!/usr/bin/env python3
"""
处理未配对的 ABCX 文件，生成 aligned ABCX 用于 Language Learning

流程：
1. 读取原始 ABCX 文件
2. 将 ABCX 转换为 Score MIDI
3. 使用 Score MIDI 提取小节信息
4. 生成 aligned ABCX（添加 H 和 M 标记）
"""

import argparse
import json
import re
import subprocess
import tempfile
import sys
from pathlib import Path
from typing import List, Dict, Tuple
from tqdm import tqdm
import pretty_midi

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from aligned_abcx_format import (
    AlignedAbcxError,
    build_orphan_aligned_abcx,
    score_measure_label,
    score_phrase_label,
)


def abcx_to_midi(abcx_path: Path, output_midi: Path) -> bool:
    """将 ABCX 转换为 MIDI"""
    try:
        # 使用 abc2midi 转换（假设系统已安装）
        result = subprocess.run(
            ['abc2midi', str(abcx_path), '-o', str(output_midi)],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0 and output_midi.exists()
    except Exception as e:
        print(f"Error converting {abcx_path}: {e}")
        return False


def parse_abcx_header(abcx_path: Path) -> List[str]:
    """解析 ABCX header"""
    with open(abcx_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header_lines = []
    found_k_line = False

    for line in lines:
        line = line.rstrip('\n')

        # 基本 header 字段
        if line.startswith(('X:', 'T:', 'C:', 'Z:', '%%', 'L:', 'Q:', 'M:', 'K:')):
            header_lines.append(line)
            if line.startswith('K:'):
                found_k_line = True
        # V: (voice) 行也属于 header，但只在 K: 之后
        elif found_k_line and line.startswith('V:'):
            header_lines.append(line)
        # 如果遇到非 header 行且已经有 K: 行，则停止
        elif found_k_line and line and not line.startswith(('V:', '%', 'w:')):
            break

    return header_lines


def parse_abcx_body(abcx_path: Path) -> List[str]:
    """解析 ABCX body，按 | 分割成小节"""
    with open(abcx_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 找到 K: 行之后的内容，跳过所有 V: 行
    body_start = None
    found_k_line = False

    for i, line in enumerate(lines):
        if line.startswith('K:'):
            found_k_line = True
            continue
        # 跳过 K: 之后的 V: 行和其他 header 行
        if found_k_line and line.strip() and not line.startswith(('V:', '%', 'w:')):
            body_start = i
            break

    if body_start is None:
        return []

    # 合并所有 body 行，过滤掉中间的 V: 行
    body_lines = []
    for line in lines[body_start:]:
        line = line.rstrip('\n')
        # 跳过 V: 行（可能出现在 body 中间）
        if line.startswith('V:'):
            continue
        body_lines.append(line)

    body_text = ' '.join(body_lines)

    # 按 | 分割小节
    measures = []
    current = ''
    i = 0

    while i < len(body_text):
        char = body_text[i]

        if char == '|':
            # 检查是否是 repeat 标记
            if i + 1 < len(body_text) and body_text[i + 1] == ':':
                current += '|:'
                i += 2
                continue
            elif i > 0 and body_text[i - 1] == ':':
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


def extract_voice_and_marks(measure_content: str) -> tuple[str, List[str]]:
    """从小节内容中提取 V: 指令和表情标记，返回 (清理后的内容, 提取的header行)"""
    extracted_headers = []
    cleaned = measure_content

    # 提取 V: 指令（可能包含复杂的参数）
    # 匹配 V:X ... 直到遇到音符或其他非V:内容
    v_pattern = r'V:\d+[^;|]*?(?=\s*[A-Ga-gz\[;|]|$)'
    v_matches = re.findall(v_pattern, cleaned)
    for v_match in v_matches:
        extracted_headers.append(v_match.strip())
        cleaned = cleaned.replace(v_match, '', 1)

    # 提取开头的表情标记 "^..."
    # 只提取最开始的表情标记，因为它们通常是全局的
    expr_pattern = r'^\s*("[\^_<>@][^"]*")+\s*'
    expr_match = re.match(expr_pattern, cleaned)
    if expr_match:
        # 表情标记不加入header，因为它们可能是小节特定的
        # 只移除V:指令
        pass

    return cleaned.strip(), extracted_headers


def extract_measures_from_midi(midi_path: Path) -> List[Dict]:
    """从 Score MIDI 提取小节信息"""
    try:
        midi = pretty_midi.PrettyMIDI(str(midi_path))

        # 获取所有音符
        notes = []
        for instrument in midi.instruments:
            if not instrument.is_drum:
                notes.extend(instrument.notes)

        notes.sort(key=lambda n: (n.start, n.pitch))

        if not notes:
            return []

        # 获取拍号和速度信息
        time_sigs = midi.time_signature_changes
        if not time_sigs:
            # 默认 4/4
            beats_per_measure = 4
        else:
            beats_per_measure = time_sigs[0].numerator

        # 估算每小节的时长（秒）
        if midi.get_tempo_changes()[1]:
            tempo = midi.get_tempo_changes()[1][0]
        else:
            tempo = 120  # 默认 120 BPM

        seconds_per_beat = 60.0 / tempo
        seconds_per_measure = seconds_per_beat * beats_per_measure

        # 根据时间分割小节
        total_duration = notes[-1].end
        num_measures = int(total_duration / seconds_per_measure) + 1

        measures = []
        for i in range(num_measures):
            start_time = i * seconds_per_measure
            end_time = (i + 1) * seconds_per_measure

            # 找到该小节内的音符
            measure_notes = [n for n in notes if start_time <= n.start < end_time]

            if measure_notes:
                measures.append({
                    'measure_num': i + 1,
                    'start_time': start_time,
                    'end_time': end_time,
                    'note_count': len(measure_notes)
                })

        return measures

    except Exception as e:
        print(f"Error extracting measures from {midi_path}: {e}")
        return []


def create_aligned_abcx(header: List[str], measures: List[str],
                       phrase_size: int = 4) -> str:
    """创建 aligned ABCX 格式"""
    lines = []

    # 添加 header
    lines.extend(header)

    # 按 phrase_size 分组添加小节
    num_measures = len(measures)
    phrase_index = 0

    for i in range(0, num_measures, phrase_size):
        # 添加 phrase 标记
        lines.append(score_phrase_label(phrase_index))

        # 添加该 phrase 的所有小节
        phrase_measures = measures[i:i + phrase_size]
        for measure_local_index, measure in enumerate(phrase_measures):
            lines.append(f'{score_measure_label(measure_local_index)}{measure}')

        phrase_index += 1

    return '\n'.join(lines)


def process_orphan_abcx(abcx_path: Path, output_dir: Path,
                       phrase_size: int = 4) -> bool:
    """处理单个未配对的 ABCX 文件"""
    try:
        aligned_abcx = build_orphan_aligned_abcx(abcx_path, phrase_size)

        # 保存 aligned ABCX
        output_path = output_dir / abcx_path.name.replace('.abcx', '_aligned.abcx')
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(aligned_abcx)

        return True

    except AlignedAbcxError:
        return False
    except Exception as e:
        print(f"Error processing {abcx_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Process orphan ABCX files to create aligned versions'
    )
    parser.add_argument('--input_dir', type=str, default='data/score_processed',
                       help='Directory containing orphan ABCX files')
    parser.add_argument('--output_dir', type=str, default='data/score_aligned',
                       help='Output directory for aligned ABCX files')
    parser.add_argument('--phrase_size', type=int, default=4,
                       help='Number of measures per phrase')
    parser.add_argument('--pattern', type=str, default='**/*.abcx',
                       help='File pattern to match')

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Processing Orphan ABCX Files")
    print("=" * 60)

    # 查找所有 ABCX 文件
    abcx_files = list(input_dir.glob(args.pattern))
    print(f"\nFound {len(abcx_files)} ABCX files")

    # 处理每个文件
    success_count = 0
    for abcx_path in tqdm(abcx_files, desc="Processing"):
        if process_orphan_abcx(abcx_path, output_dir, args.phrase_size):
            success_count += 1

    print(f"\n✓ Successfully processed {success_count}/{len(abcx_files)} files")
    print(f"✓ Output saved to {output_dir}")
    print("=" * 60)


if __name__ == '__main__':
    main()
