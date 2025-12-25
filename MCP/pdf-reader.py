#!/usr/bin/env python3
"""
MCP: pdf-reader

Utilities for downloading PDFs and rendering selected pages to images.
Designed to feed Claude vision with page images.
"""

from __future__ import annotations

import base64
import os
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import fitz  # PyMuPDF

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pdf-reader")


def _safe_filename(url: str) -> str:
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or "download.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _dpi_to_scale(dpi: int) -> float:
    return max(72, dpi) / 72.0


@mcp.tool()
async def download_pdf(url: str, dest_dir: str = "./pdf", filename: Optional[str] = None) -> Dict[str, object]:
    """
    Download a PDF from a URL to a local directory.

    Args:
        url: PDF URL
        dest_dir: Directory to save the PDF
        filename: Optional override for the saved filename
    """
    if not url:
        return {"success": False, "error": "url_required"}

    dest = Path(dest_dir)
    _ensure_dir(dest)
    name = filename or _safe_filename(url)
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    out_path = dest / name

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=60) as resp:
                if resp.status != 200:
                    return {"success": False, "status": resp.status, "error": "download_failed"}
                data = await resp.read()
        out_path.write_bytes(data)
        return {
            "success": True,
            "path": str(out_path),
            "bytes": len(data),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_pdf_pages(pdf_path: str) -> Dict[str, object]:
    """
    Return basic metadata about a PDF and its page count.
    """
    path = Path(pdf_path)
    if not path.exists():
        return {"success": False, "error": "file_not_found", "path": str(path)}

    try:
        doc = fitz.open(path)
        page_count = doc.page_count
        doc.close()
        return {
            "success": True,
            "path": str(path),
            "pages": page_count,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "path": str(path)}


@mcp.tool()
async def split_pdf_pages(
    pdf_path: str,
    pages: List[int],
    output_dir: str = "./pdf/pages",
    dpi: int = 200,
    image_format: str = "png",
) -> Dict[str, object]:
    """
    Render selected PDF pages to images.

    Args:
        pdf_path: Path to PDF
        pages: 1-based page numbers to render
        output_dir: Directory to write page images
        dpi: Render DPI (default 200)
        image_format: "png" or "jpg"
    """
    path = Path(pdf_path)
    if not path.exists():
        return {"success": False, "error": "file_not_found", "path": str(path)}
    if not pages:
        return {"success": False, "error": "pages_required"}

    out_dir = Path(output_dir)
    _ensure_dir(out_dir)
    fmt = image_format.lower().strip(".")
    if fmt not in {"png", "jpg", "jpeg"}:
        return {"success": False, "error": "invalid_image_format"}

    try:
        doc = fitz.open(path)
        scale = _dpi_to_scale(dpi)
        matrix = fitz.Matrix(scale, scale)
        results = []
        for page_num in pages:
            if page_num < 1 or page_num > doc.page_count:
                results.append({
                    "page": page_num,
                    "success": False,
                    "error": "page_out_of_range",
                })
                continue
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out_name = f"{path.stem}_p{page_num}.{fmt}"
            out_path = out_dir / out_name
            pix.save(str(out_path))
            results.append({
                "page": page_num,
                "success": True,
                "path": str(out_path),
                "bytes": out_path.stat().st_size,
            })
        doc.close()
        return {
            "success": True,
            "pdf_path": str(path),
            "output_dir": str(out_dir),
            "pages_requested": pages,
            "results": results,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "path": str(path)}


if __name__ == "__main__":
    mcp.run()
