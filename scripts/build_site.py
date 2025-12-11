import json
import os
import shutil
from jinja2 import Environment, FileSystemLoader

DATA_DIR = "data"
EPISODES_FILE = os.path.join(DATA_DIR, "episodes.json")
TEMPLATE_DIR = "templates"
PUBLIC_DIR = "public"
ASSETS_SRC = "assets"
ASSETS_DEST = os.path.join(PUBLIC_DIR, "assets")

def main():
    # Load Data
    if not os.path.exists(EPISODES_FILE):
        print("No data found. Run fetch_data.py first.")
        return

    with open(EPISODES_FILE, 'r') as f:
        episodes = json.load(f)

    # Load transcriptions if they are in external files
    for episode in episodes:
        if 'transcription_file' in episode and episode['transcription_file']:
            try:
                with open(episode['transcription_file'], 'r') as tf:
                    episode['transcription'] = tf.read()
            except FileNotFoundError:
                print(f"Warning: Transcription file not found: {episode['transcription_file']}")
                episode['transcription'] = ""

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("index.html")

    # Render
    output = template.render(episodes=episodes)

    # Ensure public dir
    os.makedirs(PUBLIC_DIR, exist_ok=True)

    # Write HTML
    output_path = os.path.join(PUBLIC_DIR, "index.html")
    with open(output_path, "w") as f:
        f.write(output)
    print(f"Site generated at {output_path}")

    # Copy Assets
    if os.path.exists(ASSETS_SRC):
        if os.path.exists(ASSETS_DEST):
            shutil.rmtree(ASSETS_DEST)
        shutil.copytree(ASSETS_SRC, ASSETS_DEST)
        print(f"Assets copied to {ASSETS_DEST}")

if __name__ == "__main__":
    main()
