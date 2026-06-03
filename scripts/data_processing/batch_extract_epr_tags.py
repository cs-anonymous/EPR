#!/usr/bin/env python3
"""
Batch extract EPR conditioning tags (piece_interpretation + performance_concept)
for files 400-800 in all_file_paths.json.

Batches multiple files per API call to reduce request count.
"""

import json
import os
import sys
import time
import re
from pathlib import Path
from anthropic import Anthropic

SYSTEM_PROMPT = """You are a creative tag generator for piano performance conditioning.

For each piece, generate TWO comma-separated lists:

ALPHA (piece_interpretation): What emotional world does this piece inhabit?
- 5-8 comma-separated tag phrases, each 1-3 words (prefer 2-word phrases)
- Capture imagery, mood, narrative arc
- Be creative, specific, evocative
- NO composer names, dates, opus numbers, key signatures

BETA (performance_concept): What texture and touch should characterize the performance?
- 5-8 comma-separated tag phrases, each 1-3 words (prefer 2-word phrases)
- Describe physical/sonic qualities: texture, articulation, dynamics, phrasing
- NEVER use emotion words (expressive, dramatic, intense, lyrical, romantic, passionate, melancholic, joyful, etc.)

RULES:
- Alpha and Beta must NOT share ANY words
- No full sentences, no prose, no technical instructions
- Each tag 1-3 words, prefer 2-word phrases
- Be CREATIVE and specific to EACH piece

Output format (repeat for each piece index):
FILE_<index>_alpha: tag1, tag2, tag3, ...
FILE_<index>_beta: tag1, tag2, tag3, ..."""


def build_batch_context(slice_paths, start_idx, batch_size):
    """Build a single prompt containing multiple files' context."""
    chunks = []
    for i in range(batch_size):
        idx = start_idx + i
        rel_path = slice_paths[idx]
        full_path = os.path.join('/home/sy/EPR', rel_path)

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"  READ ERROR idx={idx}: {e}", file=sys.stderr)
            continue

        # Build context
        parts = []
        for key in ['compressed_interpretation_short', 'compressed_interpretation_full',
                    'expressive_character', 'structural_narrative', 'stylistic_identity',
                    'interpretive_priority', 'mood']:
            val = data.get(key, '')
            if val:
                if isinstance(val, list):
                    val = ', '.join(val)
                parts.append(f"{key}: {val}")
        context = '\n'.join(parts)

        # Get piece name from path for reference
        piece_name = rel_path.split('miditsv/')[-1].replace('_', ' ') if 'miditsv/' in rel_path else rel_path

        chunks.append(f"FILE_{idx}:\nPiece: {piece_name}\n{context}\n")

    return '\n---\n'.join(chunks), len(chunks)


def parse_batch_response(text, batch_indices):
    """Parse the batch LLM response into a dict of idx -> (alpha, beta)."""
    results = {}
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        # Match FILE_NNN_alpha: ... or file_nnn_alpha: ...
        m = re.match(r'FILE_(\d+)_(alpha|beta):\s*(.*)', line, re.IGNORECASE)
        if m:
            idx = int(m.group(1))
            field = m.group(2).lower()
            value = m.group(3).strip()
            if idx not in results:
                results[idx] = {}
            results[idx][field] = value
    return results


def validate_tags(alpha, beta):
    """Basic validation."""
    if not alpha or not beta:
        return False, "Missing alpha or beta"

    alpha_words = set(alpha.lower().replace(',', ' ').split())
    beta_words = set(beta.lower().replace(',', ' ').split())
    shared = alpha_words & beta_words
    if shared:
        # Not a hard fail, just a warning
        pass

    alpha_count = len([t.strip() for t in alpha.split(',') if t.strip()])
    beta_count = len([t.strip() for t in beta.split(',') if t.strip()])
    if alpha_count < 3 or beta_count < 3:
        return False, f"Too few tags"

    return True, "OK"


def write_file(idx, rel_path, alpha, beta):
    """Write the updated JSON back."""
    full_path = os.path.join('/home/sy/EPR', rel_path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['piece_interpretation'] = alpha
        data['performance_concept'] = beta
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"  WRITE ERROR idx={idx}: {e}", file=sys.stderr)
        return False


def main():
    # Initialize client
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if base_url:
        client = Anthropic(api_key=api_key, base_url=base_url)
    else:
        client = Anthropic(api_key=api_key)

    # Load paths
    with open('/home/sy/EPR/data/piece_interpretations/all_file_paths.json') as f:
        paths = json.load(f)

    slice_paths = paths[400:800]
    total = len(slice_paths)
    batch_size = 8  # Files per API call

    print(f"Processing {total} files in batches of {batch_size}...")

    success_count = 0
    fail_count = 0
    batch_num = 0

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_num += 1

        # Build context for this batch
        batch_indices = list(range(start, end))
        context, actual_count = build_batch_context(slice_paths, start, end - start)

        if actual_count == 0:
            continue

        prompt = f"Generate alpha and beta tags for these {actual_count} pieces:\n\n{context}\n\nOutput each piece's tags as FILE_<index>_alpha: ... and FILE_<index>_beta: ..."

        # Retry logic for rate limiting
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = client.messages.create(
                    model='qwen3.6-plus',
                    max_tokens=2000,
                    system=SYSTEM_PROMPT,
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.8,
                )
                text = resp.content[0].text.strip()
                break
            except Exception as e:
                err_str = str(e)
                if '429' in err_str or 'rate' in err_str.lower():
                    wait = 10 * (attempt + 1)
                    print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"  LLM error batch {batch_num}: {err_str[:200]}", file=sys.stderr)
                    time.sleep(2)
                    break
        else:
            print(f"  FAILED batch {batch_num} after retries", file=sys.stderr)
            fail_count += (end - start)
            continue

        # Parse response
        parsed = parse_batch_response(text, batch_indices)

        for idx in batch_indices:
            rel_path = slice_paths[idx]
            if idx in parsed and 'alpha' in parsed[idx] and 'beta' in parsed[idx]:
                alpha = parsed[idx]['alpha']
                beta = parsed[idx]['beta']
                ok, msg = validate_tags(alpha, beta)
                if ok and write_file(idx, rel_path, alpha, beta):
                    success_count += 1
                else:
                    fail_count += 1
                    print(f"  VALID FAIL idx={idx}: {msg}", file=sys.stderr)
            else:
                fail_count += 1
                print(f"  MISSING tags for idx={idx}", file=sys.stderr)

        # Progress
        processed = min(end, total)
        print(f"  Batch {batch_num}: {processed}/{total} (ok={success_count}, fail={fail_count})")

        # Small delay between batches
        time.sleep(1.5)

    print(f"\n=== SUMMARY ===")
    print(f"Total files: {total}")
    print(f"Success: {success_count}")
    print(f"Failed: {fail_count}")


if __name__ == '__main__':
    main()
