#!/usr/bin/env python3
"""
MCP server for Mongo/DocumentDB-style document access.

Environment/config:
  DOCDB_URI: Mongo URI (default: mongodb://localhost:27017)
  DOCDB_DB: database name (required)
  DOCDB_COLLECTION_ALLOWLIST: comma-separated collections allowed (optional)
  DOCDB_READONLY: "true"/"false" (default: false)
  DOCDB_TIMEOUT_MS: connection timeout in ms (default: 3000)
  DOCDB_MAX_DOCS: max docs returned per call (default: 200)
  DOCDB_MAX_BYTES: max payload bytes for inserts/updates (default: 1_000_000)

Exposed tools:
  list_collections()
  insert_documents(collection, docs)
  get_document(collection, filter, projection=None)
  find_documents(collection, filter, projection=None, sort=None, limit=100)
  update_documents(collection, filter, update, many=False)
  delete_documents(collection, filter, many=False)
  create_index(collection, keys, unique=False)
  list_indexes(collection)
  collection_stats(collection)

Safety:
  - Optional collection allowlist
  - Readonly mode blocks insert/update/delete/create_index
  - Caps: limit, payload bytes, max_docs, timeout
  - Filter/sort/projection expected as dicts; no $where/eval allowed
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mongo-docdb")


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes", "on")


def _load_settings() -> Dict[str, Any]:
    uri = os.environ.get("DOCDB_URI", "mongodb://localhost:27017")
    db = os.environ.get("DOCDB_DB")
    if not db:
        raise RuntimeError("DOCDB_DB is required")
    allowlist_raw = os.environ.get("DOCDB_COLLECTION_ALLOWLIST", "")
    allowlist = [c.strip() for c in allowlist_raw.split(",") if c.strip()]
    return {
        "uri": uri,
        "db": db,
        "allowlist": allowlist,
        "readonly": _env_bool("DOCDB_READONLY", False),
        "timeout_ms": int(os.environ.get("DOCDB_TIMEOUT_MS", "3000")),
        "max_docs": int(os.environ.get("DOCDB_MAX_DOCS", "200")),
        "max_bytes": int(os.environ.get("DOCDB_MAX_BYTES", "1000000")),
    }


SETTINGS = _load_settings()


def _client() -> MongoClient:
    return MongoClient(
        SETTINGS["uri"],
        serverSelectionTimeoutMS=SETTINGS["timeout_ms"],
        connectTimeoutMS=SETTINGS["timeout_ms"],
    )


def _assert_allowed(collection: str) -> None:
    if SETTINGS["allowlist"] and collection not in SETTINGS["allowlist"]:
        raise ValueError(f"collection '{collection}' not in allowlist")


def _assert_rw() -> None:
    if SETTINGS["readonly"]:
        raise ValueError("readonly mode is enabled")


def _safe_filter(obj: Dict[str, Any]) -> Dict[str, Any]:
    # basic guard: block $where / $function style server-side JS
    def scan(d: Any):
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(k, str) and k.lower() in ("$where", "$accumulator", "$function", "$eval"):
                    raise ValueError(f"unsupported operator: {k}")
                scan(v)
        elif isinstance(d, list):
            for item in d:
                scan(item)
    scan(obj)
    return obj


def _cap_limit(limit: Optional[int]) -> int:
    if limit is None or limit <= 0:
        return min(SETTINGS["max_docs"], 100)
    return min(limit, SETTINGS["max_docs"])


def _payload_size_ok(docs: Any) -> None:
    try:
        b = json.dumps(docs).encode("utf-8")
    except Exception:
        # let pymongo handle serialization errors later
        return
    if len(b) > SETTINGS["max_bytes"]:
        raise ValueError(f"payload exceeds max bytes ({SETTINGS['max_bytes']})")


def _sanitize_obj(obj: Any) -> Any:
    # convert ObjectId to string recursively
    try:
        from bson import ObjectId
    except ImportError:
        ObjectId = None

    if ObjectId and isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, list):
        return [_sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_obj(v) for k, v in obj.items()}
    return obj


@mcp.tool()
async def list_collections() -> List[str]:
    """List collections."""
    try:
        with _client() as cli:
            return cli[SETTINGS["db"]].list_collection_names()
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def insert_documents(collection: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Insert documents (respects allowlist/read-only/max_bytes)."""
    _assert_allowed(collection)
    _assert_rw()
    _payload_size_ok(docs)
    if not isinstance(docs, list) or not docs:
        raise ValueError("docs must be a non-empty list")
    try:
        with _client() as cli:
            res = cli[SETTINGS["db"]][collection].insert_many(docs)
            return {"inserted_count": len(res.inserted_ids), "inserted_ids": [str(_id) for _id in res.inserted_ids]}
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def get_document(collection: str, filter: Dict[str, Any], projection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Find one document by filter."""
    _assert_allowed(collection)
    filt = _safe_filter(filter)
    try:
        with _client() as cli:
            doc = cli[SETTINGS["db"]][collection].find_one(filt, projection)
            return _sanitize_obj(doc) if doc else {}
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def find_documents(
    collection: str,
    filter: Dict[str, Any],
    projection: Optional[Dict[str, Any]] = None,
    sort: Optional[List[List[Any]]] = None,
    limit: Optional[int] = 100,
) -> List[Dict[str, Any]]:
    """Find many documents with filter/sort/projection, capped by limit and max_docs."""
    _assert_allowed(collection)
    filt = _safe_filter(filter)
    lim = _cap_limit(limit)
    try:
        with _client() as cli:
            cursor = cli[SETTINGS["db"]][collection].find(filt, projection, limit=lim)
            if sort:
                cursor = cursor.sort(sort)
            docs = list(cursor)
            return [_sanitize_obj(d) for d in docs]
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def update_documents(collection: str, filter: Dict[str, Any], update: Dict[str, Any], many: bool = False) -> Dict[str, Any]:
    """Update documents (blocked in readonly)."""
    _assert_allowed(collection)
    _assert_rw()
    _payload_size_ok(update)
    filt = _safe_filter(filter)
    try:
        with _client() as cli:
            col = cli[SETTINGS["db"]][collection]
            res = col.update_many(filt, update) if many else col.update_one(filt, update)
            return {"matched": res.matched_count, "modified": res.modified_count}
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def delete_documents(collection: str, filter: Dict[str, Any], many: bool = False) -> Dict[str, Any]:
    """Delete documents (blocked in readonly)."""
    _assert_allowed(collection)
    _assert_rw()
    filt = _safe_filter(filter)
    try:
        with _client() as cli:
            col = cli[SETTINGS["db"]][collection]
            res = col.delete_many(filt) if many else col.delete_one(filt)
            return {"deleted": res.deleted_count}
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def create_index(collection: str, keys: List[List[Any]], unique: bool = False) -> Dict[str, Any]:
    """Create an index (blocked in readonly). Keys format: [[\"field\", 1], [\"other\", -1]]."""
    _assert_allowed(collection)
    _assert_rw()
    try:
        with _client() as cli:
            name = cli[SETTINGS["db"]][collection].create_index(keys, unique=unique)
            return {"name": name}
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def list_indexes(collection: str) -> List[Dict[str, Any]]:
    """List indexes on a collection."""
    _assert_allowed(collection)
    try:
        with _client() as cli:
            idx = list(cli[SETTINGS["db"]][collection].list_indexes())
            return [_sanitize_obj(i) for i in idx]
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


@mcp.tool()
async def collection_stats(collection: str) -> Dict[str, Any]:
    """Return basic stats on a collection (count, storage size)."""
    _assert_allowed(collection)
    try:
        with _client() as cli:
            stats = cli[SETTINGS["db"]].command("collstats", collection)
            return _sanitize_obj(stats)
    except PyMongoError as e:
        raise RuntimeError(f"mongo error: {e}")


if __name__ == "__main__":
    mcp.run()
