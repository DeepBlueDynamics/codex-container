#!/usr/bin/env python3
"""
Persistent HTTP transcription service.
Keeps Whisper model loaded, accepts file uploads, processes queue.
"""

import asyncio
import sys
from aiohttp import web
from pathlib import Path
import whisper
import uuid
from datetime import datetime, timezone

# Service configuration
SERVICE_PORT = 8765
WHISPER_MODEL = "large-v3"

# Storage paths
STORAGE_DIR = Path("/service-storage")
PENDING_DIR = STORAGE_DIR / "pending"
TRANSCRIPTS_DIR = STORAGE_DIR / "transcripts"

# Initialize storage
PENDING_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job queue
JOBS = {}

# Model loading
MODEL = None


def utc_now():
    """Get current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


async def load_model():
    """Load Whisper model on startup."""
    global MODEL
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🔄 Loading Whisper model: {WHISPER_MODEL} on {device.upper()}", file=sys.stderr, flush=True)
    MODEL = whisper.load_model(WHISPER_MODEL, device=device)
    print(f"✅ Model {WHISPER_MODEL} loaded on {device.upper()} and ready", file=sys.stderr, flush=True)


async def handle_transcribe(request):
    """POST /transcribe - Accept WAV upload and queue transcription."""
    try:
        reader = await request.multipart()

        job_id = None
        wav_data = None
        model_name = WHISPER_MODEL
        callback_url = None

        async for field in reader:
            if field.name == "file":
                wav_data = await field.read()
            elif field.name == "job_id":
                job_id = (await field.read()).decode()
            elif field.name == "model":
                model_name = (await field.read()).decode()
            elif field.name == "callback_url":
                callback_url = (await field.read()).decode()

        if not wav_data:
            return web.json_response({"error": "No file uploaded"}, status=400)

        if not job_id:
            job_id = str(uuid.uuid4())

        # Save WAV to pending
        wav_file = PENDING_DIR / f"{job_id}.wav"
        wav_file.write_bytes(wav_data)

        print(f"📥 Job {job_id} received: {len(wav_data)} bytes", file=sys.stderr, flush=True)

        # Queue job
        JOBS[job_id] = {
            "status": "queued",
            "model": model_name,
            "wav_file": str(wav_file),
            "callback_url": callback_url,
            "created": utc_now(),
            "file_size": len(wav_data)
        }

        return web.json_response({
            "success": True,
            "job_id": job_id,
            "status": "queued",
            "message": f"Job {job_id} queued for transcription"
        })

    except Exception as e:
        print(f"❌ Upload error: {e}", file=sys.stderr, flush=True)
        return web.json_response({"error": str(e)}, status=500)


async def handle_status(request):
    """GET /status/{job_id} - Check transcription status."""
    job_id = request.match_info["job_id"]

    if job_id not in JOBS:
        return web.json_response({"error": "Job not found"}, status=404)

    job = JOBS[job_id]
    response = {
        "success": True,
        "job_id": job_id,
        "status": job["status"],
        "created": job["created"]
    }

    if "progress" in job:
        response["progress"] = job["progress"]
    if "completed" in job:
        response["completed"] = job["completed"]
    if "error" in job:
        response["error"] = job["error"]
    if job["status"] == "completed" and "transcript" in job:
        response["transcript_preview"] = job["transcript"][:200] + "..." if len(job["transcript"]) > 200 else job["transcript"]

    return web.json_response(response)


async def handle_download(request):
    """GET /download/{job_id} - Download completed transcript."""
    job_id = request.match_info["job_id"]

    if job_id not in JOBS:
        return web.json_response({"error": "Job not found"}, status=404)

    job = JOBS[job_id]

    if job["status"] != "completed":
        return web.json_response({
            "error": "Transcription not ready",
            "status": job["status"]
        }, status=404)

    transcript_file = TRANSCRIPTS_DIR / f"{job_id}.txt"
    if not transcript_file.exists():
        return web.json_response({"error": "Transcript file missing"}, status=500)

    print(f"📤 Job {job_id} downloaded", file=sys.stderr, flush=True)

    return web.Response(
        text=transcript_file.read_text(),
        content_type="text/plain"
    )


async def handle_health(request):
    """GET /health - Service health check."""
    queued_count = len([j for j in JOBS.values() if j["status"] == "queued"])
    processing_count = len([j for j in JOBS.values() if j["status"] == "processing"])
    completed_count = len([j for j in JOBS.values() if j["status"] == "completed"])
    failed_count = len([j for j in JOBS.values() if j["status"] == "failed"])

    return web.json_response({
        "status": "ok",
        "model_loaded": MODEL is not None,
        "model_name": WHISPER_MODEL,
        "queue": {
            "queued": queued_count,
            "processing": processing_count,
            "completed": completed_count,
            "failed": failed_count,
            "total": len(JOBS)
        },
        "uptime": "running"
    })


async def process_queue():
    """Background task to process queued transcription jobs."""
    print("🔄 Queue processor started", file=sys.stderr, flush=True)

    while True:
        try:
            # Find next queued job
            queued = [jid for jid, job in JOBS.items() if job["status"] == "queued"]

            if queued:
                job_id = queued[0]
                job = JOBS[job_id]

                print(f"⚙️  Processing job {job_id}", file=sys.stderr, flush=True)

                # Update status
                job["status"] = "processing"
                job["progress"] = "Loading audio file..."

                # Run Whisper transcription
                job["progress"] = "Transcribing audio..."
                result = MODEL.transcribe(job["wav_file"])
                transcript_text = result["text"]

                # Save transcript
                transcript_file = TRANSCRIPTS_DIR / f"{job_id}.txt"
                transcript_file.write_text(transcript_text)

                # Update job
                job["status"] = "completed"
                job["transcript_file"] = str(transcript_file)
                job["transcript"] = transcript_text
                job["completed"] = utc_now()

                print(f"✅ Job {job_id} completed: {len(transcript_text)} chars", file=sys.stderr, flush=True)

                # Clean up WAV file
                wav_path = Path(job["wav_file"])
                if wav_path.exists():
                    wav_path.unlink()

            else:
                # No jobs queued - idle
                await asyncio.sleep(2)

        except Exception as e:
            print(f"❌ Queue processor error for job {job_id}: {e}", file=sys.stderr, flush=True)
            if job_id in JOBS:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = str(e)
                JOBS[job_id]["failed"] = utc_now()

        await asyncio.sleep(0.5)  # Small delay between checks


async def start_background_tasks(app):
    """Start background tasks on app startup."""
    await load_model()
    app["queue_processor"] = asyncio.create_task(process_queue())


async def cleanup_background_tasks(app):
    """Cleanup background tasks on shutdown."""
    app["queue_processor"].cancel()
    await app["queue_processor"]


def main():
    """Start the transcription service."""
    print("=" * 60, file=sys.stderr, flush=True)
    print("TRANSCRIPTION SERVICE STARTING", file=sys.stderr, flush=True)
    print(f"Port: {SERVICE_PORT}", file=sys.stderr, flush=True)
    print(f"Model: {WHISPER_MODEL}", file=sys.stderr, flush=True)
    print(f"Storage: {STORAGE_DIR}", file=sys.stderr, flush=True)
    print("=" * 60, file=sys.stderr, flush=True)

    # Create app
    app = web.Application()
    app.router.add_post("/transcribe", handle_transcribe)
    app.router.add_get("/status/{job_id}", handle_status)
    app.router.add_get("/download/{job_id}", handle_download)
    app.router.add_get("/health", handle_health)

    # Register startup/cleanup handlers
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    # Run server
    web.run_app(app, host="0.0.0.0", port=SERVICE_PORT)


if __name__ == "__main__":
    main()
