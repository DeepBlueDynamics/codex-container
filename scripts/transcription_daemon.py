#!/usr/bin/env python3
"""Transcription daemon that runs in the background and processes WAV files."""

import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

QUEUE_FILE = Path("/opt/codex-home/transcription_queue.json")
MODEL_CACHE: Dict[str, object] = {}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def write_status(path: Path, lines: List[str]) -> None:
    report = "\n".join(lines).rstrip() + "\n"
    path.write_text(report, encoding="utf-8")


def load_queue() -> List[Dict]:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except Exception:
            return []
    return []


def save_queue(queue: List[Dict]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))


def load_model(model_size: str):
    """Load Whisper model (cached)."""
    if WhisperModel is None:
        raise RuntimeError("faster-whisper not installed")
    
    if model_size in MODEL_CACHE:
        print(f"✓ Using cached model: {model_size}", flush=True)
        return MODEL_CACHE[model_size]
    
    print(f"⚙ Loading Whisper model: {model_size}", flush=True)
    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        download_root="/opt/whisper-cache"
    )
    MODEL_CACHE[model_size] = model
    print(f"✓ Model {model_size} loaded", flush=True)
    return model


def process_job(job: Dict) -> None:
    """Process a single transcription job."""
    source_path = Path(job["source_file"])
    transcript_path = Path(job["transcript_file"])
    model_size = job.get("model", "large-v3")
    beam_size = job.get("beam_size", 5)
    started_at = datetime.fromisoformat(job["started"])
    
    def status_header(status: str) -> List[str]:
        return [
            "========== TRANSMISSION STATUS REPORT ==========",
            f"STATUS: {status}",
            f"FILE: {source_path}",
            f"MODEL: {model_size}",
            f"BEAM WIDTH: {beam_size}",
            f"STARTED: {format_timestamp(started_at)}",
            "------------------------------------------------------------",
        ]
    
    try:
        # Update: loading model
        loading_time = utc_now()
        header = status_header("LOADING MODEL")
        header.append(f"LOADING STARTED: {format_timestamp(loading_time)}")
        header.append("")
        header.append(f"Initializing Whisper {model_size} model from /opt/whisper-cache")
        header.append("MAXIMUM EXPECTED TIME: 10 minutes from start")
        header.append("If status unchanged after 10 minutes: job has likely failed")
        header.append("DO NOT RETRY - Report error to supervisor and enjoy your island vacation")
        header.append("")
        header.append("Stand by for model initialization STOP")
        write_status(transcript_path, header)
        
        model = load_model(model_size)
        
        # Update: transcribing
        transcribe_start = utc_now()
        load_duration = (transcribe_start - loading_time).total_seconds()
        elapsed_from_start = (transcribe_start - started_at).total_seconds()
        
        max_duration_seconds = 600
        time_remaining = max_duration_seconds - elapsed_from_start
        expected_completion = transcribe_start.timestamp() + time_remaining
        expected_completion_dt = datetime.fromtimestamp(expected_completion, tz=timezone.utc)
        
        header = status_header("TRANSCRIBING AUDIO")
        header.append(f"PROCESSING STARTED: {format_timestamp(transcribe_start)}")
        header.append(f"MODEL LOAD TIME: {load_duration:.1f}s")
        header.append(f"ELAPSED SINCE JOB START: {elapsed_from_start:.1f}s")
        header.append("")
        header.append("Model initialized successfully STOP")
        header.append("Audio transcription in progress")
        header.append("")
        header.append(f"FAILURE THRESHOLD: {format_timestamp(expected_completion_dt)}")
        header.append(f"TIME UNTIL ASSUMED FAILURE: {time_remaining:.0f}s ({time_remaining/60:.1f} minutes)")
        header.append("If status unchanged past threshold: DO NOT return to water cooler")
        header.append("Report failure to supervisor immediately")
        header.append("")
        header.append("Await final transmission STOP")
        write_status(transcript_path, header)
        
        # Transcribe
        segments, info = model.transcribe(str(source_path), beam_size=beam_size)
        
        # Collect results
        telegraph_lines = []
        for idx, seg in enumerate(segments, start=1):
            text = seg.text.strip().upper().rstrip(".")
            if not text.endswith(" STOP"):
                text = f"{text} STOP"
            if text:
                telegraph_lines.append(
                    f"{idx:04d} [{seg.start:07.2f}s - {seg.end:07.2f}s] {text}"
                )
        
        finished_at = utc_now()
        
        # Write final result
        header = status_header("TRANSCRIPTION COMPLETE")
        header.append(f"FINISHED: {format_timestamp(finished_at)}")
        header.append(f"DURATION (AUDIO): {info.duration:.2f}s")
        header.append(f"LANGUAGE: {info.language or 'UNKNOWN'}")
        header.append("------------------------------------------------------------")
        header.append("TELEGRAPH COPY FOLLOWS")
        if telegraph_lines:
            header.extend(telegraph_lines)
        else:
            header.append("NO INTELLIGIBLE AUDIO DETECTED STOP")
        header.append("END OF TRANSMISSION STOP")
        write_status(transcript_path, header)
        
        # Rename to final
        final_path = transcript_path.parent / f"{source_path.stem}.txt"
        transcript_path.rename(final_path)
        
        print(f"✓ Completed: {source_path.name}", flush=True)
        
    except Exception as exc:
        finished_at = utc_now()
        header = status_header("TRANSCRIPTION FAILED")
        header.append(f"FINISHED: {format_timestamp(finished_at)}")
        header.append("------------------------------------------------------------")
        header.append("Investigation required STOP")
        header.append(f"ERROR: {exc}")
        header.append("TRACEBACK FOLLOWS")
        header.extend(traceback.format_exc().splitlines())
        write_status(transcript_path, header)
        
        failed_path = transcript_path.parent / f"{source_path.stem}.failed.txt"
        try:
            transcript_path.rename(failed_path)
        except Exception:
            pass
        
        print(f"✗ Failed: {source_path.name} - {exc}", flush=True)


async def daemon_loop():
    """Main daemon loop - processes queue continuously."""
    print("=" * 60, flush=True)
    print("TRANSCRIPTION DAEMON STARTED", flush=True)
    print(f"Queue file: {QUEUE_FILE}", flush=True)
    print(f"Polling interval: 2 seconds", flush=True)
    print("=" * 60, flush=True)

    check_count = 0
    while True:
        try:
            queue = load_queue()

            if queue:
                print(f"\n[{utc_now().strftime('%H:%M:%S')}] Found {len(queue)} job(s) in queue", flush=True)
                job = queue.pop(0)
                save_queue(queue)

                print(f"[{utc_now().strftime('%H:%M:%S')}] Processing: {job.get('source_file', 'UNKNOWN')}", flush=True)
                print(f"  Job ID: {job.get('job_id', 'UNKNOWN')}", flush=True)
                print(f"  Model: {job.get('model', 'UNKNOWN')}", flush=True)
                print(f"  Transcript: {job.get('transcript_file', 'UNKNOWN')}", flush=True)

                process_job(job)

                print(f"[{utc_now().strftime('%H:%M:%S')}] Job completed", flush=True)
            else:
                check_count += 1
                if check_count % 30 == 0:  # Log every 60 seconds (30 * 2sec)
                    print(f"[{utc_now().strftime('%H:%M:%S')}] Queue empty, waiting... (checked {check_count} times)", flush=True)
                await asyncio.sleep(2)  # Check every 2 seconds
        except Exception as exc:
            print(f"[{utc_now().strftime('%H:%M:%S')}] ERROR in daemon loop: {exc}", flush=True)
            print(f"Traceback: {traceback.format_exc()}", flush=True)
            await asyncio.sleep(5)  # Wait longer after error


if __name__ == "__main__":
    try:
        asyncio.run(daemon_loop())
    except KeyboardInterrupt:
        print("\nDaemon stopped", flush=True)
        sys.exit(0)
