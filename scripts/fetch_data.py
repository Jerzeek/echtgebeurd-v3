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
OPENAI_MAX_BYTES = 24 * 1024 * 1024  # the API rejects uploads over 25 MB
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)

def restore_published_transcriptions():
    """On a fresh clone (empty assets/transcriptions) copy the transcripts already published in docs/ back."""
    if any(n.endswith(".txt") for n in os.listdir(TRANSCRIPTION_DIR)):
        return
    if not os.path.isdir(PUBLISHED_TRANSCRIPTION_DIR):
        return
    restored = 0
    for name in os.listdir(PUBLISHED_TRANSCRIPTION_DIR):
        if name.endswith(".txt"):
            shutil.copy2(os.path.join(PUBLISHED_TRANSCRIPTION_DIR, name), os.path.join(TRANSCRIPTION_DIR, name))
            restored += 1
    print(f"Restored {restored} transcription(s) from {PUBLISHED_TRANSCRIPTION_DIR}.")

def sanitize_filename(name):
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

def shrink_audio(audio_path):
    """Re-encode to a small mono MP3 so it fits under the API upload limit. Needs ffmpeg."""
    out = os.path.join(tempfile.gettempdir(), os.path.splitext(os.path.basename(audio_path))[0] + "_small.mp3")
    print(f"Audio is larger than {OPENAI_MAX_BYTES // (1024 * 1024)} MB, shrinking with ffmpeg...")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", "32k", out],
        check=True,
    )
    return out


class OpenAITranscriber:
    name = f"OpenAI API ({OPENAI_MODEL})"

    def __init__(self):
        self.api_key = os.environ["OPENAI_API_KEY"]

    def transcribe(self, audio_path):
        path = shrink_audio(audio_path) if os.path.getsize(audio_path) > OPENAI_MAX_BYTES else audio_path
        with open(path, "rb") as f:
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (os.path.basename(path), f, "audio/mpeg")},
                data={"model": OPENAI_MODEL, "language": "nl", "response_format": "json"},
                timeout=900,
            )
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI API returned {response.status_code}: {response.text[:300]}")
        return response.json()["text"]


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
                    if not episode.get('keywords'):
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
