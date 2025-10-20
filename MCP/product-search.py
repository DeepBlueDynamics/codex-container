#!/usr/bin/env python3
"""
MCP: product-search
Simple, transparent keyword search for products with learning/memory capabilities.

Implements the "dumb search with agent reasoning" pattern from the article:
- Direct BM25-style keyword search (no synonyms, no complex query understanding)
- Agent learns what works through query evaluation and memory
- Fuzzy matching for product searches
- Query history with semantic similarity lookup

Tools exposed:
- search_products: Simple keyword search
- get_past_queries: Retrieve similar past queries with evaluations
- save_query_evaluation: Save how well a search worked
- add_product: Add new product to catalog
- update_product: Update existing product
- delete_product: Remove product from catalog
- list_products: Browse all products
"""

from __future__ import annotations

import os
import re
import json
import time
import difflib
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("product-search")

__version__ = "0.1.0"

# ----------------------------------
# Configuration
# ----------------------------------
def get_data_dir() -> str:
    """Get the data directory for storing products and query history."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "product_search_data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

PRODUCTS_FILE = os.path.join(get_data_dir(), "products.json")
QUERY_HISTORY_FILE = os.path.join(get_data_dir(), "query_history.json")

# ----------------------------------
# Logging
# ----------------------------------
def _init_logger() -> logging.Logger:
    """Initialize and configure the product-search logger."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    substrate_logs = os.path.join(base_dir, "context_substrate", "logs")
    logs_dir = substrate_logs if os.path.isdir(os.path.join(base_dir, "context_substrate")) else os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "product_search.log")

    logger = logging.getLogger("product_search")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_path)
        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    logger.info("product-search MCP starting; version=%s", __version__)
    logger.info("Logging to %s", log_path)
    return logger

logger = _init_logger()

# ----------------------------------
# Data Storage
# ----------------------------------
def load_products() -> List[Dict[str, Any]]:
    """Load products from JSON file."""
    if not os.path.exists(PRODUCTS_FILE):
        return []
    try:
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error loading products: %s", e)
        return []

def save_products(products: List[Dict[str, Any]]) -> None:
    """Save products to JSON file."""
    try:
        with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Error saving products: %s", e)
        raise

def load_query_history() -> List[Dict[str, Any]]:
    """Load query history from JSON file."""
    if not os.path.exists(QUERY_HISTORY_FILE):
        return []
    try:
        with open(QUERY_HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error loading query history: %s", e)
        return []

def save_query_history(history: List[Dict[str, Any]]) -> None:
    """Save query history to JSON file."""
    try:
        with open(QUERY_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Error saving query history: %s", e)
        raise

# ----------------------------------
# Search Implementation (Simple BM25-style)
# ----------------------------------
def tokenize(text: str) -> List[str]:
    """Basic tokenization - lowercase and split on non-alphanumeric."""
    return [w.lower() for w in re.findall(r'\w+', text) if len(w) > 0]

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts using difflib."""
    if not text1 and not text2:
        return 1.0
    if not text1 or not text2:
        return 0.0
    return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

def bm25_score(query_tokens: List[str], doc_tokens: List[str]) -> float:
    """
    Simple BM25-inspired scoring.
    
    This is intentionally simplified - just term frequency with diminishing returns.
    No IDF, no fancy parameters. Predictable and transparent for the agent.
    """
    if not query_tokens or not doc_tokens:
        return 0.0
    
    doc_token_set = set(doc_tokens)
    matches = sum(1 for qt in query_tokens if qt in doc_token_set)
    
    # Simple score: number of matching terms / total query terms
    return matches / len(query_tokens) if query_tokens else 0.0

def search_products_internal(query: str, products: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Internal search implementation - direct keyword matching only.
    
    No synonyms, no query expansion, no reranking.
    Just BM25-style scoring on name + description.
    """
    query_tokens = tokenize(query)
    
    if not query_tokens:
        return []
    
    results = []
    for product in products:
        # Combine name and description for searching
        searchable_text = f"{product.get('name', '')} {product.get('description', '')}"
        doc_tokens = tokenize(searchable_text)
        
        score = bm25_score(query_tokens, doc_tokens)
        
        if score > 0:
            results.append({
                **product,
                'search_score': round(score, 4)
            })
    
    # Sort by score descending
    results.sort(key=lambda x: x['search_score'], reverse=True)
    
    return results[:top_k]

# ----------------------------------
# MCP Tools
# ----------------------------------
@mcp.tool()
async def search_products(query: str, top_k: int = 5) -> Dict[str, Any]:
    """
    Search for products using simple keyword matching.
    
    This is direct keyword search with NO synonyms, NO query understanding,
    and NO reranking. Only BM25-style scoring on product name and description
    with basic tokenization.
    
    The search is intentionally "dumb" and predictable so agents can learn
    how it works and apply their own intelligence to formulate better queries.
    
    Args:
        query: The search query string (will be tokenized)
        top_k: Number of top results to return (default: 5)
    
    Returns:
        Dict with search results and metadata
    """
    logger.info("search_products called: query='%s', top_k=%d", query, top_k)
    
    products = load_products()
    
    if not products:
        return {
            "success": True,
            "query": query,
            "results": [],
            "result_count": 0,
            "total_products": 0,
            "message": "No products in catalog"
        }
    
    results = search_products_internal(query, products, top_k)
    
    return {
        "success": True,
        "query": query,
        "results": results,
        "result_count": len(results),
        "total_products": len(products),
        "search_method": "bm25_keyword",
        "note": "This is simple keyword search. No synonyms or query expansion. Agent should try different query terms if results aren't good."
    }

@mcp.tool()
async def get_past_queries(
    current_query: str,
    similarity_threshold: float = 0.7,
    max_results: int = 5
) -> Dict[str, Any]:
    """
    Retrieve similar past queries with their evaluations.
    
    Uses semantic similarity to find past queries similar to the current one.
    Returns what worked well and what didn't for similar searches.
    
    This enables the agent to learn from past experience and avoid
    queries that didn't work well before.
    
    Args:
        current_query: The query to find similar past queries for
        similarity_threshold: Minimum similarity score (0.0-1.0)
        max_results: Maximum number of similar queries to return
    
    Returns:
        Dict with similar past queries and their evaluations
    """
    logger.info("get_past_queries called: query='%s'", current_query)
    
    history = load_query_history()
    
    if not history:
        return {
            "success": True,
            "current_query": current_query,
            "matched_queries": [],
            "message": "No query history available yet"
        }
    
    # Calculate similarity for each historical query
    matches = []
    for entry in history:
        similarity = calculate_similarity(current_query, entry['user_query'])
        
        if similarity >= similarity_threshold:
            matches.append({
                "user_query": entry['user_query'],
                "search_tool_query": entry.get('search_tool_query', entry['user_query']),
                "quality": entry['quality'],
                "reasoning": entry['reasoning'],
                "similarity": round(similarity, 4),
                "timestamp": entry['timestamp']
            })
    
    # Sort by similarity descending
    matches.sort(key=lambda x: x['similarity'], reverse=True)
    
    return {
        "success": True,
        "current_query": current_query,
        "matched_queries": matches[:max_results],
        "total_matches": len(matches)
    }

@mcp.tool()
async def save_query_evaluation(
    user_query: str,
    search_tool_query: str,
    quality: str,
    reasoning: str
) -> Dict[str, Any]:
    """
    Save evaluation of a search interaction for future learning.
    
    The agent should call this after each search to record:
    - What the user actually wanted
    - What query was used with the search tool
    - How well it worked (good/meh/bad)
    - Why it worked or didn't work
    
    This builds a knowledge graph of queries over time, enabling
    the agent to get smarter about product searches.
    
    Args:
        user_query: The original user query/intent
        search_tool_query: The actual query used with search_products
        quality: Rating of results ('good', 'meh', 'bad')
        reasoning: Explanation of why this rating was given
    
    Returns:
        Dict with save confirmation
    """
    logger.info("save_query_evaluation: user='%s', tool='%s', quality=%s", 
                user_query, search_tool_query, quality)
    
    if quality not in ['good', 'meh', 'bad']:
        return {
            "success": False,
            "error": "Quality must be 'good', 'meh', or 'bad'"
        }
    
    history = load_query_history()
    
    entry = {
        "user_query": user_query,
        "search_tool_query": search_tool_query,
        "quality": quality,
        "reasoning": reasoning,
        "timestamp": datetime.now().isoformat()
    }
    
    history.append(entry)
    save_query_history(history)
    
    return {
        "success": True,
        "message": "Query evaluation saved",
        "entry": entry,
        "total_history_entries": len(history)
    }

@mcp.tool()
async def add_product(
    name: str,
    description: str,
    product_id: Optional[str] = None,
    price: Optional[float] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Add a new product to the searchable catalog.
    
    Args:
        name: Product name
        description: Product description
        product_id: Optional product ID (auto-generated if not provided)
        price: Optional price
        category: Optional category
        brand: Optional brand name
        metadata: Optional additional fields
    
    Returns:
        Dict with the created product
    """
    logger.info("add_product called: name='%s'", name)
    
    products = load_products()
    
    # Generate ID if not provided
    if not product_id:
        existing_ids = [p.get('id', '') for p in products]
        max_id = 0
        for pid in existing_ids:
            if isinstance(pid, int):
                max_id = max(max_id, pid)
            elif isinstance(pid, str) and pid.isdigit():
                max_id = max(max_id, int(pid))
        product_id = str(max_id + 1)
    
    product = {
        "id": product_id,
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat()
    }
    
    if price is not None:
        product["price"] = price
    if category:
        product["category"] = category
    if brand:
        product["brand"] = brand
    if metadata:
        product["metadata"] = metadata
    
    products.append(product)
    save_products(products)
    
    return {
        "success": True,
        "message": "Product added",
        "product": product,
        "total_products": len(products)
    }

@mcp.tool()
async def update_product(
    product_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    price: Optional[float] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update an existing product.
    
    Args:
        product_id: ID of product to update
        name: New product name (optional)
        description: New description (optional)
        price: New price (optional)
        category: New category (optional)
        brand: New brand (optional)
        metadata: New metadata (optional)
    
    Returns:
        Dict with updated product
    """
    logger.info("update_product called: id='%s'", product_id)
    
    products = load_products()
    
    # Find product
    product = None
    for p in products:
        if str(p.get('id')) == str(product_id):
            product = p
            break
    
    if not product:
        return {
            "success": False,
            "error": f"Product with id '{product_id}' not found"
        }
    
    # Update fields
    if name is not None:
        product["name"] = name
    if description is not None:
        product["description"] = description
    if price is not None:
        product["price"] = price
    if category is not None:
        product["category"] = category
    if brand is not None:
        product["brand"] = brand
    if metadata is not None:
        product["metadata"] = metadata
    
    product["updated_at"] = datetime.now().isoformat()
    
    save_products(products)
    
    return {
        "success": True,
        "message": "Product updated",
        "product": product
    }

@mcp.tool()
async def delete_product(product_id: str) -> Dict[str, Any]:
    """
    Delete a product from the catalog.
    
    Args:
        product_id: ID of product to delete
    
    Returns:
        Dict with deletion confirmation
    """
    logger.info("delete_product called: id='%s'", product_id)
    
    products = load_products()
    
    # Find and remove product
    initial_count = len(products)
    products = [p for p in products if str(p.get('id')) != str(product_id)]
    
    if len(products) == initial_count:
        return {
            "success": False,
            "error": f"Product with id '{product_id}' not found"
        }
    
    save_products(products)
    
    return {
        "success": True,
        "message": f"Product '{product_id}' deleted",
        "total_products": len(products)
    }

@mcp.tool()
async def list_products(
    limit: int = 100,
    offset: int = 0,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    List products from the catalog.
    
    Args:
        limit: Maximum number of products to return
        offset: Number of products to skip (for pagination)
        category: Optional category filter
    
    Returns:
        Dict with product list
    """
    logger.info("list_products called: limit=%d, offset=%d, category='%s'", 
                limit, offset, category or "all")
    
    products = load_products()
    
    # Filter by category if specified
    if category:
        products = [p for p in products if p.get('category', '').lower() == category.lower()]
    
    # Apply pagination
    total = len(products)
    products = products[offset:offset + limit]
    
    return {
        "success": True,
        "products": products,
        "count": len(products),
        "total": total,
        "limit": limit,
        "offset": offset,
        "category_filter": category
    }

@mcp.tool()
async def get_product_stats() -> Dict[str, Any]:
    """
    Get statistics about the product catalog and query history.
    
    Returns:
        Dict with catalog statistics
    """
    products = load_products()
    history = load_query_history()
    
    # Category breakdown
    categories = {}
    for p in products:
        cat = p.get('category', 'uncategorized')
        categories[cat] = categories.get(cat, 0) + 1
    
    # Query quality breakdown
    quality_counts = {'good': 0, 'meh': 0, 'bad': 0}
    for entry in history:
        q = entry.get('quality', 'unknown')
        if q in quality_counts:
            quality_counts[q] += 1
    
    return {
        "success": True,
        "products": {
            "total": len(products),
            "categories": categories
        },
        "query_history": {
            "total_queries": len(history),
            "quality_breakdown": quality_counts
        },
        "data_directory": get_data_dir()
    }

# ----------------------------------
# Entrypoint
# ----------------------------------
if __name__ == "__main__":
    try:
        logger.info("Starting product-search MCP server (stdio)")
        mcp.run(transport='stdio')
    except Exception as e:
        logger.critical("Failed to start MCP server: %s", e, exc_info=True)
        raise
