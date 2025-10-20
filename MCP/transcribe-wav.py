#!/usr/bin/env python3
"""MCP: transcribe-wav

Transcribe WAV files using faster-whisper. This implementation starts the
transcription in the background so the MCP call returns immediately; polling the
status file (or the companion status tool) reveals progress or completion.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import traceback
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    WhisperModel = None  # type: ignore

mcp = FastMCP("transcribe-wav")

_MODEL_CACHE: Dict[str, WhisperModel] = {}
_MODEL_LOCK = asyncio.Lock()
_ACTIVE_JOBS: Dict[str, asyncio.Task] = {}
_JOB_METADATA: Dict[str, Dict[str, object]] = {}
_JOB_RESULTS: Dict[str, Dict[str, object]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(dt: Optional[datetime]) -> str:
    if dt is None:
        return "UNKNOWN"
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def _resolve_path(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _write_status_report(path: Path, lines: List[str]) -> None:
    report = "\n".join(lines).rstrip() + "\n"
    path.write_text(report, encoding="utf-8")


def _telegraphify(text: str) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    if not cleaned:
        return ""
    cleaned = cleaned.upper().rstrip(".")
    if not cleaned.endswith(" STOP"):
        cleaned = f"{cleaned} STOP"
    return cleaned


async def _load_model(model_size: str) -> WhisperModel:
    if WhisperModel is None:
        raise RuntimeError(
            "faster-whisper not installed inside MCP environment; rebuild the "
            "Codex container with this dependency."
        )
    async with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(model_size)
        if cached is not None:
            print(f"✓ Model {model_size} already loaded from cache", file=sys.stderr, flush=True)
            return cached
        
        print(f"⚙ Loading Whisper model: {model_size}", file=sys.stderr, flush=True)
        print(f"  Cache location: /opt/whisper-cache", file=sys.stderr, flush=True)
        
        # Check if model files exist
        cache_path = Path("/opt/whisper-cache")
        model_exists = False
        if cache_path.exists():
            # Look for model files (simplified check)
            model_files = list(cache_path.glob(f"*{model_size}*"))
            if model_files:
                model_exists = True
                print(f"  Model files found in cache ({len(model_files)} files)", file=sys.stderr, flush=True)
            else:
                print(f"  Model not cached - will download (~3GB for large-v3)", file=sys.stderr, flush=True)
                print(f"  This is a one-time download that may take several minutes", file=sys.stderr, flush=True)
        
        loop = asyncio.get_running_loop()
        # Models will be downloaded to /opt/whisper-cache on first use
        model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                download_root="/opt/whisper-cache"
            ),
        )
        _MODEL_CACHE[model_size] = model
        print(f"✓ Model {model_size} loaded and ready", file=sys.stderr, flush=True)
        return model


async def _transcribe_job(
    job_id: str,
    source_path: Path,
    transcript_path: Path,
    model_size: str,
    beam_size: int,
    started_at: datetime,
) -> None:
    def _status_header(status: str) -> List[str]:
        return [
            "========== TRANSMISSION STATUS REPORT ==========",
            f"STATUS: {status}",
            f"FILE: {source_path}",
            f"MODEL: {model_size}",
            f"BEAM WIDTH: {beam_size}",
            f"STARTED: {_format_timestamp(started_at)}",
            "------------------------------------------------------------",
        ]

    try:
        # Update status: loading model
        loading_time = _utc_now()
        loading_header = _status_header("LOADING MODEL")
        loading_header.append(f"LOADING STARTED: {_format_timestamp(loading_time)}")
        loading_header.append("")
        loading_header.append(f"Initializing Whisper {model_size} model from /opt/whisper-cache")
        loading_header.append("If model not cached: downloading ~3GB (one-time, several minutes)")
        loading_header.append("If model cached: loading from disk (seconds)")
        loading_header.append("")
        loading_header.append("MAXIMUM EXPECTED TIME: 10 minutes from start")
        loading_header.append("If status unchanged after 10 minutes: job has likely failed")
        loading_header.append("DO NOT RETRY - Report error to supervisor and enjoy your island vacation")
        loading_header.append("")
        loading_header.append("Stand by for model initialization STOP")
        _write_status_report(transcript_path, loading_header)
        
        model = await _load_model(model_size)
        
        # Update status: transcribing
        transcribe_start = _utc_now()
        load_duration = (transcribe_start - loading_time).total_seconds()
        elapsed_from_start = (transcribe_start - started_at).total_seconds()
        
        # Calculate when failure should be assumed (10 minutes from job start)
        max_duration_seconds = 600  # 10 minutes
        time_remaining = max_duration_seconds - elapsed_from_start
        expected_completion = transcribe_start.timestamp() + time_remaining
        expected_completion_dt = datetime.fromtimestamp(expected_completion, tz=timezone.utc)
        
        transcribing_header = _status_header("TRANSCRIBING AUDIO")
        transcribing_header.append(f"PROCESSING STARTED: {_format_timestamp(transcribe_start)}")
        transcribing_header.append(f"MODEL LOAD TIME: {load_duration:.1f}s")
        transcribing_header.append(f"ELAPSED SINCE JOB START: {elapsed_from_start:.1f}s")
        transcribing_header.append("")
        transcribing_header.append("Model initialized successfully STOP")
        transcribing_header.append("Audio transcription in progress")
        transcribing_header.append("")
        transcribing_header.append(f"FAILURE THRESHOLD: {_format_timestamp(expected_completion_dt)}")
        transcribing_header.append(f"TIME UNTIL ASSUMED FAILURE: {time_remaining:.0f}s ({time_remaining/60:.1f} minutes)")
        transcribing_header.append("If status unchanged past threshold: DO NOT return to water cooler")
        transcribing_header.append("Report failure to supervisor immediately")
        transcribing_header.append("")
        transcribing_header.append("Await final transmission STOP")
        _write_status_report(transcript_path, transcribing_header)
        
        loop = asyncio.get_running_loop()

        def _do_transcribe() -> Dict[str, object]:
            segments, info = model.transcribe(str(source_path), beam_size=beam_size)
            segment_payload: List[Dict[str, object]] = []
            collected_text: List[str] = []
            for seg in segments:
                text = seg.text.strip()
                segment_payload.append(
                    {
                        "start": float(seg.start) if seg.start is not None else 0.0,
                        "end": float(seg.end) if seg.end is not None else 0.0,
                        "text": text,
                    }
                )
                collected_text.append(text)

            info_payload = {
                "duration": float(getattr(info, "duration", 0.0)),
                "language": getattr(info, "language", None),
            }
            return {
                "segments": segment_payload,
                "text": " ".join(collected_text).strip(),
                "info": info_payload,
            }

        result = await loop.run_in_executor(None, _do_transcribe)
        finished_at = _utc_now()

        segments: List[Dict[str, object]] = result["segments"]  # type: ignore[assignment]
        telegraph_lines = []
        for idx, seg in enumerate(segments, start=1):
            start_time = seg["start"]
            end_time = seg["end"]
            text = _telegraphify(seg["text"])  # type: ignore[arg-type]
            if text:
                telegraph_lines.append(
                    f"{idx:04d} [{start_time:07.2f}s - {end_time:07.2f}s] {text}"
                )

        header = _status_header("TRANSCRIPTION COMPLETE")
        header.append(f"FINISHED: {_format_timestamp(finished_at)}")
        header.append(f"DURATION (AUDIO): {result['info']['duration']:.2f}s")
        language = result["info"].get("language")
        header.append(f"LANGUAGE: {language or 'UNKNOWN'}")
        header.append("------------------------------------------------------------")
        header.append("TELEGRAPH COPY FOLLOWS")
        if telegraph_lines:
            header.extend(telegraph_lines)
        else:
            header.append("NO INTELLIGIBLE AUDIO DETECTED STOP")
        header.append("END OF TRANSMISSION STOP")

        _write_status_report(transcript_path, header)
        
        # Rename from .transcribing.txt to .txt on completion
        # Keep the base filename from the source WAV
        final_path = transcript_path.parent / f"{source_path.stem}.txt"
        transcript_path.rename(final_path)

        payload = {
            "success": True,
            "status": "complete",
            "file": str(source_path),
            "transcript_file": str(final_path),
            "segments": segments,
            "text": result["text"],
            "telegraph": telegraph_lines,
            "duration": result["info"]["duration"],
            "language": result["info"].get("language"),
            "started": started_at.isoformat(),
            "finished": finished_at.isoformat(),
        }
        _JOB_RESULTS[job_id] = payload
    except Exception as exc:  # pragma: no cover - defensive, best effort logging
        finished_at = _utc_now()
        header = _status_header("TRANSCRIPTION FAILED")
        header.append(f"FINISHED: {_format_timestamp(finished_at)}")
        header.append("------------------------------------------------------------")
        header.append("Investigation required STOP")
        header.append(f"ERROR: {exc}")
        header.append("TRACEBACK FOLLOWS")
        header.extend(traceback.format_exc().splitlines())
        _write_status_report(transcript_path, header)
        
        # Rename from .transcribing.txt to .failed.txt on error
        # Keep the base filename from the source WAV
        failed_path = transcript_path.parent / f"{source_path.stem}.failed.txt"
        try:
            transcript_path.rename(failed_path)
        except Exception:
            failed_path = transcript_path

        _JOB_RESULTS[job_id] = {
            "success": False,
            "status": "failed",
            "file": str(source_path),
            "transcript_file": str(failed_path),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "started": started_at.isoformat(),
            "finished": finished_at.isoformat(),
        }
    finally:
        _ACTIVE_JOBS.pop(job_id, None)


@mcp.tool()
async def transcribe_wav(
    filename: str,
    model_size: str = "large-v3",
    beam_size: int = 5,
    output_dir: str = "/workspace/transcriptions",
) -> Dict[str, object]:
    """Start transcribing a WAV file asynchronously.

    The call returns immediately with the path to a status/transcript file and a
    job identifier. The status file is created right away with a "TRANSCRIBING"
    marker so the assistant can report progress. Poll the companion
    ``transcription_status`` tool to watch for completion.

    IMPORTANT: When monitoring a directory (e.g., codex -Monitor), files may be
    in subdirectories (e.g., recordings/audio.wav). By default, the transcript
    .txt file is created alongside the source WAV file. Use output_dir to place
    the transcript in the monitored directory instead, so it's visible where you
    are working.

    Args:
        filename: Path to the WAV file to transcribe (can be in subdirectory)
        model_size: Whisper model size (default: large-v3)
        beam_size: Beam search width (default: 5)
        output_dir: Directory to write transcript file (default: /workspace/transcriptions).
                   Transcripts are always written to a centralized location to avoid
                   triggering file monitors watching the source audio directory.

    Returns:
        Dictionary with job_id, transcript_file path, and status information.

    Example:
        # Default: transcript goes to /workspace/transcriptions
        transcribe_wav(filename="/workspace/recordings/audio.wav")
        # Creates: /workspace/transcriptions/audio.txt

        # Custom output directory
        transcribe_wav(filename="/workspace/recordings/audio.wav", output_dir="/workspace/completed")
        # Creates: /workspace/completed/audio.txt
    """

    import sys
    print("=" * 60, file=sys.stderr, flush=True)
    print(f"[transcribe-wav] MCP TOOL CALLED", file=sys.stderr, flush=True)
    print(f"  filename: {filename}", file=sys.stderr, flush=True)
    print(f"  model_size: {model_size}", file=sys.stderr, flush=True)
    print(f"  beam_size: {beam_size}", file=sys.stderr, flush=True)
    print(f"  output_dir: {output_dir!r}", file=sys.stderr, flush=True)
    print("=" * 60, file=sys.stderr, flush=True)

    if beam_size <= 0:
        error = "beam_size must be positive"
        print(f"  ✗ ERROR: {error}", file=sys.stderr, flush=True)
        return {"success": False, "error": error}

    source_path = _resolve_path(filename)
    print(f"  Resolved source path: {source_path}", file=sys.stderr, flush=True)

    if not source_path.exists():
        error = f"File not found: {source_path}"
        print(f"  ✗ ERROR: {error}", file=sys.stderr, flush=True)
        return {"success": False, "error": error}
    print(f"  ✓ Source file exists", file=sys.stderr, flush=True)

    if source_path.suffix.lower() != ".wav":
        error = "Only .wav files are supported"
        print(f"  ✗ ERROR: {error} (got: {source_path.suffix})", file=sys.stderr, flush=True)
        return {"success": False, "error": error}
    print(f"  ✓ File extension is .wav", file=sys.stderr, flush=True)

    # If output_dir specified, use it; otherwise use source file's directory
    # Name transcript after the source file so monitors can track them
    base_name = source_path.stem
    if output_dir:
        print(f"  Using output directory: {output_dir}", file=sys.stderr, flush=True)
        output_path = _resolve_path(output_dir)
        print(f"  Resolved output path: {output_path}", file=sys.stderr, flush=True)

        # Create output directory if it doesn't exist
        if not output_path.exists():
            print(f"  Creating output directory: {output_path}", file=sys.stderr, flush=True)
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                print(f"  ✓ Output directory created", file=sys.stderr, flush=True)
            except Exception as exc:
                error = f"Failed to create output directory {output_path}: {exc}"
                print(f"  ✗ ERROR: {error}", file=sys.stderr, flush=True)
                return {"success": False, "error": error}

        if not output_path.is_dir():
            error = f"Output path is not a directory: {output_path}"
            print(f"  ✗ ERROR: {error}", file=sys.stderr, flush=True)
            return {"success": False, "error": error}
        transcript_path = output_path / f"{base_name}.transcribing.txt"
        print(f"  ✓ Transcript will be placed in: {transcript_path}", file=sys.stderr, flush=True)
    else:
        transcript_path = source_path.parent / f"{base_name}.transcribing.txt"
        print(f"  Using default location (next to source): {transcript_path}", file=sys.stderr, flush=True)

    started_at = _utc_now()
    job_id = uuid.uuid4().hex
    print(f"  Generated job ID: {job_id}", file=sys.stderr, flush=True)

    header = [
        "========== TRANSMISSION STATUS REPORT ==========",
        "STATUS: TRANSCRIBING",
        f"FILE: {source_path}",
        f"MODEL: {model_size}",
        f"BEAM WIDTH: {beam_size}",
        f"STARTED: {_format_timestamp(started_at)}",
        "------------------------------------------------------------",
        "Transcription underway. Await final report. STOP",
    ]
    _write_status_report(transcript_path, header)

    # Queue the job for the persistent daemon to process
    import json
    queue_file = Path("/opt/codex-home/transcription_queue.json")

    job_data = {
        "job_id": job_id,
        "source_file": str(source_path),
        "transcript_file": str(transcript_path),
        "model": model_size,
        "beam_size": beam_size,
        "started": started_at.isoformat(),
    }

    print(f"[transcribe-wav] Queuing job {job_id}", file=sys.stderr, flush=True)
    print(f"  Source: {source_path}", file=sys.stderr, flush=True)
    print(f"  Transcript: {transcript_path}", file=sys.stderr, flush=True)
    print(f"  Queue file: {queue_file}", file=sys.stderr, flush=True)

    # Load existing queue
    queue = []
    if queue_file.exists():
        try:
            existing_content = queue_file.read_text()
            print(f"  Existing queue file size: {len(existing_content)} bytes", file=sys.stderr, flush=True)
            queue = json.loads(existing_content)
            print(f"  Loaded {len(queue)} existing job(s)", file=sys.stderr, flush=True)
        except Exception as load_exc:
            print(f"  WARNING: Failed to load existing queue: {load_exc}", file=sys.stderr, flush=True)
            print(f"  Starting with empty queue", file=sys.stderr, flush=True)
            queue = []
    else:
        print(f"  Queue file doesn't exist yet, will create", file=sys.stderr, flush=True)

    # Add new job
    queue.append(job_data)
    print(f"  Queue now contains {len(queue)} job(s)", file=sys.stderr, flush=True)

    # Save queue
    try:
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"  Ensured parent directory exists: {queue_file.parent}", file=sys.stderr, flush=True)

        queue_json = json.dumps(queue, indent=2)
        print(f"  Writing {len(queue_json)} bytes to queue file", file=sys.stderr, flush=True)

        queue_file.write_text(queue_json)
        print(f"  ✓ Queue file written successfully", file=sys.stderr, flush=True)

        # Verify write
        if queue_file.exists():
            verify_size = queue_file.stat().st_size
            print(f"  ✓ Verified: queue file exists ({verify_size} bytes)", file=sys.stderr, flush=True)
        else:
            print(f"  ✗ ERROR: Queue file does not exist after write!", file=sys.stderr, flush=True)
            return {
                "success": False,
                "error": "Queue file disappeared after write - possible permission issue",
                "job_id": job_id,
                "transcript_file": str(transcript_path),
            }

    except Exception as write_exc:
        error_msg = f"Failed to write queue file: {write_exc}"
        print(f"  ✗ ERROR: {error_msg}", file=sys.stderr, flush=True)
        print(f"  Traceback: {traceback.format_exc()}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": error_msg,
            "job_id": job_id,
            "transcript_file": str(transcript_path),
        }

    print(f"[transcribe-wav] ✓ Job {job_id} queued successfully", file=sys.stderr, flush=True)

    return {
        "success": True,
        "status": "queued",
        "job_id": job_id,
        "file": str(source_path),
        "transcript_file": str(transcript_path),
        "message": "Transcription queued for background processing. Monitor the .transcribing.txt file for progress updates.",
    }


@mcp.tool()
async def transcription_status(
    job_id: Optional[str] = None,
    transcript_file: Optional[str] = None,
) -> Dict[str, object]:
    """Inspect the status or final transcript of an asynchronous transcription."""

    meta: Optional[Dict[str, object]] = None
    if job_id:
        meta = _JOB_METADATA.get(job_id)
        if meta is None:
            return {"success": False, "error": f"Unknown job_id: {job_id}"}
        transcript_path = Path(meta["transcript_file"])  # type: ignore[arg-type]
    elif transcript_file:
        transcript_path = _resolve_path(transcript_file)
    else:
        return {"success": False, "error": "Provide either job_id or transcript_file"}

    content = ""
    if transcript_path.exists():
        try:
            content = transcript_path.read_text(encoding="utf-8")
        except Exception as exc:  # pragma: no cover - best effort
            return {"success": False, "error": f"Failed to read status file: {exc}"}
    else:
        return {
            "success": False,
            "error": f"Status file not found: {transcript_path}",
        }

    status: str
    if "TRANSCRIPTION COMPLETE" in content:
        status = "complete"
    elif "TRANSCRIPTION FAILED" in content:
        status = "failed"
    elif "TRANSCRIBING" in content:
        status = "transcribing"
    else:
        status = "unknown"

    active = False
    result_payload: Optional[Dict[str, object]] = None
    resolved_job_id: Optional[str] = None
    if job_id:
        resolved_job_id = job_id
    else:
        # try to reverse map transcript file to an existing job
        for jid, data in _JOB_METADATA.items():
            if data.get("transcript_file") == str(transcript_path):
                resolved_job_id = jid
                break
    if resolved_job_id:
        task = _ACTIVE_JOBS.get(resolved_job_id)
        active = bool(task and not task.done())
        result_payload = _JOB_RESULTS.get(resolved_job_id)

    response: Dict[str, object] = {
        "success": True,
        "status": status,
        "file": str(transcript_path),
        "content": content,
        "job_active": active,
    }
    if resolved_job_id:
        response["job_id"] = resolved_job_id
    if meta:
        response["metadata"] = meta
    if result_payload:
        response["result"] = result_payload

    return response


@mcp.tool()
async def list_transcription_jobs() -> Dict[str, object]:
    """List all transcription jobs (active and completed).
    
    Returns information about all transcription jobs including their status,
    file paths, and whether they are currently running.
    """
    
    jobs = []
    
    for job_id, metadata in _JOB_METADATA.items():
        task = _ACTIVE_JOBS.get(job_id)
        result = _JOB_RESULTS.get(job_id)
        
        job_info = {
            "job_id": job_id,
            "file": metadata.get("file"),
            "transcript_file": metadata.get("transcript_file"),
            "model": metadata.get("model"),
            "started": metadata.get("started"),
            "active": bool(task and not task.done()),
        }
        
        if result:
            job_info["status"] = result.get("status")
            job_info["success"] = result.get("success")
            if "finished" in result:
                job_info["finished"] = result["finished"]
            if "duration" in result:
                job_info["duration"] = result["duration"]
            if "error" in result:
                job_info["error"] = result["error"]
        else:
            job_info["status"] = "transcribing" if job_info["active"] else "unknown"
        
        jobs.append(job_info)
    
    return {
        "success": True,
        "total_jobs": len(jobs),
        "active_jobs": sum(1 for j in jobs if j.get("active")),
        "jobs": jobs,
    }


if __name__ == "__main__":
    mcp.run()
