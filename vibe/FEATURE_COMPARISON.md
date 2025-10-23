# Codex Container Script Feature Comparison

## PowerShell Script Features (codex_container.ps1)

### Parameters & Modes
- [x] `-Install` - Install runner on PATH
- [x] `-Login` - Authenticate with Anthropic
- [x] `-Run` - Run Codex with arguments
- [x] `-Serve` - Start gateway server
- [x] `-Watch` / `-WatchPath` - File watcher mode (legacy)
- [x] `-Monitor` / `-MonitorPrompt` - **Monitor mode with session persistence**
- [x] `-Exec` - Execute in existing session
- [x] `-Shell` - Interactive shell
- [x] `-Push` - Push image to registry
- [x] `-SessionId` - Resume specific session
- [x] `-ListSessions` - List recent sessions

### Monitor Mode Features (PowerShell ONLY)
- [x] **Session Persistence** - Stores session ID in `.codex-monitor-session`
- [x] **Session Resume** - Automatically resumes previous session
- [x] **Get-MonitorSession()** - Retrieves saved session ID
- [x] **Set-MonitorSession()** - Saves session ID for continuity
- [x] **Optimized Prompts** - Only sends full MONITOR.md on first event
- [x] **Event Details Only** - Subsequent events send minimal payload
- [x] **Session Logging** - Logs session creation and resumption

### Docker Configuration
- [x] Network configuration: `--network codex-container_default`
- [x] Host.docker.internal mapping
- [x] GPU support detection
- [x] Volume mounting for workspace and codex-home

### Authentication
- [x] Automatic authentication check
- [x] Session validation
- [x] Recent sessions listing
- [x] Silent mode for JSON output

## Bash Script Features (codex_container.sh)

### Parameters & Modes
- [x] `--install` - Install runner on PATH  
- [x] `--login` - Authenticate with Anthropic
- [x] `--run` - Run Codex with arguments
- [x] `--serve` - Start gateway server
- [x] `--watch` / `--watch-path` - File watcher mode (legacy)
- [x] `--monitor` / `--monitor-prompt` - Basic monitor mode
- [x] `--exec` - Execute in existing session
- [x] `--shell` - Interactive shell
- [x] `--push` - Push image to registry
- [ ] `--session-id` - Resume specific session (EXISTS but not monitor-integrated)
- [x] `--list-sessions` - List recent sessions

### Monitor Mode Features (Bash - MISSING)
- [ ] **Session Persistence** - NOT IMPLEMENTED
- [ ] **Session Resume** - NOT IMPLEMENTED  
- [ ] **get_monitor_session()** - NOT IMPLEMENTED
- [ ] **set_monitor_session()** - NOT IMPLEMENTED
- [ ] **Optimized Prompts** - Sends full prompt every time
- [ ] **Event Details Only** - NOT IMPLEMENTED
- [ ] **Session Logging** - Basic logging only

### Docker Configuration
- [x] Network configuration: `--network codex-container_default`
- [x] Host.docker.internal mapping
- [x] GPU support detection
- [x] Volume mounting for workspace and codex-home

### Authentication
- [x] Automatic authentication check
- [x] Session validation
- [x] Recent sessions listing
- [ ] Silent mode for JSON output (partial)

## Summary - What Bash Needs

### Critical Missing Features
1. **Monitor Session Persistence**
   - Add `.codex-monitor-session` file support
   - Implement `get_monitor_session()` function
   - Implement `set_monitor_session()` function
   - Resume logic in monitor mode

2. **Optimized Monitor Prompts**
   - Check if session exists before reading MONITOR.md
   - Send only event details when resuming
   - Reduce token usage on subsequent events

3. **Monitor Session Logging**
   - Log session resumption vs new session
   - Track session continuity

### Nice-to-Have Improvements
- Session ID integration with monitor mode
- Better error handling in monitor loop
- Debug logging parity with PowerShell

## Priority Order for Bash Updates

1. **HIGH**: Add session persistence functions
2. **HIGH**: Implement session resume logic
3. **HIGH**: Optimize prompt payload based on session state
4. **MEDIUM**: Add session logging
5. **LOW**: Silent mode improvements
