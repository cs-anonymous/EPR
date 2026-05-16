#!/usr/bin/env python3
"""Generate 100 example lines per task for review."""
import json, random
from pathlib import Path
from collections import defaultdict
from tqdm import tqdm
import sys
sys.path.insert(0, '.')

import importlib
import generate_language_learning_data as gll
importlib.reload(gll)
from generate_language_learning_data import TSVParser, PERF_MASKS, AlignedABCXParser, SCORE_MASKS, load_valid_ids_and_abcx_paths

random.seed(42)
valid_perf_ids, valid_abcx_dirs = load_valid_ids_and_abcx_paths()

# === SCORE tasks ===
paired_abcx_files = sorted(list(Path('PianoCoRe/aligned').glob('**/*_aligned.abcx')))
orphan_abcx_files = sorted(list(Path('PianoCoRe/orphan_abcx').glob('**/*_aligned.abcx'))) if Path('PianoCoRe/orphan_abcx').exists() else []
abcx_files = paired_abcx_files + orphan_abcx_files
print(f"Using {len(paired_abcx_files)} paired + {len(orphan_abcx_files)} orphan ABCX files = {len(abcx_files)} total")

score_cont = []
score_mask = []

def abcx_valid(p):
    parts = p.parts
    for i, pp in enumerate(parts):
        if pp in ('aligned', 'orphan_abcx') and i + 2 < len(parts):
            return (parts[i+1], parts[i+2]) in valid_abcx_dirs
    return False

for abcx_path in tqdm(abcx_files, desc='Score tasks'):
    if valid_abcx_dirs and not abcx_valid(abcx_path):
        continue
    try:
        score_data = AlignedABCXParser.parse(str(abcx_path))
    except:
        continue
    if not score_data['measures']:
        continue
    measure_ids = sorted(score_data['measures'].keys(), key=lambda x: int(x[1:]))
    header = score_data['header']
    cont_count = 0
    mask_count = 0
    for i in range(len(measure_ids) - 1):
        if cont_count < 25 and len(score_cont) < 100:
            curr = measure_ids[i]
            target = measure_ids[i + 1]
            input_text = f"{curr}\t{score_data['measures'][curr]}"
            target_text = f"{target}\t{score_data['measures'][target]}"
            score_cont.append({'task': 'measure_score_lang_continuation', 'header': header, 'input': input_text, 'target': target_text, 'piece_id': abcx_path.as_posix()})
            cont_count += 1
        if mask_count < 25 and len(score_mask) < 100:
            curr = measure_ids[i]
            curr_content = score_data['measures'][curr]
            mask_name = random.choice(list(SCORE_MASKS.keys()))
            masked = SCORE_MASKS[mask_name](curr_content)
            if masked != curr_content:
                input_text = f"{curr}\t{masked}"
                target_text = f"{curr}\t{curr_content}"
                score_mask.append({'task': 'measure_score_lang_mask', 'mask_type': mask_name, 'header': header, 'input': input_text, 'target': target_text, 'piece_id': abcx_path.as_posix()})
                mask_count += 1
    if len(score_cont) >= 100 and len(score_mask) >= 100:
        break

with open('sft_data/examples/measure_score_lang_continuation.jsonl', 'w') as f:
    for s in score_cont:
        f.write(json.dumps(s, ensure_ascii=False) + '\n')
with open('sft_data/examples/measure_score_lang_mask.jsonl', 'w') as f:
    for s in score_mask:
        f.write(json.dumps(s, ensure_ascii=False) + '\n')

# === PHRASE SCORE tasks ===
phrase_cont = []
phrase_mask = []
for abcx_path in tqdm(abcx_files, desc='Phrase score tasks'):
    if valid_abcx_dirs and not abcx_valid(abcx_path):
        continue
    try:
        score_data = AlignedABCXParser.parse(str(abcx_path))
    except:
        continue
    if not score_data['phrases']:
        continue
    header = score_data['header']
    phrase_ids = sorted(score_data['phrases'].keys(), key=lambda x: int(x[1:]))
    cont_count = 0
    mask_count = 0
    for i in range(len(phrase_ids) - 1):
        if cont_count < 25 and len(phrase_cont) < 100:
            curr_p = phrase_ids[i]
            target_p = phrase_ids[i + 1]
            curr_content = []
            for m_id in score_data['phrases'][curr_p]:
                if m_id in score_data['measures']:
                    curr_content.append(f"{m_id}\t{score_data['measures'][m_id]}")
            target_content = []
            for m_id in score_data['phrases'][target_p]:
                if m_id in score_data['measures']:
                    target_content.append(f"{m_id}\t{score_data['measures'][m_id]}")
            if curr_content and target_content:
                input_text = f"{curr_p}\n" + '\n'.join(curr_content)
                target_text = f"{target_p}\n" + '\n'.join(target_content)
                phrase_cont.append({'task': 'phrase_score_lang_continuation', 'header': header, 'input': input_text, 'target': target_text})
                cont_count += 1
        if mask_count < 25 and len(phrase_mask) < 100:
            curr_p = phrase_ids[i]
            curr_content = []
            for m_id in score_data['phrases'][curr_p]:
                if m_id in score_data['measures']:
                    curr_content.append(f"{m_id}\t{score_data['measures'][m_id]}")
            if curr_content:
                full_body = '\n'.join(curr_content)
                mask_name = random.choice(list(SCORE_MASKS.keys()))
                masked_body = SCORE_MASKS[mask_name](full_body)
                if masked_body != full_body:
                    input_text = f"{curr_p}\n" + masked_body
                    target_text = f"{curr_p}\n" + full_body
                    phrase_mask.append({'task': 'phrase_score_lang_mask', 'mask_type': mask_name, 'header': header, 'input': input_text, 'target': target_text})
                    mask_count += 1
    if len(phrase_cont) >= 100 and len(phrase_mask) >= 100:
        break

with open('sft_data/examples/phrase_score_lang_continuation.jsonl', 'w') as f:
    for s in phrase_cont:
        f.write(json.dumps(s, ensure_ascii=False) + '\n')
with open('sft_data/examples/phrase_score_lang_mask.jsonl', 'w') as f:
    for s in phrase_mask:
        f.write(json.dumps(s, ensure_ascii=False) + '\n')

# === PERF tasks ===
tsv_files = sorted(list(Path('PianoCoRe/aligned').glob('**/*.tsv')))

cont_samples = []
mask_samples = []

for tsv_path in tqdm(tsv_files, desc='Perf tasks'):
    fname = tsv_path.stem
    for suffix in ['_refined.mid', '_mini.mid', '.mid']:
        if fname.endswith(suffix):
            fname = fname[:-len(suffix)]
            break
    if valid_perf_ids and fname not in valid_perf_ids:
        continue
    try:
        perf_data = TSVParser.parse(str(tsv_path))
    except:
        continue
    if not perf_data['measures']:
        continue
    measure_ids = sorted(perf_data['measures'].keys(), key=lambda x: int(x[1:]))
    piece_id = tsv_path.relative_to(tsv_path.parents[-3]).with_suffix('').as_posix()
    half_limit = 12
    cont_count = 0
    mask_count = 0
    for i in range(len(measure_ids) - 1):
        if cont_count < half_limit and len(cont_samples) < 100:
            curr_m_id = measure_ids[i]
            target_m_id = measure_ids[i + 1]
            curr_dur = perf_data['measure_durations'].get(curr_m_id, '')
            target_dur = perf_data['measure_durations'].get(target_m_id, '')
            curr_events = '\n'.join(perf_data['measures'][curr_m_id])
            target_events = '\n'.join(perf_data['measures'][target_m_id])
            input_text = f'{curr_m_id}:{curr_dur}\n{curr_events}'
            target_text = f'{target_m_id}:{target_dur}\n{target_events}'
            cont_samples.append({'task': 'measure_perf_lang_continuation', 'input': input_text, 'target': target_text, 'piece_id': piece_id})
            cont_count += 1
        if mask_count < half_limit and len(mask_samples) < 100:
            curr_m_id = measure_ids[i]
            curr_dur = perf_data['measure_durations'].get(curr_m_id, '')
            curr_lines = perf_data['measures'][curr_m_id]
            mask_name = random.choice(list(PERF_MASKS.keys()))
            masked_lines = PERF_MASKS[mask_name](curr_lines)
            masked_events = '\n'.join(masked_lines)
            full_events = '\n'.join(curr_lines)
            input_text = f'{curr_m_id}:{curr_dur}\n{masked_events}'
            target_text = f'{curr_m_id}:{curr_dur}\n{full_events}'
            if input_text != target_text:
                mask_samples.append({'task': 'measure_perf_lang_mask', 'mask_type': mask_name, 'input': input_text, 'target': target_text, 'piece_id': piece_id})
                mask_count += 1
    if len(cont_samples) >= 100 and len(mask_samples) >= 100:
        break

with open('sft_data/examples/measure_perf_lang_continuation.jsonl', 'w') as f:
    for s in cont_samples:
        f.write(json.dumps(s, ensure_ascii=False) + '\n')
with open('sft_data/examples/measure_perf_lang_mask.jsonl', 'w') as f:
    for s in mask_samples:
        f.write(json.dumps(s, ensure_ascii=False) + '\n')

print(f'measure_score_cont: {len(score_cont)}')
print(f'measure_score_mask: {len(score_mask)}')
print(f'phrase_score_cont: {len(phrase_cont)}')
print(f'phrase_score_mask: {len(phrase_mask)}')
print(f'measure_perf_cont: {len(cont_samples)}')
print(f'measure_perf_mask: {len(mask_samples)}')
