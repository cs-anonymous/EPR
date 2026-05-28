#!/usr/bin/env python3
"""
Search agent template for piece-level interpretation collection.

This script reads a batch file (list of pieces with exact CSV piece_ids),
and generates search results for each piece using WebSearch + WebFetch.

Run as an Agent task - it will use WebSearch and WebFetch tools.
"""

import json
import os
import re
from pathlib import Path

# ============================================================================
# Search strategy
# ============================================================================

def search_queries(composer, composition, movement=None):
    """Generate search queries for a piece."""
    pieces_str = f'{composer} {composition}'
    if movement:
        pieces_str += f' {movement}'
    return [
        f'{pieces_str} program notes',
        f'{pieces_str} interpretation analysis',
        f'{pieces_str} Wikipedia',
    ]

# ============================================================================
# Batch processing
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-file', required=True, help='Path to batch JSON file')
    parser.add_argument('--output-file', required=True, help='Path to output JSONL file')
    args = parser.parse_args()

    with open(args.batch_file) as f:
        pieces = json.load(f)

    print(f'Loaded {len(pieces)} pieces from {args.batch_file}')
    print(f'Output will be written to {args.output_file}')

    # Process each piece
    results = []
    for i, piece in enumerate(pieces):
        piece_id = piece['piece_id']
        composer = piece['composer']
        composition = piece['composition']
        movement = piece.get('movement', '')

        print(f'[{i+1}/{len(pieces)}] {piece_id}')
        print(f'  Composer: {composer}')
        print(f'  Composition: {composition}')
        if movement:
            print(f'  Movement: {movement}')

        # Build search queries
        queries = search_queries(composer, composition, movement)

        # Use WebSearch to find sources
        search_text = ""
        evidence_sources = []

        for q in queries:
            print(f'  Searching: {q}')
            # WebSearch will be called by the agent
            # Results are parsed and added to search_text

        results.append({
            'piece_id': piece_id,
            'text': search_text,
            'evidence_sources': evidence_sources,
        })

    # Write results
    with open(args.output_file, 'w') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f'\nWrote {len(results)} results to {args.output_file}')

if __name__ == '__main__':
    main()
