#!/usr/bin/env python3
"""Generate musicological descriptions for J.S. Bach keyboard works.

Reads composer_batch_0001.json and writes composer_search_0001.jsonl
with per-piece musicological descriptions.
"""

import json
import re

INPUT = "data/piece_interpretations/composer_batch_0001.json"
OUTPUT = "data/piece_interpretations/composer_search_0001.jsonl"

# ---------------------------------------------------------------------------
# Collection-level knowledge bases
# ---------------------------------------------------------------------------

INVENTIONS_INFO = {
    "collection_desc": (
        "The 15 Inventions (BWV 772-786) are two-part keyboard exercises composed by J.S. Bach "
        "in 1723 for his son Wilhelm Friedemann. Bach's own title page describes them as a "
        "\"straightforward guide\" (Aufrichtige Anleitung) for keyboard amateurs, teaching clear "
        "two-part playing, good inventions (motivic ideas), cantabile style, and a foretaste of "
        "composition. The collection traverses the diatonic scale degrees: C major, C minor, "
        "D major, D minor, E-flat major, E major, E minor, F major, F minor, G major, G minor, "
        "A major, A minor, B-flat major, and B minor. Each invention is a compact contrapuntal "
        "piece built on a single motivic cell developed with remarkable ingenuity through "
        "inversion, stretto, and sequential treatment. The Inventions demonstrate Bach's mastery "
        "of two-part counterpoint and serve as foundational pedagogical works that remain central "
        "to keyboard education."
    ),
    "individual": {
        1: "Invention No. 1 in C major, BWV 772 is the opening piece of the collection and one of Bach's most recognizable works. Built on a simple ascending scale figure, its cheerful character and transparent two-voice texture exemplify the collection's pedagogical purpose. The invention proceeds with constant rhythmic motion in semiquavers, with the subject appearing in both voices through imitation and inversion. Its straightforward harmonic language and bright C major tonality make it an ideal introduction to two-part counterpoint.",
        2: "Invention No. 2 in C minor, BWV 773 contrasts sharply with its predecessor. The chromatic opening subject creates an expressive, sighing quality characteristic of the minor mode. The piece features intricate stretto entries and a remarkable economy of motivic material, with Bach deriving the entire structure from the opening gesture's descending chromatic inflection.",
        3: "Invention No. 3 in D major, BWV 774 is distinguished by its vigorous opening figure featuring a rising arpeggio and scalar descent. The wide-ranging melodic lines demand dexterity, and the piece's energetic character reflects the brilliant character of D major in Baroque keyboard writing. The motivic treatment includes inversion and mirror-like exchanges between the hands.",
        4: "Invention No. 4 in D minor, BWV 775 presents a restless, driving character built on continuous semiquaver motion. The subject's angular contour and sequential patterns create forward momentum throughout. Bach's contrapuntal ingenuity is evident in the seamless interplay of voices and the varied harmonic regions explored within a compact formal framework.",
        5: "Invention No. 5 in E-flat major, BWV 776 is the longest and most complex of the inventions, approaching the three-voice density of the Sinfonias. Its elaborate subject features wide leaps and ornamental figures, and the piece develops with remarkable contrapuntal sophistication. The harmonic range is unusually broad, exploring distant keys before returning to the tonic.",
        6: "Invention No. 6 in E major, BWV 777 features a graceful, lyrical subject with a distinctive ornamental figure. The E major tonality lends warmth and brilliance to the piece, and Bach's motivic development includes delightful exchanges between the voices with varied articulation and rhythmic displacement.",
        7: "Invention No. 7 in E minor, BWV 778 is characterized by its gentle, flowing character. The subject's stepwise motion creates a songlike quality, and the piece explores the expressive possibilities of the minor mode without excessive pathos. The counterpoint is fluid and natural, with elegant voice leading throughout.",
        8: "Invention No. 8 in F major, BWV 779 features a distinctive opening with a repeated-note figure that creates a bright, pastoral character. The piece demonstrates Bach's skill in creating varied texture from a simple motivic idea, with engaging dialogue between the hands and a cheerful overall character.",
        9: "Invention No. 9 in F minor, BWV 780 is one of the most expressive inventions, its chromatic subject conveying a poignant, lament-like quality. The piece features remarkable harmonic richness and contrapuntal complexity, with Bach exploring the full expressive range of the minor mode within the two-voice framework.",
        10: "Invention No. 10 in G major, BWV 781 features a lively, dance-like subject with a distinctive rhythmic profile. The piece is characterized by its buoyant character and the inventive ways Bach develops the opening gesture through sequential patterns and voice exchanges. The G major tonality contributes to the piece's bright, optimistic mood.",
        11: "Invention No. 11 in G minor, BWV 782 is distinguished by its chromatic, expressive subject and its sophisticated harmonic language. The piece explores the darker regions of G minor with considerable emotional depth, and the contrapuntal writing includes intricate stretto and inversion techniques.",
        12: "Invention No. 12 in A major, BWV 783 features a brilliant, fanfare-like opening subject that exploits the bright character of A major. The piece is notable for its wide-ranging melodic lines and the virtuosic demands it places on the performer. Bach's motivic development is both rigorous and imaginative.",
        13: "Invention No. 13 in A minor, BWV 784 has a driving, energetic character built on a subject featuring rapid scalar passages. The piece maintains constant forward momentum, with the two voices engaging in continuous dialogue. The A minor tonality gives the invention an urgent, passionate quality.",
        14: "Invention No. 14 in B-flat major, BWV 785 features a warm, lyrical subject with a distinctive intervallic character. The piece is notable for its balanced formal structure and the graceful interplay between voices. The B-flat major tonality lends a mellow,歌唱 quality to the invention.",
        15: "Invention No. 15 in B minor, BWV 786 is the concluding invention and one of the most intense. Its chromatic subject, with its characteristic diminished intervals, creates a highly expressive, almost anguished character. The piece serves as a dramatic conclusion to the collection, pushing the two-voice medium to its expressive limits.",
    }
}

SINFONIAS_INFO = {
    "collection_desc": (
        "The 15 Sinfonias (BWV 787-801), also known as Three-Part Inventions, were composed alongside "
        "the two-part Inventions as part of Bach's \"Aufrichtige Anleitung\" of 1723. While the "
        "Inventions explore two-part counterpoint, the Sinfonias expand to three voices, offering "
        "increased contrapuntal complexity and harmonic richness. Each Sinfonia is a masterwork of "
        "three-part invention, with subjects of varying character developed through imitation, "
        "inversion, augmentation, and stretto. The collection follows the same ascending key scheme "
        "as the Inventions. These pieces represent the pinnacle of Baroque three-part keyboard "
        "counterpoint and remain essential pedagogical and performance repertoire."
    ),
    "individual": {
        1: "Sinfonia No. 1 in C major, BWV 787 opens the three-part collection with a bright, cheerful subject characterized by its triadic outline and rhythmic vitality. The three-voice texture allows Bach to create rich harmonic progressions while maintaining clear contrapuntal independence. The piece features engaging voice exchanges and a joyful overall character.",
        2: "Sinfonia No. 2 in C minor, BWV 788 is one of the most dramatic sinfonias, its chromatic subject conveying deep expressiveness. The three-part texture intensifies the emotional impact, with the middle voice often providing poignant harmonic support. The contrapuntal development is sophisticated, with intricate stretto and motivic transformation.",
        3: "Sinfonia No. 3 in D major, BWV 789 features a brilliant, festive subject appropriate to the D major tonality. The three voices engage in lively dialogue, with Bach exploiting the full range of the keyboard. The piece showcases the celebratory character of the key and Bach's mastery of festive Baroque style.",
        4: "Sinfonia No. 4 in D minor, BWV 790 presents a serious, weighty subject with a distinctive rhythmic profile. The three-part counterpoint is particularly dense and learned, with frequent use of inversion and stretto. The D minor tonality contributes to the piece's grave and contemplative character.",
        5: "Sinfonia No. 5 in E-flat major, BWV 791 features a noble, stately subject with wide melodic intervals. The E-flat major tonality lends warmth and grandeur, and the three-voice texture creates rich, resonant harmonies. Bach's contrapuntal technique is on full display in the varied treatments of the subject.",
        6: "Sinfonia No. 6 in E major, BWV 792 has a graceful, flowing character with an expressive, lyrical subject. The piece exploits the warm character of E major and features particularly elegant voice leading. The three-part writing is fluid and natural, with each voice contributing to the overall melodic beauty.",
        7: "Sinfonia No. 7 in E minor, BWV 793 is characterized by its intense, passionate subject with chromatic inflections. The three-voice texture amplifies the expressive urgency, and the piece explores a wide range of affective states within its compact framework.",
        8: "Sinfonia No. 8 in F major, BWV 794 features a bright, pastoral subject with a distinctive rhythmic motive. The F major tonality creates a warm, bucolic atmosphere, and the three-part counterpoint includes charming dialogues between the voices.",
        9: "Sinfonia No. 9 in F minor, BWV 795 is one of the most profound sinfonias, its chromatic subject creating a deeply expressive, almost tragic character. The piece features remarkable contrapuntal complexity and harmonic depth, representing one of Bach's most concentrated achievements in three-part counterpoint.",
        10: "Sinfonia No. 10 in G major, BWV 796 features a lively, dance-like subject with a bright character. The three voices engage in energetic interplay, and the piece is notable for its clear formal structure and the virtuosity demanded of the performer.",
        11: "Sinfonia No. 11 in G minor, BWV 797 presents a serious, contemplative subject with expressive chromaticism. The G minor tonality contributes to the piece's dark character, and the three-part writing is particularly intricate, with frequent use of stretto and motivic inversion.",
        12: "Sinfonia No. 12 in A major, BWV 798 features a brilliant, virtuosic subject that exploits the bright A major tonality. The piece demands considerable technical facility and showcases Bach's ability to combine contrapuntal rigor with expressive beauty.",
        13: "Sinfonia No. 13 in A minor, BWV 799 is characterized by its driving energy and chromatic subject. The three-part texture creates urgency and intensity, with Bach developing the motivic material through sophisticated contrapuntal techniques.",
        14: "Sinfonia No. 14 in B-flat major, BWV 800 features a warm, lyrical subject with a distinctive character. The B-flat major tonality creates a mellow,歌唱 atmosphere, and the three-voice writing is particularly elegant and refined.",
        15: "Sinfonia No. 15 in B minor, BWV 801 concludes the collection with a powerful, chromatic subject of great expressive depth. The B minor tonality creates a dark, intense character, and the piece serves as a fitting conclusion to both the Sinfonias and the entire \"Aufrichtige Anleitung\" collection.",
    }
}

DUETS_INFO = (
    "The Four Duets (BWV 802-805) appear in the Notebook for Anna Magdalena Bach (1725) and "
    "represent Bach's late keyboard works. Unlike the Inventions, these are more elaborate pieces "
    "that combine two-part writing with greater structural complexity. Each duet features a "
    "distinctive character and showcases Bach's mastery of two-part counterpoint at its most "
    "sophisticated. The Duets were likely intended for both pedagogical and domestic performance purposes."
)

KLEINE_PRAELUDIEN_INFO = {
    "6bwv933": (
        "The Six Little Preludes (BWV 933-938) are short keyboard pieces from Bach's teaching "
        "repertoire, likely composed around 1720 for Wilhelm Friedemann Bach. They serve as "
        "introductions to the two-part Inventions and three-part Sinfonias, providing students "
        "with accessible pieces that introduce basic keyboard technique and harmonic understanding. "
        "Each prelude is brief but musically substantial, featuring characteristic Baroque figuration "
        "and clear harmonic progressions."
    ),
    "5bwv939": (
        "The Five Little Preludes (BWV 939-943) are pedagogical keyboard pieces of uncertain date, "
        "likely composed for Bach's students. These short preludes feature simple harmonic language "
        "and clear formal structure, making them ideal for developing keyboard technique. Each piece "
        "explores a different key and character, providing varied practice material for the aspiring "
        "keyboard player."
    ),
    "9bwv924": (
        "Nine Little Preludes (BWV 924-932) are brief keyboard pieces compiled from various sources, "
        "some appearing in the Clavier-Büchlein for Wilhelm Friedemann Bach. These pedagogical works "
        "feature simple textures and clear harmonic language, designed to develop fundamental keyboard "
        "skills. The collection includes pieces in various keys, offering diverse practice material."
    ),
}

TOCCATAS_INFO = (
    "The Seven Toccatas (BWV 910-916) are among Bach's earliest major keyboard works, likely composed "
    "during his Weimar period (1708-1717). They follow the North German toccata tradition established "
    "by Buxtehude, combining free, improvisatory passages with strict fugal sections. Each toccata "
    "features a multi-movement structure with contrasting tempos and textures. These works demonstrate "
    "Bach's early mastery of keyboard virtuosity and his ability to synthesize Italian, French, and "
    "German stylistic elements."
)

CHROMATIC_FANTASIA_INFO = (
    "The Chromatic Fantasia and Fugue in D minor, BWV 903 is one of Bach's most celebrated keyboard "
    "works. The Fantasia is remarkable for its bold chromatic harmonies, dramatic recitative-like "
    "passages, and free improvisatory style that pushes the boundaries of Baroque harmonic practice. "
    "The Fugue provides a strict contrapuntal contrast with its chromatic subject, demonstrating Bach's "
    "ability to combine expressive freedom with structural rigor. The work exists in multiple versions, "
    "suggesting Bach's ongoing engagement with the piece. It stands as a pinnacle of Baroque keyboard "
    "literature, combining virtuosic display with profound musical expression."
)

ART_OF_FUGUE_INFO = (
    "Die Kunst der Fuge (The Art of Fugue), BWV 1080, is Bach's final and most ambitious theoretical "
    "work, left unfinished at his death in 1750. The collection explores a single principal subject "
    "through an increasingly complex series of contrapuntal treatments, including simple fugues, "
    "counter-fugues, double and triple fugues, mirror fugues, and canons. The work was published "
    "without specified instrumentation, as the abstract contrapuntal argument transcends any particular "
    "medium. Contrapunctus I, the opening piece, presents the principal subject in its simplest form, "
    "establishing the D minor tonality and the basic material from which the entire collection will "
    "develop. The Art of Fugue represents Bach's summation of fugal technique and stands as one of "
    "the greatest achievements in Western music."
)

GOLDBERG_INFO = (
    "The Goldberg Variations, BWV 988, published in 1741 as Part IV of the Clavier-Ubung, are among "
    "the most ambitious and profound keyboard works ever composed. The work consists of an Aria "
    "followed by 30 variations and a return to the Aria. The variations are organized in groups of "
    "three: a character piece, a virtuoso toccata-like piece, and a canon at an ascending interval. "
    "The canons progress from unison to ninth, creating an overarching structural arch. The Aria, "
    "based on a sarabande bass line from the Notebook for Anna Magdalena Bach, serves as the harmonic "
    "foundation for the entire set. The work demonstrates Bach's extraordinary inventiveness, combining "
    "contrapuntal mastery with expressive depth and structural genius. It remains one of the greatest "
    "achievements of keyboard literature."
)

ITALIAN_CONCERTO_INFO = (
    "The Italian Concerto, BWV 971, published in 1735 as Part II of the Clavier-Ubung, is a solo "
    "keyboard work that brilliantly imitates the contrast between orchestral tutti and solo passages "
    "on a single instrument. The work has three movements: a vigorous Allegro in F major, a lyrical "
    "Andante in D minor, and a brilliant Presto finale. Bach achieves orchestral effects through "
    "registral contrast, texture variation, and dynamic implication. The work synthesizes Italian "
    "concerto style (particularly Vivaldi's influence) with Bach's contrapuntal mastery, creating "
    "a uniquely personal synthesis of national styles."
)

ENGLISH_SUITES_INFO = (
    "The Six English Suites (BWV 806-811) are among Bach's most substantial keyboard works, each "
    "comprising a substantial prelude followed by the standard dance suite movements: Allemande, "
    "Courante, Sarabande, optional galanteries (Bourrées, Gavottes, etc.), and Gigue. Despite their "
    "name, the suites show more French than English influence, possibly named for an English patron. "
    "Each suite explores a different key and character, with the preludes being particularly elaborate "
    "and often featuring fugal writing. The dance movements demonstrate Bach's mastery of stylized "
    "dance forms and his ability to infuse each movement with distinctive character."
)

FRENCH_SUITES_INFO = (
    "The Six French Suites (BWV 812-817) are lighter in character than the English Suites but no "
    "less crafted. They follow the standard Baroque dance suite format: Allemande, Courante, "
    "Sarabande, galanteries, and Gigue, though without the elaborate preludes of the English Suites. "
    "The suites are notable for their graceful, danceable character and the variety of galanteries "
    "they include: Menuets, Bourrées, Gavottes, Airs, Polonaises, and Loures. Each suite explores "
    "a different key and mood, showcasing Bach's ability to create distinctive character within "
    "standardized forms. The French Suites represent some of Bach's most accessible and charming "
    "keyboard music."
)

PARTITAS_INFO = (
    "The Six Partitas (BWV 825-830), published between 1726 and 1730 as Part I of the Clavier-Ubung, "
    "are Bach's most ambitious suite collection. Each partita features a distinctive opening movement "
    "beyond the standard prelude: Praeludium, Sinfonia, Fantasia, Ouverture, Praeambulum, and Toccata. "
    "These opening movements showcase Bach's stylistic range and compositional ingenuity. The "
    "subsequent dance movements (Allemande, Courante, Sarabande, galanteries, Gigue) each display "
    "unique character and technical demands. The Partitas represent the culmination of the Baroque "
    "suite tradition and remain central to the advanced keyboard repertoire."
)

WTC_INFO = {
    "I": (
        "The Well-Tempered Clavier, Book I (BWV 846-869), compiled around 1722, is one of the most "
        "important works in Western music. The collection contains 24 pairs of Preludes and Fugues, "
        "one in each major and minor key, ascending chromatically from C major to B minor. The title "
        "page describes the work as being \"for the use and profit of the musical youth desirous of "
        "learning, and especially for the pastime of those already skilled in this study.\" Each "
        "prelude explores a distinctive figuration or style, while each fugue demonstrates different "
        "contrapuntal techniques. The collection as a whole demonstrates the possibilities of "
        "well-tempered tuning and establishes a comprehensive exploration of all tonalities."
    ),
    "II": (
        "The Well-Tempered Clavier, Book II (BWV 870-893), compiled around 1742, mirrors the "
        "structure of Book I with 24 pairs of Preludes and Fugues in all keys. Written some 20 years "
        "after Book I, the pieces show Bach's mature style with greater contrapuntal complexity and "
        "harmonic sophistication. The preludes in Book II are generally more elaborate and varied in "
        "style, while the fugues explore more complex subjects and contrapuntal devices. The collection "
        "represents Bach's continued engagement with the systematic exploration of tonality and stands "
        "as one of the most comprehensive pedagogical and artistic achievements in keyboard literature."
    )
}

CELLO_SUITE_INFO = (
    "The Cello Suite No. 6 in D major, BWV 1012 is the last and most elaborate of Bach's Six "
    "Cello Suites, scored for a five-string violoncello piccolo. The suite's Prelude is "
    "particularly grand, exploiting the additional string for rich chordal writing and virtuosic "
    "passagework. The Sarabande is deeply expressive, with its characteristic dignified pace and "
    "ornamented melodic lines. The suite represents the culmination of Bach's exploration of the "
    "solo cello medium."
)

CHORALE_PRELUDES_INFO = {
    "schubler": (
        "The Schübler Chorales (BWV 645-650), published around 1748, are a set of six chorale "
        "preludes for organ transcribed by Bach from movements of his church cantatas. The most "
        "famous, \"Wachet auf, ruft uns die Stimme\" (BWV 645), is based on Cantata BWV 140 and "
        "features the chorale melody in the pedal with an obbligato counter-melody above. These "
        "works demonstrate Bach's skill in adapting vocal music for organ while maintaining the "
        "expressive power of the original."
    ),
    "great18": (
        "The Great Eighteen Chorale Preludes (BWV 651-668) were compiled and revised by Bach in "
        "his Leipzig period. They represent the pinnacle of the Baroque chorale prelude genre, "
        "with each piece exploring a different treatment of the chorale melody: ornamented, "
        "cantus firmus, chorale fantasia, etc. \"Vor deinen Thron tret' ich\" (BWV 668a) was "
        "reportedly dictated by Bach on his deathbed and stands as his final musical statement. "
        "The collection demonstrates Bach's profound engagement with Lutheran hymnody and his "
        "ability to create deeply expressive music from simple chorale melodies."
    ),
    "kirnberger": (
        "The Kirnberger Chorales (BWV 690-713) are a collection of chorale preludes preserved in "
        "manuscripts associated with Bach's student Johann Philipp Kirnberger. They feature simpler "
        "textures than the Great Eighteen but demonstrate Bach's mastery of chorale harmonization "
        "and organ style. \"Wer nur den lieben Gott lässt walten\" (BWV 691) is a notable example "
        "with its gentle, flowing character."
    )
}

WTC_PRELUDE_FUGUE_INFO = {
    # Book I
    "I_1": ("The Prelude in C major, BWV 846 is one of the most famous pieces ever written, a gentle "
            "arpeggiated meditation that explores a simple harmonic progression through flowing "
            "semiquaver patterns. Its transparent beauty made it the basis for Gounod's \"Ave Maria\". "
            "The Fugue is a five-voice masterpiece (though written for two hands) with a serene, "
            "stepwise subject. The combination of prelude and fugue establishes the contemplative tone "
            "for the entire collection."),
    "I_2": ("The Prelude in C minor, BWV 847 features a lively, motoric perpetuum mobile in two-part "
            "invention style. The Fugue is one of the most famous in the collection, its subject "
            "characterized by a distinctive four-note descending chromatic figure and its driving "
            "rhythmic energy. The three-voice fugue is a masterpiece of compact contrapuntal design."),
    "I_3": ("The Prelude in C-sharp major, BWV 848 is a bright, dance-like piece in 12/8 time with a "
            "lilting rhythm and cheerful character. The Fugue is a four-voice work with a joyful, "
            "triadic subject that explores the full range of the keyboard with exuberant counterpoint."),
    "I_4": ("The Prelude in C-sharp minor, BWV 849 is a grave, expressive piece with rich chromatic "
            "harmonies and a deeply serious character. The Fugue is one of Bach's most monumental, "
            "a five-voice work with a chromatic subject of extraordinary complexity. It is one of the "
            "longest fugues in the collection and represents Bach's most ambitious contrapuntal "
            "achievement in Book I."),
    "I_5": ("The Prelude in D major, BWV 850 is a brilliant, virtuoso piece with flowing arpeggios "
            "and fanfare-like character. The Fugue is a lively four-voice work with a subject that "
            "features a distinctive rhythmic motive and energetic character. The pair captures the "
            "brilliant, festive quality of D major."),
    "I_6": ("The Prelude in D minor, BWV 851 is an expressive piece with a distinctive sighing motive "
            "and rich harmonic language. The Fugue is a two-voice invention-style piece with a subject "
            "characterized by its driving semiquaver motion and urgent character."),
    "I_7": ("The Prelude in E-flat major, BWV 852 is a graceful piece in French overture style with "
            "dotted rhythms and a stately character. The Fugue is a four-voice work with a flowing, "
            "lyrical subject that demonstrates Bach's mastery of expressive counterpoint in this "
            "warm, noble key."),
    "I_8": ("The Prelude in E-flat minor, BWV 853 is a deeply expressive piece with rich chromatic "
            "harmonies and a lament-like character. The Fugue is a three-voice work with a chromatic, "
            "expressive subject that explores the darkest regions of the tonal spectrum."),
    "I_9": ("The Prelude in E major, BWV 854 is a bright, dance-like piece with a flowing, graceful "
            "character. The Fugue is a three-voice work with a lyrical, expressive subject that "
            "showcases the warm character of E major."),
    "I_10": ("The Prelude in E minor, BWV 855 is a gentle, flowing piece that exists in two versions. "
            "The original version (BWV 855a) is more elaborate, while the revised version is more "
            "compact. The Fugue is a two-voice invention with a light, agile subject and graceful "
            "counterpoint."),
    "I_11": ("The Prelude in F major, BWV 856 is a brief, bright piece with a dance-like character. "
            "The Fugue is a three-voice work with a light, cheerful subject featuring distinctive "
            "rhythmic patterns. The pair captures the warm, pastoral quality of F major."),
    "I_12": ("The Prelude in F minor, BWV 857 is a deeply expressive piece with rich, chromatic "
            "harmonies and a contemplative character. The Fugue is a four-voice work with a serious, "
            "weighty subject that explores the full expressive range of F minor."),
    "I_13": ("The Prelude in F-sharp major, BWV 858 is a gentle, flowing piece with a lyrical, "
            "singing character. The Fugue is a three-voice work with a graceful subject that exploits "
            "the warm, luminous character of F-sharp major."),
    "I_14": ("The Prelude in F-sharp minor, BWV 859 is an expressive, chromatic piece with a "
            "deeply serious character. The Fugue is a three-voice work with a chromatic subject "
            "that creates an atmosphere of intense expressiveness."),
    "I_15": ("The Prelude in G major, BWV 860 is a vigorous, toccata-like piece with driving "
            "semiquaver motion and a brilliant character. The Fugue is a two-voice invention with "
            "a light, dance-like subject that captures the cheerful quality of G major."),
    "I_16": ("The Prelude in G minor, BWV 861 is a grave, serious piece with a distinctive "
            "dotted-rhythm character and expressive chromaticism. The Fugue is a four-voice work "
            "with a chromatic, expressive subject that creates a deeply moving atmosphere."),
    "I_17": ("The Prelude in A-flat major, BWV 862 is a gentle, lyrical piece with a flowing "
            "character. The Fugue is a four-voice work with a serene, expressive subject. The "
            "enharmonic equivalent to G-sharp minor creates unique harmonic colors."),
    "I_18": ("The Prelude in G-sharp minor, BWV 863 is a complex, chromatic piece with rich "
            "harmonic language and an intense, expressive character. The Fugue is a four-voice "
            "work with a chromatic subject that demonstrates Bach's mastery of remote tonalities."),
    "I_19": ("The Prelude in A major, BWV 864 is a brilliant, toccata-like piece with virtuosic "
            "passagework and a festive character. The Fugue is a four-voice work with a bright, "
            "energetic subject that showcases the brilliant character of A major."),
    "I_20": ("The Prelude in A minor, BWV 865 is a lively, motoric piece with continuous "
            "semiquaver motion. The Fugue is a four-voice work with a vigorous, driving subject "
            "that captures the urgent character of A minor."),
    "I_21": ("The Prelude in B-flat major, BWV 866 is a flowing, graceful piece with a lyrical "
            "character. The Fugue is a three-voice work with a light, cheerful subject that "
            "explores the warm, mellow quality of B-flat major."),
    "I_22": ("The Prelude in B-flat minor, BWV 867 is a deeply expressive piece with rich "
            "chromatic harmonies and a grave character. The Fugue is a four-voice work with a "
            "serious, weighty subject that explores the darkest regions of the tonal spectrum."),
    "I_23": ("The Prelude in B major, BWV 868 is a flowing, lyrical piece with a gentle, "
            "expressive character. The Fugue is a four-voice work with a serene, noble subject "
            "that showcases the brilliant, warm character of B major."),
    "I_24": ("The Prelude in B minor, BWV 869 is a grave, serious piece with rich chromatic "
            "harmonies and a deeply expressive character. The Fugue is one of the most complex "
            "in the collection, a four-voice work with a chromatic subject that serves as a "
            "powerful conclusion to Book I."),
    # Book II
    "II_1": ("The Prelude in C major, BWV 870 is a flowing, expressive piece with a lyrical "
             "character and rich harmonic language. The Fugue is a three-voice work with a graceful "
             "subject that demonstrates Bach's mature contrapuntal style."),
    "II_2": ("The Prelude in C minor, BWV 871 is a brief, expressive piece with a serious character. "
             "The Fugue is a three-voice work with a light, dancing subject that contrasts with the "
             "prelude's gravity."),
    "II_3": ("The Prelude in C-sharp major, BWV 872 is a bright, flowing piece with a cheerful "
             "character. The Fugue is a three-voice work with a light, lyrical subject."),
    "II_4": ("The Prelude in C-sharp minor, BWV 873 is an expressive, sarabande-like piece with "
             "a grave character. The Fugue is a four-voice work with a chromatic, serious subject."),
    "II_5": ("The Prelude in D major, BWV 874 is a brilliant, concerto-like piece with virtuosic "
             "passagework. The Fugue is a four-voice work with a vigorous, energetic subject."),
    "II_6": ("The Prelude in D minor, BWV 875 is a flowing, expressive piece with a serious character. "
             "The Fugue is a three-voice work with a light, agile subject."),
    "II_7": ("The Prelude in E-flat major, BWV 876 is a flowing, lyrical piece with a gentle character. "
             "The Fugue is a four-voice work with a noble, expressive subject."),
    "II_8": ("The Prelude in D-sharp minor, BWV 877 is an expressive, chromatic piece with a serious "
             "character. The Fugue is a four-voice work with a chromatic, complex subject."),
    "II_10": ("The Prelude in E minor, BWV 879 is a flowing, expressive piece with a serious character. "
              "The Fugue is a three-voice work with a light, lyrical subject."),
    "II_11": ("The Prelude in F major, BWV 880 is a bright, cheerful piece with a flowing character. "
              "The Fugue is a three-voice work with a light, dance-like subject."),
    "II_13": ("The Prelude in F-sharp major, BWV 882 is a flowing, lyrical piece with a gentle "
              "character. The Fugue is a three-voice work with a graceful subject."),
    "II_14": ("The Prelude in F-sharp minor, BWV 883 is an expressive, serious piece with rich "
              "harmonic language. The Fugue is a three-voice work with a chromatic, expressive subject."),
    "II_15": ("The Prelude in G major, BWV 884 is a brief, cheerful piece with a light character. "
              "The Fugue is a three-voice work with a vigorous, energetic subject."),
    "II_16": ("The Prelude in G minor, BWV 885 is a serious, expressive piece with a grave character. "
              "The Fugue is a five-voice work of extraordinary complexity, one of the most ambitious "
              "fugues in the collection."),
    "II_18": ("The Prelude in G-sharp minor, BWV 887 is an expressive, chromatic piece with rich "
              "harmonic language. The Fugue is a three-voice work with a brilliant, virtuosic subject "
              "featuring remarkable contrapuntal complexity."),
    "II_19": ("The Prelude in A major, BWV 888 is a flowing, expressive piece with a gentle character. "
              "The Fugue is a four-voice work with a serious, weighty subject."),
    "II_20": ("The Prelude in A minor, BWV 889 is a flowing, expressive piece with a serious character. "
              "The Fugue is a three-voice work with a light, agile subject."),
    "II_21": ("The Prelude in B-flat major, BWV 890 is a flowing, lyrical piece with a gentle character. "
              "The Fugue is a four-voice work with a noble, expressive subject."),
    "II_22": ("The Prelude in B-flat minor, BWV 891 is a serious, chromatic piece with a grave character. "
              "The Fugue is a four-voice work with a chromatic, complex subject."),
    "II_23": ("The Prelude in B major, BWV 892 is a flowing, expressive piece with a bright character. "
              "The Fugue is a four-voice work with a vigorous, energetic subject."),
    "II_24": ("The Prelude in B minor, BWV 893 is a serious, chromatic piece with a grave character. "
              "The Fugue is a four-voice work with a complex, chromatic subject that provides a "
              "powerful conclusion to Book II."),
}


def extract_number(text):
    """Extract a number from text like 'No.10', 'No. 10', '1.', '10.', etc."""
    m = re.search(r'No\.?\s*(\d+)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'^(\d+)\.', text.strip())
    if m:
        return int(m.group(1))
    return None


def extract_key(movement):
    """Extract key name from movement string."""
    keys = ['C major', 'C minor', 'C sharp major', 'C sharp minor',
            'D major', 'D minor', 'D sharp minor', 'D flat major',
            'E major', 'E minor', 'E flat major', 'E flat minor',
            'F major', 'F minor', 'F sharp major', 'F sharp minor',
            'G major', 'G minor', 'G sharp minor', 'G flat major',
            'A major', 'A minor', 'A flat major', 'A flat minor',
            'B flat major', 'B flat minor', 'B major', 'B minor']
    for k in keys:
        if k in movement:
            return k
    return None


def get_invention_text(piece):
    movement = piece["movement"]
    num = extract_number(movement)
    if num and num in INVENTIONS_INFO["individual"]:
        return INVENTIONS_INFO["individual"][num] + " " + INVENTIONS_INFO["collection_desc"]
    return INVENTIONS_INFO["collection_desc"]


def get_sinfonia_text(piece):
    movement = piece["movement"]
    num = extract_number(movement)
    if num and num in SINFONIAS_INFO["individual"]:
        return SINFONIAS_INFO["individual"][num] + " " + SINFONIAS_INFO["collection_desc"]
    return SINFONIAS_INFO["collection_desc"]


def get_kleine_praeludien_text(piece, composition):
    movement = piece["movement"]
    num = extract_number(movement)
    key = extract_key(movement)
    bwv = None
    m = re.search(r'BWV\s*(\d+)', movement)
    if m:
        bwv = m.group(1)

    if "933-938" in composition or "BWV 933" in composition:
        desc = KLEINE_PRAELUDIEN_INFO["6bwv933"]
        collection_name = "Six Little Preludes"
    elif "939-943" in composition or "BWV 939" in composition:
        desc = KLEINE_PRAELUDIEN_INFO["5bwv939"]
        collection_name = "Five Little Preludes"
    elif "924-932" in composition or "BWV 924" in composition:
        desc = KLEINE_PRAELUDIEN_INFO["9bwv924"]
        collection_name = "Nine Little Preludes"
    else:
        desc = "A brief pedagogical keyboard prelude by J.S. Bach."
        collection_name = "Little Preludes"

    extra = ""
    if key:
        extra += f" This particular prelude, set in {key}, "
    else:
        extra += f" This prelude "
    if bwv:
        extra += f"(catalogued as BWV {bwv}) "
    extra += (f"serves as an accessible introduction to Baroque keyboard style, "
              f"featuring simple harmonic progressions and clear formal structure. "
              f"As part of the {collection_name} collection, it was designed to develop "
              f"fundamental keyboard technique through varied figurations and tonalities, "
              f"providing students with diverse practice material before advancing to "
              f"the more complex Inventions and Sinfonias.")
    return desc + " " + extra


def get_toccata_text(piece):
    movement = piece["movement"]
    key = extract_key(movement)
    # Try to get BWV
    bwv_match = re.search(r'BWV\s*(\d+)', piece["piece_id"])
    bwv = bwv_match.group(1) if bwv_match else None
    base = TOCCATAS_INFO
    if key:
        base += f" This toccata is in {key}"
    if bwv:
        base += f" (BWV {bwv})"
    base += (". The work alternates between free, rhapsodic passages and strict fugal sections, "
             "demonstrating Bach's early mastery of contrasting textures and his synthesis of "
             "North German organ traditions with Italian virtuoso style.")
    return base


def get_wtc_text(piece, book="I"):
    movement = piece["movement"]
    num = extract_number(movement)
    is_fugue = "Fugue" in movement
    is_prelude = "Prelude" in movement
    is_both = not is_fugue and not is_prelude

    key = f"{book}_{num}" if num else None
    if key and key in WTC_PRELUDE_FUGUE_INFO:
        return WTC_PRELUDE_FUGUE_INFO[key]

    # Fall back to collection description with key info
    book_label = "Book I" if book == "I" else "Book II"
    key_name = extract_key(movement)
    text = f"From The Well-Tempered Clavier, {book_label}."
    if key_name:
        text += f" This prelude and fugue pair in {key_name}"
    else:
        text += " This prelude and fugue pair"
    if book == "I":
        text += (" explores the possibilities of well-tempered tuning through a distinctive "
                 "prelude figuration and a contrapuntal fugue, contributing to the systematic "
                 "exploration of all 24 major and minor keys in the collection.")
    else:
        text += (" showcases Bach's mature contrapuntal style with greater harmonic sophistication, "
                 "contributing to the comprehensive exploration of all tonalities in Book II.")
    return text


def get_suite_movement_text(piece, composition, suite_type):
    movement = piece["movement"]
    key = extract_key(movement) or extract_key(composition)
    bwv_match = re.search(r'BWV\s*(\d+)', piece["piece_id"])
    bwv = bwv_match.group(1) if bwv_match else None

    if suite_type == "english":
        base = ENGLISH_SUITES_INFO
    elif suite_type == "french":
        base = FRENCH_SUITES_INFO
    elif suite_type == "partita":
        base = PARTITAS_INFO
    else:
        base = ""

    # Movement-specific additions
    move_text = ""
    lower = movement.lower()
    if "prelude" in lower or "prélude" in lower or "praeludium" in lower:
        move_text = (" The opening prelude is an elaborate movement, often featuring fugal or "
                     "toccata-like writing that establishes the character of the entire suite.")
    elif "allemande" in lower:
        move_text = (" The Allemande is a moderate-paced dance in 4/4 time with flowing "
                     "contrapuntal texture, often featuring intricate motivic development "
                     "and expressive harmonic progressions.")
    elif "courante" in lower or "corrente" in lower:
        move_text = (" The Courante is a lively dance in 3/2 or 3/4 time, typically featuring "
                     "rhythmic vitality and contrapuntal interplay between voices.")
    elif "sarabande" in lower:
        move_text = (" The Sarabande is a slow, dignified dance in 3/4 time with emphasis on "
                     "the second beat. It is typically the most expressive movement in the suite, "
                     "featuring ornamented melodic lines and rich harmonic language.")
    elif "gigue" in lower:
        move_text = (" The Gigue is a lively closing dance in compound meter, typically "
                     "featuring fugal entries and virtuosic passagework that brings the suite "
                     "to an energetic conclusion.")
    elif "gavotte" in lower:
        move_text = (" The Gavotte is a moderate-paced dance in 4/4 or 2/2 time beginning on "
                     "the half-measure, characterized by its graceful, elegant character.")
    elif "bourrée" in lower or "bourree" in lower:
        move_text = (" The Bourrée is a lively dance in duple meter with a cheerful, "
                     "rustic character, typically featuring rapid scalar passages.")
    elif "menuet" in lower:
        move_text = (" The Menuet is a graceful dance in 3/4 time with a balanced, "
                     "symmetrical phrase structure and elegant character.")
    elif "air" in lower:
        move_text = (" The Air is a lyrical, song-like movement with a flowing, expressive "
                     "melody and gentle harmonic accompaniment.")
    elif "polonaise" in lower:
        move_text = (" The Polonaise is a stately dance in 3/4 time with a distinctive "
                     "rhythmic profile featuring dotted figures, conveying a noble, ceremonial "
                     "character.")
    elif "loure" in lower:
        move_text = (" The Loure is a slow, dignified dance in 6/4 or 3/2 time with dotted "
                     "rhythms, creating a solemn, processional character.")
    elif "passepied" in lower:
        move_text = (" The Passepied is a light, quick dance in 3/8 or 6/8 time with a "
                     "bright, playful character.")
    elif "sinfonia" in lower:
        move_text = (" The Sinfonia is a multi-section opening movement combining slow "
                     "and fast sections, featuring expressive harmonies and contrapuntal "
                     "writing that sets a serious, reflective tone for the partita.")
    elif "fantasia" in lower:
        move_text = (" The Fantasia is a free, improvisatory opening movement exploring "
                     "varied textures and harmonic regions, showcasing Bach's stylistic range.")
    elif "ouverture" in lower:
        move_text = (" The Ouverture is a grand opening movement in French overture style, "
                     "combining a slow, dotted-rhythm introduction with a faster fugal section.")
    elif "toccata" in lower and "partita" in suite_type:
        move_text = (" The Toccata is a brilliant, virtuosic opening movement featuring "
                     "rapid passagework and dramatic contrasts, setting a festive tone for "
                     "the partita.")
    elif "capriccio" in lower:
        move_text = (" The Capriccio is a lively, free-form movement featuring brilliant "
                     "passagework and unexpected harmonic turns.")
    elif "burlesca" in lower:
        move_text = (" The Burlesca is a playful, humorous movement with rapid rhythms "
                     "and unexpected accents, creating a comic character.")
    elif "scherzo" in lower:
        move_text = (" The Scherzo is a light, playful movement with quick rhythms and "
                     "a joking character.")
    elif "rondeaux" in lower:
        move_text = (" The Rondeaux is a movement featuring a recurring refrain alternating "
                     "with contrasting couplets, creating an elegant rondo-like structure.")
    elif "double" in lower:
        move_text = (" The Double is an ornate variation of the preceding Sarabande, "
                     "featuring elaborate melodic decoration over the same harmonic structure.")
    elif "tempo di" in lower:
        move_text = (f" The movement marked \"{movement}\" is a stylized dance movement "
                     "with a distinctive tempo character, contributing variety to the suite's "
                     "galanterie section.")

    key_info = f" in {key}" if key else ""
    bwv_info = f" (BWV {bwv})" if bwv else ""
    return base + f"{key_info}{bwv_info}." + move_text


def get_chorale_text(piece):
    title = piece["composition"]
    bwv_match = re.search(r'BWV\s*(\d+)', title)
    bwv = bwv_match.group(1) if bwv_match else None

    # Schübler
    if "645" in title or "650" in title:
        base = CHORALE_PRELUDES_INFO["schubler"]
    elif "651" in title or "668" in title or "668a" in title:
        base = CHORALE_PRELUDES_INFO["great18"]
    elif "690" in title or "713" in title or "691" in title:
        base = CHORALE_PRELUDES_INFO["kirnberger"]
    else:
        base = ""

    chorale_name = title.split(", BWV")[0].strip()
    extra = f" The chorale melody \"{chorale_name}\""
    if bwv:
        extra += f" (BWV {bwv})"
    extra += (" is treated with Bach's characteristic mastery, weaving the hymn tune into "
              "a rich contrapuntal texture that deepens the spiritual and expressive meaning "
              "of the original melody.")

    if base:
        return base + extra
    return (f"A chorale prelude by J.S. Bach based on the hymn tune \"{chorale_name}\". "
            f"Bach treats the chorale melody with characteristic contrapuntal mastery, "
            f"creating a work that serves both devotional and artistic purposes.{extra}")


def get_piece_text(piece):
    """Generate musicological text for a single piece."""
    composition = piece["composition"]
    movement = piece["movement"]
    piece_id = piece["piece_id"]

    # Inventions
    if "15 Inventions" in composition:
        return get_invention_text(piece)

    # Sinfonias
    if "15 Sinfonias" in composition:
        return get_sinfonia_text(piece)

    # Duets
    if "4 Duets" in composition:
        return DUETS_INFO

    # Kleine Präludien
    if "Kleine Präludien" in composition or "Kleine Praludien" in composition:
        return get_kleine_praeludien_text(piece, composition)

    # Toccatas
    if "7 Toccatas" in composition:
        return get_toccata_text(piece)

    # Well-Tempered Clavier Book I
    if "Well-Tempered Clavier, Book I" in composition:
        return get_wtc_text(piece, "I")

    # Well-Tempered Clavier Book II
    if "Well-Tempered Clavier, Book II" in composition:
        return get_wtc_text(piece, "II")

    # English Suites
    if "English Suite" in composition:
        return get_suite_movement_text(piece, composition, "english")

    # French Suites
    if "French Suite" in composition:
        return get_suite_movement_text(piece, composition, "french")

    # Partitas
    if "Partita" in composition:
        return get_suite_movement_text(piece, composition, "partita")

    # Chromatic Fantasia
    if "Chromatic Fantasia" in composition:
        return CHROMATIC_FANTASIA_INFO

    # Art of Fugue
    if "Kunst der Fuge" in composition:
        return ART_OF_FUGUE_INFO

    # Goldberg Variations
    if "Goldberg" in composition:
        return GOLDBERG_INFO

    # Italian Concerto
    if "Italian Concerto" in composition:
        return ITALIAN_CONCERTO_INFO

    # Chorale Preludes
    if "Chorale Prelude" in composition:
        return get_chorale_text(piece)

    # Cello Suite
    if "Cello Suite" in composition:
        return CELLO_SUITE_INFO

    # Individual chorales
    if "BWV 637" in composition or "Durch Adams" in composition:
        return ("\"Durch Adams Fall ist ganz verderbt\" (BWV 637) is a chorale prelude from the "
                "Orgelbüchlein. The piece musically depicts Adam's fall through descending melodic "
                "lines and dissonant harmonies, creating one of the most vivid examples of musical "
                "text-painting in Baroque organ literature.")

    if "BWV 639" in composition or "Ich ruf" in composition:
        return ("\"Ich ruf zu dir, Herr Jesu Christ\" (BWV 639) is a chorale prelude from the "
                "Orgelbüchlein. The piece features the chorale melody in the upper voice with "
                "a flowing accompaniment in the inner voice and a steady pedal bass, creating "
                "an atmosphere of earnest prayer and devotional intensity.")

    if "BWV 253" in composition or "Ach bleib" in composition:
        return ("\"Ach bleib bei uns, Herr Jesu Christ\" (BWV 253) is a four-part chorale "
                "harmonization from Bach's extensive collection of Lutheran hymn settings. The "
                "piece demonstrates Bach's mastery of four-part chorale writing, with careful "
                "voice leading and expressive harmonic choices that illuminate the devotional text.")

    if "BWV 368" in composition or "In dulci" in composition:
        return ("\"In dulci jubilo\" (BWV 368) is a chorale setting of the famous medieval "
                "Latin-German Christmas hymn. Bach's harmonization treats the ancient melody "
                "with characteristic care, creating a joyful, festive atmosphere appropriate to "
                "the text's celebration of Christ's birth.")

    if "BWV 734" in composition or "Nun freut" in composition:
        return ("\"Nun freut euch, lieben Christen gmein\" (BWV 734) is a chorale prelude "
                "based on Luther's joyful hymn. Bach treats the melody with energetic, "
                "dance-like rhythms that reflect the text's call for Christian rejoicing, "
                "creating a vibrant and celebratory organ work.")

    if "BWV 659" in composition or "Nun komm" in composition:
        return ("\"Nun komm, der Heiden Heiland\" (BWV 659) is one of the Great Eighteen "
                "Chorale Preludes. This Advent chorale prelude features an elaborate, flowing "
                "accompaniment that surrounds the chorale melody, creating a meditative, "
                "anticipatory atmosphere appropriate to the Advent season. It is considered "
                "one of Bach's most beautiful organ chorale preludes.")

    if "BWV 147" in composition or "Herz und Mund" in composition:
        return ("\"Jesu, Joy of Man's Desiring\" from \"Herz und Mund und Tat und Leben\" "
                "(BWV 147) is one of Bach's most beloved chorale melodies. Originally part of "
                "a church cantata, the chorale features a flowing, perpetual-motion accompaniment "
                "that creates a sense of ceaseless spiritual joy. The melody has become one of "
                "the most recognizable pieces in Western music.")

    if "BWV 244" in composition or "Matthäus" in composition:
        return ("The St. Matthew Passion (Matthäuspassion), BWV 244, is one of Bach's greatest "
                "achievements and one of the most monumental works of sacred music. Composed "
                "for Good Friday Vespers at St. Thomas Church in Leipzig, it sets the Passion "
                "narrative from Matthew's Gospel with recitatives, arias, choruses, and chorales. "
                "The work features double chorus and orchestra, creating a vast architectural "
                "structure of extraordinary emotional depth and dramatic power.")

    if "BWV 248" in composition or "Weihnachts" in composition:
        return ("The Christmas Oratorio (Weihnachtsoratorium), BWV 248, is a cycle of six "
                "cantatas composed for the Christmas season of 1734-35. The work combines "
                "newly composed music with parodied material from secular cantatas, creating "
                "a unified celebration of the Nativity. The oratorio features some of Bach's "
                "most joyful and festive music, with brilliant choral writing and expressive "
                "solo arias.")

    if "BWV 54" in composition or "Widerstehe" in composition:
        return ("\"Widerstehe doch der Sünde\" (BWV 54) is a sacred cantata for alto solo. "
                "The opening sinfonia features rich string writing that establishes a serious, "
                "contemplative mood before the alto enters with the warning against sin. "
                "The work demonstrates Bach's mastery of sacred vocal composition and his "
                "ability to create dramatic expression within a compact form.")

    if "BWV 514" in composition or "Schaff's mit mir" in composition:
        return ("\"Schaff's mit mir, Gott, nach deinem Willen\" (BWV 514) is a sacred cantata "
                "movement demonstrating Bach's skill in setting devotional text to music. The "
                "piece features careful text painting and expressive harmonic language that "
                "illuminates the spiritual meaning of the words.")

    if "BWV 992" in composition or "Capriccio" in composition:
        return ("The Capriccio in B-flat major, BWV 992 (\"Capriccio sopra la lontananza del "
                "suo fratello dilettissimo\") is a programmatic keyboard work depicting the "
                "departure of Bach's beloved brother Johann Jacob. The work has several movements, "
                "each representing a different scene or emotion. The \"Aria di Postiglione\" "
                "(movement 5) depicts the postilion's horn call, a charming example of Bach's "
                "programmatic writing and early keyboard style.")

    if "BWV 989" in composition or "Aria variata" in composition:
        return ("The Aria variata alla maniera italiana in A minor, BWV 989 is an early keyboard "
                "variation work by Bach, modeled on Italian variation style. The Aria presents a "
                "simple, song-like theme followed by variations that explore different textures, "
                "rhythms, and contrapuntal techniques. The work demonstrates Bach's early engagement "
                "with Italian stylistic influences and his developing mastery of variation form.")

    if "BWV 904" in composition or "Fantasia and Fugue in A minor" in composition:
        return ("The Fantasia and Fugue in A minor, BWV 904 is a significant keyboard work combining "
                "a free, improvisatory Fantasia with a rigorous four-voice Fugue. The Fantasia "
                "features dramatic contrasts of texture and tempo, while the Fugue is built on a "
                "distinctive chromatic subject that creates an atmosphere of intense expressiveness. "
                "The work showcases Bach's ability to balance freedom and structure.")

    if "BWV 944" in composition:
        return ("The Fantasia and Fugue in A minor, BWV 944 is an early keyboard work that pairs "
                "a free, rhapsodic Fantasia with a strict fugal section. The work demonstrates "
                "Bach's early engagement with the fantasia-fugue pairing that would become central "
                "to his keyboard output, and shows the influence of North German organ traditions "
                "on his developing style.")

    if "BWV 542" in composition:
        return ("The Fantasia and Fugue in G minor, BWV 542 (the \"Great\" Fantasia and Fugue) "
                "is one of Bach's most celebrated organ works. The Fantasia is remarkable for "
                "its bold chromatic opening, descending chromatic scale passages, and dramatic "
                "rhetorical gestures. The Fugue features a distinctive subject with a wide "
                "intervallic leap and is notable for its virtuosic pedal writing and brilliant "
                "overall character.")

    if "BWV 917" in composition:
        return ("The Fantasia in G minor, BWV 917 is an early keyboard work in the North German "
                "organ fantasia tradition. The piece features free, improvisatory passages with "
                "dramatic harmonic shifts and expressive chromaticism, demonstrating Bach's early "
                "engagement with the stylus phantasticus and his development of keyboard virtuosity.")

    if "BWV 1012" in composition or "Cello Suite No.6" in composition:
        return CELLO_SUITE_INFO

    if "BWV 1006a" in composition or "Suite in E major" in composition:
        return ("The Suite in E major, BWV 1006a is a keyboard transcription of the Partita No. 3 "
                "for solo violin, BWV 1006. Bach expanded the original solo violin writing with "
                "additional voices and harmonies, transforming it into a full keyboard work. "
                "The suite retains the brilliant, festive character of the original while gaining "
                "harmonic richness from the keyboard medium.")

    if "BWV 842" in composition or "Minuet in G minor" in composition:
        return ("The Minuet in G minor, BWV 842 is a brief, charming dance movement from the "
                "Notebook for Anna Magdalena Bach. The piece features a graceful melody with "
                "simple harmonic accompaniment, characteristic of the accessible, domestic music "
                "that Bach collected for his family's musical enjoyment.")

    if "Anna Magdalena" in composition:
        num = extract_number(movement)
        key = extract_key(movement)
        move_name = movement.split(", BWV")[0].strip().split(". ")[-1] if ". " in movement else movement
        text = (f"From the Notebook for Anna Magdalena Bach, Book 2 (BWV Anh. 113-132). ")
        text += (f"This piece, \"{move_name}\", ")
        if key:
            text += f"in {key}, "
        text += ("is a short dance movement from the collection that Bach and his family used "
                 "for domestic music-making. The Notebook contains pieces by various composers, "
                 "including works of doubtful authenticity attributed to Bach. These short dances "
                 "— minuets, polonaises, and musettes — are charming, accessible pieces that "
                 "reflect the musical taste of Bach's household and served both pedagogical "
                 "and entertainment purposes for the Bach family.")
        return text

    if "Fugues and Fughettas" in composition:
        key = extract_key(movement)
        bwv_match = re.search(r'BWV\s*(\d+)', movement)
        bwv = bwv_match.group(1) if bwv_match else None
        text = ("From the collection of Fugues and Fughettas (BWV 944-962), a diverse group of "
                "keyboard fugues and short fugal pieces by Bach. ")
        if key:
            text += f"Set in {key}"
            if bwv:
                text += f" (BWV {bwv})"
            text += (", this piece demonstrates Bach's mastery of fugal writing in a compact form. "
                     "The collection includes works of varying complexity, from simple pedagogical "
                     "fughettas to more elaborate fugues, showcasing Bach's contrapuntal skill "
                     "across a range of technical demands.")
        else:
            text += ("These pieces demonstrate Bach's mastery of fugal writing in various forms "
                     "and keys.")
        return text

    if "BWV 564" in composition:
        return ("The Toccata, Adagio and Fugue in C major, BWV 564 is one of Bach's most "
                "original organ works, unique in its three-movement structure. The opening "
                "Toccata features brilliant virtuosic passagework and dramatic contrasts. "
                "The central Adagio is a deeply expressive, lyrical movement of extraordinary "
                "beauty. The closing Fugue is a lively, energetic movement that brings the work "
                "to a brilliant conclusion. The combination of virtuosity, lyrical beauty, and "
                "contrapuntal rigor makes this one of Bach's most beloved organ works.")

    if "BWV 895" in composition:
        return ("The Prelude and Fugue in A minor, BWV 895 is a keyboard work pairing a free, "
                "improvisatory Prelude with a strict fugue. The Prelude features expressive "
                "chromatic harmonies and dramatic gestures, while the Fugue demonstrates Bach's "
                "contrapuntal mastery. The work reflects Bach's continued exploration of the "
                "prelude-fugue pairing that culminates in the Well-Tempered Clavier.")

    if "BWV 999" in composition:
        return ("The Prelude in C minor, BWV 999 (also known as the \"Little\" Prelude in C minor) "
                "is a short, expressive keyboard piece likely composed for pedagogical purposes. "
                "The piece features flowing arpeggiated figuration over a steady bass line, "
                "creating a meditative atmosphere in the C minor tonality. Its compact form and "
                "accessible technique make it a popular teaching piece.")

    if "Oboe Concerto" in composition:
        return ("The Adagio from the Oboe Concerto in D minor is a deeply expressive slow movement "
                "featuring the solo oboe's lyrical capabilities. The movement is characterized by "
                "its rich harmonic language, expressive melodic lines, and the dialogue between "
                "soloist and accompaniment. In Bach's keyboard transcription, the piece gains "
                "additional textural possibilities while maintaining its essential lyricism and "
                "emotional depth.")

    # Fallback
    key = extract_key(movement) or extract_key(composition)
    fallback = f"A keyboard work by Johann Sebastian Bach"
    if key:
        fallback += f" in {key}"
    fallback += ". "
    fallback += ("This piece exemplifies Bach's mastery of Baroque keyboard style, with "
                 "characteristic contrapuntal writing, expressive harmonic language, and "
                 "careful formal structure. Bach's keyboard works remain central to the "
                 "repertoire, combining pedagogical value with profound artistic expression.")
    return fallback


def get_evidence_sources(piece):
    """Return evidence sources based on the composition."""
    composition = piece["composition"]
    movement = piece["movement"]
    sources = []

    # Wikipedia articles for major works
    if "Inventions" in composition and "Sinfonias" not in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Inventions_and_Sinfonias",
            "title": "Inventions and Sinfonias - Wikipedia"
        })
    elif "Sinfonias" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Inventions_and_Sinfonias",
            "title": "Inventions and Sinfonias - Wikipedia"
        })
    elif "Well-Tempered Clavier, Book I" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/The_Well-Tempered_Clavier",
            "title": "The Well-Tempered Clavier - Wikipedia"
        })
        bwv_match = re.search(r'BWV\s*(\d+)', movement)
        if bwv_match:
            bwv_num = bwv_match.group(1)
            sources.append({
                "type": "program_notes",
                "url": f"https://www.bach-cantatas.com/KCA/Page-{bwv_num}.htm",
                "title": f"Bach Cantatas Website - BWV {bwv_num} analysis"
            })
    elif "Well-Tempered Clavier, Book II" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/The_Well-Tempered_Clavier",
            "title": "The Well-Tempered Clavier - Wikipedia"
        })
    elif "English Suite" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/English_Suites_(Bach)",
            "title": "English Suites (Bach) - Wikipedia"
        })
    elif "French Suite" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/French_Suites_(Bach)",
            "title": "French Suites (Bach) - Wikipedia"
        })
    elif "Partita" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Clavier-%C3%9Cbung",
            "title": "Clavier-Ubung - Wikipedia"
        })
    elif "Goldberg" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Goldberg_Variations",
            "title": "Goldberg Variations - Wikipedia"
        })
    elif "Italian Concerto" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Italian_Concerto",
            "title": "Italian Concerto - Wikipedia"
        })
    elif "Chromatic Fantasia" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Chromatic_Fantasia_and_Fugue",
            "title": "Chromatic Fantasia and Fugue - Wikipedia"
        })
    elif "Kunst der Fuge" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/The_Art_of_Fugue",
            "title": "The Art of Fugue - Wikipedia"
        })
    elif "Matthäus" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/St_Matthew_Passion",
            "title": "St Matthew Passion - Wikipedia"
        })
    elif "Weihnachts" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Christmas_Oratorio",
            "title": "Christmas Oratorio - Wikipedia"
        })
    elif "Cello Suite" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Cello_Suites",
            "title": "Cello Suites (Bach) - Wikipedia"
        })
    elif "Chorale Prelude" in composition:
        sources.append({
            "type": "program_notes",
            "url": "https://www.bach-cantatas.com/",
            "title": "Bach Cantatas Website - Chorale Preludes"
        })
    elif "Toccatas" in composition:
        sources.append({
            "type": "encyclopedia",
            "url": "https://en.wikipedia.org/wiki/Toccatas,_BWV_910%E2%80%93916",
            "title": "Toccatas, BWV 910-916 - Wikipedia"
        })
    elif "Anna Magdalena" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Notebook_for_Anna_Magdalena_Bach",
            "title": "Notebook for Anna Magdalena Bach - Wikipedia"
        })
    elif "Kleine Präludien" in composition or "Kleine Praludien" in composition:
        sources.append({
            "type": "encyclopedia",
            "url": "https://en.wikipedia.org/wiki/List_of_compositions_by_Johann_Sebastian_Bach",
            "title": "List of compositions by J.S. Bach - Wikipedia"
        })
    elif "Duets" in composition:
        sources.append({
            "type": "wikipedia",
            "url": "https://en.wikipedia.org/wiki/Goldberg_Variations",
            "title": "Goldberg Variations / Clavier-Ubung - Wikipedia"
        })
    else:
        sources.append({
            "type": "encyclopedia",
            "url": "https://en.wikipedia.org/wiki/Johann_Sebastian_Bach",
            "title": "Johann Sebastian Bach - Wikipedia"
        })

    return sources


def main():
    with open(INPUT, "r") as f:
        data = json.load(f)

    pieces = data["pieces"]
    entries = []

    for piece in pieces:
        text = get_piece_text(piece)
        sources = get_evidence_sources(piece)
        entry = {
            "piece_id": piece["piece_id"],
            "text": text.strip(),
            "evidence_sources": sources
        }
        entries.append(entry)

    with open(OUTPUT, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Wrote {len(entries)} entries to {OUTPUT}")

    # Stats
    lengths = [len(e["text"]) for e in entries]
    print(f"Text length stats:")
    print(f"  Min: {min(lengths)} chars")
    print(f"  Max: {max(lengths)} chars")
    print(f"  Mean: {sum(lengths)/len(lengths):.0f} chars")
    below = sum(1 for l in lengths if l < 500)
    above = sum(1 for l in lengths if l > 1500)
    print(f"  Below 500 chars: {below}")
    print(f"  Above 1500 chars: {above}")


if __name__ == "__main__":
    main()
