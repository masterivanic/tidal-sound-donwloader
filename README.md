# Tidal Downloader Desktop App

A desktop application for searching and downloading Tidal tracks using yt-dlp + ffmpeg.

## Requirements

- Python 3.9+
- ffmpeg installed and on your `$PATH` (or specify the path in settings)

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## First launch

1. Click **Login with Tidal** — your browser will open a Tidal authorization page.
2. Approve the app on Tidal's website.
3. The app will confirm the session and save it for future launches.

## Features

- 🔍 Search tracks by name, artist, or album
- ⬇  Download individual tracks or all results at once
- 🖼  Automatic album art embedding (MP3)
- 📁 Configurable output folder
- 🎵 Format support: MP3, M4A, FLAC, Opus
- 📊 Per-track download status indicators
- 💾 Session persistence (no need to log in every time)

## Notes

- Audio is sourced from YouTube via yt-dlp, matched by track name + artist.
- Tidal API is used only for metadata and search — no direct audio streaming.
- ffmpeg must be installed. On macOS: `brew install ffmpeg`. On Ubuntu: `sudo apt install ffmpeg`.
