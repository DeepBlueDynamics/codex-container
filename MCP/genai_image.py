#!/usr/bin/env python3
"""
GenAI MCP server for Gemini text-to-image generation.

Wraps the Google GenAI client, exposes a tool that generates images from a prompt,
and optionally saves the output to disk for downstream workflows.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("genai-image")


def _get_client(api_key: Optional[str] = None) -> genai.Client:
    """Return a GenAI client using the provided key or GENAI_API_KEY env var."""
    key = api_key or os.environ.get("GENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "Missing GenAI API key. Set the GENAI_API_KEY environment variable "
            "or pass `api_key` explicitly."
        )
    return genai.Client(api_key=key)


def _content_type_extension(content_type: Optional[str]) -> str:
    """Simplistic map from MIME type to file extension."""
    if not content_type:
        return "png"
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
    }
    return mapping.get(content_type.lower(), "png")


@mcp.tool()
async def generate_image(
    prompt: str,
    model: str = "gemini-2.5-flash-image-preview",
    api_key: Optional[str] = None,
    output_dir: Optional[str] = None,
    save_prefix: str = "genai-image",
) -> Dict[str, Any]:
    """Generate an image with the Gemini text-to-image model.

    Args:
        prompt: Text prompt describing the desired image.
        model: GenAI model to invoke (defaults to `gemini-2.5-flash-image-preview`).
        api_key: Optional key that overrides the `GENAI_API_KEY` environment variable.
        output_dir: If provided, saves each image to this directory.
        save_prefix: Filename prefix when writing output files.

    Returns:
        Dict containing the prompt, model, and metadata for each generated image.
    """
    client = _get_client(api_key=api_key)

    response = client.models.generate_content(
        model=model,
        contents=[prompt],
    )

    saved_paths: List[str] = []
    metadata: List[Dict[str, Any]] = []

    for candidate_index, candidate in enumerate(response.candidates):
        for part_index, part in enumerate(candidate.content.parts):
            if not getattr(part, "inline_data", None):
                continue
            inline = part.inline_data
            data_bytes = inline.data
            content_type = getattr(inline, "content_type", None)
            ext = _content_type_extension(content_type)
            filename = f"{save_prefix}-{candidate_index}-{part_index}.{ext}"
            entry: Dict[str, Any] = {
                "candidate_index": candidate_index,
                "part_index": part_index,
                "content_type": content_type,
                "bytes": base64.b64encode(data_bytes).decode("ascii"),
            }

            if output_dir:
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)
                file_path = output_path / filename
                file_path.write_bytes(data_bytes)
                entry["saved_path"] = str(file_path.resolve())
                saved_paths.append(str(file_path.resolve()))

            metadata.append(entry)

    return {
        "success": True,
        "prompt": prompt,
        "model": model,
        "image_count": len(metadata),
        "images": metadata,
        "saved_paths": saved_paths,
    }


if __name__ == "__main__":
    mcp.run()
