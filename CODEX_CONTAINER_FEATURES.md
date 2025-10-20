# Codex Container Scripts - Feature Comparison

## Overview

Two entry points for running Codex in containers:
- **`codex_container.ps1`** - PowerShell (Windows/Mac/Linux)
- **`codex_container.sh`** - Bash (Mac/Linux)

---

## ✅ Common Features (Both Scripts)

### Core Actions
- `--install` / `-Install` - Build Docker image
- `--login` / `-Login` - Authenticate with Codex
- `--shell` / `-Shell` - Interactive container shell
- `--exec` / `-Exec` - Run single Codex command
- `--serve` / `-Serve` - Start HTTP gateway
- `--monitor` / `-Monitor` - File system monitoring with MCP tools
- (default) - Interactive chat

### Configuration
- `--tag` - Custom Docker image tag
- `--workspace` - Set workspace directory
- `--codex-home` - Override Codex home directory
- `--skip-update` - Skip Codex CLI update
- `--no-auto-login` - Disable automatic login
- `--json` / `--json-e` - JSON output mode
- `--oss` / `--oss-model` - Use local Ollama models
- `--push` - Push image after build

### Gateway Options
- `--gateway-port` - HTTP server port
- `--gateway-host` - Bind address
- `--gateway-timeout-ms` - Request timeout
- `--gateway-default-model` - Default model selection

### Monitor Options
- `--monitor-prompt` - Template file (default: MONITOR.md)
- File watching with debouncing
- Template variable substitution
- MCP tool integration

---

## ⭐ PowerShell-Only Features (.ps1)

### 1. Session Management
```powershell
# List recent sessions with previews
.\codex_container.ps1

# Resume session with short ID (last 5 chars)
.\codex_container.ps1 -SessionId bffba

# Resume with full UUID
.\codex_container.ps1 -SessionId 019a0221-064c-7cd3-aad2-dffde6bbffba
```

**Features:**
- Lists 5 most recent sessions with:
  - Age (3 min ago, 2h ago, 5d ago)
  - Short ID (last 5 chars)
  - Full UUID
  - Preview of first user message
- Docker-style partial ID matching
- Resolves ambiguous IDs (errors if multiple matches)
- Platform-aware help text (shows `.cmd` on Windows, `.ps1` elsewhere)

### 2. Transcription Service Configuration
```powershell
.\codex_container.ps1 -TranscriptionServiceUrl http://localhost:9000
```

**Purpose:**
- Configure persistent transcription service endpoint
- Default: `http://host.docker.internal:8765`
- Passed to container as `TRANSCRIPTION_SERVICE_URL` environment variable
- Used by `transcribe-wav` MCP tool

### 3. Value From Remaining Arguments
```powershell
.\codex_container.ps1 arg1 arg2 --some-flag
```

**Purpose:**
- Captures positional arguments for Codex
- Makes it feel like running `codex` directly
- Example: `.\codex_container.ps1 --model=opus --reasoning=high`

### 4. Runner Installation
Automatically installs launcher on PATH:
- Creates `~/.codex-service/bin/codex_container.ps1` wrapper
- Creates `codex-container.cmd` shim for Windows
- Adds to user PATH
- Can run `codex-container` from anywhere

---

## 🔧 Implementation Details

### Session Storage Structure
```
~/.codex-service/.codex/sessions/
└── 2025/
    └── 10/
        └── 20/
            └── rollout-2025-10-20T14-58-30-019a0221-064c-7cd3-aad2-dffde6bbffba.jsonl
```

- Sessions organized by date hierarchy: `YYYY/MM/DD/`
- Filename format: `rollout-<timestamp>-<uuid>.jsonl`
- UUID extracted with regex: `([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`

### Session ID Matching
```powershell
# Input: bffba
# Matches: *bffba (suffix match)
# Resolves to: 019a0221-064c-7cd3-aad2-dffde6bbffba
# Runs: codex resume 019a0221-064c-7cd3-aad2-dffde6bbffba
```

---

## 🚀 Recommended Usage

### Windows Users
```powershell
# Use installed launcher
codex-container

# Or direct script
.\scripts\codex_container.ps1
```

### Mac/Linux Users
```bash
# Use shell script (faster, native)
./scripts/codex_container.sh

# Or PowerShell (more features)
pwsh ./scripts/codex_container.ps1
```

---

## 📋 Todo: Sync Features to Shell Script

**Missing in `codex_container.sh`:**
- [ ] Session management (`--session-id` parameter)
- [ ] Recent sessions listing
- [ ] Session ID resolution (partial matching)
- [ ] Transcription service URL configuration
- [ ] Platform-aware help text

**Consideration:**
- Shell script doesn't need runner installation (users typically add scripts/ to PATH manually)
- Session listing could use `jq` for JSON parsing
- Partial ID matching is straightforward with `grep -E`

---

## 🛠️ Line Ending Fixes

Created `scripts/fix_line_endings.ps1` to convert CRLF → LF for Unix compatibility.

**Usage:**
```powershell
# Fix all .sh files in scripts/
.\scripts\fix_line_endings.ps1

# Fix specific file
.\scripts\fix_line_endings.ps1 -Path codex_container.sh

# Recursive fix
.\scripts\fix_line_endings.ps1 -Recursive
```

**Fixed files:**
- cleanup_codex.sh
- codex_container.sh
- codex_entry.sh
- init_firewall.sh
- install_mcp_servers.sh

---

## 📊 Feature Matrix

| Feature | .ps1 | .sh |
|---------|------|-----|
| Core Actions | ✅ | ✅ |
| Configuration | ✅ | ✅ |
| Gateway Server | ✅ | ✅ |
| File Monitoring | ✅ | ✅ |
| Session Resume | ✅ | ❌ |
| Recent Sessions List | ✅ | ❌ |
| Partial ID Match | ✅ | ❌ |
| Transcription URL | ✅ | ❌ |
| Runner Install | ✅ | N/A |
| Cross-Platform | ✅ | ✅ |

---

## 🎯 Key Improvements from This Session

1. **Session Discovery** - No more guessing UUIDs, see recent conversations
2. **Short IDs** - Type 5 chars instead of 36-char UUID
3. **Preview Text** - Remember what each session was about
4. **Platform Awareness** - Correct commands shown for your OS
5. **Line Ending Fix** - Shell scripts now work on Mac without errors
6. **Transcription Config** - Can point to custom service endpoint

All improvements are permanent and committed to the repository! 🎉
