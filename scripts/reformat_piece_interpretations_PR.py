#!/usr/bin/env python3
"""
Reformat piece_interpretation.json files to use 3-tier compressed format.
Process P-R directories.
"""

import json
import os
import sys
from pathlib import Path
from anthropic import Anthropic

client = Anthropic()

def generate_compressed_interpretations(existing_data):
    """
    Generate 3-tier compressed interpretations using Claude API.

    Returns dict with keys: compressed_interpretation_50, compressed_interpretation_100, compressed_interpretation_200
    """

    # Determine what content we have to work with
    if "text" in existing_data:
        # Old format - only has text field
        source_content = existing_data["text"]
        format_type = "old_text_only"
    elif "compressed_interpretation_short" in existing_data and "compressed_interpretation_full" in existing_data:
        # Has short and full versions
        source_content = f"SHORT VERSION:\n{existing_data['compressed_interpretation_short']}\n\nFULL VERSION:\n{existing_data['compressed_interpretation_full']}"
        format_type = "short_and_full"
    else:
        # Unknown format
        return None

    piece_id = existing_data.get("piece_id", "Unknown")
    composer = existing_data.get("composer", "Unknown")
    composition = existing_data.get("composition", "Unknown")

    prompt = f"""You are reformatting a piece interpretation for: {composer} - {composition}

EXISTING CONTENT:
{source_content}

Generate THREE compressed interpretations with different lengths:

1. **compressed_interpretation_50** (~50 words):
   - HIGH information density
   - Focus on ACTIONABLE, DISTINCTIVE style markers
   - Avoid generic words like "romantic, expressive, beautiful"
   - Use specific descriptors:
     * Rhythm: elastic tempo / tight rhythmic spine / broad pulse / rubato freedom / metronomic precision
     * Texture: transparent inner voices / dense harmonic saturation / contrapuntal clarity / homophonic blocks
     * Dynamics: terraced dynamics / sudden dynamic bloom / gradual crescendo waves / subito contrasts
     * Structure: delayed cadential release / cyclic return / through-composed / sectional clarity
     * Articulation: detached clarity / legato binding / staccato sparkle / portamento connection
   - DIFFERENTIATE this piece from others by the same composer
   - Use CONTRASTIVE descriptions that help identify this specific work

2. **compressed_interpretation_100** (~100 words):
   - Medium detail level
   - Expand on the style markers from the 50-word version
   - Add context about form, key relationships, or historical position
   - Still maintain high information density

3. **compressed_interpretation_200** (~200 words):
   - Full narrative with interpretive guidance
   - Include performance considerations
   - Provide historical/stylistic context
   - Maintain the distinctive style markers established in shorter versions

OUTPUT FORMAT (JSON only, no markdown):
{{
  "compressed_interpretation_50": "...",
  "compressed_interpretation_100": "...",
  "compressed_interpretation_200": "..."
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text.strip()

        # Try to extract JSON from response
        if response_text.startswith("```"):
            # Remove markdown code blocks
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

        # If already has new format, skip
        if has_50 and has_100 and has_200:
            return ("skip", "already_new")

        # Determine format type
        if has_text and not has_short and not has_full:
            format_type = "text_only"
        elif has_short and has_full:
            format_type = "short_and_full"
        else:
            return ("skip", "unknown")

        # Generate new interpretations
        print(f"Processing: {data.get('piece_id', 'Unknown')}")
        new_interpretations = generate_compressed_interpretations(data)

        if new_interpretations is None:
            return ("error", format_type)

        # Update the data structure
        # Remove old fields
        if "text" in data:
            del data["text"]
        if "compressed_interpretation_short" in data:
            del data["compressed_interpretation_short"]
        if "compressed_interpretation_full" in data:
            del data["compressed_interpretation_full"]

        # Add new fields
        data["compressed_interpretation_50"] = new_interpretations["compressed_interpretation_50"]
        data["compressed_interpretation_100"] = new_interpretations["compressed_interpretation_100"]
        data["compressed_interpretation_200"] = new_interpretations["compressed_interpretation_200"]

        # Write back to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return ("success", format_type)

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return ("error", "unknown")


def main():
    # Find all piece_interpretation.json files in P-R directories
    base_path = Path("/home/sy/EPR/PianoCoReS/miditsv")

    files = []
    for pattern in ['P*', 'Q*', 'R*']:
        files.extend(base_path.glob(f"{pattern}/**/piece_interpretation.json"))

    files = sorted([str(f) for f in files])
    print(f"Found {len(files)} files to process in P-R directories")

    # Statistics
    stats = {
        "total": len(files),
        "success": 0,
        "skip_already_new": 0,
        "skip_unknown": 0,
        "error": 0,
        "text_only_converted": 0,
        "short_and_full_converted": 0
    }

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {file_path}")
        status, format_type = process_file(file_path)

        if status == "success":
            stats["success"] += 1
            if format_type == "text_only":
                stats["text_only_converted"] += 1
            elif format_type == "short_and_full":
                stats["short_and_full_converted"] += 1
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
    print(f"Skipped (already new format): {stats['skip_already_new']}")
    print(f"Skipped (unknown format): {stats['skip_unknown']}")
    print(f"Errors: {stats['error']}")


if __name__ == "__main__":
    main()
