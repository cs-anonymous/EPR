#!/usr/bin/env python3
"""Score MIDI → ABCX converter for ASAP dataset.

Uses ABCX & multi-track syntax for polyphonic parts (e.g. Bach fugues).
Each MIDI Voice within a part becomes a separate track joined by &.
Pads shorter voices with rests to fill the declared measure duration.
"""

import os
from fractions import Fraction
from music21 import converter, note as m21note


KEY_MAP = {
    'C major': 'C', 'C minor': 'Cm',
    'G major': 'G', 'G minor': 'Gm',
    'D major': 'D', 'D minor': 'Dm',
    'F major': 'F', 'F minor': 'Fm',
    'Bb major': 'Bb', 'Bb minor': 'Bbm',
    'Eb major': 'Eb', 'Eb minor': 'Em',
    'Ab major': 'Ab', 'Ab minor': 'Abm',
    'A major': 'A', 'A minor': 'Am',
    'E major': 'E', 'E minor': 'Em',
    'B major': 'B', 'B minor': 'Bm',
    'Cb major': 'Cb', 'Gb major': 'Gb',
    'Db major': 'Db', 'Db minor': 'Dbm',
    'F# major': 'F#', 'F# minor': 'F#m',
    'C# major': 'C#', 'C# minor': 'C#m',
}


def get_key(midi_path):
    s = converter.parse(midi_path)
    ks = s.analyze('key')
    mode = 'major' if ks.mode == 'major' else 'minor'
    return f"{ks.tonic.name} {mode}"


def key_to_abc(key_str):
    return KEY_MAP.get(key_str, 'C')


def pitch_to_abc(pitch):
    name = pitch.name
    oct_num = pitch.octave
    acc = ""
    base = name[0]
    if len(name) > 1:
        if name[1] == '-': acc = '_'
        elif name[1] == '#': acc = '^'
    if oct_num >= 5:
        letter = base.lower() + "'" * (oct_num - 5)
    elif oct_num == 4:
        letter = base.lower()
    else:
        letter = base.upper() + "," * (4 - oct_num)
    return f"{acc}{letter}"


# Standard ABC durations in sixteenth-units (L:1/16 base):
# 1=16th, 2=8th, 3=dotted-8th, 4=quarter, 6=dotted-quarter, 8=half, 12=dotted-half, 16=whole
# Also common tuplets: 4/3 (triplet-8th), 8/3 (triplet-quarter), 4/5 (quintuplet), 8/5
STANDARD_SIXTEENTHS = sorted([
    1, 2, 3, 4, 6, 8, 12, 16,
    Fraction(4, 3), Fraction(8, 3),
    Fraction(4, 5), Fraction(8, 5),
    Fraction(4, 7), Fraction(8, 7),
])


def round_to_sixteenth(n_sixteenths):
    """Round a sixteenth-count to the nearest standard value.

    Uses limit_denominator(8) to simplify fractions early, reducing
    accumulated error from complex tuplets like 9-tuplets or 7-tuplets.
    """
    f = Fraction(n_sixteenths).limit_denominator(8)
    # If already a simple fraction, return as-is
    if f.denominator <= 8:
        return f
    # Otherwise find nearest standard value
    best = min(STANDARD_SIXTEENTHS, key=lambda s: abs(float(s) - float(f)))
    return best


def ql_to_abc_dur(ql):
    """L:1/16 base: abc_dur = ql * 4, rounded to standard value."""
    if ql <= 0:
        return ""
    f = round_to_sixteenth(Fraction(ql) * 4)
    if f.numerator == f.denominator:
        return ""
    if f.denominator == 1:
        return str(f.numerator)
    if f.numerator == 1:
        return f"/{f.denominator}"
    return f"{f.numerator}/{f.denominator}"


def merge_consecutive_rests(events):
    """Combine consecutive rest events into a single rest.

    Reduces accumulated rounding error from many small rests.
    e.g., [z/12, z/12, z/12, z/8, z/8] → [z with combined duration]
    """
    if not events:
        return
    result = []
    current_rest_ql = 0
    for pitch, ql in events:
        if pitch == 'z':
            current_rest_ql += ql
        else:
            if current_rest_ql > 0:
                result.append(('z', current_rest_ql))
                current_rest_ql = 0
            result.append((pitch, ql))
    if current_rest_ql > 0:
        result.append(('z', current_rest_ql))
    events[:] = result


def events_to_abc_string(events):
    parts = []
    for pitch, ql in events:
        dur = ql_to_abc_dur(ql)
        if pitch == 'z':
            parts.append(f"z{dur}")
        else:
            parts.append(f"{pitch}{dur}")
    return " ".join(parts)


def extract_voice_events(voice):
    events = []
    for el in voice.notesAndRests:
        if el.quarterLength <= 0:
            continue
        if isinstance(el, m21note.Note):
            events.append((pitch_to_abc(el.pitch), el.quarterLength))
        else:
            events.append(('z', el.quarterLength))
    return events


def group_simultaneous(events, container):
    by_offset = {}
    for el in container.notesAndRests:
        if el.quarterLength <= 0:
            continue
        offset = round(el.offset, 3)
        if offset not in by_offset:
            by_offset[offset] = []
        if isinstance(el, m21note.Note):
            by_offset[offset].append(('note', pitch_to_abc(el.pitch), el.quarterLength))
        else:
            by_offset[offset].append(('rest', 'z', el.quarterLength))

    if not by_offset:
        return []

    result = []
    for offset in sorted(by_offset.keys()):
        items = by_offset[offset]
        notes = [(p, ql) for typ, p, ql in items if typ == 'note']
        rests = [(p, ql) for typ, p, ql in items if typ == 'rest']

        if notes:
            if len(notes) == 1:
                result.append((notes[0][0], notes[0][1]))
            else:
                pitches = sorted([p for p, _ in notes])
                chord_ql = max(ql for _, ql in notes)
                result.append(('[' + ' '.join(pitches) + ']', chord_ql))
        elif rests:
            max_rest_ql = max(ql for _, ql in rests)
            result.append(('z', max_rest_ql))

    return result


def measure_to_voice_events(m, measure_ql):
    """Extract events from a measure.

    Returns list of event lists, one per internal voice.
    Each event list is a list of (pitch/chord, ql) tuples.
    """
    voices = list(m.getElementsByClass('Voice'))

    if len(voices) > 1:
        tracks = []
        for v in voices:
            events = extract_voice_events(v)
            events = group_simultaneous(events, v)
            events = resolve_overlaps(events, measure_ql)
            tracks.append(events)
        return tracks
    else:
        events = extract_voice_events(m.flatten())
        events = group_simultaneous(events, m.flatten())
        events = resolve_overlaps(events, measure_ql)
        return [events]


def resolve_overlaps(events, measure_ql):
    """Walk events sequentially, truncating to measure_ql.

    After grouping, events should be sequential. But overlapping MIDI
    events can produce a total > measure_ql. This truncates at measure_ql
    and pads with rest if needed.
    """
    if not events:
        return events

    result = []
    cursor = 0.0
    for pitch, ql in events:
        if cursor >= measure_ql - 0.01:
            break
        # Shorten event if it would exceed measure_ql
        available = measure_ql - cursor
        if ql > available + 0.01:
            ql = max(available, 0)
        if ql > 0.01:
            result.append((pitch, ql))
        cursor += ql

    return result


def fill_track_to(events, target_ql):
    """Adjust the last rest (or add one) so the track exactly fills target_ql.

    Rounding of tuplet durations can cause the total to be slightly off.
    This adjusts the final rest to compensate. If there's no rest, adjusts
    the last event or adds a compensating rest.
    """
    total = sum(ql for _, ql in events)
    remaining = target_ql - total
    if abs(remaining) < 0.0001:
        return  # Close enough

    if remaining > 0:
        # Need more rest
        if events and events[-1][0] == 'z':
            events[-1] = ('z', events[-1][1] + remaining)
        else:
            events.append(('z', remaining))
    elif remaining < 0:
        # Events overfill slightly — shorten the last rest or last note
        if events and events[-1][0] == 'z':
            new_ql = max(events[-1][1] + remaining, 0.001)
            events[-1] = ('z', new_ql)
        elif events:
            # Shorten the last event slightly
            last_pitch, last_ql = events[-1]
            new_ql = max(last_ql + remaining, 0.001)
            events[-1] = (last_pitch, new_ql)


def scale_events_to_ql(events, target_ql):
    """Compress events proportionally when they exceed the target ql.

    Used when Part 0's declared TS is larger than the chosen TS
    (e.g., Part 0 says 9/8 but we pick 4/4). Scales each event's
    duration by the ratio target_ql / actual_ql.
    """
    total = sum(ql for _, ql in events)
    if total <= target_ql + 0.01:
        return  # Already fits
    ratio = target_ql / total
    result = []
    for pitch, ql in events:
        result.append((pitch, ql * ratio))
    events[:] = result


def ts_to_ql(ts_str):
    if '-' in ts_str:
        return None
    n, d = ts_str.split('/')
    return int(n) * 4 / int(d)


def midi_to_abcx(midi_path, min_seconds=10.0, min_tail_seconds=6.0):
    s = converter.parse(midi_path)

    # Get BPM
    bpm = 120
    for p in s.parts:
        mm = p.flatten().getElementsByClass('MetronomeMark').first()
        if mm and hasattr(mm, 'number'):
            bpm = mm.number
            break
    sec_per_ql = 60.0 / bpm

    n_parts = len(s.parts)
    voice_names = [f"V{i+1}" for i in range(n_parts)]

    key_str = get_key(midi_path)
    key_abc = key_to_abc(key_str)

    # Collect per-measure data
    max_measures = max(
        len(list(p.getElementsByClass('Measure'))) for p in s.parts
    )
    measure_data = [None] * max_measures

    for pi, part in enumerate(s.parts):
        voice = f"V{pi+1}"
        measures = list(part.getElementsByClass('Measure'))
        for mi, m in enumerate(measures):
            if measure_data[mi] is None:
                measure_data[mi] = {
                    'num': mi + 1,
                    'ts': '-',
                    'ql': 0,
                    'ts_candidates': {},
                    'part0_ts': None,
                    'voices': {},
                }
            md = measure_data[mi]
            ts = m.timeSignature
            part_ql = m.duration.quarterLength
            if part_ql > md['ql']:
                md['ql'] = part_ql
            if ts:
                ts_str = f"{ts.numerator}/{ts.denominator}"
                md['ts_candidates'][ts_str] = md['ts_candidates'].get(ts_str, 0) + 1
                if pi == 0:
                    md['part0_ts'] = ts_str

            tracks = measure_to_voice_events(m, part_ql)
            # Calculate actual ql from event span (max end offset)
            actual_ql = 0
            for track in tracks:
                track_ql = sum(ql for _, ql in track)
                if track_ql > actual_ql:
                    actual_ql = track_ql
            # Also consider the measure's reported ql
            part_ql = m.duration.quarterLength
            max_ql = max(actual_ql, part_ql)
            if max_ql > md['ql']:
                md['ql'] = max_ql

            measure_data[mi]['voices'][voice] = tracks

    # Determine TS for each measure
    # Strategy: prefer Part 0's declared TS when parts conflict, since Part 0
    # carries the primary musical material (melody, fugue subject, etc.).
    ql_to_ts_map = {
        0.5: '1/2', 0.75: '3/8', 1.0: '2/4', 1.25: '5/4',
        1.5: '3/8', 2.0: '2/2', 2.5: '5/4', 3.0: '3/2',
        4.0: '4/4', 4.5: '9/8', 5.0: '5/4', 6.0: '6/4', 8.0: '4/2',
        3.0: '6/8',
    }

    def pick_best_ts(md):
        candidates = md.get('ts_candidates', {})
        actual_ql = md['ql']
        part0_ts = md.get('part0_ts')

        if part0_ts and part0_ts in candidates:
            # Skip Part 0's TS if it's anomalously short (likely an anacrusis
            # or pickup measure) — less than half the actual measure content
            part0_ql = ts_to_ql(part0_ts)
            if part0_ql >= actual_ql * 0.5:
                return part0_ts

        if not candidates:
            return ql_to_ts_map.get(actual_ql, '4/4')

        # Prefer TS whose barDuration matches the actual ql
        for ts_str, count in candidates.items():
            if abs(ts_to_ql(ts_str) - actual_ql) < 0.01:
                return ts_str

        # If no TS matches, use actual ql to derive a sensible TS
        # (the parts have conflicting TS in the MIDI)
        if actual_ql in ql_to_ts_map:
            return ql_to_ts_map[actual_ql]

        # Fallback: use the TS with the largest ql
        return max(candidates, key=lambda t: ts_to_ql(t))

    last_ts = "4/4"
    for md in measure_data:
        if md:
            best = pick_best_ts(md)
            if best:
                last_ts = best
                md['ts'] = best
            elif md['ts'] == '-':
                md['ts'] = last_ts
            md['ql'] = ts_to_ql(md['ts'])
            md['sec'] = md['ql'] * sec_per_ql

    # Pad each voice to exactly fill the declared measure ql
    for md in measure_data:
        if not md:
            continue
        target_ql = md['ql']
        for vname in voice_names:
            if vname in md['voices']:
                for track in md['voices'][vname]:
                    # Scale down events if they exceed target ql
                    # (happens when Part 0 declares a larger TS like 9/8
                    # but we picked 4/4 based on other parts)
                    scale_events_to_ql(track, target_ql)
                    # Merge consecutive rests to reduce accumulated rounding
                    merge_consecutive_rests(track)
                    fill_track_to(track, target_ql)
                # Convert events to ABC string
                track_strs = [events_to_abc_string(t) for t in md['voices'][vname]]
                md['voices'][vname] = " & ".join(track_strs)
            else:
                # Completely missing voice: full rest
                md['voices'][vname] = f"z{ql_to_abc_dur(target_ql)}" if target_ql else "z4"

    first_ts = measure_data[0]['ts'] if measure_data else "4/4"

    # Batch by time
    remaining_sec = [0] * (len(measure_data) + 1)
    for i in range(len(measure_data) - 1, -1, -1):
        remaining_sec[i] = measure_data[i]['sec'] + remaining_sec[i+1]

    batches = []
    current_batch, current_sec = [], 0
    for i, md in enumerate(measure_data):
        current_batch.append(md)
        current_sec += md['sec']
        if current_sec >= min_seconds:
            remaining = remaining_sec[i+1]
            if remaining > 0 and remaining < min_tail_seconds:
                continue
            batches.append(current_batch)
            current_batch, current_sec = [], 0
    if current_batch:
        if current_sec >= min_tail_seconds:
            batches.append(current_batch)
        elif batches:
            batches[-1].extend(current_batch)
        else:
            batches.append(current_batch)

    # Generate ABCX
    lines = [
        "X:1",
        f"T:{os.path.basename(midi_path).replace('.mid', '').replace('_', ' ')}",
        f"M:{first_ts}",
        "L:1/16",
        f"K:{key_abc}",
        f"%%score {' '.join('(' + v + ')' for v in voice_names)}",
        "",
    ]

    current_ts = first_ts
    for bi, batch in enumerate(batches):
        total_sec = sum(md['sec'] for md in batch)
        m_range = f"{batch[0]['num']}-{batch[-1]['num']}"
        lines.append(f"% BATCH {bi+1}: m{m_range}, {len(batch)}m, {total_sec:.1f}s")

        for md in batch:
            if md['ts'] != current_ts:
                current_ts = md['ts']
                lines.append(f"[M:{current_ts}]")

            parts = [md['voices'].get(v, "") for v in voice_names]
            events_line = " ; ".join(parts)
            lines.append(events_line)

    return "\n".join(lines)


def main():
    base_dir = "/home/sy/2026/Music/data/audio_symbolic_alignment/asap-dataset"
    out_dir = "/home/sy/2026/Music/EPR/smidi-tsv"
    os.makedirs(out_dir, exist_ok=True)

    files = []
    for root, dirs, fnames in os.walk(base_dir):
        if "midi_score.mid" in fnames:
            files.append(os.path.join(root, "midi_score.mid"))

    files.sort()
    print(f"Found {len(files)} files")

    total_batches = 0
    total_lines = 0

    for fpath in files:
        rel = os.path.relpath(fpath, base_dir)
        name = rel.replace("/", "_").replace("\\", "_").replace("midi_score.mid", "").strip("_")
        out_path = os.path.join(out_dir, f"{name}.abcx")

        try:
            abc = midi_to_abcx(fpath)
            with open(out_path, "w") as f:
                f.write(abc + "\n")

            n_lines = abc.count("\n")
            n_batches = abc.count("% BATCH")
            total_batches += n_batches
            total_lines += n_lines
            print(f"  OK: {name} ({n_batches} batches, {n_lines} lines)")
        except Exception as e:
            print(f"  ERROR: {name}: {e}")

    print(f"\nDone: {total_batches} batches, {total_lines} lines total")


if __name__ == "__main__":
    main()
