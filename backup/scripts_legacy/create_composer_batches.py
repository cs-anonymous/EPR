#!/usr/bin/env python3
"""
Create composer-level search batches.

Instead of searching per-piece (1600 pieces × 3 searches = 4800 searches),
we search per-composer (~155 composers × 3 searches = ~465 searches).

Each composer batch contains:
- composer name
- list of all pieces by that composer with their exact piece_ids
- recommended search queries for the composer's works
"""

import json
from collections import defaultdict

with open('data/piece_interpretations/pieces_batch.json') as f:
    pieces = json.load(f)

# Group by composer
groups = defaultdict(list)
for p in pieces:
    groups[p['composer']].append(p)

# Create composer batches
sorted_composers = sorted(groups.keys(), key=lambda c: (-len(groups[c]), c))

batch_num = 0
for composer in sorted_composers:
    ps = groups[composer]
    batch_num += 1

    # Build recommended search queries based on unique collections
    collections = set()
    for p in ps:
        comp = p['composition']
        collections.add(comp)

    # Unique compositions for search queries
    unique_comps = sorted(collections)

    batch_data = {
        'composer': composer,
        'num_pieces': len(ps),
        'pieces': ps,
        'unique_compositions': unique_comps,
        'recommended_queries': [f"{composer} program notes piano works"]
    }

    # Add specific queries for major works
    for comp in unique_comps[:5]:  # Top 5 compositions
        batch_data['recommended_queries'].append(f"{composer} {comp} analysis")

    batch_file = f'data/piece_interpretations/composer_batch_{batch_num:04d}.json'
    with open(batch_file, 'w') as f:
        json.dump(batch_data, f, ensure_ascii=False, indent=2)

print(f"Created {batch_num} composer batches")
print(f"Total pieces: {len(pieces)}")

# Summary
for i, composer in enumerate(sorted_composers[:20]):
    num_pieces = len(groups[composer])
    print(f"  Batch {i+1:04d}: {composer} ({num_pieces} pieces, {len(set(p['composition'] for p in groups[composer]))} unique works)")
if len(sorted_composers) > 20:
    print(f"  ... and {len(sorted_composers) - 20} more composers")
