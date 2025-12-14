# Echt Gebeurd Archive

A project to archive, transcribe, and index episodes of the [Echt Gebeurd](https://echtgebeurd.net/) podcast. This tool downloads episodes from the RSS feed, generates Dutch transcriptions using OpenAI's Whisper model, and builds a static searchable website.

## Features

- **RSS Parsing**: Automatically fetches the latest episodes from the podcast feed.
- **Audio Transcription**: Uses OpenAI's `whisper` model (medium) to transcribe Dutch audio to text.
- **Keyword Extraction**: Analyzes transcriptions to extract relevant keywords for better searchability.
- **Static Site Generation**: Builds a fast, lightweight HTML website to browse and read episodes.
- **Asset Management**: Downloads and organizes audio, images, and transcription files.

## Prerequisites

- **Python 3.8+**
- **FFmpeg**: Required by `openai-whisper` for audio processing.
  - *Windows*: `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/).
  - *macOS*: `brew install ffmpeg`
  - *Linux*: `sudo apt install ffmpeg`

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd echtgebeurd-v3
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: You may need to install `torch` separately if your system requires a specific version (e.g., for CUDA support).*

## Usage

The workflow consists of two main steps: fetching data and building the website.

### 1. Fetch Data & Transcribe

Run the fetch script to download episodes, transcribe audio, and generate metadata.

```bash
python scripts/fetch_data.py
```

*Configuration:*
You can modify `scripts/fetch_data.py` to change:
- `EPISODE_LIMIT`: Number of episodes to process (default: 10).
- `TRANSCRIPTION_LIMIT`: Number of episodes to transcribe (default: 10).
- `RSS_URL`: The podcast feed URL.

### 2. Build Website

Generate the static HTML site using the fetched data.

```bash
python scripts/build_site.py
```

The generated site will be available in the `public/` directory.

### 3. Preview

You can serve the `public` directory locally to preview the site:

```bash
python -m http.server -d public
```
Then open `http://localhost:8000` in your browser.

## Project Structure

- `data/`: Contains `episodes.json` (metadata).
- `scripts/`: Python scripts for fetching data and building the site.
- `templates/`: Jinja2 HTML templates.
- `public/`: The generated static website (ready for deployment).
- `assets/`: Raw downloaded assets (audio, images, text).

## License

This project is for personal archiving purposes. Content copyright belongs to the original creators of the Echt Gebeurd podcast.
