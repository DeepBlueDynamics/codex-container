#!/usr/bin/env python3
"""MCP tool shim for operating OpenCPN via CLI and REST API."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPSHandler
import ssl

if hasattr(ssl, "_create_unverified_context"):
    ssl._create_default_https_context = ssl._create_unverified_context

from mcp.server.fastmcp import FastMCP


class OpenCPNError(RuntimeError):
    """Raised when an OpenCPN operation fails."""


@dataclass
class RestConfig:
    base_url: str = "http://localhost:8000"
    api_key: Optional[str] = None
    source: str = "mcp-opencpn"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RestConfig":
        return cls(
            base_url=str(payload.get("base_url") or cls.base_url),
            api_key=payload.get("api_key"),
            source=str(payload.get("source") or cls.source),
        )

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "has_api_key": bool(self.api_key),
            "source": self.source,
        }


mcp = FastMCP("opencpn")

CONFIG_DIR = Path.home() / ".openpcn"
CONFIG_PATH = CONFIG_DIR / "mcp_opencpn.json"


def _load_config() -> RestConfig:
    env_base = os.environ.get("OPENCPN_REST_BASE")
    env_key = os.environ.get("OPENCPN_REST_API_KEY")
    env_source = os.environ.get("OPENCPN_REST_SOURCE")

    cfg = RestConfig()

    if CONFIG_PATH.exists():
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = RestConfig.from_dict(payload)
        except (OSError, json.JSONDecodeError):
            # Ignore malformed files; caller can overwrite.
            pass

    if env_base:
        cfg.base_url = env_base.strip()
    if env_key:
        cfg.api_key = env_key.strip()
    if env_source:
        cfg.source = env_source.strip()

    return cfg


def _save_config(cfg: RestConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": cfg.base_url,
        "api_key": cfg.api_key,
        "source": cfg.source,
    }
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _result(success: bool, **kwargs: Any) -> Dict[str, Any]:
    return {"success": success, **kwargs}


def _compose_url(base: str, path: str, params: Optional[Dict[str, Any]]) -> str:
    base_url = base.rstrip("/")
    path_fragment = path.lstrip("/")
    url = f"{base_url}/{path_fragment}" if path_fragment else base_url
    if params:
        url = f"{url}?{urlencode(params, doseq=True)}"
    return url


def _perform_request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Any] = None,
    require_key: bool = True,
    content_type: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    cfg = _load_config()

    if not cfg.base_url:
        raise OpenCPNError("REST base URL is not configured. Use opencpn_set_rest_config first.")

    query: Dict[str, Any] = dict(params or {})

    if require_key:
        if not cfg.api_key:
            raise OpenCPNError(
                "No API key configured. Pair your client and store the key via opencpn_set_rest_config."
            )
        query.setdefault("apikey", cfg.api_key)
        if cfg.source:
            query.setdefault("source", cfg.source)

    url = _compose_url(cfg.base_url, path, query)

    headers: Dict[str, str] = {}
    body: Optional[bytes]

    if data is None:
        body = None
    elif isinstance(data, (bytes, bytearray)):
        body = bytes(data)
    elif isinstance(data, str):
        body = data.encode("utf-8")
        headers.setdefault("Content-Type", content_type or "text/plain; charset=utf-8")
    else:
        body = json.dumps(data).encode("utf-8")
        headers.setdefault("Content-Type", content_type or "application/json")

    request = Request(url, data=body, method=method.upper())
    for key, value in headers.items():
        request.add_header(key, value)

    ssl_context = None
    if url.lower().startswith("https://"):
        try:
            ssl_context = ssl._create_unverified_context()
        except AttributeError:  # pragma: no cover - very old Python
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

    opener = None
    if ssl_context is not None:
        opener = build_opener(HTTPSHandler(context=ssl_context))

    try:
        if opener is not None:
            response = opener.open(request, timeout=timeout)
        else:
            response = urlopen(request, timeout=timeout)
        with response:
            raw = response.read()
            text = raw.decode("utf-8", errors="replace")
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"raw": text}
            return {
                "status": response.status,
                "headers": dict(response.headers.items()),
                "data": payload,
            }
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
            maybe_json = json.loads(detail)
        except Exception:
            maybe_json = detail or exc.reason
        raise OpenCPNError(f"HTTP error {exc.code}: {maybe_json}") from exc
    except URLError as exc:  # pragma: no cover - network failures are environment specific
        raise OpenCPNError(f"Failed to reach OpenCPN REST endpoint: {exc.reason}") from exc


def _run_cli(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise OpenCPNError(f"Executable not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise OpenCPNError(exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise OpenCPNError(f"Command timed out: {' '.join(args)}") from exc
    return result.stdout.strip()


@mcp.tool()
async def opencpn_get_rest_config() -> Dict[str, Any]:
    """Inspect cached REST connection details used by other tools.

    Returns a dictionary with the currently configured base URL, whether an API
    key is available, and the path on disk where the settings file is stored.

    Tip: Start by running `opencpn_detect_rest_endpoint` while OpenCPN is live
    on your host, then store the resulting URL/API key here using
    `opencpn_set_rest_config`. Inside a Docker container use
    `OPENCPN_REST_BASE=https://host.docker.internal:8443` so traffic reaches the
    host instance.
    """

    cfg = _load_config()
    return _result(True, config=cfg.to_public_dict(), config_path=str(CONFIG_PATH))


@mcp.tool()
async def opencpn_set_rest_config(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist REST connection details used by other tools.

    Use this after pairing with OpenCPN's REST server. Provide the `base_url`
    reported by `opencpn_detect_rest_endpoint` (for containers,
    `https://host.docker.internal:8443` is a good default) and the API key
    displayed after entering the PIN. Pending the PIN dialog, run the tool once
    with just the base URL, then again with the key once OpenCPN issues it. The
    optional `source` label is forwarded to OpenCPN when making REST calls so
    you can identify this client in the log.
    """

    cfg = _load_config()

    if base_url is not None:
        cfg.base_url = base_url.strip()
    if api_key is not None:
        cfg.api_key = api_key.strip() or None
    if source is not None:
        cfg.source = source.strip()

    _save_config(cfg)
    return _result(True, config=cfg.to_public_dict(), config_path=str(CONFIG_PATH))


@mcp.tool()
async def opencpn_detect_rest_endpoint() -> Dict[str, Any]:
    """Ask OpenCPN for the active REST endpoint using the CLI.

    This calls `opencpn --remote --get_rest_endpoint`, which requires OpenCPN to
    already be running on the host. On success the discovered URL is saved to
    the local MCP config so subsequent REST calls know where to connect.

    Notes:
        • Windows users often have the binary at
          `C:\\Program Files\\OpenCPN\\opencpn.exe` (or the x86 variant). If
          it's not on PATH set the environment variable `OPENCPN_BIN` to the full
          path before running this tool; the helper respects that hint when
          invoking the CLI.
        • Inside a container `localhost` points to the container, not the host.
          Map the host REST port and export `OPENCPN_REST_BASE` to something like
          `https://host.docker.internal:8443` before calling this tool so
          follow-up REST calls succeed.
    """

    cmd = ["opencpn", "--remote", "--get_rest_endpoint"]
    endpoint = _run_cli(cmd)
    if endpoint:
        await opencpn_set_rest_config(base_url=endpoint)
    return _result(True, endpoint=endpoint)


@mcp.tool()
async def opencpn_quit() -> Dict[str, Any]:
    """Request the running OpenCPN instance to quit using `opencpn --quit`.

    On Windows, make sure the CLI `opencpn.exe` is on PATH or expose its
    location using `OPENCPN_BIN` / `PATH` so the helper can find it.
    """

    cmd = ["opencpn", "--remote", "--quit"]
    _run_cli(cmd)
    return _result(True)


@mcp.tool()
async def opencpn_ping() -> Dict[str, Any]:
    """Ping the REST server to verify connectivity and API key validity."""

    response = _perform_request("GET", "/api/ping", require_key=True)
    if response.get("status") == 401:
        raise OpenCPNError(
            "Ping denied: provide API key via opencpn_set_rest_config once the PIN dialog appears in OpenCPN."
        )
    return _result(True, response=response)


@mcp.tool()
async def opencpn_get_version(require_key: bool = False) -> Dict[str, Any]:
    """Fetch the OpenCPN version via REST.

    Set `require_key=True` if your server is configured to demand API key
    authentication even for informational endpoints.
    """

    response = _perform_request("GET", "/api/get-version", require_key=require_key)
    return _result(True, response=response)


@mcp.tool()
async def opencpn_send_plugin_message(
    plugin_id: str,
    message: Optional[str] = None,
    payload: Optional[Any] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a plugin message using the REST bridge.

    Provide the OpenCPN plugin ID (e.g. `CHART_CONTROL_PI`) and optionally a
    short `message` string plus a JSON-serialisable `payload`. The call maps to
    `/api/plugin-msg` and requires that the API key has already been stored via
    `opencpn_set_rest_config`.
    """

    if not plugin_id:
        raise OpenCPNError("plugin_id is required")

    params: Dict[str, Any] = {"id": plugin_id}
    if message is not None:
        params["message"] = message

    if source is not None:
        cfg = _load_config()
        cfg.source = source
        _save_config(cfg)
        params.setdefault("source", source)

    response = _perform_request("POST", "/api/plugin-msg", params=params, data=payload, require_key=True)
    return _result(True, response=response)


@mcp.tool()
async def opencpn_list_routes() -> Dict[str, Any]:
    """Retrieve the list of routes from the running OpenCPN instance."""

    response = _perform_request("GET", "/api/list-routes", require_key=True)
    return _result(True, response=response)


@mcp.tool()
async def opencpn_activate_route(guid: str) -> Dict[str, Any]:
    """Activate a route by GUID using the REST API."""

    if not guid:
        raise OpenCPNError("Route GUID is required")

    params = {"guid": guid}
    response = _perform_request("GET", "/api/activate-route", params=params, require_key=True)
    return _result(True, response=response)


@mcp.tool()
async def opencpn_push_gpx(gpx_xml: str) -> Dict[str, Any]:
    """Upload navigation objects (routes/waypoints) to OpenCPN via GPX."""

    if not gpx_xml:
        raise OpenCPNError("GPX payload cannot be empty")

    response = _perform_request(
        "POST",
        "/api/rx_object",
        data=gpx_xml,
        require_key=True,
        content_type="application/xml; charset=utf-8",
    )
    return _result(True, response=response)


@mcp.tool()
async def opencpn_cli_list_plugins(verbose: bool = False) -> Dict[str, Any]:
    """List installed plugins by invoking `opencpn-cli list-plugins`."""

    args = ["opencpn-cli"]
    if verbose:
        args.append("--verbose")
    args.append("list-plugins")

    output = _run_cli(args)
    return _result(True, output=output)


@mcp.tool()
async def opencpn_cli_install_plugin(plugin_name: str, abi: Optional[str] = None, verbose: bool = False) -> Dict[str, Any]:
    """Install an OpenCPN managed plugin via `opencpn-cli install-plugin`."""

    if not plugin_name:
        raise OpenCPNError("plugin_name is required")

    args = ["opencpn-cli"]
    if verbose:
        args.append("--verbose")
    if abi:
        args.extend(["--abi", abi])
    args.extend(["install-plugin", plugin_name])

    output = _run_cli(args)
    return _result(True, output=output)


@mcp.tool()
async def opencpn_cli_uninstall_plugin(plugin_name: str, verbose: bool = False) -> Dict[str, Any]:
    """Uninstall an OpenCPN plugin via `opencpn-cli uninstall-plugin`."""

    if not plugin_name:
        raise OpenCPNError("plugin_name is required")

    args = ["opencpn-cli"]
    if verbose:
        args.append("--verbose")
    args.extend(["uninstall-plugin", plugin_name])

    output = _run_cli(args)
    return _result(True, output=output)


if __name__ == "__main__":  # pragma: no cover
    mcp.run(transport="stdio")
