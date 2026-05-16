"""Utilities for projecting raw ABCX scores into two-staff aligned ABCX."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class AlignedAbcxError(ValueError):
    """Raised when a raw ABCX score cannot be converted to aligned ABCX."""


@dataclass(frozen=True)
class ScoreLayout:
    """Raw score voice order plus the two output staves to keep."""

    staves: list[list[int]]
    voice_order: list[int]
    mode: str


def read_abcx_lines(abcx_path: Path) -> list[str]:
    with open(abcx_path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def parse_score_layout(lines: list[str]) -> ScoreLayout:
    """Return a two-staff projection from %%score, or raise.

    Preferred forms map directly:
    - %%score { 1 | 2 }
    - %%score { (1 2 5) | (3 4 6) }
    - %%score 1 | 2

    Relaxed forms are projected to two staves:
    - %%score 1 2                  -> 1 ; 2
    - %%score 1 { (2 4) | (3 5) }  -> keep the braced piano group
    - 3+ top-level staves          -> fold upper half ; lower half
    """
    score_lines = [line for line in lines if line.lstrip().startswith("%%score")]
    if not score_lines:
        raise AlignedAbcxError("missing %%score")
    if len(score_lines) != 1:
        raise AlignedAbcxError("multiple %%score directives")

    payload = score_lines[0].lstrip()[len("%%score"):].strip()
    if not payload:
        raise AlignedAbcxError("empty %%score")

    voice_order = _voice_numbers(payload)
    if not voice_order:
        raise AlignedAbcxError("%%score without voices")

    piano_group = _find_braced_two_staff_group(payload)
    if piano_group is not None:
        return ScoreLayout(piano_group, voice_order, "braced_two_staff_projection")

    payload_no_outer = _strip_outer_braces(payload)
    if "{" in payload_no_outer or "}" in payload_no_outer:
        raise AlignedAbcxError("%%score contains unsupported nested groups")

    parts = _split_top_level_staffs(payload_no_outer)
    if len(parts) == 2:
        return ScoreLayout(_parts_to_staves(parts), voice_order, "two_staff")

    if len(parts) == 1:
        voices = _voice_numbers(parts[0])
        if len(voices) == 2:
            return ScoreLayout([[voices[0]], [voices[1]]], voice_order, "two_voice")
        if len(voices) > 2:
            split = max(1, len(voices) // 2)
            return ScoreLayout([voices[:split], voices[split:]], voice_order, "voice_fold")

    if len(parts) > 2:
        top_level_staves = _parts_to_staves(parts)
        split = max(1, len(top_level_staves) // 2)
        upper = [voice for staff in top_level_staves[:split] for voice in staff]
        lower = [voice for staff in top_level_staves[split:] for voice in staff]
        return ScoreLayout([upper, lower], voice_order, "multi_staff_fold")

    raise AlignedAbcxError("could not project %%score to two staves")


def is_two_staff_abcx(abcx_path: Path) -> bool:
    try:
        parse_score_layout(read_abcx_lines(abcx_path))
        return True
    except AlignedAbcxError:
        return False


def extract_aligned_header(lines: list[str]) -> list[str]:
    """Extract header/directive lines, dropping %%score and V: definitions."""
    header: list[str] = []
    found_k = False

    for line in lines:
        stripped = line.strip()
        if not found_k:
            if _keep_header_line(stripped):
                header.append(line)
            if stripped.startswith("K:"):
                found_k = True
            continue

        if not stripped:
            continue
        if stripped.startswith("V:") or stripped.startswith("w:"):
            continue
        if stripped.startswith("%"):
            if not stripped.startswith("%%score"):
                header.append(line)
            continue
        break

    if not found_k:
        raise AlignedAbcxError("missing K: header")
    return header


def parse_body_measures(lines: list[str]) -> list[str]:
    """Parse raw ABCX body into measure fragments without bar lines."""
    body_start = None
    found_k = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("K:"):
            found_k = True
            continue
        if not found_k:
            continue
        if not stripped or stripped.startswith(("V:", "%", "w:")):
            continue
        body_start = i
        break

    if body_start is None:
        return []

    body_lines = []
    for line in lines[body_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("V:", "w:")):
            continue
        body_lines.append(stripped)

    body_text = " ".join(body_lines)
    measures: list[str] = []
    for segment in body_text.split("|"):
        segment = segment.strip()
        if not segment:
            continue
        for part in segment.split("::"):
            cleaned = clean_measure_markers(part)
            if cleaned:
                measures.append(cleaned)
    return measures


def clean_measure_markers(content: str) -> str:
    cleaned = content.strip()
    cleaned = cleaned.lstrip(":").strip()
    cleaned = re.sub(r":\s*$", "", cleaned).strip()
    cleaned = re.sub(r"^\d+\s+", "", cleaned).strip()
    if re.fullmatch(r"[\[\]]+", cleaned):
        return ""
    return cleaned


def simplify_measure_content(content: str, layout: ScoreLayout) -> str:
    """Collapse raw per-voice measure content into StaffU ; StaffL."""
    parts = [clean_measure_markers(p) for p in content.split(";")]
    voice_to_index = {
        voice: index for index, voice in enumerate(layout.voice_order)
        if voice not in layout.voice_order[:index]
    }

    staff_texts: list[str] = []
    for staff in layout.staves:
        voices = []
        for voice in staff:
            part_index = voice_to_index.get(voice)
            if part_index is None or part_index >= len(parts):
                voices.append("")
            else:
                voices.append(parts[part_index])

        while voices and is_rest_only_voice(voices[-1]):
            voices.pop()

        if not voices:
            staff_texts.append(".")
        else:
            staff_texts.append(" & ".join(v.strip() or "." for v in voices))

    return f"{staff_texts[0]} ; {staff_texts[1]}"


def build_aligned_abcx(
    original_abcx: Path,
    measures: list[tuple[int, str]],
    phrase_groups: list[tuple[str, list[int], bool]],
) -> str:
    """Build aligned ABCX text from raw/expanded measure content."""
    lines = read_abcx_lines(original_abcx)
    layout = parse_score_layout(lines)
    header = extract_aligned_header(lines)
    measure_map = {
        measure_num: simplify_measure_content(content, layout)
        for measure_num, content in measures
    }

    out_lines = list(header)
    for phrase_id, phrase_measures, has_linebreak in phrase_groups:
        out_lines.append(phrase_id)
        for measure_num in phrase_measures:
            content = measure_map.get(measure_num, ". ; .")
            out_lines.append(f"M{measure_num}\t{content}")
        if has_linebreak:
            out_lines.append("$")
    return "\n".join(out_lines) + "\n"


def build_orphan_aligned_abcx(
    abcx_path: Path,
    phrase_size: int = 4,
) -> str:
    lines = read_abcx_lines(abcx_path)
    layout = parse_score_layout(lines)
    header = extract_aligned_header(lines)
    raw_measures = parse_body_measures(lines)
    if not raw_measures:
        raise AlignedAbcxError("no body measures")

    out_lines = list(header)
    phrase_id = 1
    for i in range(0, len(raw_measures), phrase_size):
        out_lines.append(f"H{phrase_id}")
        for j, content in enumerate(raw_measures[i:i + phrase_size]):
            measure_num = i + j + 1
            out_lines.append(
                f"M{measure_num}\t{simplify_measure_content(content, layout)}"
            )
        phrase_id += 1
    return "\n".join(out_lines) + "\n"


def is_rest_only_voice(content: str) -> bool:
    """Return True when a voice has no pitched ABC notes."""
    cleaned = content.strip()
    if not cleaned or cleaned == ".":
        return True

    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    cleaned = re.sub(r"![^!]*!", "", cleaned)
    cleaned = re.sub(r"\[[A-Za-z]:[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"%\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\[A-Za-z]+", "", cleaned)
    return re.search(r"[\^_=]?[A-Ga-g][,']*", cleaned) is None


def _keep_header_line(stripped: str) -> bool:
    if not stripped:
        return False
    if stripped.startswith("%%score") or stripped.startswith("V:"):
        return False
    return stripped.startswith(("X:", "T:", "C:", "Z:", "L:", "Q:", "M:", "K:", "%"))


def _strip_outer_braces(payload: str) -> str:
    if not (payload.startswith("{") and payload.endswith("}")):
        return payload

    depth = 0
    for i, char in enumerate(payload):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and i != len(payload) - 1:
                return payload
    return payload[1:-1].strip()


def _split_top_level_staffs(payload: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in payload:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _parts_to_staves(parts: list[str]) -> list[list[int]]:
    staves: list[list[int]] = []
    for part in parts:
        voices = _voice_numbers(part)
        if not voices:
            raise AlignedAbcxError("staff without voices")
        staves.append(voices)
    return staves


def _voice_numbers(text: str) -> list[int]:
    return [int(v) for v in re.findall(r"\d+", text)]


def _find_braced_two_staff_group(payload: str) -> list[list[int]] | None:
    candidates: list[list[list[int]]] = []
    for group in _balanced_groups(payload, "{", "}"):
        inner = _strip_outer_braces(group.strip())
        parts = _split_top_level_staffs(inner)
        if len(parts) == 2:
            candidates.append(_parts_to_staves(parts))

    if not candidates:
        return None
    return max(candidates, key=lambda staves: sum(len(staff) for staff in staves))


def _balanced_groups(text: str, opener: str, closer: str) -> list[str]:
    groups: list[str] = []
    start = None
    depth = 0
    for index, char in enumerate(text):
        if char == opener:
            if depth == 0:
                start = index
            depth += 1
        elif char == closer and depth:
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(text[start:index + 1])
                start = None
    return groups
