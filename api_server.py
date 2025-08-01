import os
import json
import threading
import time
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import requests
import feedparser
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Podcast Admin API", version="1.0.0")

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
GLADIA_API_KEY = os.getenv('GLADIA_API_KEY')
if not GLADIA_API_KEY:
    raise ValueError("GLADIA_API_KEY environment variable is required")
EPISODES_DIR = "episodes"
STATUS_FILE = "status.json"

# Global state for background tasks
background_tasks = {}

def cleanup_old_tasks():
    """Clean up old completed/error tasks to prevent memory leaks"""
    current_time = datetime.now()
    tasks_to_remove = []
    
    for task_id, task_data in background_tasks.items():
        if task_data.get('status') in ['completed', 'error']:
            # Keep tasks for 1 hour, then remove
            created_at = datetime.fromisoformat(task_data.get('created_at', '2000-01-01'))
            if (current_time - created_at).total_seconds() > 3600:  # 1 hour
                tasks_to_remove.append(task_id)
    
    for task_id in tasks_to_remove:
        del background_tasks[task_id]

def load_feeds():
    """Load RSS feeds from feeds.json"""
    try:
        with open('feeds.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_status():
    """Load transcription status from status.json"""
    try:
        with open(STATUS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_status(status):
    """Save transcription status to status.json"""
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)

def sanitize_filename(s):
    """Sanitize filename for folder creation"""
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in s)

def download_audio(audio_url, folder):
    """Download audio file from URL"""
    local_path = os.path.join(folder, "audio.mp3")
    if os.path.exists(local_path):
        return local_path
    
    # Check disk space before downloading (rough estimate: 50MB per episode)
    try:
        import shutil
        total, used, free = shutil.disk_usage(folder)
        if free < 50 * 1024 * 1024:  # Less than 50MB free
            raise RuntimeError(f"Insufficient disk space. Only {free // (1024*1024)}MB available")
    except Exception as e:
        print(f"Warning: Could not check disk space: {e}")
    
    r = requests.get(audio_url, stream=True)
    r.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return local_path

def transcribe_with_gladia(audio_path, task_id):
    """Transcribe audio using Gladia API"""
    try:
        # Upload file (using Gladia's recommended method)
        file_name, file_extension = os.path.splitext(audio_path)
        with open(audio_path, "rb") as f:
            file_content = f.read()
        
        files = [("audio", (audio_path, file_content, "audio/" + file_extension[1:]))]
        
        res = requests.post(
            "https://api.gladia.io/v2/upload/",
            headers={"x-gladia-key": GLADIA_API_KEY},
            files=files
        )
        res.raise_for_status()
        audio_url = res.json()["audio_url"]
        
        # Start transcription
        headers = {"x-gladia-key": GLADIA_API_KEY, "Content-Type": "application/json"}
        res = requests.post(
            "https://api.gladia.io/v2/pre-recorded/",
            headers=headers,
            json={
                "audio_url": audio_url,
                "language": "en",
                "diarization": True,
                "subtitles": False
            }
        )
        res.raise_for_status()
        result_url = res.json().get("result_url")
        
        if not result_url:
            raise RuntimeError("No result_url in response")
        
        # Poll for result using result_url
        while True:
            res = requests.get(result_url, headers={"x-gladia-key": GLADIA_API_KEY})
            res.raise_for_status()
            data = res.json()
            status = data["status"]
            
            background_tasks[task_id]['message'] = f"Transcription status: {status}"
            
            if status == "done":
                if data["result"] and "transcription" in data["result"]:
                    transcription_data = data["result"]["transcription"]
                    if isinstance(transcription_data, dict):
                        if "utterances" in transcription_data:
                            # Raw diarization output (no post-processing)
                            lines = []
                            for utterance in transcription_data["utterances"]:
                                speaker = utterance.get("speaker", "Unknown")
                                text = utterance.get("text", "")
                                start_time = utterance.get("start", 0)
                                
                                if text.strip():
                                    # Convert seconds to MM:SS.mmm format
                                    minutes = int(start_time // 60)
                                    seconds = int(start_time % 60)
                                    milliseconds = int((start_time % 1) * 1000)
                                    timestamp = f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
                                    
                                    lines.append(f"Speaker {speaker} | {timestamp}\n{text}\n\n")
                            
                            return "".join(lines).strip()
                        elif "full_transcript" in transcription_data:
                            # Use full transcript for complete sentences (no diarization)
                            return transcription_data["full_transcript"]
                        elif "segments" in transcription_data:
                            # Fallback for segments format (optimized)
                            lines = []
                            for segment in transcription_data["segments"]:
                                speaker = segment.get("speaker", "Unknown")
                                text = segment.get("text", "")
                                if text.strip():
                                    lines.append(f"[{speaker}]: {text}\n")
                            return "".join(lines).strip()
                        elif "full_transcript" in transcription_data:
                            return transcription_data["full_transcript"]
                    else:
                        return transcription_data
                elif data["result"] and "utterances" in data["result"]:
                    # Process utterances at root level with timestamps (optimized)
                    lines = []
                    for utterance in data["result"]["utterances"]:
                        speaker = utterance.get("speaker", "Unknown")
                        text = utterance.get("text", "")
                        start_time = utterance.get("start", 0)
                        
                        if text.strip():
                            # Convert seconds to MM:SS.mmm format
                            minutes = int(start_time // 60)
                            seconds = int(start_time % 60)
                            milliseconds = int((start_time % 1) * 1000)
                            timestamp = f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
                            
                            lines.append(f"Speaker {speaker} | {timestamp}\n{text}\n\n")
                    return "".join(lines).strip()
                elif data["result"] and "segments" in data["result"]:
                    # Process segments at root level (optimized)
                    lines = []
                    for segment in data["result"]["segments"]:
                        speaker = segment.get("speaker", "Unknown")
                        text = segment.get("text", "")
                        if text.strip():
                            lines.append(f"[{speaker}]: {text}\n")
                    return "".join(lines).strip()
                else:
                    raise RuntimeError("No transcription data found in result.")
            elif status == "error":
                error_msg = data.get("error_code", "Unknown error")
                raise RuntimeError(f"Transcription failed: {error_msg}")
            
            time.sleep(10)
            
    except Exception as e:
        raise RuntimeError(f"Transcription error: {str(e)}")

def save_transcript(folder, transcript_text):
    """Save transcript to file"""
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, "transcript.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(transcript_text)
    return file_path

def transcribe_episode(episode_data, task_id):
    """Transcribe a single episode"""
    try:
        background_tasks[task_id]['status'] = 'running'
        background_tasks[task_id]['message'] = 'Starting transcription...'
        
        podcast_name = episode_data.get('podcast_name', 'podcast')
        episode_title = episode_data.get('title', 'episode')
        audio_url = episode_data.get('audio_url', '')
        episode_id = episode_data.get('id', '')
        
        if not audio_url:
            raise ValueError("No audio URL provided")
        
        folder_name = sanitize_filename(f"{podcast_name}_{episode_title}")
        folder_path = os.path.join(EPISODES_DIR, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        
        background_tasks[task_id]['message'] = 'Downloading audio...'
        audio_path = download_audio(audio_url, folder_path)
        
        background_tasks[task_id]['message'] = 'Transcribing audio...'
        transcript = transcribe_with_gladia(audio_path, task_id)
        
        transcript_path = save_transcript(folder_path, transcript)
        
        # Update status
        status = load_status()
        status[episode_id] = {
            "status": "completed",
            "transcript_path": transcript_path,
            "completed_at": datetime.now().isoformat(),
            "podcast_name": podcast_name,
            "episode_title": episode_title
        }
        save_status(status)
        
        background_tasks[task_id]['status'] = 'completed'
        background_tasks[task_id]['message'] = f'Transcription complete: {transcript_path}'
        
        return transcript_path
        
    except Exception as e:
        background_tasks[task_id]['status'] = 'error'
        background_tasks[task_id]['message'] = f'Error: {str(e)}'
        
        # Update status with error
        status = load_status()
        status[episode_id] = {
            "status": "error",
            "error": str(e),
            "failed_at": datetime.now().isoformat(),
            "podcast_name": podcast_name,
            "episode_title": episode_title
        }
        save_status(status)
        
        return None

# API Routes
@app.get("/")
def read_root():
    """Serve the dashboard HTML"""
    from fastapi.responses import FileResponse
    return FileResponse('static/index.html')

@app.get("/api")
def api_info():
    """API information endpoint"""
    return {"message": "Podcast Admin API", "version": "1.0.0"}

@app.get("/episodes")
def get_episodes(limit: int = 100, days: int = 90):
    """Get episodes from RSS feeds with status and filtering options
    
    Args:
        limit: Maximum number of episodes to return (default: 100)
        days: Only include episodes from last N days (default: 90)
    """
    # Clean up old tasks periodically
    cleanup_old_tasks()
    
    feeds = load_feeds()
    status = load_status()
    all_episodes = []
    
    # Calculate cutoff date
    from datetime import timezone, timedelta
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    for feed in feeds:
        try:
            feed_data = feedparser.parse(feed['rss'])
            
            # Validate RSS feed
            if feed_data.bozo:
                print(f"Warning: RSS feed {feed['name']} has parsing errors: {feed_data.bozo_exception}")
            
            if not feed_data.entries:
                print(f"Warning: RSS feed {feed['name']} has no entries")
                continue
                
            podcast_name = feed['name']
            
            # Sort entries by date (newest first) to optimize early break
            sorted_entries = sorted(
                feed_data.entries, 
                key=lambda x: x.get('published_parsed', (0,0,0,0,0,0,0,0,0)), 
                reverse=True
            )
            
            for entry in sorted_entries:
                # Get audio URL
                audio_url = None
                if entry.enclosures:
                    for enclosure in entry.enclosures:
                        if enclosure.type.startswith('audio/'):
                            audio_url = enclosure.href
                            break
                
                if not audio_url:
                    continue
                
                # Create unique episode ID using RSS feed URL + episode title (more stable)
                base_id = entry.get('id', '')
                title = entry.title if hasattr(entry, 'title') else "Unknown Title"
                
                # Use RSS ID if available, otherwise hash the title
                if base_id:
                    episode_base = base_id
                else:
                    # Hash title to create stable ID (same title = same hash)
                    episode_base = hashlib.md5(title.encode()).hexdigest()[:12]
                
                # Use a hash of the RSS URL to keep IDs shorter
                feed_hash = hashlib.md5(feed['rss'].encode()).hexdigest()[:8]
                episode_id = f"{feed_hash}_{episode_base}"
                
                # Get episode details
                title = entry.title if hasattr(entry, 'title') else "Unknown Title"
                pub_date = entry.published if hasattr(entry, 'published') else ""
                
                # Parse publication date for filtering
                pub_date_parsed = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date_parsed = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                
                # Skip episodes older than cutoff date
                if pub_date_parsed and pub_date_parsed < cutoff_date:
                    break  # Exit early - we're past our date range
                
                episode_data = {
                    "id": episode_id,
                    "podcast_name": podcast_name,
                    "title": title,
                    "pub_date": pub_date,
                    "pub_date_parsed": pub_date_parsed.isoformat() if pub_date_parsed else None,
                    "audio_url": audio_url,
                    "status": status.get(episode_id, {}).get("status", "pending")
                }
                
                all_episodes.append(episode_data)
                
        except Exception as e:
            print(f"Error processing feed {feed['name']}: {e}")
    
    # Sort by publication date (newest first)
    all_episodes.sort(key=lambda x: x.get('pub_date_parsed', ''), reverse=True)
    
    # Apply limit
    all_episodes = all_episodes[:limit]
    
    return all_episodes

@app.post("/transcribe/{episode_id}")
def start_transcription(episode_id: str):
    """Start transcription for a specific episode"""
    # Find the episode
    feeds = load_feeds()
    target_episode = None
    
    for feed in feeds:
        try:
            feed_data = feedparser.parse(feed['rss'])
            
            # Validate RSS feed
            if feed_data.bozo:
                print(f"Warning: RSS feed {feed['name']} has parsing errors: {feed_data.bozo_exception}")
            
            if not feed_data.entries:
                print(f"Warning: RSS feed {feed['name']} has no entries")
                continue
                
            podcast_name = feed['name']
            
            for entry in feed_data.entries:
                # Get audio URL
                audio_url = None
                if entry.enclosures:
                    for enclosure in entry.enclosures:
                        if enclosure.type.startswith('audio/'):
                            audio_url = enclosure.href
                            break
                
                if not audio_url:
                    continue
                
                # Create unique episode ID using RSS feed URL + episode title (more stable)
                base_id = entry.get('id', '')
                title = entry.title if hasattr(entry, 'title') else "Unknown Title"
                
                # Use RSS ID if available, otherwise hash the title
                if base_id:
                    episode_base = base_id
                else:
                    # Hash title to create stable ID (same title = same hash)
                    episode_base = hashlib.md5(title.encode()).hexdigest()[:12]
                
                # Use a hash of the RSS URL to keep IDs shorter
                feed_hash = hashlib.md5(feed['rss'].encode()).hexdigest()[:8]
                current_episode_id = f"{feed_hash}_{episode_base}"
                
                if current_episode_id == episode_id:
                    target_episode = {
                        "id": episode_id,
                        "podcast_name": podcast_name,
                        "title": entry.title if hasattr(entry, 'title') else "Unknown Title",
                        "audio_url": audio_url
                    }
                    break
            
            if target_episode:
                break
                
        except Exception as e:
            print(f"Error processing feed {feed['name']}: {e}")
    
    if not target_episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    
    # Check if already completed
    status = load_status()
    if episode_id in status and status[episode_id].get("status") == "completed":
        raise HTTPException(status_code=400, detail="Episode already transcribed")
    
    # Start transcription in background
    task_id = f"transcribe_{episode_id}_{int(time.time())}"
    background_tasks[task_id] = {
        'type': 'transcribe',
        'status': 'pending',
        'message': 'Starting...',
        'episode_title': target_episode['title'],
        'created_at': datetime.now().isoformat()
    }
    
    def run_transcribe():
        transcribe_episode(target_episode, task_id)
    
    thread = threading.Thread(target=run_transcribe)
    thread.start()
    
    return {"task_id": task_id, "message": "Transcription task started"}

@app.get("/task-status/{task_id}")
def get_task_status(task_id: str):
    """Get status of a background task"""
    if task_id not in background_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return background_tasks[task_id]

@app.get("/transcript/{episode_id}")
def get_transcript(episode_id: str):
    """Get transcript for a specific episode"""
    status = load_status()
    if episode_id not in status:
        raise HTTPException(status_code=404, detail="Episode not found")
    
    episode_status = status[episode_id]
    if episode_status.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Episode not yet transcribed")
    
    transcript_path = episode_status.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        raise HTTPException(status_code=404, detail="Transcript file not found")
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript = f.read()
        return {
            "episode": episode_status,
            "transcript": transcript
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading transcript: {str(e)}")

@app.get("/status")
def get_all_status():
    """Get all transcription status"""
    return load_status()

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 