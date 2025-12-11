import feedparser
import requests
import json
import os
import re
import whisper
from datetime import datetime

# Configuration
RSS_URL = "https://www.omnycontent.com/d/playlist/61ee9ca4-a1b2-4660-9651-b2b70035edf5/0c13f220-bf12-49ed-9d47-b2f100f7c60c/c39fca6c-3f36-4b12-a7e8-b2f100f7c61a/podcast.rss"
DATA_DIR = "data"
ASSETS_DIR = "assets"
AUDIO_DIR = os.path.join(ASSETS_DIR, "audio")
IMAGE_DIR = os.path.join(ASSETS_DIR, "images")
TRANSCRIPTION_DIR = os.path.join(ASSETS_DIR, "transcriptions")
EPISODES_FILE = os.path.join(DATA_DIR, "episodes.json")

# Limits
EPISODE_LIMIT = None # Set to None to process all episodes
TRANSCRIPTION_LIMIT = 3 # Only transcribe the first N episodes

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPTION_DIR, exist_ok=True)

def sanitize_filename(name):
    return re.sub(r'[\\/*?:\"<>|]', "", name).replace(" ", "_").lower()

def download_file(url, filepath):
    if os.path.exists(filepath):
        print(f"File already exists: {filepath}")
        return
    
    print(f"Downloading {url} to {filepath}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("Download complete.")
    except Exception as e:
        print(f"Error downloading {url}: {e}")

def transcribe_audio(audio_path):
    print(f"Transcribing {audio_path}...")
    try:
        # Load model (using 'base' for speed in prototype)
        model = whisper.load_model("base")
        
        # Transcribe
        result = model.transcribe(audio_path, language="nl") # Dutch
        return result["text"]
    except Exception as e:
        print(f"Transcription failed: {e}")
        return "Transcription unavailable."

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
    if not text:
        return text
    
    # Case-insensitive search
    lower_text = text.lower()
    keyword = "aflevering"
    
    first_index = lower_text.find(keyword)
    last_index = lower_text.rfind(keyword)
    
    # If "aflevering" appears less than twice (start and end markers), do not cut.
    if first_index == -1 or last_index == -1 or first_index == last_index:
        return text
    
    # Include the last occurrence fully
    end_pos = last_index + len(keyword)
    
    return text[first_index:end_pos]

def main():
    ensure_dirs()
    
    print(f"Parsing RSS feed: {RSS_URL}")
    try:
        response = requests.get(RSS_URL, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return
    
    episodes = []
    
    # Load existing data to avoid re-work if we run multiple times
    if os.path.exists(EPISODES_FILE):
        with open(EPISODES_FILE, 'r') as f:
            try:
                episodes = json.load(f)
                print(f"Loaded {len(episodes)} existing episodes.")
            except json.JSONDecodeError:
                pass
    
    existing_guids = {ep['guid'] for ep in episodes}
    
    count = 0
    for entry in feed.entries:
        if EPISODE_LIMIT and count >= EPISODE_LIMIT:
            break
            
        guid = entry.get('id', entry.link)
        
        if guid in existing_guids:
            # We might want to update details, but skip for now
            count += 1
            continue

        title = entry.title
        print(f"Processing: {title}")
        
        # Get Audio URL
        audio_url = None
        for link in entry.links:
            if link['type'].startswith('audio/'):
                audio_url = link['href']
                break
        
        if not audio_url:
            print("No audio found, skipping.")
            continue
            
        # Get Image URL
        image_url = entry.image.href if 'image' in entry else None
        if not image_url and 'itunes_image' in entry:
            image_url = entry.itunes_image.get('href')

        # Filenames
        safe_title = sanitize_filename(title)
        
        keywords = []
        transcription_file_entry = None
        
        # Logic to decide if we transcribe
        if count < TRANSCRIPTION_LIMIT:
            audio_filename = f"{safe_title}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            
            # Download Audio (Still needed for transcription)
            download_file(audio_url, audio_path)
            
            # Transcribe (Stub/Real)
            transcription = "Transcription pending..."
            transcription_filename = f"{safe_title}.txt"
            transcription_path = os.path.join(TRANSCRIPTION_DIR, transcription_filename)
            
            if os.path.exists(transcription_path):
                print(f"Loading existing transcription from {transcription_path}")
                with open(transcription_path, 'r') as f:
                    transcription = f.read()
            elif os.path.exists(audio_path):
                transcription = transcribe_audio(audio_path)
            
            # Trim transcription
            transcription = trim_transcription(transcription)

            keywords = extract_keywords(transcription)

            # Save transcription to file (update/create)
            with open(transcription_path, "w") as f:
                f.write(transcription)
                
            transcription_file_entry = f"assets/transcriptions/{transcription_filename}"
        else:
            # print("Skipping transcription (limit reached)")
            pass

        episode_data = {
            'guid': guid,
            'title': title,
            'published': entry.published,
            'description': entry.summary,
            'audio_file': audio_url,
            'image_file': image_url,
            'transcription_file': transcription_file_entry,
            'keywords': keywords,
            'original_link': entry.link
        }
        
        episodes.append(episode_data)
        count += 1
        
    # Save Data
    with open(EPISODES_FILE, 'w') as f:
        json.dump(episodes, f, indent=4)
    print("Data fetch complete.")

if __name__ == "__main__":
    main()