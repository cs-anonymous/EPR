#!/usr/bin/env python3
"""Add performance_gist field to piece_interpretation.json files.
Generates a 20-30 word performance_gist from compressed_interpretation_200.
ONLY performance parameters: tempo feel, articulation, dynamic contour, rubato, phrasing.
NO dates, composer names, piece titles, historical context.
Comma-separated phrases, operationally focused.
No duplicate phrases.
"""
import json
import re
import os

# Read all file paths from the four lists
file_paths = []
for batch in [44, 45, 46, 47]:
    txt_path = f"/tmp/gist_missing_{batch}.txt"
    with open(txt_path) as f:
        for line in f:
            line = line.strip()
            if '\t' in line:
                line = line.split('\t', 1)[1]
            if line and line.endswith("piece_interpretation.json"):
                file_paths.append(line)

print(f"Total files to process: {len(file_paths)}")


def extract_performance_gist(text):
    """
    Generate a performance_gist (20-30 words) from compressed_interpretation_200.
    Only performance parameters: tempo feel, articulation, dynamic contour, rubato, phrasing.
    No dates, composer names, piece titles, historical context.
    Comma-separated phrases, operationally focused.
    """
    text_lower = text.lower()

    # We'll collect candidate output phrases. Each candidate has a trigger keyword
    # and the output phrase. We only keep UNIQUE output phrases.
    candidates = []

    def add(keyword, phrase):
        """Add a candidate if keyword matches and phrase not already used."""
        if keyword in text_lower:
            candidates.append(phrase)

    # --- TEMPO ---
    add("metronomic", "metronomic precision")
    add("steady pulse", "steady underlying pulse")
    add("steady tempo", "steady measured pulse")
    add("walking tempo", "steady walking-tempo pulse")
    add("measured tempo", "measured deliberate tempo")
    add("broad pulse", "broad measured pulse")
    add("driving", "driving energetic pulse")
    add("lively animated", "lively animated tempo")
    add("lively", "lively spirited tempo")
    add("fleet", "fleet agile tempo")
    add("unhurried", "unhurried spacious tempo")
    add("patient", "patient expansive pacing")
    add("energetic", "energetic spirited drive")
    add("animated", "animated urgent tempo")
    add("restless", "restless agitated momentum")
    add("buoyant", "buoyant light-footed pulse")
    add("brisk", "brisk forward drive")
    add("moderate", "moderate comfortable tempo")
    add("march-like", "march-like steady tread")
    add("dancing", "light dancing character")
    add("dance-like", "dance-like buoyant pulse")
    add("ceremonial", "ceremonial dignified gravity")
    add("vigorous", "vigorous robust drive")
    add("sprightly", "sprightly nimble tempo")
    add("forward momentum", "forward propulsive momentum")
    add("propulsive", "propulsive forward drive")
    add("sweeping", "sweeping expansive gesture")
    add("urgent", "urgent restless drive")
    add("broad", "broad expansive pacing")
    add("unforced", "unforced natural flow")
    add("andante", "moderate measured pacing")
    add("adagio", "slow sustained pacing")
    add("lento", "slow contemplative pacing")
    add("allegro", "bright forward drive")
    add("presto", "swift driving tempo")
    add("vivace", "lively spirited tempo")
    add("relaxed", "relaxed unhurried ease")
    add("relentless", "relentless driving force")
    add("motoric", "motoric relentless drive")
    add("tempo", "controlled measured pulse")
    add("slow tempo", "patient unhurried pacing")
    add("moderate tempo", "moderate measured pacing")

    # --- ARTICULATION ---
    add("transparent crystalline", "transparent crystalline texture")
    add("crystalline", "clear crystalline touch")
    add("transparent", "transparent voice layering")
    add("seamless legato", "seamless legato connection")
    add("legato", "smooth legato phrasing")
    add("staccato", "crisp staccato articulation")
    add("detached", "light detached touch")
    add("crisp", "crisp sharply defined attack")
    add("precise articulation", "precise controlled articulation")
    add("precise", "precise controlled execution")
    add("matched articulation", "uniform matched articulation")
    add("non-legato", "clean non-legato touch")
    add("portato", "gentle portato breathing")
    add("accented", "sharply profiled accents")
    add("light touch", "light fleet touch")
    add("delicate", "delicate gossamer touch")
    add("weighty", "weighty resonant sonority")
    add("resonant", "deep resonant sonority")
    add("singing cantabile", "singing cantabile line")
    add("cantabile", "singing cantabile touch")
    add("warm tone", "warm rounded sonority")
    add("voicing", "balanced voice projection")
    add("clear profiled", "clear profiled articulation")
    add("clean", "clean precise articulation")
    add("ornament", "graceful ornament execution")
    add("turn", "graceful turn execution")
    add("trill", "shimmering trill texture")
    add("attack", "defined attack profile")
    add("bell-like", "clear bell-like resonance")
    add("assertive articulation", "assertive profiled articulation")
    add("dotted rhythm", "crisp dotted-rhythm articulation")
    add("conviction", "confident assured touch")

    # --- DYNAMICS ---
    add("terraced dynamics", "terraced dynamic shifts")
    add("terraced", "terraced dynamic contrasts")
    add("crescendo", "gradual dynamic crescendo")
    add("swell", "controlled dynamic swell")
    add("subtle", "subtle dynamic shading")
    add("nuanced dynamic", "nuanced dynamic gradation")
    add("gradual dynamic", "gradual dynamic arch")
    add("contrasting dynamic", "contrasting dynamic levels")
    add("muted", "muted subdued palette")
    add("restrained dynamic", "restrained controlled dynamic")
    add("dynamic bloom", "sudden dynamic bloom")
    add("dynamic shading", "expressive dynamic shading")
    add("dynamic control", "careful dynamic control")
    add("quiet", "quiet introspective focus")
    add("soft", "delicate soft touch")
    add("forte", "bold full-voiced sonority")
    add("climactic", "natural dynamic climax")
    add("gradual rise", "gradual dynamic rise")
    add("diminuendo", "gradual dynamic decay")
    add("dynamic", "sensitive dynamic shaping")
    add("pianissimo", "whisper-soft dynamic touch")
    add("piano", "delicate soft touch")
    add("pianiss", "whisper-soft dynamic touch")
    add("dynamic contrast", "contrasting dynamic levels")
    add("dramatic dynamic", "dramatic dynamic contrast")
    add("subtle dynamic", "subtle dynamic shading")
    add("controlled climactic", "controlled climactic energy")

    # --- RUBATO / PHRASING ---
    add("rubato", "flexible expressive rubato")
    add("elastic tempo", "elastic tempo flexibility")
    add("flexible", "flexible breathing phrasing")
    add("expressive freedom", "expressive rhythmic freedom")
    add("natural breath", "natural breath-marked phrasing")
    add("suspension", "tensioned suspended resolution")
    add("delayed", "delayed cadential release")
    add("eased", "eased rubato at cadences")
    add("sigh", "sigh-shaped micro-gestures")
    add("hesitation", "hesitant expressive pause")
    add("linger", "lingering phrase extension")
    add("measured pause", "measured expressive pause")
    add("phrase shaping", "careful phrase shaping")
    add("phrasing", "vocal shaped phrasing")
    add("phrase group", "clear phrase architecture")
    add("rise and fall", "natural phrase rise and fall")
    add("melodic line", "vocal melodic contour")
    add("melodic", "lyrically shaped melodic line")
    add("song-like", "song-like melodic contour")
    add("lyrical", "lyrically shaped lines")
    add("lyricism", "expressive lyricism")
    add("vocal", "vocal sensitivity")
    add("shape", "careful phrase architecture")
    add("arched", "arched phrase trajectory")
    add("cadential", "clear cadential articulation")
    add("cadence", "well-shaped cadential approach")
    add("resolution", "clear harmonic resolution")
    add("plaintive", "plaintive plaintive line")
    add("descending phrase", "descending sighing phrases")
    add("descending", "descending sighing contour")
    add("resignation", "resigned fading cadence")
    add("forward-moving", "forward-moving pulse")
    add("purposeful", "purposeful directed motion")

    # --- TEXTURE ---
    add("polyphonic", "balanced polyphonic voicing")
    add("fugal", "tight fugal entries")
    add("canonic", "clear canonic entries")
    add("contrapuntal", "interwoven contrapuntal lines")
    add("counterpoint", "balanced contrapuntal voicing")
    add("voice leading", "clean voice leading")
    add("inner voices", "transparent inner voices")
    add("textural", "carefully graded texture")
    add("dense", "rich dense texture")
    add("sparse", "sparse transparent texture")
    add("layered", "layered textural buildup")
    add("homophonic", "homophonic clarity")
    add("accompaniment", "light accompanying texture")
    add("ground bass", "steady ground bass pulse")
    add("bass", "grounded bass foundation")
    add("ostinato", "persistent ostinato drive")
    add("arpeggiated", "rippling arpeggiated flow")
    add("broken chord", "flowing broken chord texture")
    add("chordal", "solid chordal sonority")
    add("block chord", "solid block-chord weight")
    add("tremolo", "shimmering tremolo texture")
    add("sustained", "sustained broad pacing")
    add("pedal", "sensitive nuanced pedaling")
    add("pedal point", "sustained pedal-point drone")
    add("improvisatory", "free improvisatory gesture")
    add("rhapsodic", "rhapsodic fantasia freedom")
    add("flowing", "flowing seamless continuity")
    add("two-part", "clear two-part voicing")
    add("two part", "clear two-part voicing")

    # --- CHARACTER / COLOR ---
    add("contemplative", "contemplative introspective focus")
    add("introspective", "introspective reflective tone")
    add("syncopat", "playful syncopated lilt")
    add("dramatic tension", "dramatic tension arc")
    add("dramatic", "dramatic expressive contrast")
    add("stormy", "stormy volatile intensity")
    add("volatile", "volatile restless drive")
    add("tender", "tender warmth of tone")
    add("gentle", "gentle nuanced shading")
    add("pastoral", "pastoral rustic coloration")
    add("playful", "playful light character")
    add("noble", "noble dignified bearing")
    add("solemn", "solemn measured gravity")
    add("heroic", "heroic bold projection")
    add("intimate", "intimate confessional tone")
    add("virtuosic", "brilliant virtuoso display")
    add("bright vivid", "bright vivid coloration")
    add("bright", "bright luminous sonority")
    add("dark brooding", "dark brooding coloration")
    add("somber", "somber restrained palette")
    add("warm", "warm rounded sonority")
    add("shimmering", "shimmering tremolo texture")
    add("graceful", "graceful flowing contour")
    add("ragtime", "syncopated ragtime lilt")
    add("waltz", "rotating waltz lilt")
    add("minuet", "courtly minuet grace")
    add("sarabande", "solemn sarabande gravity")
    add("gigue", "lively gigue bounce")
    add("allemande", "measured allemande flow")
    add("courante", "flowing courante motion")
    add("gavotte", "light gavotte step")
    add("bourree", "bright bourree drive")
    add("nocturne", "nocturnal dreamy reverie")
    add("berceuse", "gentle rocking lullaby pulse")
    add("mazurka", "elastic mazurka lilt")
    add("ballade", "narrative ballade sweep")
    add("prelude", "free prelude gesture")
    add("fantasia", "rhapsodic fantasia freedom")
    add("impromptu", "spontaneous impromptu ease")
    add("etude", "focused technical clarity")
    add("serene", "serene poised calm")
    add("majestic", "majestic broad sonority")
    add("festive", "festive brilliant energy")
    add("ethereal", "ethereal floating lightness")
    add("ecstatic", "ecstatic heightened intensity")
    add("meditative", "meditative still focus")
    add("dreamy", "dreamy floating reverie")
    add("melancholic", "melancholic subdued tone")
    add("melancholy", "melancholic subdued tone")
    add("joyful", "joyful bright energy")
    add("cheerful", "cheerful buoyant spirit")
    add("whimsical", "whimsical light character")
    add("mysterious", "mysterious veiled sonority")
    add("mystic", "mystic hushed atmosphere")
    add("agitated", "agitated restless energy")
    add("fierce", "fierce driven intensity")
    add("passionate", "passionate ardent warmth")
    add("turbulent", "turbulent volatile energy")
    add("anguish", "anguished pressing intensity")
    add("anguished", "anguished pressing intensity")
    add("triumphant", "triumphant bold proclamation")
    add("tragic", "tragic weight gravity")
    add("elegiac", "elegiac mourning tone")
    add("mournful", "mournful lamenting line")
    add("lament", "lamenting expressive line")
    add("wistful", "wistful tender nostalgia")
    add("yearning", "yearning expressive reach")
    add("nostalgic", "nostalgic tender warmth")
    add("humorous", "humorous light character")
    add("comic", "comic playful gesture")
    add("grotesque", "grotesque angular character")
    add("eccentric", "eccentric angular character")
    add("mechanical", "mechanical precise drive")
    add("jazzy", "jazzy syncopated lilt")
    add("impressionistic", "impressionistic blurred coloration")
    add("impressionist", "impressionistic veiled texture")
    add("baroque", "baroque clarity of line")
    add("classical", "classical balance of phrase")
    add("romantic", "romantic expressive warmth")
    add("folk", "folk directness of tone")
    add("modal", "modal open sonority")
    add("diatonic", "diatonic clarity of tone")
    add("chromatic", "chromatic harmonic tension")
    add("rustic", "rustic folk simplicity")
    add("national", "national character projection")
    add("theatrical", "theatrical expressive gesture")
    add("fragment", "fragmentary suggestive phrasing")
    add("incomplet", "open unresolved gesture")
    add("poetic", "poetic evocative touch")
    add("poignant", "poignant tender expressivity")
    add("emotional", "emotional expressive depth")
    add("empathetic", "empathetic sympathetic warmth")
    add("searching", "searching restless line")
    add("wandering", "wandering harmonic drift")
    add("agitation", "agitated restless energy")
    add("assertive", "assertive bold character")
    add("conviction", "confident assured touch")
    add("harmonic direction", "clear harmonic direction")
    add("harmonic", "expressive harmonic shading")

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for phrase in candidates:
        if phrase not in seen:
            seen.add(phrase)
            unique.append(phrase)

    if len(unique) < 4:
        # Supplement with regex-based cues
        for pattern, phrase in [
            (r'slow|adagio|lento|grave', 'patient unhurried pacing'),
            (r'fast|allegro|presto|vivace', 'energetic forward drive'),
            (r'song|sing|cantabile', 'singing cantabile line'),
            (r'dance|rhythmic', 'rhythmic dance character'),
            (r'counter|fug|poly', 'balanced contrapuntal voicing'),
            (r'rubato|flexible', 'flexible expressive rubato'),
            (r'soft|delicate', 'delicate soft touch'),
            (r'loud|bold', 'bold full-voiced sonority'),
            (r'dark|minor|somber', 'somber restrained palette'),
            (r'bright|major|luminous', 'bright luminous sonority'),
            (r'gentle|tender', 'warm rounded sonority'),
            (r'lyric|melod', 'lyrically shaped lines'),
            (r'virtuoso|brilliant|flash', 'brilliant virtuoso display'),
            (r'intimat|quiet|still', 'intimate confessional tone'),
            (r'nostalg|wistful|tender', 'nostalgic tender warmth'),
            (r'agitat|restless|storm', 'agitated restless energy'),
            (r'solemn|serious|grave', 'solemn measured gravity'),
            (r'playful|light|nimble', 'playful light character'),
            (r'flowing|seamless|smooth', 'flowing seamless continuity'),
            (r'graceful|elegant|refined', 'graceful flowing contour'),
            (r'pastoral|rural', 'pastoral rustic coloration'),
            (r'nocturnal|dream|reverie', 'nocturnal dreamy reverie'),
            (r'heroic|bold|triumph', 'heroic bold projection'),
            (r'melanchol|sad|lament', 'melancholic subdued tone'),
            (r'festive|joyful', 'festive brilliant energy'),
            (r'comic|humorous|whim', 'playful light character'),
            (r'mysterious|mystic|veiled', 'mysterious veiled sonority'),
            (r'ecstatic|heightened', 'ecstatic heightened intensity'),
            (r'turbulent|volatile', 'turbulent volatile energy'),
            (r'yearning|expressive reach', 'yearning expressive reach'),
            (r'wistful|nostalg', 'wistful tender nostalgia'),
            (r'dotted', 'crisp dotted-rhythm articulation'),
            (r'entr(e|ée)', 'ceremonial dignified gravity'),
        ]:
            if re.search(pattern, text_lower) and phrase not in seen:
                unique.append(phrase)
                seen.add(phrase)

    # If still very few, add generic performance fillers based on text analysis
    if len(unique) < 5:
        # Broad regex cues for performance-relevant content
        for pattern, phrase in [
            (r'compound meter|gigue', 'lively compound-meter bounce'),
            (r'improvisator|free|rhapsod', 'free improvisatory gesture'),
            (r'fug|strict.*section', 'tight fugal entries'),
            (r'binary|form|structure', 'clear formal architecture'),
            (r'texture|texture', 'carefully graded texture'),
            (r'modulat|key|harmonic', 'expressive harmonic shading'),
            (r'tempo|pulse|speed|pace', 'controlled measured pulse'),
            (r'dynamic|volume|loud|soft', 'sensitive dynamic shaping'),
            (r'articulat|touch|finger', 'clean precise articulation'),
            (r'phrase|melod|line|shape', 'careful phrase shaping'),
            (r'voic|layer|part|line', 'balanced voice projection'),
            (r'character|character|style', 'distinctive expressive character'),
            (r'expressive|expression', 'expressive emotional depth'),
            (r'clarity|clear|precise', 'clear crystalline clarity'),
            (r'control|precision|control', 'controlled precise execution'),
            (r'rhythm|meter|rhythmic', 'tight rhythmic spine'),
            (r'style|stylistic', 'stylistic authenticity'),
            (r'keyboard|piano|touch', 'responsive keyboard touch'),
        ]:
            if re.search(pattern, text_lower) and phrase not in seen:
                unique.append(phrase)
                seen.add(phrase)

    # Add universal performance phrases if still under threshold
    generic_filler = [
        'sensitive dynamic shaping',
        'careful phrase shaping',
        'clean precise articulation',
        'balanced voice projection',
        'controlled measured pulse',
        'expressive emotional depth',
        'stylistic clarity of line',
        'responsive keyboard touch',
        'clear formal architecture',
        'tight rhythmic spine',
    ]
    for g in generic_filler:
        if g not in seen:
            unique.append(g)
            seen.add(g)

    if not unique:
        unique = [
            'controlled measured pulse',
            'clean precise articulation',
            'sensitive dynamic shaping',
            'vocal shaped phrasing',
            'balanced voice projection',
            'expressive harmonic shading',
            'clear formal architecture',
            'stylistic clarity of line',
        ]

    # Build result targeting 20-30 words
    result_parts = []
    word_count = 0
    target_max = 30

    for phrase in unique:
        phrase_wc = len(phrase.split())
        if word_count + phrase_wc <= target_max:
            result_parts.append(phrase)
            word_count += phrase_wc
        elif word_count >= 20:
            break

    # If under 20 words, add more
    if word_count < 20:
        for phrase in unique:
            if phrase not in result_parts:
                result_parts.append(phrase)
                word_count += len(phrase.split())
                if word_count >= 20:
                    break

    # Final trim if still over 30
    if word_count > 30:
        trimmed = []
        wc = 0
        for phrase in result_parts:
            pwc = len(phrase.split())
            if wc + pwc <= 30:
                trimmed.append(phrase)
                wc += pwc
            else:
                break
        result_parts = trimmed

    return ', '.join(result_parts)


def process_file(filepath):
    """Process a single JSON file, add performance_gist."""
    try:
        with open(filepath) as f:
            data = json.load(f)

        interp_200 = data.get('compressed_interpretation_200', '')
        if not interp_200:
            return 'no_interp'

        gist = extract_performance_gist(interp_200)
        data['performance_gist'] = gist

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return 'ok'
    except Exception as e:
        return f'error: {e}'


# Process all files in batches
counts = {'ok': 0, 'no_interp': 0, 'error': 0}

for batch_num in [44, 45, 46, 47]:
    batch_files = file_paths[(batch_num - 44) * 40 : (batch_num - 44 + 1) * 40]
    batch_ok = 0
    batch_err = 0

    for fp in batch_files:
        result = process_file(fp)
        if result == 'ok':
            batch_ok += 1
            counts['ok'] += 1
        elif result == 'no_interp':
            counts['no_interp'] += 1
        else:
            batch_err += 1
            counts['error'] += 1
            print(f"  ERROR {fp}: {result}")

    print(f"Batch {batch_num}: {batch_ok} updated, {batch_err} errors ({len(batch_files)} total)")

print(f"\nOverall: {counts['ok']} updated, {counts['no_interp']} no interp, {counts['error']} errors")
