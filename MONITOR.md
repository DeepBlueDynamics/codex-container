# File Monitor Template

This prompt is rendered by Codex Gateway when a watched file changes (or when a scheduled trigger fires). Available template fields:

**File events**
- `{{watch_root}}` – watch root inside the container
- `{{timestamp}}` – event time (ISO)
- `{{action}}` – create | modify | move | delete
- `{{relative_path}}` – path relative to watch root
- `{{full_path}}` – absolute host path (inside container namespace)
- `{{container_path}}` – container path you should use for tool calls
- `{{old_relative_path}}` – previous relative path (only for moves)

**Scheduled triggers** (if configured)
- `{{trigger_id}}`, `{{trigger_title}}`, `{{trigger_description}}`
- `{{now_iso}}`, `{{now_local}}`, `{{trigger_time}}`, `{{session_id}}`

## Task
1) Identify the event type and file.
2) If it is text, summarize key contents. If binary (audio, etc.), describe handling steps.
3) Keep it brief and exit.
