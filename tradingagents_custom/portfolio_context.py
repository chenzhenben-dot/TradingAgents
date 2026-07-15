"""Read the user's portfolio and build context strings for the LLM.

The portfolio lives at ``~/.tradingagents/portfolio.json`` (user-editable,
not committed). This module is read-only — it never mutates positions.

Schema (all fields optional except ``ticker``):
{
  "ticker": "AAOX",
  "qty": 137,
  "avg_cost": 31.01,
  "current_price": 19.54,            // optional, for derived fields
  "rules": {
    "stop": 15.50,
    "trim_zones": [24.00, 26.00],
    "add_zones": [60, 65]
  },
  "notes": "Opened 6/16. DCA'd down 6 times. Framework: Underweight."
}
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".tradingagents" / "portfolio.json"


def load_portfolio(path: str | os.PathLike | None = None) -> dict[str, dict[str, Any]]:
    """Load portfolio from JSON. Returns ``{}`` on missing/invalid file."""
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        logger.info("portfolio_context: no portfolio file at %s", p)
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("portfolio_context: %s did not contain a dict, got %s", p, type(data).__name__)
            return {}
        return data
    except Exception as exc:
        logger.warning("portfolio_context: failed to load %s: %s", p, exc)
        return {}


def build_portfolio_context(ticker: str, portfolio: dict[str, dict[str, Any]] | None = None) -> str:
    """Return a formatted string describing the user's current position in ``ticker``.

    Empty string if the user has no position. Designed to be injected into
    the LLM state so analysts can factor in cost basis, P&L, and user-set
    rules when forming their judgment.
    """
    if portfolio is None:
        portfolio = load_portfolio()
    pos = portfolio.get(ticker.upper())
    if not pos:
        return ""

    qty = pos.get("qty", 0)
    avg_cost = pos.get("avg_cost")
    current = pos.get("current_price")
    rules = pos.get("rules", {}) or {}
    notes = pos.get("notes", "")

    lines = [f"USER PORTFOLIO CONTEXT for {ticker.upper()}:"]

    if qty:
        lines.append(f"- Position: {qty} shares @ avg cost ${avg_cost}")
        cost_basis = qty * (avg_cost or 0)
        if current and avg_cost:
            mv = qty * current
            pnl = mv - cost_basis
            pnl_pct = (pnl / cost_basis) * 100 if cost_basis else 0
            lines.append(
                f"- Market value: ${mv:,.0f}  |  Cost basis: ${cost_basis:,.0f}  |  "
                f"Unrealized P&L: ${pnl:+,.0f} ({pnl_pct:+.1f}%)"
            )
        elif cost_basis:
            lines.append(f"- Cost basis: ${cost_basis:,.0f}")

    if rules.get("stop") is not None:
        lines.append(f"- Hard stop user set: ${rules['stop']}")
    if rules.get("trim_zones"):
        zones = ", ".join(f"${z}" for z in rules["trim_zones"])
        lines.append(f"- Trim zones user set: {zones}")
    if rules.get("add_zones"):
        zones = ", ".join(f"${z}" for z in rules["add_zones"])
        lines.append(f"- Add zones user set: {zones}")
    if notes:
        lines.append(f"- User notes: {notes}")

    lines.append(
        "This is the user's *existing* position. Factor it into your analysis: "
        "an Underweight on a 37%-underwater position is not the same as an "
        "Underweight on a fresh entry."
    )
    return "\n".join(lines)


def build_leverage_context(leverage_info: dict[str, Any], portfolio: dict[str, dict[str, Any]] | None = None) -> str:
    """Return a context string if the user is currently holding a leveraged ETF.

    Empty string if the user is not exposed. Helps the framework connect
    "you own AAOX" to "AAOX is a 2X long ETF" without the user manually
    stitching them together.
    """
    if portfolio is None:
        portfolio = load_portfolio()
    if not leverage_info.get("is_leveraged"):
        return ""
    underlying = (leverage_info.get("underlying") or "").upper()
    held_etf = any(t.upper() in portfolio for t in (leverage_info.get("ticker", ""),))
    held_underlying = underlying and underlying in portfolio
    if not (held_etf or held_underlying):
        return ""
    parts = ["USER ALSO HOLDS:"]
    if held_etf:
        pos = portfolio[leverage_info["ticker"].upper()]
        parts.append(
            f"- The leveraged ETF itself: {pos.get('qty')} shares @ ${pos.get('avg_cost')}"
        )
    if held_underlying:
        pos = portfolio[underlying]
        parts.append(
            f"- The underlying ({underlying}): {pos.get('qty')} shares @ ${pos.get('avg_cost')}"
        )
    parts.append(
        "If the framework says the underlying has structural issues, the leveraged "
        "ETF inherits those issues at 2X the volatility — user's effective risk "
        "is double-counted if both positions are large."
    )
    return "\n".join(parts)
