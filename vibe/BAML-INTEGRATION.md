# BAML Integration Brief

## Overview

This document outlines the integration of [BAML (Boundary ML)](https://docs.boundaryml.com) into the Codex Service Container to enable type-safe, structured outputs from LLMs alongside Codex's existing capabilities.

## What is BAML?

BAML is a domain-specific language for generating structured outputs from LLMs with:
- **Type-safe outputs** with full autocomplete support
- **Hot-reloading** development experience via VSCode playground
- **Multi-provider support** (OpenAI, Anthropic, Google, AWS Bedrock, Ollama, etc.)
- **State-of-the-art structured outputs** that outperform native provider implementations
- **Language agnostic** - generates clients for Python, TypeScript, Go, Ruby, and more

### Key Differentiator

BAML acts as "TSX/JSX for prompt engineering" - providing a proper abstraction layer for prompts instead of treating them as raw strings. This enables:
- Prompt testing without running full Python environments
- Version control for prompts as first-class code
- Type checking and validation at development time
- Reusable prompt components and templates

## Integration Architecture

### Current Codex Container Stack
```
┌─────────────────────────────────────┐
│   Codex CLI (@openai/codex)         │
│   - Agent framework                  │
│   - Tool execution                   │
│   - Natural language interface       │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│   MCP Server Layer (FastMCP)        │
│   - time-tool.py                     │
│   - google-calendar.py               │
│   - google-drive.py                  │
│   - google-gmail.py                  │
│   - gnosis-crawl.py                  │
│   - serpapi-search.py                │
└─────────────────────────────────────┘
```

### Proposed BAML Integration
```
┌─────────────────────────────────────┐
│   Codex CLI (@openai/codex)         │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│   MCP Server Layer                   │
│   ├─ Existing tools...               │
│   └─ baml-server.py (NEW)            │
│      ├─ baml_extract_structured()    │
│      ├─ baml_classify()              │
│      ├─ baml_parse_document()        │
│      └─ baml_query_with_schema()     │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│   BAML Runtime Layer                 │
│   ├─ BAML CLI (@boundaryml/baml)    │
│   ├─ BAML Projects (/opt/baml-ws)   │
│   └─ Generated Clients (Python)     │
└─────────────────────────────────────┘
```

## Implementation Options

### Option A: BAML MCP Server (Recommended)
**Pros:**
- Seamless integration with existing Codex workflow
- Accessible via natural language through Codex
- Reuses existing MCP infrastructure
- Can be selectively enabled/disabled

**Cons:**
- Adds complexity to MCP layer
- Requires BAML project management within container

**Use Cases:**
- Extract structured data from documents/emails
- Parse resumes, invoices, contracts
- Classify support tickets, sentiment analysis
- Transform unstructured logs into structured JSON

### Option B: Standalone BAML Gateway
**Pros:**
- Clean separation of concerns
- Can be used independently of Codex
- Easier to scale horizontally
- Direct HTTP API access

**Cons:**
- Requires separate service management
- Not directly accessible via Codex natural language
- Additional port management

**Use Cases:**
- External services need structured LLM outputs
- Building BAML-powered APIs
- Integration with non-Codex workflows

### Option C: Hybrid Approach
**Pros:**
- Best of both worlds
- Flexible deployment options
- Progressive adoption path

**Cons:**
- Most complex to maintain
- Potential for confusion about which to use

## Quick Start Implementation

### 1. Dockerfile Changes

Add BAML to the container:

```dockerfile
# After Codex CLI installation
ARG BAML_CLI_VERSION=latest
RUN npm install -g @boundaryml/baml@${BAML_CLI_VERSION} \
  && npm cache clean --force

# Add BAML Python client to MCP venv
RUN "$MCP_VENV/bin/pip" install --no-cache-dir \
    baml-py \
    pydantic
```

### 2. Create MCP Server

Place `baml-server.py` in the `MCP/` directory (see detailed implementation below).

### 3. Rebuild Container

```powershell
# Windows
./scripts/codex_container.ps1 -Install

# Linux/Mac
./scripts/codex_container.sh --install
```

### 4. Usage Examples

```bash
# Extract structured data
codex exec "Use BAML to extract contact info: John Doe, john@example.com, 555-1234"

# Parse documents
codex exec "Parse this resume with BAML" < candidate-resume.pdf

# Classify content
codex exec "Classify this support ticket using BAML: User cannot login"

# Schema-driven extraction
codex exec "Extract meeting details with BAML: Call with Sarah tomorrow at 2pm re: Q4 budget"
```

## Key Use Cases

### 1. Document Intelligence
```python
# Resume parsing
baml_parse_document(content=resume_text, output_type="resume")
# Returns: { name, email, phone, experience[], education[], skills[] }

# Invoice processing
baml_parse_document(content=invoice_pdf, output_type="invoice")
# Returns: { invoice_number, date, vendor, total, items[] }
```

### 2. Data Extraction
```python
# Extract entities from unstructured text
baml_extract_structured(
    prompt="Extract all dates, people, and locations",
    schema="class Entities { dates: string[], people: string[], locations: string[] }",
    input_text="Meeting with John in NYC on Jan 15th"
)
```

### 3. Classification & Routing
```python
# Ticket classification
baml_classify(
    text="Customer cannot access dashboard",
    categories=["bug", "feature_request", "support", "billing"]
)
# Returns: { category: "bug", confidence: 0.95 }
```

### 4. Structured Query Response
```python
# Database query generation from natural language
baml_query_with_schema(
    question="Show me all users who signed up last month",
    schema=User_schema,
    format="sql"
)
# Returns: valid SQL query
```

## Benefits

### For Codex Users
1. **Type Safety**: Guaranteed output structure, no more parsing brittle JSON
2. **Reliability**: Automatic retry logic and JSON repair built into BAML
3. **Flexibility**: Easy model switching (OpenAI → Anthropic → Ollama)
4. **Development Speed**: Test prompts in playground before deploying

### For Developers
1. **Version Control**: Prompts as code in `.baml` files
2. **Testing**: Unit test structured outputs like regular functions
3. **Documentation**: Schema serves as documentation
4. **Maintainability**: Refactor prompts without breaking consumers

### For the System
1. **Modular**: BAML handles structured outputs, Codex handles orchestration
2. **Scalable**: BAML projects are self-contained and cacheable
3. **Observable**: Built-in logging and token tracking
4. **Cost Efficient**: Prompt caching and optimized parsing

## Technical Considerations

### Storage
- BAML projects: `/opt/baml-workspace/`
- Generated clients: `<project>/baml_client/`
- Persistent across container restarts via volume mount

### Dependencies
- Node.js (already present)
- Python 3.9+ with venv (already present)
- BAML CLI via npm
- `baml-py` Python package
- `pydantic` for schema validation

### Performance
- BAML generation: ~1-2s per new function
- Cached generation: <100ms
- LLM call time: dependent on model
- Parsing overhead: <50ms

### Security
- API keys via environment variables
- Sandboxed execution within container
- No network access required for generation
- All code execution in isolated venv

## Migration Path

### Phase 1: Pilot (Week 1)
- Install BAML in container
- Create basic MCP server with 2-3 functions
- Test with simple extraction tasks
- Gather feedback from Codex usage

### Phase 2: Expansion (Week 2-3)
- Add document parsing templates
- Implement classification functions
- Create library of reusable BAML functions
- Document common patterns

### Phase 3: Optimization (Week 4+)
- Implement caching for frequent schemas
- Add monitoring and observability
- Optimize BAML project management
- Consider standalone gateway if needed

## Example MCP Server Skeleton

```python
#!/usr/bin/env python3
"""
BAML Integration Server (MCP)
Exposes BAML structured output capabilities to Codex CLI.
"""

from mcp.server.fastmcp import FastMCP
from pathlib import Path
import subprocess
import json

mcp = FastMCP("baml-server")

BAML_WORKSPACE = Path("/opt/baml-workspace")

@mcp.tool()
async def baml_extract_structured(
    prompt: str,
    schema: str,
    input_text: str,
    model: str = "gpt-4"
) -> dict:
    """Extract structured data using BAML."""
    # 1. Create BAML project
    # 2. Define function with schema
    # 3. Generate client code
    # 4. Execute and return result
    pass

@mcp.tool()
async def baml_classify(
    text: str,
    categories: list[str],
    model: str = "gpt-4"
) -> dict:
    """Classify text into categories."""
    pass

@mcp.tool()
async def baml_parse_document(
    content: str,
    output_type: str,
    model: str = "gpt-4"
) -> dict:
    """Parse common document types (resume, invoice, etc)."""
    pass

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

## Resources

- **BAML Documentation**: https://docs.boundaryml.com
- **BAML Playground**: https://promptfiddle.com
- **Example Projects**: https://github.com/boundaryml/baml-examples
- **VSCode Extension**: Install from marketplace for local development

## Next Steps

1. Review this brief with team
2. Decide on integration approach (MCP server vs Gateway vs Hybrid)
3. Create detailed implementation plan
4. Set up development environment with BAML VSCode extension
5. Build and test pilot MCP server
6. Document common patterns and use cases
7. Iterate based on real-world usage

## Questions & Considerations

- **Should we create a library of pre-built BAML functions?**
- **How do we handle BAML project lifecycle (create/cache/cleanup)?**
- **Do we want BAML functions versioned alongside Codex config?**
- **Should users be able to define custom BAML schemas via Codex?**
- **Do we need monitoring for BAML generation/execution performance?**

---

**Status**: Proposal  
**Owner**: TBD  
**Created**: 2025-01-17  
**Last Updated**: 2025-01-17
