"""Chip / holder data for the underlying asset of any ticker.

Pulls institutional, insider, and short-interest data via yfinance so it works
without a VPN. Designed to be used as a single LLM tool that returns a
formatted string the analyst can read directly.

For leveraged ETFs (no fundamentals), resolves to the underlying before
fetching — so analyzing AAOX automatically surfaces AAOI's holders.
"""
from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_call(label: str, fn):
    """Run ``fn`` and return either its result or a short failure string."""
    try:
        result = fn()
        if result is None or (hasattr(result, "empty") and result.empty):
            return f"{label}: no data available"
        return result
    except Exception as exc:
        return f"{label}: unavailable ({type(exc).__name__}: {exc})"


def _resolve_underlying(ticker: str) -> tuple[str, dict[str, Any]]:
    """For ETFs, return the underlying ticker (best-effort). Otherwise identity.

    yfinance exposes `.info` even for ETFs; the underlying symbol is usually
    in the long name or summaryProfile. We fall back to a small heuristic for
    common leveraged single-stock ETFs (Tradr / GraniteShares / Direxion).
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        quote_type = info.get("quoteType", "")
        long_name = (info.get("longName") or info.get("shortName") or "").lower()
        if quote_type == "ETF" and any(k in long_name for k in ("2x", "3x", "long", "short", "leveraged", "ultra", "inverse")):
            # Heuristic: "2X Long AAOI" -> AAOI.
            # Strategy: greedily consume ALL direction words first, so we land
            # on the ticker (e.g. AAOI) rather than the "L" of "Long".
            import re

            m = re.search(
                r"(?i)(?:\b(?:long|short|bull|bear|inverse|leveraged|daily|ultra|2x|3x)\b[\s\-]+)+"
                r"([A-Z][A-Z0-9\.\-]{0,4})\b",
                long_name,
            )
            if m:
                return m.group(1).upper(), info
        return ticker, info
    except Exception:
        return ticker, {}


def get_institutional_holders(ticker: str) -> str:
    """Top 10 institutional holders with % change (quarterly, delayed ~45 days)."""
    def _fetch():
        t = yf.Ticker(ticker)
        df = t.institutional_holders
        if df is None or df.empty:
            return None
        cols = [c for c in ("Holder", "pctHeld", "pctChange", "Value") if c in df.columns]
        return df[cols].head(10)

    data = _safe_call("institutional_holders", _fetch)
    if isinstance(data, str):
        return data
    return f"Top {len(data)} institutional holders (most recent 13F, ~45-day delay):\n" + data.to_string(index=False)


def get_insider_transactions(ticker: str) -> str:
    """Recent insider Form 4 transactions (yfinance aggregates SEC filings)."""
    def _fetch():
        t = yf.Ticker(ticker)
        df = t.insider_transactions
        if df is None or df.empty:
            return None
        cols = [c for c in ("Insider", "Transaction", "Shares", "Value", "Start Date") if c in df.columns]
        return df[cols].head(10)

    data = _safe_call("insider_transactions", _fetch)
    if isinstance(data, str):
        return data
    return f"Recent insider transactions (last {len(data)} Form 4 filings):\n" + data.to_string(index=False)


def get_short_interest(ticker: str) -> str:
    """Short interest summary from yfinance (limited but free)."""
    def _fetch():
        t = yf.Ticker(ticker)
        info = t.info or {}
        fields = {
            "shortPercentOfFloat": info.get("shortPercentOfFloat"),
            "shortRatio": info.get("shortRatio"),
            "shortPercentOfSharesOutstanding": info.get("shortPercentOfSharesOutstanding"),
            "floatShares": info.get("floatShares"),
            "sharesOutstanding": info.get("sharesOutstanding"),
            "heldPercentInstitutions": info.get("heldPercentInstitutions"),
            "heldPercentInsiders": info.get("heldPercentInsiders"),
        }
        # Drop Nones
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            return None
        return fields

    data = _safe_call("short_interest", _fetch)
    if isinstance(data, str):
        return data
    lines = [f"  {k}: {v}" for k, v in data.items()]
    return "Holder concentration & short interest:\n" + "\n".join(lines)


def get_chip_context(ticker: str) -> str:
    """Combined chip-data report for ``ticker`` (auto-resolves ETF -> underlying).

    Returns a single formatted string suitable for direct LLM consumption.
    For leveraged ETFs where yfinance returns no fundamentals, this function
    transparently fetches the underlying's chip data and prepends a note.

    Combines:
    - yfinance institutional_holders (top 10, ~45-day delay from 13F)
    - SEC EDGAR real-time Form 4 (replaces delayed yfinance insider)
    - yfinance.info short interest fields
    """
    from .edgar import get_recent_form4  # local import to avoid circular

    underlying, info = _resolve_underlying(ticker)
    if underlying != ticker:
        header = (
            f"NOTE: {ticker} is a leveraged ETF. Resolved underlying: {underlying}. "
            f"All chip data below is for {underlying}, which is what drives {ticker}.\n\n"
        )
    else:
        header = ""

    sections = [
        get_institutional_holders(underlying),
        get_recent_form4(underlying, days=90, limit=15),  # REAL-TIME EDGAR Form 4
        get_short_interest(underlying),
    ]
    body = "\n\n".join(s for s in sections if s)
    return header + body
