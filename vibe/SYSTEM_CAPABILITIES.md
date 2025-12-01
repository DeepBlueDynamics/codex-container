# Codex Container System Capabilities

## Core Architecture

**Autonomous AI agent platform** running OpenAI Codex CLI in Docker with **135 specialized tools**, GPU acceleration, and multi-agent orchestration.

---

## Three Operating Modes

### 1. **Terminal Mode** (Interactive/One-shot)
Execute commands directly or maintain conversational sessions:
```powershell
codex-container --exec "analyze this codebase"
codex-container --session-id abc12  # Resume conversation
```
- Session persistence across runs
- Full MCP tool access
- Scripting/automation support

### 2. **API Mode** (HTTP Gateway)
RESTful endpoint for external integration:
```powershell
codex-container --serve --gateway-port 4000
```
- `POST /completion` - Submit tasks
- `GET /health` - Service status
- Language-agnostic client support

### 3. **Monitor Mode** (Event-Driven Autonomous Agent)
**This is the killer feature** - agents that respond to events automatically:

#### File System Events
Watches directories and triggers on file changes:
```powershell
codex-container --monitor --watch-path ./vhf_monitor
```
- Detects new files, modifications, moves
- Template-driven prompts with variable substitution
- Session continuity across events

#### Scheduled Triggers (NEW - 135 tools)
Time-based automation with cron-like scheduling:
- **Daily**: Fire at specific time in any timezone
- **Interval**: Every N minutes
- **Once**: Specific datetime execution
- **Self-modifying**: Agents create their own schedules
- **Fire on reload**: Immediate execution when created

**Example**: Agent monitoring VHF radio creates hourly weather checks for itself:
```python
create_trigger(
    watch_path="/workspace/vhf_monitor",
    title="Hourly Weather Check",
    schedule_mode="interval",
    interval_minutes=60,
    prompt_text="Check NOAA marine forecast and log summary",
    tags=["fire_on_reload"]  # Runs immediately + every hour
)
```

---

## Tool Categories (135 Total)

### AI Orchestration & Multi-Agent Communication
- **Agent Chat**: `check_with_agent`, `chat_with_context`, `agent_to_agent`
  - Specialized agents with different roles/expertise
  - Inter-agent consultation and collaboration
  - Claude-powered decision making
- **Task Planning**: `get_next_step`
  - Stateless instructor pattern
  - Adaptive multi-step workflows
  - Returns next action based on progress
- **Tool Discovery**: `recommend_tool`, `list_available_tools`
  - Claude analyzes tasks and recommends tools
  - Automatic tool selection
- **Scheduling**: 7 trigger management tools
  - Create/update/delete/toggle triggers
  - Persistent state across restarts

### File Operations (gnosis-files-*)
- **Basic**: read, write, stat, exists, delete, copy, move
- **Advanced**: diff, backup, patch, restore, versioning
- **Search**: `file_search_content`, `file_find_by_name`, `file_tree`, `file_find_recent`
  - Optimized grep-like content search
  - Skip common directories (.git, node_modules)
  - File size limits to prevent timeouts

### Web & Search
- **Wraith Integration**: Production web scraper
  - `crawl_url`, `crawl_batch` - Markdown conversion
  - JavaScript rendering support
  - Screenshot capture
- **SerpAPI**: Google search with page fetching
  - `google_search`, `google_search_markdown`
  - Fetch top K results automatically

### Cloud Integrations
- **Google Calendar**: Events, creation, updates, deletion
- **Gmail**: Send, search, threads, drafts, labels
- **Google Drive**: Upload, download, share, search
- **Slack**: Messages, files, channels, users

### Maritime & Navigation (Specialized Domain)
- **VHF Radio Control**: Full SDR automation
  - Monitor frequencies
  - Auto-record transmissions
  - Queue for transcription
- **NOAA Marine**: Official weather/warnings
- **OpenCPN**: Chart plotting integration
- **Radio Networks**: Frequency coordination

### GPU-Accelerated Services
- **Whisper Transcription**:
  - OpenAI Whisper large-v3 stays loaded in VRAM
  - ~10x faster with CUDA (RTX 3080: 1 min audio in 5-10 sec)
  - HTTP API with async job queue
  - Pre-cached 3GB model in container
  - Formatted transmission-style reports

### Communication & Collaboration
- **Slack**: Full messaging, file uploads
- **Human Interaction**: `talk_to_human`, `report_to_supervisor`
- **Sticky Notes**: Persistent agent memory

### Utilities
- **Time Operations**: Scheduling, timezone conversion
- **Log Analysis**: Tail, filter by level, search
- **Water Cooler**: Process coordination primitives
- **Monitor Status**: Real-time process inspection

---

## Key Differentiators

### 1. **Self-Modifying Agents**
Agents can reprogram themselves:
```python
# Agent realizes it needs periodic checks
create_trigger(
    title="Check for stuck processes",
    schedule_mode="interval",
    interval_minutes=15,
    prompt_text="List processes, kill any stuck for >1hr"
)
```

### 2. **Hybrid Event Model**
File events + time events in unified queue:
- VHF recording detected → transcribe immediately
- Every hour → check weather
- New transcript → analyze for distress calls
- Daily at 9am → send summary report

### 3. **Session Continuity**
Monitor maintains conversation across:
- Container restarts
- File events
- Scheduled triggers
- Mixed event types

### 4. **Template-Driven Prompts**
`MONITOR.md` with variable substitution:
```markdown
## Event: {{trigger_title}}
Fired at: {{now_local}}
Session: {{session_id}}

Check marine weather for coordinates...
```

### 5. **Persistent Configuration**
Everything stored in workspace (survives restarts):
- `.codex-monitor-triggers.json` - Scheduled tasks
- `.codex-monitor-session` - Active session ID
- Trigger state includes `last_fired` timestamps

### 6. **Detailed Observability**
Startup logging shows full trigger state:
```
[schedule] Loaded 3 trigger(s) from .codex-monitor-triggers.json
  [✓ enabled] 'Weather Check' (interval: every 60 min) - next: 2025-11-05 15:00:00 UTC
  [✓ enabled] 'Daily Report' (daily: 09:00 EST) - next: 2025-11-06 09:00:00 EST
  [✗ disabled] 'Test' (once: at ...) - next: never
[schedule] Summary: 2 enabled, 1 disabled
```

---

## Real-World Use Case: VHF Monitor

**The system was built for this**:

1. **SDR records VHF transmissions** → saves WAV files
2. **File monitor detects new WAV** → queues transcription
3. **GPU transcribes in <10 seconds** → saves TXT file
4. **Agent reads transcript** → analyzes for:
   - Vessel names/callsigns
   - Distress calls
   - Weather reports
   - Coordinates
5. **Agent reports to supervisor** via Slack
6. **Hourly scheduled trigger** → checks NOAA for conditions
7. **Daily 9am trigger** → summarizes 24hr traffic

All autonomous. All event-driven. Self-scheduling. Session-persistent.

---

## Platform Features

- **Docker-based**: Reproducible, isolated, portable
- **Cross-platform**: Windows/macOS/Linux (PowerShell + Bash scripts)
- **MCP Framework**: FastMCP for reliable async tool execution
- **Git Integration**: Works in repos, handles commits/PRs
- **Sandbox Modes**: read-only, workspace-write, full-access
- **Approval Policies**: untrusted, on-failure, never, on-request

---

## Architecture Layers

```
┌─────────────────────────────────────────────────┐
│           User Interface Layer                  │
│  PowerShell/Bash Scripts │ HTTP API │ CLI      │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│         Docker Container Layer                  │
│  ┌──────────────────────────────────────────┐  │
│  │   Codex CLI (Node.js)                    │  │
│  │   - Session Management                   │  │
│  │   - Model Communication                  │  │
│  │   - Tool Execution                       │  │
│  └──────────────┬───────────────────────────┘  │
│                 │                               │
│  ┌──────────────▼───────────────────────────┐  │
│  │   MCP Tool Runtime (Python)              │  │
│  │   - 135 FastMCP Tools                    │  │
│  │   - Async Execution                      │  │
│  │   - Environment Isolation                │  │
│  └──────────────┬───────────────────────────┘  │
└─────────────────┼───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│        Monitor Layer (Python)                   │
│  ┌─────────────────┐  ┌────────────────────┐   │
│  │ File Watcher    │  │ Scheduler Thread   │   │
│  │ (watchdog)      │  │ (threading)        │   │
│  └────────┬────────┘  └────────┬───────────┘   │
│           │                    │               │
│           └────────┬───────────┘               │
│                    ▼                           │
│         ┌──────────────────────┐               │
│         │  Event Queue         │               │
│         │  - File events       │               │
│         │  - Trigger events    │               │
│         └──────────┬───────────┘               │
│                    ▼                           │
│         ┌──────────────────────┐               │
│         │  Codex Executor      │               │
│         │  Resume/Exec calls   │               │
│         └──────────────────────┘               │
└─────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│         External Services                       │
│  - GPU Transcription (Whisper)                  │
│  - Wraith Web Scraper                           │
│  - NOAA Weather API                             │
│  - Google Workspace APIs                        │
│  - Slack API                                    │
│  - SerpAPI                                      │
└─────────────────────────────────────────────────┘
```

---

## Technical Innovations

### Event-Driven Agent Pattern
Unlike traditional chatbots that wait for user input, this system enables **reactive autonomous agents**:
- Agents sleep until events occur
- Events can be external (files) or internal (time)
- Agents maintain context across events
- Multiple event types processed in unified workflow

### Stateless Instructor Pattern
AI-powered task planning without brittle state machines:
- Agent asks: "What should I do next?"
- Instructor responds with actionable step
- Agent executes and reports back
- Instructor adapts plan based on actual results
- No pre-programmed workflows - Claude figures it out

### Self-Modifying Agent Loop
Agents that evolve their own behavior:
1. Agent monitors VHF radio
2. Notices missed transmissions during sleep hours
3. Creates trigger: "Check for missed recordings at 6am daily"
4. Now automatically handles overnight traffic
5. Agent improved itself without human intervention

### Hybrid Synchronization
File events and time events in single processing queue:
- Both trigger same Codex session
- Session maintains context across event types
- "I just transcribed recording X, now my hourly weather check fired, I can correlate them"
- Unified conversation spanning multiple event sources

---

## Performance Characteristics

### Monitor Responsiveness
- **File detection**: <1 second (watchdog polling)
- **Trigger precision**: ±1 second from scheduled time
- **Queue processing**: Sequential, one Codex call at a time
- **Config reload**: Immediate on file change

### Transcription Performance
- **GPU (RTX 3080)**: 1 min audio → 5-10 sec
- **CPU fallback**: 1 min audio → 60-120 sec
- **Model loading**: 0 sec (kept in VRAM)
- **Concurrent jobs**: Queue-based, unlimited submissions

### Tool Execution
- **MCP overhead**: ~10-50ms per tool call
- **FastMCP async**: Non-blocking I/O
- **Python venv**: Isolated, PEP-668 compliant
- **Error isolation**: Tool crashes don't kill agent

---

## Configuration Files

### `.codex-monitor-triggers.json`
```json
{
  "version": 1,
  "updated_at": "2025-11-05T20:00:00Z",
  "triggers": [
    {
      "id": "abc123...",
      "title": "Hourly Weather",
      "description": "Check marine forecast",
      "schedule": {
        "mode": "interval",
        "interval_minutes": 60,
        "timezone": "UTC"
      },
      "prompt_text": "Check NOAA forecast for 25.77N, -80.19W",
      "enabled": true,
      "tags": ["weather"],
      "created_at": "2025-11-05T12:00:00Z",
      "created_by": {"id": "agent", "name": "Alpha India"},
      "last_fired": "2025-11-05T20:00:00Z"
    }
  ]
}
```

### `MONITOR.md` (Template)
```markdown
You are Alpha India, monitoring VHF maritime traffic.

## EVENT: {{trigger_title}}

**Fired**: {{now_local}} ({{timezone}})
**Session**: {{session_id}}
**Watch Root**: {{watch_root}}

### Your Task
{{trigger_description}}

### Available Tools
- list_triggers(watch_path)
- create_trigger(...)
- get_marine_forecast(lat, lon)
- transcribe_wav(filename)

Execute the scheduled task and report results.
```

### `.codex-monitor-session`
```
019a54c3-255a-7dd3-90ed-78bdf971169e
```
Single line file containing active session UUID for monitor continuity.

---

## Security Considerations

### Sandbox Modes
- **read-only**: Agent can read workspace, execute safe commands
- **workspace-write**: Agent can modify workspace, no system access
- **danger-full-access**: Full system access (use with extreme caution)

### Approval Policies
- **untrusted**: Human approves non-whitelisted commands
- **on-failure**: Human approves only failed commands
- **on-request**: Agent decides when to ask
- **never**: Fully autonomous (dangerous)

### Environment Isolation
- Docker container boundary
- Python venv for MCP tools
- No host network access by default
- Volume mounts are explicit

### Secrets Management
- Environment variables passed through Docker
- `.wraithenv`, `.serpapi.env` for API keys
- Not committed to git
- Container-only visibility

---

## Development Workflow

### Adding New MCP Tools
1. Create `MCP/my-tool.py` with FastMCP framework
2. Run `codex-container -Install` to register
3. Tool available immediately to all agents

### Creating Monitor Agents
1. Write `MONITOR.md` with template variables
2. Place in watch directory
3. Start monitor: `codex-container --monitor --watch-path ./mydir`
4. Agent activates on file changes

### Adding Scheduled Tasks
Agent can create triggers at runtime:
```python
# Agent decides it needs periodic checks
create_trigger(
    watch_path="/workspace/data",
    title="Data validation",
    schedule_mode="daily",
    schedule_time="03:00",
    timezone_name="America/New_York",
    prompt_text="Validate data integrity and email results"
)
```

Or manually edit `.codex-monitor-triggers.json` and it reloads automatically.

---

## Future Capabilities

### Potential Extensions
- **Multi-agent collaboration**: Agents consulting each other via `agent_to_agent()`
- **Tool chaining**: `get_next_step()` orchestrating multi-tool workflows
- **Learning from history**: Analyzing session logs to improve prompts
- **Conditional triggers**: "Fire only if disk usage >90%"
- **Trigger dependencies**: "Run B only if A succeeded"
- **Result caching**: Avoid redundant expensive operations

### Already Possible (Just Not Implemented)
- Agent creates triggers for itself
- Agent disables failing triggers
- Agent adjusts interval based on activity
- Agent spawns sub-agents for specialized tasks
- Multi-tier agent hierarchies

---

This isn't just "ChatGPT with tools" - it's **infrastructure for autonomous agent systems** with scheduling, event processing, self-modification, and production-grade tool execution.

Thanks for the detailed rundown—I'll refer back here when validating monitor behavior or tool coverage. -Agent
