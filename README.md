# Podcast Newsletter Bot

A simple dashboard to transcribe podcast episodes using RSS feeds and the Gladia API.

## What it does

- Fetches episodes from multiple podcast RSS feeds
- Downloads audio files locally
- Transcribes episodes using Gladia's speech-to-text API
- Provides a web dashboard to manage transcriptions
- Tracks transcription status to avoid duplicates

## Quick Start

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up your API key**
   ```bash
   cp env.example .env
   # Edit .env with your Gladia API key from https://app.gladia.io/
   ```

3. **Start the server**
   ```bash
   python start_server.py
   ```

4. **Open dashboard**
   Visit [http://localhost:8000](http://localhost:8000)

## How it works

### Dashboard
- Lists episodes from your configured RSS feeds
- Shows transcription status (pending/completed/error)
- Click "Transcribe" to start transcription
- View completed transcripts in the browser

### Transcription Process
1. Downloads MP3 file to `episodes/[Episode_Name]/audio.mp3`
2. Sends audio to Gladia API for transcription
3. Saves transcript to `episodes/[Episode_Name]/transcript.txt`
4. Updates status in `status.json`

### File Structure
```
├── api_server.py          # FastAPI backend
├── feeds.json             # RSS feed configuration
├── static/                # Dashboard frontend
├── episodes/              # Downloaded episodes (auto-created)
└── status.json            # Transcription tracking (auto-created)
```

## Configuration

### RSS Feeds (`feeds.json`)
```json
[
  {
    "name": "Podcast Name",
    "rss": "https://feeds.example.com/feed.xml"
  }
]
```

### Environment Variables (`.env`)
```bash
GLADIA_API_KEY=your-gladia-api-key-here
```

## Features

- **Multi-podcast support** - Configure multiple RSS feeds
- **Status tracking** - Prevents duplicate transcriptions
- **Real-time updates** - See transcription progress
- **Speaker diarization** - Identifies different speakers
- **Date filtering** - Filter episodes by recency

## Requirements

- Python 3.7+
- Gladia API key
- Internet connection for RSS feeds and API calls

## Notes

- Audio files and transcripts are stored locally
- Server needs to stay running for transcriptions to complete
- Uses Gladia's diarization for speaker identification
- Transcripts include timestamps and speaker labels 