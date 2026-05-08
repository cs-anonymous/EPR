#!/usr/bin/env python3
"""
Batch evaluate measure alignment on ASAP dataset.

1. Generate GT from annotations.txt for each MIDI performance
2. Run align_measures.py with GT reference
3. Report accuracy statistics
"""
import os
import sys
import subprocess
import json
import time
from pathlib import Path

# Load pairs
pairs_file = '/tmp/abc_midi_pairs.txt'
pairs = []
with open(pairs_file) as f:
    for line in f:
        line = line.strip()
        if line:
            parts = line.split('\t')
            pairs.append((parts[0], parts[1], parts[2]))  # abcx, midi, ann

print(f'Loaded {len(pairs)} pairs')

# Parameters for alignment
ALIGN_PARAMS = {
    '--gap-penalty': '20000',
    '--min-gap': '2',
}

results = []
gt_dir = '/tmp/align_gt'
os.makedirs(gt_dir, exist_ok=True)

start_time = time.time()

for i, (abcx, midi, ann) in enumerate(pairs):
    piece = abcx.replace('data/abc_from_xml/', '').rsplit('/', 1)[0]
    performer = os.path.basename(midi).replace('.mid', '')

    # Step 1: Generate GT from annotations
    gt_path = os.path.join(gt_dir, f'gt_{i}.txt')
    gt_cmd = ['python3', 'generate_ground_truth.py', ann, midi, '-o', gt_path]
    gt_result = subprocess.run(gt_cmd, capture_output=True, text=True, timeout=600)
    if gt_result.returncode != 0:
        print(f'  [{i+1}/{len(pairs)}] GT generation failed for {piece}/{performer}: {gt_result.stderr[:200]}')
        results.append({'piece': piece, 'performer': performer, 'status': 'gt_error'})
        continue

    # Step 2: Run alignment algorithm with GT reference
    align_cmd = ['python3', 'align_measures.py', abcx, midi,
                 '-r', gt_path,
                 '--gap-penalty', '20000',
                 '--min-gap', '2']
    align_result = subprocess.run(align_cmd, capture_output=True, text=True, timeout=600)
    if not align_result.stdout.strip():
        print(f'  [{i+1}/{len(pairs)}] Alignment failed for {piece}/{performer}')
        results.append({'piece': piece, 'performer': performer, 'status': 'align_error'})
        continue

    # Step 3: Parse results and evaluate
    pred = {}
    for pair in align_result.stdout.strip().split():
        if ':' in pair:
            m, t = pair.split(':')
            pred[int(m)] = int(t)

    gt = {}
    with open(gt_path) as f:
        for p in f.read().strip().split():
            if ':' in p:
                m, t = p.split(':')
                gt[int(m)] = int(t)

    if not pred or not gt:
        results.append({'piece': piece, 'performer': performer, 'status': 'empty', 'total_measures': len(gt)})
        continue

    total = len(gt)
    exact = sum(1 for m in gt if pred.get(m) == gt[m])
    within1 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 1)
    within5 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 5)

    results.append({
        'piece': piece,
        'performer': performer,
        'status': 'ok',
        'total_measures': total,
        'exact': exact,
        'within1': within1,
        'within5': within5,
        'exact_pct': exact / total if total > 0 else 0,
        'within1_pct': within1 / total if total > 0 else 0,
    })

    if (i + 1) % 50 == 0:
        elapsed = time.time() - start_time
        ok_results = [r for r in results if r['status'] == 'ok']
        if ok_results:
            avg_exact = sum(r['exact_pct'] for r in ok_results) / len(ok_results)
            avg_w1 = sum(r['within1_pct'] for r in ok_results) / len(ok_results)
        else:
            avg_exact = avg_w1 = 0
        print(f'  [{i+1}/{len(pairs)}] elapsed={elapsed:.0f}s, avg_exact={avg_exact:.1%}, avg_w1={avg_w1:.1%}')

# Save results
output_path = '/tmp/alignment_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2)

# Print summary
ok_results = [r for r in results if r['status'] == 'ok']
total_ok = len(ok_results)
if total_ok == 0:
    print('\nNo successful results!')
else:
    avg_exact = sum(r['exact_pct'] for r in ok_results) / total_ok
    avg_w1 = sum(r['within1_pct'] for r in ok_results) / total_ok
    avg_w5 = sum(r['within5_pct'] for r in ok_results) / total_ok

    total_measures = sum(r['total_measures'] for r in ok_results)
    total_correct = sum(r['exact'] for r in ok_results)
    total_within1 = sum(r['within1'] for r in ok_results)
    total_within5 = sum(r['within5'] for r in ok_results)

    print(f'\n=== Summary ({total_ok} successful performances, {total_measures} total measures) ===')
    print(f'Overall exact match: {total_correct}/{total_measures} = {total_correct/total_measures:.1%}')
    print(f'Overall within ±1 tick: {total_within1}/{total_measures} = {total_within1/total_measures:.1%}')
    print(f'Overall within ±5 ticks: {total_within5}/{total_measures} = {total_within5/total_measures:.1%}')

    # Per composer
    from collections import Counter, defaultdict
    composer_results = defaultdict(list)
    for r in ok_results:
        composer = r['piece'].split('/')[0]
        composer_results[composer].append(r)

    print(f'\nPer-composer results:')
    print(f'{"Composer":>15} {"Performances":>12} {"Measures":>10} {"Exact":>10} {"±1tick":>10} {"±5tick":>10}')
    for composer in sorted(composer_results.keys(), key=lambda c: -len(composer_results[c])):
        cr = composer_results[composer]
        cm = sum(r['total_measures'] for r in cr)
        ce = sum(r['exact'] for r in cr)
        c1 = sum(r['within1'] for r in cr)
        c5 = sum(r['within5'] for r in cr)
        print(f'{composer:>15} {len(cr):>12} {cm:>10} {ce/cm:>10.1%} {c1/cm:>10.1%} {c5/cm:>10.1%}')

# Count errors
errors = [r for r in results if r['status'] != 'ok']
if errors:
    print(f'\nFailed: {len(errors)} performances')
    for e in errors[:5]:
        print(f'  {e["piece"]}/{e["performer"]}: {e["status"]}')
