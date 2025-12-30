#!/usr/bin/env python3
"""
MCP server: Simple multi-portfolio tracker with cash + buy/sell lots.

Design:
- Multiple named portfolios.
- One open lot per symbol at a time (enforced).
- Cash tracked in USD.
- Populate pulls latest prices (Stooq by default, Finnhub if key available).
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("portfolio")

DATA_PATH = Path("data/portfolio.json")
STOOQ_URL = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
FINNHUB_URL = "https://finnhub.io/api/v1/quote?symbol={symbol}&token={token}"
FINNHUB_ENV_FILE = ".finnhub.env"


def _utc_iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _normalize_stooq_symbol(symbol: str, assume_us: bool) -> str:
    sym = symbol.strip()
    if assume_us and "." not in sym:
        sym = f"{sym}.us"
    return sym.lower()


def _fetch_stooq(symbol: str, assume_us: bool) -> Dict[str, Any]:
    stooq_symbol = _normalize_stooq_symbol(symbol, assume_us)
    url = STOOQ_URL.format(symbol=stooq_symbol)
    req = Request(url, headers={"User-Agent": "codex-container/portfolio"})
    with urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8", errors="ignore")

    reader = csv.DictReader(text.splitlines())
    row = next(reader, None)
    if not row:
        return {"success": False, "error": "empty_response", "source": "stooq"}

    def _num(val: str) -> Optional[float]:
        try:
            return float(val)
        except Exception:
            return None

    date = row.get("Date") or ""
    time_str = row.get("Time") or ""
    ts = None
    if date:
        try:
            dt = datetime.strptime(f"{date} {time_str}".strip(), "%Y-%m-%d %H:%M:%S")
            ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            ts = None

    return {
        "success": True,
        "source": "stooq",
        "symbol": symbol,
        "symbol_resolved": stooq_symbol,
        "timestamp_utc": _utc_iso(ts),
        "open": _num(row.get("Open", "")),
        "high": _num(row.get("High", "")),
        "low": _num(row.get("Low", "")),
        "close": _num(row.get("Close", "")),
    }


def _fetch_finnhub(symbol: str, token: str) -> Dict[str, Any]:
    url = FINNHUB_URL.format(symbol=symbol, token=token)
    req = Request(url, headers={"User-Agent": "codex-container/portfolio"})
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        return {
            "success": False,
            "source": "finnhub",
            "error": f"http_{exc.code}",
            "details": body.strip() or None,
        }
    except URLError as exc:
        return {
            "success": False,
            "source": "finnhub",
            "error": "network_error",
            "details": str(exc),
        }

    try:
        data = json.loads(raw)
    except Exception:
        return {"success": False, "error": "invalid_json", "source": "finnhub", "details": raw[:200]}

    if not isinstance(data, dict):
        return {"success": False, "error": "invalid_response", "source": "finnhub"}

    if "error" in data:
        return {"success": False, "error": data.get("error"), "source": "finnhub"}

    price = data.get("c")
    if price is None:
        return {"success": False, "error": "missing_price", "source": "finnhub", "details": data}

    ts = int(data.get("t") or 0)
    return {
        "success": True,
        "source": "finnhub",
        "symbol": symbol,
        "timestamp_utc": _utc_iso(ts),
        "open": data.get("o"),
        "high": data.get("h"),
        "low": data.get("l"),
        "close": data.get("c"),
        "previous_close": data.get("pc"),
    }


def _get_finnhub_key() -> Optional[str]:
    token = os.getenv("FINNHUB_API_KEY")
    if token:
        return token
    if not Path(FINNHUB_ENV_FILE).exists():
        return None
    try:
        text = Path(FINNHUB_ENV_FILE).read_text(encoding="utf-8")
    except Exception:
        return None
    for line in text.splitlines():
        if line.startswith("FINNHUB_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def _fetch_price(symbol: str, prefer: str, assume_us: bool) -> Dict[str, Any]:
    prefer = prefer.lower().strip()
    warnings: List[str] = []
    token = _get_finnhub_key()

    if prefer in ("finnhub", "auto") and token:
        try:
            result = _fetch_finnhub(symbol, token)
            if result.get("success"):
                result["warnings"] = warnings
                return result
            err = result.get("error") or "unknown_error"
            detail = result.get("details")
            if detail:
                warnings.append(f"finnhub_failed:{err}:{detail}")
            else:
                warnings.append(f"finnhub_failed:{err}")
        except (HTTPError, URLError, TimeoutError) as exc:
            warnings.append(f"finnhub_error:{exc}")

    if prefer == "finnhub":
        return {"success": False, "source": "finnhub", "error": "finnhub_unavailable_or_failed", "warnings": warnings}

    try:
        result = _fetch_stooq(symbol, assume_us)
        result["warnings"] = warnings
        return result
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"success": False, "source": "stooq", "error": str(exc), "warnings": warnings}


def _load() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        return {"portfolios": {}}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"portfolios": {}}


def _save(data: Dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_portfolio(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    portfolios = data.setdefault("portfolios", {})
    if name not in portfolios:
        portfolios[name] = {"cash": 0.0, "positions": [], "closed": []}
    return portfolios[name]


def _find_open_position(portfolio: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    for pos in portfolio.get("positions", []):
        if pos.get("symbol", "").upper() == symbol.upper():
            return pos
    return None


@mcp.tool()
def portfolio_init(name: str, cash: float = 0.0) -> Dict[str, Any]:
    data = _load()
    if name in data.get("portfolios", {}):
        return {"success": False, "error": "portfolio_exists", "name": name}
    data["portfolios"] = data.get("portfolios", {})
    data["portfolios"][name] = {"cash": float(cash), "positions": [], "closed": []}
    _save(data)
    return {"success": True, "name": name, "cash": float(cash)}


@mcp.tool()
def portfolio_list(name: Optional[str] = None) -> Dict[str, Any]:
    data = _load()
    portfolios = data.get("portfolios", {})
    if not name:
        return {"success": True, "portfolios": list(portfolios.keys())}
    if name not in portfolios:
        return {"success": False, "error": "portfolio_not_found", "name": name}
    return {"success": True, "name": name, "portfolio": portfolios[name]}


@mcp.tool()
def portfolio_rename(old_name: str, new_name: str) -> Dict[str, Any]:
    data = _load()
    portfolios = data.get("portfolios", {})
    if old_name not in portfolios:
        return {"success": False, "error": "portfolio_not_found", "name": old_name}
    if new_name in portfolios:
        return {"success": False, "error": "portfolio_exists", "name": new_name}
    portfolios[new_name] = portfolios.pop(old_name)
    _save(data)
    return {"success": True, "old_name": old_name, "new_name": new_name}


@mcp.tool()
def portfolio_add_note(
    name: str,
    symbol: str,
    note: str,
    kind: str = "note",
    url: Optional[str] = None,
    source: Optional[str] = None,
    include_closed: bool = False,
) -> Dict[str, Any]:
    """
    Append a timestamped note to a position. Notes can be thesis/news/etc.
    """
    if not note or not note.strip():
        return {"success": False, "error": "empty_note"}

    data = _load()
    portfolio = _get_portfolio(data, name)
    symbol = symbol.upper()

    pos = _find_open_position(portfolio, symbol)
    if not pos and include_closed:
        for closed in portfolio.get("closed", []):
            if closed.get("symbol") == symbol:
                pos = closed
                break

    if not pos:
        return {"success": False, "error": "position_not_found", "symbol": symbol}

    entry = {
        "timestamp": _now_iso(),
        "kind": (kind or "note").strip(),
        "note": note.strip(),
    }
    if url:
        entry["url"] = url
    if source:
        entry["source"] = source

    pos.setdefault("notes", []).append(entry)
    _save(data)
    return {"success": True, "name": name, "symbol": symbol, "note": entry}


@mcp.tool()
def portfolio_add_cash(name: str, amount: float, note: Optional[str] = None) -> Dict[str, Any]:
    data = _load()
    portfolio = _get_portfolio(data, name)
    portfolio["cash"] = float(portfolio.get("cash", 0.0)) + float(amount)
    if note:
        portfolio.setdefault("cash_notes", []).append({"amount": float(amount), "note": note, "date": _utc_iso(int(datetime.now(tz=timezone.utc).timestamp()))})
    _save(data)
    return {"success": True, "name": name, "cash": portfolio["cash"]}


@mcp.tool()
def portfolio_buy(
    name: str,
    symbol: str,
    quantity: float,
    buy_price: float,
    buy_date: str,
    fees: float = 0.0,
) -> Dict[str, Any]:
    data = _load()
    portfolio = _get_portfolio(data, name)

    if _find_open_position(portfolio, symbol):
        return {"success": False, "error": "position_already_open", "symbol": symbol}

    cost = float(quantity) * float(buy_price) + float(fees)
    cash = float(portfolio.get("cash", 0.0))
    if cost > cash:
        return {"success": False, "error": "insufficient_cash", "cash": cash, "cost": cost}

    pos = {
        "symbol": symbol.upper(),
        "quantity": float(quantity),
        "buy_price": float(buy_price),
        "buy_date": buy_date,
        "fees": float(fees),
        "status": "open",
        "notes": [],
    }
    portfolio.setdefault("positions", []).append(pos)
    portfolio["cash"] = cash - cost
    _save(data)
    return {"success": True, "name": name, "position": pos, "cash": portfolio["cash"]}


@mcp.tool()
def portfolio_sell(
    name: str,
    symbol: str,
    quantity: float,
    sell_price: float,
    sell_date: str,
    fees: float = 0.0,
) -> Dict[str, Any]:
    data = _load()
    portfolio = _get_portfolio(data, name)
    pos = _find_open_position(portfolio, symbol)
    if not pos:
        return {"success": False, "error": "position_not_found", "symbol": symbol}

    if float(quantity) != float(pos.get("quantity", 0.0)):
        return {"success": False, "error": "full_close_required", "expected_qty": pos.get("quantity"), "provided_qty": quantity}

    proceeds = float(quantity) * float(sell_price) - float(fees)
    cost_basis = float(pos.get("quantity")) * float(pos.get("buy_price")) + float(pos.get("fees", 0.0))
    realized_pl = proceeds - cost_basis

    pos["status"] = "closed"
    pos["sell_price"] = float(sell_price)
    pos["sell_date"] = sell_date
    pos["sell_fees"] = float(fees)
    pos["realized_pl"] = realized_pl

    portfolio["positions"] = [p for p in portfolio.get("positions", []) if p is not pos]
    portfolio.setdefault("closed", []).append(pos)
    portfolio["cash"] = float(portfolio.get("cash", 0.0)) + proceeds

    _save(data)
    return {"success": True, "name": name, "closed": pos, "cash": portfolio["cash"]}


@mcp.tool()
def portfolio_populate(
    name: str,
    prefer: str = "auto",
    assume_us: bool = True,
) -> Dict[str, Any]:
    data = _load()
    portfolio = _get_portfolio(data, name)
    positions = portfolio.get("positions", [])

    holdings = []
    total_value = 0.0
    total_cost = 0.0
    errors = []

    for pos in positions:
        symbol = pos.get("symbol")
        price = _fetch_price(symbol, prefer, assume_us)
        if not price.get("success"):
            errors.append(
                {
                    "symbol": symbol,
                    "error": price.get("error"),
                    "source": price.get("source"),
                    "warnings": price.get("warnings"),
                    "details": price.get("details"),
                }
            )
            continue

        last = price.get("close")
        qty = float(pos.get("quantity", 0.0))
        basis = qty * float(pos.get("buy_price", 0.0)) + float(pos.get("fees", 0.0))
        value = qty * float(last)
        pl = value - basis
        pl_pct = (pl / basis) * 100.0 if basis else 0.0

        holdings.append(
            {
                "symbol": symbol,
                "quantity": qty,
                "buy_price": pos.get("buy_price"),
                "buy_date": pos.get("buy_date"),
                "last": last,
                "value": value,
                "cost_basis": basis,
                "unrealized_pl": pl,
                "unrealized_pl_pct": pl_pct,
                "quote_source": price.get("source"),
                "quote_time": price.get("timestamp_utc"),
            }
        )
        total_value += value
        total_cost += basis

    cash = float(portfolio.get("cash", 0.0))
    total_equity = cash + total_value
    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost) * 100.0 if total_cost else 0.0

    return {
        "success": True,
        "name": name,
        "cash": cash,
        "holdings": holdings,
        "totals": {
            "invested": total_cost,
            "holdings_value": total_value,
            "total_equity": total_equity,
            "unrealized_pl": total_pl,
            "unrealized_pl_pct": total_pl_pct,
        },
        "errors": errors,
    }


if __name__ == "__main__":
    mcp.run()
