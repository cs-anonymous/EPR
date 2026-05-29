#!/usr/bin/env python3
"""Reformat piece_interpretation.json files from old format to new format.

Handles three cases:
  1. text_only: has 'text' but no 'compressed_interpretation_50'
     -> Generate complete new format with all fields
  2. compressed_singular: has 'compressed_interpretation' but no 'compressed_interpretation_50'
     -> Rename to compressed_interpretation_200, generate 50 and 100
  3. has_short_no_100: has 'compressed_interpretation_short' but no 'compressed_interpretation_100'
     -> Rename short->100, full->200, generate 50
"""

import json
import re
import os
import sys
from collections import Counter

BASE = "/home/sy/EPR/PianoCoReS/miditsv"


def parse_piece_id(piece_id):
    """Parse piece_id like 'Isaac_Albeniz-Iberia_11._Jerez' into components."""
    # Format: Composer_Composition_Movement
    parts = piece_id.split("-", 1)
    composer_raw = parts[0].replace("_", " ") if len(parts) > 0 else ""
    rest = parts[1] if len(parts) > 1 else ""

    # Split composition and movement
    # The movement is usually the last part after an underscore that follows Op./number
    movement = ""
    composition = rest

    # Try to detect movement: patterns like _11._Jerez, _No.1, _2._Tango, _Presto_(E_flat_minor)
    movement_patterns = [
        r"^(.+)_((?:No\.)?\d+[._:\-].+)$",  # _11._Jerez, _No.1_in_F_sharp
        r"^(.+)_((?:Allegro|Andante|Adagio|Largo|Presto|Moderato|Vivace|Grave|Maestoso|Andantino|Allegretto|Lento)[_:\-].*)$",  # tempo marking
    ]

    for pat in movement_patterns:
        m = re.match(pat, rest)
        if m:
            composition = m.group(1).replace("_", " ")
            movement = m.group(2).replace("_", " ")
            return composer_raw, composition, movement

    composition = rest.replace("_", " ")
    return composer_raw, composition, movement


def parse_path_info(filepath):
    """Extract composer and composition from file path."""
    rel = os.path.relpath(filepath, BASE)
    parts = rel.split(os.sep)
    composer_from_path = parts[0].replace("_", " ") if len(parts) > 0 else ""
    # Composition might be in parts[1] or further nested
    if len(parts) > 1:
        comp_from_path = parts[1].replace("_", " ")
    else:
        comp_from_path = ""
    return composer_from_path, comp_from_path


def extract_mood_from_text(text, existing_mood=None):
    """Extract or generate mood keywords from text."""
    if existing_mood:
        return existing_mood

    mood_keywords = {
        "lyrical": "lyrical", "lyricism": "lyrical", "singing": "cantabile",
        "virtuosic": "virtuosic", "virtuosity": "virtuosic", "brilliant": "brilliant",
        "dramatic": "dramatic", "intense": "intense", "passionate": "passionate",
        "melancholic": "melancholic", "melancholy": "melancholic", "somber": "somber",
        "playful": "playful", "light": "light", "graceful": "graceful",
        "dark": "dark", "turbulent": "turbulent", "ferocious": "ferocious",
        "tender": "tender", "gentle": "gentle", "intimate": "intimate",
        "solemn": "solemn", "contemplative": "contemplative", "meditative": "meditative",
        "noble": "noble", "majestic": "majestic", "heroic": "heroic",
        "restless": "restless", "agitated": "restless", "fiery": "fiery",
        "warm": "warm", "luminous": "luminous", "transparent": "transparent",
        "rhythmic": "rhythmically-driven", "dance-like": "dance-like",
        "introspective": "introspective", "austere": "austere",
        "exuberant": "exuberant", "jubilant": "jubilant",
        "ethereal": "ethereal", "dreamy": "dreamy",
        "percussive": "percussive", "driving": "driving",
    }

    text_lower = text.lower()
    found = []
    for word, mood in mood_keywords.items():
        if word in text_lower and mood not in found:
            found.append(mood)
            if len(found) >= 5:
                break

    if not found:
        found = ["expressive", "nuanced"]

    return found[:5]


def count_words(text):
    return len(text.split())


def truncate_to_words(text, target, tolerance=15):
    """Truncate text to approximately target words."""
    words = text.split()
    if len(words) <= target + tolerance:
        return " ".join(words)
    return " ".join(words[:target]) + "..."


def generate_compressed_50_from_text(text):
    """Generate ~50 word compressed interpretation from full text."""
    sentences = re.split(r'(?<=[.!?]) +', text)
    # Take the first 1-2 sentences that capture the essence
    result = []
    word_count = 0
    for s in sentences:
        words = s.split()
        if word_count + len(words) > 55:
            break
        result.append(s)
        word_count += len(words)
    return " ".join(result)


def generate_compressed_100_from_text(text):
    """Generate ~100 word compressed interpretation from full text."""
    sentences = re.split(r'(?<=[.!?]) +', text)
    result = []
    word_count = 0
    for s in sentences:
        words = s.split()
        if word_count + len(words) > 115:
            break
        result.append(s)
        word_count += len(words)
    return " ".join(result)


def generate_compressed_50_from_200(text_200):
    """Generate ~50 word compressed from 200-word text."""
    sentences = re.split(r'(?<=[.!?]) +', text_200)
    result = []
    word_count = 0
    for s in sentences:
        words = s.split()
        if word_count + len(words) > 55:
            break
        result.append(s)
        word_count += len(words)
    return " ".join(result)


def generate_compressed_100_from_200(text_200):
    """Generate ~100 word compressed from 200-word text."""
    sentences = re.split(r'(?<=[.!?]) +', text_200)
    result = []
    word_count = 0
    for s in sentences:
        words = s.split()
        if word_count + len(words) > 115:
            break
        result.append(s)
        word_count += len(words)
    return " ".join(result)


def generate_text_field_sections(text):
    """Parse a rich text field into structural_narrative, expressive_character, etc."""
    sentences = re.split(r'(?<=[.!?]) +', text)

    # Group sentences by likely purpose
    narrative_sentences = []
    character_sentences = []
    stylistic_sentences = []
    priority_sentences = []

    for s in sentences:
        s_lower = s.lower()
        if any(w in s_lower for w in ["form", "structure", "movement", "section", "builds", "arc", "narrative",
                                       "opens", "concludes", "alternates", "alternating", "culminates", "returns"]):
            narrative_sentences.append(s)
        elif any(w in s_lower for w in ["style", "tradition", "period", "baroque", "classical", "romantic",
                                         "impressionist", "genre", "national", "folk", "influence", "historical",
                                         "era", "century", "composed"]):
            stylistic_sentences.append(s)
        elif any(w in s_lower for w in ["perform", "interpret", "should", "must", "requires", "demands",
                                         "avoid", "maintain", "balance", "ensure", "bring out", "emphasize"]):
            priority_sentences.append(s)
        else:
            character_sentences.append(s)

    # Ensure each section has at least something
    all_sentences = sentences
    if not narrative_sentences and len(all_sentences) > 3:
        narrative_sentences = all_sentences[1:3]
    if not character_sentences and len(all_sentences) > 1:
        character_sentences = all_sentences[:1]
    if not stylistic_sentences and len(all_sentences) > 2:
        stylistic_sentences = all_sentences[-1:]

    return {
        "expressive_character": " ".join(character_sentences[:2]) if character_sentences else all_sentences[0] if all_sentences else "",
        "structural_narrative": " ".join(narrative_sentences[:2]) if narrative_sentences else all_sentences[1] if len(all_sentences) > 1 else all_sentences[0] if all_sentences else "",
        "stylistic_identity": " ".join(stylistic_sentences[:1]) if stylistic_sentences else "",
        "interpretive_priority": " ".join(priority_sentences[:1]) if priority_sentences else "Focus on the essential character and structural clarity of the piece.",
    }


def process_text_only(filepath):
    """Process a file that has only 'text' and 'evidence_sources' and 'piece_id'."""
    with open(filepath) as f:
        data = json.load(f)

    piece_id = data.get("piece_id", "")
    text = data.get("text", "")
    evidence = data.get("evidence_sources", [])

    # Parse metadata
    composer_raw, composition, movement = parse_piece_id(piece_id)
    composer_from_path, comp_from_path = parse_path_info(filepath)

    composer = composer_raw if composer_raw else composer_from_path
    if not composition and comp_from_path:
        composition = comp_from_path

    # Generate new fields from text
    mood = extract_mood_from_text(text)
    sections = generate_text_field_sections(text)

    # Generate compressed versions
    compressed_50 = generate_compressed_50_from_text(text)
    compressed_100 = generate_compressed_100_from_text(text)
    compressed_200 = text  # The original text is the 200

    new_data = {
        "piece_id": piece_id,
        "composer": composer,
        "composition": composition,
        "movement": movement,
        "alpha_type": "piece_level_interpretation",
        "scope": "piece",
        "performance_specific": False,
        "teaching_specific": False,
        "language": "en",
        "mood": mood,
        "expressive_character": sections["expressive_character"],
        "structural_narrative": sections["structural_narrative"],
        "stylistic_identity": sections["stylistic_identity"],
        "interpretive_priority": sections["interpretive_priority"],
        "evidence_sources": evidence,
        "compressed_interpretation_50": compressed_50,
        "compressed_interpretation_100": compressed_100,
        "compressed_interpretation_200": compressed_200,
    }

    return new_data, "text_only"


def process_compressed_singular(filepath):
    """Process a file that has 'compressed_interpretation' (singular) but no compressed_interpretation_50."""
    with open(filepath) as f:
        data = json.load(f)

    old_text = data.pop("compressed_interpretation", "")

    # Rename to _200
    data["compressed_interpretation_200"] = old_text
    data["compressed_interpretation_100"] = generate_compressed_100_from_200(old_text)
    data["compressed_interpretation_50"] = generate_compressed_50_from_200(old_text)

    return data, "compressed_singular"


def process_has_short_no_100(filepath):
    """Process a file that has compressed_interpretation_short but no compressed_interpretation_100."""
    with open(filepath) as f:
        data = json.load(f)

    short_text = data.pop("compressed_interpretation_short", "")
    full_text = data.pop("compressed_interpretation_full", "")

    # Rename: short -> 100, full -> 200
    data["compressed_interpretation_100"] = short_text
    data["compressed_interpretation_200"] = full_text
    # Generate 50 from the 100
    data["compressed_interpretation_50"] = generate_compressed_50_from_200(short_text)

    return data, "has_short_no_100"


def main():
    # Read the list of files
    with open("/tmp/reformat_files_1.txt") as f:
        lines = f.readlines()

    stats = Counter()
    processed = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        filepath = parts[0]
        reason = parts[1] if len(parts) > 1 else "unknown"

        if not os.path.exists(filepath):
            print(f"  SKIP (not found): {filepath}")
            stats["skipped"] += 1
            continue

        try:
            if reason == "text_only":
                new_data, type_label = process_text_only(filepath)
            elif reason == "compressed_singular":
                new_data, type_label = process_compressed_singular(filepath)
            elif reason == "has_short_no_100":
                new_data, type_label = process_has_short_no_100(filepath)
            else:
                print(f"  SKIP (unknown reason {reason}): {filepath}")
                stats["skipped"] += 1
                continue

            with open(filepath, "w") as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)

            stats[type_label] += 1
            rel = os.path.relpath(filepath, BASE)
            print(f"  OK [{type_label}]: {rel}")
            processed.append(filepath)

        except Exception as e:
            print(f"  ERROR: {filepath}: {e}")
            stats["error"] += 1

    print(f"\n{'='*60}")
    print(f"SUMMARY:")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"  total: {sum(stats.values())}")


if __name__ == "__main__":
    main()
