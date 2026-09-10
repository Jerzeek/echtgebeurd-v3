# Echt Gebeurd Archive

A project to archive, transcribe, and index episodes of the [Echt Gebeurd](https://echtgebeurd.net/) podcast. This tool downloads episodes from the RSS feed, generates Dutch transcriptions using OpenAI's Whisper model, and builds a static searchable website.

## Features

- **RSS Parsing**: Automatically fetches the latest episodes from the podcast feed.
- **Audio Transcription**: Uses OpenAI's `whisper` model (medium) to transcribe Dutch audio to text.
- **Keyword Extraction**: Analyzes transcriptions to extract relevant keywords for better searchability.
- **Static Site Generation**: Builds a fast, lightweight HTML website to browse and read episodes. The build step splits titles into episode number, theme and storyteller, strips marketing boilerplate from descriptions, and filters weak keywords.
- **Asset Management**: Downloads and organizes audio, images, and transcription files.

## Prerequisites

- **Python 3.8+**
- **FFmpeg**: Required by `openai-whisper` for audio processing.

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd echtgebeurd-v3
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-whisper.txt   # only for local transcription
   ```
   *Note: You may need to install `torch` separately if your system requires a specific version (e.g., for CUDA support). On Apple Silicon, `pip install mlx-whisper` gives much faster local transcription.*

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

The generated site will be available in the `docs/` directory.

### 3. Preview

You can serve the `docs` directory locally to preview the site:

```bash
python -m http.server -d docs
```
Then open `http://localhost:8000` in your browser.

The site reads its state from the URL hash, so episodes and searches are linkable:

- `#afl=542` opens episode 542 (`#ep=<guid>` for episodes without a number)
- `#q=gevangenis` runs a full-text search; matches are highlighted in the transcript
- `#thema=Kerst` and `#jaar=2024` apply the theme and year filters

These combine, e.g. `#afl=100&q=gevangenis`.

## Automatic updates on GitHub

The workflow in `.github/workflows/update.yml` runs every Thursday morning (and on demand via *Actions → Update episodes → Run workflow*). It fetches the RSS feed, transcribes new episodes, rebuilds `docs/`, and pushes the result to `main`. GitHub Pages then publishes it from `main:/docs`.

Transcription engine:

- **OpenAI API** (recommended): add a repository secret named `OPENAI_API_KEY`. A run then takes a few minutes and costs roughly €0.10 per episode. Files over 25 MB are shrunk with ffmpeg first.
- **Local Whisper on the runner** (no key configured): free, but a CPU runner needs roughly 30–60 minutes per episode. On a private repository this counts against the 2,000 free Actions minutes per month.

Each run transcribes at most 3 new episodes (`MAX_NEW_TRANSCRIPTIONS`, adjustable when running manually), so a large backlog is better handled once on your own machine:

```bash
python scripts/fetch_data.py && python scripts/clean_transcriptions.py && python scripts/build_site.py
```

Environment variables understood by `scripts/fetch_data.py`: `TRANSCRIBE_ENGINE` (`auto`, `openai`, `local`), `OPENAI_TRANSCRIBE_MODEL` (default `gpt-4o-transcribe`), `WHISPER_MODEL` (default `medium`), `MAX_NEW_TRANSCRIPTIONS`.

`assets/` is not committed. On the runner the fetch script first copies the transcripts already published in `docs/assets/transcriptions/` back into `assets/transcriptions/`, so only genuinely new episodes get transcribed.

## Project Structure

- `data/`: Contains `episodes.json` (metadata).
- `scripts/`: Python scripts for fetching data and building the site.
- `templates/`: Jinja2 HTML templates.
- `docs/`: The generated static website (ready for deployment).
- `assets/`: Raw downloaded assets (audio, images, text).

## License

This project is for personal archiving purposes. Content copyright belongs to the original creators of the Echt Gebeurd podcast.
