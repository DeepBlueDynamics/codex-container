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
        original_filename = None
        model_name = WHISPER_MODEL
        callback_url = None

        async for field in reader:
            if field.name == "file":
                wav_data = await field.read()
                # Extract original filename from Content-Disposition header
                if hasattr(field, 'filename') and field.filename:
                    original_filename = field.filename
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

        # Save WAV to pending (use job_id to avoid conflicts)
        wav_file = PENDING_DIR / f"{job_id}.wav"
        wav_file.write_bytes(wav_data)

        print(f"📥 Job {job_id} received: {len(wav_data)} bytes (original: {original_filename})", file=sys.stderr, flush=True)

        # Queue job
        JOBS[job_id] = {
            "status": "queued",
            "model": model_name,
            "wav_file": str(wav_file),
            "original_filename": original_filename or f"{job_id}.wav",
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
    try:
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
    except Exception as e:
        print(f"❌ Error in handle_status: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return web.json_response({"error": f"Internal server error: {str(e)}"}, status=500)


async def handle_download(request):
    """GET /download/{job_id} - Download completed transcript."""
    try:
        job_id = request.match_info["job_id"]

        if job_id not in JOBS:
            return web.json_response({"error": "Job not found"}, status=404)

        job = JOBS[job_id]

        if job["status"] != "completed":
            return web.json_response({
                "error": "Transcription not ready",
                "status": job["status"]
            }, status=404)

        # Use the transcript_file path stored in the job
        if "transcript_file" not in job:
            # Fallback to old behavior for backwards compatibility
            transcript_file = TRANSCRIPTS_DIR / f"{job_id}.txt"
        else:
            transcript_file = Path(job["transcript_file"])

        if not transcript_file.exists():
            print(f"❌ Transcript file missing: {transcript_file}", file=sys.stderr, flush=True)
            return web.json_response({"error": f"Transcript file missing: {transcript_file.name}"}, status=500)

        print(f"📤 Job {job_id} downloaded: {transcript_file.name}", file=sys.stderr, flush=True)

        return web.Response(
            text=transcript_file.read_text(),
            content_type="text/plain"
        )
    except Exception as e:
        print(f"❌ Error in handle_download: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return web.json_response({"error": f"Internal server error: {str(e)}"}, status=500)


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
                start_time = datetime.now(timezone.utc)
                result = MODEL.transcribe(job["wav_file"], beam_size=5, verbose=False)
                end_time = datetime.now(timezone.utc)

                # Extract transcript and metadata
                transcript_text = result["text"].strip()
                language = result.get("language", "unknown")

                # Get audio duration from segments if available
                segments = result.get("segments", [])
                audio_duration = segments[-1]["end"] if segments else 0.0

                # Get original WAV filename from job metadata
                wav_filename = job.get("original_filename", Path(job["wav_file"]).name)

                # Format transcript with transmission header
                processing_duration = (end_time - start_time).total_seconds()

                # Create ASCII waveform visualization from audio data
                waveform_viz = ""
                speech_viz = ""
                try:
                    import wave
                    import numpy as np

                    # Read WAV file for waveform
                    with wave.open(job["wav_file"], 'rb') as wav:
                        frames = wav.readframes(wav.getnframes())
                        sample_width = wav.getsampwidth()

                        # Convert to numpy array based on sample width
                        if sample_width == 1:
                            audio_data = np.frombuffer(frames, dtype=np.uint8)
                            audio_data = audio_data.astype(np.float32) - 128
                        elif sample_width == 2:
                            audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                        else:
                            audio_data = np.frombuffer(frames, dtype=np.int32).astype(np.float32)

                        # Downsample to 60 points for visualization
                        viz_width = 60
                        chunk_size = len(audio_data) // viz_width

                        if chunk_size > 0:
                            # Calculate RMS amplitude for each chunk
                            amplitudes = []
                            for i in range(viz_width):
                                start_idx = i * chunk_size
                                end_idx = min(start_idx + chunk_size, len(audio_data))
                                chunk = audio_data[start_idx:end_idx]
                                rms = np.sqrt(np.mean(chunk**2))
                                amplitudes.append(rms)

                            # Normalize to 0-8 range for vertical bars
                            max_amp = max(amplitudes) if amplitudes else 1
                            normalized = [int((amp / max_amp) * 8) if max_amp > 0 else 0 for amp in amplitudes]

                            # Create vertical bar chart using block characters
                            bars = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█', '█']
                            waveform_viz = "".join([bars[n] for n in normalized])
                        else:
                            waveform_viz = "▁" * viz_width

                except Exception as e:
                    print(f"⚠️  Waveform visualization error: {e}", file=sys.stderr, flush=True)
                    waveform_viz = "▁" * 60

                # Create speech activity visualization from segments
                if segments:
                    # Build timeline visualization (60 chars wide)
                    viz_width = 60
                    viz_chars = [" "] * viz_width

                    for seg in segments:
                        # Calculate position in timeline
                        start_pct = seg["start"] / audio_duration
                        end_pct = seg["end"] / audio_duration
                        start_pos = int(start_pct * viz_width)
                        end_pos = int(end_pct * viz_width)

                        # Mark speech activity with █
                        for i in range(start_pos, min(end_pos + 1, viz_width)):
                            viz_chars[i] = "█"

                    speech_viz = "".join(viz_chars)
                else:
                    speech_viz = " " * 60  # Empty if no segments

                formatted_transcript = f"""========== TRANSMISSION STATUS REPORT ==========
STATUS: TRANSCRIPTION COMPLETE
FILE: /workspace/recordings/{wav_filename}
MODEL: {WHISPER_MODEL}
BEAM WIDTH: 5
STARTED: {start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
------------------------------------------------------------
FINISHED: {end_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
DURATION (AUDIO): {audio_duration:.2f}s
LANGUAGE: {language}
------------------------------------------------------------
WAVEFORM (RMS AMPLITUDE):
[{waveform_viz}]
0s{' ' * 54}{audio_duration:.1f}s

SPEECH ACTIVITY:
[{speech_viz}]
0s{' ' * 54}{audio_duration:.1f}s
------------------------------------------------------------
TELEGRAPH COPY FOLLOWS
0001 [0000.00s - {audio_duration:.2f}s] {transcript_text}
END OF TRANSMISSION STOP
"""

                # Save transcript with formatted header using original filename
                # Replace .wav extension with .txt
                transcript_filename = Path(wav_filename).stem + ".txt"
                transcript_file = TRANSCRIPTS_DIR / transcript_filename

                print(f"📝 Saving transcript to: {transcript_file.name}", file=sys.stderr, flush=True)
                transcript_file.write_text(formatted_transcript)
                print(f"💾 Transcript saved: {transcript_file} ({len(formatted_transcript)} bytes)", file=sys.stderr, flush=True)

                # Update job
                job["status"] = "completed"
                job["transcript_file"] = str(transcript_file)
                job["transcript"] = transcript_text
                job["completed"] = utc_now()

                print(f"✅ Job {job_id} completed: {len(transcript_text)} chars", file=sys.stderr, flush=True)
                print(f"   Original WAV: {wav_filename}", file=sys.stderr, flush=True)
                print(f"   Transcript file: {transcript_filename}", file=sys.stderr, flush=True)
                print(f"   Available for download at: /download/{job_id}", file=sys.stderr, flush=True)

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
