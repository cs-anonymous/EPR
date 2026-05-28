#!/usr/bin/env python3
"""
修复 Language Learning 数据的问题：
1. Performance mask: 使用 X 代替 [MASK_VEL] 等长字符串
2. 添加 instruction 字段
3. Score mask: 使用 X 代替 z 作为 mask token
"""

import json
import re
from pathlib import Path
from typing import Dict, List


def create_instruction(task: str, mask_type: str = None) -> str:
    """为每个任务生成自然语言 instruction"""
    if task == 'measure_score_lang_continuation':
        return 'Continue the score to the next measure'
    elif task == 'phrase_score_lang_continuation':
        return 'Continue the score to the next phrase'
    elif task == 'measure_perf_lang_continuation':
        return 'Continue the performance to the next measure'
    elif task == 'phrase_perf_lang_continuation':
        return 'Continue the performance to the next phrase'
    elif task == 'measure_score_lang_mask':
        mask_desc = {
            'acc': 'accidentals (sharps/flats)',
            'treble': 'treble clef (right hand)',
            'bass': 'bass clef (left hand)',
            'label': 'expression marks'
        }
        return f'Reconstruct the masked {mask_desc.get(mask_type, mask_type)} in the score'
    elif task == 'phrase_score_lang_mask':
        mask_desc = {
            'acc': 'accidentals (sharps/flats)',
            'treble': 'treble clef (right hand)',
            'bass': 'bass clef (left hand)',
            'label': 'expression marks'
        }
        return f'Reconstruct the masked {mask_desc.get(mask_type, mask_type)} in the score'
    elif task == 'measure_perf_lang_mask':
        mask_desc = {
            'timing': 'note timing',
            'velocity': 'note velocities',
            'duration': 'note durations',
            'pedal': 'pedal events'
        }
        return f'Reconstruct the masked {mask_desc.get(mask_type, mask_type)} in the performance'
    elif task == 'phrase_perf_lang_mask':
        mask_desc = {
            'timing': 'note timing',
            'velocity': 'note velocities',
            'duration': 'note durations',
            'pedal': 'pedal events'
        }
        return f'Reconstruct the masked {mask_desc.get(mask_type, mask_type)} in the performance'
    return ''


def fix_perf_mask_tokens(text: str) -> str:
    """将 performance mask 中的长字符串替换为 X"""
    text = text.replace('[MASK_VEL]', 'X')
    text = text.replace('[MASK_DUR]', 'X')
    text = text.replace('[MASK_TIMING]', 'X')
    return text


def fix_score_mask_tokens(text: str) -> str:
    """将 score mask 中的 z 替换为 X"""
    # 只替换作为 mask token 的 z，保留合法的休止符
    # 策略：替换连续的 z 和带八度标记的 z

    # 替换 z, z,, z,,, 等（带逗号的八度标记）
    text = re.sub(r'z,+', 'X', text)

    # 替换连续的 z（如 zz, zzz）
    text = re.sub(r'z{2,}', lambda m: 'X' * len(m.group()), text)

    # 替换单独的 z 后面跟数字（如 z2, z4）
    text = re.sub(r'z(\d+)', r'X\1', text)

    # 替换剩余的单独 z（在空格或特殊字符之间）
    # 但要小心不要替换合法的休止符
    # 这里我们假设 mask 后的内容会有很多连续的 z

    return text


def process_file(input_file: Path, output_file: Path):
    """处理单个 jsonl 文件"""
    samples = []

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue

            sample = json.loads(line)
            task = sample['task']

            # 添加 instruction
            mask_type = sample.get('mask_type')
            sample['instruction'] = create_instruction(task, mask_type)

            # 修复 performance mask tokens
            if 'perf' in task and 'mask' in task:
                if 'input' in sample:
                    sample['input'] = fix_perf_mask_tokens(sample['input'])

            # 修复 score mask tokens (但不包括 acc mask，因为 acc 不应该 mask 休止符)
            if 'score' in task and 'mask' in task and sample.get('mask_type') != 'acc':
                if 'input' in sample:
                    sample['input'] = fix_score_mask_tokens(sample['input'])

            samples.append(sample)

    # 保存修复后的数据
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')

    return len(samples)


def main():
    base_dir = Path('sft_data')

    # 需要处理的文件
    files_to_process = [
        # Measure-based
        ('measure-based/measure_score_lang_continuation.jsonl', 'measure-based/measure_score_lang_continuation.jsonl'),
        ('measure-based/measure_score_lang_mask.jsonl', 'measure-based/measure_score_lang_mask.jsonl'),
        ('measure-based/measure_perf_lang_continuation.jsonl', 'measure-based/measure_perf_lang_continuation.jsonl'),
        ('measure-based/measure_perf_lang_mask.jsonl', 'measure-based/measure_perf_lang_mask.jsonl'),

        # Phrase-based
        ('phrase-based/phrase_score_lang_continuation.jsonl', 'phrase-based/phrase_score_lang_continuation.jsonl'),
        ('phrase-based/phrase_score_lang_mask.jsonl', 'phrase-based/phrase_score_lang_mask.jsonl'),
        ('phrase-based/phrase_perf_lang_continuation.jsonl', 'phrase-based/phrase_perf_lang_continuation.jsonl'),
        ('phrase-based/phrase_perf_lang_mask.jsonl', 'phrase-based/phrase_perf_lang_mask.jsonl'),
    ]

    print("=" * 60)
    print("Fixing Language Learning Data")
    print("=" * 60)

    for input_rel, output_rel in files_to_process:
        input_file = base_dir / input_rel
        output_file = base_dir / output_rel

        if not input_file.exists():
            print(f"⚠ Skipping {input_file} (not found)")
            continue

        print(f"\nProcessing {input_file.name}...")
        count = process_file(input_file, output_file)
        print(f"✓ Fixed {count} samples")

        # 同时更新 examples
        example_input = base_dir / 'examples' / input_rel
        example_output = base_dir / 'examples' / output_rel

        if example_input.exists():
            count = process_file(example_input, example_output)
            print(f"✓ Fixed {count} example samples")

    print("\n" + "=" * 60)
    print("All files processed!")
    print("=" * 60)


if __name__ == '__main__':
    main()
