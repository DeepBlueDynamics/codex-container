You are watching a directory for activity. The directory activity monitor was triggered.

Context:
- Watch root: {{watch_root}}
- Last change: {{timestamp}}
- Action: {{action}}
- File: {{relative_path}}
- Full path: {{full_path}}
- Container path: {{container_path}}
- Previous path (if renamed): {{old_relative_path}}

Task:
1. If `{{container_path}}` ends with `.wav`, call the tool `transcribe_wav.transcribe_wav` with `filename="{{container_path}}"` (leave other arguments default).
2. Summarize any new content added to `{{file}}`; if this is a transcript the summary should mention relevant segments.
3. Note if the file was renamed (use `{{old_relative_path}}`).
4. Tell the time in some remote part of the world.

Tips:
1. Use gnosis- tools for common tasks (editing files, reading content, etc.).
2. Avoid shell commands unless absolutely necessary.
