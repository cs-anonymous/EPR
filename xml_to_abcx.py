#!/usr/bin/env python3
"""Convert MusicXML -> ABCX via xml2abc + abc2abcx.

Pipeline:
    MusicXML (.musicxml / .xml / .mxl)
        |
        v  (xml2abc.py by W. Vergeynst)
    ABC (rich: dynamics, slurs, articulations, pedals, tempo marks)
        |
        v  (abc2abcx.to_standard_abcx)
    ABCX (unified L: across voices, `;`-separated measures)

Why MusicXML (not Score MIDI) is the preferred source:
    MusicXML preserves the full symbolic layer -- `p/f`, `crescendo`,
    slurs, `Ped./*`, articulations, tempo markings. Score MIDI discards
    all of these. MIDI -> ABCX is therefore lossy; MusicXML -> ABCX is
    lossless w.r.t. the notational surface and is the only way to realise
    the "ABCX carries more information than score MIDI" core advantage
    discussed in EPR/README.md section 8.

CLI examples:
    # Single file:
    python3 xml_to_abcx.py input.musicxml -o input.abcx

    # Batch over a directory tree (discovers xml_score.musicxml files):
    python3 xml_to_abcx.py --batch \\
        /home/sy/2026/Music/data/audio_symbolic_alignment/asap-dataset \\
        --out-dir /home/sy/2026/Music/EPR/abcx_from_xml

    # Skip validation (keep ABC only; write .abc instead of .abcx):
    python3 xml_to_abcx.py input.musicxml --abc-only
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# --- Path wiring for the two external components -----------------------------

_HERE = Path(__file__).resolve().parent
_XML2ABC_DIR = _HERE / "xml2abc"
_ABCX_SCRIPTS_DIR = _HERE / "abcx" / "scripts"

for p in (_XML2ABC_DIR, _ABCX_SCRIPTS_DIR):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    import xml2abc  # type: ignore
except ImportError as e:
    raise SystemExit(
        f"Cannot import xml2abc from {_XML2ABC_DIR}. "
        "Run: git clone https://github.com/SpotlightKid/xml2abc "
        f"{_XML2ABC_DIR}"
    ) from e

try:
    from abc2abcx import to_standard_abcx, AbcError  # type: ignore
except ImportError as e:
    raise SystemExit(
        f"Cannot import abc2abcx from {_ABCX_SCRIPTS_DIR}. "
        "Check the path exists."
    ) from e


# ---------------------------------------------------------------------------
# xml2abc invocation
# ---------------------------------------------------------------------------

def _xml2abc_convert(xml_path: Path, out_dir: Path) -> Path:
    """Run xml2abc on `xml_path`, writing a .abc into `out_dir`.

    xml2abc writes `<stem>.abc` next to the output dir. We return the path.
    Stderr chatter (accidental fixups, empty voice skips) is suppressed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # xml2abc has a module-level `main()` driven by sys.argv. Invoke via
    # argv-swap so we stay in-process (much faster than subprocess for batches).
    old_argv = sys.argv
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.argv = [
            "xml2abc",
            "-o", str(out_dir),
            "-m", "2",           # emit %%MIDI directives (voice programs etc.)
            "-u",                # unfold simple repeats -> linear performance
            str(xml_path),
        ]
        # Swallow xml2abc's verbose output
        with open(os.devnull, "w") as devnull:
            sys.stdout = devnull
            sys.stderr = devnull
            try:
                xml2abc.main()
            except SystemExit:
                pass  # xml2abc may call sys.exit on some warnings
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # xml2abc uses the input stem: foo.musicxml -> foo.abc
    expected = out_dir / (xml_path.stem + ".abc")
    if not expected.exists():
        raise RuntimeError(f"xml2abc did not produce {expected}")
    return expected


# ---------------------------------------------------------------------------
# Post-processing: clean xml2abc output for abcjs compatibility
# ---------------------------------------------------------------------------
#
# The bundled abcjs (v6.1.9) used by the abcx plugin doesn't accept several
# constructs that xml2abc happily emits. Rather than fix xml2abc or upgrade
# abcjs, we strip / rewrite the offenders so the plugin renders cleanly in
# ABC mode (extension.js: analyzeAbc -> abcjs.parseOnly).
#
# Diagnostics removed by this pass (in priority order):
#   1. `$` linebreak markers (`I:linebreak $` directive + body `$` chars)
#   2. `[I:staff +N]` / `[I:staff -N]` cross-staff hints
#   3. Unsupported decorations (pedal, 8va/8vb, fermatafixed/proportional,
#      stemless, fine, courtesy, accidental-letter shorthand !_e!, !B2!, ...)
#
# Decorations that *are* recognised by abcjs and must be preserved:
#   - dynamics:    !p! !pp! !ppp! !pppp! !mp! !mf! !f! !ff! !fff! !ffff! !sfz!
#   - cresc/dim:   !crescendo(! !crescendo)! !diminuendo(! !diminuendo)!
#                  !<(! !<)! !>(! !>)!
#   - ornaments:   !trill! !trill(! !trill)! !turn! !mordent!
#                  !lowermordent! !uppermordent! !pralltriller!
#   - articulation:!accent! !>! !emphasis! !tenuto! !marcato!
#   - other:       !fermata! !wedge! !arpeggio! !segno! !coda!
#   - fingerings:  !0! !1! !2! !3! !4! !5!
# ---------------------------------------------------------------------------

import re as _re

_KEEP_DECORATIONS = frozenset({
    # dynamics
    "p", "pp", "ppp", "pppp", "f", "ff", "fff", "ffff", "mp", "mf", "sfz",
    # crescendo brackets
    "crescendo(", "crescendo)", "diminuendo(", "diminuendo)",
    "<(", "<)", ">(", ">)",
    # ornaments
    "trill", "trill(", "trill)", "turn", "mordent",
    "lowermordent", "uppermordent", "pralltriller",
    # articulation
    "accent", ">", "emphasis", "tenuto", "marcato",
    # other
    "fermata", "wedge", "arpeggio", "segno", "coda",
    # fingerings 0-5
    "0", "1", "2", "3", "4", "5",
})

# Pedal markings -> text annotation that abcjs renders harmlessly.
# Information is preserved in human-readable form for downstream EPR pipelines.
_PEDAL_REWRITE = {
    "ped": '"^Ped."',
    "Ped": '"^Ped."',
    "pedstart": '"^Ped."',
    "pedalstart": '"^Ped."',
    "ped(": '"^Ped."',
    "ped-up": '"^*"',
    "pedend": '"^*"',
    "pedalend": '"^*"',
    "ped)": '"^*"',
}

# Octave-shift decorations → native ABC decorations.
# The bundled abcjs has been patched to recognise !8va(! / !8va)! / !8vb(! / !8vb)!
# as ottava range markers, rendering them as dashed lines with labels above/below
# the staff and transposing playback pitch by ±1 octave.
_OCTAVE_REWRITE = {
    "8va(": "!8va(!",
    "8va)": "!8va)!",
    "8vb(": "!8vb(!",
    "8vb)": "!8vb)!",
    "ottava8va": "!8va(!",
    "ottava8vb": "!8vb(!",
}


# ---------------------------------------------------------------------------
# Ottava conversion: handle 8va/8vb decorations and transpose notes within
# range to engraved (display) position
# ---------------------------------------------------------------------------

_NOTE_PITCH_RE = _re.compile(r"((?:\^{1,2}|_{1,2}|=)?)([A-Ga-gxyzZ])([,']*)")


def _shift_pitch_octave(letter: str, mods: str, delta: int) -> tuple:
    """Shift an ABC pitch letter + mods by `delta` octaves.

    ABC octave convention: `C,` = C2, `C` = C3, `c` = C4 (middle C),
    `c'` = C5, `c''` = C6. Each `,` lowers by one octave; each `'` raises.
    """
    if letter not in "ABCDEFGabcdefg":
        return letter, mods  # rests (x, y, z) — no pitch to transpose
    apos = mods.count("'")
    commas = mods.count(",")
    base_octave = 3 if letter.isupper() else 4
    octave = base_octave - commas + apos
    new_octave = octave + delta
    pitch = letter.upper()
    if new_octave <= 3:
        return pitch, "," * (3 - new_octave)
    return pitch.lower(), "'" * (new_octave - 4)


def _transpose_notes_flat(text: str, delta: int) -> str:
    """Transpose all pitches inside `text` by `delta` octaves.
    Used for chord `[...]` and grace `{...}` interiors."""
    if delta == 0:
        return text
    out = []
    i = 0
    n = len(text)
    while i < n:
        m = _NOTE_PITCH_RE.match(text, i)
        if m and m.group(2) in "ABCDEFGabcdefg":
            accidental, letter, mods = m.group(1), m.group(2), m.group(3)
            new_letter, new_mods = _shift_pitch_octave(letter, mods, delta)
            out.append(accidental + new_letter + new_mods)
            i = m.end()
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _process_ottava_line(line: str, state: int) -> tuple:
    """Process one music line. `state` = 0 (none), -1 (8va active), +1 (8vb
    active). Notes within an active range are transposed to engraved
    (display) position. Returns (new_line, new_state).

    Outputs native ABC decorations: !8va(! / !8va)! / !8vb(! / !8vb)!
    Also accepts legacy text annotation input ("^8va~" / "^8vb~" / "^~")
    for backwards compatibility and rewrites them to native form.
    """
    out = []
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]

        # Text annotation "..." (legacy input from older _OCTAVE_REWRITE)
        if ch == '"':
            end = line.find('"', i + 1)
            if end < 0:
                out.append(line[i:])
                break
            text_content = line[i + 1:end]
            if text_content == "^8va~":
                if state == 0:
                    out.append("!8va(!")
                    state = -1
                i = end + 1
                continue
            if text_content == "^8vb~":
                if state == 0:
                    out.append("!8vb(!")
                    state = +1
                i = end + 1
                continue
            if text_content == "^~":
                if state != 0:
                    if state == -1:
                        out.append("!8va)!")
                    else:
                        out.append("!8vb)!")
                    state = 0
                # stray close — drop
                i = end + 1
                continue
            out.append(line[i:end + 1])
            i = end + 1
            continue

        # Native decoration !...!
        if ch == '!':
            end = line.find('!', i + 1)
            if end < 0:
                out.append(line[i:])
                break
            deco = line[i + 1:end]
            if deco == "8va(":
                if state == 0:
                    out.append("!8va(!")
                    state = -1
                i = end + 1
                continue
            if deco == "8va)":
                if state == -1:
                    out.append("!8va)!")
                    state = 0
                # stray close — drop
                i = end + 1
                continue
            if deco == "8vb(":
                if state == 0:
                    out.append("!8vb(!")
                    state = +1
                i = end + 1
                continue
            if deco == "8vb)":
                if state == +1:
                    out.append("!8vb)!")
                    state = 0
                # stray close — drop
                i = end + 1
                continue
            out.append(line[i:end + 1])
            i = end + 1
            continue

        # Inline field [X:...] — pass through, no transposition
        if ch == '[' and i + 2 < n and _re.match(r"[A-Za-z]:", line[i + 1:i + 3]):
            end = line.find(']', i + 1)
            if end < 0:
                out.append(line[i:])
                break
            out.append(line[i:end + 1])
            i = end + 1
            continue

        # Chord [...]
        if ch == '[':
            end = line.find(']', i + 1)
            if end < 0:
                out.append(line[i:])
                break
            inner = line[i + 1:end]
            out.append('[' + _transpose_notes_flat(inner, state) + ']')
            i = end + 1
            continue

        # Grace {...}
        if ch == '{':
            end = line.find('}', i + 1)
            if end < 0:
                out.append(line[i:])
                break
            inner = line[i + 1:end]
            out.append('{' + _transpose_notes_flat(inner, state) + '}')
            i = end + 1
            continue

        # Pitched note
        m = _NOTE_PITCH_RE.match(line, i)
        if m and m.group(2) in "ABCDEFGabcdefg" and state != 0:
            accidental, letter, mods = m.group(1), m.group(2), m.group(3)
            new_letter, new_mods = _shift_pitch_octave(letter, mods, state)
            out.append(accidental + new_letter + new_mods)
            i = m.end()
            continue
        if m:
            out.append(m.group(0))
            i = m.end()
            continue

        # Default
        out.append(ch)
        i += 1

    return "".join(out), state


def _convert_ottava_to_native(text: str) -> str:
    """Transpose notes within each 8va/8vb range to engraved (display) position.

    Accepts two input forms (mixed within one file is fine):
      - "^8va~" / "^8vb~" text annotations with "^~" closing markers
        (legacy form from older _OCTAVE_REWRITE, for backwards compatibility)
      - !8va(! / !8va)! / !8vb(! / !8vb)! native decorations
        (xml2abc raw output or _OCTAVE_REWRITE output)

    Output form is always `!8va(!` / `!8va)!` / `!8vb(!` / `!8vb)!` native
    decorations. Within each range all pitches are shifted by one octave
    (8va lowers, 8vb raises) so the rendered score matches the original
    engraving: notes appear at their written position under the ottava line.

    State is tracked per-voice across line boundaries (an ottava may span
    multiple rendered lines).
    """
    lines = text.split("\n")
    out_lines = []
    voice_state: dict = {}
    current_voice = "1"
    in_body = False

    for line in lines:
        s = line.strip()
        if not in_body:
            out_lines.append(line)
            if s.startswith("K:"):
                in_body = True
            continue

        v_match = _re.match(r"^V:\s*(\S+)", s)
        if v_match:
            current_voice = v_match.group(1)
            voice_state.setdefault(current_voice, 0)
            out_lines.append(line)
            continue

        if not s or s.startswith("%") or _re.match(r"^[A-Za-z]:", s):
            out_lines.append(line)
            continue

        state = voice_state.get(current_voice, 0)
        new_line, new_state = _process_ottava_line(line, state)
        voice_state[current_voice] = new_state
        out_lines.append(new_line)

    return "\n".join(out_lines)


def _rewrite_decoration(match: "_re.Match") -> str:
    body = match.group(1)
    if body in _KEEP_DECORATIONS:
        return match.group(0)
    if body in _PEDAL_REWRITE:
        return _PEDAL_REWRITE[body]
    if body in _OCTAVE_REWRITE:
        return _OCTAVE_REWRITE[body]
    if body == "fermatafixed" or body == "fermataproportional":
        return "!fermata!"
    if body == "fz":
        return "!sfz!"
    # Drop everything else silently. The xml2abc-emitted "spelt-out chord"
    # and "letter-shorthand" decorations (!cBAG!, !aeg!, !_e!, !B2!, ...) are
    # noise from MusicXML directives we can't faithfully render in ABC, and
    # the source MusicXML stays as the ground-truth artefact.
    return ""


_DECO_RE = _re.compile(r"!([^!\n]+)!")
_LINEBREAK_DIRECTIVE_RE = _re.compile(r"^I:linebreak\s+\$\s*\n", _re.MULTILINE)
_STAFF_HINT_RE = _re.compile(r"\[I:staff\s*[+-]?\d+\]\s*")
# U: macro that maps to a decoration (whether the target was stripped or not)
_U_MACRO_RE = _re.compile(r"^U:([A-Za-z])\s*=.*\n", _re.MULTILINE)
# Grace-note chord: `{/[CE]}` / `{[CE]}` -> strip the `[]` so abcjs parses a
# sequence of grace pitches instead of trying to open a chord. Run multiple
# times to handle nested chords inside graces.
_GRACE_BRACKET_RE = _re.compile(r"(\{[^{}]*?)\[([^\[\]]*?)\]")
# Decoration followed immediately by inline field `[Q:...]` or `[M:...]` etc.
_DECO_THEN_INLINE_FIELD_RE = _re.compile(
    r"(!(?:[^!\n]+)!)(\[[A-Za-z]:[^\]\n]+\])"
)
# Run of inline fields and quoted text annotations at one position.
_INLINE_FIELD_RUN_RE = _re.compile(
    r"((?:\[[A-Za-z]:[^\]\n]+\]|\"[^\"\n]+\"){2,})"
)
# Grace-note group `{...}` -- abcjs's grace parser doesn't accept embedded
# `!deco!` markers or articulation dots; strip them so the pitches survive.
_GRACE_GROUP_RE = _re.compile(r"\{[^{}\n]+\}")
# Unclosed grace `{...` at end of a music line (xml2abc occasionally emits a
# grace that spans a bar line / key change, which abcjs can't parse).
_UNCLOSED_GRACE_RE = _re.compile(r"\{[^{}\n|]*(?=\||$)")
# Grace group immediately followed by an inline field `[Q:...]` / `[M:...]`:
# abcjs tries to continue parsing the field as a chord and fails.
_GRACE_THEN_INLINE_FIELD_RE = _re.compile(
    r"(\{[^{}\n]*\})(\[[A-Za-z]:[^\]\n]+\])"
)
# Big tuplet prefix `(N:M:K` -- abcjs supports `(N` (N in 2..9) cleanly but
# barfs on multi-arg tuplets that nest, have ratio (1:1:n), or use double-
# digit counts. Strip the entire `(p:q:r` form. We keep simple `(N` notation.
_FULL_TUPLET_RE = _re.compile(r"\(\d+:\d+(?::\d+)?")
# Bare big-N tuplet `(10`, `(31`, etc.
_BARE_BIG_TUPLET_RE = _re.compile(r"\((\d{2,})(?!\d)")
# Chord that contains an `x` (invisible rest) -- abcjs rejects them.
_CHORD_WITH_X_RE = _re.compile(r"\[([^\[\]\n]*x[^\[\]\n]*)\]")
# Stacked %%score braces  `%%score { { (...) } }` -- abcjs doesn't nest braces.
_NESTED_SCORE_BRACE_RE = _re.compile(r"^(%%score\s*)\{\s*\{(.*)\}\s*\}\s*$",
                                       _re.MULTILINE)


def _strip_chord_x(match: "_re.Match") -> str:
    inside = match.group(1)
    # Remove `x` plus any duration suffix that immediately follows it.
    cleaned = _re.sub(r"x\d*\/*\d*", "", inside).strip()
    if not cleaned:
        return "x"           # empty chord -> single invisible rest
    return f"[{cleaned}]"


def _reorder_inline_run(match: "_re.Match") -> str:
    """Reorder `[F:...]"^x"[F:...]"^y"` so all inline fields come first."""
    run = match.group(1)
    fields = []
    annotations = []
    i = 0
    n = len(run)
    while i < n:
        ch = run[i]
        if ch == "[":
            end = run.find("]", i)
            if end < 0:
                fields.append(run[i:])
                break
            fields.append(run[i:end + 1])
            i = end + 1
        elif ch == '"':
            end = run.find('"', i + 1)
            if end < 0:
                annotations.append(run[i:])
                break
            annotations.append(run[i:end + 1])
            i = end + 1
        else:
            i += 1
    return "".join(fields) + "".join(annotations)


# ---------------------------------------------------------------------------
# Voice clef correction (step 17 helper)
# ---------------------------------------------------------------------------
# abcjs v6.1.9 resets each voice to its DECLARED clef (from `V:n treble|bass`)
# at the start of every visual line, overriding any prior inline `[K:...]`
# switches.  A voice declared `bass` will show bass clef on every new line
# even when `[K:treble]` was active.  We scan each voice's music for the
# predominant clef and rewrite the voice declaration to match.

_VOICE_DECL_RE = _re.compile(
    r"^(V:\s*(\S+)\s+)(treble|bass)(.*)$"
)
_K_CLEF_RE = _re.compile(r"\[K:\s*(treble|bass)\]")
_SCORE_BRACE_RE = _re.compile(r"%%score\s*\{([^}]*)\}")


def _parse_score_groups(text: str) -> dict[str, str]:
    """Parse %%score braces and return {voice_id: 'treble'|'bass'}.
    First group → treble, second group → bass (ABCX spec default)."""
    result: dict[str, str] = {}
    for m in _SCORE_BRACE_RE.finditer(text):
        inner = m.group(1)
        groups = inner.split("|")
        for group_idx, group in enumerate(groups):
            group = group.strip()
            if group.startswith("(") and group.endswith(")"):
                group = group[1:-1]
            default_clef = "treble" if group_idx == 0 else "bass"
            for tok in group.split():
                vid = _re.sub(r"^v?(\d+)", r"V\1", tok.strip(), flags=_re.IGNORECASE)
                if vid:
                    result[vid] = default_clef
    return result


def _correct_voice_clefs(text: str) -> str:
    """Rewrite `V:n bass|treble` declarations to match the predominant
    inline clef used by each voice's music content. If inline switches
    are tied or absent, fall back to the %%score group default
    (first group = treble, second = bass per ABCX spec)."""
    lines = text.split("\n")

    voice_lines: dict[str, list[str]] = {}
    current_voice: str | None = None
    for line in lines:
        m = _re.match(r"^V:\s*(\S+)", line.strip())
        if m:
            current_voice = m.group(1)
            voice_lines.setdefault(current_voice, []).append(line)
            continue
        if current_voice and line.strip() and not line.startswith("%%"):
            voice_lines[current_voice].append(line)

    # Parse %%score group defaults.
    score_defaults = _parse_score_groups(text)

    clef_map: dict[str, str] = {}
    for voice_id, vlines in voice_lines.items():
        treble = 0
        bass = 0
        for ln in vlines:
            if _re.match(r"^(V:|%%)", ln.strip()):
                continue
            for cm in _K_CLEF_RE.finditer(ln):
                if cm.group(1) == "treble":
                    treble += 1
                else:
                    bass += 1
        if treble > bass and treble >= 2:
            clef_map[voice_id] = "treble"
        elif bass > treble and bass >= 2:
            clef_map[voice_id] = "bass"
        elif voice_id in score_defaults:
            # Tied, zero, or weak signal — use %%score group default.
            clef_map[voice_id] = score_defaults[voice_id]

    if not clef_map:
        return text

    # Step 2: rewrite voice declarations.
    def _rewrite_decl(line: str) -> str:
        m = _VOICE_DECL_RE.match(line.strip())
        if m:
            vid = m.group(2)
            new_clef = clef_map.get(vid)
            if new_clef and new_clef != m.group(3):
                return "V:" + vid + " " + new_clef + m.group(4)
        return line

    text = "\n".join(_rewrite_decl(ln) for ln in text.split("\n"))

    # Step 3: strip redundant inline clef switches. Track the current
    # voice as we iterate through sequential voice blocks in the output.
    current_voice: str | None = None
    stripped_lines = []
    for line in text.split("\n"):
        vm = _re.match(r"^(V:\s*(\S+))(.*)$", line.strip())
        if vm:
            current_voice = vm.group(2)
            # Also strip from the V: declaration line itself.
            new_clef = clef_map.get(current_voice)
            if new_clef:
                line = _re.sub(r"\[K:\s*" + new_clef + r"\]", "", line)
            stripped_lines.append(line)
            continue
        new_clef = clef_map.get(current_voice) if current_voice else None
        if new_clef:
            line = _re.sub(r"\[K:\s*" + new_clef + r"\]", "", line)
        stripped_lines.append(line)

    return "\n".join(stripped_lines)


def clean_for_abcjs(abc_text: str) -> str:
    """Post-process xml2abc output so abcjs (v6.1.9) parses without warnings."""
    text = abc_text

    # 1. Remove the I:linebreak $ prelude directive.
    text = _LINEBREAK_DIRECTIVE_RE.sub("", text)

    # 2. Strip standalone `$` linebreak markers in the body.
    def _strip_dollar(line: str) -> str:
        if line.startswith(("X:", "T:", "M:", "L:", "Q:", "K:", "V:", "U:",
                            "W:", "I:", "P:", "%%", "%")):
            return line
        out = []
        i = 0
        in_quote = False
        while i < len(line):
            ch = line[i]
            if ch == '"':
                in_quote = not in_quote
                out.append(ch)
                i += 1
                continue
            if not in_quote and ch == "$":
                if i + 1 < len(line) and line[i + 1] == " ":
                    i += 2
                else:
                    i += 1
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    text = "\n".join(_strip_dollar(ln) for ln in text.split("\n"))

    # 3. Drop cross-staff hints `[I:staff +1]`, `[I:staff -1]`, etc.
    text = _STAFF_HINT_RE.sub("", text)

    # 4. Strip decorations and non-pitch characters from grace-note groups.
    #    abcjs's grace parser only accepts pitch + accidental + octave/duration,
    #    and rejects `!deco!`, staccato `.`, and shorthand deco letters like
    #    `P` (uppermordent), `T` (trill), `H` (fermata), etc. that are legal
    #    at body position but not inside `{...}`.
    _GRACE_SHORTHAND_DECO = frozenset("PMRSHTLOuv")

    def _clean_grace(m: "_re.Match") -> str:
        inner = m.group(0)[1:-1]
        # Remove !deco! markers.
        inner = _DECO_RE.sub("", inner)
        # Drop staccato/articulation dots.
        inner = inner.replace(".", "")
        # Drop shorthand decoration letters that abcjs can't parse inside grace.
        inner = "".join(c for c in inner
                        if c not in _GRACE_SHORTHAND_DECO)
        return "{" + inner + "}"

    text = _GRACE_GROUP_RE.sub(_clean_grace, text)

    # 4b. Drop any grace group left unclosed on a music line (e.g. `... {a |`
    #     when xml2abc spans a grace across a bar line / voice change).
    def _drop_unclosed_grace(line: str) -> str:
        if line.startswith(("%%", "%", "X:", "T:", "M:", "L:", "Q:", "K:",
                            "V:", "U:", "W:", "I:", "P:")):
            return line
        return _UNCLOSED_GRACE_RE.sub("", line)

    text = "\n".join(_drop_unclosed_grace(ln) for ln in text.split("\n"))

    # 5. Rewrite / drop unsupported decorations.
    text = _DECO_RE.sub(_rewrite_decoration, text)

    # 5b. Normalise 8va/8vb: convert "^8va~"/"^8vb~" text annotations to
    # native !8va(!/!8vb(! decorations AND transpose notes within each
    # range down/up one octave so they render at engraved (display) pitch.
    # Handles both legacy text form and current native form as input.
    text = _convert_ottava_to_native(text)

    # 6. Drop *all* U: macro definitions (e.g. `U:s=!stemless!`). Their target
    #    decorations are unsupported and the body uses of the macro letter
    #    (`sC`, `sB,2`) leave abcjs warning either way; we strip both the
    #    definition AND the prefix usages in step 7.
    macro_letters = set(m.group(1) for m in _U_MACRO_RE.finditer(text))
    text = _U_MACRO_RE.sub("", text)

    # 7. Strip `<letter>` prefix usages of those macros from the body. Only
    #    apply on music-body lines (skip header/inline-field/directive lines)
    #    and only when the letter precedes a note pitch / accidental / chord
    #    open AND is not itself inside a `!...!` decoration or `"..."` text
    #    annotation (otherwise we'd e.g. clip the `s` out of `!sfz!`).
    if macro_letters:
        _HDR = ("%%", "%", "X:", "T:", "M:", "L:", "Q:", "K:", "V:", "U:",
                "W:", "I:", "P:", "R:", "C:", "N:", "O:", "Z:", "S:", "H:",
                "B:", "D:", "F:", "G:")

        def _strip_macro_prefix(line: str) -> str:
            if line.startswith(_HDR):
                return line
            # Mask out !...! decorations and "..." annotations so the prefix
            # patterns can't match inside them.
            spans = []
            for m in _re.finditer(r"!(?:[^!\n]+)!|\"[^\"\n]*\"", line):
                spans.append((m.start(), m.end()))

            def in_span(i: int) -> bool:
                for s, e in spans:
                    if s <= i < e:
                        return True
                return False

            out_chars = list(line)
            i = 0
            while i < len(out_chars):
                ch = out_chars[i]
                if ch in macro_letters and not in_span(i):
                    # Verify lookbehind/lookahead.
                    prev = out_chars[i - 1] if i > 0 else ""
                    nxt = out_chars[i + 1] if i + 1 < len(out_chars) else ""
                    if (prev.isalpha()):
                        i += 1
                        continue
                    if nxt and (nxt in "ABCDEFGabcdefg_=^.["):
                        out_chars[i] = ""
                        # don't increment - re-check next char
                        i += 1
                        continue
                i += 1
            return "".join(out_chars)

        text = "\n".join(_strip_macro_prefix(ln) for ln in text.split("\n"))

    # 8. Grace-note chord `{/[CE]}` -> `{/CE}`. abcjs can't open a chord
    #    inside a grace-note group. Apply repeatedly for nested cases.
    prev = None
    while prev != text:
        prev = text
        text = _GRACE_BRACKET_RE.sub(r"\1\2", text)

    # 9/10. Fixpoint: (a) reorder `!deco![X:...]` -> `[X:...]!deco!`;
    #       (b) reorder `{grace}[X:...]` -> `[X:...]{grace}`;
    #       (c) reorder runs of `[X:...]` / `"..."` so fields precede quoted
    #       annotations. Step (c) can create new grace/deco-before-field
    #       adjacencies that (a)/(b) then repair, so we loop until stable.
    prev = None
    while prev != text:
        prev = text
        text = _DECO_THEN_INLINE_FIELD_RE.sub(r"\2\1", text)
        text = _GRACE_THEN_INLINE_FIELD_RE.sub(r"\2\1", text)
        text = _INLINE_FIELD_RUN_RE.sub(_reorder_inline_run, text)

    # 11. Strip multi-arg tuplet prefixes `(p:q:r` and big bare tuplets
    #     `(10`, `(31`. abcjs accepts `(2..(9` only and doesn't allow nested
    #     tuplets; xml2abc emits both. Dropping the prefix preserves the
    #     pitches but loses the tuplet ratio -- acceptable for preview.
    text = _FULL_TUPLET_RE.sub("", text)
    text = _BARE_BIG_TUPLET_RE.sub("", text)

    # 12. Strip `x` from chord brackets `[xx]`, `[xCE]`, etc. abcjs rejects
    #     `x` inside `[...]`. Empty residual chords collapse to a single `x`.
    text = _CHORD_WITH_X_RE.sub(_strip_chord_x, text)

    # 12b. Replace invisible rest `x` with visible rest `z`. abcjs v6.1.9 has
    #      a bug: `x` elements lack pitch/Y-position data, so their
    #      `top`/`bottom` stay undefined. When `undefined` is used in
    #      `Math.max` for voice height calculation, NaN propagates through
    #      the entire SVG viewBox height, making the rendering invisible.
    #      `z` (visible rest) has proper staff positioning.

    def _replace_invisible_rests(line: str) -> str:
        if line.startswith(("%%", "%", "X:", "T:", "M:", "L:", "Q:", "K:",
                            "V:", "U:", "W:", "I:", "P:", "R:", "C:", "N:",
                            "O:", "Z:", "S:", "H:", "B:", "D:", "F:", "G:")):
            return line
        # Mask decorations, annotations, and chord brackets so we don't touch
        # `x` inside them (e.g. text like `"8va~"` or `!sfz!`).
        spans = []
        for m in _re.finditer(r"!(?:[^!\n]+)!|\"[^\"\n]*\"|\[[^\]\n]*\]", line):
            spans.append((m.start(), m.end()))

        def in_span(i: int) -> bool:
            for s, e in spans:
                if s <= i < e:
                    return True
            return False

        out = []
        for i, ch in enumerate(line):
            if ch == "x" and not in_span(i):
                # `x` in ABC music is always an invisible rest (never a pitch
                # letter). Replace it with `z` so abcjs can position it on
                # the staff.
                out.append("z")
            else:
                out.append(ch)
        return "".join(out)

    text = "\n".join(_replace_invisible_rests(ln) for ln in text.split("\n"))

    # 13. Flatten nested `%%score { { (...) } }` to `%%score { (...) }`,
    #     and drop ALL braces from %%score lines whose nesting we can't
    #     express in abcjs (e.g. `%%score { { A } B }` -- abcjs rejects
    #     mixed nesting; stripping braces only loses the visual grouping).
    text = _NESTED_SCORE_BRACE_RE.sub(r"\1{\2}", text)

    def _flatten_score(line: str) -> str:
        if not line.startswith(("%%score", "%%staves")):
            return line
        # If still contains more than one `{`, flatten by removing all braces.
        if line.count("{") > 1:
            return line.replace("{", "").replace("}", "")
        return line

    text = "\n".join(_flatten_score(ln) for ln in text.split("\n"))

    # 13b. abcjs v6.1.9 has a bug parsing `>X-)` (snap-target tied + slur
    #      close) when X has no explicit duration, even across intervening
    #      decorations like `_C>!>)!D-)`. Detect any `-)` on a music line
    #      whose last note has no digit and the token is reachable from a
    #      `>` snap earlier in the same bar; insert an explicit `1` before
    #      `-)` so the parser accepts the construct. The rendered duration
    #      is unchanged (default IS unit length).
    _NOTE_BEFORE_DASHCLOSE_RE = _re.compile(
        r"([\^_=]{0,3}[A-Ga-g][,']*)-\)"
    )

    def _fix_dashclose_on_line(line: str) -> str:
        if line.startswith(("%%", "%", "X:", "T:", "M:", "L:", "Q:", "K:",
                            "V:", "U:", "W:", "I:", "P:")):
            return line

        def _repl(m: "_re.Match") -> str:
            note = m.group(1)
            # Is there a bare `>` snap earlier on this line (excluding
            # `>` inside `!...!` or `"..."`)?
            upto = line[: m.start()]
            # Strip decorations / annotations from `upto`.
            cleaned = _re.sub(r"!(?:[^!\n]+)!|\"[^\"\n]*\"", "", upto)
            if ">" in cleaned:
                return f"{note}1-)"
            return m.group(0)

        return _NOTE_BEFORE_DASHCLOSE_RE.sub(_repl, line)

    text = "\n".join(_fix_dashclose_on_line(ln) for ln in text.split("\n"))

    # 13c. Strip slur-close `)` from inside grace groups (xml2abc occasionally
    #      emits `{=e-g-)}` where the slur belongs to the surrounding context).
    #      Skip `%%score` / `%%staves` lines whose outer `{...}` is a brace.
    def _strip_grace_slur_close(line: str) -> str:
        if line.startswith(("%%score", "%%staves")):
            return line
        prev = None
        while prev != line:
            prev = line
            line = _re.sub(r"(\{[^{}\n]*?)\)([^{}\n]*\})", r"\1\2", line)
        return line

    text = "\n".join(_strip_grace_slur_close(ln) for ln in text.split("\n"))

    # 13d. Drop orphan `}` on music lines (left over after step 4b dropped
    #      an unclosed grace `{...` that originally had its `}` on this line).
    def _drop_orphan_brace(line: str) -> str:
        if line.startswith(("%%", "%", "X:", "T:", "M:", "L:", "Q:", "K:",
                            "V:", "U:", "W:", "I:", "P:")):
            return line
        out = []
        depth = 0
        for ch in line:
            if ch == "{":
                depth += 1
                out.append(ch)
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    out.append(ch)
                # else: drop orphan
            else:
                out.append(ch)
        return "".join(out)

    text = "\n".join(_drop_orphan_brace(ln) for ln in text.split("\n"))

    # 14. Normalise `x` invisible-rest and `z` visible-rest durations.
    #     xml2abc emits things like `x10`, `x/15`, `z13/2`, `z/40` from
    #     non-power-of-2 tuplet contexts and very fine subdivisions
    #     (`x/8` against `L:1/16` -> 1/128 note); abcjs (v6.1.9) rejects
    #     anything finer than 1/64. Replace any non-representable rest
    #     duration with bare `x`/`z` (default unit length). Rest timing may
    #     be slightly off but preserving the rest is more important than
    #     exact subdivision for rendering.
    def _representable_after_L(num: int, den: int, l_num: int,
                                 l_den: int) -> bool:
        if num <= 0 or den <= 0:
            return False
        from math import gcd
        # effective fraction of whole: (num/den) * (l_num/l_den)
        e_num = num * l_num
        e_den = den * l_den
        g = gcd(e_num, e_den)
        e_num, e_den = e_num // g, e_den // g
        # denominator must be a power of 2 and at most 64 (max 64th note)
        if e_den & (e_den - 1):
            return False
        if e_den > 64:
            return False
        # numerator (after stripping factors of 2) must be in standard set
        n = e_num
        while n > 1 and n % 2 == 0:
            n //= 2
        return n in (1, 3, 7, 15, 31)

    # Discover the unit-note-length L: from the prelude (default 1/8 per ABC).
    l_match = _re.search(r"^L:\s*(\d+)\s*/\s*(\d+)", text, _re.MULTILINE)
    l_num = int(l_match.group(1)) if l_match else 1
    l_den = int(l_match.group(2)) if l_match else 8

    def _make_normaliser(rest_ch: str):
        def _normalise(match: "_re.Match") -> str:
            full = match.group(0)
            num_s = match.group("num")
            den_s = match.group("den")
            if num_s is None and den_s is None and "/" not in full:
                return full   # bare rest char
            n = int(num_s) if num_s else 1
            d = int(den_s) if den_s else 2  # `x/` alone means `x/2`
            if _representable_after_L(n, d, l_num, l_den):
                return full
            return rest_ch
        return _normalise

    text = _re.sub(
        r"x(?P<num>\d+)?(?:/(?P<den>\d+)?)?",
        _make_normaliser("x"),
        text,
    )
    text = _re.sub(
        r"z(?P<num>\d+)?(?:/(?P<den>\d+)?)?",
        _make_normaliser("z"),
        text,
    )

    # 14b. Normalise pitch-note durations whose effective length isn't
    #      representable in abcjs (e.g. `b/3` in L:1/16 -> 1/48). After
    #      step 11 stripped tuplet brackets we're left with bare `/3`,
    #      `/5`, `/15` orphans. Snap the denominator down to the next
    #      power-of-2 so the duration parses; this loses tuplet ratio but
    #      keeps the pitch and approximate timing.
    _PITCH_DUR_RE = _re.compile(
        r"(?P<note>(?:[\^_=]{0,3}[A-Ga-g][,']*))"
        r"(?P<num>\d+)?(?:/(?P<den>\d+)?)?"
    )

    def _snap_pow2(n: int) -> int:
        # Largest power of two <= n; clamp to [1, 64].
        if n <= 1:
            return 1
        p = 1
        while (p << 1) <= n and (p << 1) <= 64:
            p <<= 1
        return p

    def _normalise_pitch(match: "_re.Match") -> str:
        note = match.group("note")
        num_s = match.group("num")
        den_s = match.group("den")
        full = match.group(0)
        if num_s is None and den_s is None and "/" not in full:
            return full
        n = int(num_s) if num_s else 1
        d = int(den_s) if den_s else 2
        if _representable_after_L(n, d, l_num, l_den):
            return full
        # Snap numerator down to power-of-2 (so 13/8 -> 8/8 = 1).
        n2 = _snap_pow2(n)
        d2 = _snap_pow2(d)
        if _representable_after_L(n2, d2, l_num, l_den):
            if n2 == 1 and d2 == 1:
                return note
            if d2 == 1:
                return f"{note}{n2}"
            if n2 == 1:
                return f"{note}/{d2}"
            return f"{note}{n2}/{d2}"
        # Fallback: drop the duration entirely.
        return note

    text = _PITCH_DUR_RE.sub(_normalise_pitch, text)

    # 15. Collapse stretches of whitespace that the rewrites may have left.
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r" *\| *", " | ", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)

    # 16. Correct voice clef declarations. This MUST run BEFORE
    # _align_voice_lines (step 17) because alignment redistributes measures
    # across voice blocks, moving [K:...] inline switches between voices.
    # We need to scan clef switches in the ORIGINAL voice-to-line mapping.
    text = _correct_voice_clefs(text)

    # 17. Re-wrap voice blocks so all voices have the SAME number of lines.
    #     abcjs uses source-code line breaks to determine visual line breaks.
    #     xml2abc often emits V:1 with 1 measure/line and V:2 with 5-8
    #     measures/line (because of different L: values), which causes
    #     misaligned rendering. We parse measures per voice, find the max
    #     line count, and re-distribute measures evenly.
    text = _align_voice_lines(text)

    return text


# ---------------------------------------------------------------------------
# Voice line alignment (step 16 helper)
# ---------------------------------------------------------------------------

def _split_measures(voice_lines: list) -> list:
    """Split a list of voice music lines into a list of individual measures.

    Each measure is a string like `  notes | %1` or `notes |`.
    """
    measures = []
    for line in voice_lines:
        # Strip trailing comment.
        comment_idx = line.rfind(" %")
        comment = ""
        if comment_idx >= 0:
            comment = line[comment_idx:]
            line = line[:comment_idx]
        # Split on `|`.
        parts = line.split("|")
        for j, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            suffix = " |" if j < len(parts) - 1 else ""
            if comment and j == len(parts) - 1:
                suffix += comment
            measures.append(part + suffix)
    return measures


def _realign_voice_lines(voice_lines: list, target_lines: int) -> list:
    """Re-wrap a voice's measures into exactly `target_lines` text lines."""
    measures = _split_measures(voice_lines)
    if not measures or target_lines <= 0:
        return voice_lines
    n = len(measures)
    if n <= target_lines:
        # Already fewer measures than target lines -- keep 1 per line.
        return [m for m in measures]
    # Distribute measures evenly.
    result = []
    measures_per_line = n // target_lines
    remainder = n % target_lines
    idx = 0
    for i in range(target_lines):
        count = measures_per_line + (1 if i < remainder else 0)
        chunk = measures[idx: idx + count]
        idx += count
        result.append(" ".join(chunk))
    return result


def _align_voice_lines(text: str) -> str:
    """Re-wrap all voice blocks in an ABC tune to have matching line counts."""
    lines = text.split("\n")

    # 1) Find the first "bare" V:<id> line (no attributes). Prelude voice
    #    declarations look like `V:1 treble nm="Piano"`; the ones that start
    #    music blocks are bare `V:1`.
    music_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        m_v = _re.match(r"^V:\s*(\S+)\s*(.*)$", stripped)
        if m_v:
            rest = m_v.group(2).strip()
            # Bare V:<id> = start of a music block.
            if not rest:
                music_start = i
                break
        # Music content with `|` before any bare V: -- also marks start.
        if "|" in stripped and not stripped.startswith("%") and music_start is None:
            # Find the preceding V: line if any.
            for j in range(i - 1, -1, -1):
                if _re.match(r"^V:\s*\S+", lines[j].strip()):
                    music_start = j
                    break
            if music_start is None:
                music_start = i
            break

    if music_start is None:
        return text

    # 2) Collect voice blocks starting from music_start.
    voice_blocks = []
    i = music_start
    while i < len(lines):
        line = lines[i].strip()
        m = _re.match(r"^V:\s*(\S+)", line)
        if m:
            voice_id = m.group(1)
            start = i
            music = [lines[i]]  # include the V: declaration
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                # Another voice declaration -- end of this block.
                if _re.match(r"^V:\s*\S+", nxt):
                    break
                # Voice-specific directives (keep as part of voice).
                if nxt.startswith(("%%MIDI", "%%voice")):
                    music.append(lines[i])
                    i += 1
                    continue
                # Skip %% directives between voices.
                if nxt.startswith("%%"):
                    i += 1
                    continue
                # Non-empty, non-directive line = music content.
                if nxt:
                    music.append(lines[i])
                i += 1
            if len(music) > 1:  # has actual music
                voice_blocks.append((start, voice_id, music))
        else:
            i += 1

    if len(voice_blocks) < 2:
        return text

    # 3) Find the max number of MUSIC lines (excluding V: declaration).
    max_music = max(len(music) - 1 for _, _, music in voice_blocks)
    if max_music <= 1:
        return text

    # 4) Re-wrap each voice's MUSIC lines to have the same count.
    new_blocks = {}
    for start, voice_id, music in voice_blocks:
        music_lines = music[1:]  # skip V: declaration
        wrapped = _realign_voice_lines(music_lines, max_music)
        new_blocks[start] = [music[0]] + wrapped  # re-add V: declaration

    # 5) Rebuild text, replacing old voice blocks.
    skip_indices = set()
    for start, _vid, music in voice_blocks:
        for j in range(1, len(music)):
            skip_indices.add(start + j)

    result = []
    for i, line in enumerate(lines):
        if i in skip_indices:
            continue
        if i in new_blocks:
            result.extend(new_blocks[i])
        else:
            result.append(line)

    return "\n".join(result)


# ---------------------------------------------------------------------------
# End-to-end conversion
# ---------------------------------------------------------------------------

def _strip_harmony_nodes(xml_path: Path, out_dir: Path) -> Path:
    """Write a copy of `xml_path` with MusicXML `<harmony>` nodes removed."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def _remove_harmony(xml_bytes: bytes) -> bytes:
        root = ET.fromstring(xml_bytes)
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag.rsplit("}", 1)[-1] == "harmony":
                    parent.remove(child)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    if xml_path.suffix.lower() == ".mxl":
        out_path = out_dir / xml_path.name
        with zipfile.ZipFile(xml_path, "r") as zin, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            xml_names = [
                n for n in zin.namelist()
                if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF/")
            ]
            main_xml = xml_names[0] if xml_names else None
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == main_xml:
                    data = _remove_harmony(data)
                zout.writestr(info, data)
        return out_path

    out_path = out_dir / xml_path.name
    out_path.write_bytes(_remove_harmony(xml_path.read_bytes()))
    return out_path


def musicxml_to_abcx(xml_path: Path, *, validate: bool = True, drop_harmony: bool = False) -> str:
    """Convert one MusicXML file to ABCX text."""
    with tempfile.TemporaryDirectory(prefix="xml2abcx_") as tmp:
        tmp_path = Path(tmp)
        work_path = _strip_harmony_nodes(xml_path, tmp_path / "no_harmony") if drop_harmony else xml_path
        abc_path = _xml2abc_convert(work_path, tmp_path)
        abc_text = abc_path.read_text(encoding="utf-8")
    return to_standard_abcx(clean_for_abcjs(abc_text), validate=validate)


def musicxml_to_abc(xml_path: Path, *, drop_harmony: bool = False) -> str:
    """Convert one MusicXML file to (rich) ABC text, no ABCX normalisation.

    The output is post-processed by `clean_for_abcjs` so the abcx plugin's
    ABC-mode rendering (abcjs.parseOnly) emits zero warnings.
    """
    with tempfile.TemporaryDirectory(prefix="xml2abc_") as tmp:
        tmp_path = Path(tmp)
        work_path = _strip_harmony_nodes(xml_path, tmp_path / "no_harmony") if drop_harmony else xml_path
        abc_path = _xml2abc_convert(work_path, tmp_path)
        abc_text = abc_path.read_text(encoding="utf-8")
    return clean_for_abcjs(abc_text)


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def _discover_xml_files(root: Path, pattern: str) -> list:
    return sorted(root.rglob(pattern))


def _composer_categorised_path(src_root: Path, xml_path: Path,
                                out_root: Path, suffix: str) -> Path:
    """Mirror the source tree under `out_root`, using composer/piece layout."""
    rel = xml_path.parent.relative_to(src_root)
    stem = xml_path.stem  # usually "xml_score"
    flat_name = str(rel).replace(os.sep, "_")
    # Group by composer (first path component) while preserving rel tree.
    out_dir = out_root / rel
    return out_dir / f"{flat_name}.{suffix}"


def batch_convert(src_root: Path, out_root: Path, *, pattern: str,
                   validate: bool, abc_only: bool, drop_harmony: bool) -> None:
    files = _discover_xml_files(src_root, pattern)
    if not files:
        print(f"No files matching {pattern!r} under {src_root}", file=sys.stderr)
        return

    print(f"Found {len(files)} MusicXML files under {src_root}")
    ok = 0
    failed = 0
    validation_failed = 0
    failures = []

    for i, xml_path in enumerate(files, 1):
        out_path = _composer_categorised_path(
            src_root, xml_path, out_root,
            suffix="abc" if abc_only else "abcx",
        )
        try:
            if abc_only:
                text = musicxml_to_abc(xml_path, drop_harmony=drop_harmony)
            else:
                text = musicxml_to_abcx(xml_path, validate=validate, drop_harmony=drop_harmony)
        except AbcError as e:
            validation_failed += 1
            failures.append((xml_path, "validate", str(e)))
            print(f"  [{i}/{len(files)}] VALIDATE FAIL: {xml_path}: {e}",
                  file=sys.stderr)
            continue
        except Exception as e:
            failed += 1
            tb = traceback.format_exc(limit=1).strip().splitlines()[-1]
            failures.append((xml_path, "convert", f"{e} // {tb}"))
            print(f"  [{i}/{len(files)}] CONVERT FAIL: {xml_path}: {e}",
                  file=sys.stderr)
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text if text.endswith("\n") else text + "\n",
                             encoding="utf-8")
        ok += 1
        if i % 20 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] ok={ok} convert_fail={failed} "
                  f"validate_fail={validation_failed}")

    print()
    print("=" * 60)
    print(f"Summary: {ok} ok, {failed} convert-failed, "
          f"{validation_failed} validate-failed, {len(files)} total")
    if failures:
        print()
        print("Failures:")
        for path, stage, msg in failures[:40]:
            print(f"  [{stage}] {path}: {msg[:140]}")
        if len(failures) > 40:
            print(f"  ... and {len(failures) - 40} more")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert MusicXML to ABCX via xml2abc + to_standard.",
    )
    parser.add_argument("input",
                        help="MusicXML file (single mode) OR source root "
                             "directory (with --batch).")
    parser.add_argument("-o", "--output",
                        help="Output file path (single mode). Defaults to "
                             "<input>.abcx in the same dir.")
    parser.add_argument("--batch", action="store_true",
                        help="Treat input as a directory; recurse and convert "
                             "all MusicXML files under it.")
    parser.add_argument("--pattern", default="xml_score.musicxml",
                        help="Glob pattern for batch mode (default: "
                             "xml_score.musicxml, matches ASAP layout).")
    parser.add_argument("--out-dir", default=None,
                        help="Output root directory for --batch. Required in "
                             "batch mode.")
    parser.add_argument("--no-validate", action="store_true",
                        help="Do not raise on ABCX structural errors.")
    parser.add_argument("--abc-only", action="store_true",
                        help="Emit .abc (rich, xml2abc output) instead of "
                             "normalised .abcx.")
    parser.add_argument("--drop-harmony", action="store_true",
                        help="Remove MusicXML <harmony> chord/analysis nodes before conversion.")
    args = parser.parse_args(argv)

    validate = not args.no_validate

    if args.batch:
        src_root = Path(args.input).expanduser().resolve()
        if not src_root.is_dir():
            parser.error(f"--batch input must be a directory: {src_root}")
        if not args.out_dir:
            parser.error("--batch requires --out-dir")
        out_root = Path(args.out_dir).expanduser().resolve()
        batch_convert(src_root, out_root,
                       pattern=args.pattern,
                       validate=validate,
                       abc_only=args.abc_only,
                       drop_harmony=args.drop_harmony)
        return 0

    # Single-file mode
    xml_path = Path(args.input).expanduser().resolve()
    if not xml_path.exists():
        parser.error(f"Input file not found: {xml_path}")

    try:
        if args.abc_only:
            text = musicxml_to_abc(xml_path, drop_harmony=args.drop_harmony)
            default_suffix = ".abc"
        else:
            text = musicxml_to_abcx(xml_path, validate=validate, drop_harmony=args.drop_harmony)
            default_suffix = ".abcx"
    except AbcError as e:
        print(f"xml_to_abcx: validation error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"xml_to_abcx: error: {e}", file=sys.stderr)
        return 2

    out_path = (Path(args.output).expanduser().resolve() if args.output
                else xml_path.with_suffix(default_suffix))
    out_path.write_text(text if text.endswith("\n") else text + "\n",
                         encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
