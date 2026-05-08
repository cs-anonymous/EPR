#!/usr/bin/env python3
"""
Evaluate measure alignment with pickup measure offset detection.

When GT M1 doesn't correspond to ABCX M1 (due to pickup/anacrusis measures),
we detect the offset and compare accordingly.
"""
import os
import subprocess
import json
import time
from pathlib import Path
from collections import Counter, defaultdict

# Find all midi_score files
asap_root = 'data/asap-dataset'
abc_root = 'data/abc_from_xml'

# Build ABCX mapping: piece_dir -> abcx_path
abc_by_piece = {}
for root, dirs, files in os.walk(abc_root):
    for f in files:
        if f.endswith('.abcx'):
            rel = os.path.relpath(root, abc_root)
            abc_by_piece[rel] = os.path.join(root, f)

# Find all midi_score files
pairs = []
for root, dirs, files in os.walk(asap_root):
    for f in files:
        if f == 'midi_score_annotations.txt':
            ann = os.path.join(root, f)
            midi = os.path.join(root, 'midi_score.mid')
            if not os.path.isfile(midi):
                continue
            piece_dir = os.path.relpath(root, asap_root)
            if piece_dir in abc_by_piece:
                pairs.append((abc_by_piece[piece_dir], midi, ann))

print(f'midi_score pairs: {len(pairs)}')

gt_dir = '/tmp/align_gt_v2'
os.makedirs(gt_dir, exist_ok=True)

results = []
start_time = time.time()

for i, (abcx, midi, ann) in enumerate(pairs):
    piece = abcx.replace('data/abc_from_xml/', '')
    gt_path = os.path.join(gt_dir, f'gt_{i}.txt')

    # Step 1: Generate GT from annotations
    gt_cmd = ['python3', 'generate_ground_truth.py', ann, midi, '-o', gt_path]
    gt_result = subprocess.run(gt_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=600)
    if gt_result.returncode != 0:
        print(f'  [{i+1}/{len(pairs)}] GT failed for {piece}: {gt_result.stderr[:200]}')
        results.append({'piece': piece, 'status': 'gt_error'})
        continue

    # Step 2: Run alignment with GT reference
    align_cmd = ['python3', 'align_measures.py', abcx, midi,
                 '-r', gt_path,
                 '--gap-penalty', '20000',
                 '--min-gap', '2']
    align_result = subprocess.run(align_cmd, capture_output=True, text=True, timeout=600)
    if not align_result.stdout.strip():
        print(f'  [{i+1}/{len(pairs)}] Align failed for {piece}')
        results.append({'piece': piece, 'status': 'align_error'})
        continue

    # Step 3: Also run WITHOUT GT reference
    align_nr_cmd = ['python3', 'align_measures.py', abcx, midi,
                    '--gap-penalty', '20000',
                    '--min-gap', '2']
    align_nr_result = subprocess.run(align_nr_cmd, capture_output=True, text=True, timeout=600)

    # Parse GT
    gt = {}
    with open(gt_path) as f:
        for p in f.read().strip().split():
            if ':' in p:
                m, t = p.split(':')
                gt[int(m)] = int(t)

    # Parse with-GT result
    pred = {}
    for pair_str in align_result.stdout.strip().split():
        if ':' in pair_str:
            m, t = pair_str.split(':')
            pred[int(m)] = int(t)

    # Parse no-reference result
    pred_nr = {}
    if align_nr_result.stdout.strip():
        for pair_str in align_nr_result.stdout.strip().split():
            if ':' in pair_str:
                m, t = pair_str.split(':')
                pred_nr[int(m)] = int(t)

    if not pred or not gt:
        results.append({'piece': piece, 'status': 'empty', 'total_measures': len(gt)})
        continue

    # === Detect pickup measure offset ===
    # Find which ABCX measure's predicted position is closest to GT M1's position
    gt_m1_tick = gt[1]
    best_offset = 0  # default: GT M1 = ABCX M1
    best_offset_score = float('inf')
    for abc_m in range(1, min(5, max(pred.keys()) + 1)):  # Check first few ABCX measures
        if abc_m in pred:
            diff = abs(pred[abc_m] - gt_m1_tick)
            if diff < best_offset_score:
                best_offset_score = diff
                best_offset = abc_m - 1  # offset = ABCX_M - GT_M = abc_m - 1

    # Also check if offset=0 is better than others
    # offset=0 means GT M1 = ABCX M1
    # offset=1 means GT M1 = ABCX M2
    # We use the one with smallest diff for GT M1 position

    # Now compare: GT Mm should match ABCX M(m + offset)
    total = len(gt)
    exact = 0
    within1 = 0
    within5 = 0
    matched_gt = 0
    for m in gt:
        abc_m = m + best_offset
        if abc_m in pred:
            matched_gt += 1
            diff = abs(pred[abc_m] - gt[m])
            if diff == 0:
                exact += 1
            if diff <= 1:
                within1 += 1
            if diff <= 5:
                within5 += 1

    # No-reference with same offset detection
    nr_offset = 0
    nr_offset_score = float('inf')
    if pred_nr:
        for abc_m in range(1, min(5, max(pred_nr.keys()) + 1)):
            if abc_m in pred_nr:
                diff = abs(pred_nr[abc_m] - gt_m1_tick)
                if diff < nr_offset_score:
                    nr_offset_score = diff
                    nr_offset = abc_m - 1

    nr_exact = 0
    nr_within1 = 0
    nr_within5 = 0
    if pred_nr:
        for m in gt:
            abc_m = m + nr_offset
            if abc_m in pred_nr:
                diff = abs(pred_nr[abc_m] - gt[m])
                if diff == 0:
                    nr_exact += 1
                if diff <= 1:
                    nr_within1 += 1
                if diff <= 5:
                    nr_within5 += 1

    results.append({
        'piece': piece,
        'status': 'ok',
        'total_measures': total,
        'offset': best_offset,
        'exact': exact,
        'within1': within1,
        'within5': within5,
        'exact_pct': exact / total if total > 0 else 0,
        'within1_pct': within1 / total if total > 0 else 0,
        'nr_exact': nr_exact,
        'nr_within1': nr_within1,
        'nr_within5': nr_within5,
        'nr_exact_pct': nr_exact / total if total > 0 else 0,
        'nr_within1_pct': nr_within1 / total if total > 0 else 0,
    })

    if (i + 1) % 20 == 0:
        elapsed = time.time() - start_time
        ok = [r for r in results if r['status'] == 'ok']
        if ok:
            avg_gt = sum(r['exact_pct'] for r in ok) / len(ok)
            avg_nr = sum(r['nr_exact_pct'] for r in ok) / len(ok)
        else:
            avg_gt = avg_nr = 0
        print(f'  [{i+1}/{len(pairs)}] elapsed={elapsed:.0f}s, gt_exact={avg_gt:.1%}, nr_exact={avg_nr:.1%}')

# Save results
output_path = '/tmp/baseline_results_v2.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2)

# Print summary
ok_results = [r for r in results if r['status'] == 'ok']
total_ok = len(ok_results)
if total_ok == 0:
    print('\nNo successful results!')
else:
    gt_exact = sum(r['exact'] for r in ok_results)
    gt_w1 = sum(r['within1'] for r in ok_results)
    gt_w5 = sum(r['within5'] for r in ok_results)
    nr_exact = sum(r['nr_exact'] for r in ok_results)
    nr_w1 = sum(r['nr_within1'] for r in ok_results)
    nr_w5 = sum(r['nr_within5'] for r in ok_results)
    total_measures = sum(r['total_measures'] for r in ok_results)

    print(f'\n=== Baseline v2 Summary ({total_ok} pieces, {total_measures} total measures) ===')
    print(f'{"":>15} {"Exact":>10} {"Exact%":>10} {"±1tick":>10} {"±1%":>10} {"±5tick":>10} {"±5%":>10}')
    print(f'With GT ref:  {gt_exact:>10} {gt_exact/total_measures:>10.1%} {gt_w1:>10} {gt_w1/total_measures:>10.1%} {gt_w5:>10} {gt_w5/total_measures:>10.1%}')
    print(f'No reference: {nr_exact:>10} {nr_exact/total_measures:>10.1%} {nr_w1:>10} {nr_w1/total_measures:>10.1%} {nr_w5:>10} {nr_w5/total_measures:>10.1%}')

    # Show offset distribution
    offsets = Counter(r['offset'] for r in ok_results)
    print(f'\nOffset distribution:')
    for off, count in sorted(offsets.items()):
        print(f'  offset={off}: {count} pieces')

    # Per composer
    composer_results = defaultdict(list)
    for r in ok_results:
        composer = r['piece'].split('/')[0]
        composer_results[composer].append(r)

    print(f'\nPer-composer (GT ref | No ref):')
    print(f'{"Composer":>15} {"Pieces":>8} {"GT%":>10} {"±1%":>10} {"±5%":>10} | {"NR%":>10} {"±1%":>10} {"±5%":>10}')
    for composer in sorted(composer_results.keys(), key=lambda c: -len(composer_results[c])):
        cr = composer_results[composer]
        cm = sum(r['total_measures'] for r in cr)
        ce = sum(r['exact'] for r in cr)
        c1 = sum(r['within1'] for r in cr)
        c5 = sum(r['within5'] for r in cr)
        nce = sum(r['nr_exact'] for r in cr)
        nc1 = sum(r['nr_within1'] for r in cr)
        nc5 = sum(r['nr_within5'] for r in cr)
        print(f'{composer:>15} {len(cr):>8} {ce/cm:>10.1%} {c1/cm:>10.1%} {c5/cm:>10.1%} | {nce/cm:>10.1%} {nc1/cm:>10.1%} {nc5/cm:>10.1%}')

errors = [r for r in results if r['status'] != 'ok']
if errors:
    print(f'\nFailed: {len(errors)} pieces')
    for e in errors[:5]:
        print(f'  {e["piece"]}: {e["status"]}')
