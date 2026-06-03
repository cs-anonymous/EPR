#!/usr/bin/env python3
"""
Stage B: Extract α (piece_interpretation) and β (performance_concept) tags
from existing piece_interpretation.json files.

Usage:
  python scripts/extract_epr_conditioning.py [--start N] [--end N]

Reads:  data/piece_interpretations/all_file_paths.json
Writes: data/miditsv/.../piece_interpretation.json (in-place, adds α+β fields)
"""

import json
import os
import argparse
import glob

# ============================================================================
# EPR Conditioning Tag Extraction
# ============================================================================

def extract_alpha_beta(obj):
    """Extract α (piece_interpretation) and β (performance_concept) from rich JSON.

    α = imagery, mood, narrative (what emotional world this piece inhabits)
    β = texture, touch, articulation, dynamics (how the performance should sound)

    CRITICAL: α and β must NOT share any words.
    """
    piece_id = obj.get('piece_id', '')
    composer = obj.get('composer', '')
    movement = obj.get('movement', '')
    composition = obj.get('composition', '')
    mood = obj.get('mood', [])
    expressive = obj.get('expressive_character', '')
    narrative = obj.get('structural_narrative', '')
    stylistic = obj.get('stylistic_identity', '')
    priority = obj.get('interpretive_priority', '')
    comp_short = obj.get('compressed_interpretation_short', '')
    comp_full = obj.get('compressed_interpretation_full', '')
    perf_gist = obj.get('performance_gist', '')

    # Combine all rich text for context
    all_text = ' '.join(filter(None, [expressive, narrative, stylistic, priority, comp_short, comp_full, perf_gist]))
    mood_str = ' '.join(mood) if isinstance(mood, list) else ''

    # Build α from expressive content + mood + narrative imagery
    alpha_tags = []
    if expressive:
        alpha_tags.extend(_extract_phrases(expressive, max_tags=3))
    if narrative:
        alpha_tags.extend(_extract_phrases(narrative, max_tags=2))
    if stylistic:
        alpha_tags.extend(_extract_phrases(stylistic, max_tags=2))
    if mood_str:
        for m in mood_str.split():
            if len(m) > 3:
                alpha_tags.append(m.lower())

    # Build β from interpretive priority + performance_gist + structural cues
    beta_tags = []
    if priority:
        beta_tags.extend(_extract_phrases(priority, max_tags=3))
    if perf_gist:
        beta_tags.extend(_extract_phrases(perf_gist, max_tags=3))

    # Deduplicate and ensure no overlap
    alpha_set = set(t.lower() for t in alpha_tags)
    beta_set = set(t.lower() for t in beta_tags)
    # Remove any β that appears in α
    beta_tags = [t for t in beta_tags if t.lower() not in alpha_set]

    # Remove emotion words from β
    emotion_words = {'expressive', 'dramatic', 'intense', 'lyrical', 'emotional', 'passionate'}
    beta_tags = [t for t in beta_tags if t.lower() not in emotion_words]

    # Format as comma-separated
    piece_interpretation = ', '.join(alpha_tags[:8]) if alpha_tags else ''
    performance_concept = ', '.join(beta_tags[:8]) if beta_tags else ''

    return piece_interpretation, performance_concept


def _extract_phrases(text, max_tags=3):
    """Extract meaningful phrases from text."""
    phrases = []
    for part in text.split(','):
        part = part.strip().strip('.').strip()
        if part and len(part) > 2:
            phrases.append(part)
    return phrases[:max_tags]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int, default=None)
    args = parser.parse_args()

    with open('data/piece_interpretations/all_file_paths.json') as f:
        paths = json.load(f)

    paths = paths[args.start:]
    if args.end:
        paths = paths[:args.end - args.start]

    print(f"Processing {len(paths)} files (start={args.start}, end={args.end})")

    done = 0
    for i, path in enumerate(paths):
        if not os.path.exists(path):
            continue

        with open(path) as f:
            obj = json.load(f)

        if 'piece_interpretation' in obj and 'performance_concept' in obj:
            continue

        alpha, beta = extract_alpha_beta(obj)
        obj['piece_interpretation'] = alpha
        obj['performance_concept'] = beta

        with open(path, 'w') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

        done += 1

    print(f"Done: {done} files processed")


if __name__ == '__main__':
    main()
