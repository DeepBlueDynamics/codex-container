# Persistent Transcription Service - Architecture Plan

## Problem Statement

Current issue: Whisper model loads on every WAV file trigger because the transcription daemon runs inside ephemeral Codex containers that die after each run.

**Constraints:**
- Transcription daemon cannot monitor directories (queue-based only)
- Cannot share `/workspace` volumes between containers
- Need persistent daemon to keep Whisper model loaded in memory
- Files must be uploaded to daemon via HTTP endpoint

---

## Proposed Architecture

### Component 1: Persistent Transcription Service Container

**Purpose:** Long-running container that keeps Whisper model loaded and processes transcription jobs.

**Implementation:**
```
Name: codex-transcription-service
Base: Same as codex-container (Python, Whisper, dependencies)
Entry: transcription_service_daemon.py (new file)
Ports: 8765 (HTTP API for job submission)
Storage: /service-storage (container-local, not shared)
```

**API Endpoints:**

1. **POST /transcribe**
   - Accept: `multipart/form-data` (WAV file upload)
   - Parameters:
     - `file`: WAV file binary
     - `job_id`: Unique identifier
     - `callback_url`: Optional webhook for completion notification
     - `model`: Whisper model name (default: large-v3)
   - Returns: `{"job_id": "...", "status": "queued"}`

2. **GET /status/{job_id}**
   - Returns: `{"job_id": "...", "status": "queued|processing|completed|failed", "progress": "...", "transcript": "...", "error": "..."}`

3. **GET /download/{job_id}**
   - Returns: Completed transcript as text/plain
   - Or 404 if not ready

4. **GET /health**
   - Returns: `{"status": "ok", "model_loaded": true, "queue_size": 3}`

**File Flow:**
```
1. MCP tool uploads WAV → Service stores in /service-storage/pending/{job_id}.wav
2. Daemon processes → Creates /service-storage/transcripts/{job_id}.txt
3. MCP tool polls /status/{job_id} or gets webhook callback
4. MCP tool downloads transcript via /download/{job_id}
5. MCP tool saves to /workspace/transcriptions/ (local Codex container)
```

---

### Component 2: Updated MCP Tool (transcribe-wav.py)

**New Behavior:**

```python
async def transcribe_wav(
    filename: str,
    output_dir: str = "/workspace/transcriptions",
    model: str = "large-v3",
    transcription_service_url: str = "http://host.docker.internal:8765"
) -> Dict[str, object]:
    """
    Upload WAV file to persistent transcription service.
    Poll for completion, download transcript when ready.
    """

    # 1. Read WAV file from /workspace
    with open(filename, "rb") as f:
        wav_data = f.read()

    # 2. Upload to service
    job_id = generate_job_id()
    response = requests.post(
        f"{transcription_service_url}/transcribe",
        files={"file": wav_data},
        data={"job_id": job_id, "model": model}
    )

    # 3. Create .transcribing.txt status file locally
    status_file = Path(output_dir) / f"{Path(filename).stem}.transcribing.txt"
    write_status(status_file, "QUEUED - Uploaded to transcription service")

    # 4. Return immediately (don't block)
    return {
        "success": True,
        "status": "queued",
        "job_id": job_id,
        "service_url": transcription_service_url,
        "message": "WAV uploaded to transcription service. Use check_transcription_status() to poll."
    }
```

**New MCP Tool: check_transcription_status()**

```python
async def check_transcription_status(
    job_id: str,
    output_dir: str = "/workspace/transcriptions",
    transcription_service_url: str = "http://host.docker.internal:8765"
) -> Dict[str, object]:
    """
    Check status of transcription job and download if complete.
    """

    # 1. Query service status
    response = requests.get(f"{transcription_service_url}/status/{job_id}")
    status_data = response.json()

    # 2. If completed, download transcript
    if status_data["status"] == "completed":
        transcript_response = requests.get(f"{transcription_service_url}/download/{job_id}")
        transcript_text = transcript_response.text

        # Save to local filesystem
        output_file = Path(output_dir) / f"{job_id}.txt"
        output_file.write_text(transcript_text)

        # Remove .transcribing.txt status file
        status_file = Path(output_dir) / f"{job_id}.transcribing.txt"
        if status_file.exists():
            status_file.unlink()

        return {
            "success": True,
            "status": "completed",
            "transcript_file": str(output_file),
            "transcript": transcript_text
        }

    # 3. Still processing
    return {
        "success": True,
        "status": status_data["status"],
        "progress": status_data.get("progress", ""),
        "message": "Transcription still in progress"
    }
```

---

### Component 3: Service Daemon (transcription_service_daemon.py)

**Implementation:**

```python
#!/usr/bin/env python3
"""
Persistent HTTP transcription service.
Keeps Whisper model loaded, accepts file uploads, processes queue.
"""

import asyncio
from aiohttp import web
from pathlib import Path
import whisper
import json
import uuid
from datetime import datetime

# Load model once at startup
print("Loading Whisper model: large-v3")
MODEL = whisper.load_model("large-v3")
print("Model loaded and ready")

STORAGE_DIR = Path("/service-storage")
PENDING_DIR = STORAGE_DIR / "pending"
TRANSCRIPTS_DIR = STORAGE_DIR / "transcripts"
QUEUE_FILE = STORAGE_DIR / "queue.json"

# Initialize storage
PENDING_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job queue
JOBS = {}

async def handle_transcribe(request):
    """POST /transcribe - Accept WAV upload"""
    reader = await request.multipart()

    job_id = None
    wav_data = None
    model_name = "large-v3"

    async for field in reader:
        if field.name == "file":
            wav_data = await field.read()
        elif field.name == "job_id":
            job_id = (await field.read()).decode()
        elif field.name == "model":
            model_name = (await field.read()).decode()

    if not wav_data:
        return web.json_response({"error": "No file uploaded"}, status=400)

    if not job_id:
        job_id = str(uuid.uuid4())

    # Save WAV to pending
    wav_file = PENDING_DIR / f"{job_id}.wav"
    wav_file.write_bytes(wav_data)

    # Queue job
    JOBS[job_id] = {
        "status": "queued",
        "model": model_name,
        "wav_file": str(wav_file),
        "created": datetime.utcnow().isoformat()
    }

    return web.json_response({
        "job_id": job_id,
        "status": "queued"
    })

async def handle_status(request):
    """GET /status/{job_id}"""
    job_id = request.match_info["job_id"]

    if job_id not in JOBS:
        return web.json_response({"error": "Job not found"}, status=404)

    return web.json_response(JOBS[job_id])

async def handle_download(request):
    """GET /download/{job_id}"""
    job_id = request.match_info["job_id"]

    if job_id not in JOBS:
        return web.json_response({"error": "Job not found"}, status=404)

    if JOBS[job_id]["status"] != "completed":
        return web.json_response({"error": "Transcription not ready"}, status=404)

    transcript_file = TRANSCRIPTS_DIR / f"{job_id}.txt"
    if not transcript_file.exists():
        return web.json_response({"error": "Transcript file missing"}, status=500)

    return web.Response(text=transcript_file.read_text())

async def handle_health(request):
    """GET /health"""
    return web.json_response({
        "status": "ok",
        "model_loaded": MODEL is not None,
        "queue_size": len([j for j in JOBS.values() if j["status"] == "queued"])
    })

async def process_queue():
    """Background task to process queued jobs"""
    while True:
        # Find next queued job
        queued = [jid for jid, job in JOBS.items() if job["status"] == "queued"]

        if queued:
            job_id = queued[0]
            job = JOBS[job_id]

            try:
                # Update status
                job["status"] = "processing"
                job["progress"] = "Transcribing audio..."

                # Run Whisper
                result = MODEL.transcribe(job["wav_file"])
                transcript_text = result["text"]

                # Save transcript
                transcript_file = TRANSCRIPTS_DIR / f"{job_id}.txt"
                transcript_file.write_text(transcript_text)

                # Update job
                job["status"] = "completed"
                job["transcript_file"] = str(transcript_file)
                job["transcript"] = transcript_text
                job["completed"] = datetime.utcnow().isoformat()

            except Exception as e:
                job["status"] = "failed"
                job["error"] = str(e)

        await asyncio.sleep(2)  # Poll every 2 seconds

# Create app
app = web.Application()
app.router.add_post("/transcribe", handle_transcribe)
app.router.add_get("/status/{job_id}", handle_status)
app.router.add_get("/download/{job_id}", handle_download)
app.router.add_get("/health", handle_health)

# Start background queue processor
async def start_background_tasks(app):
    app["queue_processor"] = asyncio.create_task(process_queue())

app.on_startup.append(start_background_tasks)

if __name__ == "__main__":
    print("Starting transcription service on port 8765")
    web.run_app(app, host="0.0.0.0", port=8765)
```

---

### Component 4: Docker Setup

**New script: scripts/start_transcription_service.ps1**

```powershell
# Start persistent transcription service container
docker run -d `
  --name codex-transcription-service `
  --restart unless-stopped `
  -p 8765:8765 `
  codex-container `
  python /opt/scripts/transcription_service_daemon.py
```

**Update codex_container.ps1:**
- Add `-TranscriptionServiceUrl` parameter (default: `http://host.docker.internal:8765`)
- Pass to Codex runs via environment variable
- Check service health before starting monitor

---

### Component 5: Updated Alpha India Workflow (MONITOR.md)

```markdown
**IF this is a NEW .wav file:**
1. Queue transcription using: `transcribe_wav(filename="{{container_path}}")`
   - This uploads the file to the transcription service
   - Returns immediately with job_id
2. Wait at water cooler (30-45 seconds) for transcription to process
3. Check status using: `check_transcription_status(job_id="<from step 1>")`
4. If still processing, wait more and check again
5. **Wait until transcript is complete** - status will be "completed"
6. Read the completed transcript from the returned transcript_file path
7. [rest of workflow unchanged]
```

---

## Implementation Steps

1. ✅ Create `scripts/transcription_service_daemon.py` (HTTP service)
2. ✅ Update `MCP/transcribe-wav.py` to upload files and return job_id
3. ✅ Add new MCP tool `check_transcription_status()` to transcribe-wav.py
4. ✅ Create `scripts/start_transcription_service.ps1`
5. ✅ Update `scripts/codex_container.ps1` to pass service URL
6. ✅ Update `MONITOR.md` with new workflow
7. ✅ Add service health check to monitor startup
8. ✅ Test: Start service → Monitor triggers → Upload works → Download works

---

## Benefits

- ✅ Whisper model loads **once** when service starts
- ✅ Fast job submission (upload only, no blocking)
- ✅ Service can handle multiple jobs concurrently
- ✅ No shared volume needed (HTTP upload/download)
- ✅ Service runs independently, can be restarted without affecting monitor
- ✅ Clean separation of concerns

---

## Testing Plan

```powershell
# 1. Build container
.\scripts\codex_container.ps1 -Install

# 2. Start transcription service
.\scripts\start_transcription_service.ps1

# 3. Check health
curl http://localhost:8765/health

# 4. Start monitor (will use service automatically)
.\scripts\codex_container.ps1 -Monitor C:\path\to\recordings

# 5. Drop a WAV file in recordings
# Watch logs - should see:
#   - Upload to service
#   - Poll for status
#   - Download transcript
#   - Alpha India processes
```

---

## Future Enhancements

- Webhook callbacks instead of polling
- Queue priority (URGENT transmissions first)
- Multiple model support (small/medium/large)
- Transcript caching (avoid re-processing same file)
- Service dashboard (web UI showing queue status)
- Multi-language detection
- Speaker diarization
