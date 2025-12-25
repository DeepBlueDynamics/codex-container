#!/usr/bin/env python3
"""
MCP server: term graph, URL sampling, and local page index helpers (embeddings + Jaccard).

Tools
- Graph core: build_term_graph, update_graph, summarize_signals, propose_queries
- URL helpers: filter_urls, sample_urls, oracle_walk_hint
- Page index: save_page, search_saved_pages

Embedding backends
- "instructor-xl": uses hkunlp/instructor-xl (service or local) with hash fallback.
- "hash": deterministic hash-based vectors (no external deps).

Notes
- No crawling here; callers supply docs (url, text). Keep text bounded upstream.
- Embeddings can be persisted to JSON if a path is provided.
- Jaccard similarity is computed on per-doc term sets to highlight overlaps.
"""

from __future__ import annotations

import json
import math
import os
import re
import string
import random
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import blake2b
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
import urllib.request
import urllib.error
import urllib.parse

mcp = FastMCP("term-graph-tools")

try:
    from InstructorEmbedding import INSTRUCTOR  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    INSTRUCTOR = None
    _INSTRUCTOR_IMPORT_ERROR = "InstructorEmbedding not available; install it to use instructor-xl embeddings."
else:
    _INSTRUCTOR_IMPORT_ERROR = ""

_INSTRUCTOR_MODEL = None
_INSTRUCTOR_MODEL_NAME: Optional[str] = None

# Default to container-to-container DNS name on codex-network; override via env for host access
INSTRUCTOR_SERVICE_URL = os.environ.get("INSTRUCTOR_SERVICE_URL", "http://gnosis-instructor-service:8787/embed")

STOPWORDS: Set[str] = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "if",
    "else",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "as",
    "that",
    "this",
    "it",
    "not",
    "but",
    "we",
    "you",
    "they",
    "he",
    "she",
    "them",
    "their",
    "our",
    "your",
}


def _tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split, drop stopwords."""
    text = text.lower()
    text = text.translate(str.maketrans({ch: " " for ch in string.punctuation}))
    raw = text.split()
    return [t for t in raw if t and t not in STOPWORDS and len(t) > 2]


def _bigrams(tokens: List[str]) -> List[str]:
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def _term_counts(tokens: List[str]) -> Counter:
    uni = tokens
    bi = _bigrams(tokens)
    return Counter(uni + bi)


def _tfidf(term_freqs: Counter, doc_freqs: Counter, total_docs: int) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for term, tf in term_freqs.items():
        df = doc_freqs.get(term, 1)
        scores[term] = (1 + math.log(tf)) * math.log((1 + total_docs) / df)
    return scores


def _sliding_edges(tokens: List[str], window: int) -> Counter:
    edges: Counter = Counter()
    for i in range(len(tokens)):
        end = min(len(tokens), i + window)
        for j in range(i + 1, end):
            a, b = tokens[i], tokens[j]
            if a == b:
                continue
            if a > b:
                a, b = b, a
            edges[(a, b)] += 1
    return edges


def _hash_embed(term: str, dim: int = 64) -> List[float]:
    """Deterministic hash-based embedding; lightweight stand-in for full models."""
    needed_bytes = max(4, dim // 8)
    h = blake2b(term.encode("utf-8"), digest_size=needed_bytes).digest()
    vec: List[float] = []
    for i in range(0, len(h), 2):
        v = int.from_bytes(h[i:i+2], "big", signed=False)
        vec.append((v / 65535.0) * 2 - 1)
    while len(vec) < dim:
        vec.append(0.0)
    return vec[:dim]


def _embed_term(term: str, backend: str, model_name: str, warnings: List[str]) -> List[float]:
    """Embed a term using the requested backend."""
    global _INSTRUCTOR_MODEL, _INSTRUCTOR_MODEL_NAME
    if backend == "instructor-xl":
        # Prefer HTTP service if reachable
        if INSTRUCTOR_SERVICE_URL:
            try:
                payload = json.dumps({
                    "texts": [term],
                    "instruction": "Represent the term for clustering",
                    "normalize": True,
                }).encode("utf-8")
                req = urllib.request.Request(
                    INSTRUCTOR_SERVICE_URL,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    embeds = body.get("embeddings") or []
                    if embeds:
                        return embeds[0]
                    warnings.append("Instructor service returned no embeddings; falling back.")
            except Exception as e:
                warnings.append(f"instructor service failed ({e}); falling back to local.")

        if INSTRUCTOR is None:
            warnings.append(_INSTRUCTOR_IMPORT_ERROR or "InstructorEmbedding missing; fell back to hash embedding.")
            return _hash_embed(term)
        try:
            if _INSTRUCTOR_MODEL is None or _INSTRUCTOR_MODEL_NAME != model_name:
                _INSTRUCTOR_MODEL = INSTRUCTOR(model_name)
                _INSTRUCTOR_MODEL_NAME = model_name
            vec = _INSTRUCTOR_MODEL.encode(
                [["Represent the term for clustering", term]],
                normalize_embeddings=True,
            )
            return vec[0].tolist()
        except Exception as e:  # pragma: no cover - runtime protection
            warnings.append(f"instructor-xl failed ({e}); fell back to hash embedding.")
            return _hash_embed(term)
    return _hash_embed(term)


def _embed_text(text: str, backend: str, model_name: str, warnings: List[str]) -> List[float]:
    """Embed arbitrary text (uses term embed under the hood)."""
    return _embed_term(text, backend, model_name, warnings)


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _save_embeddings(path: str, embeddings: Dict[str, List[float]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"embeddings": embeddings}, f, indent=2)


def _normalize_url(u: str) -> str:
    parsed = urlparse(u)
    norm = parsed._replace(fragment="", query="", params="").geturl()
    return norm.rstrip("/")


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _hexagram_from_seed(seed: str) -> int:
    """Deterministically map a seed to 1..64."""
    h = blake2b(seed.encode("utf-8"), digest_size=2).digest()
    return (int.from_bytes(h, "big") % 64) + 1


_HEXAGRAM_GUIDANCE = {
    # hexagram_number: (explore_ratio, domain_diversity, novelty_bias, term_pair_bias, note)
    1: (0.2, True, False, True, "Forceful start: bias to high-signal terms, interleave domains."),
    2: (0.35, True, True, False, "Receptive: explore unseen terms/domains generously."),
    3: (0.3, True, True, True, "Difficulty at the beginning: mix exploration with cross-pair probes."),
    4: (0.4, True, True, False, "Youthful folly: widen sampling; avoid over-trusting scores."),
    5: (0.25, True, False, False, "Wait and see: smaller explore, keep caps tight."),
    6: (0.2, False, False, True, "Conflict: stay focused, fewer domains, pair top terms."),
    34: (0.15, True, False, True, "Power of the great: exploit, but keep domain interleave."),
    44: (0.3, True, True, False, "Coming to meet: add exploration to catch emergent signals."),
}


def _oracle_hint(seed: str, question: Optional[str]) -> Dict[str, Any]:
    hx = _hexagram_from_seed(seed)
    explore_ratio, domain_div, novelty_bias, term_pair_bias, note = _HEXAGRAM_GUIDANCE.get(
        hx,
        (0.3, True, True, False, "Balanced: moderate exploration with domain diversity."),
    )
    return {
        "hexagram": hx,
        "explore_ratio": explore_ratio,
        "domain_diversity": domain_div,
        "novelty_bias": novelty_bias,
        "term_pair_bias": term_pair_bias,
        "note": note,
        "seed": seed,
        "question": question,
    }


def _collect_docs(docs: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Counter, Counter]:
    per_doc_terms: List[Dict[str, Any]] = []
    doc_freqs: Counter = Counter()
    all_term_freqs: Counter = Counter()

    for doc in docs:
        url = doc.get("url", "")
        text = doc.get("text", "") or ""
        tokens = _tokenize(text)
        terms = _term_counts(tokens)
        per_doc_terms.append({"url": url, "terms": terms})
        all_term_freqs.update(terms)
        doc_freqs.update(set(terms.keys()))

    return per_doc_terms, all_term_freqs, doc_freqs


def _build_graph(
    docs: List[Dict[str, str]],
    top_terms: int,
    window: int,
    max_edges: int,
    embedding_path: Optional[str],
    embedding_backend: str,
    embedding_model: str,
) -> Dict[str, Any]:
    per_doc_terms, all_term_freqs, doc_freqs = _collect_docs(docs)
    total_docs = len(docs) or 1
    tfidf_scores = _tfidf(all_term_freqs, doc_freqs, total_docs)

    # Top terms
    top = sorted(tfidf_scores.items(), key=lambda x: x[1], reverse=True)[:top_terms]
    top_set = {t for t, _ in top}

    # Edges from per-doc tokens, limited to top terms
    edge_counts: Counter = Counter()
    for doc in docs:
        tokens = [t for t in _tokenize(doc.get("text", "")) if t in top_set]
        edge_counts.update(_sliding_edges(tokens, window))
    edges = sorted(edge_counts.items(), key=lambda x: x[1], reverse=True)[:max_edges]

    warnings: List[str] = []

    nodes = [{"id": term, "term": term, "score": score} for term, score in top]
    edge_list = [{"source": a, "target": b, "weight": w} for (a, b), w in edges]

    sources = []
    for doc in docs:
        url = doc.get("url", "")
        tokens = set(_tokenize(doc.get("text", "")))
        sources.append({
            "url": url,
            "hash": blake2b((url + doc.get("text", "")).encode("utf-8"), digest_size=8).hexdigest(),
            "terms": list(tokens & top_set),
            "date": datetime.utcnow().isoformat()
        })

    embeddings: Dict[str, List[float]] = {
        term: _embed_term(term, embedding_backend, embedding_model, warnings) for term in top_set
    }
    if embedding_path:
        _save_embeddings(embedding_path, embeddings)

    effective_backend = embedding_backend
    if warnings:
        effective_backend = f"{embedding_backend} (fallback=hash)"

    return {
        "nodes": nodes,
        "edges": edge_list,
        "sources": sources,
        "metadata": {
            "built_at": datetime.utcnow().isoformat(),
            "top_terms": top_terms,
            "window": window,
            "max_edges": max_edges,
            "documents": len(docs),
            "embeddings_path": embedding_path,
            "embedding_backend_requested": embedding_backend,
            "embedding_backend_effective": effective_backend,
            "embedding_model": embedding_model,
            "warnings": warnings,
        },
    }


@mcp.tool()
async def build_term_graph(
    docs: List[Dict[str, str]],
    top_terms: int = 300,
    window: int = 5,
    max_edges: int = 3000,
    embedding_path: str = "temp/term_graph_embeddings.json",
    embedding_backend: str = "instructor-xl",
    embedding_model: str = "hkunlp/instructor-xl",
) -> Dict[str, Any]:
    """Build a bounded term graph from provided documents.

    Args:
        docs: List of {"url": str, "text": str}. Text should be pre-trimmed; no crawling is done here.
        top_terms: Max terms to keep (nodes).
        window: Sliding window size for co-occurrence edges.
        max_edges: Max edges to keep by weight.
        embedding_path: Where to persist hash-based embeddings for nodes (JSON).
        embedding_backend: "instructor-xl" (preferred) or "hash".
        embedding_model: Instructor model name to load when backend is instructor-xl.

    Returns:
        Graph dict: nodes, edges, sources, metadata. Embeddings are stored on disk if path provided.
    """
    return _build_graph(
        docs,
        top_terms,
        window,
        max_edges,
        embedding_path,
        embedding_backend,
        embedding_model,
    )


@mcp.tool()
async def propose_queries(
    graph: Dict[str, Any],
    max_queries: int = 15,
    focus_terms: Optional[List[str]] = None,
) -> List[str]:
    """Propose search queries from graph central terms.

    Args:
        graph: Graph dict with nodes.
        max_queries: Max queries to return.
        focus_terms: Optional terms to prioritize.

    Returns:
        List of query strings, deduped and capped.
    """
    nodes = graph.get("nodes", [])
    ranked = [n["term"] for n in sorted(nodes, key=lambda x: x.get("score", 0), reverse=True)]
    focus = focus_terms or []

    queries: List[str] = []
    # Seed with focus terms if present
    for f in focus:
        if f not in queries:
            queries.append(f)
        if len(queries) >= max_queries:
            return queries[:max_queries]

    # Pair top terms to make more specific queries
    for i, t1 in enumerate(ranked[: max_queries * 2]):
        if len(queries) >= max_queries:
            break
        for t2 in ranked[i + 1 : i + 5]:
            q = f"{t1} {t2}"
            if q not in queries:
                queries.append(q)
                if len(queries) >= max_queries:
                    break

    # Fill with single terms if still short
    for t in ranked:
        if len(queries) >= max_queries:
            break
        if t not in queries:
            queries.append(t)

    return queries[:max_queries]


@mcp.tool()
async def oracle_walk_hint(
    question: Optional[str] = None,
    seed: Optional[str] = None,
) -> Dict[str, Any]:
    """Return randomized-but-reproducible exploration knobs for URL sampling.

    Args:
        question: Optional prompt to include in metadata.
        seed: Seed for reproducibility; if omitted, uses current UTC date.

    Returns:
        Dict with hexagram, explore_ratio, domain_diversity, novelty_bias, term_pair_bias, note, seed, question.
        Also returns chaining hints:
        - next_tool_to_run: recommended follow-up tool.
        - suggested_call: JSON payload template for that tool (with placeholders to fill).
        - required_inputs: list of placeholders that must be provided.
    """
    seed_val = seed or datetime.utcnow().strftime("%Y-%m-%d")
    hint = _oracle_hint(seed_val, question)

    # Non-breaking chaining metadata so agents can immediately call the sampler.
    # Placeholders should be replaced by the caller.
    hint["next_tool_to_run"] = "term_graph_tools.sample_urls"
    hint["required_inputs"] = ["urls", "allowlist"]
    hint["suggested_call"] = {
        "tool": "term_graph_tools.sample_urls",
        "arguments": {
            "urls": "${urls}",  # list[str] to supply
            "allowlist": "${allowlist}",  # list[str] to supply
            "scores": "${scores_optional}",  # optional list[float]
            "max_per_domain": 3,
            "max_total": 10,
            "explore_ratio": hint["explore_ratio"],
            "domain_diversity": hint["domain_diversity"],
            "seed": hint["seed"],
        },
        "description": "Fill urls/allowlist (and optional scores), then call sample_urls using oracle parameters.",
    }
    return hint


@mcp.tool()
async def sample_urls(
    urls: List[str],
    allowlist: List[str],
    scores: Optional[List[float]] = None,
    max_per_domain: int = 3,
    max_total: int = 25,
    explore_ratio: float = 0.3,
    domain_diversity: bool = True,
    drop_params: bool = True,
    seed: Optional[str] = None,
) -> List[str]:
    """Sample URLs with a Monte Carlo-style mix of exploitation and exploration.

    Args:
        urls: Candidate URLs.
        allowlist: Allowed domain substrings.
        scores: Optional relevance scores (same length as urls); if absent, uniform.
        max_per_domain: Cap per domain.
        max_total: Cap total.
        explore_ratio: Fraction to pick uniformly at random (exploration); rest weighted by scores (exploitation).
        domain_diversity: If True, reshuffle final list to interleave domains.
        drop_params: Strip query/fragment before deduping.
        seed: Optional seed for reproducibility.

    Returns:
        List of sampled URLs, capped and filtered.
    """
    if len(urls) == 0:
        return []
    rng = random.Random(seed or datetime.utcnow().isoformat())

    norm_urls = []
    for i, u in enumerate(urls):
        u_norm = _normalize_url(u) if drop_params else u
        norm_urls.append((u_norm, i))

    # Dedup preserving first occurrence
    seen = set()
    deduped = []
    for u, idx in norm_urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append((u, idx))

    # Filter by allowlist first
    filtered = []
    for u, idx in deduped:
        if any(allow in u for allow in allowlist):
            filtered.append((u, idx))
    if not filtered:
        return []

    # Align scores
    if scores and len(scores) == len(urls):
        score_map = {i: s for i, s in enumerate(scores)}
        vals = [score_map[idx] for _, idx in filtered]
    else:
        vals = [1.0 for _ in filtered]

    # Softmax scores for exploitation
    max_v = max(vals) if vals else 1.0
    exp_vals = [pow(2.71828, (v - max_v)) for v in vals]  # basic softmax shift
    total_exp = sum(exp_vals) or 1.0
    probs = [v / total_exp for v in exp_vals]

    # Determine counts
    exploit_count = max(0, min(int(round(max_total * (1 - explore_ratio))), max_total))
    explore_count = max_total - exploit_count

    # Exploitation sampling (weighted without replacement)
    available = list(range(len(filtered)))
    exploit_indices = []
    for _ in range(min(exploit_count, len(available))):
        # draw proportional to probs over remaining
        weights = [probs[i] for i in available]
        s = sum(weights) or 1.0
        pick = rng.random() * s
        acc = 0.0
        chosen = available[-1]
        for a, w in zip(available, weights):
            acc += w
            if pick <= acc:
                chosen = a
                break
        exploit_indices.append(chosen)
        available.remove(chosen)

    # Exploration sampling (uniform from remaining)
    rng.shuffle(available)
    explore_indices = available[:explore_count]

    picked = exploit_indices + explore_indices

    # Enforce per-domain caps while building output
    per_domain: Dict[str, int] = defaultdict(int)
    output: List[str] = []
    for idx in picked:
        u, _ = filtered[idx]
        host = urlparse(u).netloc
        if per_domain[host] >= max_per_domain:
            continue
        per_domain[host] += 1
        output.append(u)
        if len(output) >= max_total:
            break

    if domain_diversity:
        rng.shuffle(output)

    return output[:max_total]
@mcp.tool()
async def filter_urls(
    urls: List[str],
    allowlist: List[str],
    max_per_domain: int = 3,
    max_total: int = 25,
    drop_params: bool = True,
) -> List[str]:
    """Filter URLs by allowlist and caps.

    Args:
        urls: Candidate URLs.
        allowlist: Allowed domain substrings (e.g., ["example.com", "github.com/org"]).
        max_per_domain: Max URLs per domain.
        max_total: Max total URLs.
        drop_params: If true, strip query/fragment before deduping.

    Returns:
        Filtered URL list.
    """
    allowed = []
    per_domain: Dict[str, int] = defaultdict(int)
    seen: Set[str] = set()
    for u in urls:
        u_norm = _normalize_url(u) if drop_params else u
        if u_norm in seen:
            continue
        seen.add(u_norm)
        host = urlparse(u_norm).netloc
        if not any(allow in u_norm for allow in allowlist):
            continue
        if per_domain[host] >= max_per_domain:
            continue
        per_domain[host] += 1
        allowed.append(u_norm)
        if len(allowed) >= max_total:
            break
    return allowed


@mcp.tool()
async def update_graph(
    graph: Dict[str, Any],
    docs: List[Dict[str, str]],
    top_terms: int = 300,
    window: int = 5,
    max_edges: int = 3000,
    embedding_path: str = "temp/term_graph_embeddings.json",
    embedding_backend: str = "instructor-xl",
    embedding_model: str = "hkunlp/instructor-xl",
) -> Dict[str, Any]:
    """Merge new docs into an existing graph and return a refreshed graph.

    Args:
        graph: Existing graph dict.
        docs: New docs [{"url","text"}].
        top_terms: Max nodes.
        window: Edge window.
        max_edges: Max edges.
        embedding_path: Where to persist embeddings.
        embedding_backend: "instructor-xl" or "hash".
        embedding_model: Instructor model name when backend is instructor-xl.

    Returns:
        Updated graph dict with new metadata timestamp.
    """
    combined_docs = []
    existing_sources = graph.get("sources", [])
    for src in existing_sources:
        combined_docs.append({
            "url": src.get("url", ""),
            "text": " ".join(src.get("terms", []))
        })
    combined_docs.extend(docs)
    new_graph = _build_graph(
        combined_docs,
        top_terms,
        window,
        max_edges,
        embedding_path,
        embedding_backend,
        embedding_model,
    )
    return new_graph


@mcp.tool()
async def summarize_signals(
    graph: Dict[str, Any],
    docs: List[Dict[str, str]],
    top_k: int = 10,
) -> Dict[str, Any]:
    """Extract notable signals from graph + docs, including Jaccard overlaps.

    Args:
        graph: Graph dict.
        docs: Docs analyzed (url, text).
        top_k: Number of top terms to surface.

    Returns:
        Summary dict with top_terms, edges, jaccard_pairs, and provenance.
    """
    nodes = sorted(graph.get("nodes", []), key=lambda x: x.get("score", 0), reverse=True)[:top_k]
    edges = sorted(graph.get("edges", []), key=lambda x: x.get("weight", 0), reverse=True)[:top_k]

    # Jaccard between doc term sets
    doc_terms: List[Tuple[str, Set[str]]] = []
    for d in docs:
        url = d.get("url", "")
        terms = set(_tokenize(d.get("text", "") or ""))
        doc_terms.append((url, terms))

    jaccard_pairs: List[Dict[str, Any]] = []
    for i in range(len(doc_terms)):
        for j in range(i + 1, len(doc_terms)):
            u1, t1 = doc_terms[i]
            u2, t2 = doc_terms[j]
            score = _jaccard(t1, t2)
            if score > 0:
                jaccard_pairs.append({"url_a": u1, "url_b": u2, "jaccard": round(score, 4)})

    jaccard_pairs = sorted(jaccard_pairs, key=lambda x: x["jaccard"], reverse=True)[:top_k]

    return {
        "top_terms": nodes,
        "top_edges": edges,
        "jaccard_pairs": jaccard_pairs,
        "provenance": graph.get("sources", []),
        "metadata": {
            "summarized_at": datetime.utcnow().isoformat(),
            "docs": len(docs),
            "top_k": top_k,
        },
    }


@mcp.tool()
async def save_url(
    url: str,
    note: Optional[str] = None,
    log_path: str = "temp/url_index.jsonl",
) -> Dict[str, Any]:
    """Append a URL + timestamp to a JSONL index.

    Args:
        url: URL to record.
        note: Optional note or label.
        log_path: File path for the JSONL log (default temp/url_index.jsonl).

    Returns:
        Dict with entry data and log_path.
    """
    entry = {
        "url": url,
        "note": note,
        "timestamp": datetime.utcnow().isoformat(),
    }
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return {"entry": entry, "log_path": str(p)}


@mcp.tool()
async def search_saved_urls(
    query: str,
    log_path: str = "temp/url_index.jsonl",
    top_k: int = 10,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
) -> Dict[str, Any]:
    """Search saved URLs (from save_url) by semantic similarity to a query.

    Args:
        query: Text to search for.
        log_path: Path to JSONL log produced by save_url.
        top_k: Number of matches to return.
        embedding_backend: "instructor-xl" or "hash".
        embedding_model: Instructor model name when backend is instructor-xl.

    Returns:
        Dict with matches and metadata.
    """
    p = Path(log_path)
    if not p.exists():
        return {"matches": [], "metadata": {"log_path": str(p), "error": "log_not_found"}}

    warnings: List[str] = []
    q_embed = _embed_text(query, embedding_backend, embedding_model, warnings)
    matches: List[Dict[str, Any]] = []

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = entry.get("url", "") + " " + (entry.get("note") or "")
            e_embed = _embed_text(text, embedding_backend, embedding_model, warnings)
            score = _cosine(q_embed, e_embed)
            matches.append({"score": score, "entry": entry})

    matches = sorted(matches, key=lambda x: x["score"], reverse=True)[:top_k]
    return {
        "matches": matches,
        "metadata": {
            "log_path": str(p),
            "embedding_backend_requested": embedding_backend,
            "embedding_backend_effective": embedding_backend if not warnings else f"{embedding_backend} (fallback=hash)",
            "embedding_model": embedding_model,
            "warnings": warnings,
        },
    }


@mcp.tool()
async def save_page(
    url: str,
    text: str,
    note: Optional[str] = None,
    log_path: str = "temp/page_index.jsonl",
    max_store_chars: int = 8000,
    embed: bool = False,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
    instructor_service_url: str = "",
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    """Save a crawled page (url + content) to a JSONL index with timestamp."""
    warnings: List[str] = []
    snippet = text[:max_store_chars]
    entry: Dict[str, Any] = {
        "url": url,
        "note": note,
        "timestamp": datetime.utcnow().isoformat(),
        "content": snippet,
        "content_len": len(text),
        "content_hash": blake2b(text.encode("utf-8"), digest_size=8).hexdigest(),
    }

    if embed:
        backend = embedding_backend
        if backend == "instructor-xl":
            svc = instructor_service_url or os.environ.get("INSTRUCTOR_SERVICE_URL", "http://gnosis-instructor-service:8787/embed")
            try:
                payload = {
                    "texts": [f"{url} {note or ''} {snippet}"],
                    "instruction": "Represent the text for semantic search",
                    "normalize": True,
                }
                req = urllib.request.Request(
                    svc,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    embeds = body.get("embeddings") or []
                    if embeds:
                        entry["embedding"] = embeds[0]
                        entry["embedding_backend"] = "instructor-xl"
                    else:
                        warnings.append("instructor service returned no embeddings; falling back to hash.")
            except Exception as e:
                warnings.append(f"instructor service failed ({e}); falling back to hash.")
        if "embedding" not in entry:
            entry["embedding"] = _embed_text(f"{url} {note or ''} {snippet}", "hash", embedding_model, warnings)
            entry["embedding_backend"] = "hash"

    if warnings:
        entry["warnings"] = warnings
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return {"entry": entry, "log_path": str(p)}


@mcp.tool()
async def search_saved_pages(
    query: str,
    log_path: str = "temp/page_index.jsonl",
    top_k: int = 10,
    embedding_backend: str = "hash",
    embedding_model: str = "hkunlp/instructor-xl",
    max_query_chars: int = 2000,
) -> Dict[str, Any]:
    """Search saved pages by semantic similarity to a query over url/note/content."""
    p = Path(log_path)
    if not p.exists():
        return {"matches": [], "metadata": {"log_path": str(p), "error": "log_not_found"}}

    warnings: List[str] = []
    q_embed = _embed_text(query, embedding_backend, embedding_model, warnings)
    matches: List[Dict[str, Any]] = []

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "embedding" in entry:
                e_embed = entry["embedding"]
            else:
                text_blob = " ".join(
                    filter(
                        None,
                        [
                            entry.get("url", ""),
                            entry.get("note") or "",
                            (entry.get("content") or "")[:max_query_chars],
                        ],
                    )
                )
                e_embed = _embed_text(text_blob, embedding_backend, embedding_model, warnings)
            score = _cosine(q_embed, e_embed)
            matches.append({"score": score, "entry": entry})

    matches = sorted(matches, key=lambda x: x["score"], reverse=True)[:top_k]
    effective_backend = embedding_backend if not warnings else f"{embedding_backend} (fallback=hash)"
    return {
        "matches": matches,
        "metadata": {
            "log_path": str(p),
            "embedding_backend_requested": embedding_backend,
            "embedding_backend_effective": effective_backend,
            "embedding_model": embedding_model,
            "warnings": warnings,
        },
    }


if __name__ == "__main__":
    mcp.run()
