#!/usr/bin/env python3
"""
Reformat piece_interpretation.json files to use 3-tier compressed format.
"""

import json
import os
import sys
from pathlib import Path
from anthropic import Anthropic

def extract_composer_composition_from_path(file_path):
    """Extract composer, composition, movement from file path."""
    parts = Path(file_path).parts
    try:
        miditsv_idx = parts.index('miditsv')
        composer_dir = parts[miditsv_idx + 1] if miditsv_idx + 1 < len(parts) else ""
        composition_dir = parts[miditsv_idx + 2] if miditsv_idx + 2 < len(parts) else ""
        movement_dir = parts[miditsv_idx + 3] if miditsv_idx + 3 < len(parts) else ""

        # Clean up names
        composer = composer_dir.replace('_', ' ')
        composition = composition_dir.replace('_', ' ')
        movement = movement_dir.replace('_', ' ') if movement_dir and movement_dir != 'piece_interpretation.json' else ""

        return composer, composition, movement
    except (ValueError, IndexError):
        return "", "", ""


def generate_complete_interpretation(existing_data, file_path):
    """
    Generate complete interpretation structure including all fields.

    Returns dict with all required fields for new format.
    """

    # Initialize client here to avoid hanging on import
    # Use ANTHROPIC_AUTH_TOKEN if ANTHROPIC_API_KEY is not set
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if base_url:
        client = Anthropic(api_key=api_key, base_url=base_url)
    else:
        client = Anthropic(api_key=api_key)

    # Determine what content we have to work with
    if "text" in existing_data:
        source_content = existing_data["text"]
        format_type = "old_text_only"
    elif "compressed_interpretation_short" in existing_data and "compressed_interpretation_full" in existing_data:
        source_content = f"SHORT VERSION:\n{existing_data['compressed_interpretation_short']}\n\nFULL VERSION:\n{existing_data['compressed_interpretation_full']}"
        format_type = "short_and_full"
    elif "compressed_interpretation_200" in existing_data:
        # Has new format but needs quality improvement - use the 200-word version as source
        source_content = existing_data["compressed_interpretation_200"]
        # Also include other structured fields if available
        if existing_data.get("expressive_character"):
            source_content = f"EXPRESSIVE CHARACTER:\n{existing_data['expressive_character']}\n\nSTRUCTURAL NARRATIVE:\n{existing_data.get('structural_narrative', '')}\n\nSTYLISTIC IDENTITY:\n{existing_data.get('stylistic_identity', '')}\n\nINTERPRETIVE PRIORITY:\n{existing_data.get('interpretive_priority', '')}\n\nEXISTING INTERPRETATION:\n{source_content}"
        format_type = "quality_improvement"
    else:
        return None

    piece_id = existing_data.get("piece_id", "Unknown")
    composer = existing_data.get("composer", "")
    composition = existing_data.get("composition", "")
    movement = existing_data.get("movement", "")

    # If missing, extract from path
    if not composer or not composition:
        composer_path, composition_path, movement_path = extract_composer_composition_from_path(file_path)
        composer = composer or composer_path
        composition = composition or composition_path
        movement = movement or movement_path

    prompt = f"""You are reformatting a piece interpretation for: {composer} - {composition}{' - ' + movement if movement else ''}

EXISTING CONTENT:
{source_content}

Generate a COMPLETE interpretation structure with ALL fields:

1. **mood**: Array of 3-5 DISTINCTIVE keywords (NOT generic)
   - Use specific descriptors: "restless", "yearning", "impulsive", "stormy", "crystalline", "brooding"
   - AVOID: "romantic", "beautiful", "expressive", "dramatic" (too generic)
   - DIFFERENTIATE this piece from others by same composer

2. **expressive_character**: 2-3 sentences describing emotional/expressive qualities

3. **structural_narrative**: 2-3 sentences describing form/structure/tension arc

4. **stylistic_identity**: 1-2 sentences on historical/stylistic context

5. **interpretive_priority**: 2-3 sentences on performance priorities

6. **compressed_interpretation_50** (~50 words):
   - HIGH information density with ACTIONABLE style markers
   - Specific descriptors:
     * Rhythm: elastic tempo / tight rhythmic spine / broad pulse / rubato freedom / metronomic precision
     * Texture: transparent inner voices / dense harmonic saturation / contrapuntal clarity / homophonic blocks
     * Dynamics: terraced dynamics / sudden dynamic bloom / gradual crescendo waves / subito contrasts
     * Structure: delayed cadential release / cyclic return / through-composed / sectional clarity
     * Articulation: detached clarity / legato binding / staccato sparkle / portamento connection
   - DIFFERENTIATE from other pieces by same composer

7. **compressed_interpretation_100** (~100 words):
   - Medium detail, expand on 50-word markers
   - Add context about form, key relationships, historical position

8. **compressed_interpretation_200** (~200 words):
   - Full narrative with performance considerations
   - Historical/stylistic context
   - Maintain distinctive style markers from shorter versions

OUTPUT FORMAT (JSON only, no markdown):
{{
  "mood": ["keyword1", "keyword2", "keyword3"],
  "expressive_character": "...",
  "structural_narrative": "...",
  "stylistic_identity": "...",
  "interpretive_priority": "...",
  "compressed_interpretation_50": "...",
  "compressed_interpretation_100": "...",
  "compressed_interpretation_200": "..."
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text.strip()

        # Try to extract JSON from response
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text

        result = json.loads(response_text)
        return result

    except Exception as e:
        print(f"Error generating interpretations for {piece_id}: {e}")
        return None


def process_file(file_path):
    """
    Process a single piece_interpretation.json file.

    Returns: (status, old_format_type)
    - status: "success", "skip", "error"
    - old_format_type: "text_only", "short_and_full", "already_new", "unknown"
    """

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check what format we have
        has_text = "text" in data
        has_short = "compressed_interpretation_short" in data
        has_full = "compressed_interpretation_full" in data
        has_50 = "compressed_interpretation_50" in data
        has_100 = "compressed_interpretation_100" in data
        has_200 = "compressed_interpretation_200" in data

        # Check if already has new format with good quality
        if has_50 and has_100 and has_200:
            # Check quality indicators
            mood = data.get("mood", [])
            compressed_50 = data.get("compressed_interpretation_50", "")

            # Check for generic/poor quality indicators
            generic_moods = ["expressive", "nuanced", "refined", "fluid", "graceful", "dramatic", "beautiful", "romantic"]
            has_generic_mood = any(m in generic_moods for m in mood)

            # Check if compressed_50 is too short or looks like truncated text
            is_too_short = len(compressed_50.split()) < 40

            # Check for specific style markers (good quality indicators)
            style_markers = ["rubato", "staccato", "legato", "terraced", "contrapuntal", "homophonic",
                           "metronomic", "elastic", "transparent", "dense", "subito", "gradual",
                           "detached", "portamento", "cyclic", "through-composed", "sectional"]
            has_style_markers = any(marker in compressed_50.lower() for marker in style_markers)

            # If has good quality, skip
            if not has_generic_mood and not is_too_short and has_style_markers:
                return ("skip", "already_new")

            # Otherwise, treat as needing regeneration
            print(f"  → Needs quality improvement (generic_mood={has_generic_mood}, too_short={is_too_short}, has_markers={has_style_markers})")
            # Continue to regeneration below

        # Determine format type
        if has_text and not has_short and not has_full:
            format_type = "text_only"
        elif has_short and has_full:
            format_type = "short_and_full"
        elif has_50 and has_100 and has_200:
            # Has new format but needs quality improvement
            format_type = "quality_improvement"
        else:
            return ("skip", "unknown")

        # Generate new interpretations
        print(f"Processing: {data.get('piece_id', 'Unknown')}", flush=True)
        new_interpretations = generate_complete_interpretation(data, file_path)

        if new_interpretations is None:
            return ("error", format_type)

        # Extract composer/composition/movement from path if not present
        composer, composition, movement = extract_composer_composition_from_path(file_path)

        # Update the data structure
        # Remove old fields
        if "text" in data:
            del data["text"]
        if "compressed_interpretation_short" in data:
            del data["compressed_interpretation_short"]
        if "compressed_interpretation_full" in data:
            del data["compressed_interpretation_full"]

        # Ensure all required fields are present
        if "composer" not in data or not data["composer"]:
            data["composer"] = composer
        if "composition" not in data or not data["composition"]:
            data["composition"] = composition
        if "movement" not in data:
            data["movement"] = movement

        # Set standard fields if not present
        if "alpha_type" not in data:
            data["alpha_type"] = "piece_level_interpretation"
        if "scope" not in data:
            data["scope"] = "piece"
        if "performance_specific" not in data:
            data["performance_specific"] = False
        if "teaching_specific" not in data:
            data["teaching_specific"] = False
        if "language" not in data:
            data["language"] = "en"

        # Add new fields from generated content
        data["mood"] = new_interpretations.get("mood", ["expressive"])
        data["expressive_character"] = new_interpretations.get("expressive_character", "")
        data["structural_narrative"] = new_interpretations.get("structural_narrative", "")
        data["stylistic_identity"] = new_interpretations.get("stylistic_identity", "")
        data["interpretive_priority"] = new_interpretations.get("interpretive_priority", "")
        data["compressed_interpretation_50"] = new_interpretations["compressed_interpretation_50"]
        data["compressed_interpretation_100"] = new_interpretations["compressed_interpretation_100"]
        data["compressed_interpretation_200"] = new_interpretations["compressed_interpretation_200"]

        # Reorder fields for consistency
        ordered_data = {
            "piece_id": data.get("piece_id", ""),
            "composer": data.get("composer", ""),
            "composition": data.get("composition", ""),
            "movement": data.get("movement", ""),
            "alpha_type": data.get("alpha_type", "piece_level_interpretation"),
            "scope": data.get("scope", "piece"),
            "performance_specific": data.get("performance_specific", False),
            "teaching_specific": data.get("teaching_specific", False),
            "language": data.get("language", "en"),
            "mood": data.get("mood", []),
            "expressive_character": data.get("expressive_character", ""),
            "structural_narrative": data.get("structural_narrative", ""),
            "stylistic_identity": data.get("stylistic_identity", ""),
            "interpretive_priority": data.get("interpretive_priority", ""),
            "compressed_interpretation_50": data.get("compressed_interpretation_50", ""),
            "compressed_interpretation_100": data.get("compressed_interpretation_100", ""),
            "compressed_interpretation_200": data.get("compressed_interpretation_200", ""),
            "evidence_sources": data.get("evidence_sources", [])
        }

        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(ordered_data, f, indent=2, ensure_ascii=False)

        return ("success", format_type)

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return ("error", "unknown")


def main():
    # Find all piece_interpretation.json files in D-F directories
    base_path = Path("/home/sy/EPR/PianoCoReS/miditsv")

    print("Starting file search...", flush=True)
    files = []
    for pattern in ['D*', 'E*', 'F*']:
        files.extend(base_path.glob(f"{pattern}/**/piece_interpretation.json"))

    files = sorted([str(f) for f in files])
    print(f"Found {len(files)} files to process in D-F directories", flush=True)

    # Statistics
    stats = {
        "total": len(files),
        "success": 0,
        "skip_already_new": 0,
        "skip_unknown": 0,
        "error": 0,
        "text_only_converted": 0,
        "short_and_full_converted": 0,
        "quality_improved": 0
    }

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {file_path}", flush=True)
        status, format_type = process_file(file_path)

        if status == "success":
            stats["success"] += 1
            if format_type == "text_only":
                stats["text_only_converted"] += 1
            elif format_type == "short_and_full":
                stats["short_and_full_converted"] += 1
            elif format_type == "quality_improvement":
                stats["quality_improved"] += 1
        elif status == "skip":
            if format_type == "already_new":
                stats["skip_already_new"] += 1
            else:
                stats["skip_unknown"] += 1
        else:
            stats["error"] += 1

    # Print summary
    print("\n" + "="*60)
    print("PROCESSING COMPLETE")
    print("="*60)
    print(f"Total files: {stats['total']}")
    print(f"Successfully processed: {stats['success']}")
    print(f"  - Old format (text only) → new: {stats['text_only_converted']}")
    print(f"  - Old format (short+full) → new: {stats['short_and_full_converted']}")
    print(f"  - Quality improved (regenerated): {stats['quality_improved']}")
    print(f"Skipped (already high quality): {stats['skip_already_new']}")
    print(f"Skipped (unknown format): {stats['skip_unknown']}")
    print(f"Errors: {stats['error']}")


if __name__ == "__main__":
    main()
