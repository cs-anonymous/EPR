#!/usr/bin/env python3
"""Convert sampled SFT data (sft_data_sampled/) to swift messages format and split train/val."""
import json
import random
import os
from pathlib import Path

random.seed(42)

INSTRUCTION_TEMPLATES = {
    'score_lang_continuation': 'Complete the next measure of ABCX score given the current measure.',
    'score_lang_mask': 'Restore the masked ABCX score measure. Mask type: {mask_type}.',
    'perf_lang_continuation': 'Predict the next measure of performance MIDI events given the current Measure.',
    'perf_lang_mask_timing': '填补缺失的timing到X。',
    'perf_lang_mask_velocity': '填补缺失的velocity到X。',
    'perf_lang_mask_duration': '填补缺失的duration到X。',
    'perf_lang_mask_pedal': '填补缺失的pedal events。',
}


def convert_to_messages(sample):
    """Convert a raw SFT sample to swift messages format."""
    task = sample['task']

    if 'score_lang' in task:
        header = sample.get('header', '')
        input_text = sample['input']
        target_text = sample['target']

        if header:
            user_content = f"{header}\n{input_text}"
        else:
            user_content = input_text

        if 'mask' in task:
            mask_type = sample.get('mask_type', '')
            instruction = INSTRUCTION_TEMPLATES['score_lang_mask'].format(mask_type=mask_type)
        else:
            instruction = INSTRUCTION_TEMPLATES['score_lang_continuation']

        assistant_content = target_text

    elif 'perf_lang' in task:
        input_text = sample['input']
        target_text = sample['target']

        if 'mask' in task:
            mask_type = sample.get('mask_type', '')
            instruction = INSTRUCTION_TEMPLATES.get(f'perf_lang_mask_{mask_type}',
                                                    f'填补缺失的{mask_type}到X。')
        else:
            instruction = INSTRUCTION_TEMPLATES['perf_lang_continuation']

        user_content = input_text
        assistant_content = target_text

    else:
        return None

    return {
        'messages': [
            {'role': 'system', 'content': 'You are a music score and performance language model.'},
            {'role': 'user', 'content': f'{instruction}\n\n{user_content}'},
            {'role': 'assistant', 'content': assistant_content},
        ],
    }


def merge_and_split(file_paths, output_train, output_val, val_ratio=0.01):
    """Merge multiple JSONL files, convert to messages, shuffle, and split."""
    all_samples = []
    for fp in file_paths:
        if not os.path.exists(fp):
            print(f"  SKIP (not found): {fp}")
            continue
        print(f"  Reading {fp}...")
        count = 0
        with open(fp, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    sample = json.loads(line.strip())
                except Exception:
                    continue

                converted = convert_to_messages(sample)
                if converted:
                    converted['task'] = sample['task']  # keep task for analysis
                    all_samples.append(converted)
                    count += 1
        print(f"    -> {count:,} valid samples from this file")

    print(f"  Total: {len(all_samples):,} samples")
    random.shuffle(all_samples)

    val_size = max(1, int(len(all_samples) * val_ratio))
    val_samples = all_samples[:val_size]
    train_samples = all_samples[val_size:]

    with open(output_train, 'w', encoding='utf-8') as f:
        for s in train_samples:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    with open(output_val, 'w', encoding='utf-8') as f:
        for s in val_samples:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f"  Train: {len(train_samples):,}, Val: {len(val_samples):,}")
    return len(train_samples), len(val_samples)


def main():
    sft_dir = Path('sft_data_sampled')
    measure_dir = sft_dir / 'measure-based'
    phrase_dir = sft_dir / 'phrase-based'

    output_root = Path('sft_data_sampled/swift_format')
    output_root.mkdir(parents=True, exist_ok=True)

    files = [
        str(measure_dir / 'measure_score_lang_continuation.jsonl'),
        str(measure_dir / 'measure_score_lang_mask.jsonl'),
        str(phrase_dir / 'phrase_score_lang_continuation.jsonl'),
        str(phrase_dir / 'phrase_score_lang_mask.jsonl'),
        str(measure_dir / 'measure_perf_lang_continuation.jsonl'),
        str(measure_dir / 'measure_perf_lang_mask.jsonl'),
    ]

    train_path = str(output_root / 'language_train.jsonl')
    val_path = str(output_root / 'language_val.jsonl')

    merge_and_split(files, train_path, val_path)

    print("\nDone!")


if __name__ == '__main__':
    main()
