#!/usr/bin/env python3
"""MCP: transcribe-wav

Upload WAV files to persistent transcription service for processing.
Service keeps Whisper model loaded, avoiding repeated model loading overhead.
"""

from __future__ import annotations

import sys
import os
import uuid
from pathlib import Path
from typing import Dict, Optional
from urllib import request as _urlrequest
from urllib.parse import urljoin
import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transcribe-wav")

# Service URL - can be overridden via environment variable
# Use Docker container name for inter-container communication on codex-network
DEFAULT_SERVICE_URL = "http://gnosis-transcription-service:8765"
SERVICE_URL = os.getenv("TRANSCRIPTION_SERVICE_URL", DEFAULT_SERVICE_URL)


def _generate_job_id() -> str:
    """Generate unique job ID."""
    return str(uuid.uuid4()).replace("-", "")[:16]


def _upload_file(service_url: str, file_path: Path, job_id: str, model: str) -> Dict:
    """Upload WAV file to transcription service."""
    import mimetypes
    from io import BytesIO

    # Read WAV file
    if not file_path.exists():
        raise FileNotFoundError(f"WAV file not found: {file_path}")

    wav_data = file_path.read_bytes()

    # Prepare multipart form data
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
    body = BytesIO()

    # Add file field
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode())
    body.write(f"Content-Type: audio/wav\r\n\r\n".encode())
    body.write(wav_data)
    body.write(b"\r\n")

    # Add job_id field
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="job_id"\r\n\r\n')
    body.write(job_id.encode())
    body.write(b"\r\n")

    # Add model field
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body.write(model.encode())
    body.write(b"\r\n")

    # End boundary
    body.write(f"--{boundary}--\r\n".encode())

    # Upload
    upload_url = urljoin(service_url, "/transcribe")
    req = _urlrequest.Request(
        upload_url,
        data=body.getvalue(),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "transcribe-wav-mcp/1.0"
        },
        method="POST"
    )

    with _urlrequest.urlopen(req, timeout=60) as resp:
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"Upload failed with HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def _check_status(service_url: str, job_id: str) -> Dict:
    """Check transcription status."""
    import urllib.error
    status_url = urljoin(service_url, f"/status/{job_id}")
    req = _urlrequest.Request(status_url, headers={"User-Agent": "transcribe-wav-mcp/1.0"})

    try:
        with _urlrequest.urlopen(req, timeout=10) as resp:
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Status check failed with HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Read error response body for debugging
        error_body = e.read().decode("utf-8") if e.fp else "No error body"
        raise RuntimeError(f"HTTP Error {e.code}: {e.reason} - {error_body}")


def _download_transcript(service_url: str, job_id: str) -> str:
    """Download completed transcript."""
    download_url = urljoin(service_url, f"/download/{job_id}")
    req = _urlrequest.Request(download_url, headers={"User-Agent": "transcribe-wav-mcp/1.0"})

    with _urlrequest.urlopen(req, timeout=30) as resp:
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"Download failed with HTTP {resp.status}")
        return resp.read().decode("utf-8")


@mcp.tool()
async def transcribe_wav(
    filename: str,
    output_dir: str = "/workspace/transcriptions",
    model: str = "large-v3",
    service_url: Optional[str] = None,
) -> Dict[str, object]:
    """Upload WAV file to transcription service for processing.

    The transcription service keeps the Whisper model loaded in memory,
    avoiding the overhead of loading it on every request.

    Args:
        filename: Path to WAV file to transcribe
        output_dir: Directory where transcript will be saved (default: /workspace/transcriptions)
        model: Whisper model to use (default: large-v3)
        service_url: Transcription service URL (default: from env or http://host.docker.internal:8765)

    Returns:
        Dictionary with upload status and job_id for status checking.

    Example:
        transcribe_wav(filename="/workspace/recordings/transmission.wav")
    """

    try:
        print(f"[transcribe-wav] MCP TOOL CALLED", file=sys.stderr, flush=True)
        print(f"  filename: {filename}", file=sys.stderr, flush=True)
        print(f"  output_dir: {output_dir}", file=sys.stderr, flush=True)
        print(f"  model: {model}", file=sys.stderr, flush=True)

        # Resolve paths
        file_path = Path(filename)
        if not file_path.is_absolute():
            file_path = Path("/workspace") / filename
            print(f"  Resolved to absolute path: {file_path}", file=sys.stderr, flush=True)

        output_path = Path(output_dir)
        if not output_path.exists():
            print(f"  Creating output directory: {output_path}", file=sys.stderr, flush=True)
            output_path.mkdir(parents=True, exist_ok=True)

        # Use provided service URL or default
        svc_url = service_url or SERVICE_URL
        print(f"  Service URL: {svc_url}", file=sys.stderr, flush=True)

        # Generate job ID
        job_id = _generate_job_id()
        print(f"  Job ID: {job_id}", file=sys.stderr, flush=True)

        # Upload file
        print(f"📤 Uploading {file_path.name} to transcription service...", file=sys.stderr, flush=True)
        upload_response = _upload_file(svc_url, file_path, job_id, model)
        print(f"✅ Upload complete: {upload_response}", file=sys.stderr, flush=True)

        # Create local .transcribing.txt status file
        status_file = output_path / f"{file_path.stem}.transcribing.txt"
        status_content = f"""TRANSCRIPTION IN PROGRESS

Job ID: {job_id}
Source: {filename}
Model: {model}
Service: {svc_url}
Status: Queued at transcription service

Use check_transcription_status(job_id="{job_id}") to poll for completion.
"""
        status_file.write_text(status_content)
        print(f"  Created status file: {status_file}", file=sys.stderr, flush=True)

        return {
            "success": True,
            "status": "queued",
            "job_id": job_id,
            "file": str(file_path),
            "status_file": str(status_file),
            "service_url": svc_url,
            "message": f"WAV file uploaded to transcription service. Job ID: {job_id}"
        }

    except Exception as e:
        print(f"❌ Transcription upload failed: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to upload WAV file to transcription service"
        }


@mcp.tool()
async def check_transcription_status(
    job_id: str,
    output_dir: str = "/workspace/transcriptions",
    service_url: Optional[str] = None,
    download_if_ready: bool = True,
) -> Dict[str, object]:
    """Check status of transcription job and download if complete.

    Args:
        job_id: Job ID returned from transcribe_wav()
        output_dir: Directory where transcript will be saved (default: /workspace/transcriptions)
        service_url: Transcription service URL (default: from env or http://host.docker.internal:8765)
        download_if_ready: Automatically download transcript if completed (default: True)

    Returns:
        Dictionary with job status and transcript if completed.

    Example:
        check_transcription_status(job_id="abc123def456")
    """

    try:
        print(f"[check_transcription_status] Checking job {job_id}", file=sys.stderr, flush=True)

        # Use provided service URL or default
        svc_url = service_url or SERVICE_URL

        # Check status
        status_response = _check_status(svc_url, job_id)
        print(f"  Status: {status_response['status']}", file=sys.stderr, flush=True)

        result = {
            "success": True,
            "job_id": job_id,
            "status": status_response["status"],
        }

        if "progress" in status_response:
            result["progress"] = status_response["progress"]

        if "error" in status_response:
            result["error"] = status_response["error"]

        # If completed and download requested
        if status_response["status"] == "completed" and download_if_ready:
            print(f"📥 Downloading completed transcript...", file=sys.stderr, flush=True)

            # Download transcript
            transcript_text = _download_transcript(svc_url, job_id)

            # Save to local filesystem
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Find the corresponding .transcribing.txt file to get original filename
            transcript_filename = None
            transcribing_file = None
            for status_file in output_path.glob("*.transcribing.txt"):
                status_content = status_file.read_text()
                if job_id in status_content:
                    # Extract original filename from status file
                    # Status file is named {original_stem}.transcribing.txt
                    # Remove .transcribing.txt extension to get original base name
                    original_name = status_file.name.replace(".transcribing.txt", "")
                    transcript_filename = original_name + ".txt"
                    transcribing_file = status_file
                    print(f"  Found status file: {status_file}", file=sys.stderr, flush=True)
                    print(f"  Will save as: {transcript_filename}", file=sys.stderr, flush=True)
                    break

            # Fallback: use job_id if we can't find the original filename
            if not transcript_filename:
                transcript_filename = f"{job_id}.txt"
                print(f"  Warning: Could not find original filename, using job_id: {transcript_filename}", file=sys.stderr, flush=True)

            transcript_file = output_path / transcript_filename
            transcript_file.write_text(transcript_text)
            print(f"✅ Transcript saved to {transcript_file}", file=sys.stderr, flush=True)

            # Remove .transcribing.txt status file
            if transcribing_file and transcribing_file.exists():
                print(f"  Removing status file: {transcribing_file}", file=sys.stderr, flush=True)
                transcribing_file.unlink()

            result["transcript"] = transcript_text
            result["transcript_file"] = str(transcript_file)
            result["message"] = f"Transcription completed and saved to {transcript_file}"

        elif status_response["status"] == "processing":
            result["message"] = "Transcription in progress..."
        elif status_response["status"] == "queued":
            result["message"] = "Transcription queued, waiting for processing..."
        elif status_response["status"] == "failed":
            result["message"] = f"Transcription failed: {status_response.get('error', 'Unknown error')}"

        return result

    except Exception as e:
        print(f"❌ Status check failed: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to check transcription status"
        }


if __name__ == "__main__":
    mcp.run()
