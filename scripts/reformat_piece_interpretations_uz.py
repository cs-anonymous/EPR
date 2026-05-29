#!/usr/bin/env python3
"""
Reformat piece_interpretation.json files to use 3-tier compressed format.
Processes files in PianoCoReS/miditsv/[U-Z]*/**/piece_interpretation.json
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List


def extract_metadata_from_path(file_path: str) -> Dict[str, str]:
    """Extract composer, composition, and movement from file path."""
    parts = Path(file_path).parts

    try:
        miditsv_idx = parts.index('miditsv')
    except ValueError:
        return {}

    metadata = {}

    if miditsv_idx + 1 < len(parts):
        metadata['composer'] = parts[miditsv_idx + 1].replace('_', ' ')

    if miditsv_idx + 2 < len(parts):
        metadata['composition'] = parts[miditsv_idx + 2].replace('_', ' ')

    if miditsv_idx + 3 < len(parts) and parts[miditsv_idx + 3] != 'piece_interpretation.json':
        metadata['movement'] = parts[miditsv_idx + 3].replace('_', ' ')

    return metadata


def generate_mood_keywords(text: str) -> List[str]:
    """Generate 3-5 mood keywords from text."""
    mood_map = {
        'dreamy': ['dream', 'floating', 'ethereal', 'hazy'],
        'mysterious': ['mystery', 'enigma', 'secret', 'hidden'],
        'contemplative': ['contemplat', 'reflect', 'meditat', 'introspect'],
        'playful': ['playful', 'jest', 'game', 'whimsic'],
        'melancholic': ['melanchol', 'sad', 'lament', 'mourn', 'sorrow'],
        'brilliant': ['brilliant', 'sparkling', 'virtuos', 'dazzl'],
        'lyrical': ['lyrical', 'singing', 'melodic', 'cantabile'],
        'dramatic': ['dramatic', 'intense', 'passion', 'fierce'],
        'gentle': ['gentle', 'tender', 'delicate', 'soft'],
        'energetic': ['energetic', 'vivace', 'presto', 'vigorous'],
        'serene': ['serene', 'peaceful', 'calm', 'tranquil'],
        'nostalgic': ['nostalg', 'memory', 'reminisce', 'wistful'],
        'heroic': ['heroic', 'triumph', 'victory', 'noble'],
        'intimate': ['intimate', 'personal', 'confessional', 'private'],
        'elegant': ['elegant', 'refined', 'graceful', 'polished']
    }

    text_lower = text.lower()
    moods = []

    for mood, keywords in mood_map.items():
        if any(kw in text_lower for kw in keywords):
            moods.append(mood)

    if len(moods) < 3:
        if 'slow' in text_lower or 'lento' in text_lower or 'adagio' in text_lower:
            if 'contemplative' not in moods:
                moods.append('contemplative')
        if 'fast' in text_lower or 'allegro' in text_lower:
            if 'energetic' not in moods:
                moods.append('energetic')
        if 'waltz' in text_lower or 'dance' in text_lower:
            if 'elegant' not in moods:
                moods.append('elegant')

    return moods[:5] if moods else ['expressive', 'nuanced', 'refined']


def determine_stylistic_identity(text: str, composer: str) -> str:
    """Infer stylistic identity from text and composer."""
    text_lower = text.lower()
    composer_lower = composer.lower()

    if any(c in composer_lower for c in ['bach', 'vivaldi', 'handel', 'zipoli', 'valente']):
        return 'Baroque'
    elif any(c in composer_lower for c in ['mozart', 'haydn']):
        return 'Classical'
    elif any(c in composer_lower for c in ['chopin', 'schumann', 'liszt', 'brahms', 'wagner', 'schubert']):
        return 'Romanticism'
    elif any(c in composer_lower for c in ['debussy', 'ravel']):
        return 'Impressionism'
    elif any(c in composer_lower for c in ['prokofiev', 'bartók', 'bartok']):
        return 'Russian Modernism' if 'prokofiev' in composer_lower else 'Hungarian Modernism'
    elif any(c in composer_lower for c in ['joplin', 'shepherd', 'waller', 'wenrich']):
        return 'Ragtime'
    elif 'vierne' in composer_lower:
        return 'French Romantic'
    elif 'elgar' in composer_lower:
        return 'English Romantic'

    if 'romantic' in text_lower:
        return 'Romanticism'
    elif 'modern' in text_lower:
        return 'Modernism'
    elif 'impressionist' in text_lower:
        return 'Impressionism'

    return 'Western Classical'


def generate_compressed_50(data: Dict, text: str) -> str:
    """Generate ultra-compressed 50-word interpretation."""
    # Use the first 50 words from the text, ensuring we capture key information
    words = text.split()

    if len(words) <= 50:
        return text

    # Take first 50 words and try to end at a sentence boundary
    first_50 = ' '.join(words[:50])

    # If we're in the middle of a sentence, try to complete it
    if not first_50.endswith('.'):
        # Look for the next period within the next 10 words
        for i in range(50, min(60, len(words))):
            if words[i].endswith('.'):
                return ' '.join(words[:i+1])
        # Otherwise just truncate at 50 words
        return first_50 + '...'

    return first_50


def generate_compressed_100(data: Dict, text: str) -> str:
    """Generate medium-compressed 100-word interpretation."""
    sentences = [s.strip() for s in text.split('.') if s.strip()]

    result_parts = []
    word_count = 0

    for sent in sentences[:5]:
        words = sent.split()
        if word_count + len(words) <= 100:
            result_parts.append(sent)
            word_count += len(words)
        else:
            remaining = 100 - word_count
            if remaining > 10:
                result_parts.append(' '.join(words[:remaining]) + '...')
            break

    return '. '.join(result_parts) + ('.' if result_parts and not result_parts[-1].endswith('...') else '')


def generate_compressed_200(data: Dict, text: str) -> str:
    """Generate full-compressed 200-word interpretation."""
    words = text.split()

    if len(words) <= 200:
        return text

    return ' '.join(words[:197]) + '...'


def process_old_format(data: Dict, file_path: str, text: str) -> Dict:
    """Convert old format (text-only) to new complete format."""
    metadata = extract_metadata_from_path(file_path)

    # Ensure piece_id
    if 'piece_id' not in data or not data['piece_id']:
        composer = metadata.get('composer', 'Unknown')
        composition = metadata.get('composition', 'Unknown')
        movement = metadata.get('movement', '')
        data['piece_id'] = f"{composer}-{composition}_{movement}".replace(' ', '_')

    # Add metadata fields
    data['composer'] = metadata.get('composer', '')
    data['composition'] = metadata.get('composition', '')
    data['movement'] = metadata.get('movement', '')

    # Add alpha fields
    data['alpha_type'] = 'piece_level_interpretation'
    data['scope'] = 'piece'
    data['performance_specific'] = False
    data['teaching_specific'] = False
    data['language'] = 'en'

    # Generate mood keywords
    data['mood'] = generate_mood_keywords(text)

    # Extract interpretive fields from text
    sentences = [s.strip() for s in text.split('.') if s.strip()]

    # Expressive character: first 1-2 sentences
    data['expressive_character'] = '. '.join(sentences[:2]) + '.' if len(sentences) >= 2 else text

    # Structural narrative
    if len(sentences) > 3:
        data['structural_narrative'] = '. '.join(sentences[2:4]) + '.'
    else:
        data['structural_narrative'] = f"A {data.get('movement', 'piece')} with {data['mood'][0] if data['mood'] else 'expressive'} character."

    # Stylistic identity
    data['stylistic_identity'] = determine_stylistic_identity(text, data.get('composer', ''))

    # Interpretive priority
    if len(sentences) > 4:
        data['interpretive_priority'] = sentences[-1] + '.'
    else:
        mood_desc = data['mood'][0] if data['mood'] else 'expressive'
        data['interpretive_priority'] = f"Focus on {mood_desc} character and {data.get('stylistic_identity', 'stylistic')} authenticity."

    # Generate compressed interpretations
    data['compressed_interpretation_50'] = generate_compressed_50(data, text)
    data['compressed_interpretation_100'] = generate_compressed_100(data, text)
    data['compressed_interpretation_200'] = generate_compressed_200(data, text)

    return data


def process_intermediate_format(data: Dict) -> Dict:
    """Convert intermediate format (short/full) to new format (50/100/200)."""
    # Get source text - prefer full over short
    short_text = data.get('compressed_interpretation_short', '')
    full_text = data.get('compressed_interpretation_full', '')

    # If we don't have the old fields, use the existing 200 field as source
    if not full_text and not short_text:
        full_text = data.get('compressed_interpretation_200', '')
        short_text = data.get('compressed_interpretation_100', '')

    # Use full text as the primary source for generating compressed_50
    source_text = full_text if full_text else short_text

    # Rename existing fields if they exist
    if 'compressed_interpretation_short' in data:
        data['compressed_interpretation_100'] = data.pop('compressed_interpretation_short')

    if 'compressed_interpretation_full' in data:
        data['compressed_interpretation_200'] = data.pop('compressed_interpretation_full')

    # Generate or regenerate compressed_interpretation_50 from the source text
    if source_text:
        data['compressed_interpretation_50'] = generate_compressed_50(data, source_text)

    return data


def process_file(file_path: str) -> tuple:
    """Process a single piece_interpretation.json file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check what format we have
        has_text = "text" in data
        has_short = "compressed_interpretation_short" in data
        has_full = "compressed_interpretation_full" in data
        has_single = "compressed_interpretation" in data  # Old single-field format
        has_50 = "compressed_interpretation_50" in data
        has_100 = "compressed_interpretation_100" in data
        has_200 = "compressed_interpretation_200" in data

        # Check if compressed_interpretation_50 is too short (likely truncated)
        needs_fix = False
        if has_50:
            text_50 = data.get('compressed_interpretation_50', '')
            word_count = len(text_50.split())
            # Should be around 40-60 words, anything under 30 is suspicious
            if word_count < 30:
                needs_fix = True

        # If already has new format and doesn't need fixing, skip
        if has_50 and has_100 and has_200 and not needs_fix:
            return ("skip", "already_new")

        # Process based on format
        if has_text and not has_short and not has_full and not has_single:
            # Old format: text-only
            text = data.pop('text')
            data = process_old_format(data, file_path, text)
            format_type = "text_only"
        elif has_single and not has_50:
            # Old single compressed_interpretation format
            text = data.pop('compressed_interpretation')
            # Treat it like the full text and generate all three tiers
            data['compressed_interpretation_50'] = generate_compressed_50(data, text)
            data['compressed_interpretation_100'] = generate_compressed_100(data, text)
            data['compressed_interpretation_200'] = text  # Use original as the 200-word version
            format_type = "single_compressed"
        elif has_short or has_full or needs_fix:
            # Intermediate format: short/full OR needs fixing
            data = process_intermediate_format(data)
            format_type = "short_and_full" if (has_short or has_full) else "fixed_50"
        else:
            return ("skip", "unknown")

        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return ("success", format_type)

    except Exception as e:
        print(f"    Error processing file: {e}")
        return ("error", str(e))


def main():
    """Main processing function."""
    base_path = Path("/home/sy/EPR/PianoCoReS/miditsv")

    # Find all piece_interpretation.json files where any directory component starts with U-Z
    all_files = list(base_path.glob("**/piece_interpretation.json"))

    files = []
    for file_path in all_files:
        # Check if any directory component in the path starts with U-Z
        parts = file_path.parts
        for part in parts:
            if part and part[0] in 'UVWXYZ':
                files.append(str(file_path))
                break

    files = sorted(files)

    print(f"Found {len(files)} files in U-Z directories\n")

    # Statistics
    stats = {
        "total": len(files),
        "success": 0,
        "skip_already_new": 0,
        "skip_unknown": 0,
        "error": 0,
        "text_only_converted": 0,
        "short_and_full_converted": 0,
        "single_compressed_converted": 0,
        "fixed_50": 0
    }

    for i, file_path in enumerate(files, 1):
        rel_path = str(Path(file_path).relative_to(base_path))
        print(f"[{i}/{len(files)}] {rel_path}")

        try:
            status, format_type = process_file(file_path)

            if status == "success":
                stats["success"] += 1
                if format_type == "text_only":
                    stats["text_only_converted"] += 1
                elif format_type == "short_and_full":
                    stats["short_and_full_converted"] += 1
                elif format_type == "single_compressed":
                    stats["single_compressed_converted"] += 1
                elif format_type == "fixed_50":
                    stats["fixed_50"] += 1
                print(f"  ✓ {status} ({format_type})")
            elif status == "skip":
                if format_type == "already_new":
                    stats["skip_already_new"] += 1
                else:
                    stats["skip_unknown"] += 1
                print(f"  - {status} ({format_type})")
            else:
                stats["error"] += 1
                print(f"  ✗ {status}: {format_type}")
        except Exception as e:
            print(f"  ✗ Exception: {e}")
            stats["error"] += 1

    # Print summary
    print("\n" + "="*60)
    print("PROCESSING COMPLETE")
    print("="*60)
    print(f"Total files: {stats['total']}")
    print(f"Successfully converted: {stats['success']}")
    print(f"  - Old format (text only): {stats['text_only_converted']}")
    print(f"  - Old format (short+full): {stats['short_and_full_converted']}")
    print(f"  - Old format (single compressed): {stats['single_compressed_converted']}")
    print(f"  - Fixed compressed_50: {stats['fixed_50']}")
    print(f"Skipped (already new): {stats['skip_already_new']}")
    print(f"Skipped (unknown): {stats['skip_unknown']}")
    print(f"Errors: {stats['error']}")


if __name__ == "__main__":
    main()
