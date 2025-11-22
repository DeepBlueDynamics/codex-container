# Transcription Service

GPU-accelerated persistent transcription service using Whisper large-v3.

## Features

- **GPU Acceleration**: CUDA-enabled for fast transcription
- **Cached Model**: Whisper large-v3 pre-downloaded in image (~3GB)
- **Persistent**: Keeps model loaded in memory, no reload between jobs
- **HTTP API**: Upload WAV files, get transcripts back
- **Job Queue**: Async processing with status polling

## Quick Start

### Build and Start

```powershell
# Build image and start service
./scripts/start_transcription_service_docker.ps1 -Build

# Or just start (uses existing image)
./scripts/start_transcription_service_docker.ps1
```

### Stop Service

```powershell
./scripts/start_transcription_service_docker.ps1 -Stop
```

### View Logs

```powershell
./scripts/start_transcription_service_docker.ps1 -Logs
```

## API Endpoints

### Upload WAV File
```bash
POST http://localhost:8765/transcribe
Content-Type: multipart/form-data

# Response
{
  "job_id": "abc123",
  "status": "queued",
  "model": "large-v3"
}
```

### Check Status
```bash
GET http://localhost:8765/status/{job_id}

# Response (processing)
{
  "job_id": "abc123",
  "status": "processing"
}

# Response (completed)
{
  "job_id": "abc123",
  "status": "completed",
  "transcript": "Full transcription text here..."
}
```

### Download Transcript
```bash
GET http://localhost:8765/download/{job_id}

# Returns plain text transcript
```

### Health Check
```bash
GET http://localhost:8765/health

# Response
{
  "status": "healthy",
  "model": "large-v3",
  "device": "cuda" # or "cpu"
}
```

## Usage from MCP

The `transcribe-wav.py` MCP server uses this service:

```python
# Uploads WAV to service
job_id = transcribe_wav(filename="/workspace/recording.wav")

# Polls until complete
status = check_transcription_status(job_id=job_id)
```

## Requirements

### GPU Support (Recommended)

1. **NVIDIA GPU** with CUDA support
2. **NVIDIA Docker runtime**:
   ```bash
   # Install nvidia-docker2
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
   sudo apt-get update && sudo apt-get install -y nvidia-docker2
   sudo systemctl restart docker
   ```

3. **Verify GPU access**:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
   ```

### CPU Fallback

Service works on CPU but is much slower (~10x). The Dockerfile will automatically fall back to CPU if GPU isn't available.

## Performance

With GPU (NVIDIA RTX 3080):
- 1 minute audio: ~5-10 seconds
- 10 minute audio: ~30-60 seconds

With CPU (8-core):
- 1 minute audio: ~60-90 seconds
- 10 minute audio: ~8-10 minutes

## Architecture

```
┌─────────────────┐
│  Codex Agent    │
│  (Alpha India)  │
└────────┬────────┘
         │ MCP call: transcribe_wav()
         ▼
┌─────────────────┐
│ transcribe-wav  │
│  MCP Server     │
└────────┬────────┘
         │ HTTP POST
         ▼
┌─────────────────────────────┐
│ Transcription Service       │
│ (Docker, port 8765)         │
│                             │
│ ┌─────────────────────────┐ │
│ │ Whisper large-v3        │ │
│ │ (loaded in memory)      │ │
│ └─────────────────────────┘ │
│                             │
│ ┌─────────────────────────┐ │
│ │ Job Queue               │ │
│ │ /app/jobs/*.json        │ │
│ └─────────────────────────┘ │
└─────────────────────────────┘
         │
         ▼
    GPU (CUDA)
```

## Troubleshooting

### Service won't start

```powershell
# Check logs
docker-compose -f docker-compose.transcription.yml logs

# Check if port 8765 is in use
netstat -ano | findstr :8765

# Rebuild from scratch
docker-compose -f docker-compose.transcription.yml down -v
./scripts/start_transcription_service_docker.ps1 -Build
```

### GPU not detected

```bash
# Verify NVIDIA runtime
docker info | grep -i nvidia

# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

### Out of memory

Large-v3 model needs ~3GB VRAM. If you have less:

1. Edit `Dockerfile.transcription`
2. Change model to `large-v2` or `medium`
3. Rebuild: `./scripts/start_transcription_service_docker.ps1 -Build`

## Files

- `Dockerfile.transcription` - GPU-enabled image with cached model
- `docker-compose.transcription.yml` - Service orchestration
- `scripts/start_transcription_service_docker.ps1` - Management script
- `scripts/transcription_service_daemon.py` - HTTP service implementation
