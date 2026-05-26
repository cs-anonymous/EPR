#!/usr/bin/env python3
"""Generate annotated score MIDI TSV files from ABCX and score MIDI.

This script:
1. Parses score.abcx to extract annotations (dynamics, articulation, expression, etc.)
2. Uses existing alignment logic to map ABCX measures to score MIDI measures
3. Generates/loads score MIDI TSV
4. Merges annotations into the TSV at appropriate positions
5. Outputs annotated_score.mid.tsv for each piece

The alignment reuses the logic from align_score_performance.py to ensure consistency.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import existing alignment module
try:
    from scripts import align_score_performance as asp
    from scripts.lm_midi_tsv import midi_pitch_to_logic_note
except ModuleNotFoundError:
    import align_score_performance as asp
    from lm_midi_tsv import midi_pitch_to_logic_note


DEFAULT_METADATA = ROOT / "PianoCoReS" / "score_metadata.csv"
DEFAULT_PIANOCORE_ROOT = ROOT / "PianoCoRe"

# Annotation token mappings (from lm_midi_tokenizer.md)
ARTICULATION_MAP = {
    "!>!": "accent",
    "!wedge!": "staccato",
    "!tenuto!": "tenuto",
    "!sfz!": "sfz",
}

DYNAMIC_MAP = {
    "!pppp!": "pppp",
    "!ppp!": "ppp",
    "!pp!": "pp",
    "!p!": "p",
    "!mp!": "mp",
    "!mf!": "mf",
    "!f!": "f",
    "!ff!": "ff",
    "!fff!": "fff",
    "!ffff!": "ffff",
}

ORNAMENT_MAP = {
    "!arpeggio!": "arpeggio",
    "!turn!": "turn",
}

RANGE_START_MAP = {
    "!<(!": "cre",
    "!>(!": "dim",
    "!trill(!": "trill",
}

RANGE_END_MAP = {
    "!<)!": "cre",
    "!>)!": "dim",
    "!trill)!": "trill",
}

PEDAL_MAP = {
    "^Ped.": "down",
    "^*": "up",
}

# Expression terms (≥10 occurrences) - normalized
EXPRESSION_MAP = {
    "a tempo": "a_tempo",
    "cresc": "cresc",
    "dim": "dim",
    "rit": "rit",
    "dolce": "dolce",
    "loco": "loco",
    "tempo i": "tempo_i",
    "poco rit": "poco_rit",
    "rall": "rall",
    "ten": "ten",
    "espress": "espress",
    "ritard": "ritard",
    "legato": "legato",
    "accel": "accel",
    "subito": "subito",
    "sempre": "sempre",
    "una corda": "una_corda",
    "sec": "sec",
    "marcato": "marcato",
    "molto rall": "molto_rall",
    "cédez": "cédez",
    "calando": "calando",
    "stretto": "stretto",
    "in tempo": "in_tempo",
    "leggiero": "leggiero",
    "sotto voce": "sotto_voce",
    "riten": "riten",
    "cantabile": "cantabile",
    "mouvt": "mouvt",
    "crescendo": "crescendo",
    "espressivo": "espressivo",
    "piu": "piu",
    "sostenuto": "sostenuto",
    "tranquillo": "tranquillo",
    "allargando": "allargando",
    "colla parte": "colla_parte",
    "dimin": "dimin",
    "agitato": "agitato",
    "poco ritard": "poco_ritard",
    "colla voce": "colla_voce",
    "pesante": "pesante",
    "rubato": "rubato",
}

# Meter types (≥10 occurrences)
VALID_METERS = {
    "4/4", "3/4", "2/4", "6/8", "2/2", "3/8", "9/8", "6/4", "3/2", "12/8",
    "5/4", "5/8", "4/8", "1/4", "12/16", "7/4", "7/8", "6/16", "4/2", "2/8",
    "1/8", "9/16", "9/4", "1/2", "3/16", "11/8", "8/8", "1/16", "12/32",
    "2/16", "4/16", "5/16", "8/32", "10/4", "17/16", "3/1", "10/8", "11/16",
    "2/1", "8/4", "9/2",
}

# Key signatures
KEY_MAP = {
    # Major keys
    "C": "key_C", "G": "key_G", "D": "key_D", "A": "key_A", "E": "key_E",
    "B": "key_B", "F#": "key_F#", "Db": "key_Db", "Ab": "key_Ab",
    "Eb": "key_Eb", "Bb": "key_Bb", "F": "key_F",
    # Minor keys
    "Am": "key_Am", "Em": "key_Em", "Bm": "key_Bm", "F#m": "key_F#m",
    "C#m": "key_C#m", "G#m": "key_G#m", "D#m": "key_D#m", "Bbm": "key_Bbm",
    "Fm": "key_Fm", "Cm": "key_Cm", "Gm": "key_Gm", "Dm": "key_Dm",
}


_worker_midi_tsv = None


def _worker_init() -> None:
    """Initialize worker process."""
    global _worker_midi_tsv
    _worker_midi_tsv = asp.load_midi_tsv_module()


@dataclass
class Annotation:
    """A musical annotation extracted from ABCX."""
    measure_num: int  # ABCX measure number (1-indexed)
    position: int  # Position within measure (0 = start, 1+ = after nth note)
    type: str  # annotation type: dynamic, articulation, ornament, expression, etc.
    value: str  # annotation value (token name)
    staff: str | None  # "upper" or "lower" (None = both/global)


@dataclass
class ABCXHeader:
    """ABCX header information."""
    titles: list[str]
    composer: str | None
    source: str | None
    tempo: int | None  # BPM
    meter: str | None  # e.g., "2/4"
    key: str | None  # e.g., "D"


class ABCXAnnotationParser:
    """Parse musical annotations from ABCX files."""

    def __init__(self, abcx_path: Path):
        self.abcx_path = abcx_path
        self.content = abcx_path.read_text(encoding='utf-8')
        self.lines = self.content.split('\n')

    def extract_header(self) -> ABCXHeader:
        """Extract header information (T:, C:, Z:, Q:, M:, K:)."""
        titles = []
        composer = None
        source = None
        tempo = None
        meter = None
        key = None

        for line in self.lines:
            if line.startswith("T:"):
                titles.append(line[2:].strip())
            elif line.startswith("C:"):
                composer = line[2:].strip()
            elif line.startswith("Z:"):
                source = line[2:].strip()
            elif line.startswith("Q:"):
                # Parse tempo: Q:1/4=80 -> 80 BPM
                match = re.search(r'=(\d+)', line)
                if match:
                    tempo = int(match.group(1))
            elif line.startswith("M:"):
                meter = line[2:].strip()
            elif line.startswith("K:"):
                key = line[2:].strip()
                break  # K: is last header line

        return ABCXHeader(
            titles=titles,
            composer=composer,
            source=source,
            tempo=tempo,
            meter=meter,
            key=key,
        )

    def extract_annotations(self) -> list[Annotation]:
        """Extract all annotations from ABCX content.

        Strategy: Parse measure-by-measure, extract annotations at measure level.
        For simplicity, we place all annotations at the start of their measure.
        """
        annotations = []

        # Parse ABCX measures using existing logic
        abcx_measures = asp._parse_abcx_measures(self.abcx_path)

        for measure_info in abcx_measures:
            measure_num = measure_info["num"]
            content = measure_info["content"]

            # Extract annotations from this measure
            measure_annotations = self._extract_from_measure(content, measure_num)
            annotations.extend(measure_annotations)

        return annotations

    def _extract_from_measure(self, content: str, measure_num: int) -> list[Annotation]:
        """Extract annotations from a single measure's content."""
        annotations = []

        # Split by voice separator (;) to handle upper/lower staff
        voices = content.split(';')

        # For now, treat first 2 voices as upper/lower
        # More complex: need to parse %%score directive
        for voice_idx, voice_content in enumerate(voices[:2]):
            staff = "upper" if voice_idx == 0 else "lower"

            # Extract dynamics
            for marker, token in DYNAMIC_MAP.items():
                if marker in voice_content:
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="dynamic",
                        value=token,
                        staff=staff,
                    ))

            # Extract articulations (per-note, but we place at measure start)
            for marker, token in ARTICULATION_MAP.items():
                if marker in voice_content:
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="articulation",
                        value=token,
                        staff=staff,
                    ))

            # Extract ornaments
            for marker, token in ORNAMENT_MAP.items():
                if marker in voice_content:
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="ornament",
                        value=token,
                        staff=staff,
                    ))

            # Extract range starts
            for marker, token in RANGE_START_MAP.items():
                if marker in voice_content:
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="range_start",
                        value=token,
                        staff=staff,
                    ))

            # Extract range ends
            for marker, token in RANGE_END_MAP.items():
                if marker in voice_content:
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="range_end",
                        value=token,
                        staff=staff,
                    ))

            # Extract expression text (!"..."!)
            expr_pattern = r'!"([^"]+)"!'
            for match in re.finditer(expr_pattern, voice_content):
                expr_text = match.group(1).strip()
                # Normalize expression text
                expr_normalized = expr_text.lower().replace('^', '').replace('_', '').replace('.', '').strip()

                # Check if it's a known expression term
                if expr_normalized in EXPRESSION_MAP:
                    token = EXPRESSION_MAP[expr_normalized]
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="expression",
                        value=token,
                        staff=staff,
                    ))
                # Check for pedal marks
                elif expr_text in PEDAL_MAP:
                    annotations.append(Annotation(
                        measure_num=measure_num,
                        position=0,
                        type="pedal",
                        value=PEDAL_MAP[expr_text],
                        staff=None,  # pedal is global
                    ))

            # Extract fermata
            if "!fermata!" in voice_content:
                annotations.append(Annotation(
                    measure_num=measure_num,
                    position=0,
                    type="fermata",
                    value="fermata",
                    staff=staff,
                ))

        return annotations


def generate_score_midi_tsv_if_needed(
    score_midi_path: Path,
    score_abcx_path: Path,
    output_dir: Path,
    midi_tsv_module,
) -> Path | None:
    """Generate score MIDI TSV if it doesn't exist.

    Returns the path to the TSV file, or None if generation failed.
    """
    # Determine output path
    tsv_filename = score_midi_path.stem + ".tsv"
    tsv_path = output_dir / tsv_filename

    if tsv_path.exists():
        return tsv_path

    # Generate using existing logic from build_score_midi_tsv.py
    try:
        # Extract score structure
        score_measures = asp.extract_score_measures(score_midi_path, midi_tsv_module)
        if not score_measures:
            return None

        # Build score structure with phrases
        structure, ok = _build_score_structure(score_midi_path, score_abcx_path, output_dir, midi_tsv_module)
        if not ok or structure is None:
            return None

        # Generate TSV
        success = asp.generate_score_tsv_with_phrases(score_midi_path, structure, tsv_path, midi_tsv_module)
        if success:
            return tsv_path

    except Exception as e:
        print(f"Error generating TSV for {score_midi_path}: {e}")

    return None


def _build_score_structure(score_midi_path, score_abcx_path, output_dir, midi_tsv_module):
    """Build score structure (reuse from align_score_performance.py)."""
    try:
        score_measures = asp.extract_score_measures(score_midi_path, midi_tsv_module)
        if not score_measures:
            return None, False

        phrases, abcx_measures = asp.parse_abcx_structure(score_abcx_path, score_measures)
        if not phrases:
            return None, False

        # Build measure_to_phrase mapping
        measure_to_phrase = {}
        for phrase in phrases:
            for m_num in phrase.measures:
                measure_to_phrase[m_num] = phrase.phrase_id

        # Build midi_to_abcx mapping (1:1 for now, assuming no repeats in score MIDI)
        midi_to_abcx = {i: i for i in range(1, len(score_measures) + 1)}

        # Build midi_measure_content from abcx_measures
        # abcx_measures is a dict[int, str] mapping measure_num -> content
        midi_measure_content = abcx_measures.copy()

        structure = asp.ScoreStructure(
            measures=score_measures,
            phrases=phrases,
            measure_to_phrase=measure_to_phrase,
            abcx_measures=abcx_measures,
            midi_to_abcx=midi_to_abcx,
            midi_measure_content=midi_measure_content,
        )

        return structure, True

    except Exception as e:
        print(f"Error building structure: {e}")
        import traceback
        traceback.print_exc()
        return None, False


def generate_midi_from_abcx(abcx_path: Path, output_midi_path: Path) -> bool:
    """Convert ABCX to MIDI using abc2midi.

    Returns True if successful, False otherwise.
    """
    try:
        output_midi_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ['abc2midi', str(abcx_path), '-o', str(output_midi_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        return output_midi_path.exists() and output_midi_path.stat().st_size > 0

    except subprocess.TimeoutExpired:
        print(f"Timeout converting {abcx_path}")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error converting {abcx_path}: {e.stderr}")
        return False
    except Exception as e:
        print(f"Unexpected error converting {abcx_path}: {e}")
        return False


def generate_annotation_only_tsv(
    header: ABCXHeader,
    annotations: list[Annotation],
    output_path: Path,
) -> bool:
    """Generate TSV with only annotations (no note events) for scores without MIDI.

    This is useful for unpaired scores where we only have ABCX but no score MIDI.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = []

        # Header
        lines.append('# midi-tsv v0.4\n')
        lines.append('# source=annotation_only\n')
        lines.append('# columns=event\tvalue\tduration\toffset\n')
        lines.append('# note: This file contains only annotations extracted from ABCX\n')
        lines.append('# note: No score MIDI available, so no note events included\n')

        # Score header info
        if header.titles:
            for title in header.titles:
                lines.append(f'T:{title}\n')
        if header.composer:
            lines.append(f'C:{header.composer}\n')
        lines.append('\n')

        # Global annotations
        if header.key and header.key in KEY_MAP:
            lines.append(f'KS\t{KEY_MAP[header.key]}\tNIL\tNIL\n')

        if header.tempo:
            quantized = round(header.tempo / 3)
            if quantized > 127:
                quantized = 127
            lines.append(f'TP\tV{quantized:03d}\tNIL\tNIL\n')

        if header.meter and header.meter in VALID_METERS:
            meter_token = f'meter_{header.meter}'
            lines.append(f'MT\t{meter_token}\tNIL\tNIL\n')

        # Group annotations by measure
        annotations_by_measure = defaultdict(list)
        for ann in annotations:
            annotations_by_measure[ann.measure_num].append(ann)

        # Write annotations measure by measure
        for measure_num in sorted(annotations_by_measure.keys()):
            lines.append(f'# Measure {measure_num}\n')
            for ann in annotations_by_measure[measure_num]:
                ann_line = _format_annotation(ann)
                if ann_line:
                    lines.append(ann_line)

        # Write output
        with output_path.open('w', encoding='utf-8') as f:
            f.writelines(lines)

        return True

    except Exception as e:
        print(f"Error generating annotation-only TSV: {e}")
        return False


def merge_annotations_into_tsv(
    tsv_path: Path,
    annotations: list[Annotation],
    header: ABCXHeader,
    output_path: Path,
    midi_to_abcx: dict[int, int],
) -> bool:
    """Merge annotations into existing score MIDI TSV.

    Strategy:
    1. Read existing TSV
    2. Group annotations by MIDI measure number (using midi_to_abcx mapping)
    3. Insert annotation events at the start of each measure
    4. Add global annotations (KS, TP, MT) at the very beginning
    5. Write annotated TSV
    """
    if not tsv_path.exists():
        return False

    try:
        # Read existing TSV
        with tsv_path.open('r', encoding='utf-8') as f:
            lines = f.readlines()

        # Separate header and data
        header_lines = []
        data_lines = []
        for line in lines:
            if line.startswith('#'):
                header_lines.append(line)
            else:
                data_lines.append(line)

        # Update header to v0.4
        updated_header = []
        for line in header_lines:
            if line.startswith('# midi-tsv v'):
                updated_header.append('# midi-tsv v0.4\n')
            else:
                updated_header.append(line)

        # Add score header info
        if header.titles:
            for title in header.titles:
                updated_header.append(f'T:{title}\n')
        if header.composer:
            updated_header.append(f'C:{header.composer}\n')
        if header.source:
            updated_header.append(f'Z:{header.source}\n')
        updated_header.append('\n')

        # Group annotations by MIDI measure number
        annotations_by_measure = defaultdict(list)
        for ann in annotations:
            # Map ABCX measure to MIDI measure
            midi_measure = None
            for midi_m, abcx_m in midi_to_abcx.items():
                if abcx_m == ann.measure_num:
                    midi_measure = midi_m
                    break

            if midi_measure is not None:
                annotations_by_measure[midi_measure].append(ann)

        # Parse data lines to find measure boundaries
        measure_starts = {}  # midi_measure_num -> line_index
        current_measure = None

        for i, line in enumerate(data_lines):
            # Check if this is a measure marker line
            if line.startswith('<M>') or line.startswith('M\t'):
                # Extract measure number from line
                # Format: <M><V000>... or M\t0\t...
                match = re.match(r'<M><V(\d+)>', line)
                if match:
                    measure_num = int(match.group(1)) + 1  # V000 = measure 1
                    measure_starts[measure_num] = i
                    current_measure = measure_num
                else:
                    # TSV format: M\t{local_index}\t...
                    parts = line.split('\t')
                    if len(parts) >= 2 and parts[0] == 'M':
                        # This is a measure marker, but we need global measure number
                        # For now, increment
                        if current_measure is None:
                            current_measure = 1
                        else:
                            current_measure += 1
                        measure_starts[current_measure] = i

        # Build output with annotations inserted
        output_lines = updated_header.copy()

        # Add global annotations at the beginning
        if header.key and header.key in KEY_MAP:
            output_lines.append(f'KS\t{KEY_MAP[header.key]}\tNIL\tNIL\n')

        if header.tempo:
            # Quantize tempo: divide by 3 and round
            quantized = round(header.tempo / 3)
            if quantized > 127:
                quantized = 127
            output_lines.append(f'TP\tV{quantized:03d}\tNIL\tNIL\n')

        if header.meter and header.meter in VALID_METERS:
            meter_token = f'meter_{header.meter}'
            output_lines.append(f'MT\t{meter_token}\tNIL\tNIL\n')

        # Insert data lines with annotations
        for i, line in enumerate(data_lines):
            # Check if we should insert annotations before this line
            for measure_num, start_idx in measure_starts.items():
                if i == start_idx and measure_num in annotations_by_measure:
                    # Insert annotations for this measure
                    for ann in annotations_by_measure[measure_num]:
                        ann_line = _format_annotation(ann)
                        if ann_line:
                            output_lines.append(ann_line)

            # Add the original line
            output_lines.append(line)

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open('w', encoding='utf-8') as f:
            f.writelines(output_lines)

        return True

    except Exception as e:
        print(f"Error merging annotations: {e}")
        return False


def _format_annotation(ann: Annotation) -> str | None:
    """Format an annotation as a TSV line."""
    if ann.type == "dynamic":
        event_type = "DL" if ann.staff == "lower" else "D"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "articulation":
        event_type = "AL" if ann.staff == "lower" else "A"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "ornament":
        event_type = "ORL" if ann.staff == "lower" else "OR"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "range_start":
        event_type = "RSL" if ann.staff == "lower" else "RS"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "range_end":
        event_type = "REL" if ann.staff == "lower" else "RE"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "expression":
        event_type = "EXL" if ann.staff == "lower" else "EX"
        return f'{event_type}\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "pedal":
        return f'PM\t{ann.value}\tNIL\tNIL\n'

    elif ann.type == "fermata":
        return f'FM\tNIL\tNIL\tNIL\n'

    return None


def process_score(task: dict[str, str]) -> dict[str, Any]:
    """Process a single score file."""
    score_abcx_path = Path(task["score_abcx_path"])
    score_midi_path = Path(task["score_midi_path"]) if task.get("score_midi_path") else None
    output_path = Path(task["output_path"])

    if not score_abcx_path.exists():
        return {"ok": False, "error": "ABCX not found", "path": str(score_abcx_path)}

    # Parse ABCX
    try:
        parser = ABCXAnnotationParser(score_abcx_path)
        header = parser.extract_header()
        annotations = parser.extract_annotations()
    except Exception as e:
        return {"ok": False, "error": f"ABCX parse error: {e}", "path": str(score_abcx_path)}

    # If no score MIDI, generate it from ABCX
    if not score_midi_path or not score_midi_path.exists():
        # Generate MIDI from ABCX (use unique filename per ABCX)
        generated_midi_filename = score_abcx_path.stem + ".generated.mid"
        generated_midi_path = score_abcx_path.parent / generated_midi_filename
        success = generate_midi_from_abcx(score_abcx_path, generated_midi_path)

        if success:
            score_midi_path = generated_midi_path
        else:
            # If MIDI generation fails, create annotation-only TSV
            success = generate_annotation_only_tsv(header, annotations, output_path)
            if success:
                return {"ok": True, "output": str(output_path), "path": str(score_abcx_path), "type": "annotation_only"}
            else:
                return {"ok": False, "error": "Failed to generate MIDI and annotation-only TSV", "path": str(score_abcx_path)}

    # Generate or load score MIDI TSV
    tsv_path = generate_score_midi_tsv_if_needed(
        score_midi_path,
        score_abcx_path,
        score_abcx_path.parent,
        _worker_midi_tsv,
    )

    if not tsv_path:
        return {"ok": False, "error": "Failed to generate/load TSV", "path": str(score_abcx_path)}

    # Build midi_to_abcx mapping
    try:
        structure, ok = _build_score_structure(
            score_midi_path,
            score_abcx_path,
            score_abcx_path.parent,
            _worker_midi_tsv,
        )
        if not ok or structure is None:
            midi_to_abcx = {i: i for i in range(1, 1000)}  # fallback: 1:1 mapping
        else:
            midi_to_abcx = structure.midi_to_abcx
    except Exception:
        midi_to_abcx = {i: i for i in range(1, 1000)}

    # Merge annotations
    success = merge_annotations_into_tsv(
        tsv_path,
        annotations,
        header,
        output_path,
        midi_to_abcx,
    )

    if success:
        return {"ok": True, "output": str(output_path), "path": str(score_abcx_path), "type": "full"}
    else:
        return {"ok": False, "error": "Failed to merge annotations", "path": str(score_abcx_path)}


def build_tasks(metadata_csv: Path, pianocore_root: Path) -> list[dict[str, str]]:
    """Build task list from metadata."""
    tasks = []

    with metadata_csv.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            score_abcx_path = row.get("score_abcx_path", "").strip()
            if not score_abcx_path:
                continue

            # Resolve full paths
            abcx_full = Path(score_abcx_path)

            # Skip if ABCX doesn't exist
            if not abcx_full.exists():
                continue

            # Determine score MIDI path (prefer refined)
            score_midi_rel = row.get("refined_score_midi_path", "").strip()
            is_refined = True
            if not score_midi_rel:
                score_midi_rel = row.get("score_midi_path", "").strip()
                is_refined = False

            # Resolve MIDI path if available
            midi_full = None
            if score_midi_rel:
                # Score MIDI is in PianoCoRe/refined/ or PianoCoRe/raw/
                if is_refined:
                    midi_full = pianocore_root / "refined" / score_midi_rel
                else:
                    midi_full = pianocore_root / "raw" / score_midi_rel

            # Output path: same directory as ABCX, with ABCX filename stem
            output_filename = abcx_full.stem + ".annotated_score.mid.tsv"
            output_path = abcx_full.parent / output_filename

            tasks.append({
                "score_abcx_path": str(abcx_full),
                "score_midi_path": str(midi_full) if midi_full else None,
                "output_path": str(output_path),
            })

    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--pianocore-root", type=Path, default=DEFAULT_PIANOCORE_ROOT)
    parser.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() // 2))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, help="Limit number of files to process (for testing)")
    args = parser.parse_args()

    print("Building task list...")
    tasks = build_tasks(args.metadata, args.pianocore_root)

    if args.limit:
        tasks = tasks[:args.limit]

    print(f"Found {len(tasks)} scores to process")

    if not args.overwrite:
        # Filter out existing files
        tasks = [t for t in tasks if not Path(t["output_path"]).exists()]
        print(f"After filtering existing: {len(tasks)} tasks remaining")

    if not tasks:
        print("No tasks to process")
        return

    print(f"Processing with {args.jobs} workers...")

    results = []
    with mp.Pool(processes=args.jobs, initializer=_worker_init) as pool:
        for result in pool.imap_unordered(process_score, tasks):
            results.append(result)
            if result["ok"]:
                print(f"✓ {result['path']}")
            else:
                print(f"✗ {result['path']}: {result['error']}")

    # Summary
    success_count = sum(1 for r in results if r["ok"])
    print(f"\nCompleted: {success_count}/{len(results)} successful")


if __name__ == "__main__":
    main()
