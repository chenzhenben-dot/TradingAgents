"""Detect leveraged / inverse ETFs and emit explicit warnings.

The upstream framework treats ETFs the same as single stocks, which causes
problems for instruments like AAOX (2X long AAOI) where:
- ATR is typically 2-3x the underlying's ATR
- daily reset + volatility drag makes position sizing and stops useless
- the "fundamentals" tab returns nothing useful

This module provides:
- detect_leveraged_etf(ticker) -> dict with leverage, type, underlying, atr_ratio
- leverage_warning_text(info) -> formatted string the LLM prompt can prepend
"""
from __future__ import annotations

import logging
import re
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# Heuristic: 2x/3x daily-reset ETFs have name patterns like "2X Long", "3x Short",
# "Ultra", "UltraPro", "Direxion Daily", etc. We also fall back to a curated
# issuer list for confirmation.
LEVERAGE_KEYWORDS = (
    r"\b(2x|3x|2\xd7|3\xd7)\b",  # 2X / 3X (incl. unicode multiplier sign)
    r"\b(ultra|ultraPro|inverse|leveraged|daily)\b",
)
LEVERAGE_ISSUERS = (
    "Tradr",
    "GraniteShares",
    "Direxion",
    "ProShares",
    "Simplify",
    "AXS",
    "T-Rex",
    "REX",
    "Maxi",
    "Volatility Shares",
)

_LEVERAGE_RE = [re.compile(p, re.IGNORECASE) for p in LEVERAGE_KEYWORDS]


def detect_leveraged_etf(ticker: str) -> dict[str, Any]:
    """Return a dict describing whether ``ticker`` is a leveraged/inverse ETF.

    Keys:
        is_leveraged (bool)
        leverage_ratio (str | None)        "2X", "3X", "Inverse", "Ultra", etc.
        direction (str | None)             "long" / "short" / "unknown"
        underlying (str | None)            best-effort guess of underlying ticker
        atr_pct (float | None)             14-day ATR as fraction of price
        quote_type (str | None)
        raw_name (str | None)
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as exc:
        logger.warning("leverage_detector: could not load info for %s: %s", ticker, exc)
        return {"is_leveraged": False, "ticker": ticker, "error": str(exc)}

    quote_type = info.get("quoteType")
    name = (info.get("longName") or info.get("shortName") or "") or ""
    name_lower = name.lower()
    issuer = (info.get("fundFamily") or info.get("brandName") or "")

    is_leveraged = quote_type == "ETF" and (
        any(p.search(name) for p in _LEVERAGE_RE)
        or any(iss in (issuer + name) for iss in LEVERAGE_ISSUERS)
    )

    leverage_ratio = None
    direction = None
    underlying = None
    if is_leveraged:
        m = re.search(r"\b(2x|3x|2\xd7|3\xd7|ultra|ultrapro|inverse)\b", name_lower)
        if m:
            tok = m.group(1).lower()
            if tok in ("2x", "2\xd7"):
                leverage_ratio = "2X"
            elif tok in ("3x", "3\xd7"):
                leverage_ratio = "3X"
            elif tok == "ultra":
                leverage_ratio = "Ultra (typically 2X)"
            elif tok == "ultrapro":
                leverage_ratio = "UltraPro (typically 3X)"
            else:
                leverage_ratio = tok
        if "short" in name_lower or "inverse" in name_lower:
            direction = "short"
        elif "long" in name_lower or "bull" in name_lower:
            direction = "long"
        else:
            direction = "unknown"

        # Best-effort underlying: usually the all-caps token after "Long" / "Short"
        # Strategy: greedily consume ALL direction words first, so we land
        # on the ticker (e.g. AAOI) rather than the "L" of "Long".
        m2 = re.search(
            r"(?i)(?:\b(?:long|short|bull|bear|inverse|leveraged|daily|ultra|2x|3x)\b[\s\-]+)+"
            r"([A-Z][A-Z0-9\.\-]{0,4})\b",
            name,
        )
        if m2:
            underlying = m2.group(1).upper()

    # ATR as fraction of price
    atr_pct = None
    try:
        hist = t.history(period="1mo")
        if not hist.empty and len(hist) >= 14:
            atr = (hist["High"] - hist["Low"]).tail(14).mean()
            last = hist["Close"].iloc[-1]
            if last:
                atr_pct = float(atr / last)
    except Exception:
        pass

    return {
        "is_leveraged": is_leveraged,
        "ticker": ticker,
        "leverage_ratio": leverage_ratio,
        "direction": direction,
        "underlying": underlying,
        "atr_pct": atr_pct,
        "quote_type": quote_type,
        "raw_name": name,
    }


def leverage_warning_text(info: dict[str, Any]) -> str:
    """Format a leverage-ETF warning as a string for LLM prompts.

    Empty string if not leveraged — safe to always include in the prompt.
    """
    if not info.get("is_leveraged"):
        return ""
    parts = [
        "!!! LEVERAGED ETF WARNING !!!",
        f"Ticker: {info['ticker']} is a {info.get('leverage_ratio') or 'leveraged'} {info.get('direction') or 'unknown'} ETF.",
        f"Underlying: {info.get('underlying') or 'unknown'}.",
    ]
    if info.get("atr_pct") is not None:
        parts.append(f"ATR/price ratio: {info['atr_pct']*100:.1f}% (extreme volatility; conventional stops unreliable).")
    parts += [
        "Structural constraints:",
        "- Daily reset compounds volatility drag in choppy markets",
        "- 2X/3X moves are vs PRIOR day close, not in real-time",
        "- Bid-ask spreads are wider than underlying",
        "- Not suitable for long-term holds; for tactical trades only",
        "",
        "Framework guidance:",
        "- Recommend position size <= 2-3% of portfolio (not 8-12%)",
        "- Recommend HARD stop loss at 50-day SMA or -20%, whichever is closer",
        "- Recommend NO averaging down — the leverage amplifies losses",
        "- For long-term exposure to the underlying, buy the underlying directly",
    ]
    return "\n".join(parts)
