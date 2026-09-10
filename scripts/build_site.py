import hashlib
import json
import os
import re
import shutil
from collections import Counter
from html import unescape

from jinja2 import Environment, FileSystemLoader

# Configuration
BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
EPISODES_FILE = os.path.join(DATA_DIR, "episodes.json")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
ASSETS_SRC = os.path.join(BASE_DIR, "assets")
ASSETS_DEST = os.path.join(DOCS_DIR, "assets")
DATA_DEST = os.path.join(DOCS_DIR, "data")

# Titles look like "Afl. 542 Kerst: Richard Saly". Older ones use a dash or no separator.
TITLE_PATTERNS = [
    re.compile(r"^Afl\.?\s*(\d+)\.?\s+(.+?)\s*[:\-–]\s*(.+)$"),
    re.compile(r"^(?:Uit het archief|Bonusaflevering)\s*:\s*(.+?)\s*[\-–]\s*(.+)$"),
]

# Paragraphs in the RSS description that are marketing boilerplate rather than about the episode.
BOILERPLATE = re.compile(
    r"omnystudio\.com|vriend van de show|adverteren in onze podcast|te volgen op|"
    r"leren hoe je dat|instagram\.com/echt_gebeurd|dagennacht|geef-je-op|thema.s voor alle verhalenmiddagen|"
    r"meld je (?:dan )?bij ons|waargebeurd verhaal dat je|aanmelden via onze|op zoek naar nieuwe vertellers|"
    r"gesponsord door|^\s*_{5,}\s*$|een keer (?:een )?verhaal (?:bij ons )?vertellen",
    re.I,
)

# Words that slip through the keyword extractor but say nothing about an episode.
EXTRA_STOPWORDS = {
    "hoe", "hebben", "staat", "want", "denk", "alleen", "even", "zeker", "ja", "nee", "nou", "oh", "ok", "oké",
    "dacht", "denken", "zit", "zat", "zitten", "komt", "gaan", "gingen", "kom", "kijk", "kijken", "keek", "ziet",
    "zag", "zagen", "weer", "toe", "tegen", "onder", "boven", "tussen", "zonder", "achter", "eens", "iemand",
    "niemand", "niets", "niks", "veel", "weinig", "elke", "elk", "ieder", "iedereen", "andere", "ander", "anders",
    "zelf", "zelfs", "ooit", "nooit", "altijd", "vaak", "steeds", "meteen", "daar", "daarna", "dan", "toen",
    "vandaag", "morgen", "gisteren", "avond", "nacht", "ochtend", "week", "weken", "maand", "maanden", "jaren",
    "uur", "minuten", "één", "een", "eerste", "tweede", "derde", "tien", "twintig", "honderd", "duizend",
    "helemaal", "precies", "ineens", "opeens", "best", "heb", "hebt", "moest", "moeten", "mocht", "mogen",
    "wilde", "willen", "wou", "kon", "konden", "zou", "zouden", "zul", "zullen", "wordt", "werd", "werden",
    "geworden", "gedaan", "doet", "deed", "deden", "gaf", "geven", "gegeven", "krijg", "krijgt", "kreeg",
    "kregen", "krijgen", "gekregen", "hoor", "hoorde", "horen", "ging", "gegaan", "gekomen", "gezegd", "gezien",
    "gehad", "geweest", "vind", "vond", "vonden", "voel", "voelde", "voelen", "weet", "wist", "wisten", "weten",
    "zeggen", "zei", "zeiden", "vraag", "vragen", "vroeg", "vroegen", "antwoord", "man", "vrouw", "jongen",
    "meisje", "meneer", "mevrouw", "moment", "tijd", "ding", "dingen", "soort", "manier", "plek", "kant", "eind",
    "einde", "begin", "hele", "half", "lang", "kort", "nieuw", "nieuwe", "oud", "oude", "goeie", "goede", "leuk",
    "leuke", "mooi", "mooie", "raar", "rare", "blij", "bang", "hard", "zacht", "snel", "langzaam", "gewoon",
    "misschien", "waarschijnlijk", "inderdaad", "uiteindelijk", "ondertussen", "trouwens", "tenminste",
    "ergens", "nergens", "overal", "thuis", "huis", "weg", "wegen", "auto", "hier", "daarom", "dus", "omdat",
    "terwijl", "hoewel", "zodat", "voordat", "nadat", "totdat", "alsof", "applaus", "publiek", "verteller",
    "vertellen", "vertelde", "verteld", "thema", "middag", "toomler", "amsterdam", "welkom", "luister",
    "luisteren", "wij", "jullie", "hun", "hen", "haar", "hem", "zij", "u", "het", "de", "die", "dat", "deze",
    "dit", "wat", "wie", "waar", "waarom", "wanneer", "welke", "welk", "dezelfde", "zo'n", "zon", "z'n",
    "m'n", "d'r", "hè", "hé", "gewoon", "echt", "heel", "erg", "ook", "nog", "wel", "niet", "al", "maar",
    "of", "en", "ja", "zo", "nou", "goed", "beetje", "keer", "eigenlijk", "natuurlijk", "allemaal",
}


def parse_title(title):
    """Split a title into episode number, theme and storyteller. Returns None fields when unknown."""
    if not title:
        return None, None, None
    m = TITLE_PATTERNS[0].match(title)
    if m:
        return int(m.group(1)), m.group(2).strip(), m.group(3).strip()
    m = TITLE_PATTERNS[1].match(title)
    if m:
        # "Uit het archief: Name – Theme"
        return None, m.group(2).strip(), m.group(1).strip()
    m = re.match(r"^Afl\.?\s*(\d+)\.?\s*:?\s*(.*)$", title)
    if m:
        return int(m.group(1)), None, (m.group(2).strip() or None)
    return None, None, None


def strip_tags(html):
    return unescape(re.sub(r"<[^>]+>", " ", html or ""))


OMNY_NOTICE = re.compile(r"See\s*<a[^>]*>omnystudio\.com/listener</a>\s*for privacy information\.?", re.I)


def split_paragraphs(html):
    html = OMNY_NOTICE.sub("", html or "")
    # Text can sit inside <p> blocks, outside them, or be separated by <br>; treat every chunk as a paragraph.
    parts = []
    for chunk in re.split(r"</?p[^>]*>", html):
        parts.extend(re.split(r"<br\s*/?>", chunk))
    return [p for p in parts if p.strip()]


def clean_description(html, common):
    """Drop boilerplate paragraphs, keep what is actually about the episode."""
    kept = []
    for p in split_paragraphs(html):
        text = re.sub(r"\s+", " ", strip_tags(p)).strip()
        if not text or text == "///":
            continue
        if BOILERPLATE.search(p) or common.get(text.lower(), 0) >= 4:
            continue
        kept.append("<p>" + p.strip() + "</p>")
    return "".join(kept)


def clean_keywords(keywords, limit=8):
    seen = []
    for kw in keywords or []:
        kw = kw.strip().lower()
        if len(kw) < 4 or kw in EXTRA_STOPWORDS or kw in seen or kw.isdigit():
            continue
        seen.append(kw)
    return seen[:limit]


def read_text(path):
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as fh:
                return fh.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    print(f"Could not read {path} with any encoding")
    return ""


def main():
    print(f"Building site from {BASE_DIR}...")

    if not os.path.exists(EPISODES_FILE):
        print("Error: No data found. Run fetch_data.py first.")
        return

    with open(EPISODES_FILE, "r", encoding="utf-8") as f:
        episodes = json.load(f)

    # Count description paragraphs across all episodes so repeated ones can be treated as boilerplate.
    common = Counter()
    for episode in episodes:
        for p in split_paragraphs(episode.get("description")):
            text = re.sub(r"\s+", " ", strip_tags(p)).strip().lower()
            if text:
                common[text] += 1

    frontend_episodes = []
    search_documents = []
    print(f"Processing {len(episodes)} episodes...")

    for episode in episodes:
        number, theme, storyteller = parse_title(episode.get("title"))
        description = clean_description(episode.get("description"), common)
        keywords = clean_keywords(episode.get("keywords"))

        transcription_text = ""
        transcription_path = episode.get("transcription_file")
        if transcription_path:
            full_path = os.path.join(BASE_DIR, transcription_path)
            if os.path.exists(full_path):
                transcription_text = read_text(full_path)
            else:
                print(f"Transcription file not found: {full_path}")

        words = len(transcription_text.split())

        frontend_episodes.append({
            "guid": episode.get("guid"),
            "title": episode.get("title"),
            "number": number,
            "theme": theme,
            "storyteller": storyteller,
            "published": episode.get("published"),
            "description": description,
            "image_file": episode.get("image_file"),
            "audio_file": episode.get("audio_file"),
            "original_link": episode.get("original_link"),
            "keywords": keywords,
            "transcription_file": transcription_path if transcription_text else None,
            "words": words,
        })

        search_documents.append({
            "id": episode.get("guid"),
            "title": episode.get("title"),
            "who": storyteller or "",
            "theme": theme or "",
            "txt": transcription_text,
            "desc": strip_tags(description),
            "keywords": " ".join(keywords),
        })

    os.makedirs(DOCS_DIR, exist_ok=True)
    os.makedirs(DATA_DEST, exist_ok=True)

    with open(os.path.join(DATA_DEST, "episodes.json"), "w", encoding="utf-8") as f:
        json.dump(frontend_episodes, f, ensure_ascii=False)

    with open(os.path.join(DATA_DEST, "search_index.json"), "w", encoding="utf-8") as f:
        json.dump(search_documents, f, ensure_ascii=False)

    print("Generated JSON data files.")

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("index.html")
    # A short hash of the data lets the browser cache JSON aggressively but still pick up new builds.
    with open(os.path.join(DATA_DEST, "search_index.json"), "rb") as f:
        build_id = hashlib.sha1(f.read()).hexdigest()[:10]
    output = template.render(episode_count=len(frontend_episodes), build_id=build_id)

    output_path = os.path.join(DOCS_DIR, "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Site shell generated at {output_path}")

    if os.path.exists(ASSETS_SRC):
        if os.path.exists(ASSETS_DEST):
            shutil.rmtree(ASSETS_DEST)
        shutil.copytree(ASSETS_SRC, ASSETS_DEST, ignore=shutil.ignore_patterns("audio", ".DS_Store"))
        print(f"Assets copied to {ASSETS_DEST}")


if __name__ == "__main__":
    main()
