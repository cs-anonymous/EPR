#!/usr/bin/env python3
"""
Generate search batch files from pieces_batch.json.

Splits 1600 pieces into composer-based batches, each with exact CSV piece_ids.
Each batch contains pieces for ~1 composer (or small group), to keep the
search scope manageable.

Output: data/piece_interpretations/batch_*.json
  Each file contains a list of piece dicts with exact piece_id, composer, etc.
"""

import json
from collections import defaultdict

with open('data/piece_interpretations/pieces_batch.json') as f:
    pieces = json.load(f)

# Group by composer
groups = defaultdict(list)
for p in pieces:
    groups[p['composer']].append(p)

# Sort composers: large first, then alphabetically
sorted_composers = sorted(groups.keys(), key=lambda c: (-len(groups[c]), c))

# Strategy: each batch is one composer, but cap at 30 pieces per batch
# For large composers (Bach 276, Chopin 152, etc.), split into sub-batches
batch_num = 0
for composer in sorted_composers:
    ps = groups[composer]
    max_per_batch = 30
    for i in range(0, len(ps), max_per_batch):
        batch_pieces = ps[i:i+max_per_batch]
        batch_num += 1
        batch_file = f'data/piece_interpretations/batch_{batch_num:04d}.json'
        with open(batch_file, 'w') as f:
            json.dump(batch_pieces, f, ensure_ascii=False, indent=2)
        print(f'Batch {batch_num:04d}: {composer} ({len(batch_pieces)} pieces) -> {batch_file}')

print(f'\nTotal batches: {batch_num}')
print(f'Total pieces: {len(pieces)}')
