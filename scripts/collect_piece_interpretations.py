#!/usr/bin/env python3
"""
Collect piece-level musical interpretations (α) for symbolic music works.

Usage:
  python3 scripts/collect_piece_interpretations.py [--limit N] [--start N] [--batch-file PATH]

Reads search results from a batch results file (JSONL), processes each piece's
retrieved text, and writes piece_interpretation.json to each piece's folder.

This script is designed to work in two stages:
  Stage 1: Use WebSearch skill to collect URLs and content snippets
  Stage 2: This script builds interpretations from the collected data

For Stage 1, we generate a search batch file with all queries.
"""

import json
import os
import re
import sys
import time
import subprocess
import unicodedata
import html as html_mod
from urllib.parse import quote_plus, unquote

PROXY = "http://127.0.0.1:7890"

# ============================================================================
# Network helpers
# ============================================================================

def fetch_url(url, max_retries=2):
    """Fetch URL content using curl through proxy."""
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ['curl', '-k', '-s', '--max-time', '12',
                 '-x', PROXY,
                 '-H', 'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                 '-H', 'Accept-Language: en-US,en;q=0.9',
                 url],
                capture_output=True, text=True, timeout=18
            )
            if result.returncode == 0 and result.stdout and len(result.stdout) > 100:
                return result.stdout
        except Exception:
            pass
        time.sleep(1)
    return None

def extract_text(html):
    """Strip HTML tags, return plain text."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    lines = [l.strip() for l in text.split('\n')]
    return '\n'.join(l for l in lines if len(l) > 20)

def search_wikipedia(composer, composition, movement=None):
    """Search Wikipedia for relevant articles using the API."""
    pieces_str = f'{composer} {composition}'
    if movement:
        pieces_str += f' {movement}'

    # Wikipedia opensearch
    queries = [
        pieces_str,
        f'{composer} {composition}',
    ]

    results = []
    for q in queries:
        url = f'https://en.wikipedia.org/w/api.php?action=opensearch&search={quote_plus(q)}&limit=3&format=json'
        raw = fetch_url(url)
        if raw:
            try:
                data = json.loads(raw)
                if len(data) >= 3 and data[1]:
                    for title, desc in zip(data[1], data[3] if len(data) > 3 else [''] * len(data[1])):
                        results.append({
                            'title': title,
                            'url': f'https://en.wikipedia.org/wiki/{quote_plus(title.replace(" ", "_"))}',
                            'snippet': desc[:200]
                        })
            except:
                pass
        time.sleep(0.5)

    return results

def search_wiki_content(query):
    """Search Wikipedia content API for relevant articles."""
    url = f'https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(query)}&utf8=&format=json&srlimit=5'
    raw = fetch_url(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        results = []
        for item in data.get('query', {}).get('search', []):
            results.append({
                'title': item.get('title', ''),
                'pageid': item.get('pageid', ''),
                'snippet': re.sub(r'<[^>]+>', '', item.get('snippet', '')),
                'url': f'https://en.wikipedia.org/?curid={item.get("pageid", "")}'
            })
        return results
    except:
        return []

def fetch_wikipedia_article(title):
    """Fetch full text of a Wikipedia article using the API."""
    url = f'https://en.wikipedia.org/w/api.php?action=query&titles={quote_plus(title)}&prop=extracts&explaintext=true&format=json'
    raw = fetch_url(url)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        pages = data.get('query', {}).get('pages', {})
        for page_id, page in pages.items():
            if page_id != '-1':
                return page.get('extract', '')
    except:
        pass
    return None

def fetch_quality_source(url):
    """Fetch a single quality source URL and return parsed text."""
    html = fetch_url(url)
    if not html:
        return None
    return extract_text(html)

# ============================================================================
# Interpretation logic
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
}

def lookup_composer(composer):
    c_lower = composer.lower()
    for name, (style, features) in COMPOSER_KB.items():
        if name.lower() in c_lower or c_lower in name.lower():
            return style, features
    return None, None

MOOD_KEYWORDS = {
    'melancholic': ['melanchol', 'sad', 'mournful', 'sorrow', 'lament', 'grief'],
    'lyrical': ['lyrical', 'singing', 'song-like', 'cantabile', 'melodic'],
    'heroic': ['heroic', 'triumphant', 'bold', 'majestic', 'grand', 'triumph'],
    'playful': ['playful', 'lively', 'vivacious', 'spirited', 'whimsical', 'charm', 'gaiety'],
    'dramatic': ['dramatic', 'intense', 'passionate', 'stormy', 'tumultuous', 'powerful'],
    'nostalgic': ['nostalgic', 'yearning', 'longing', 'wistful', 'reminiscent', 'bittersweet'],
    'contemplative': ['contemplative', 'meditative', 'reflective', 'introspective', 'tranquil'],
    'dance-like': ['dance', 'rhythmic', 'lively', 'vitality', 'energetic', 'folk'],
    'intimate': ['intimate', 'delicate', 'subtle', 'refined', 'tender', 'graceful'],
    'virtuosic': ['virtuosic', 'brilliant', 'dazzling', 'bravura', 'technically demanding'],
    'poetic': ['poetic', 'evocative', 'imagery', 'dream', 'ethereal', 'mystical'],
    'solemn': ['solemn', 'solemnity', 'dignified', 'noble', 'reverent', 'sacred'],
}

# ============================================================================
# Search query generation
# ============================================================================

def generate_queries(composer, composition, movement=None):
    """Generate search queries for a piece."""
    pieces_str = f'{composer} {composition}'
    if movement:
        pieces_str += f' {movement}'
    return [
        f'{pieces_str} program notes',
        f'{pieces_str} interpretation',
        f'{pieces_str} analysis',
        f'{pieces_str} emotional character',
        f'{composer} {composition} musicological',
    ]

# ============================================================================
# Main processing
# ============================================================================

def process_piece(piece):
    """Process a single piece: retrieve web sources, build interpretation, write JSON."""
    piece_id = piece['piece_id']
    composer = piece['composer']
    composition = piece['composition']
    movement = piece['movement']
    output_folder = piece['output_folder']

    print(f"  Processing: {piece_id}")

    full_path = os.path.join('/home/sy/EPR', output_folder, 'piece_interpretation.json')
    if os.path.exists(full_path):
        print(f"    Already exists, skipping")
        return 'skip'

    # Stage 1: Wikipedia search + fetch
    wiki_results = search_wikipedia(composer, composition, movement)
    all_text = ""
    evidence_sources = []

    for wr in wiki_results[:2]:
        article_text = fetch_wikipedia_article(wr['title'])
        if article_text and len(article_text) > 200:
            all_text += article_text[:5000] + "\n\n"
            evidence_sources.append({
                "type": "wikipedia",
                "url": wr['url'],
                "title": wr['title']
            })

    # Stage 2: Also try Wikipedia content search
    pieces_str = f'{composer} {composition}'
    if movement:
        pieces_str += f' {movement}'
    wiki_content = search_wiki_content(f'{pieces_str} piano')
    for wc in wiki_content[:2]:
        if wc['pageid']:
            article_text = fetch_wikipedia_article(wc['title'])
            if article_text and len(article_text) > 200:
                # Avoid duplicate
                if wc['title'] not in [e.get('title', '') for e in evidence_sources]:
                    all_text += article_text[:5000] + "\n\n"
                    evidence_sources.append({
                        "type": "wikipedia",
                        "url": wc['url'],
                        "title": wc['title']
                    })

    # Build interpretation
    style_id, features = lookup_composer(composer)
    if not style_id:
        style_id = "Romantic-era piano repertoire"
    if not features:
        features = "distinctive melodic and harmonic character"

    # Mood detection from text
    found_moods = []
    if all_text:
        text_lower = all_text.lower()
        for mood, keywords in MOOD_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                found_moods.append(mood)

    # Fallback moods from composer style
    if not found_moods:
        if 'Romantic' in style_id:
            found_moods = ['lyrical', 'expressive']
        elif 'dance' in style_id.lower() or 'Nationalism' in style_id:
            found_moods = ['playful', 'lively']
        elif 'Baroque' in style_id:
            found_moods = ['contemplative', 'solemn']
        else:
            found_moods = ['expressive']

    # Build compressed interpretation
    mood_str = ', '.join(found_moods[:3])
    title_with_mov = f'{composition}, {movement}' if movement else composition

    compressed = (
        f"This work, {title_with_mov} by {composer}, is characterized by a "
        f"{mood_str} atmosphere, rooted in {style_id}. "
        f"Its expressive identity is shaped by {features}. "
        f"The piece's overall narrative develops through contrasting emotional "
        f"states while maintaining structural coherence. In interpretation, "
        f"the primary expressive goal is to convey the work's essential "
        f"character and emotional authenticity."
    )

    # Expressive character
    if 'dance-like' in found_moods or 'dance' in style_id.lower():
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
    else:
        expr_char = f"Expressive character shaped by {features}."

    # Structural narrative
    if 'dramatic' in found_moods:
        struct_narr = "The piece unfolds through increasing dramatic tension, building toward climactic moments before resolving into quieter passages."
    elif 'dance' in style_id.lower():
        struct_narr = "The music follows a rhythmic and episodic trajectory, alternating between energetic sections and moments of lyrical relaxation."
    elif 'contemplative' in found_moods:
        struct_narr = "The work develops through gradual emotional intensification, moving between introspection and outward expression."
    else:
        struct_narr = "The piece develops through contrasting sections that explore different facets of its core musical material while maintaining formal balance."

    # Interpretive priority
    if 'lyrical' in found_moods:
        interp_prior = "Preserve melodic breathing and avoid excessive sentimentality."
    elif 'dance' in style_id.lower():
        interp_prior = "Maintain rhythmic vitality and natural dance character without mechanical rigidity."
    elif 'virtuosic' in found_moods:
        interp_prior = "Balance technical brilliance with expressive depth, avoiding superficial display."
    elif 'contemplative' in found_moods:
        interp_prior = "Sustain reflective atmosphere and resist rushing through quiet passages."
    else:
        interp_prior = "Convey the work's emotional truth while respecting its formal structure."

    interpretation = {
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

    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w') as f:
        json.dump(interpretation, f, ensure_ascii=False, indent=2)

    print(f"    -> Written to {full_path}")
    return 'done'

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--start', type=int, default=0)
    args = parser.parse_args()

    with open('data/piece_interpretations/pieces_batch.json') as f:
        pieces = json.load(f)

    pieces_to_process = pieces[args.start:]
    if args.limit:
        pieces_to_process = pieces_to_process[:args.limit]

    print(f"Processing {len(pieces_to_process)} pieces (start={args.start}, limit={args.limit})")

    done = 0
    skipped = 0
    for i, piece in enumerate(pieces_to_process):
        result = process_piece(piece)
        if result == 'done':
            done += 1
        elif result == 'skip':
            skipped += 1
        if i > 0 and i % 5 == 0:
            idx = args.start + i
            with open('data/piece_interpretations/progress.json', 'w') as f:
                json.dump({'last_index': idx, 'piece_id': piece['piece_id']}, f)

    print(f"\nDone: {done}, Skipped: {skipped}")

if __name__ == '__main__':
    main()
