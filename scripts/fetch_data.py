import feedparser
import requests
import json
import os
import re
import ssl
import platform
import shutil
import subprocess
import tempfile
import time
import unicodedata
from datetime import datetime

# Some corporate networks intercept TLS, which breaks model downloads locally. Not needed on CI.
if os.environ.get("CI") != "true":
    ssl._create_default_https_context = ssl._create_unverified_context

# Configuration
RSS_URL = "https://www.omnycontent.com/d/playlist/61ee9ca4-a1b2-4660-9651-b2b70035edf5/0c13f220-bf12-49ed-9d47-b2f100f7c60c/c39fca6c-3f36-4b12-a7e8-b2f100f7c61a/podcast.rss"
DATA_DIR = "data"
ASSETS_DIR = "assets"
AUDIO_DIR = os.path.join(ASSETS_DIR, "audio")
IMAGE_DIR = os.path.join(ASSETS_DIR, "images")
TRANSCRIPTION_DIR = os.path.join(ASSETS_DIR, "transcriptions")
EPISODES_FILE = os.path.join(DATA_DIR, "episodes.json")
# assets/ is not in git, but the built site in docs/ is. A fresh clone reuses the transcripts published there.
PUBLISHED_TRANSCRIPTION_DIR = os.path.join("docs", "assets", "transcriptions")

# Limits
EPISODE_LIMIT = 600 # Set to None to process all episodes
TRANSCRIPTION_LIMIT = 600 # Only transcribe the first N episodes

# How many episodes may be transcribed in a single run. Unset = no cap. CI sets this to bound run time.
MAX_NEW_TRANSCRIPTIONS = os.environ.get("MAX_NEW_TRANSCRIPTIONS")
MAX_NEW_TRANSCRIPTIONS = int(MAX_NEW_TRANSCRIPTIONS) if MAX_NEW_TRANSCRIPTIONS not in (None, "") else None

# Transcription engine: "auto" uses the OpenAI API when OPENAI_API_KEY is set, otherwise a local Whisper model.
# Force one with TRANSCRIBE_ENGINE=openai or TRANSCRIBE_ENGINE=local.
TRANSCRIBE_ENGINE = os.environ.get("TRANSCRIBE_ENGINE", "auto")
OPENAI_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
# gpt-4o-transcribe silently stops after ~2000 output tokens (about 7 minutes of Dutch speech),
# so long episodes are sent in pieces of at most this many seconds.
OPENAI_CHUNK_SECONDS = 240
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)

def restore_published_transcriptions():
    """Copy the published transcripts from docs/ into assets/, overwriting local copies.

    docs/ is committed and is what the weekly GitHub run updates (and cleans), so it is the source of truth.
    Without this, a local build would overwrite newer published transcripts with stale local ones.
    To force a transcript to be redone, delete it from both docs/assets/transcriptions and assets/transcriptions.
    """
    if not os.path.isdir(PUBLISHED_TRANSCRIPTION_DIR):
        return
    restored = 0
    for name in os.listdir(PUBLISHED_TRANSCRIPTION_DIR):
        if name.endswith(".txt"):
            shutil.copy2(os.path.join(PUBLISHED_TRANSCRIPTION_DIR, name), os.path.join(TRANSCRIPTION_DIR, name))
            restored += 1
    print(f"Synced {restored} published transcription(s) from {PUBLISHED_TRANSCRIPTION_DIR}.")

def normalize_transcription_names():
    """Some feed titles contain decomposed characters (u + combining accent). macOS and git store those
    file names precomposed (NFC), Linux keeps them byte-for-byte, so on CI the existing transcript was not
    found and the episode was transcribed again under a second, decomposed name. Keep one NFC name."""
    names = set(os.listdir(TRANSCRIPTION_DIR))
    for name in sorted(names):
        nfc = unicodedata.normalize("NFC", name)
        if nfc == name:
            continue
        path = os.path.join(TRANSCRIPTION_DIR, name)
        if nfc in names:
            # Two separate files (only possible on Linux): keep the precomposed original.
            os.remove(path)
            print(f"Removed duplicate transcription with decomposed name: {name}")
        elif not os.path.exists(os.path.join(TRANSCRIPTION_DIR, nfc)):
            os.rename(path, os.path.join(TRANSCRIPTION_DIR, nfc))
            print(f"Renamed transcription to precomposed name: {nfc}")

def sanitize_filename(name):
    name = unicodedata.normalize("NFC", name)
    return re.sub(r'[\\/*?:\"<>|]', "", name).replace(" ", "_").lower()

def download_file(url, filepath):
    if os.path.exists(filepath):
        print(f"File already exists: {filepath}")
        return
    
    print(f"Downloading {url} to {filepath}...")
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("Download complete.")
    except Exception as e:
        print(f"Error downloading {url}: {e}")


# ---------------------------------------------------------------------------
# Transcription engines
# ---------------------------------------------------------------------------

def audio_duration(audio_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio_path],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def find_pauses(audio_path):
    """Midpoints (seconds) of short pauses, so chunks are cut between words instead of through them."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", audio_path,
         "-af", "silencedetect=noise=-25dB:d=0.2", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", result.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", result.stderr)]
    return [(a + b) / 2 for a, b in zip(starts, ends)]


def chunk_boundaries(duration, pauses, max_seconds):
    """Cut points [0, ..., duration]; each cut is the last pause in the final minute before the limit."""
    points = [0.0]
    while duration - points[-1] > max_seconds:
        limit = points[-1] + max_seconds
        candidates = [p for p in pauses if limit - 60 <= p <= limit]
        points.append(max(candidates) if candidates else limit)
    points.append(duration)
    return points


class OpenAITranscriber:
    name = f"OpenAI API ({OPENAI_MODEL})"

    def __init__(self):
        self.api_key = os.environ["OPENAI_API_KEY"]

    def _request(self, chunk_path, prompt):
        data = {"model": OPENAI_MODEL, "language": "nl", "response_format": "json"}
        if prompt:
            data["prompt"] = prompt
        for attempt in range(3):
            with open(chunk_path, "rb") as f:
                response = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (os.path.basename(chunk_path), f, "audio/mpeg")},
                    data=data,
                    timeout=300,
                )
            if response.status_code == 200:
                return response.json()["text"].strip()
            if response.status_code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"OpenAI API returned {response.status_code}: {response.text[:300]}")

    def transcribe(self, audio_path):
        duration = audio_duration(audio_path)
        points = chunk_boundaries(duration, find_pauses(audio_path), OPENAI_CHUNK_SECONDS)
        print(f"  {duration / 60:.1f} min of audio, sending {len(points) - 1} chunk(s).")
        parts = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, (start, end) in enumerate(zip(points, points[1:])):
                chunk_path = os.path.join(tmp, f"chunk_{i:03d}.mp3")
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
                     "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", "32k", chunk_path],
                    check=True,
                )
                # The end of the previous chunk gives the model context to continue mid-story.
                prompt = parts[-1][-300:].split(" ", 1)[-1] if parts else None
                text = self._request(chunk_path, prompt)
                if text:
                    parts.append(text)
        return " ".join(parts)


class LocalWhisperTranscriber:
    def __init__(self):
        self.use_mlx = False
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            try:
                import mlx_whisper  # noqa: F401
                self.use_mlx = True
            except ImportError:
                pass

        if self.use_mlx:
            self.model = f"mlx-community/whisper-{WHISPER_MODEL}-mlx"
            self.name = f"mlx_whisper ({self.model})"
            print("Apple Silicon Mac detected. Using mlx_whisper.")
        else:
            import torch
            import whisper
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.name = f"whisper {WHISPER_MODEL} on {device.upper()}"
            print(f"Loading Whisper model '{WHISPER_MODEL}' on {device.upper()}...")
            self.model = whisper.load_model(WHISPER_MODEL, device=device)

    def transcribe(self, audio_path):
        if self.use_mlx:
            import mlx_whisper
            result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=self.model, language="nl")
        else:
            result = self.model.transcribe(audio_path, language="nl")
        return result["text"]


def make_transcriber():
    engine = TRANSCRIBE_ENGINE
    if engine == "auto":
        engine = "openai" if os.environ.get("OPENAI_API_KEY") else "local"
    if engine == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("TRANSCRIBE_ENGINE=openai but OPENAI_API_KEY is not set.")
        return OpenAITranscriber()
    return LocalWhisperTranscriber()


def transcribe_audio(transcriber, audio_path):
    """Returns the transcript text, or None when transcription failed (so a later run retries)."""
    start_time = datetime.now()
    print(f"[{start_time.strftime('%H:%M:%S')}] Transcribing {audio_path} with {transcriber.name}...")
    try:
        text = transcriber.transcribe(audio_path)
        end_time = datetime.now()
        print(f"[{end_time.strftime('%H:%M:%S')}] Transcription finished in {end_time - start_time}.")
        return text
    except Exception as e:
        print(f"Transcription failed: {e}")
        return None

def extract_keywords(text, n=10):
    if not text:
        return []
        
    # Basic Dutch stopwords
    stopwords = {
        "de", "het", "een", "en", "van", "ik", "te", "dat", "die", "in", "is", "op", "voor", "met", "als", "niet", 
        "om", "hij", "ze", "dan", "ook", "je", "er", "mijn", "maar", "aan", "of", "hier", "naar", "uit", "hem", 
        "haar", "wil", "heb", "had", "zou", "wat", "wel", "zo", "we", "ons", "u", "dit", "deze", "toen", "nog", 
        "zal", "moet", "kan", "nu", "bij", "geen", "doen", "omdat", "goed", "waar", "ben", "wij", "al", "door", 
        "over", "mij", "meer", "iets", "alles", "dus", "zijn", "waren", "was", "heel", "gewoon", "weet", "gaat", 
        "gaan", "ging", "kwam", "komen", "mensen", "jaar", "dag", "keer", "aflevering", "echt", "gebeurd", 
        "podcast", "verhaal", "verhalen", "hoi", "tom", "welkom", "onze", "jou", "jij", "jullie", "hun", "heeft", 
        "hadden", "worden", "kunnen", "maken", "zien", "zeggen", "allemaal", "eigenlijk", "natuurlijk", "misschien", 
        "vinden", "soms", "twee", "drie", "vier", "vijf", "erg", "grote", "kleine", "beetje", "terug", "laatste", 
        "eerst", "later", "toch", "echt", "zeg", "zei", "zegt"
    }
    
    # Normalize text: lowercase and remove punctuation
    words = re.findall(r'\b\w+\b', text.lower())
    
    # Filter stopwords and short words
    filtered_words = [w for w in words if w not in stopwords and len(w) > 2]
    
    # Count frequency
    frequency = {}
    for w in filtered_words:
        frequency[w] = frequency.get(w, 0) + 1
        
    # Sort by frequency
    sorted_words = sorted(frequency.items(), key=lambda item: item[1], reverse=True)
    
    return [word for word, count in sorted_words[:n]]

def trim_transcription(text):
    # Trimming disabled: return full text
    return text

def main():
    ensure_dirs()
    restore_published_transcriptions()
    normalize_transcription_names()
    
    print(f"Parsing RSS feed: {RSS_URL}")
    try:
        response = requests.get(RSS_URL, timeout=30)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        raise SystemExit(1)

    # The transcription model is only loaded once an episode actually needs it.
    transcriber = None
    transcribed_this_run = 0
    
    episodes = []
    
    # Load existing data to avoid re-work if we run multiple times
    if os.path.exists(EPISODES_FILE):
        with open(EPISODES_FILE, 'r', encoding='utf-8') as f:
            try:
                episodes = json.load(f)
                print(f"Loaded {len(episodes)} existing episodes.")
            except json.JSONDecodeError:
                pass
    
    count = 0
    for entry in feed.entries:
        if EPISODE_LIMIT and count >= EPISODE_LIMIT:
            break
            
        guid = entry.get('id', entry.link)
        title = entry.title

        # Find existing episode or create new one
        episode = next((ep for ep in episodes if ep['guid'] == guid), None)
        is_new = False
        
        if episode is None:
            is_new = True
            print(f"New episode: {title}")
            episode = {
                'guid': guid,
                'title': title,
                'published': entry.published,
                'description': entry.summary,
                'original_link': entry.link,
                'keywords': []
            }
        else:
            # Update mutable metadata
            episode['title'] = title
            episode['published'] = entry.published
            episode['description'] = entry.summary
            episode['original_link'] = entry.link

        # Get Audio URL
        audio_url = None
        for link in entry.links:
            if link['type'].startswith('audio/'):
                audio_url = link['href']
                break
        episode['audio_file'] = audio_url
        
        if not audio_url:
            print(f"No audio found for {title}, skipping.")
            count += 1 
            continue
            
        # Get Image URL
        image_url = entry.image.href if 'image' in entry else None
        if not image_url and 'itunes_image' in entry:
            image_url = entry.itunes_image.get('href')
        episode['image_file'] = image_url

        # Transcription Logic
        if count < TRANSCRIPTION_LIMIT:
            safe_title = sanitize_filename(title)
            audio_filename = f"{safe_title}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            transcription_filename = f"{safe_title}.txt"
            transcription_path = os.path.join(TRANSCRIPTION_DIR, transcription_filename)
            
            current_transcript_file = episode.get('transcription_file')
            transcript_exists = current_transcript_file and os.path.exists(current_transcript_file)
            
            if not transcript_exists:
                if os.path.exists(transcription_path):
                    # We have the file locally even if the json doesn't know about it
                    print(f"Linking existing transcription: {transcription_path}")
                    with open(transcription_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    episode['transcription_file'] = f"assets/transcriptions/{transcription_filename}"
                    episode['keywords'] = extract_keywords(text)
                elif MAX_NEW_TRANSCRIPTIONS is not None and transcribed_this_run >= MAX_NEW_TRANSCRIPTIONS:
                    print(f"Skipping transcription of '{title}': cap of {MAX_NEW_TRANSCRIPTIONS} per run reached.")
                else:
                    download_file(audio_url, audio_path)
                    if os.path.exists(audio_path):
                        if transcriber is None:
                            transcriber = make_transcriber()
                        transcription = transcribe_audio(transcriber, audio_path)
                        if transcription:
                            transcription = trim_transcription(transcription)
                            with open(transcription_path, "w", encoding='utf-8') as f:
                                f.write(transcription)
                            episode['transcription_file'] = f"assets/transcriptions/{transcription_filename}"
                            episode['keywords'] = extract_keywords(transcription)
                            transcribed_this_run += 1
                    else:
                        print(f"Audio file missing, cannot transcribe: {audio_path}")

        if is_new:
            episodes.append(episode)
            
        count += 1
        
    # Save Data
    with open(EPISODES_FILE, 'w', encoding='utf-8') as f:
        json.dump(episodes, f, indent=4, ensure_ascii=False)
    print(f"Data fetch complete. {transcribed_this_run} episode(s) transcribed this run.")

if __name__ == "__main__":
    main()
