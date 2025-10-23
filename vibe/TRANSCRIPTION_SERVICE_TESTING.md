# Transcription Service - Testing Guide

## Implementation Complete! ✅

All components have been implemented:

1. ✅ `scripts/transcription_service_daemon.py` - HTTP transcription service
2. ✅ `MCP/transcribe-wav.py` - Updated to upload via HTTP
3. ✅ `scripts/start_transcription_service.ps1` - Service startup script
4. ✅ `scripts/codex_container.ps1` - Added TranscriptionServiceUrl parameter
5. ✅ `MONITOR.md` - Updated workflow for new tools

---

## Testing Steps

### Step 1: Rebuild Container

The container needs to be rebuilt to include the new MCP tools and service daemon:

```powershell
cd C:\Users\kord\Code\gnosis\codex-container
.\scripts\codex_container.ps1 -Install
```

This will:
- Build the container with updated transcribe-wav.py
- Install radio-net.py MCP tool
- Copy transcription_service_daemon.py to /opt/scripts/
- Remove gnosis-files.py (disabled to prevent timeout)

### Step 2: Start Transcription Service

Start the persistent transcription service container:

```powershell
.\scripts\start_transcription_service.ps1
```

This will:
- Start container named `codex-transcription-service`
- Load Whisper large-v3 model (may take a few minutes first time)
- Expose service on http://localhost:8765
- Show health check status

**Expected output:**
```
✅ Service started
   Container ID: <container-id>

✅ Health check passed

Service Status:
  Model Loaded: True
  Model Name: large-v3
  Queue Size: 0
```

### Step 3: Verify Service is Running

Check that the service is healthy:

```powershell
curl http://localhost:8765/health
```

**Expected response:**
```json
{
  "status": "ok",
  "model_loaded": true,
  "model_name": "large-v3",
  "queue": {
    "queued": 0,
    "processing": 0,
    "completed": 0,
    "failed": 0,
    "total": 0
  }
}
```

### Step 4: Start File Monitor

Start monitoring the VHF recordings directory:

```powershell
cd C:\Users\kord\Code\gnosis\codex-container
.\scripts\codex_container.ps1 -Monitor C:\Users\kord\Code\gnosis\vhf_monitor\recordings
```

This will:
- Watch for new WAV files in recordings/
- Use MONITOR.md prompt for Alpha India
- Pass TRANSCRIPTION_SERVICE_URL environment variable

### Step 5: Trigger Transcription

Drop a WAV file into the recordings directory to trigger the workflow.

**Alpha India should:**
1. Upload WAV to transcription service via `transcribe_wav()`
2. Wait at water cooler for 30-45 seconds
3. Check status via `check_transcription_status(job_id)`
4. Download completed transcript when ready
5. Read transcript and extract information
6. If Alpha Tango requested weather:
   - Geocode location
   - Get weather forecast
   - Transmit response directly to ALPHATANGO via `radio_net_transmit()`
   - Do NOT report to Trek
7. If transcript contains maritime intelligence:
   - Report to Trek via `report_to_supervisor()`
8. Exit cleanly with code 0

---

## Expected Logs

### Transcription Service Logs

Watch the service logs during processing:

```powershell
docker logs -f codex-transcription-service
```

**Expected output:**
```
🔄 Loading Whisper model: large-v3
✅ Model large-v3 loaded and ready
🔄 Queue processor started

📥 Job abc123def456 received: 524288 bytes
⚙️  Processing job abc123def456
✅ Job abc123def456 completed: 145 chars
📤 Job abc123def456 downloaded
```

### Monitor Logs

Check the monitor log file:

```
C:\Users\kord\Code\gnosis\vhf_monitor\recordings\codex-monitor.log
```

**Expected entries:**
```
[2025-10-19 21:30:00] Dispatching Codex run for transmission_20251019_213000_30.wav
[2025-10-19 21:30:15] Codex run completed for transmission_20251019_213000_30.wav
```

### Radio Transmissions Log

Check direct responses to Alpha Tango:

```
C:\Users\kord\Code\gnosis\vhf_monitor\recordings\radio_transmissions.log
```

**Expected format:**
```
================================================================================
TRANSMISSION at 2025-10-19 21:30:45 UTC
FROM: ALPHAINDIA
TO: ALPHATANGO
PRIORITY: ROUTINE
--------------------------------------------------------------------------------
Weather check complete for Miami. Current conditions: 24.5°C (76.1°F), partly cloudy.
Winds 12 knots from northeast. Seas 2-3 feet. Favorable for operations.
================================================================================
```

### Supervisor Reports Log

Check reports to Trek:

```
C:\Users\kord\Code\gnosis\vhf_monitor\recordings\supervisor_reports.log
```

**Should only contain actual maritime intelligence, NOT routine weather assistance.**

---

## Verification Checklist

- [ ] Container built successfully
- [ ] Transcription service starts and loads model
- [ ] Health endpoint returns 200 OK
- [ ] Monitor starts and watches directory
- [ ] WAV file triggers Alpha India
- [ ] WAV uploads to service (no model loading delay)
- [ ] Transcript downloads successfully
- [ ] Alpha India reads transcript
- [ ] Weather requests go directly to Alpha Tango via radio_net_transmit()
- [ ] Maritime intelligence gets reported to Trek
- [ ] Codex exits with code 0
- [ ] No duplicate processing of same file
- [ ] Second WAV file processes without reloading model (fast!)

---

## Troubleshooting

### Service Won't Start

**Check if port 8765 is in use:**
```powershell
netstat -ano | findstr :8765
```

**Stop existing service:**
```powershell
docker stop codex-transcription-service
docker rm codex-transcription-service
```

### Upload Fails

**Check service is reachable from container:**
```powershell
docker run --rm codex-container curl -v http://host.docker.internal:8765/health
```

**Expected:** Should see 200 OK response

### Model Not Loading

**Check service logs for errors:**
```powershell
docker logs codex-transcription-service
```

**First time:** Model download may take 5-10 minutes (~3GB)

### MCP Tool Errors

**Check MCP tool was installed:**
```powershell
docker run --rm codex-container ls -la /opt/codex-home/mcp/transcribe-wav.py
```

**Check environment variable is passed:**
```powershell
docker run --rm -e TRANSCRIPTION_SERVICE_URL=http://host.docker.internal:8765 codex-container env | findstr TRANSCRIPTION
```

---

## Performance Comparison

### Before (In-Container Daemon)

```
WAV file arrives
└─> Spin up Codex container (2s)
    └─> Load Whisper model (30-60s) ⚠️ SLOW
        └─> Transcribe audio (10-20s)
            └─> Save transcript
                └─> Process with Alpha India
                    └─> Container dies

Next WAV file arrives
└─> START OVER - Reload model again! ⚠️
```

**Total time per file: ~50-90 seconds**
**Model reloads: Every single file**

### After (Persistent Service)

```
[Transcription Service Container - Always Running]
└─> Whisper model loaded ONCE ✅
    └─> Listens on port 8765

WAV file arrives
└─> Spin up Codex container (2s)
    └─> Upload to service (1-2s) ✅ FAST
        └─> Return job_id immediately
            └─> Poll for completion
                └─> Download transcript
                    └─> Process with Alpha India
                        └─> Container dies

[Service keeps running with model loaded]

Next WAV file arrives
└─> Upload immediately (1-2s) ✅ NO RELOAD
    └─> Transcribe with already-loaded model (10-20s)
        └─> Done!
```

**Total time per file: ~15-25 seconds**
**Model reloads: ZERO (loaded once at service startup)**
**Speedup: 3-4x faster! 🚀**

---

## Next Steps After Testing

Once testing is successful:

1. **Adjust water cooler wait times** if transcriptions complete faster
2. **Add webhook support** (optional) - Service can POST to callback URL when done, eliminating polling
3. **Monitor service health** - Add to system startup or Docker Compose
4. **Scale if needed** - Can run multiple transcription service instances on different ports
5. **Add metrics** - Track job completion times, queue depths, etc.

---

## Service Management Commands

```powershell
# View logs
docker logs -f codex-transcription-service

# Restart service
docker restart codex-transcription-service

# Stop service
docker stop codex-transcription-service

# Check service status
docker ps -f name=codex-transcription-service

# Check health
curl http://localhost:8765/health

# View queue status
curl http://localhost:8765/health | jq .queue
```

---

## Success Criteria

✅ **Test is successful when:**

1. Transcription service starts and stays running
2. First WAV file transcribes correctly
3. **Second WAV file transcribes FAST (no model reload)**
4. Alpha India responds to Alpha Tango weather requests via radio
5. Maritime intelligence gets reported to Trek (not routine assistance)
6. No exit code 1 errors
7. No duplicate processing
8. Logs are clean and informative

🎉 **You'll know it's working when the second transcription is 3-4x faster than the first!**
