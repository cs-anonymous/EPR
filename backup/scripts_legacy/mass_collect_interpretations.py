#!/usr/bin/env python3
"""
Mass-collect piece interpretations using proxy-based web scraping.

Architecture:
1. For each composer, generate search queries
2. Use curl + proxy to search Bing/DuckDuckGo and extract quality URLs
3. Fetch the content from quality sources directly
4. Build per-piece interpretations from the collected text
5. Write JSONL results + per-piece JSON files

Usage:
  python3 scripts/mass_collect_interpretations.py [--composer "Composer Name"] [--batch N]

Without args, processes all 155 composers sequentially.
With --batch N, processes only batch N (1-indexed).
With --composer, processes only that composer.
"""

import json
import os
import re
import sys
import time
import subprocess
import unicodedata
from collections import defaultdict
from urllib.parse import quote_plus, unquote
import html as html_mod

PROXY = "http://127.0.0.1:7890"

# ============================================================================
# Network helpers
# ============================================================================

def fetch_url(url, max_time=12, retries=2):
    """Fetch URL via proxy using curl."""
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ['curl', '-k', '-s', f'--max-time={max_time}',
                 '-x', PROXY,
                 '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                 '-H', 'Accept-Language: en-US,en;q=0.9',
                 url],
                capture_output=True, text=True, timeout=max_time + 10
            )
            if result.returncode == 0 and result.stdout and len(result.stdout) > 100:
                return result.stdout
        except Exception:
            pass
        time.sleep(2)
    return None

def extract_text(html_content):
    """Strip HTML, return plain text."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    lines = [l.strip() for l in text.split('\n')]
    return '\n'.join(l for l in lines if len(l) > 20)

def search_bing(query):
    """Search Bing, return list of (url, title) tuples."""
    url = f'https://www.bing.com/search?q={quote_plus(query)}&count=10'
    html = fetch_url(url, max_time=15)
    if not html:
        return []

    results = []
    seen = set()

    # Bing uses <li class="b_algo"><h2><a href="...">title</a></h2>
    # and <cite>url</cite>
    # Also: <div class="b_attribution"><cite>url</cite>

    # Extract <a> tags within b_algo blocks
    blocks = re.findall(r'<li class="b_algo">(.*?)</li>', html, re.DOTALL)
    for block in blocks:
        a_match = re.search(r'<a[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', block)
        if a_match:
            href = a_match.group(1)
            title = re.sub(r'<[^>]+>', '', a_match.group(2)).strip()
            if href not in seen and href.startswith('http') and 'bing' not in href.lower():
                seen.add(href)
                results.append((href, title))

    return results[:8]

def search_duckduckgo(query):
    """Search DuckDuckGo HTML, return list of URLs."""
    url = f'https://html.duckduckgo.com/html/?q={quote_plus(query)}'
    html = fetch_url(url, max_time=12)
    if not html:
        return []

    results = []
    seen = set()

    # DDG uses <a class="result__a" href="//duckduckgo.com/l/?uddg=URL&rut=...">
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
    for link in links:
        match = re.search(r'uddg=([^&]+)', link)
        if match:
            real = html_mod.unescape(unquote(match.group(1)))
        elif link.startswith('http'):
            real = link
        else:
            continue
        if real not in seen and real.startswith('http'):
            seen.add(real)
            results.append(real)
        if len(results) >= 8:
            break

    return results

QUALITY_DOMAINS = [
    'wikipedia.org', 'imslp.org', 'henle.de', 'gramophone.co.uk',
    'carnegiehall.org', 'laphil.com', 'hyperion-records.co.uk',
    'britannica.com', 'allmusic.com', 'classical-music.com',
    'musicweb-international.com', 'interlude.hk', 'pianodao.com',
    'van-magazine.com', 'wqxr.org', 'sheetmusicinternational.com',
    'bach-cantatas.com', 'musescore.com',
]

def is_quality(url):
    u = url.lower()
    for d in QUALITY_DOMAINS:
        if d in u:
            return True
    return '.edu' in u

# ============================================================================
# Search strategy
# ============================================================================

def composer_search_queries(composer, unique_compositions):
    """Generate search queries for a composer."""
    queries = []

    # General composer query
    queries.append(f"{composer} piano works program notes")

    # Each unique composition
    for comp in unique_compositions[:20]:  # Cap at 20
        queries.append(f"{composer} {comp} analysis")
        queries.append(f"{composer} {comp} Wikipedia")

    return queries

# ============================================================================
# Composer KB (for fallback when web sources are sparse)
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

# ============================================================================
# Interpretation builder
# ============================================================================

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
    return [mood for mood, keywords in MOOD_KEYWORDS.items() if any(kw in text_lower for kw in keywords)]

def build_interpretation(piece, composer_text, evidence_sources):
    """Build interpretation JSON from piece metadata + collected text."""
    piece_id = piece['piece_id']
    composer = piece['composer']
    composition = piece['composition']
    movement = piece['movement']

    # Lookup composer style
    style_id, features = None, None
    for name, (s, f) in COMPOSER_KB.items():
        if name.lower() in composer.lower() or composer.lower() in name.lower():
            style_id, features = s, f
            break
    if not style_id:
        style_id = "Romantic-era piano repertoire"
    if not features:
        features = "distinctive melodic and harmonic character"

    # Extract moods from collected text
    found_moods = extract_moods(composer_text)
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
    if any(m in found_moods for m in ['dance-like']) or any(d in style_id.lower() for d in ['dance', 'tango', 'choro', 'ragtime']):
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
    elif any(d in style_id.lower() for d in ['dance', 'tango', 'choro', 'ragtime']):
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
    elif any(d in style_id.lower() for d in ['dance', 'tango', 'choro', 'ragtime']):
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

# ============================================================================
# Main processing
# ============================================================================

def process_composer(batch_data):
    """Process all pieces by one composer."""
    composer = batch_data['composer']
    pieces = batch_data['pieces']
    unique_comps = batch_data['unique_compositions']

    print(f"\n{'='*60}")
    print(f"Processing: {composer} ({len(pieces)} pieces, {len(unique_comps)} unique works)")
    print(f"{'='*60}")

    # Collect text from web sources
    all_text = ""
    evidence_sources = []
    urls_visited = set()

    queries = composer_search_queries(composer, unique_comps)

    for i, q in enumerate(queries):
        print(f"  [{i+1}/{len(queries)}] Searching: {q[:80]}...")

        # Try Bing first
        results = search_bing(q)
        time.sleep(3)  # Delay between searches

        # If Bing didn't return enough, try DuckDuckGo
        if len(results) < 3:
            ddg_results = search_duckduckgo(q)
            for url in ddg_results:
                if url not in urls_visited:
                    results.append((url, url.split('/')[-1][:80]))

        # Fetch top quality source
        for url, title in results[:3]:
            if url in urls_visited:
                continue
            if is_quality(url):
                print(f"    Fetching: {url[:80]}...")
                content = fetch_url(url, max_time=15)
                if content and len(content) > 500:
                    text = extract_text(content)
                    if len(text) > 100:
                        all_text += text[:4000] + "\n\n"
                        evidence_sources.append({
                            "type": "web_source",
                            "url": url,
                            "title": title[:80]
                        })
                        urls_visited.add(url)
                break
            time.sleep(0.5)

        # Cap the total text
        if len(all_text) > 50000:
            all_text = all_text[:50000]
            break

    print(f"  Collected {len(all_text)} chars of text from {len(evidence_sources)} sources")

    # Build per-piece interpretations
    results = []
    for piece in pieces:
        interp = build_interpretation(piece, all_text, evidence_sources)
        results.append(interp)

        # Write to piece folder
        output_folder = piece['output_folder']
        full_path = os.path.join('/home/sy/EPR', output_folder, 'piece_interpretation.json')
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            json.dump(interp, f, ensure_ascii=False, indent=2)

    # Write JSONL
    jsonl_path = f'data/piece_interpretations/composer_search_{composer.replace(" ", "_").replace("/", "_")}.jsonl'
    with open(jsonl_path, 'w') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f"  Written {len(results)} piece interpretations")
    return len(results)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--composer', type=str, default=None, help='Process only this composer')
    parser.add_argument('--batch', type=int, default=None, help='Process only batch N (1-indexed)')
    parser.add_argument('--start', type=int, default=0, help='Start from batch N')
    parser.add_argument('--limit', type=int, default=None, help='Process N composers')
    args = parser.parse_args()

    # Load all composer batches
    batch_files = sorted([
        f for f in os.listdir('data/piece_interpretations')
        if f.startswith('composer_batch_') and f.endswith('.json')
    ])

    if args.start > 0:
        batch_files = batch_files[args.start:]
    if args.limit:
        batch_files = batch_files[:args.limit]

    print(f"Total composer batches to process: {len(batch_files)}")

    total_pieces = 0
    for i, bf in enumerate(batch_files):
        batch_path = f'data/piece_interpretations/{bf}'
        with open(batch_path) as f:
            batch_data = json.load(f)

        # Filter by composer or batch if specified
        if args.composer and batch_data['composer'] != args.composer:
            continue
        if args.batch and i + 1 != args.batch:
            continue

        n = process_composer(batch_data)
        total_pieces += n

    print(f"\n{'='*60}")
    print(f"Total pieces processed: {total_pieces}")

if __name__ == '__main__':
    main()
