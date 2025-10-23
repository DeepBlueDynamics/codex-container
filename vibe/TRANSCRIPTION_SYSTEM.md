# Transcription System Architecture

## Overview
This document explains the persistent background transcription system for processing WAV files in the codex-container.

## Problem
Codex has a 1-minute execution timeout. Whisper transcriptions take 5-10 minutes (including model loading). Background async tasks die when the MCP server process exits after Codex finishes.

## Solution
A persistent daemon process that runs in the background and processes transcription jobs from a queue file.

## Components

### 1. Transcription Daemon (`scripts/transcription_daemon.py`)
- **Purpose**: Persistent background process that processes transcription jobs
- **Location**: Copied to `/usr/local/bin/transcription_daemon.py` in container
- **Startup**: Launched by `codex_entry.sh` on container start
- **Queue**: Reads from `/opt/codex-home/transcription_queue.json`
- **Process**: 
  1. Polls queue every 2 seconds
  2. Picks up jobs one at a time
  3. Updates status files through each stage
  4. Renames files on completion/failure

### 2. MCP Tool (`MCP/transcribe-wav.py`)
- **Function**: `transcribe_wav()` - Queues jobs for background processing
- **Returns**: Immediately (under 1 second)
- **Creates**: Initial `.transcribing.txt` status file
- **Queue Format**:
```json
[
  {
    "job_id": "unique-id",
    "source_file": "/workspace/recordings/audio.wav",
    "transcript_file": "/workspace/recordings/audio.transcribing.txt",
    "model": "large-v3",
    "beam_size": 5,
    "started": "2025-10-19T18:30:52.087149+00:00"
  }
]
```

### 3. Status Files
Files progress through naming stages to indicate status:

- **Queued**: `audio.transcribing.txt` - Initial "TRANSCRIBING" placeholder
- **Loading**: `audio.transcribing.txt` - "LOADING MODEL" with timing info
- **Processing**: `audio.transcribing.txt` - "TRANSCRIBING AUDIO" with progress
- **Complete**: `audio.txt` - Final transcript with telegraph format
- **Failed**: `audio.failed.txt` - Error details and traceback

### 4. Status File Format
Each stage updates with detailed information:

**LOADING MODEL Stage:**
```
========== TRANSMISSION STATUS REPORT ==========
STATUS: LOADING MODEL
FILE: /workspace/recordings/audio.wav
MODEL: large-v3
BEAM WIDTH: 5
STARTED: 2025-10-19 18:30:52 UTC
------------------------------------------------------------
LOADING STARTED: 2025-10-19 18:30:53 UTC

Initializing Whisper large-v3 model from /opt/whisper-cache
MAXIMUM EXPECTED TIME: 10 minutes from start
If status unchanged after 10 minutes: job has likely failed
DO NOT RETRY - Report error to supervisor and enjoy your island vacation

Stand by for model initialization STOP
```

**TRANSCRIBING AUDIO Stage:**
```
========== TRANSMISSION STATUS REPORT ==========
STATUS: TRANSCRIBING AUDIO
FILE: /workspace/recordings/audio.wav
MODEL: large-v3
BEAM WIDTH: 5
STARTED: 2025-10-19 18:30:52 UTC
------------------------------------------------------------
PROCESSING STARTED: 2025-10-19 18:32:15 UTC
MODEL LOAD TIME: 82.3s
ELAPSED SINCE JOB START: 82.3s

Model initialized successfully STOP
Audio transcription in progress

FAILURE THRESHOLD: 2025-10-19 18:40:52 UTC
TIME UNTIL ASSUMED FAILURE: 517s (8.6 minutes)
If status unchanged past threshold: DO NOT return to water cooler
Report failure to supervisor immediately

Await final transmission STOP
```

## Integration with Monitor

### Path Mapping Fix (`scripts/codex_container.ps1`)
When monitoring subdirectories (e.g., `./recordings`):
- Files are in: `C:\Users\...\vhf_monitor\recordings\audio.wav`
- Container path must be: `/workspace/recordings/audio.wav`
- Script calculates relative path from workspace root (not watch dir)
- Auto-injects `output_dir="/workspace"` so transcripts appear in parent directory

### Monitor Template Variables
MONITOR.md uses these variables:
- `{{container_path}}`: Correct full path for tool calls (e.g., `/workspace/recordings/audio.wav`)
- `{{relative_path}}`: Path relative to watch directory (e.g., `audio.wav`)
- `{{watch_root}}`: The directory being monitored

## File Naming Strategy
All transcripts are named after the source WAV file:
- Source: `recordings/my_recording_20251019.wav`
- During: `my_recording_20251019.transcribing.txt`
- Success: `my_recording_20251019.txt`
- Failure: `my_recording_20251019.failed.txt`

This allows:
1. Easy matching of transcripts to source files
2. Monitoring `.transcribing.txt` to watch progress
3. Monitoring `.txt` to process completed transcripts
4. Handling `.failed.txt` for error recovery

## Workflow

### For Codex (AI Agent):
1. Detect new WAV file in monitored directory
2. Call `transcribe_wav(filename="/workspace/recordings/audio.wav")`
3. Tool returns immediately with job queued
4. Use `wait_at_water_cooler(60)` to give daemon time to work
5. Check status file or call `transcription_status(job_id="...")`
6. When complete, process the final `.txt` transcript

### For Daemon (Background Process):
1. Poll queue file every 2 seconds
2. Pick up next job from queue
3. Update status: "LOADING MODEL"
4. Load Whisper model (cached after first use)
5. Update status: "TRANSCRIBING AUDIO" with timing
6. Process audio through Whisper
7. Write final transcript in telegraph format
8. Rename `.transcribing.txt` → `.txt`
9. Move to next job in queue

## Timing Expectations
- **Model Load** (first time): 2-5 minutes (downloads ~3GB)
- **Model Load** (cached): 5-15 seconds
- **Transcription**: 1-3 minutes per minute of audio
- **Total**: 5-10 minutes typical, 10 minutes maximum before timeout

## Debugging

### Check if daemon is running:
```bash
docker exec codex-container ps aux | grep transcription
```

### Check if script exists:
```bash
docker exec codex-container ls -la /usr/local/bin/transcription_daemon.py
```

### View queue:
```bash
docker exec codex-container cat /opt/codex-home/transcription_queue.json
```

### View daemon logs:
```bash
docker logs codex-container 2>&1 | grep -i transcription
```

### Check status file:
```bash
docker exec codex-container cat /workspace/recordings/audio.transcribing.txt
```

## Installation
After making changes to daemon or MCP tool:
1. Rebuild container: `.\scripts\codex_container.ps1 -Install`
2. Daemon auto-starts via `codex_entry.sh`
3. Queue and status files persist in `/opt/codex-home` (mapped to `~/.codex-service`)

## Model Caching
- Models cached in: `/opt/whisper-cache` (in container)
- Persists across container restarts via Docker volume
- First download is slow, subsequent loads are fast
- `large-v3`: ~3GB, best quality
- `medium`: ~1.5GB, faster but less accurate

## Future Improvements
- [ ] Add daemon health check endpoint
- [ ] Support for batch processing multiple files
- [ ] Progress percentage during transcription
- [ ] Configurable timeout thresholds
- [ ] Queue priority system
- [ ] Daemon restart on crash
