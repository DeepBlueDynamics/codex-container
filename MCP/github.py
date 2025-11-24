#!/usr/bin/env python3
"""MCP: github

GitHub API integration for managing issues, PRs, and repositories.
Now fully async (aiohttp), supports Enterprise base override, status checks,
pagination helpers, and a broader set of operations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("github")

CONFIG_FILE = Path(__file__).resolve().parent.parent / ".github-discussion.env"
DISCUSSIONS_TOKEN_KEY = "GITHUB_DISCUSSIONS_TOKEN"


def _read_discussion_env() -> Dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}
    values: Dict[str, str] = {}
    try:
        for raw in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def _get_token() -> Optional[str]:
    """Get GitHub token from environment.

    Checks common variables in order: GITHUB_TOKEN, GH_TOKEN.
    Falls back to the saved .github-discussion.env token so both
    GitHub MCP tools share credentials.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    env_values = _read_discussion_env()
    return env_values.get(DISCUSSIONS_TOKEN_KEY)


def _get_api_base() -> str:
    """Base URL for GitHub API (supports GH Enterprise via GITHUB_API_BASE)."""
    return os.environ.get("GITHUB_API_BASE", "https://api.github.com")


def _get_headers() -> Dict[str, str]:
    token = _get_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "codex-mcp/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _api_request(
    method: str,
    endpoint: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Any] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    url = f"{_get_api_base()}{endpoint}"
    headers = _get_headers()
    try:
        timeout_cfg = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.request(
                method, url, headers=headers, params=params, json=json, data=data
            ) as resp:
                text = await resp.text()
                ok = 200 <= resp.status < 300
                try:
                    payload = await resp.json(content_type=None) if text else {}
                except Exception:
                    payload = {"raw": text}
                if ok:
                    return {"success": True, "data": payload}
                return {
                    "success": False,
                    "status_code": resp.status,
                    "error": payload.get("message") if isinstance(payload, dict) else text,
                    "data": payload,
                }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _paginate(
    endpoint: str,
    *,
    base_params: Optional[Dict[str, Any]] = None,
    per_page: int = 30,
    max_pages: int = 1,
    timeout: int = 15,
) -> Tuple[List[Any], int]:
    items: List[Any] = []
    page = 1
    total_pages = 0
    while page <= max_pages:
        params = dict(base_params or {})
        params.update({"per_page": min(max(1, per_page), 100), "page": page})
        resp = await _api_request("GET", endpoint, params=params, timeout=timeout)
        if not resp.get("success"):
            return items, page - 1
        batch = resp.get("data") or []
        if not isinstance(batch, list):
            break
        if not batch:
            break
        items.extend(batch)
        page += 1
        total_pages += 1
    return items, total_pages


@mcp.tool()
async def github_status() -> Dict[str, Any]:
    """Report GitHub API connectivity and authentication state.

    Returns dict with `api_base`, `token_present`, and optional `login` if the
    token can hit `/user`. Includes status info on errors.
    """
    token = _get_token()
    base = _get_api_base()
    out: Dict[str, Any] = {"success": True, "api_base": base, "token_present": bool(token)}
    if not token:
        out["message"] = "No GitHub token found in env (set GITHUB_TOKEN or GH_TOKEN)"
        return out
    ping = await _api_request("GET", "/user")
    out["reachable"] = ping.get("success", False)
    if ping.get("success"):
        data = ping.get("data", {})
        out["login"] = data.get("login")
    else:
        out["error"] = ping.get("error")
        out["status_code"] = ping.get("status_code")
    return out


# -------------------- Issues --------------------
@mcp.tool()
async def github_get_issue(owner: str, repo: str, issue_number: int) -> Dict[str, Any]:
    """Fetch a single issue with metadata such as labels and assignees."""
    return await _api_request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")


@mcp.tool()
async def github_list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    labels: Optional[str] = None,
    assignee: Optional[str] = None,
    creator: Optional[str] = None,
    since: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
    max_pages: int = 1,
) -> Dict[str, Any]:
    """List repository issues using standard filters and pagination.

    Returns `issues` plus `count`, and `pages` when multi-page fetches occur.
    """
    base_params: Dict[str, Any] = {"state": state}
    if labels:
        base_params["labels"] = labels
    if assignee:
        base_params["assignee"] = assignee
    if creator:
        base_params["creator"] = creator
    if since:
        base_params["since"] = since
    if max_pages <= 1 and page > 1:
        base_params["page"] = page
        resp = await _api_request(
            "GET", f"/repos/{owner}/{repo}/issues", params={**base_params, "per_page": min(per_page, 100)}
        )
        if resp.get("success") and isinstance(resp.get("data"), list):
            return {"success": True, "count": len(resp["data"]), "issues": resp["data"]}
        return resp
    items, pages = await _paginate(
        f"/repos/{owner}/{repo}/issues", base_params=base_params, per_page=per_page, max_pages=max_pages
    )
    return {"success": True, "count": len(items), "issues": items, "pages": pages}


@mcp.tool()
async def github_create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new issue with optional body, labels, and assignees."""
    payload: Dict[str, Any] = {"title": title, "body": body}
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees
    return await _api_request("POST", f"/repos/{owner}/{repo}/issues", json=payload)


@mcp.tool()
async def github_update_issue(
    owner: str,
    repo: str,
    issue_number: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    state: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update mutable issue fields; omit params to leave them unchanged."""
    payload: Dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees
    return await _api_request("PATCH", f"/repos/{owner}/{repo}/issues/{issue_number}", json=payload)


@mcp.tool()
async def github_add_comment(owner: str, repo: str, issue_number: int, body: str) -> Dict[str, Any]:
    """Add a comment to an issue or pull request thread."""
    return await _api_request(
        "POST", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", json={"body": body}
    )


# -------------------- Pull Requests --------------------
@mcp.tool()
async def github_list_prs(
    owner: str,
    repo: str,
    state: str = "open",
    base: Optional[str] = None,
    head: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
    max_pages: int = 1,
) -> Dict[str, Any]:
    """List pull requests filtered by state/base/head with pagination."""
    params: Dict[str, Any] = {"state": state}
    if base:
        params["base"] = base
    if head:
        params["head"] = head
    if max_pages <= 1 and page > 1:
        params["page"] = page
        resp = await _api_request(
            "GET", f"/repos/{owner}/{repo}/pulls", params={**params, "per_page": min(per_page, 100)}
        )
        if resp.get("success") and isinstance(resp.get("data"), list):
            return {"success": True, "count": len(resp["data"]), "pulls": resp["data"]}
        return resp
    items, pages = await _paginate(
        f"/repos/{owner}/{repo}/pulls", base_params=params, per_page=per_page, max_pages=max_pages
    )
    return {"success": True, "count": len(items), "pulls": items, "pages": pages}


@mcp.tool()
async def github_get_pr(owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
    """Return metadata for a single pull request."""
    return await _api_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")


@mcp.tool()
async def github_create_pr(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    draft: bool = False,
    maintainer_can_modify: bool = True,
) -> Dict[str, Any]:
    """Open a pull request; supports draft flag and maintainer override."""
    payload = {
        "title": title,
        "head": head,
        "base": base,
        "body": body,
        "draft": draft,
        "maintainer_can_modify": maintainer_can_modify,
    }
    return await _api_request("POST", f"/repos/{owner}/{repo}/pulls", json=payload)


@mcp.tool()
async def github_update_pr(
    owner: str,
    repo: str,
    pr_number: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    state: Optional[str] = None,
    base: Optional[str] = None,
) -> Dict[str, Any]:
    """Update PR fields such as title/body/state/base."""
    payload: Dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state
    if base is not None:
        payload["base"] = base
    return await _api_request("PATCH", f"/repos/{owner}/{repo}/pulls/{pr_number}", json=payload)


@mcp.tool()
async def github_merge_pr(
    owner: str,
    repo: str,
    pr_number: int,
    merge_method: str = "merge",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
    sha: Optional[str] = None,
    admin_merge: bool = False,
) -> Dict[str, Any]:
    """Merge a PR using merge/squash/rebase with optional commit overrides."""
    payload: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title is not None:
        payload["commit_title"] = commit_title
    if commit_message is not None:
        payload["commit_message"] = commit_message
    if sha is not None:
        payload["sha"] = sha
    if admin_merge:
        payload["admin"] = True
    return await _api_request("PUT", f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", json=payload)


# -------------------- Labels --------------------
@mcp.tool()
async def github_list_labels(
    owner: str, repo: str, per_page: int = 100, page: int = 1, max_pages: int = 1
) -> Dict[str, Any]:
    """List repository labels, handling pagination for large sets."""
    if max_pages <= 1 and page > 1:
        resp = await _api_request(
            "GET", f"/repos/{owner}/{repo}/labels", params={"per_page": min(per_page, 100), "page": page}
        )
        if resp.get("success") and isinstance(resp.get("data"), list):
            return {"success": True, "count": len(resp["data"]), "labels": resp["data"]}
        return resp
    items, pages = await _paginate(f"/repos/{owner}/{repo}/labels", per_page=per_page, max_pages=max_pages)
    return {"success": True, "count": len(items), "labels": items, "pages": pages}


@mcp.tool()
async def github_add_labels(owner: str, repo: str, issue_number: int, labels: List[str]) -> Dict[str, Any]:
    """Attach existing labels to an issue or pull request."""
    return await _api_request(
        "POST", f"/repos/{owner}/{repo}/issues/{issue_number}/labels", json={"labels": labels}
    )


@mcp.tool()
async def github_create_label(
    owner: str, repo: str, name: str, color: str = "ededed", description: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new label with optional description."""
    payload: Dict[str, Any] = {"name": name, "color": color}
    if description is not None:
        payload["description"] = description
    return await _api_request("POST", f"/repos/{owner}/{repo}/labels", json=payload)


if __name__ == "__main__":
    mcp.run()
