#!/usr/bin/env python3
"""
Evaluate measure alignment on ASAP midi_score files as baseline.

midi_score is the score-generated MIDI, so it should give near-perfect alignment.
This serves as an upper bound baseline for the algorithm.
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

gt_dir = '/tmp/align_gt_baseline'
os.makedirs(gt_dir, exist_ok=True)

results = []
start_time = time.time()

for i, (abcx, midi, ann) in enumerate(pairs):
    piece = abcx.replace('data/abc_from_xml/', '')
    gt_path = os.path.join(gt_dir, f'gt_{i}.txt')

    # Step 1: Generate GT from annotations
    gt_cmd = ['python3', 'generate_ground_truth.py', ann, midi, '-o', gt_path]
    gt_result = subprocess.run(gt_cmd, capture_output=True, text=True, timeout=600)
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

    # Step 3: Also run WITHOUT GT reference (no-reference mode)
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

    total = len(gt)
    exact = sum(1 for m in gt if pred.get(m) == gt[m])
    within1 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 1)
    within5 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 5)
    within10 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 10)
    within50 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 50)
    within100 = sum(1 for m in gt if abs(pred.get(m, gt[m]) - gt[m]) <= 100)

    # No-reference metrics
    nr_exact = sum(1 for m in gt if pred_nr.get(m) == gt[m]) if pred_nr else 0
    nr_within1 = sum(1 for m in gt if abs(pred_nr.get(m, gt[m]) - gt[m]) <= 1) if pred_nr else 0
    nr_within5 = sum(1 for m in gt if abs(pred_nr.get(m, gt[m]) - gt[m]) <= 5) if pred_nr else 0
    nr_within50 = sum(1 for m in gt if abs(pred_nr.get(m, gt[m]) - gt[m]) <= 50) if pred_nr else 0
    nr_within100 = sum(1 for m in gt if abs(pred_nr.get(m, gt[m]) - gt[m]) <= 100) if pred_nr else 0

    results.append({
        'piece': piece,
        'status': 'ok',
        'total_measures': total,
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
output_path = '/tmp/baseline_results.json'
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

    print(f'\n=== Baseline Summary ({total_ok} pieces, {total_measures} total measures) ===')
    print(f'{"":>15} {"Exact":>10} {"Exact%":>10} {"±1tick":>10} {"±1%":>10} {"±5tick":>10} {"±5%":>10}')
    print(f'With GT ref:  {gt_exact:>10} {gt_exact/total_measures:>10.1%} {gt_w1:>10} {gt_w1/total_measures:>10.1%} {gt_w5:>10} {gt_w5/total_measures:>10.1%}')
    print(f'No reference: {nr_exact:>10} {nr_exact/total_measures:>10.1%} {nr_w1:>10} {nr_w1/total_measures:>10.1%} {nr_w5:>10} {nr_w5/total_measures:>10.1%}')

    # Per composer
    composer_results = defaultdict(list)
    for r in ok_results:
        composer = r['piece'].split('/')[0]
        composer_results[composer].append(r)

    print(f'\nPer-composer (GT ref | No ref):')
    print(f'{"Composer":>15} {"Pieces":>8} {"GT%":>10} {"±1%":>10} | {"NR%":>10} {"±1%":>10}')
    for composer in sorted(composer_results.keys(), key=lambda c: -len(composer_results[c])):
        cr = composer_results[composer]
        cm = sum(r['total_measures'] for r in cr)
        ce = sum(r['exact'] for r in cr)
        c1 = sum(r['within1'] for r in cr)
        nce = sum(r['nr_exact'] for r in cr)
        nc1 = sum(r['nr_within1'] for r in cr)
        print(f'{composer:>15} {len(cr):>8} {ce/cm:>10.1%} {c1/cm:>10.1%} | {nce/cm:>10.1%} {nc1/cm:>10.1%}')

errors = [r for r in results if r['status'] != 'ok']
if errors:
    print(f'\nFailed: {len(errors)} pieces')
    for e in errors[:5]:
        print(f'  {e["piece"]}: {e["status"]}')
