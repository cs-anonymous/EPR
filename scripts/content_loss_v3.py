#!/usr/bin/env python3
"""Corrected content-preservation analysis: MusicXML → ABC via xml2abc."""
import re, subprocess, zipfile
from pathlib import Path

XML2ABC = "/home/sy/2026/Music/EPR/xml2abc/xml2abc.py"
ROOT = Path("/home/sy/2026/Music/EPR")

samples = [
    ("NATIVE_XML", "chopin/Op028 (Prelude)",  "data/maestro_score_v1/works/chopin/Op028/score.musicxml"),
    ("SCANNED",    "scriabin/Op009 (LH Prelude+Nocturne)", "data/maestro_score_v1/works/scriabin/Op009/score.xml"),
    ("OMR",        "schubert/D960 mvt1",      "data/maestro_score_v1/works/schubert/D960/score.mxl"),
]

def read_xml(p):
    p = Path(p)
    if p.suffix == ".mxl":
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.endswith(".xml") and not n.startswith("META-INF"):
                    return z.read(n).decode("utf-8", errors="replace")
    return p.read_text(errors="replace")

def xml_metrics(t):
    return {
        "pitched_notes": t.count("<note") - t.count("<rest"),
        "rests":         t.count("<rest"),
        "chords":        t.count("<chord"),
        "ties":          len(re.findall(r"<tied\b", t)),
        "slurs":         len(re.findall(r"<slur\b", t)),
        "tuplets":       len(re.findall(r"<tuplet\b", t)),
        "accents":       t.count("<accent/") + t.count("<strong-accent/"),
        "staccatos":     t.count("<staccato/"),
        "tenutos":       t.count("<tenuto/"),
        "fermatas":      t.count("<fermata"),
        "arpeggiates":   t.count("<arpeggiate"),
        "graces":        t.count("<grace"),
        "dynamics":      sum(t.count(f"<{d}/") for d in ["p","pp","ppp","f","ff","fff","mf","mp","sfz","sf","fz"]),
        "trills":        t.count("<trill-mark") + t.count("<wavy-line"),
        "mordents":      t.count("<mordent") + t.count("<inverted-mordent"),
        "turns":         t.count("<turn"),
        "pedals":        len(re.findall(r"<pedal\b", t)),
        "wedges":        len(re.findall(r"<wedge\b", t)),
        "words":         len(re.findall(r"<words\b", t)),
        "metronomes":    t.count("<metronome"),
        "octave_shifts": len(re.findall(r"<octave-shift\b", t)),
        "endings":       t.count("<ending"),
        "repeats":       t.count("<repeat"),
        "measures":      len(re.findall(r"<measure\b", t)),
    }

def abc_metrics(a):
    body = "\n".join(l for l in a.splitlines() if not re.match(r"^[A-Z]:|^%", l))
    return {
        "abc_notes":      len(re.findall(r"(?<![\!A-Za-z\^_=])[\^_=]{0,2}[A-Ga-g][,']*[\d/]*", re.sub(r"!.*?!", "", re.sub(r'"[^"]*"', '', body)))),
        "abc_rests_z":    len(re.findall(r"(?<![A-Za-z])z\d*", body)),
        "abc_chord_brk":  len(re.findall(r"\[[^\]]*[A-Ga-g][^\]]*\]", body)),
        "abc_ties":       len(re.findall(r"[A-Ga-g][,']*[\d/]*-", body)),
        "abc_slurs_open": body.count("(") - len(re.findall(r"\(\d", body)),
        "abc_tuplets":    len(re.findall(r"\(\d", body)),
        "abc_accents":    a.count("!>!") + a.count("!^!"),
        "abc_stacc":      len(re.findall(r"(?<![A-Za-z!])\.[A-Ga-g\[\^_=]", body)),
        "abc_tenuto":     a.count("!tenuto!"),
        "abc_fermata":    a.count("!fermata!"),
        "abc_arpeg":      a.count("!arpeggio!"),
        "abc_grace":      a.count("{"),
        "abc_dyn":        sum(a.count(f"!{d}!") for d in ["p","pp","ppp","f","ff","fff","mf","mp","sfz"]),
        "abc_trill":      len(re.findall(r"(?<![A-Za-z])T(?=[\^_=]?[A-Ga-g\[])", a)),
        "abc_mordent":    len(re.findall(r"(?<![A-Za-z])M(?=[\^_=]?[A-Ga-g\[])", a)) + len(re.findall(r"(?<![A-Za-z])P(?=[\^_=]?[A-Ga-g\[])", a)),
        "abc_turn":       a.count("!turn!") + a.count("!invertedturn!"),
        "abc_pedal_open": a.count("!ped!"),
        "abc_pedal_close":a.count("!ped-up!"),
        "abc_hairpin":    a.count("!<(!") + a.count("!>(!") + a.count("!<)!") + a.count("!>)!"),
        "abc_hairpin_open": a.count("!<(!") + a.count("!>(!"),
        "abc_words":      len(re.findall(r'"[\^_][^"]+"', a)),
        "abc_tempo_inline": len(re.findall(r"\[Q:", a)),
        "abc_tempo_header": len(re.findall(r"^Q:", a, re.M)),
        "abc_8va":        a.count("!8v"),
        "abc_voltas":     len(re.findall(r"(?<!\[)\[[12]", a)),
        "abc_inlineK":    len(re.findall(r"\[K:[^\]]+\]", a)),
    }

print(f"{'category':30} {'XML':>8} {'ABC':>8} {'preserved':>11}")
print("="*68)

for label, name, p in samples:
    p = ROOT/p
    if not p.exists(): continue
    xml = read_xml(p)
    abc = subprocess.run(["python3", XML2ABC, str(p), "-o", "/tmp/abc_v3"],
                         capture_output=True, text=True, timeout=180)
    abcfile = next(Path("/tmp/abc_v3").glob("*.abc"))
    abc = abcfile.read_text()
    abcfile.unlink()
    x = xml_metrics(xml); a = abc_metrics(abc)
    
    print(f"\n--- [{label}] {name} ---")
    pairs = [
        ("notes (pitched)",       x["pitched_notes"], a["abc_notes"]),
        ("rests (visible)",       x["rests"],         a["abc_rests_z"]),
        ("chord notes",           x["chords"],        a["abc_chord_brk"]),
        ("ties",                  x["ties"]//2,       a["abc_ties"]),  # XML has start+stop pair
        ("slurs (open)",          x["slurs"]//2,      a["abc_slurs_open"]),
        ("tuplets",               x["tuplets"]//2,    a["abc_tuplets"]),
        ("accents",               x["accents"],       a["abc_accents"]),
        ("staccato",              x["staccatos"],     a["abc_stacc"]),
        ("tenuto",                x["tenutos"],       a["abc_tenuto"]),
        ("fermata",               x["fermatas"],      a["abc_fermata"]),
        ("arpeggio",              x["arpeggiates"],   a["abc_arpeg"]),
        ("grace notes",           x["graces"],        a["abc_grace"]),
        ("dynamics (p/f/...)",    x["dynamics"],      a["abc_dyn"]),
        ("trills",                x["trills"],        a["abc_trill"]),
        ("mordents",              x["mordents"],      a["abc_mordent"]),
        ("turns",                 x["turns"],         a["abc_turn"]),
        ("pedals open",           x["pedals"]//2,     a["abc_pedal_open"]),
        ("hairpin (cresc/dim) start", x["wedges"]//2, a["abc_hairpin_open"]),
        ("words (rit/dolce..)",   x["words"],         a["abc_words"]),
        ("metronome",             x["metronomes"],    a["abc_tempo_header"] + a["abc_tempo_inline"]),
        ("octave shift (8va)",    x["octave_shifts"]//2, a["abc_8va"]//2),
        ("voltas (endings)",      x["endings"]//2,    a["abc_voltas"]),
        ("repeat barlines",       x["repeats"],       0),  # represented by |: :| not counted yet
    ]
    for n, xv, av in pairs:
        if xv == 0:
            line = f"{n:30} {xv:>8} {av:>8}    n/a"
        else:
            pct = av/xv*100
            mark = " <" if pct < 80 else ("==" if pct <= 120 else " >")
            line = f"{n:30} {xv:>8} {av:>8} {pct:>7.0f}% {mark}"
        print(line)
