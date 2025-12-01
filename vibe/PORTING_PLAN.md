# Porting gnosis-evolve tools into Codex MCP

## Research notes
1. Codex container MCP servers follow the FastMCP pattern (see `MCP/sample_tool.py`) and are installed by placing scripts inside `/workspace/MCP` so they can be registered during `--install`/`-Install` runs.
2. The Codex workflow uses `/workspace/.codex-mcp.config` + the default `MCP/.codex-mcp.config` to control which tools load, so each new script needs a distinct name, careful async tool definitions, and associated entries in the config file when ready for activation.
3. The README describes both how MCP servers are launched and how custom tools are scoped per workspace (`README.md:450`, `README.md:473`), which differs from the Claude-era repo that bundled its own tool discovery logic.

## Functionality to port
### Emoji translator
- Core requirement: extract emoji sequences, interpret them, and produce human-readable descriptions from crying-report text. The reference list in `/workspace/plan/gnosis_evolve_dependencies.txt:3` points at `semantic_storage_clean.py` for the original extraction logic. The new tool needs an MCP entry that accepts raw reports and returns `text`, `emoji_summary`, and optionally `alert_level` (e.g., crying emoji -> "urgent" summary).

### Fuzzy search & edit helpers
- The legacy fuzzy helpers in `file_diff_editor.py`, `file_diff_writer.py`, and `toolkami_enhanced_diff.py` (see `/workspace/plan/gnosis_evolve_dependencies.txt:5`) will guide new MCP utilities that let Codex locate approximate matches within files, produce context, and optionally perform replacements once the user approves them.

### Character/Iching/random generator
- The `iching_character_generator`, `iching_casting`, and `random_generator` functions from the older repo (noted in `/workspace/plan/gnosis_evolve_dependencies.txt:7`) supply personas, hexagram casts, and random seeds. These will be ported into new FastMCP tools that accept optional seeds/questions, return structured hexagram metadata, and optionally store generated characters for later retrieval (mirroring the `save_character_data` path from line 9 of the reference file).

## Next steps inside `/workspace/MCP`
1. Sketch each new MCP script file (`emoji_translator.py`, `fuzzy_character_search.py`, `iching_character.py`) with FastMCP server setup and minimal tool signatures.
2. Identify which helper data (hexagram tables, emotion lists, emoji mappings) can be copied or distilled from the older repo; create shared modules if needed.
3. Update `.codex-mcp.config` entries once the scripts are ready so Codex can load them.
4. Keep this plan and the dependency list near at hand for reference when reconstructing the logic without direct access to `gnosis-evolve`.
