#!/usr/bin/env python3
"""
Align score phrases with performance phrases.

Step 1: Detect phrases in score (ABCX) heuristically and restructure format
Step 2: Align performance TSV phrase boundaries to match score structure
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from tqdm import tqdm


@dataclass
class Measure:
    """A single measure from ABCX score."""
    number: int
    content: str  # ABC notation content
    is_rest_only: bool


@dataclass
class Phrase:
    """A phrase containing multiple measures."""
    number: int
    measures: list[Measure]


class AbcxParser:
    """Parse and restructure ABCX files with explicit phrase/measure markers."""

    def __init__(self, abcx_path: Path):
        self.abcx_path = abcx_path
        self.header_lines: list[str] = []
        self.body_lines: list[str] = []
        self.measures: list[Measure] = []

    def parse(self) -> None:
        """Parse ABCX file into header and body."""
        with open(self.abcx_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Split header and body
        body_start = None
        for i, line in enumerate(lines):
            line = line.rstrip()
            if not line:
                continue
            # Body starts after K: (key signature)
            if line.startswith("K:"):
                self.header_lines.append(line)
                body_start = i + 1
                break
            self.header_lines.append(line)

        if body_start is not None:
            self.body_lines = [line.rstrip() for line in lines[body_start:] if line.strip()]

    def extract_measures(self) -> list[Measure]:
        """Extract measures from body without expanding repeats."""
        # Join all body lines
        body_text = " ".join(self.body_lines)

        # Split by bar lines, removing repeat markers
        measure_texts = re.split(r'\s*(\|+|:\||\|:|::)\s*', body_text)

        measures = []
        measure_num = 1

        for text in measure_texts:
            text = text.strip()
            # Skip bar line markers
            if not text or text in ('|', '||', ':|', '|:', '::'):
                continue

            # Check if measure is rest-only
            is_rest = self._is_rest_only(text)
            measures.append(Measure(measure_num, text, is_rest))
            measure_num += 1

        # Remove leading/trailing rest-only measures
        while measures and measures[0].is_rest_only:
            measures.pop(0)
        while measures and measures[-1].is_rest_only:
            measures.pop()

        # Renumber after removing rests
        for i, m in enumerate(measures, 1):
            m.number = i

        self.measures = measures
        return measures

    def _is_rest_only(self, measure_text: str) -> bool:
        """Check if a measure contains only rests."""
        # Remove voice separators and whitespace
        voices = measure_text.split(';')
        for voice in voices:
            voice = voice.strip()
            # Remove annotations, dynamics, text
            voice = re.sub(r'![^!]*!', '', voice)
            voice = re.sub(r'"[^"]*"', '', voice)
            voice = re.sub(r'\^[^\s]*', '', voice)
            voice = voice.strip()

            # Check if anything remains besides z (rest) and numbers
            if voice and not re.match(r'^[z0-9\s]*$', voice):
                return False
        return True

    def detect_phrases(self, min_len: int = 3, max_len: int = 8) -> list[Phrase]:
        """Detect phrases heuristically based on score structure."""
        if not self.measures:
            return []

        # Simple heuristic: look for 4/6/8 measure groupings
        # In the future, could analyze harmony, dynamics, articulation
        phrases = []
        phrase_num = 1
        start = 0

        while start < len(self.measures):
            remaining = len(self.measures) - start

            if remaining <= min_len:
                phrases.append(Phrase(phrase_num, self.measures[start:]))
                break

            # Prefer 4-measure phrases, then 6, then 8
            for length in [4, 6, 8, min_len]:
                if start + length <= len(self.measures):
                    end = start + length
                    phrases.append(Phrase(phrase_num, self.measures[start:end]))
                    start = end
                    phrase_num += 1
                    break
            else:
                # Fallback: take remaining
                phrases.append(Phrase(phrase_num, self.measures[start:]))
                break

        return phrases

    def write_restructured(self, output_path: Path, phrases: list[Phrase]) -> None:
        """Write restructured ABCX with explicit H/M markers."""
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header
            for line in self.header_lines:
                f.write(line + '\n')

            # Write body with H/M markers
            for phrase in phrases:
                f.write(f"H{phrase.number}\n")
                for measure in phrase.measures:
                    # Clean up measure content: remove extra spaces
                    content = ' '.join(measure.content.split())
                    f.write(f"M{measure.number}\t{content}\n")

            f.write('\n')


class TsvAligner:
    """Align performance TSV phrase boundaries to match score structure."""

    def __init__(self, tsv_path: Path, score_phrases: list[Phrase]):
        self.tsv_path = tsv_path
        self.score_phrases = score_phrases
        self.tsv_lines: list[str] = []
        self.header_lines: list[str] = []
        self.body_lines: list[str] = []

    def parse_tsv(self) -> None:
        """Parse TSV file."""
        with open(self.tsv_path, encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()
                if line.startswith('#'):
                    self.header_lines.append(line)
                else:
                    self.body_lines.append(line)

    def align_and_write(self, output_path: Path) -> bool:
        """Align TSV phrase boundaries to score and write output."""
        self.parse_tsv()

        # Extract measure numbers from TSV
        tsv_measure_numbers = []
        tsv_measure_lines = []
        for line in self.body_lines:
            if line.startswith('M') and '\t' in line:
                parts = line.split('\t')
                measure_id = parts[0]
                if measure_id[0] == 'M' and measure_id[1:].isdigit():
                    tsv_measure_numbers.append(int(measure_id[1:]))
                    tsv_measure_lines.append(line)

        # Build score measure-to-phrase mapping
        score_measure_to_phrase = {}
        for phrase in self.score_phrases:
            for measure in phrase.measures:
                score_measure_to_phrase[measure.number] = phrase.number

        # Extract tick values from measure lines
        def get_measure_ticks(line: str) -> tuple[str, str]:
            parts = line.split('\t')
            if len(parts) >= 3:
                return parts[1], parts[2]
            return None, None

        # Build phrase markers: track when phrase changes in TSV
        phrase_markers = {}  # tsv_line_index -> (phrase_num, start_tick, end_tick)
        current_phrase = None
        phrase_start_idx = None

        for idx, measure_num in enumerate(tsv_measure_numbers):
            phrase_num = score_measure_to_phrase.get(measure_num)

            if phrase_num != current_phrase:
                # Phrase changed - finalize previous phrase if exists
                if current_phrase is not None and phrase_start_idx is not None:
                    start_tick, _ = get_measure_ticks(tsv_measure_lines[phrase_start_idx])
                    _, end_tick = get_measure_ticks(tsv_measure_lines[idx - 1])
                    if start_tick and end_tick:
                        phrase_markers[phrase_start_idx] = (current_phrase, start_tick, end_tick)

                # Start new phrase
                current_phrase = phrase_num
                phrase_start_idx = idx

        # Finalize last phrase
        if current_phrase is not None and phrase_start_idx is not None:
            start_tick, _ = get_measure_ticks(tsv_measure_lines[phrase_start_idx])
            _, end_tick = get_measure_ticks(tsv_measure_lines[-1])
            if start_tick and end_tick:
                phrase_markers[phrase_start_idx] = (current_phrase, start_tick, end_tick)

        # Rebuild TSV with corrected phrase boundaries
        output_lines = []
        measure_index = 0

        for line in self.body_lines:
            if line.startswith('M') and '\t' in line:
                # Insert phrase marker if this measure starts a new phrase
                if measure_index in phrase_markers:
                    phrase_num, start_tick, end_tick = phrase_markers[measure_index]
                    output_lines.append(f"H{phrase_num}\t{start_tick}\t{end_tick}")

                output_lines.append(line)
                measure_index += 1
            elif line.startswith('H'):
                # Skip original phrase markers
                continue
            else:
                output_lines.append(line)

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            for line in self.header_lines:
                f.write(line + '\n')
            for line in output_lines:
                f.write(line + '\n')

        return True


def process_piece(piece_dir: Path, output_dir: Path) -> None:
    """Process a single piece: restructure score and align performances."""
    score_path = piece_dir / "score.abcx"
    if not score_path.exists():
        return

    # Step 1: Parse and restructure score
    parser = AbcxParser(score_path)
    parser.parse()
    measures = parser.extract_measures()

    if not measures:
        print(f"No measures found in {score_path}")
        return

    phrases = parser.detect_phrases()

    # Write restructured score
    output_piece_dir = output_dir / piece_dir.relative_to(piece_dir.parent.parent)
    output_piece_dir.mkdir(parents=True, exist_ok=True)
    output_score_path = output_piece_dir / "score.abcx"
    parser.write_restructured(output_score_path, phrases)

    # Step 2: Align all TSV files
    for tsv_path in piece_dir.glob("*.mid.tsv"):
        output_tsv_path = output_piece_dir / tsv_path.name
        aligner = TsvAligner(tsv_path, phrases)
        aligner.align_and_write(output_tsv_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Align score and performance phrase boundaries")
    parser.add_argument("--input-dir", default="PianoCoRe_output", help="Input directory")
    parser.add_argument("--output-dir", default="PianoCoRe_processed", help="Output directory")
    parser.add_argument("--piece-filter", default=None, help="Process only pieces matching this substring")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    # Find all pieces (directories with score.abcx)
    pieces = []
    for score_path in input_dir.rglob("score.abcx"):
        piece_dir = score_path.parent
        if args.piece_filter and args.piece_filter not in str(piece_dir):
            continue
        pieces.append(piece_dir)

    print(f"Found {len(pieces)} pieces to process")

    for piece_dir in tqdm(pieces):
        try:
            process_piece(piece_dir, output_dir)
        except Exception as exc:
            print(f"Error processing {piece_dir}: {exc}")


if __name__ == "__main__":
    main()
