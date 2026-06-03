#!/usr/bin/env python3
"""Add performance_gist field to piece_interpretation.json files."""

import json
import sys

FILES_08 = [
    "/home/sy/EPR/data/miditsv/Schubert,_Franz/Piano_Sonata_No.20_in_A_major,_D.959/3._Scherzo_(Allegro_vivace)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Glinka,_Mikhail/Nocturne_in_E_flat_major/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Ballade_No.3_in_A_flat_major,_Op.47/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Schubert,_Franz/2_Scherzos,_D.593/1._Allegretto_(B_flat_major)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Tchaikovsky,_Pyotr_Ilyich/The_Nutcracker_(ballet),_Op.71/Act_2._12d._Trépak:_Danse_russe._Tempo_di_Trepak,_molto_vivace/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mozart,_Wolfgang_Amadeus/Piano_Sonata_No.2_in_F_major,_K.280/1._Allegro_assai/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Scarlatti,_Domenico/Keyboard_Sonata_in_G_minor,_K.4/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Tchaikovsky,_Pyotr_Ilyich/The_Nutcracker_(ballet),_Op.71/Overture._Allegro_giusto/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Ravel,_Maurice/Prélude,_M.65/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Berceuse_in_D_flat_major,_Op.57/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Joplin,_Scott/Pine_Apple_Rag/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Mazurkas,_Op.7/3._Mazurka_(F_minor)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Grieg,_Edvard/Lyric_Pieces,_Book_5,_Op.54/2._Norwegian_March/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Czerny,_Carl/March_in_D_minor/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/The_Well-Tempered_Clavier,_Book_I,_BWV_846-869/No.17_in_A_flat_major,_BWV_862:_Fugue/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Lemoine,_Henry/Études_enfantines,_Op.37/7._Allegretto/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Borodin,_Aleksandr/Prince_Igor/11._Fly_Away_on_the_Wings_of_the_Wind_(Polovtsian_Dances)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Piano_Sonata_No.2_in_B_flat_minor,_Op.35/4._Finale_(Presto)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Joplin,_Scott/Rose_Leaf_Rag/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Fauré,_Gabriel/3_Romances_sans_paroles,_Op.17/Andante_moderato_(A_flat_major)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/9_Kleine_Präludien,_BWV_924-932/4._Prelude_in_F_major,_BWV_927/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Czerny,_Carl/The_Art_of_Finger_Dexterity,_Op.740/8._Allegro_molto_(A_minor)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Waltzes,_Op.70/Waltz_No.13_in_D_flat_major,_Moderato/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Nocturnes,_Op.9/Nocturne_No.2_in_E_flat_major,_Andante/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Beethoven,_Ludwig_van/Piano_Sonata_No.31_in_A_flat_major,_Op.110/4._Fuga._Allegro_ma_non_troppo/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/12_Études,_Op.10/No.5_in_G_flat_major_"Black_Keys"/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Beethoven,_Ludwig_van/Piano_Sonata_No.22_in_F_major,_Op.54/1._In_tempo_d'un_minuetto/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mussorgsky,_Modest/Impromptu_passione/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Tchaikovsky,_Pyotr_Ilyich/The_Nutcracker_(ballet),_Op.71/Act_2._14c._Var.2._Dance_of_the_Sugarplum_Fairy._Andante_ma_non_troppo/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Schumann,_Robert/Kinderszenen,_Op.15/10._Fast_zu_ernst/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Waltz_No.17_in_E_flat_major,_Op.posth./piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Liszt,_Franz/Liebesträume,_S.541/3._Nocturne_in_A_flat_major/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Liszt,_Franz/Nuages_gris,_S.199/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Rachmaninoff,_Sergei/9_Etudes-Tableaux,_Op.33/No.7_in_E_flat_major/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Satie,_Erik/Gnossiennes,_IES_24/6._Avec_conviction_et_avec_une_tristesse_rigoureuse/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/The_Well-Tempered_Clavier,_Book_II,_BWV_870-893/No.10_in_E_minor,_BWV_879:_Fugue/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mozart,_Wolfgang_Amadeus/Piano_Sonata_No.8_in_A_minor,_K.310/2._Andante_cantabile_con_espressione/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Mazurkas,_Op.7/4._Presto_(A_flat_major)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/Partita_No.1_in_B_flat_major,_BWV_825/1._Praeludium/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Paull,_Edward_Taylor/Ben_Hur_Chariot_Race_March/piece_interpretation.json",
]

FILES_09 = [
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Polonaise_No.6_in_A_flat_major,_Op.53,_"Heroic"/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/The_Well-Tempered_Clavier,_Book_II,_BWV_870-893/No.10_in_E_minor,_BWV_879:_Prelude/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bertini,_Henri/24_Etudes,_Op.29/4._Aria._Andante._Con_expres._(B_flat_major)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Pleyel,_Ignaz/6_Sonatinas/4._Rondo_in_B_flat_major/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Beethoven,_Ludwig_van/Piano_Sonata_No.31_in_A_flat_major,_Op.110/3._Adagio_ma_non_troppo/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Schubert,_Franz/6_Moments_musicaux,_Op.94_D.780/No.4_in_C_sharp_minor_(Moderato)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/24_Préludes,_Op.28/No.5_in_D_major:_Molto_allegro/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mozart,_Wolfgang_Amadeus/Piano_Sonata_No.4_in_E_flat_major,_K.282/3._Allegro/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/The_Well-Tempered_Clavier,_Book_I,_BWV_846-869/No.11_in_F_major,_BWV_856:_Prelude/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Debussy,_Claude/Images,_Book_1,_L.110/2._Hommage_à_Rameau/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Handel,_George_Frideric/Suite_No.3_in_D_minor,_HWV_428/2._Allegro/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/The_Well-Tempered_Clavier,_Book_I,_BWV_846-869/No.19_in_A_major,_BWV_864:_Prelude/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Gruber,_Franz_Xaver/Stille_Nacht,_heilige_Nacht,_H.145/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Waltzes,_Op.69/Waltz_No.10_in_B_minor,_Moderato/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mozart,_Wolfgang_Amadeus/Piano_Sonata_No.12_in_F_major,_K.332/3._Allegro_assai/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/15_Inventions,_BWV_772-786/Invention_No.3_in_D_major,_BWV_774/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Debussy,_Claude/Préludes,_Book_1,_L.117/10._La_cathédrale_engloutie/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Grieg,_Edvard/Peer_Gynt_Suite_No.1,_Op.46/4._In_the_Hall_of_the_Mountain_King/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Beethoven,_Ludwig_van/Piano_Sonata_No.30_in_E_major,_Op.109/2._Prestissimo/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Joplin,_Scott/The_Easy_Winners/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mozart,_Wolfgang_Amadeus/5_Variations_in_G_major,_K.501/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/5_Kleine_Präludien,_BWV_939-943/5._Prelude_in_C_major,_BWV_943/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Debussy,_Claude/Préludes,_Book_2,_L.123/3._La_puerta_del_vino/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Handel,_George_Frideric/Suite_No.4_in_E_minor,_HWV_429/4._Gigue/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Debussy,_Claude/12_Etudes,_Book_1,_L.136/2._Pour_les_tierces/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/7_Toccatas,_BWV_910-916/Toccata_in_G_minor,_BWV_915/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Rachmaninoff,_Sergei/Etudes-Tableaux,_Op.39/No.1_in_C_minor/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Bach,_Johann_Sebastian/The_Well-Tempered_Clavier,_Book_II,_BWV_870-893/No.4_in_C_sharp_minor_BWV_873/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/12_Études,_Op.25/No.4_in_A_minor/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Liszt,_Franz/Grandes_études_de_Paganini,_S.141/3._La_campanella/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Botsford,_George/Black_and_White_Rag/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Alkan,_Charles-Valentin/3_Scherzi_di_bravoure,_Op.16/2._Moderato_(quasi_Minuetto)_(C_minor)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Liszt,_Franz/Consolations,_S.172/1._Andante_con_moto_(E_major)/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Joplin,_Scott/Palm_Leaf_Rag/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Mussorgsky,_Modest/Pictures_at_an_Exhibition/6._Samuel_Goldenberg_and_Schmuyle/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Gurlitt,_Cornelius/Die_ersten_Schritte_des_jungen_Klavierspielers,_Op.82/No.52/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Liszt,_Franz/Romance,_S.169/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Joplin,_Scott/Binks'_Waltz/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Loeschhorn,_Albert/Studies_for_the_Piano,_Op.65/40._Study_in_D_minor/piece_interpretation.json",
    "/home/sy/EPR/data/miditsv/Chopin,_Frédéric/Piano_Sonata_No.3_in_B_minor,_Op.58/2._Scherzo._Molto_vivace/piece_interpretation.json",
]

# Pre-computed performance_gist values keyed by piece_id/movement/context
# These are generated from the compressed_interpretation_200 content

GIST_MAP = {
    # BATCH 08
    "Schubert_D959_Scherzo": "restless syncopated drive, crisp articulation of off-beat accents, elastic tempo in trio, controlled dynamic swells, persistent forward momentum",
    "Glinka_Nocturne_Eb": "broad cantabile line, gentle rubato, warm mezzo-voiced melody, delicate filigree accompaniment, gradual dynamic arch",
    "Chopin_Ballade3_Op47": "graceful lyricism, flowing cantabile touch,轻盈 filigree passagework, elastic tempo in transitions, brilliant virtuosic coda",
    "Schubert_D593_Scherzo": "buoyant allegretto pulse, light staccato touch, warm trio lyricism, restrained dynamic shading, balanced phrase articulation",
    "Tchaikovsky_Trepak": "furious accelerando drive, sharply profiled rhythmic accents, relentless forward momentum, brilliant staccato articulation, explosive dynamic bloom",
    "Mozart_K280_Allegro": "crisp classical articulation, buoyant allegro pulse, transparent texture, restrained dynamic contrasts, precise scalar passagework",
    "Scarlatti_K4_Gm": "driving rhythmic spine, crisp harpsichord-derived articulation, urgent tempo, sharp dynamic contrasts, relentless motoric energy",
    "Tchaikovsky_Nutcracker_Overture": "bright orchestral clarity, brisk allegro pulse, transparent voicing, measured dynamic build, precise ensemble-style articulation",
    "Ravel_Prelude_M65": "searching harmonic color, restrained rubato, delicate dynamic gradations, sustained pedal resonance, contemplative phrasing",
    "Chopin_Berceuse_Op57": "rocking cradle rhythm, whispered dynamic palette, seamless legato line, minimal rubato, infinitely varied ornamental filigree",
    "Joplin_PineAppleRag": "syncopated ragtime snap, steady march-tempo spine, crisp staccato articulation, buoyant dynamic bounce, playful rhythmic displacement",
    "Chopin_Mazurka_Op7_No3": "folk-dance lilt, sharp mazurka accent on beat two, flexible rubato, muted dynamic palette, intimate phrasing",
    "Grieg_Norwegian_March": "broad march pulse, crisp chordal articulation, terraced dynamic build, sturdy rhythmic spine, ceremonial gravitas",
    "Czerny_March_Dm": "march-tempo drive, crisp finger-work articulation, steady dynamic pulse, precise rhythmic execution, functional phrasing",
    "Bach_BWV862_Fugue": "transparent contrapuntal voicing, measured tempo, even dynamic balance between entries, controlled articulation, restrained expressive shading",
    "Lemoine_Etude_Op37_No7": "light allegretto touch, even finger articulation, modest dynamic range, straightforward phrasing, pedagogical clarity",
    "Borodin_Polovtsian": "soaring lyrical sweep, broad rubato expansiveness, lush dynamic bloom, sweeping phrase arcs, passionate climactic release",
    "Chopin_Sonata2_Finale_Presto": "relentless perpetual motion, ghostly dynamic level, unbroken legato at extreme tempo, breathless forward drive, minimal rubato",
    "Joplin_RoseLeafRag": "buoyant ragtime syncopation, crisp articulation, steady dance-tempo pulse, playful dynamic contrast, clean sectional articulation",
    "Faure_Romance_Op17": "warm cantabile line, gentle rubato, nuanced dynamic shading, seamless phrase transitions, restrained expressive warmth",
    "Bach_BWV927_Prelude": "light touch, even articulation, modest tempo, transparent voicing, unadorned phrasing",
    "Czerny_Op740_No8": "brisk motoric drive, precise finger dexterity, even dynamic level, crisp staccato articulation, relentless forward energy",
    "Chopin_Waltz_Op70_No13": "gentle waltz lilt, flexible rubato, singing melodic line, nuanced dynamic shading, elegant phrase shaping",
    "Chopin_Nocturne_Op9_No2": "bel canto lyricism, flexible rubato, delicate fioritura ornamentation, warm dynamic arch, seamless legato phrasing",
    "Beethoven_Op110_Fuga": "learned contrapuntal clarity, measured fugal tempo, balanced voice entry, dynamic intensification through stretto, intellectual precision",
    "Chopin_Etude_Op10_No5": "brilliant pentatonic sparkle, finger-tip articulation on black keys, even dynamic level, buoyant tempo, playful lightness",
    "Beethoven_Op54_Minuetto": "stately minuet pulse, measured tempo contrast with trio, crisp articulation, restrained dynamic shading, balanced formal clarity",
    "Mussorgsky_Impromptu": "passionate impulsive drive, volatile dynamic contrasts, elastic rubato, sharp accentual profile, urgent forward momentum",
    "Tchaikovsky_Sugarplum": "delicate bell-like articulation, celesta-transparency texture, restrained dynamic palette, precise staccato touch, crystalline phrasing",
    "Schumann_Fast_zu_ernst": "contemplative gravity, measured tempo, muted dynamic palette, introspective phrasing, restrained rubato",
    "Chopin_Waltz_Eb_Opposth": "graceful waltz lilt, flexible tempo, singing cantabile line, delicate dynamic shading, elegant phrase arcs",
    "Liszt_Liebestraum_No3": "passionate bel canto sweep, expansive rubato, sweeping dynamic arch, rich textural bloom, cadential delay for maximum tension",
    "Liszt_Nuages_gris": "dissolving harmonic tension, measured contemplative pace, muted dynamic palette, suspended phrasing, bleak expressive stillness",
    "Rachmaninoff_Etude_Op33_No7": "luminous expansive lyricism, broad rubato sweep, rich textural layering, sweeping dynamic climaxes, singing top-voice projection",
    "Satie_Gnossienne_No6": "austere measured pace, rigid expressive restraint, even dynamic level, suspended rubato, stark textural clarity",
    "Bach_BWV879_Fugue": "dense contrapuntal weaving, steady tempo, balanced dynamic voicing, crisp articulation of subject entries, intellectual clarity",
    "Mozart_K310_Andante": "aching cantabile line, restrained rubato, delicate dynamic shading, singing phrase arcs, poignant harmonic coloring",
    "Chopin_Mazurka_Op7_No4": "brisk presto dance pulse, sharp accentual profile, playful rubato, buoyant dynamic bounce, folk-inflected rhythmic lilt",
    "Bach_BWV825_Praeludium": "bright French-overture gesture, crisp dotted-rhythm articulation, buoyant tempo, transparent textural voicing, balanced dynamic shading",
    "Paull_BenHur_March": "driving march momentum, bold chordal articulation, relentless rhythmic spine, terraced dynamic build, ceremonial sweep",

    # BATCH 09
    "Chopin_Polonaise_Op53": "heroic march grandeur, broad sweeping rubato, thunderous octave chords, sweeping dynamic arches, commanding rhythmic drive",
    "Bach_BWV879_Prelude": "flowing contrapuntal ease, steady tempo, transparent voice-leading, even dynamic balance, measured expressive restraint",
    "Bertini_Etude_Op29_No4": "singing aria line, gentle rubato, warm dynamic shading, bel canto phrasing, delicate accompaniment voicing",
    "Pleyel_Rondo_Bb": "light classical elegance, buoyant rondo pulse, crisp articulation, transparent texture, balanced dynamic shading",
    "Beethoven_Op110_Adagio": "deeply expressive lament, free-floating rubato, warm tonal shading, arioso lyricism, suspended temporal flow",
    "Schubert_D780_No4": "agitated minor-key urgency, sharp dynamic contrasts, restless rhythmic drive, tense articulation, compressed phrase arcs",
    "Chopin_Prelude_Op28_No5": "fleeting moto perpetuo, crisp staccato touch, minimal dynamic range, breathless tempo, ephemeral phrasing",
    "Mozart_K282_Allegro": "lively classical energy, crisp articulation, buoyant pulse, transparent voicing, balanced dynamic contrast",
    "Bach_BWV856_Prelude": "buoyant two-part invention feel, light touch, even articulation, steady tempo, transparent voicing",
    "Debussy_Hommage_Rameau": "solemn processional gravity, measured rubato, rich harmonic resonance, terraced dynamic layers, reverent phrasing",
    "Handel_HWV428_Allegro": "driving baroque motoric energy, crisp articulation, steady tempo, clear harmonic pulse, balanced dynamic shading",
    "Bach_BWV864_Prelude": "sparkling figuration flow, even touch, buoyant tempo, transparent harmonic rhythm, balanced dynamic arc",
    "Gruber_Stille_Nacht": "gentle cradle-like pulse, muted dynamic palette, warm legato phrasing, minimal rubato, reverent stillness",
    "Chopin_Waltz_Op69_No10": "melancholy waltz lilt, flexible rubato, muted dynamic shading, introspective phrasing, bittersweet cantabile line",
    "Mozart_K332_Allegro": "brilliant classical exuberance, crisp passagework, buoyant allegro pulse, transparent texture, balanced dynamic play",
    "Bach_BWV774_Invention": "lively three-voice counterpoint, even articulation, steady tempo, balanced voicing, clear motivic projection",
    "Debussy_Cathedrale": "gradual sonic emergence, submerged dynamic bloom, measured temporal dilation, resonant pedal layering, monumental phrasing arc",
    "Grieg_Mountain_King": "insistent accelerando drive, mounting dynamic crescendo, sharp rhythmic profile, increasingly frantic articulation, breathless climactic release",
    "Beethoven_Op109_Prestissimo": "ferocious driving energy, sharp accentual profile, breathless tempo, compressed phrase arcs, volatile dynamic contrast",
    "Joplin_EasyWinners": "buoyant ragtime syncopation, crisp articulation, steady march-tempo spine, playful dynamic bounce, clean sectional definition",
    "Mozart_K501_Variations": "graceful variation character shifts, measured tempo, delicate dynamic shading, transparent texture, balanced phrase shaping",
    "Bach_BWV943_Prelude": "flowing figuration, even touch, modest tempo, transparent voicing, straightforward dynamic arc",
    "Debussy_Puerta_del_vino": "habanera rhythmic spine, volatile dynamic contrasts, sharp accentual profile, abrupt tempo shifts, passionate climactic release",
    "Handel_HWV429_Gigue": "lively compound-meter drive, crisp articulation, buoyant pulse, balanced voice entries, clear rhythmic definition",
    "Debussy_Etude_Tierces": "relentless thirds passagework, crisp finger articulation, even dynamic level, driving tempo, precise textural control",
    "Bach_BWV915_Toccata": "virtuosic improvisatory sweep, volatile tempo fluctuations, sharp dynamic contrasts, brilliant figuration, dramatic rhetorical pauses",
    "Rachmaninoff_Etude_Op39_No1": "brooding minor-key drive, thunderous chordal texture, sweeping dynamic arches, expansive rubato, urgent forward momentum",
    "Bach_BWV873_Prelude": "contemplative harmonic flow, measured tempo, even dynamic shading, transparent voicing, restrained expressive depth",
    "Chopin_Etude_Op25_No4": "agitated minor-key urgency, crisp articulation, driving tempo, sharp dynamic contrasts, restless forward momentum",
    "Liszt_La_campanella": "brilliant bell-like figuration, finger-tip precision, sparkling dynamic level, breathless tempo, crystalline articulation",
    "Botsford_BlackWhiteRag": "crisp ragtime syncopation, steady march pulse, buoyant dynamic bounce, clean staccato articulation, playful sectional contrast",
    "Alkan_Scherzo_Op16_No2": "bravura scherzo energy, crisp staccato touch, volatile dynamic contrasts, elastic tempo, driving rhythmic spine",
    "Liszt_Consolation_No1": "warm cantabile lyricism, gentle rubato, soft dynamic palette, seamless legato phrasing, contemplative stillness",
    "Joplin_PalmLeafRag": "graceful ragtime lilt, crisp articulation, steady dance-tempo pulse, delicate dynamic shading, clean phrase definition",
    "Mussorgsky_Goldenberg": "staccato character contrast, sharp dynamic juxtaposition, alternating speech-like articulation, comic timing, abrupt tempo gestures",
    "Gurlitt_Op82_No52": "gentle pedagogical touch, even articulation, modest tempo, transparent voicing, straightforward phrasing",
    "Liszt_Romance_S169": "warm romantic sweep, expansive rubato, singing cantabile line, nuanced dynamic shading, tender phrase arcs",
    "Joplin_BinksWaltz": "graceful waltz lilt with rag inflection, buoyant pulse, delicate dynamic shading, crisp sectional articulation, playful rhythmic displacement",
    "Loeschhorn_Study_Op65_No40": "driving study energy, precise finger articulation, even dynamic pulse, crisp passagework, relentless forward momentum",
    "Chopin_Sonata3_Scherzo": "ferocious moto perpetuo drive, ghostly dynamic level, breathless tempo, minimal rubato, relentless forward energy",
}


def process_files(file_list, label=""):
    """Process a list of piece_interpretation.json files."""
    for i, fpath in enumerate(file_list):
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        piece_id = data.get("piece_id", "")
        movement = data.get("movement", "")
        composer = data.get("composer", "")

        # Find matching gist
        gist = None
        for key, val in GIST_MAP.items():
            # Try to match by checking key tokens against piece_id/movement/composer
            key_parts = key.lower().split('_')
            # Simple heuristic: if key contains a distinctive substring from piece_id
            if key in piece_id.replace(' ', '_').replace('-', '_'):
                gist = val
                break
            # Try matching key parts individually
            match = True
            for part in key_parts:
                if part and part not in piece_id.lower() and part not in movement.lower() and part not in composer.lower():
                    # Check if the part appears in any form
                    cleaned = part.replace('_', ' ')
                    if cleaned.lower() not in piece_id.lower() and cleaned.lower() not in movement.lower():
                        match = False
                        break
            if match and len(key_parts) > 1:
                gist = val
                break

        if gist is None:
            # Use the first part of the key to find a match
            for key, val in GIST_MAP.items():
                first = key.split('_')[0].lower()
                if first in piece_id.lower() or first in composer.lower():
                    # Check if movement matches too
                    mv_parts = key.split('_')[1:] if len(key.split('_')) > 1 else []
                    mv_match = all(p.lower() in piece_id.lower() or p.lower() in movement.lower() for p in mv_parts if p)
                    if mv_match:
                        gist = val
                        break

        if gist is None:
            print(f"  WARNING: No gist match for: {fpath}")
            print(f"    piece_id={piece_id}")
            continue

        data["performance_gist"] = gist

        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [{label}] Done ({i+1}/{len(file_list)}): {piece_id[:60]}...")


if __name__ == "__main__":
    print("Processing batch 08...")
    process_files(FILES_08, "08")
    print("\nProcessing batch 09...")
    process_files(FILES_09, "09")
    print("\nDone with batches 08 and 09.")
