#!/usr/bin/env python3
"""
Complete score-performance alignment pipeline with repeat detection.

Step 1: Extract logical measures from Score MIDI (output JSON)
Step 2: Parse ABCX phrase structure and align with Score MIDI measures
Step 3: Align Performance MIDI with Score structure, auto-detect repeats, assign measures and phrases
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pretty_midi
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))

from aligned_abcx_format import AlignedAbcxError, build_aligned_abcx
from lm_midi_tsv import midi_pitch_to_logic_note, semantic_event_to_tsv_rows, tsv_row_to_line


@dataclass
class ScoreMeasure:
    """A logical measure from Score MIDI."""
    measure_num: int  # 1-indexed
    start_note_idx: int  # inclusive
    end_note_idx: int  # exclusive
    start_time: float
    end_time: float
    time_signature: str


@dataclass
class Phrase:
    """A phrase containing multiple measures."""
    phrase_id: str  # e.g., "H1", "H2"
    measures: list[int]  # measure numbers in this phrase
    has_linebreak: bool  # whether phrase ends with linebreak


@dataclass
class ScoreStructure:
    """Complete score structure with measures and phrases.

    Canonical unit: Score MIDI measures (expanded with repeats).
    """
    measures: list[ScoreMeasure]  # Score MIDI measures (e.g. 1-41)
    phrases: list[Phrase]  # phrases with MIDI measure numbers, one entry per pass
    measure_to_phrase: dict[int, str]  # midi_measure_num -> phrase_id
    abcx_measures: dict[int, str]  # original abcx_measure_num -> ABC content
    midi_to_abcx: dict[int, int]  # midi_measure_num -> abcx_measure_num
    midi_measure_content: dict[int, str]  # midi_measure_num -> ABC content (expanded from ABCX)


def _abc_measure_duration(text: str) -> float:
    """Approximate beat duration of an ABC measure fragment.

    Only counts actual notes/rests with duration numbers, not bare pitches.
    """
    cleaned = re.sub(r'![^!]*!|"[^"]*"|%\{[^\}]*\}|\\[a-z]+', '', text)
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    total = 0.0
    for match in re.finditer(r"(\d+)(/(\d+))?", cleaned):
        num = int(match.group(1))
        denom = int(match.group(3)) if match.group(3) else 1
        total += num / denom
    # Also count bare rests (z without number = 1 beat)
    for match in re.finditer(r'(?<![A-Ga-g0-9])z(?![A-Ga-g0-9/])', cleaned):
        total += 1.0
    return total


def _is_marker_only(content: str) -> bool:
    """Check if an ABCX measure contains ONLY structural markers (no musical content).

    Volta markers like '1', '2', ':', '::', 'O' etc. without any notes or rests.
    This happens when the score MIDI puts the volta bracket in its own measure
    with notes, while ABCX puts the bracket as a separate empty measure.
    """
    # Strip volta/repeat/ottava markers and structural symbols
    cleaned = re.sub(r'(?<![A-Ga-g])\d+(?![A-Ga-g\'/,])', '', content)  # bare numbers (volta)
    cleaned = re.sub(r':', '', cleaned)  # repeat markers
    cleaned = re.sub(r'\bO\b', '', cleaned)  # ottava
    cleaned = re.sub(r'[\[\]{}]', '', cleaned)  # brackets
    cleaned = re.sub(r'![^!]*!', '', cleaned)  # ornaments
    cleaned = re.sub(r'"[^"]*"', '', cleaned)  # annotations
    cleaned = re.sub(r'\s+', '', cleaned)  # whitespace
    # After stripping, only voice separators (;) should remain
    cleaned = cleaned.replace(';', '')
    return len(cleaned) == 0


def _parse_abcx_measures(abcx_path: Path) -> list[dict]:
    """Parse ABCX body into measures, splitting on `::` repeat markers.

    Returns list of {num, content, is_phrase_closer, is_phrase_starter} dicts.
    - is_phrase_closer: measure ends a phrase (first-ending material, or ends with `:`)
    - is_phrase_starter: measure starts a new phrase (second-ending material)
    """
    with open(abcx_path, encoding="utf-8") as f:
        lines = [line.rstrip() for line in f]

    body_start = None
    for i, line in enumerate(lines):
        if line.startswith("K:"):
            body_start = i + 1
            break
    if body_start is None:
        return []

    body_text = " ".join(
        line for line in lines[body_start:]
        if line.strip() and not line.strip().startswith(("%%", "V:", "w:"))
    )

    # Split by `|` first
    segments = [s.strip() for s in body_text.split("|") if s.strip()]

    # Within each segment, split on `::` and classify parts
    # Skip `w:` lyrics-only segments — they are not musical measures
    raw_measures = []
    for seg in segments:
        if seg.startswith("w:"):
            continue
        if "::" in seg:
            parts = seg.split("::")
            for i, p in enumerate(parts):
                p = p.strip()
                if not p:
                    continue
                if i == 0:
                    # First part before `::` = first ending material → phrase closer
                    raw_measures.append((p, True, False))
                else:
                    # Everything after first `::` = second ending / post-repeat material
                    # → phrase starter
                    raw_measures.append((p, False, True))
        else:
            clean = seg.strip()
            if clean:
                has_end_colon = bool(re.search(r':\s*$', clean))
                raw_measures.append((clean, has_end_colon, False))

    # Filter out marker-only measures (volta brackets with no notes)
    # These cause mismatches when the score MIDI encodes the volta bracket
    # as a measure WITH notes but ABCX has it as a separate empty measure.
    filtered_measures = []
    for content, is_closer, is_starter in raw_measures:
        if _is_marker_only(content):
            continue  # skip phantom measures
        filtered_measures.append((content, is_closer, is_starter))

    # Build measure list with numbering (renumbered after filtering)
    measures = []
    for idx, (content, is_closer, is_starter) in enumerate(filtered_measures, 1):
        measures.append({
            "num": idx,
            "content": content,
            "is_phrase_closer": is_closer,
            "is_phrase_starter": is_starter,
        })

    return measures


def load_midi_tsv_module():
    """Load midi_tsv.py module."""
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load midi_tsv.py from {midi_tsv_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_score_measures(score_midi_path: Path, midi_tsv) -> list[ScoreMeasure]:
    """
    Step 1: Extract logical measures from Score MIDI.

    Returns a list of ScoreMeasure objects with note index ranges.
    """
    # Load Score MIDI
    score_midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    # Parse MIDI to get tempo and time signature info
    tpq, tracks = midi_tsv.parse_midi(score_midi_path.read_bytes())
    tempos = []
    time_sigs = []
    end_tick = 0

    for events in tracks:
        tick = 0
        for evt in events:
            tick += evt["delta"]
            end_tick = max(end_tick, tick)
            if evt["type"] == "meta" and evt.get("meta_type") == 0x51:
                tempos.append({"tick": tick, "microseconds_per_beat": evt["microseconds_per_beat"]})
            elif evt["type"] == "meta" and evt.get("meta_type") == 0x58:
                time_sigs.append({
                    "tick": tick,
                    "numerator": evt["numerator"],
                    "denominator": evt["denominator"],
                })

    if not time_sigs:
        time_sigs = [{"tick": 0, "numerator": 4, "denominator": 4}]
    time_sigs = sorted(time_sigs, key=lambda sig: sig["tick"])
    if time_sigs[0]["tick"] != 0:
        time_sigs.insert(0, {"tick": 0, "numerator": 4, "denominator": 4})

    tempo_map = midi_tsv.build_original_tempo_map(tpq, tempos)

    # Calculate measure boundaries
    measure_boundaries = []
    for idx, sig in enumerate(time_sigs):
        start_tick = sig["tick"]
        stop_tick = time_sigs[idx + 1]["tick"] if idx + 1 < len(time_sigs) else end_tick
        measure_ticks = round(tpq * sig["numerator"] * 4 / sig["denominator"])
        if measure_ticks <= 0:
            continue

        tick = start_tick
        while tick < stop_tick - measure_ticks * 0.25:
            if not measure_boundaries or tick > measure_boundaries[-1][0]:
                measure_boundaries.append((tick, f"{sig['numerator']}/{sig['denominator']}"))
            tick += measure_ticks

    # Convert ticks to seconds
    def tick_to_seconds(tick: int) -> float:
        selected = tempo_map[0]
        for point in tempo_map:
            if point["tick"] <= tick:
                selected = point
            else:
                break
        return selected["seconds"] + (
            (tick - selected["tick"]) * selected["microseconds_per_beat"]
        ) / selected["tpq"] / 1_000_000

    measure_times = [(tick_to_seconds(tick), sig) for tick, sig in measure_boundaries]

    # Assign notes to measures
    measures = []
    for measure_num, (measure_time, time_sig) in enumerate(measure_times, 1):
        start_time = measure_time
        end_time = measure_times[measure_num][0] if measure_num < len(measure_times) else score_notes[-1].end + 1.0

        # Find notes in this measure
        start_idx = None
        end_idx = None
        for i, note in enumerate(score_notes):
            if start_idx is None and note.start >= start_time - 0.01:
                start_idx = i
            if note.start < end_time - 0.01:
                end_idx = i + 1

        if start_idx is not None and end_idx is not None:
            measures.append(ScoreMeasure(
                measure_num=measure_num,
                start_note_idx=start_idx,
                end_note_idx=end_idx,
                start_time=start_time,
                end_time=end_time,
                time_signature=time_sig,
            ))

    return measures


def parse_abcx_structure(abcx_path: Path, score_measures: list[ScoreMeasure]) -> tuple[list[Phrase], dict[int, str]]:
    """
    Step 2: Parse ABCX phrase structure and align with Score MIDI measures.

    Properly handles:
    - `::` repeat markers that split ABCX measures
    - Pickup (incomplete) measures at the beginning
    - Repeat-marker measures closing phrases
    - 4-measure phrase chunks (pickup measures don't count toward the 4)
    """
    abcx_measures_info = _parse_abcx_measures(abcx_path)
    if not abcx_measures_info:
        return [], {}

    n = len(abcx_measures_info)
    if n == 0:
        return [], {}

    # Get time signature info
    with open(abcx_path, encoding="utf-8") as f:
        abcx_lines = [line.rstrip() for line in f]
    expected_beats = 4.0
    for line in abcx_lines:
        if line.startswith("M:"):
            m = re.match(r'M:(\d+)/(\d+)', line)
            if m:
                expected_beats = int(m.group(1)) / int(m.group(2)) * 4
            break

    # Identify pickup measures: first measure(s) with duration < expected_beats
    pickup_set = set()
    for i, m_info in enumerate(abcx_measures_info):
        dur = _abc_measure_duration(m_info["content"])
        if dur < expected_beats * 0.6:
            pickup_set.add(m_info["num"])
        else:
            break  # only check from start

    # Identify phrase-closer measures (first-endings, or measures ending with `:`)
    phrase_closer_set = {m["num"] for m in abcx_measures_info if m.get("is_phrase_closer")}
    # Identify phrase-starter measures (second-endings, material after repeat)
    phrase_starter_set = {m["num"] for m in abcx_measures_info if m.get("is_phrase_starter")}

    # Build phrase groups: aim for ~4 full measures per phrase (4-8 range).
    # - Pickup measures: skip during main loop, attach to first phrase at end
    # - Phrase-closer measures: trigger close once we have >= target measures
    # - Phrase-starter measures: always start a new phrase
    # - Force close at max_phrase measures

    phrases = []
    phrase_num = 1
    current_phrase_measures = []
    full_count = 0
    target = 4
    max_phrase = 8

    for idx, mnum in enumerate(abcx_measures_info):
        num = mnum["num"]
        if num in pickup_set:
            continue  # pickups handled separately

        is_closer = num in phrase_closer_set
        is_starter = num in phrase_starter_set

        current_phrase_measures.append(num)
        full_count += 1

        # Determine if we should close this phrase
        should_close = False

        # Phrase-starter: close current phrase, but not if it only contains starters
        # (consecutive starters from `::` splits should stay grouped)
        if is_starter and full_count > 1:
            has_non_starter = any(
                m not in phrase_starter_set for m in current_phrase_measures
            )
            if has_non_starter:
                should_close = True
        # Phrase-closer with enough measures
        elif is_closer and full_count >= 2:
            should_close = True
        # Force close at max_phrase
        elif full_count >= max_phrase:
            should_close = True
        # Close at target+ if no closer/starter ahead
        elif full_count >= target:
            # Look ahead: if next measure is a closer, include it
            # If next measure is a starter, close now (starter begins new phrase)
            next_idx = idx + 1
            if next_idx < len(abcx_measures_info):
                next_num = abcx_measures_info[next_idx]["num"]
                next_is_closer = next_num in phrase_closer_set
                next_is_starter = next_num in phrase_starter_set
                if next_is_starter:
                    should_close = True  # close before starter
                elif next_is_closer:
                    pass  # wait for closer
                else:
                    should_close = True  # no structural boundary ahead
            else:
                should_close = True

        if should_close:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))
            phrase_num += 1
            current_phrase_measures = []
            full_count = 0

    if current_phrase_measures:
        phrases.append(Phrase(
            phrase_id=f"H{phrase_num}",
            measures=current_phrase_measures.copy(),
            has_linebreak=False,
        ))

    # Handle pickups: attach each pickup to the first non-pickup phrase
    if pickup_set and phrases:
        pickup_nums = sorted(pickup_set)
        first_full_idx = None
        for i, p in enumerate(phrases):
            if any(m not in pickup_set for m in p.measures):
                first_full_idx = i
                break

        if first_full_idx is not None:
            new_measures = pickup_nums + phrases[first_full_idx].measures
            phrases[first_full_idx] = Phrase(
                phrase_id=phrases[first_full_idx].phrase_id,
                measures=new_measures,
                has_linebreak=phrases[first_full_idx].has_linebreak,
            )

    abcx_measures = {m["num"]: m["content"] for m in abcx_measures_info}
    return phrases, abcx_measures


def build_midi_to_abcx_mapping(
    score_measures: list[ScoreMeasure],
    abcx_measures: dict[int, str],
    score_midi_path: Path,
    key: str = "G",
) -> dict[int, int]:
    """Build mapping from score MIDI measure number → ABCX measure number.

    Strategy:
    1. Extract content signatures (note count + pitch classes) for both MIDI and ABCX.
    2. Detect the repeat split point by comparing MIDI measure content.
    3. Map first-pass MIDI measures sequentially to ABCX measures.
    4. Map second-pass MIDI measures to the same ABCX as corresponding first-pass.
    5. If no repeat is detected, use content-based matching as fallback.
    """
    if not score_measures or not abcx_measures:
        return {}

    import pretty_midi as _pm
    from collections import defaultdict

    # Load Score MIDI to get actual note data
    score_midi = _pm.PrettyMIDI(str(score_midi_path))
    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    midi_nums = [m.measure_num for m in score_measures]
    num_midi = len(midi_nums)
    abcx_nums = sorted(abcx_measures.keys())
    num_abcx = len(abcx_nums)

    # Pitch class helpers
    pc_map = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    KEY_ACC: dict[str, dict[str, int]] = {
        "G": {"F": 1}, "D": {"F": 1, "C": 1}, "A": {"F": 1, "C": 1, "G": 1},
        "E": {"F": 1, "C": 1, "G": 1, "D": 1},
        "B": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1},
        "F#": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1},
        "F": {"B": -1}, "Bb": {"B": -1, "E": -1}, "Eb": {"B": -1, "E": -1, "A": -1},
        "Ab": {"B": -1, "E": -1, "A": -1, "D": -1},
    }
    key_acc = KEY_ACC.get(key, {})

    # Build measure lookup by measure number (not index-based)
    measure_by_num = {m.measure_num: m for m in score_measures}

    def midi_sig(mnum: int) -> tuple[int, frozenset[int]]:
        m = measure_by_num[mnum]
        notes_in_m = [n for n in score_notes if m.start_time <= n.start < m.end_time]
        count = len(notes_in_m)
        pcs = frozenset(n.pitch % 12 for n in notes_in_m)
        return count, pcs

    def abcx_sig(mnum: int) -> tuple[int, frozenset[int]]:
        text = abcx_measures[mnum]
        letters = re.findall(r'[A-Ga-g]', text)
        count = len(letters)
        all_pitches = re.findall(r'[\^=_]?[A-Ga-g]', text)
        pcs = set()
        for p in all_pitches:
            base = p[-1].upper()
            accidental = p[:-1]
            pc = pc_map.get(base, 0)
            if '^' in accidental:
                pc += 1
            elif '_' in accidental:
                pc -= 1
            elif base in key_acc:
                pc += key_acc[base]
            pcs.add(pc % 12)
        return count, frozenset(pcs)

    midi_sigs = {mnum: midi_sig(mnum) for mnum in midi_nums}
    abcx_sigs = {mnum: abcx_sig(mnum) for mnum in abcx_nums}

    def jaccard(a: frozenset, b: frozenset) -> float:
        if not a and not b:
            return 1.0
        return len(a & b) / len(a | b) if a | b else 0.0

    def match_score(mnum: int, abnum: int) -> float:
        """Score a MIDI→ABCX match. Higher is better."""
        mc, mp = midi_sigs[mnum]
        ac, ap = abcx_sigs[abnum]
        count_diff = abs(mc - ac)
        sim = jaccard(mp, ap)
        if count_diff == 0:
            return 1.0 + sim * 0.5
        return sim * 0.5 - count_diff * 0.1

    def match_score(mnum: int, abnum: int) -> float:
        """Score a MIDI→ABCX match. Higher is better."""
        mc, mp = midi_sigs[mnum]
        ac, ap = abcx_sigs[abnum]
        count_diff = abs(mc - ac)
        if count_diff == 0:
            jac = jaccard(mp, ap)
            return 10.0 + jac
        return -count_diff * 2.0 + jaccard(mp, ap) * 0.5

    # Use full-sequence content-based matching to find the best starting offset.
    # Slide a window of ALL MIDI measures across the ABCX and pick the offset
    # that maximizes total match score.
    mapping: dict[int, int] = {}

    best_start_idx = 0
    best_total = -999.0
    for offset in range(num_abcx - num_midi + 1):
        total = 0.0
        for k in range(num_midi):
            mnum = midi_nums[k]
            abnum = abcx_nums[offset + k]
            total += match_score(mnum, abnum)
        if total > best_total:
            best_total = total
            best_start_idx = offset

    # Map sequentially from the best offset; wrap for excess MIDI measures.
    for i in range(num_midi):
        mapping[midi_nums[i]] = abcx_nums[(best_start_idx + i) % num_abcx]

    return mapping


def build_midi_measure_content(
    score_measures: list[ScoreMeasure],
    abcx_measures: dict[int, str],
    midi_to_abcx: dict[int, int],
) -> dict[int, str]:
    """Expand ABCX measure content to each Score MIDI measure.

    Each MIDI measure gets the ABCX content of its mapped ABCX measure.
    When a MIDI measure maps to an ABCX measure that spans multiple MIDI
    measures, each gets the same content (the ABC notation is the same,
    just performed at different times).
    """
    content = {}
    for m in score_measures:
        abcx_num = midi_to_abcx.get(m.measure_num)
        if abcx_num is not None and abcx_num in abcx_measures:
            raw = abcx_measures[abcx_num]
            # Strip repeat markers: `::` becomes space
            cleaned = raw.replace("::", " ").strip()
            # Strip trailing `:` (leftover from `:|`)
            cleaned = re.sub(r':\s*$', '', cleaned).strip()
            # Strip leading `:` (leftover from `|:` where `|` was consumed)
            cleaned = cleaned.lstrip(':').strip()
            # Strip leading volta numbers like `1 ` or `2 ` (from `|1`, `|2`)
            cleaned = re.sub(r'^\d+\s+', '', cleaned).strip()
            content[m.measure_num] = cleaned
    return content


def build_midi_phrases(
    score_measures: list[ScoreMeasure],
    midi_to_abcx: dict[int, int],
    midi_measure_content: dict[int, str],
    abcx_path: Path,
    expected_beats: float = 4.0,
) -> list[Phrase]:
    """Build phrases from expanded MIDI measures.

    Strategy: group consecutive measures into ~4-measure phrases.
    Use pickup detection from ABCX and `::`/`:` markers from the **original**
    ABCX structure to identify phrase boundaries, but only when they appear
    at natural structural points (not from cyclic repeats).
    """
    if not score_measures or not midi_measure_content:
        return []

    # Build the expanded measure list in MIDI order
    expanded = []
    for m in score_measures:
        mnum = m.measure_num
        content = midi_measure_content.get(mnum, "")
        if not content:
            continue
        expanded.append({"mnum": mnum, "content": content})

    if not expanded:
        return []

    # Get expected beats from ABCX header
    with open(abcx_path, encoding="utf-8") as f:
        abcx_lines = [line.rstrip() for line in f]
    for line in abcx_lines:
        if line.startswith("M:"):
            m = re.match(r'M:(\d+)/(\d+)', line)
            if m:
                expected_beats = int(m.group(1)) / int(m.group(2)) * 4
            break

    # Identify pickup measures from the **start** of the expanded list
    pickup_set = set()
    for i, m_info in enumerate(expanded):
        dur = _abc_measure_duration(m_info["content"])
        if dur < expected_beats * 0.6:
            pickup_set.add(m_info["mnum"])
        else:
            break

    # Build phrase groups: aim for 4 measures per phrase, force close at 8.
    # No `::`/`:` marker detection — just the 4-measure heuristic.
    phrases = []
    phrase_num = 1
    current_phrase_measures = []
    full_count = 0
    target = 4
    max_phrase = 8
    total = len(expanded)

    for idx, m_info in enumerate(expanded):
        mnum = m_info["mnum"]
        if mnum in pickup_set:
            continue

        current_phrase_measures.append(mnum)
        full_count += 1

        should_close = False
        remaining = total - idx - 1

        # Force close at max_phrase
        if full_count >= max_phrase:
            should_close = True
        # Close at target if there are enough remaining measures for another phrase
        elif full_count >= target and remaining >= target:
            should_close = True

        if should_close:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))
            phrase_num += 1
            current_phrase_measures = []
            full_count = 0

    # Handle trailing measures
    if current_phrase_measures:
        if len(current_phrase_measures) >= target:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))
        elif phrases:
            # Fewer than 4 measures left — merge into the last phrase
            phrases[-1].measures.extend(current_phrase_measures)
        else:
            phrases.append(Phrase(
                phrase_id=f"H{phrase_num}",
                measures=current_phrase_measures.copy(),
                has_linebreak=False,
            ))

    # Attach pickups to first full phrase
    if pickup_set and phrases:
        pickup_nums = sorted(pickup_set)
        first_full_idx = None
        for i, p in enumerate(phrases):
            if any(m not in pickup_set for m in p.measures):
                first_full_idx = i
                break

        if first_full_idx is not None:
            new_measures = pickup_nums + phrases[first_full_idx].measures
            phrases[first_full_idx] = Phrase(
                phrase_id=phrases[first_full_idx].phrase_id,
                measures=new_measures,
                has_linebreak=phrases[first_full_idx].has_linebreak,
            )

    # Post-process: merge any phrase with fewer than `target` measures
    # into the previous phrase (or next if it's the first one).
    i = 0
    while i < len(phrases):
        if len(phrases[i].measures) < target:
            if i > 0:
                phrases[i - 1].measures.extend(phrases[i].measures)
            elif len(phrases) > 1:
                phrases[1].measures = phrases[i].measures + phrases[1].measures
            phrases.pop(i)
            if i > 0:
                i -= 1
        else:
            i += 1

    # Re-number phrases
    for i, p in enumerate(phrases, 1):
        p.phrase_id = f"H{i}"

    return phrases


def align_performance_with_score(
    score_midi_path: Path,
    perf_midi_path: Path,
    align_file: Path,
    score_structure: ScoreStructure,
) -> list[tuple[int, str, float, float]]:
    """
    Step 3: Align Performance MIDI with Score structure.

    Uses Score MIDI measures as the canonical unit. Each performance note is
    mapped to its corresponding Score MIDI measure via the alignment file.
    When the performer repeats a section, all performance notes for the same
    MIDI measure are merged into a single time range.

    Returns list of (midi_measure_num, phrase_id, start_time, end_time) tuples.
    """
    score_midi = pretty_midi.PrettyMIDI(str(score_midi_path))
    perf_midi = pretty_midi.PrettyMIDI(str(perf_midi_path))

    score_notes = sorted(
        [n for inst in score_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )
    perf_notes = sorted(
        [n for inst in perf_midi.instruments if not inst.is_drum for n in inst.notes],
        key=lambda n: (n.start, n.pitch, n.end),
    )

    data = np.load(align_file, allow_pickle=True)
    perf_idx = data["perf_idx"]

    # Build score_times -> perf_times mapping
    score_times_arr = []
    perf_times_arr = []
    limit = min(len(score_notes), len(perf_idx))
    for score_idx in range(limit):
        perf_idx_value = int(perf_idx[score_idx])
        if 0 <= perf_idx_value < len(perf_notes):
            score_times_arr.append(score_notes[score_idx].start)
            perf_times_arr.append(perf_notes[perf_idx_value].start)

    score_times_arr = np.array(score_times_arr)
    perf_times_arr = np.array(perf_times_arr)

    # Build note-to-MIDI-measure mapping using the score structure
    note_to_midi_measure = {}
    for measure in score_structure.measures:
        for note_idx in range(measure.start_note_idx, measure.end_note_idx):
            note_to_midi_measure[note_idx] = measure.measure_num

    # Collect per-measure performance times
    perf_measure_times: dict[int, list[float]] = {}

    for score_idx in range(limit):
        perf_idx_value = int(perf_idx[score_idx])
        if not (0 <= perf_idx_value < len(perf_notes)):
            continue

        midi_mnum = note_to_midi_measure.get(score_idx)
        if midi_mnum is None:
            continue

        perf_time = perf_notes[perf_idx_value].start
        if midi_mnum not in perf_measure_times:
            perf_measure_times[midi_mnum] = []
        perf_measure_times[midi_mnum].append(perf_time)

    # Build contiguous time ranges for each MIDI measure.
    # The perf_measure_times gives us a distribution of performance times per
    # measure. We use min/max of these times, then merge gaps between
    # consecutive measures so that M[i].end == M[i+1].start.
    sorted_mnums = sorted(perf_measure_times.keys())
    if not sorted_mnums:
        return []

    # Step 1: compute raw per-measure time boundaries
    raw_bounds: dict[int, tuple[float, float]] = {}
    for mnum in sorted_mnums:
        times = perf_measure_times[mnum]
        raw_bounds[mnum] = (min(times), max(times))

    # Step 2: make measures contiguous — each measure's end becomes the next
    # measure's start, using the midpoint between max of current and min of next.
    contiguous: list[tuple[int, float, float]] = []
    for i, mnum in enumerate(sorted_mnums):
        raw_start, raw_end = raw_bounds[mnum]
        if i < len(sorted_mnums) - 1:
            next_mnum = sorted_mnums[i + 1]
            next_raw_start, _ = raw_bounds[next_mnum]
            contiguous_end = (raw_end + next_raw_start) / 2
        else:
            # Last measure: use raw end + small buffer
            contiguous_end = raw_end + 0.1
        contiguous_start = raw_start if i == 0 else contiguous[-1][2]
        contiguous.append((mnum, contiguous_start, contiguous_end))

    # Step 3: compute phrase-level contiguous time ranges
    phrase_bounds: dict[str, tuple[int, float, float]] = {}
    for _, mnum, start, end in [(i,) + c for i, c in enumerate(contiguous)]:
        phrase_id = score_structure.measure_to_phrase.get(mnum, "H1")
        if phrase_id not in phrase_bounds:
            phrase_bounds[phrase_id] = (mnum, start, end)
        else:
            _, ps, _ = phrase_bounds[phrase_id]
            phrase_bounds[phrase_id] = (mnum, ps, end)

    # Build result: phrase starts only when phrase changes
    result = []
    current_phrase = None
    for mnum, start, end in contiguous:
        phrase_id = score_structure.measure_to_phrase.get(mnum, "H1")
        if phrase_id != current_phrase:
            # Emit phrase header
            ps, pe = phrase_bounds[phrase_id][1], phrase_bounds[phrase_id][2]
            result.append((None, phrase_id, round(ps * 100), round(pe * 100)))
            current_phrase = phrase_id
        result.append((mnum, phrase_id, round(start * 100), round(end * 100)))

    return result


def write_aligned_abcx(
    original_abcx: Path,
    output_abcx: Path,
    phrases: list[Phrase],
    measure_content: dict[int, str],
) -> bool:
    """Write expanded ABCX file with H/M markers based on MIDI measure structure.

    Unlike the compact ABCX (which has one entry per score measure),
    this expanded version has one entry per Score MIDI measure (including repeats).
    """
    phrase_groups = [
        (phrase.phrase_id, phrase.measures, phrase.has_linebreak)
        for phrase in phrases
    ]
    measures = sorted(measure_content.items())

    try:
        text = build_aligned_abcx(original_abcx, measures, phrase_groups)
    except AlignedAbcxError:
        if output_abcx.exists():
            output_abcx.unlink()
        return False

    output_abcx.parent.mkdir(parents=True, exist_ok=True)
    with open(output_abcx, "w", encoding="utf-8") as f:
        f.write(text)
    return True

def generate_performance_tsv_with_phrases(
    perf_midi_path: Path,
    perf_entries: list[tuple[int | None, str, int, int]],
    output_tsv: Path,
    midi_tsv,
) -> bool:
    """Generate LM-MIDI TSV v0.3 with fixed 4-column event rows.

    perf_entries: list of (mnum|None, phrase_id, start_tick, end_tick)
    - (None, phrase_id, start, end) → phrase header
    - (mnum, phrase_id, start, end) → measure entry
    All times are already in integer ticks (100 ticks = 1 second).

    TSV columns are:
        event, value, duration, offset

    Note events use Logic Pro note names (MIDI 60 = C3).  Durations and
    offsets are 10 ms bins.  Structural and pedal PAD slots are written as 0.
    """
    def structural_row(event: str, value: int, duration: int) -> str:
        duration = max(0, min(65535, int(duration)))
        return f"{event}\t{value}\t{duration // 256}\t{duration % 256}"

    perf_midi = pretty_midi.PrettyMIDI(str(perf_midi_path))

    all_notes = []
    for inst in perf_midi.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            all_notes.append({
                "pitch": note.pitch,
                "start": note.start,
                "end": note.end,
                "dur": note.end - note.start,
                "vel": note.velocity,
            })

    all_pedals = []
    for inst in perf_midi.instruments:
        if inst.is_drum:
            continue
        for cc in inst.control_changes:
            if cc.number == 64:
                all_pedals.append({"t": cc.time, "val": cc.value})

    lines = [
        "# midi-tsv v0.3",
        f"# source={perf_midi_path.name}",
        "# unit=bin",
        "# bin_ms=10",
        "# columns=event\tvalue\tduration\toffset",
        "# pitch=logic-pro-note",
        "# middle_c=C3",
        "# nil=0",
        "# note_offset=previous_note_onset",
        "# pedal_offset=most_recent_note_onset",
        "# structural_duration=u16_hi_lo",
        "# slice_type=measure",
    ]

    # Build measure boundaries for pedal quantization
    measure_bounds = []
    for mnum_or_none, phrase_id, start_tick, end_tick in perf_entries:
        if mnum_or_none is not None:
            measure_bounds.append({
                "id": mnum_or_none,
                "start": start_tick,
                "end": end_tick,
            })

    # Quantize pedals across all notes
    pedal_dicts = [
        {"t": round(p["t"] * 100), "val": p["val"], "type": "sustain"}
        for p in all_pedals
    ]
    note_dicts = [
        {"t": round(n["start"] * 100), "end": round(n["end"] * 100)}
        for n in all_notes
    ]
    quantized_pedals = midi_tsv.smart_quantize_pedals_between_notes(
        pedal_dicts, note_dicts, measure_bounds
    )

    # Iterate through entries: phrase headers and measure entries are already ordered
    phrase_index = -1
    measure_local_index = 0
    last_note_tick: int | None = None

    for mnum_or_none, phrase_id, start_tick, end_tick in perf_entries:
        if mnum_or_none is None:
            phrase_index += 1
            measure_local_index = 0
            lines.append(structural_row("H", phrase_index, end_tick - start_tick))
            continue

        m_start_s = start_tick * 0.01
        m_end_s = end_tick * 0.01

        # Find notes in this measure
        events = []
        for n in all_notes:
            if m_start_s <= n["start"] < m_end_s:
                abs_start_tick = round(n["start"] * 100)
                dur_tick = round(n["dur"] * 100)
                events.append((abs_start_tick, 0, n["pitch"], dur_tick, n["vel"]))

        # Find quantized pedals in this measure
        for p in quantized_pedals:
            p_tick = int(p["t"])
            if start_tick <= p_tick < end_tick:
                events.append((p_tick, 1, None, 0, p["val"]))

        # Structural rows do not affect note-offset reference.
        lines.append(structural_row("M", measure_local_index, end_tick - start_tick))
        measure_local_index += 1

        # Notes establish the timing anchor.  Pedals at the same timestamp are
        # emitted after notes so they can attach to that note onset.
        events.sort(key=lambda e: (e[0], e[1], e[2] if e[2] is not None else 128))

        for abs_tick, kind, pitch, duration, value in events:
            if kind == 0:
                note_offset = 0 if last_note_tick is None else max(0, abs_tick - last_note_tick)
                last_note_tick = abs_tick
                for row in semantic_event_to_tsv_rows(
                    midi_pitch_to_logic_note(int(pitch)),
                    int(value),
                    int(duration),
                    note_offset,
                ):
                    lines.append(tsv_row_to_line(row))
            else:
                pedal_offset = 0 if last_note_tick is None else max(0, abs_tick - last_note_tick)
                for row in semantic_event_to_tsv_rows("P", int(value), 0, pedal_offset):
                    lines.append(tsv_row_to_line(row))

    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_tsv, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return True


def _build_score_structure(
    score_midi: Path,
    score_abcx: Path,
    piece_dir: Path,
    midi_tsv,
) -> tuple[ScoreStructure, bool]:
    """Build ScoreStructure from a Score MIDI file. Returns (structure, success)."""
    score_measures = extract_score_measures(score_midi, midi_tsv)
    if not score_measures:
        return None, False

    _, abcx_measures = parse_abcx_structure(score_abcx, score_measures)

    # For content-based matching, prefer the raw full Score MIDI
    # to get pitch data for all measures including repeats
    raw_score_midi = piece_dir.parent.parent / piece_dir.relative_to(piece_dir.parent.parent) / "score_PDMX.mid"
    if not raw_score_midi.exists():
        raw_score_midi = None
    mapping_source = raw_score_midi or score_midi
    midi_to_abcx = build_midi_to_abcx_mapping(score_measures, abcx_measures, mapping_source)

    midi_measure_content = build_midi_measure_content(score_measures, abcx_measures, midi_to_abcx)
    midi_phrases = build_midi_phrases(score_measures, midi_to_abcx, midi_measure_content, score_abcx)

    measure_to_phrase = {}
    for phrase in midi_phrases:
        for measure_num in phrase.measures:
            measure_to_phrase[measure_num] = phrase.phrase_id

    score_structure = ScoreStructure(
        measures=score_measures,
        phrases=midi_phrases,
        measure_to_phrase=measure_to_phrase,
        abcx_measures=abcx_measures,
        midi_to_abcx=midi_to_abcx,
        midi_measure_content=midi_measure_content,
    )
    return score_structure, True


def _process_score_midi(
    score_midi: Path,
    score_abcx: Path,
    piece_dir: Path,
    refined_piece_dir: Path,
    output_piece_dir: Path,
    midi_tsv,
    suffix: str = "",
) -> int:
    """Process one Score MIDI version (main or mini).

    Generates:
    - score_structure{suffix}.json
    - score_aligned{suffix}.abcx
    - For each align file matching the score type: {perf}_refined.mid{suffix}.tsv

    suffix is "" for main, "_mini" for mini.
    """
    struct, ok = _build_score_structure(score_midi, score_abcx, piece_dir, midi_tsv)
    if not ok:
        return 0

    # Write score_structure.json (or _mini variant)
    json_path = output_piece_dir / f"score_structure{suffix}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "measures": [asdict(m) for m in struct.measures],
            "phrases": [asdict(p) for p in struct.phrases],
            "measure_to_phrase": struct.measure_to_phrase,
            "abcx_measures": struct.abcx_measures,
            "midi_to_abcx": struct.midi_to_abcx,
            "midi_measure_content": {str(k): v for k, v in sorted(struct.midi_measure_content.items())},
        }, f, indent=2, ensure_ascii=False)

    # Write score_aligned.abcx (or _mini variant)
    write_aligned_abcx(score_abcx, output_piece_dir / f"score_aligned{suffix}.abcx", struct.phrases, struct.midi_measure_content)

    # Step 3: Align performance MIDI files
    # Match align files to score type:
    #   main: *_refined_align.npz (not mini)
    #   mini: *_mini_refined_align.npz
    if suffix == "_mini":
        align_pattern = "*_mini_refined_align.npz"
    else:
        align_pattern = "*_refined_align.npz"
        # Exclude mini align files from main processing

    success_count = 0
    for align_file in refined_piece_dir.glob(align_pattern):
        if suffix != "_mini" and "_mini_" in align_file.name:
            continue

        # Determine corresponding perf MIDI name
        if suffix == "_mini":
            perf_midi_name = align_file.name.replace("_mini_refined_align.npz", "_mini_refined.mid")
        else:
            perf_midi_name = align_file.name.replace("_refined_align.npz", "_refined.mid")

        perf_midi = refined_piece_dir / perf_midi_name
        if not perf_midi.exists():
            continue

        perf_measures = align_performance_with_score(score_midi, perf_midi, align_file, struct)

        # Determine TSV output name
        if suffix == "_mini":
            # perf_midi_name is e.g. Aria_xxx_mini_refined.mid
            # TSV name should be Aria_xxx_mini_refined.tsv
            tsv_name = perf_midi_name + ".tsv"
        else:
            tsv_name = perf_midi_name + ".tsv"

        output_tsv = output_piece_dir / tsv_name
        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_measures,
            output_tsv,
            midi_tsv,
        ):
            success_count += 1

    return success_count


def process_piece(
    piece_dir: Path,
    refined_root: Path,
    output_dir: Path,
    midi_tsv,
) -> bool:
    """Main pipeline: run all three steps for one piece.

    DEPRECATED: use process_metadata_task() instead, which uses metadata.csv
    as the source of truth rather than directory scanning.
    """
    import shutil

    try:
        # Find required files
        score_abcx = piece_dir / "score.abcx"
        if not score_abcx.exists():
            return False

        # Map piece_dir (under PianoCoRe_output) to refined_piece_dir
        refined_piece_dir = None
        for base in [piece_dir.parent, piece_dir.parent.parent, piece_dir.parent.parent.parent]:
            try:
                rel_path = piece_dir.relative_to(base)
                candidate = refined_root / rel_path
                if (candidate / "score_PDMX_refined.mid").exists() or (candidate / "score_PDMX_mini_refined.mid").exists():
                    refined_piece_dir = candidate
                    break
            except ValueError:
                continue

        if refined_piece_dir is None:
            return False

        # Determine output directory
        output_piece_dir = output_dir / refined_piece_dir.relative_to(refined_root)
        output_piece_dir.mkdir(parents=True, exist_ok=True)

        # Copy original score.abcx (only once)
        shutil.copy2(score_abcx, output_piece_dir / "score.abcx")

        any_success = False

        # Main Score MIDI
        main_score = refined_piece_dir / "score_PDMX_refined.mid"
        if main_score.exists():
            count = _process_score_midi(
                main_score, score_abcx, piece_dir, refined_piece_dir,
                output_piece_dir, midi_tsv, suffix="",
            )
            any_success = any_success or count > 0

        # Mini Score MIDI (if exists)
        mini_score = refined_piece_dir / "score_PDMX_mini_refined.mid"
        if mini_score.exists():
            count = _process_score_midi(
                mini_score, score_abcx, piece_dir, refined_piece_dir,
                output_piece_dir, midi_tsv, suffix="_mini",
            )
            any_success = any_success or count > 0

        return any_success

    except Exception as exc:
        print(f"Error processing {piece_dir}: {exc}")
        return False


def process_metadata_task_legacy(
    task: dict,
    midi_tsv,
    refined_root: Path,
    abcx_root: Path,
    output_dir: Path,
) -> int:
    """Process one score file + its performances, driven by metadata.

    task: {
        'score_path': str,       # relative to refined_root, e.g. 'Composer/Piece/score_PDMX_refined.mid'
        'piece_path': str,       # relative to abcx_root, e.g. 'Composer/Piece'
        'suffix': str,           # '' or '_mini'
        'performances': [        # list of (perf_midi_path, align_path) relative to refined_root
            ('Composer/Piece/Aria_xxx_refined.mid', 'Composer/Piece/Aria_xxx_refined_align.npz'),
            ...
        ]
    }

    Returns number of successful TSV generations.
    """
    import shutil

    score_midi = refined_root / task['score_path']
    abcx_path = abcx_root / task['piece_path'] / 'score.abcx'
    piece_rel = task['piece_path']
    suffix = task['suffix']

    if not score_midi.exists() or not abcx_path.exists():
        return 0

    # Build score structure
    score_measures = extract_score_measures(score_midi, midi_tsv)
    if not score_measures:
        return 0

    _, abcx_measures = parse_abcx_structure(abcx_path, score_measures)

    # Use raw score MIDI for content matching fallback
    raw_score_midi = refined_root / task['score_path'].replace('_refined.mid', '.mid')
    mapping_source = raw_score_midi if raw_score_midi.exists() else score_midi
    midi_to_abcx = build_midi_to_abcx_mapping(score_measures, abcx_measures, mapping_source)

    midi_measure_content = build_midi_measure_content(score_measures, abcx_measures, midi_to_abcx)
    midi_phrases = build_midi_phrases(score_measures, midi_to_abcx, midi_measure_content, abcx_path)

    measure_to_phrase = {}
    for phrase in midi_phrases:
        for measure_num in phrase.measures:
            measure_to_phrase[measure_num] = phrase.phrase_id

    score_structure = ScoreStructure(
        measures=score_measures,
        phrases=midi_phrases,
        measure_to_phrase=measure_to_phrase,
        abcx_measures=abcx_measures,
        midi_to_abcx=midi_to_abcx,
        midi_measure_content=midi_measure_content,
    )

    # Output directory
    output_piece_dir = output_dir / piece_rel
    output_piece_dir.mkdir(parents=True, exist_ok=True)

    # Write score_structure.json (write once, skip if exists)
    json_path = output_piece_dir / f"score_structure{suffix}.json"
    if not json_path.exists():
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "measures": [asdict(m) for m in score_structure.measures],
                "phrases": [asdict(p) for p in score_structure.phrases],
                "measure_to_phrase": score_structure.measure_to_phrase,
                "abcx_measures": score_structure.abcx_measures,
                "midi_to_abcx": score_structure.midi_to_abcx,
                "midi_measure_content": {str(k): v for k, v in sorted(score_structure.midi_measure_content.items())},
            }, f, indent=2, ensure_ascii=False)

    # Write score_aligned.abcx. Scores that cannot be projected to the two-staff
    # aligned format are removed/skipped by write_aligned_abcx.
    aligned_abcx = output_piece_dir / f"score_aligned{suffix}.abcx"
    write_aligned_abcx(abcx_path, aligned_abcx, score_structure.phrases, score_structure.midi_measure_content)

    # Copy original score.abcx (write once)
    orig_abcx = output_piece_dir / "score.abcx"
    if not orig_abcx.exists():
        shutil.copy2(abcx_path, orig_abcx)

    # Process each performance
    success_count = 0
    for perf_midi_rel, align_rel in task['performances']:
        perf_midi = refined_root / perf_midi_rel
        align_file = refined_root / align_rel

        if not perf_midi.exists() or not align_file.exists():
            continue

        perf_measures = align_performance_with_score(score_midi, perf_midi, align_file, score_structure)

        # TSV output name: same as perf MIDI but with .tsv extension
        tsv_name = Path(perf_midi_rel).name + ".tsv"
        output_tsv = output_piece_dir / tsv_name

        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_measures,
            output_tsv,
            midi_tsv,
        ):
            success_count += 1

    return success_count


def process_metadata_task(
    task: dict,
    midi_tsv,
    pianocore_root: Path,
    output_dir: Path,
    overwrite_tsv: bool = False,
) -> int:
    """Process one score file + its performances, driven by metadata with refined priority.

    task: {
        'score_path': str,       # relative path from metadata, e.g. 'Composer/Piece/score_PDMX_refined.mid'
        'piece_path': str,       # piece identifier, e.g. 'Composer/Piece'
        'suffix': str,           # '' or '_mini'
        'performances': [        # list of (perf_midi_path, align_path) from metadata
            ('Composer/Piece/Aria_xxx_refined.mid', 'Composer/Piece/Aria_xxx_refined_align.npz'),
            ...
        ],
        'abcx_path': str,        # full path from metadata, e.g. 'PianoCoRe/score/Composer/Piece/score.abcx'
    }

    Returns number of successful TSV generations.
    """
    import shutil

    # Metadata paths for refined files live under `refined/`, while the
    # non-refined assets used by legacy ASAP rows live under `raw/`.
    score_path = task['score_path']
    if '_refined' in score_path or '_mini' in score_path:
        score_midi = pianocore_root / 'refined' / score_path
    else:
        score_midi = pianocore_root / 'raw' / score_path

    abcx_path = Path(task['abcx_path'])
    piece_rel = task['piece_path']
    suffix = task['suffix']

    if not score_midi.exists() or not abcx_path.exists():
        return 0

    # Build score structure
    score_measures = extract_score_measures(score_midi, midi_tsv)
    if not score_measures:
        return 0

    _, abcx_measures = parse_abcx_structure(abcx_path, score_measures)

    # Use raw score MIDI for content matching fallback
    raw_score_path = task['score_path'].replace('_refined.mid', '.mid')
    if '_refined' in raw_score_path or '_mini' in raw_score_path:
        raw_score_midi = pianocore_root / 'refined' / raw_score_path
    else:
        raw_score_midi = pianocore_root / 'raw' / raw_score_path
    mapping_source = raw_score_midi if raw_score_midi.exists() else score_midi
    midi_to_abcx = build_midi_to_abcx_mapping(score_measures, abcx_measures, mapping_source)

    midi_measure_content = build_midi_measure_content(score_measures, abcx_measures, midi_to_abcx)
    midi_phrases = build_midi_phrases(score_measures, midi_to_abcx, midi_measure_content, abcx_path)

    measure_to_phrase = {}
    for phrase in midi_phrases:
        for measure_num in phrase.measures:
            measure_to_phrase[measure_num] = phrase.phrase_id

    score_structure = ScoreStructure(
        measures=score_measures,
        phrases=midi_phrases,
        measure_to_phrase=measure_to_phrase,
        abcx_measures=abcx_measures,
        midi_to_abcx=midi_to_abcx,
        midi_measure_content=midi_measure_content,
    )

    # Output directory
    output_piece_dir = output_dir / piece_rel
    output_piece_dir.mkdir(parents=True, exist_ok=True)

    # Write score_structure.json (write once, skip if exists)
    json_path = output_piece_dir / f"score_structure{suffix}.json"
    if not json_path.exists():
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "measures": [asdict(m) for m in score_structure.measures],
                "phrases": [asdict(p) for p in score_structure.phrases],
                "measure_to_phrase": score_structure.measure_to_phrase,
                "abcx_measures": score_structure.abcx_measures,
                "midi_to_abcx": score_structure.midi_to_abcx,
                "midi_measure_content": {str(k): v for k, v in sorted(score_structure.midi_measure_content.items())},
            }, f, indent=2, ensure_ascii=False)

    # Write score_aligned.abcx. Scores that cannot be projected to the two-staff
    # aligned format are removed/skipped by write_aligned_abcx.
    aligned_abcx = output_piece_dir / f"score_aligned{suffix}.abcx"
    write_aligned_abcx(abcx_path, aligned_abcx, score_structure.phrases, score_structure.midi_measure_content)

    # Copy original score.abcx (write once)
    orig_abcx = output_piece_dir / "score.abcx"
    if not orig_abcx.exists():
        shutil.copy2(abcx_path, orig_abcx)

    # Process each performance
    success_count = 0
    for perf_midi_rel, align_rel in task['performances']:
        # Metadata paths for refined files live under `refined/`, while the
        # non-refined assets used by legacy ASAP rows live under `raw/`.
        if '_refined' in perf_midi_rel or '_mini' in perf_midi_rel:
            perf_midi = pianocore_root / 'refined' / perf_midi_rel
            align_file = pianocore_root / 'refined' / align_rel
        else:
            perf_midi = pianocore_root / 'raw' / perf_midi_rel
            align_file = pianocore_root / 'raw' / align_rel

        if not perf_midi.exists() or not align_file.exists():
            continue

        perf_measures = align_performance_with_score(score_midi, perf_midi, align_file, score_structure)

        # TSV output name: same as perf MIDI but with .tsv extension
        tsv_name = Path(perf_midi_rel).name + ".tsv"
        output_tsv = output_piece_dir / tsv_name

        # Skip TSV generation if already exists and non-empty, unless the user
        # is intentionally building after a serialization fix.
        if not overwrite_tsv and output_tsv.exists() and output_tsv.stat().st_size > 0:
            success_count += 1
            continue

        if generate_performance_tsv_with_phrases(
            perf_midi,
            perf_measures,
            output_tsv,
            midi_tsv,
        ):
            success_count += 1

    return success_count


# Global references for worker processes (set by _worker_init)
_worker_refined_root = None
_worker_output_dir = None
_worker_abcx_root = None


def _worker_init_legacy(refined_root, output_dir, abcx_root):
    """Initialize worker process with required modules and paths."""
    global _worker_midi_tsv, _worker_refined_root, _worker_output_dir, _worker_abcx_root
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    _worker_midi_tsv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_worker_midi_tsv)
    _worker_refined_root = refined_root
    _worker_output_dir = output_dir
    _worker_abcx_root = abcx_root


def _worker_process_legacy(task):
    """Worker function for metadata-driven multiprocessing."""
    return process_metadata_task_legacy(task, _worker_midi_tsv, _worker_refined_root, _worker_abcx_root, _worker_output_dir)


# Worker functions for metadata-driven processing with refined priority
_worker_pianocore_root = None
_worker_overwrite_tsv = False


def _worker_init(pianocore_root, output_dir, overwrite_tsv=False):
    """Initialize worker process for metadata-driven processing with refined priority."""
    global _worker_midi_tsv, _worker_pianocore_root, _worker_output_dir, _worker_overwrite_tsv
    midi_tsv_script = Path(__file__).parent.parent / "wave-roll" / "midi_tsv.py"
    spec = importlib.util.spec_from_file_location("midi_tsv", midi_tsv_script)
    _worker_midi_tsv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_worker_midi_tsv)
    _worker_pianocore_root = pianocore_root
    _worker_output_dir = output_dir
    _worker_overwrite_tsv = overwrite_tsv


def _worker_process(task):
    """Worker function for metadata-driven multiprocessing."""
    return process_metadata_task(
        task,
        _worker_midi_tsv,
        _worker_pianocore_root,
        _worker_output_dir,
        overwrite_tsv=_worker_overwrite_tsv,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete score-performance alignment with repeat detection"
    )
    parser.add_argument(
        "--metadata",
        default="PianoCoRe/metadata.csv",
        help="Path to metadata.csv",
    )
    parser.add_argument(
        "--pianocore-root",
        default="PianoCoRe",
        help="PianoCoRe root directory",
    )
    parser.add_argument(
        "--output-dir",
        default="PianoCoRe/aligned",
        help="Output directory (default: PianoCoRe/aligned)",
    )
    parser.add_argument(
        "--tier",
        default="all",
        choices=["a", "a_star", "b", "all"],
        help="Which tier to process (default: all)",
    )
    parser.add_argument(
        "--piece-filter",
        default=None,
        help="Process only pieces matching this substring",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of score files to process",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=16,
        help="Number of parallel workers (default: 16, use 0 for CPU count)",
    )
    parser.add_argument(
        "--overwrite-tsv",
        action="store_true",
        help="Regenerate TSV files even when the output path already exists",
    )
    args = parser.parse_args()

    import pandas as pd

    pianocore_root = Path(args.pianocore_root)
    output_dir = Path(args.output_dir)

    # ---- Step 1: Load metadata and filter ----
    meta = pd.read_csv(args.metadata)

    # Filter by tier
    if args.tier == 'a_star':
        meta = meta[meta['tier_a_star'] == True]
    elif args.tier == 'a':
        meta = meta[meta['tier_a'] == True]
    elif args.tier == 'b':
        meta = meta[meta['tier_b'] == True]
    # 'all' keeps everything

    # Filter: must have score_abcx_path
    meta = meta[meta['score_abcx_path'].notna()]

    # Filter: must have either refined or non-refined paths (prefer refined)
    # For score: refined_score_midi_path OR score_midi_path
    # For performance: refined_performance_midi_path OR performance_midi_path
    # For alignment: refined_alignment_path OR raw_alignment_path
    has_score = meta['refined_score_midi_path'].notna() | meta['score_midi_path'].notna()
    has_perf = meta['refined_performance_midi_path'].notna() | meta['performance_midi_path'].notna()
    has_align = meta['refined_alignment_path'].notna() | meta['raw_alignment_path'].notna()
    meta = meta[has_score & has_perf & has_align]

    # Apply piece filter
    if args.piece_filter:
        meta = meta[meta['score_abcx_path'].str.contains(args.piece_filter, na=False)]

    # ---- Step 2: Build tasks with refined priority ----
    # For each row, pick refined if available, otherwise use non-refined
    def get_paths(row):
        """Extract paths with refined priority."""
        score_midi = row['refined_score_midi_path'] if pd.notna(row['refined_score_midi_path']) else row['score_midi_path']
        perf_midi = row['refined_performance_midi_path'] if pd.notna(row['refined_performance_midi_path']) else row['performance_midi_path']
        align_path = row['refined_alignment_path'] if pd.notna(row['refined_alignment_path']) else row['raw_alignment_path']

        # Determine suffix based on score path
        suffix = '_mini' if '_mini' in str(score_midi) else ''

        return {
            'score_midi': score_midi,
            'perf_midi': perf_midi,
            'align_path': align_path,
            'abcx_path': row['score_abcx_path'],
            'suffix': suffix,
        }

    # Build task list
    tasks_dict = {}  # key: (score_midi, abcx_path, suffix), value: list of (perf_midi, align_path)

    for _, row in meta.iterrows():
        paths = get_paths(row)
        key = (paths['score_midi'], paths['abcx_path'], paths['suffix'])

        if key not in tasks_dict:
            tasks_dict[key] = []

        tasks_dict[key].append((paths['perf_midi'], paths['align_path']))

    # Convert to task list
    tasks = []
    for (score_midi, abcx_path, suffix), perfs in tasks_dict.items():
        # Extract piece_path from abcx_path (remove 'PianoCoRe/score/' prefix and '/score.abcx' suffix)
        abcx_rel = abcx_path.replace('PianoCoRe/score/', '').replace('/score.abcx', '')

        tasks.append({
            'score_path': score_midi,
            'piece_path': abcx_rel,
            'suffix': suffix,
            'performances': perfs,
            'abcx_path': abcx_path,
        })

    if args.limit:
        tasks = tasks[:args.limit]

    total_perfs = sum(len(t['performances']) for t in tasks)
    print(f"Found {len(tasks)} score files, {total_perfs} performances to process")

    # ---- Step 3: Process ----
    jobs = args.jobs
    if jobs == 0:
        import multiprocessing
        jobs = multiprocessing.cpu_count()

    if jobs <= 1:
        midi_tsv = load_midi_tsv_module()
        success_count = 0
        tsv_count = 0
        for task in tqdm(tasks):
            n = process_metadata_task(
                task,
                midi_tsv,
                pianocore_root,
                output_dir,
                overwrite_tsv=args.overwrite_tsv,
            )
            success_count += 1 if n > 0 else 0
            tsv_count += n
    else:
        from multiprocessing import Pool, cpu_count

        n_workers = min(jobs, len(tasks), cpu_count())
        init_args = (pianocore_root, output_dir, args.overwrite_tsv)

        with Pool(n_workers, initializer=_worker_init, initargs=init_args) as pool:
            results = list(tqdm(
                pool.imap(_worker_process, tasks),
                total=len(tasks),
            ))
        success_count = sum(1 for r in results if r > 0)
        tsv_count = sum(results)

    print(f"\n处理完成: {success_count} / {len(tasks)} 个 score 成功")
    print(f"生成 {tsv_count} 个 TSV 文件")
    print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    main()
