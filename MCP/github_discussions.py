#!/usr/bin/env python3
"""MCP: github-discussions

Manage GitHub Discussions via GraphQL.
Provides utilities to store repo credentials, list discussions, fetch details,
and reply to threads from Codex using FastMCP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import os

import aiohttp
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("github-discussions")

API_URL = "https://api.github.com/graphql"
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / ".github-discussion.env"
OWNER_KEY = "GITHUB_DISCUSSIONS_OWNER"
REPO_KEY = "GITHUB_DISCUSSIONS_REPO"
TOKEN_KEY = "GITHUB_DISCUSSIONS_TOKEN"


GET_REPO_ID_QUERY = """
query GetRepoId($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    id
  }
}
"""

GET_CATEGORIES_QUERY = """
query GetCategories($owner: String!, $repo: String!, $first: Int!) {
  repository(owner: $owner, name: $repo) {
    discussionCategories(first: $first) {
      edges {
        node {
          id
          name
          description
          isAnswerable
          emoji
        }
      }
    }
  }
}
"""

LIST_DISCUSSIONS_QUERY = """
query GetDiscussions($owner: String!, $repo: String!, $first: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    discussions(first: $first, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        node {
          id
          number
          title
          body
          author { login }
          createdAt
          updatedAt
          isAnswered
          category { name }
          comments(first: 1) { totalCount }
          url
        }
      }
    }
  }
}
"""

GET_DISCUSSION_QUERY = """
query GetDiscussion($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    discussion(number: $number) {
      id
      number
      title
      body
      author { login }
      createdAt
      updatedAt
      isAnswered
      answer { id body author { login } }
      category { id name }
      locked
      comments(first: 50) {
        totalCount
        edges { node { id body author { login } createdAt updatedAt } }
      }
      reactions(first: 10) {
        totalCount
        edges { node { content user { login } } }
      }
      url
    }
  }
}
"""

ADD_COMMENT_MUTATION = """
mutation AddDiscussionComment($discussionId: ID!, $body: String!, $replyToId: ID) {
  addDiscussionComment(input: {
    discussionId: $discussionId,
    body: $body,
    replyToId: $replyToId
  }) {
    comment {
      id
      body
      createdAt
      author { login }
    }
  }
}
"""

CREATE_DISCUSSION_MUTATION = """
mutation CreateDiscussion($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {
    repositoryId: $repositoryId
    categoryId: $categoryId
    title: $title
    body: $body
  }) {
    discussion {
      id
      number
      title
      url
      createdAt
    }
  }
}
"""


def _read_env_file() -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not CONFIG_FILE.exists():
        return data
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _write_env_file(values: Dict[str, str]) -> None:
    lines = [f"{key}={val}" for key, val in values.items()]
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_setting(key: str) -> Optional[str]:
    env_values = _read_env_file()
    return env_values.get(key) or os.environ.get(key)


def _resolve_token(env_token: Optional[str]) -> Optional[str]:
    return env_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _require_context() -> Dict[str, str]:
    owner = _resolve_setting(OWNER_KEY)
    repo = _resolve_setting(REPO_KEY)
    token = _resolve_token(_resolve_setting(TOKEN_KEY))
    if not owner or not repo:
        raise RuntimeError("Configure GitHub discussions with github_discussions_configure first.")
    if not token:
        raise RuntimeError("Missing GitHub token; pass it to configure or set GITHUB_TOKEN.")
    return {"owner": owner, "repo": repo, "token": token}


async def _graphql(token: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "codex-mcp-discussions/1.0",
    }
    payload = {"query": query, "variables": variables}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            text = await resp.text()
            try:
                data = await resp.json(content_type=None)
            except Exception:
                raise RuntimeError(f"Non-JSON response from GitHub: {text}")
            if resp.status >= 400:
                message = data.get("message") if isinstance(data, dict) else text
                raise RuntimeError(f"GitHub HTTP {resp.status}: {message}")
            if isinstance(data, dict) and "errors" in data:
                err = data["errors"][0]
                raise RuntimeError(f"GraphQL error: {err.get('message', err)}")
            if not isinstance(data, dict):
                raise RuntimeError("Unexpected response payload.")
            return data.get("data", {})


async def _get_repo_id(ctx: Dict[str, str]) -> str:
    variables = {"owner": ctx["owner"], "repo": ctx["repo"]}
    data = await _graphql(ctx["token"], GET_REPO_ID_QUERY, variables)
    repo = (data.get("repository") or {}).get("id")
    if not repo:
        raise RuntimeError("Repository ID not found. Check owner/repo configuration.")
    return repo


async def _get_categories(ctx: Dict[str, str], first: int = 25) -> Dict[str, Any]:
    variables = {"owner": ctx["owner"], "repo": ctx["repo"], "first": max(1, first)}
    data = await _graphql(ctx["token"], GET_CATEGORIES_QUERY, variables)
    categories = (data.get("repository") or {}).get("discussionCategories") or {}
    return categories


@mcp.tool()
async def github_discussions_configure(repo: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Persist owner/repo/token into .github-discussion.env for later calls."""
    repo_value = repo.strip()
    if "/" not in repo_value:
        return {"success": False, "error": "Repo must be in the form 'owner/name'."}
    owner, name = repo_value.split("/", 1)
    owner = owner.strip()
    name = name.strip()
    token_value = _resolve_token(token)
    if not token_value:
        return {"success": False, "error": "Provide a GitHub token or set GITHUB_TOKEN."}
    _write_env_file(
        {
            OWNER_KEY: owner,
            REPO_KEY: name,
            TOKEN_KEY: token_value,
        }
    )
    masked = f"{token_value[:4]}..." if len(token_value) > 8 else "***"
    return {
        "success": True,
        "repo": f"{owner}/{name}",
        "token_saved": masked,
        "env_file": str(CONFIG_FILE),
    }


@mcp.tool()
async def github_discussions_list(first: int = 10, after: Optional[str] = None) -> Dict[str, Any]:
    """List the most recently updated discussions for the configured repository."""
    try:
        ctx = _require_context()
        variables = {"owner": ctx["owner"], "repo": ctx["repo"], "first": max(1, min(first, 50)), "after": after}
        data = await _graphql(ctx["token"], LIST_DISCUSSIONS_QUERY, variables)
        discussions = (data.get("repository") or {}).get("discussions") or {}
        return {
            "success": True,
            "repo": f"{ctx['owner']}/{ctx['repo']}",
            "totalCount": discussions.get("totalCount"),
            "pageInfo": discussions.get("pageInfo"),
            "edges": discussions.get("edges", []),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def github_discussions_create(
    title: str, body: str, category_name: Optional[str] = None, category_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new discussion using the configured repository."""
    if not title.strip():
        return {"success": False, "error": "Title cannot be empty."}
    if not body.strip():
        return {"success": False, "error": "Body cannot be empty."}
    try:
        ctx = _require_context()
        repo_id = await _get_repo_id(ctx)
        chosen_category = category_id
        categories = None
        if not chosen_category:
            categories = await _get_categories(ctx)
            edges = categories.get("edges", []) if isinstance(categories, dict) else []
            if category_name:
                lowered = category_name.strip().lower()
                for edge in edges:
                    node = edge.get("node") if isinstance(edge, dict) else None
                    if node and isinstance(node.get("name"), str) and node["name"].strip().lower() == lowered:
                        chosen_category = node.get("id")
                        break
            if not chosen_category and edges:
                chosen_category = edges[0].get("node", {}).get("id")
        if not chosen_category:
            return {"success": False, "error": "Unable to determine a discussion category."}
        variables = {
            "repositoryId": repo_id,
            "categoryId": chosen_category,
            "title": title,
            "body": body,
        }
        data = await _graphql(ctx["token"], CREATE_DISCUSSION_MUTATION, variables)
        discussion = (data.get("createDiscussion") or {}).get("discussion")
        if not discussion:
            return {"success": False, "error": "GitHub did not return a discussion payload."}
        return {"success": True, "discussion": discussion}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def github_discussions_get(number: int) -> Dict[str, Any]:
    """Fetch a specific discussion thread (including comments and reactions)."""
    try:
        ctx = _require_context()
        variables = {"owner": ctx["owner"], "repo": ctx["repo"], "number": number}
        data = await _graphql(ctx["token"], GET_DISCUSSION_QUERY, variables)
        discussion = (data.get("repository") or {}).get("discussion")
        if not discussion:
            return {"success": False, "error": f"Discussion #{number} not found."}
        return {"success": True, "discussion": discussion}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
async def github_discussions_reply(number: int, body: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
    """Post a new comment or reply inside a discussion thread."""
    if not body.strip():
        return {"success": False, "error": "Comment body cannot be empty."}
    try:
        ctx = _require_context()
        detail_vars = {"owner": ctx["owner"], "repo": ctx["repo"], "number": number}
        detail_data = await _graphql(ctx["token"], GET_DISCUSSION_QUERY, detail_vars)
        discussion = (detail_data.get("repository") or {}).get("discussion")
        if not discussion:
            return {"success": False, "error": f"Discussion #{number} not found."}
        variables = {"discussionId": discussion["id"], "body": body, "replyToId": reply_to_id}
        data = await _graphql(ctx["token"], ADD_COMMENT_MUTATION, variables)
        comment = (data.get("addDiscussionComment") or {}).get("comment")
        return {"success": True, "comment": comment}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


if __name__ == "__main__":
    mcp.run()
