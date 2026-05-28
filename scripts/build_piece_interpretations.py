#!/usr/bin/env python3
"""
Stage 2: Build piece interpretations from search results.

Reads search result data from data/piece_interpretations/search_results.jsonl
and generates piece_interpretation.json files in each piece's folder.

Usage:
  python3 scripts/build_piece_interpretations.py [--limit N] [--start N]
"""

import json
import os
import re
import unicodedata

# ============================================================================
# Interpretation knowledge base
# ============================================================================

COMPOSER_KB = {
    "Frédéric Chopin": ("Polish Romanticism", "bel canto melody, rubato expressivity, nocturnal intimacy"),
    "Franz Liszt": ("Hungarian Romantic virtuosity", "dramatic narrative, pianistic brilliance, programmatic ambition"),
    "Johann Sebastian Bach": ("Baroque counterpoint", "architectural clarity, contrapuntal density, spiritual depth"),
    "Wolfgang Amadeus Mozart": ("Classical elegance", "formal clarity, conversational grace, dramatic subtlety"),
    "Ludwig van Beethoven": ("Transitional Classical-Romantic", "heroic struggle, structural innovation, emotional extremity"),
    "Claude Debussy": ("French Impressionism", "harmonic color, atmospheric suggestion, timbral nuance"),
    "Maurice Ravel": ("French Impressionism", "orchestral precision, exotic harmony, refined craftsmanship"),
    "Robert Schumann": ("German Romanticism", "poetic introspection, dual-natured expressivity, literary association"),
    "Johannes Brahms": ("German Romantic Classicism", "structural density, rhythmic complexity, autumnal warmth"),
    "Isaac Albéniz": ("Spanish Nationalism", "flamenco-inflected rhythms, Iberian folk colors, dance vitality"),
    "Enrique Granados": ("Spanish Romanticism", "lyrical melancholy, Goyesque elegance, national character"),
    "Sergei Rachmaninoff": ("Russian Late Romanticism", "lush harmonic richness, expansive melodies, nostalgic yearning"),
    "Alexander Scriabin": ("Russian Symbolism", "mystical aspiration, harmonic ambiguity, ecstatic transcendence"),
    "Domenico Scarlatti": ("Late Baroque keyboard style", "virtuosic figuration, Iberian folk inflections, harmonic daring"),
    "Franz Schubert": ("Austrian Romantic lyricism", "song-like melodies, harmonic wandering, existential longing"),
    "Mily Balakirev": ("Russian Nationalism", "orientalist color, folk-derived material, dramatic narrative"),
    "Modest Mussorgsky": ("Russian Realism", "raw emotional directness, folk harmony, pictorial vividness"),
    "Pyotr Ilyich Tchaikovsky": ("Russian Romanticism", "dramatic pathos, sweeping lyricism, theatrical grandeur"),
    "César Franck": ("French Romantic mysticism", "cyclic form, harmonic luminosity, spiritual contemplation"),
    "Mikhail Glinka": ("Russian Romanticism", "song-derived lyricism, national character, poetic tenderness"),
    "Zequinha de Abreu": ("Brazilian choro", "dance-like vitality, rhythmic playfulness, Brazilian folk character"),
    "Carl Reinecke": ("German Romantic salon style", "graceful lyricism, accessible charm, domestic elegance"),
    "Hugo Wolf": ("German Lieder tradition", "poetic intensity, harmonic precision, psychological depth"),
    "Fats Waller": ("Jazz stride piano", "rhythmic exuberance, improvisatory freedom, popular song vitality"),
    "Scott Joplin": ("American ragtime", "syncopated vitality, formal elegance, popular sophistication"),
    "Erik Satie": ("French avant-garde", "austere simplicity, ironic detachment, meditative stillness"),
    "Sergei Prokofiev": ("Russian Modernism", "sardonic wit, motoric energy, neoclassical clarity"),
    "George Gershwin": ("American jazz-classical fusion", "syncopated elegance, blues inflection, urban energy"),
    "Béla Bartók": ("Hungarian modernism", "folk-derived rhythm, percussive vitality, modal harmonic language"),
    "Edvard Grieg": ("Norwegian Nationalism", "folk-inflected melody, Nordic atmosphere, intimate lyricism"),
    "Gabriel Fauré": ("French late Romanticism", "refined harmonic subtlety, lyrical restraint, spiritual elegance"),
    "Henry Lemoine": ("French pedagogical Romanticism", "graceful melody, accessible charm, technical refinement"),
    "Felix Mendelssohn": ("German Romantic Classicism", "lyrical clarity, contrapuntal elegance, Mendelssohnian lightness"),
    "Jean-Baptiste Duvernoy": ("French pedagogical tradition", "graceful lyricism, technical clarity, salon elegance"),
    "Carl Czerny": ("Viennese pedagogical tradition", "brilliant passagework, technical refinement, classical form"),
    "George Frideric Handel": ("Baroque grandeur", "contrapuntal mastery, dramatic clarity, ceremonial dignity"),
    "Joseph Haydn": ("Classical wit and invention", "formal playfulness, harmonic surprise, conversational elegance"),
    "Jean-Philippe Rameau": ("French Baroque", "harmonic daring, dance-derived rhythms, rhetorical elegance"),
    "Henry Purcell": ("English Baroque", "rhetorical directness, chromatic expressivity, dance vitality"),
    "Muzio Clementi": ("Classical keyboard style", "brilliant passagework, structural clarity, pianistic invention"),
    "Louis-Claude Daquin": ("French Rococo", "graceful ornamentation, harpsichord elegance, pictorial charm"),
    "Johann Pachelbel": ("German Baroque", "contrapuntal clarity, chorale-based structure, contemplative depth"),
    "François Couperin": ("French Rococo", "character piece elegance, ornamental refinement, pictorial suggestion"),
    "Cécile Chaminade": ("French salon Romanticism", "graceful lyricism, accessible charm, feminine expressivity"),
    "Aleksandr Scriabin": ("Russian Symbolism", "mystical aspiration, harmonic ambiguity, ecstatic transcendence"),
    "Carlos Gardel": ("Argentine tango", "passionate melancholy, dance rhythm, urban nostalgia"),
    "Jelly Roll Morton": ("Jazz ragtime", "syncopated exuberance, improvisatory flair, New Orleans vitality"),
    "James Scott": ("American ragtime", "syncopated elegance, formal sophistication, rhythmic vitality"),
    "Tom Turpin": ("American ragtime", "syncopated vitality, popular song character, urban energy"),
    "George Botsford": ("American ragtime", "syncopated vitality, popular sophistication, rhythmic drive"),
    "Theron C. Bennett": ("American ragtime", "syncopated exuberance, popular song energy, rhythmic playfulness"),
    "James P. Johnson": ("Jazz stride piano", "virtuosic syncopation, improvisatory freedom, Harlem energy"),
    "Ernesto Nazareth": ("Brazilian tango-choro", "dance-like lyricism, Brazilian folk character, rhythmic subtlety"),
    "Chiquinha Gonzaga": ("Brazilian popular music", "dance vitality, national character, accessible charm"),
    "Camille Saint-Saëns": ("French Romantic Classicism", "formal elegance, technical refinement, classical restraint"),
    "Charles-Valentin Alkan": ("French Romantic virtuosity", "extreme technical demands, harmonic daring, monumental scale"),
    "Louise Farrenc": ("French Romanticism", "classical clarity, lyrical warmth, structural balance"),
    "Cécile Chaminade": ("French salon Romanticism", "graceful lyricism, accessible charm, feminine expressivity"),
    "Louis Vierne": ("French Romantic organ tradition", "harmonic richness, spiritual depth, late Romantic expressivity"),
    "Lili Boulanger": ("French early modernism", "harmonic subtlety, spiritual intensity, lyrical refinement"),
    "Gabriel Fauré": ("French late Romanticism", "refined harmonic subtlety, lyrical restraint, spiritual elegance"),
    "Jean-Philippe Rameau": ("French Baroque", "harmonic daring, dance-derived rhythms, rhetorical elegance"),
    "Louis-Claude Daquin": ("French Rococo", "graceful ornamentation, harpsichord elegance, pictorial charm"),
    "François Couperin": ("French Rococo", "character piece elegance, ornamental refinement, pictorial suggestion"),
    "Ignaz Pleyel": ("Classical elegance", "formal clarity, accessible charm, pedagogical grace"),
    "Muzio Clementi": ("Classical keyboard style", "brilliant passagework, structural clarity, pianistic invention"),
    "John Field": ("Irish Romanticism", "nocturnal lyricism, gentle expressivity, precursor to Chopin"),
    "Friedrich Kuhlau": ("Classical-Romantic transition", "formal clarity, melodic charm, technical refinement"),
    "Friedrich Burgmüller": ("German pedagogical Romanticism", "graceful character pieces, accessible expressivity, technical elegance"),
    "Anton Diabelli": ("Viennese Classical style", "accessible charm, dance character, pedagogical clarity"),
    "Carl Maria von Weber": ("German Romanticism", "dramatic narrative, folk-inflected melody, virtuosic display"),
    "Carl Philipp Emanuel Bach": ("Empfindsamer Stil", "rhetorical expressivity, emotional immediacy, formal innovation"),
    "Johann Christian Bach": ("Classical galant style", "melodic elegance, Italianate lyricism, formal clarity"),
    "Johann Ernst Bach": ("German Baroque", "contrapuntal clarity, chorale-based structure, formal discipline"),
    "Johann Ludwig Krebs": ("German Baroque", "contrapuntal mastery, chorale elaboration, Bach-influenced style"),
    "Johann Anton André": ("Classical style", "formal clarity, Mozartian influence, accessible charm"),
    "Johann Strauss Jr.": ("Viennese light music", "dance elegance, waltz character, popular sophistication"),
    "Johann Strauss Sr.": ("Viennese light music", "dance vitality, waltz tradition, popular charm"),
    "Henry Purcell": ("English Baroque", "rhetorical directness, chromatic expressivity, dance vitality"),
    "Henry Lemoine": ("French pedagogical Romanticism", "graceful melody, accessible charm, technical refinement"),
    "Henry Lodge": ("British light classical", "accessible melody, salon character, domestic elegance"),
    "François-Joseph Gossec": ("French Classical", "formal elegance, orchestral clarity, Revolutionary-era character"),
    "Georges Bizet": ("French Romanticism", "Mediterranean color, dramatic vitality, melodic charm"),
    "Gioacchino Rossini": ("Italian Romantic opera", "dramatic brilliance, bel canto lyricism, comic vitality"),
    "Giuseppe Martucci": ("Italian Romantic Classicism", "structural clarity, Brahmsian influence, formal elegance"),
    "Gottfried Heinrich Stölzel": ("German Baroque", "chorale-based structure, contrapuntal clarity, sacred character"),
    "Gustav Holst": ("English early modernism", "modal harmony, folk-inflected melody, mystical atmosphere"),
    "Hans Leo Hassler": ("German Renaissance-Baroque transition", "contrapuntal elegance, madrigal influence, sacred character"),
    "Henri Bertini": ("French pedagogical tradition", "technical refinement, graceful melody, accessible charm"),
    "Henrique Oswald": ("Brazilian Romanticism", "lyrical warmth, national character, accessible elegance"),
    "Henry Hiles": ("Victorian English music", "accessible melody, pedagogical purpose, domestic elegance"),
    "Homer Newton Bartlett": ("American salon music", "accessible charm, popular song character, domestic elegance"),
    "Ignaz Pleyel": ("Classical elegance", "formal clarity, accessible charm, pedagogical grace"),
    "Ira David Sankey": ("American gospel hymn", "devotional character, accessible melody, popular religious expression"),
    "Jack Glogau": ("American popular music", "popular song character, accessible charm, ragtime influence"),
    "Jacques Offenbach": ("French operetta", "comic vitality, dance elegance, popular sophistication"),
    "Johan Halvorsen": ("Norwegian Nationalism", "folk-inflected melody, Nordic character, dance vitality"),
    "Johann Pachelbel": ("German Baroque", "contrapuntal clarity, chorale-based structure, contemplative depth"),
}

def lookup_composer(composer):
    c_lower = composer.lower()
    for name, (style, features) in COMPOSER_KB.items():
        if name.lower() in c_lower or c_lower in name.lower():
            return style, features
    return None, None

MOOD_KEYWORDS = {
    'melancholic': ['melanchol', 'sad', 'mournful', 'sorrow', 'lament', 'grief', 'anguish'],
    'lyrical': ['lyrical', 'singing', 'song-like', 'cantabile', 'melodic'],
    'heroic': ['heroic', 'triumphant', 'bold', 'majestic', 'grand', 'triumph'],
    'playful': ['playful', 'lively', 'vivacious', 'spirited', 'whimsical', 'charm', 'gaiety'],
    'dramatic': ['dramatic', 'intense', 'passionate', 'stormy', 'tumultuous', 'powerful'],
    'nostalgic': ['nostalgic', 'yearning', 'longing', 'wistful', 'reminiscent', 'bittersweet'],
    'contemplative': ['contemplative', 'meditative', 'reflective', 'introspective', 'tranquil', 'serene'],
    'dance-like': ['dance', 'rhythmic', 'lively', 'vitality', 'energetic', 'folk'],
    'intimate': ['intimate', 'delicate', 'subtle', 'refined', 'tender', 'graceful'],
    'virtuosic': ['virtuosic', 'brilliant', 'dazzling', 'bravura', 'technically demanding'],
    'poetic': ['poetic', 'evocative', 'imagery', 'dream', 'ethereal', 'mystical'],
    'solemn': ['solemn', 'solemnity', 'dignified', 'noble', 'reverent', 'sacred'],
}

def extract_moods(text):
    if not text:
        return []
    text_lower = text.lower()
    found = []
    for mood, keywords in MOOD_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(mood)
    return found

def build_interpretation(piece, search_text, evidence_sources):
    """Build interpretation JSON from piece metadata + retrieved text."""
    piece_id = piece['piece_id']
    composer = piece['composer']
    composition = piece['composition']
    movement = piece['movement']

    style_id, features = lookup_composer(composer)
    if not style_id:
        style_id = "Romantic-era piano repertoire"
    if not features:
        features = "distinctive melodic and harmonic character"

    # Mood detection
    found_moods = extract_moods(search_text)
    if not found_moods:
        if 'Romantic' in style_id:
            found_moods = ['lyrical', 'expressive']
        elif 'dance' in style_id.lower() or 'Nationalism' in style_id:
            found_moods = ['playful', 'lively']
        elif 'Baroque' in style_id:
            found_moods = ['contemplative', 'solemn']
        else:
            found_moods = ['expressive']

    mood_str = ', '.join(found_moods[:3])
    title_with_mov = f'{composition}, {movement}' if movement else composition

    # Build compressed interpretation
    compressed = (
        f"A {mood_str} work in the {style_id} tradition, shaped by {features}. "
        f"{struct_narr} "
        f"{interp_prior}"
    )

    # Expressive character
    if 'dance-like' in found_moods or 'dance' in style_id.lower() or 'tango' in style_id.lower() or 'choro' in style_id.lower() or 'ragtime' in style_id.lower():
        expr_char = "Dance-like vitality combined with rhythmic playfulness and folk character."
    elif 'virtuosic' in found_moods:
        expr_char = "Brilliant virtuosity balanced with lyrical expressivity."
    elif 'dramatic' in found_moods:
        expr_char = "Dramatic intensity with strong emotional contrasts."
    elif 'intimate' in found_moods or 'contemplative' in found_moods:
        expr_char = "Intimate lyricism with reflective depth and poetic subtlety."
    elif 'lyrical' in found_moods:
        expr_char = "Song-like lyricism with expressive warmth and melodic fluency."
    elif 'solemn' in found_moods:
        expr_char = "Solemn dignity with contemplative depth and spiritual resonance."
    elif 'poetic' in found_moods:
        expr_char = "Poetic expressivity with evocative imagery and atmospheric subtlety."
    elif 'heroic' in found_moods:
        expr_char = "Heroic grandeur with dramatic intensity and structural boldness."
    elif 'nostalgic' in found_moods:
        expr_char = "Nostalgic warmth with yearning melodies and bittersweet harmony."
    else:
        expr_char = f"Expressive character shaped by {features}."

    # Structural narrative
    if 'dramatic' in found_moods:
        struct_narr = "The piece unfolds through increasing dramatic tension, building toward climactic moments before resolving into quieter passages."
    elif 'dance' in style_id.lower() or 'tango' in style_id.lower() or 'choro' in style_id.lower() or 'ragtime' in style_id.lower():
        struct_narr = "The music follows a rhythmic and episodic trajectory, alternating between energetic sections and moments of lyrical relaxation."
    elif 'contemplative' in found_moods:
        struct_narr = "The work develops through gradual emotional intensification, moving between introspection and outward expression."
    elif 'Baroque' in style_id:
        struct_narr = "The piece develops through contrapuntal interplay and harmonic exploration while maintaining formal architectural coherence."
    elif 'Classical' in style_id:
        struct_narr = "The work unfolds through clear formal sections, balancing thematic development with conversational grace."
    else:
        struct_narr = "The piece develops through contrasting sections that explore different facets of its core musical material while maintaining formal balance."

    # Interpretive priority
    if 'lyrical' in found_moods:
        interp_prior = "Preserve melodic breathing and avoid excessive sentimentality."
    elif 'dance' in style_id.lower() or 'tango' in style_id.lower() or 'choro' in style_id.lower() or 'ragtime' in style_id.lower():
        interp_prior = "Maintain rhythmic vitality and natural dance character without mechanical rigidity."
    elif 'virtuosic' in found_moods:
        interp_prior = "Balance technical brilliance with expressive depth, avoiding superficial display."
    elif 'contemplative' in found_moods:
        interp_prior = "Sustain reflective atmosphere and resist rushing through quiet passages."
    elif 'poetic' in found_moods:
        interp_prior = "Preserve atmospheric subtlety and resist over-dramatization."
    elif 'Baroque' in style_id:
        interp_prior = "Maintain contrapuntal clarity and rhythmic discipline while allowing expressive warmth."
    else:
        interp_prior = "Convey the work's emotional truth while respecting its formal structure."

    return {
        "piece_id": piece_id,
        "composer": composer,
        "composition": composition,
        "movement": movement,
        "alpha_type": "piece_level_interpretation",
        "scope": "piece",
        "performance_specific": False,
        "teaching_specific": False,
        "language": "en",
        "mood": found_moods,
        "expressive_character": expr_char,
        "structural_narrative": struct_narr,
        "stylistic_identity": style_id,
        "interpretive_priority": interp_prior,
        "compressed_interpretation": compressed,
        "evidence_sources": evidence_sources[:5],
    }

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--results', type=str, default='data/piece_interpretations/search_results.jsonl',
                        help='Path to search results JSONL file')
    args = parser.parse_args()

    with open('data/piece_interpretations/pieces_batch.json') as f:
        pieces = json.load(f)

    # Load search results
    search_data = {}
    if os.path.exists(args.results):
        with open(args.results) as f:
            for line in f:
                line = line.strip()
                if line:
                    item = json.loads(line)
                    search_data[item['piece_id']] = item

    pieces_to_process = pieces[args.start:]
    if args.limit:
        pieces_to_process = pieces_to_process[:args.limit]

    print(f"Processing {len(pieces_to_process)} pieces (start={args.start}, limit={args.limit})")
    print(f"Loaded {len(search_data)} search results")

    done = 0
    skipped = 0
    no_search = 0
    for i, piece in enumerate(pieces_to_process):
        piece_id = piece['piece_id']
        output_folder = piece['output_folder']
        full_path = os.path.join('/home/sy/EPR', output_folder, 'piece_interpretation.json')

        if os.path.exists(full_path):
            skipped += 1
            continue

        sr = search_data.get(piece_id)
        search_text = sr.get('text', '') if sr else ''
        evidence = sr.get('evidence_sources', []) if sr else []

        if not search_text:
            no_search += 1

        interp = build_interpretation(piece, search_text, evidence)

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            json.dump(interp, f, ensure_ascii=False, indent=2)

        done += 1

    print(f"Done: {done}, Skipped: {skipped}, No search data: {no_search}")

if __name__ == '__main__':
    main()
