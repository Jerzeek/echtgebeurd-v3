import json
import os
import shutil
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

def main():
    print(f"Building site from {BASE_DIR}...")

    # 1. Load Data
    if not os.path.exists(EPISODES_FILE):
        print("Error: No data found. Run fetch_data.py first.")
        return

    with open(EPISODES_FILE, 'r', encoding='utf-8') as f:
        episodes = json.load(f)

    # 2. Prepare Data for Frontend
    # We want two datasets:
    # A. Light metadata for the UI list (episodes.json)
    # B. Full text index for Search (search_index.json)
    
    frontend_episodes = []
    search_documents = []

    print(f"Processing {len(episodes)} episodes...")

    for episode in episodes:
        # --- Prepare Light Metadata ---
        # We keep the essential fields for display
        frontend_ep = {
            "guid": episode.get("guid"),
            "title": episode.get("title"),
            "published": episode.get("published"),
            "description": episode.get("description"), # Description is usually HTML, might be large but useful
            "image_file": episode.get("image_file"),
            "audio_file": episode.get("audio_file"),
            "original_link": episode.get("original_link"),
            "keywords": episode.get("keywords", []),
            "transcription_file": episode.get("transcription_file") # Frontend will fetch this on demand
        }
        frontend_episodes.append(frontend_ep)

        # --- Prepare Search Index ---
        # We need to read the transcription text to index it
        transcription_text = ""
        transcription_path = episode.get("transcription_file")
        
        if transcription_path:
            # The path in json is relative like "assets/transcriptions/..."
            # We need to resolve it relative to the project root
            full_transcription_path = os.path.join(BASE_DIR, transcription_path)
            
            if os.path.exists(full_transcription_path):
                # Try multiple encodings to handle different file encodings properly
                encodings_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
                transcription_text_read = False
                
                for encoding in encodings_to_try:
                    try:
                        with open(full_transcription_path, 'r', encoding=encoding) as tf:
                            transcription_text = tf.read()
                        transcription_text_read = True
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                    except Exception as e:
                        print(f"Error reading transcription {full_transcription_path} with {encoding}: {e}")
                        break
                
                if not transcription_text_read:
                    print(f"Could not read transcription {full_transcription_path} with any encoding")
            else:
                print(f"Transcription file not found: {full_transcription_path}")

        # Search Doc Structure (optimized for MiniSearch)
        search_doc = {
            "id": episode.get("guid"),
            "title": episode.get("title"),
            "txt": transcription_text, # Full text
            "desc": episode.get("description"),
            "keywords": " ".join(episode.get("keywords", [])),
            "date": episode.get("published")
        }
        search_documents.append(search_doc)

    # 3. Ensure Output Directories
    os.makedirs(DOCS_DIR, exist_ok=True)
    os.makedirs(DATA_DEST, exist_ok=True)

    # 4. Write JSON Data
    
    # frontend_episodes -> docs/data/episodes.json
    with open(os.path.join(DATA_DEST, "episodes.json"), 'w', encoding='utf-8') as f:
        json.dump(frontend_episodes, f, ensure_ascii=False, indent=2)
    
    # search_documents -> docs/data/search_index.json
    # This might be large, but it's loaded asynchronously
    with open(os.path.join(DATA_DEST, "search_index.json"), 'w', encoding='utf-8') as f:
        json.dump(search_documents, f, ensure_ascii=False)

    print("Generated JSON data files.")

    # 5. Render HTML Shell
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("index.html")
    
    # We pass nothing or just basic site config to the template
    # The template will fetch the JSONs via JS
    output = template.render() 

    output_path = os.path.join(DOCS_DIR, "index.html")
    with open(output_path, "w", encoding='utf-8') as f:
        f.write(output)
    print(f"Site shell generated at {output_path}")

    # 6. Copy Assets
    if os.path.exists(ASSETS_SRC):
        if os.path.exists(ASSETS_DEST):
            shutil.rmtree(ASSETS_DEST)
        
        # Copy everything including transcriptions
        # Ignore audio if it's there (based on original script)
        shutil.copytree(ASSETS_SRC, ASSETS_DEST, ignore=shutil.ignore_patterns('audio', '.DS_Store'))
        print(f"Assets copied to {ASSETS_DEST}")

if __name__ == "__main__":
    main()