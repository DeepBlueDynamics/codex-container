#!/usr/bin/env python3
"""
MCP server: Personal search/index manager

Capabilities:
- save_url: log URLs (bookmark style) to JSONL
- save_page: log page content with optional embeddings (instructor-xl service/local; hash fallback)
- save_pdf_pages: index PDF pages (with page numbers) into the page index
- search_saved_urls: simple substring search over saved URLs/notes
- search_saved_pages: embedding search over saved pages
- count_saved_urls / count_saved_pages: quick counts without returning payloads

Defaults:
- URL log: temp/url_index.jsonl
- Page log: temp/page_index.jsonl
- Embedding service: INSTRUCTOR_SERVICE_URL env (default http://gnosis-instructor-service:8787/embed)

Notes:
- No crawling here; caller supplies text for pages.
- Uses API-key-less embeddings: instructor service or local InstructorEmbedding if present; otherwise hash embeddings.
"""

from __future__ import annotations

import json
import os
import string
from collections import Counter
from datetime import datetime
from hashlib import blake2b
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import urllib.request
import urllib.error
import urllib.parse

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("personal-search")

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None

# Embedding settings
INSTRUCTOR_SERVICE_URL = os.environ.get("INSTRUCTOR_SERVICE_URL", "http://gnosis-instructor-service:8787/embed")
GNOSIS_CRAWL_URL = os.environ.get("GNOSIS_CRAWL_BASE_URL", "http://gnosis-crawl:8080").rstrip("/")
_INSTRUCTOR_MODEL = None
_INSTRUCTOR_MODEL_NAME: Optional[str] = None
try:
    from InstructorEmbedding import INSTRUCTOR  # type: ignore
except Exception:
    INSTRUCTOR = None
    _INSTRUCTOR_IMPORT_ERROR = "InstructorEmbedding not available; using hash embeddings."
else:
    _INSTRUCTOR_IMPORT_ERROR = ""

STOPWORDS = {
    "the","a","an","and","or","if","else","of","to","in","for","on","with","at","by","from",
    "is","are","was","were","be","been","as","that","this","it","not","but","we","you","they",
    "he","she","them","their","our","your"
}


def _normalize_url(u: str) -> str:
    try:
        parsed = urlparse(u)
        if not parsed.scheme:
            return "http://" + u
        return u
    except Exception:
        return u


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    text = text.translate(str.maketrans({ch: " " for ch in string.punctuation}))
    raw = text.split()
    return [t for t in raw if t and t not in STOPWORDS and len(t) > 2]


def _hash_embed(text: str, dim: int = 64) -> List[float]:
    needed_bytes = max(4, dim // 8)
    h = blake2b(text.encode("utf-8"), digest_size=needed_bytes).digest()
    vec: List[float] = []
    for i in range(0, len(h), 2):
        v = int.from_bytes(h[i:i+2], "big", signed=False)
        vec.append((v / 65535.0) * 2 - 1)
    while len(vec) < dim:
        vec.append(0.0)
    return vec[:dim]


def _embedding_summary(vec: Optional[List[float]]) -> Optional[Dict[str, float]]:
    if not vec:
        return None
    n = len(vec)
    zero_count = sum(1 for v in vec if v == 0)
    mean = sum(vec) / n
    mean_abs = sum(abs(v) for v in vec) / n
    var = sum((v - mean) ** 2 for v in vec) / n
    std = var ** 0.5
    return {
        "length": float(n),
        "zero_count": float(zero_count),
        "zero_ratio": float(zero_count / n),
        "mean": float(mean),
        "std": float(std),
        "min": float(min(vec)),
        "max": float(max(vec)),
        "mean_abs": float(mean_abs),
    }


def _strip_embedding_fields(entry: Dict[str, Any]) -> Dict[str, Any]:
    if "embedding" not in entry:
        return entry
    vec = entry.get("embedding")
    entry = dict(entry)
    entry.pop("embedding", None)
    summary = _embedding_summary(vec if isinstance(vec, list) else None)
    if summary:
        entry["embedding_summary"] = summary
    return entry


def _crawl_markdown(url: str, timeout_seconds: int) -> str:
    payload = json.dumps({"url": url}).encode("utf-8")
    req = urllib.request.Request(
        f"{GNOSIS_CRAWL_URL}/api/markdown",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
    try:
        data = json.loads(body)
        return data.get("markdown", "") or ""
    except Exception:
        return ""


def _embed_text(text: str, backend: str, model_name: str, timeout: int, warnings: List[str]) -> List[float]:
    global _INSTRUCTOR_MODEL, _INSTRUCTOR_MODEL_NAME
    if backend == "instructor-xl":
        svc = os.environ.get("INSTRUCTOR_SERVICE_URL", INSTRUCTOR_SERVICE_URL)
        if svc:
            try:
                payload = {
                    "texts": [text],
                    "instruction": "Represent the text for semantic search",
                    "normalize": True,
                }
                req = urllib.request.Request(
                    svc,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    embeds = body.get("embeddings") or []
                    if embeds:
                        return embeds[0]
                    warnings.append("Instructor service returned no embeddings; falling back to hash.")
            except Exception as e:
                warnings.append(f"instructor service failed ({e}); falling back to local/hash.")
        if INSTRUCTOR is None:
            if _INSTRUCTOR_IMPORT_ERROR:
                warnings.append(_INSTRUCTOR_IMPORT_ERROR)
            return _hash_embed(text)
        try:
            if _INSTRUCTOR_MODEL is None or _INSTRUCTOR_MODEL_NAME != model_name:
                _INSTRUCTOR_MODEL = INSTRUCTOR(model_name)
                _INSTRUCTOR_MODEL_NAME = model_name
            vec = _INSTRUCTOR_MODEL.encode(
                [["Represent the text for semantic search", text]],
                normalize_embeddings=True,
            )
            return vec[0].tolist()
        except Exception as e:
            warnings.append(f"instructor-xl local failed ({e}); using hash.")
            return _hash_embed(text)
    # default hash
    return _hash_embed(text)


@mcp.tool()
def save_url(
    url: str,
    note: Optional[str] = None,
    log_path: str = "temp/url_index.jsonl",
) -> Dict[str, Any]:
    """Save a URL bookmark entry to JSONL."""
    entry = {
        "url": _normalize_url(url),
        "note": note,
        "timestamp": datetime.utcnow().isoformat(),
    }
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return {
        "entry": entry,
        "log_path": str(p),
        "hint": "To make this URL searchable by content, call save_page (or save_pdf_pages for PDFs).",
    }


@mcp.tool()
def save_page(
    url: str,
    text: str,
    note: Optional[str] = None,
    log_path: str = "temp/page_index.jsonl",
    max_store_chars: int = 8000,
    embed: bool = False,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    """Save a page (url + content) with optional embeddings to JSONL."""
    warnings: List[str] = []
    snippet = text[:max_store_chars]
    entry: Dict[str, Any] = {
        "url": _normalize_url(url),
        "note": note,
        "timestamp": datetime.utcnow().isoformat(),
        "content": snippet,
        "content_len": len(text),
        "content_hash": blake2b(text.encode("utf-8"), digest_size=8).hexdigest(),
    }
    if embed:
        entry["embedding"] = _embed_text(f"{url} {note or ''} {snippet}", embedding_backend, embedding_model, timeout_seconds, warnings)
        entry["embedding_backend"] = entry.get("embedding_backend", embedding_backend)
    if warnings:
        entry["warnings"] = warnings
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return {"entry": _strip_embedding_fields(entry), "log_path": str(p)}


@mcp.tool()
def save_crawled_page(
    url: str,
    note: Optional[str] = None,
    log_path: str = "temp/page_index.jsonl",
    max_store_chars: int = 8000,
    embed: bool = False,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Crawl a URL via gnosis-crawl and save content to the page index."""
    try:
        markdown = _crawl_markdown(url, timeout_seconds)
    except Exception as e:
        return {"success": False, "error": f"crawl_failed: {e}", "url": url}
    if not markdown:
        return {"success": False, "error": "empty_crawl_result", "url": url}
    return save_page(
        url=url,
        text=markdown,
        note=note,
        log_path=log_path,
        max_store_chars=max_store_chars,
        embed=embed,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        timeout_seconds=timeout_seconds,
    )


def _get_pdf_page_count(pdf_path: str) -> int:
    if fitz is not None:
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    if PdfReader is not None:
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    raise RuntimeError("No PDF reader available; install PyMuPDF or pypdf.")


def _extract_pdf_text(pdf_path: str, page_number: int) -> str:
    if fitz is not None:
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(page_number - 1)
            return page.get_text("text") or ""
    if PdfReader is not None:
        reader = PdfReader(pdf_path)
        page = reader.pages[page_number - 1]
        return page.extract_text() or ""
    raise RuntimeError("No PDF reader available; install PyMuPDF or pypdf.")


@mcp.tool()
def save_pdf_pages(
    pdf_path: str,
    source_url: Optional[str] = None,
    pages: Optional[List[int]] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    note: Optional[str] = None,
    log_path: str = "temp/page_index.jsonl",
    max_store_chars: int = 8000,
    embed: bool = False,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    """Index one or more PDF pages into the page index with optional embeddings."""
    warnings: List[str] = []
    p = Path(pdf_path).expanduser()
    if not p.exists():
        candidate = Path("/workspace/pdf") / p
        p = candidate
    p = p.resolve()
    if not p.exists():
        return {"success": False, "error": "pdf_not_found", "pdf_path": str(p)}

    try:
        page_count = _get_pdf_page_count(str(p))
    except Exception as e:
        return {"success": False, "error": f"pdf_read_failed: {e}", "pdf_path": str(p)}

    if pages:
        page_numbers = sorted(set(int(n) for n in pages))
    else:
        start = int(start_page) if start_page else 1
        end = int(end_page) if end_page else page_count
        page_numbers = list(range(start, end + 1))

    valid_pages = []
    for n in page_numbers:
        if 1 <= n <= page_count:
            valid_pages.append(n)
        else:
            warnings.append(f"page_out_of_range:{n}")

    if not valid_pages:
        return {
            "success": False,
            "error": "no_valid_pages",
            "pdf_path": str(p),
            "page_count": page_count,
            "warnings": warnings,
        }

    entries: List[Dict[str, Any]] = []
    index_path = Path(log_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    for n in valid_pages:
        try:
            text = _extract_pdf_text(str(p), n)
        except Exception as e:
            warnings.append(f"page_extract_failed:{n}:{e}")
            continue

        snippet = text[:max_store_chars]
        url = source_url or f"pdf://{p}"
        if source_url:
            url = f"{source_url}#page={n}"
        else:
            url = f"pdf://{p}#page={n}"

        entry: Dict[str, Any] = {
            "url": _normalize_url(url),
            "note": note,
            "timestamp": datetime.utcnow().isoformat(),
            "content": snippet,
            "content_len": len(text),
            "content_hash": blake2b(text.encode("utf-8"), digest_size=8).hexdigest(),
            "pdf_path": str(p),
            "pdf_page": n,
            "pdf_page_count": page_count,
        }

        if embed:
            entry["embedding"] = _embed_text(
                f"{url} {note or ''} {snippet}",
                embedding_backend,
                embedding_model,
                timeout_seconds,
                warnings,
            )
            entry["embedding_backend"] = entry.get("embedding_backend", embedding_backend)

        entries.append(entry)
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")

    result: Dict[str, Any] = {
        "success": True,
        "pdf_path": str(p),
        "page_count": page_count,
        "pages_indexed": [e["pdf_page"] for e in entries],
        "log_path": str(index_path),
    }
    if embed:
        summaries = []
        for e in entries:
            summary = _embedding_summary(e.get("embedding") if isinstance(e.get("embedding"), list) else None)
            if summary:
                summaries.append({"page": e["pdf_page"], "embedding_summary": summary})
        if summaries:
            result["embedding_summaries"] = summaries
    if warnings:
        result["warnings"] = warnings
    return result


@mcp.tool()
def search_saved_urls(
    query: str,
    log_path: str = "temp/url_index.jsonl",
    top_k: int = 10,
) -> Dict[str, Any]:
    """Simple substring search over saved URLs/notes."""
    p = Path(log_path)
    if not p.exists():
        return {"matches": [], "metadata": {"log_path": str(p), "error": "log_not_found"}}
    q = query.lower()
    matches: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            hay = (entry.get("url", "") + " " + (entry.get("note") or "")).lower()
            if q in hay:
                matches.append(entry)
    return {
        "matches": matches[:top_k],
        "metadata": {
            "log_path": str(p),
            "count": len(matches),
            "hint": "URL bookmarks are not content-indexed; consider crawling and saving pages with save_page/save_pdf_pages.",
        },
    }


@mcp.tool()
def search_saved_pages(
    query: str,
    log_path: str = "temp/page_index.jsonl",
    top_k: int = 10,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
    max_query_chars: int = 2000,
) -> Dict[str, Any]:
    """Search saved pages by semantic similarity (embeds on the fly if missing)."""
    p = Path(log_path)
    if not p.exists():
        return {"matches": [], "metadata": {"log_path": str(p), "error": "log_not_found"}}
    warnings: List[str] = []
    q_embed = _embed_text(query[:max_query_chars], embedding_backend, embedding_model, 20, warnings)
    matches: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if "embedding" in entry:
                e_embed = entry["embedding"]
            else:
                text_blob = " ".join(
                    filter(None, [entry.get("url", ""), entry.get("note") or "", (entry.get("content") or "")[:max_query_chars]])
                )
                e_embed = _embed_text(text_blob, embedding_backend, embedding_model, 20, warnings)
            # cosine similarity
            a = q_embed
            b = e_embed
            if not a or not b or len(a) != len(b):
                score = 0.0
            else:
                dot = sum(x * y for x, y in zip(a, b))
                na = sum(x * x for x in a) ** 0.5
                nb = sum(y * y for y in b) ** 0.5
                score = dot / (na * nb) if na and nb else 0.0
            matches.append({"score": score, "entry": entry})
    matches = sorted(matches, key=lambda x: x["score"], reverse=True)[:top_k]
    matches = [{"score": m["score"], "entry": _strip_embedding_fields(m["entry"])} for m in matches]
    return {
        "matches": matches,
        "metadata": {
            "log_path": str(p),
            "embedding_backend_requested": embedding_backend,
            "embedding_backend_effective": embedding_backend if not warnings else f"{embedding_backend} (fallback=hash)",
            "embedding_model": embedding_model,
            "warnings": warnings,
            "hint": "If results are thin, check URL bookmarks or crawl/summarize URLs with save_page/save_pdf_pages to index content.",
        },
    }


@mcp.tool()
def count_saved_urls(log_path: str = "temp/url_index.jsonl") -> Dict[str, Any]:
    """Return count of saved URLs without returning entries."""
    p = Path(log_path)
    if not p.exists():
        return {"count": 0, "log_path": str(p)}
    n = sum(1 for _ in p.open("r", encoding="utf-8"))
    return {"count": n, "log_path": str(p)}


@mcp.tool()
def count_saved_pages(log_path: str = "temp/page_index.jsonl") -> Dict[str, Any]:
    """Return count of saved pages without returning entries."""
    p = Path(log_path)
    if not p.exists():
        return {"count": 0, "log_path": str(p)}
    n = sum(1 for _ in p.open("r", encoding="utf-8"))
    return {"count": n, "log_path": str(p)}


@mcp.tool()
def term_stats(
    log_path: str = "temp/page_index.jsonl",
    top_k: int = 20,
) -> Dict[str, Any]:
    """Compute top unigrams/bigrams from saved pages (quick text stats)."""
    p = Path(log_path)
    if not p.exists():
        return {"top_unigrams": [], "top_bigrams": [], "log_path": str(p), "error": "log_not_found"}
    uni = Counter()
    bi = Counter()
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            txt = entry.get("content", "")
            toks = _tokenize(txt)
            uni.update(toks)
            bi.update([f"{toks[i]} {toks[i+1]}" for i in range(len(toks) - 1)])
    return {
        "top_unigrams": uni.most_common(top_k),
        "top_bigrams": bi.most_common(top_k),
        "log_path": str(p),
    }


@mcp.tool()
def delete_page_entries(
    url: Optional[str] = None,
    content_hash: Optional[str] = None,
    match_text: Optional[str] = None,
    log_path: str = "temp/page_index.jsonl",
    dry_run: bool = False,
    sample_limit: int = 5,
) -> Dict[str, Any]:
    """
    Delete entries from the page index by url/content_hash or a text match.
    """
    if not any([url, content_hash, match_text]):
        return {
            "success": False,
            "error": "Provide url, content_hash, or match_text to delete entries.",
            "log_path": log_path,
        }

    p = Path(log_path)
    if not p.exists():
        return {"success": False, "error": "log_not_found", "log_path": str(p)}

    kept_lines: List[str] = []
    deleted_samples: List[Dict[str, Any]] = []
    deleted_count = 0
    total_count = 0

    def _matches(entry: Dict[str, Any]) -> bool:
        if url and entry.get("url") == url:
            return True
        if content_hash and entry.get("content_hash") == content_hash:
            return True
        if match_text:
            hay = " ".join(
                [
                    str(entry.get("url", "")),
                    str(entry.get("note", "")),
                    str(entry.get("content", "")),
                ]
            ).lower()
            return match_text.lower() in hay
        return False

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            total_count += 1
            raw = line.rstrip("\n")
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                kept_lines.append(line)
                continue

            if _matches(entry):
                deleted_count += 1
                if len(deleted_samples) < sample_limit:
                    deleted_samples.append(
                        {
                            "url": entry.get("url"),
                            "content_hash": entry.get("content_hash"),
                            "note": entry.get("note"),
                        }
                    )
                continue

            kept_lines.append(line)

    if not dry_run:
        with p.open("w", encoding="utf-8") as f:
            for line in kept_lines:
                f.write(line)

    return {
        "success": True,
        "log_path": str(p),
        "dry_run": dry_run,
        "total_count": total_count,
        "deleted_count": deleted_count,
        "remaining_count": len(kept_lines),
        "deleted_samples": deleted_samples,
        "hint": "Use dry_run=true to preview matches before deleting.",
    }


if __name__ == "__main__":
    mcp.run()
