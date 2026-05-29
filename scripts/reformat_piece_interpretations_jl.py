#!/usr/bin/env python3
"""
Reformat piece interpretation files to use 3-tier compressed format.
Processes files in PianoCoReS/miditsv/[J-L]*/**/piece_interpretation.json
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, List


def extract_metadata_from_path(file_path: Path) -> Dict[str, str]:
    """Extract composer, composition, and movement from file path."""
    parts = file_path.parts

    # Find the index of 'miditsv' in the path
    try:
        miditsv_idx = parts.index('miditsv')
    except ValueError:
        return {"composer": "", "composition": "", "movement": ""}

    # Composer is the next part after miditsv
    composer = parts[miditsv_idx + 1] if len(parts) > miditsv_idx + 1 else ""

    # Composition is the next part
    composition = parts[miditsv_idx + 2] if len(parts) > miditsv_idx + 2 else ""

    # Movement is the next part if it exists and isn't the filename
    movement = ""
    if len(parts) > miditsv_idx + 3 and parts[miditsv_idx + 3] != 'piece_interpretation.json':
        movement = parts[miditsv_idx + 3]

    return {
        "composer": composer.replace('_', ' '),
        "composition": composition.replace('_', ' '),
        "movement": movement.replace('_', ' ')
    }


def extract_moods_from_text(text: str) -> List[str]:
    """Extract mood keywords from text."""
    # Common mood descriptors in music
    mood_keywords = [
        'energetic', 'confident', 'celebratory', 'joyous', 'playful', 'sparkling',
        'dramatic', 'lyrical', 'melancholic', 'passionate', 'virtuosic', 'brilliant',
        'sensuous', 'fluid', 'powerful', 'delicate', 'mysterious', 'triumphant',
        'nostalgic', 'whimsical', 'heroic', 'tender', 'exuberant', 'contemplative',
        'bold', 'graceful', 'intense', 'serene', 'turbulent', 'elegant'
    ]

    text_lower = text.lower()
    found_moods = []

    for mood in mood_keywords:
        if mood in text_lower and mood not in found_moods:
            found_moods.append(mood)
            if len(found_moods) >= 5:
                break

    # Ensure at least 3 moods
    if len(found_moods) < 3:
        found_moods.extend(['expressive', 'nuanced', 'refined'][:3 - len(found_moods)])

    return found_moods[:5]


def generate_compressed_50(text: str, composer: str, composition: str) -> str:
    """Generate ultra-compressed 50-word interpretation with high-density style markers."""
    # Extract key phrases from the text
    sentences = text.split('. ')

    # Try to find the most characteristic sentence
    key_sentence = sentences[0] if sentences else text

    # Create a compressed version
    words = key_sentence.split()
    if len(words) > 50:
        compressed = ' '.join(words[:50]) + '...'
    else:
        # Add more context if we have room
        for sentence in sentences[1:]:
            potential = key_sentence + '. ' + sentence
            if len(potential.split()) <= 50:
                key_sentence = potential
            else:
                break
        compressed = key_sentence

    return compressed


def generate_compressed_100(text: str) -> str:
    """Generate compressed 100-word interpretation."""
    sentences = text.split('. ')

    # Build up to approximately 100 words
    result = []
    word_count = 0

    for sentence in sentences:
        sentence_words = sentence.split()
        if word_count + len(sentence_words) <= 100:
            result.append(sentence)
            word_count += len(sentence_words)
        else:
            # Add partial sentence if we have room
            remaining = 100 - word_count
            if remaining > 10:
                result.append(' '.join(sentence_words[:remaining]) + '...')
            break

    return '. '.join(result)


def generate_compressed_200(text: str) -> str:
    """Generate compressed 200-word interpretation."""
    words = text.split()

    if len(words) <= 200:
        return text

    # Take first 200 words and try to end at a sentence boundary
    compressed_words = words[:200]
    compressed_text = ' '.join(compressed_words)

    # Try to end at a period
    last_period = compressed_text.rfind('.')
    if last_period > 150:  # Only if we're reasonably close to the end
        compressed_text = compressed_text[:last_period + 1]
    else:
        compressed_text += '...'

    return compressed_text


def generate_expressive_character(text: str) -> str:
    """Extract or generate expressive character description."""
    sentences = text.split('. ')

    # Look for sentences with characteristic descriptive words
    for sentence in sentences:
        if any(word in sentence.lower() for word in ['character', 'atmosphere', 'mood', 'expressive', 'evoke']):
            return sentence.strip()

    # Default to first sentence
    return sentences[0].strip() if sentences else text[:200]


def generate_structural_narrative(text: str) -> str:
    """Extract or generate structural narrative description."""
    sentences = text.split('. ')

    # Look for sentences about structure, form, or narrative
    for sentence in sentences:
        if any(word in sentence.lower() for word in ['structure', 'form', 'unfold', 'movement', 'section', 'strain', 'narrative']):
            return sentence.strip()

    # Look for sentences about the piece's progression
    for sentence in sentences[1:3]:
        if any(word in sentence.lower() for word in ['open', 'begin', 'build', 'climax', 'close', 'end']):
            return sentence.strip()

    return "The piece unfolds through carefully structured sections that build dramatic tension and release."


def generate_stylistic_identity(text: str, composer: str) -> str:
    """Extract or generate stylistic identity."""
    text_lower = text.lower()

    # Look for style/period mentions
    styles = []

    style_keywords = {
        'romantic': 'Romantic',
        'impressionist': 'Impressionist',
        'impressionism': 'Impressionism',
        'baroque': 'Baroque',
        'classical': 'Classical',
        'ragtime': 'Ragtime',
        'jazz': 'Jazz',
        'modern': 'Modern',
        'contemporary': 'Contemporary'
    }

    for keyword, style in style_keywords.items():
        if keyword in text_lower:
            styles.append(style)

    if styles:
        return ', '.join(styles[:2])

    # Default based on composer
    if 'Liszt' in composer or 'Chopin' in composer or 'Schumann' in composer:
        return 'Romantic'
    elif 'Debussy' in composer or 'Ravel' in composer:
        return 'Impressionist'
    elif 'Joplin' in composer:
        return 'Ragtime'
    elif 'Bach' in composer or 'Scarlatti' in composer:
        return 'Baroque'

    return 'Classical tradition'


def generate_interpretive_priority(text: str) -> str:
    """Generate interpretive priority guidance."""
    # Look for technical or interpretive guidance in the text
    sentences = text.split('. ')

    for sentence in sentences:
        if any(word in sentence.lower() for word in ['performer', 'performance', 'must', 'should', 'require', 'demand', 'challenge']):
            return sentence.strip()

    return "Balance technical precision with expressive freedom, allowing the music's inherent character to emerge naturally."


def process_old_format(data: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
    """Convert old format (text only) to new complete format."""
    text = data.get('text', '')
    piece_id = data.get('piece_id', '')

    metadata = extract_metadata_from_path(file_path)

    new_data = {
        "piece_id": piece_id,
        "composer": metadata['composer'],
        "composition": metadata['composition'],
        "movement": metadata['movement'],
        "alpha_type": "piece_level_interpretation",
        "scope": "piece",
        "performance_specific": False,
        "teaching_specific": False,
        "language": "en",
        "mood": extract_moods_from_text(text),
        "expressive_character": generate_expressive_character(text),
        "structural_narrative": generate_structural_narrative(text),
        "stylistic_identity": generate_stylistic_identity(text, metadata['composer']),
        "interpretive_priority": generate_interpretive_priority(text),
        "compressed_interpretation_50": generate_compressed_50(text, metadata['composer'], metadata['composition']),
        "compressed_interpretation_100": generate_compressed_100(text),
        "compressed_interpretation_200": generate_compressed_200(text),
        "evidence_sources": data.get('evidence_sources', [])
    }

    return new_data


def process_new_format(data: Dict[str, Any]) -> Dict[str, Any]:
    """Update new format: rename short->100, full->200, add 50."""
    # Rename fields
    if 'compressed_interpretation_short' in data:
        data['compressed_interpretation_100'] = data.pop('compressed_interpretation_short')

    if 'compressed_interpretation_full' in data:
        data['compressed_interpretation_200'] = data.pop('compressed_interpretation_full')

    # Generate compressed_interpretation_50 if not present
    if 'compressed_interpretation_50' not in data:
        # Use the 100 version as source
        source_text = data.get('compressed_interpretation_100', data.get('expressive_character', ''))
        data['compressed_interpretation_50'] = generate_compressed_50(
            source_text,
            data.get('composer', ''),
            data.get('composition', '')
        )

    return data


def process_file(file_path: Path) -> bool:
    """Process a single piece_interpretation.json file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Determine format and process accordingly
        if 'text' in data and 'compressed_interpretation_short' not in data and 'compressed_interpretation_100' not in data:
            # Old format
            new_data = process_old_format(data, file_path)
        else:
            # New format (or partial new format)
            new_data = process_new_format(data)

        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)

        return True

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False


def main():
    """Main processing function."""
    base_path = Path('/home/sy/EPR/PianoCoReS/miditsv')

    # Find all piece_interpretation.json files in B-L directories
    # (includes Bach, Bortkiewicz, Chopin, Czerny, Daquin, Debussy, Diabelli, Glinka, Gobbaerts, Grieg, J-L composers)
    patterns = ['[B-L]*']
    files = []

    for pattern in patterns:
        for composer_dir in sorted(base_path.glob(pattern)):
            if composer_dir.is_dir():
                for file_path in composer_dir.rglob('piece_interpretation.json'):
                    files.append(file_path)

    print(f"Found {len(files)} files to process")

    processed = 0
    failed = 0

    for file_path in files:
        if process_file(file_path):
            processed += 1
        else:
            failed += 1

    print(f"\nProcessing complete:")
    print(f"  Successfully processed: {processed}")
    print(f"  Failed: {failed}")


if __name__ == '__main__':
    main()
