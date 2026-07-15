"""Free yfinance extras — earnings calendar, analyst ratings, dividends/splits.

These are already accessible via yfinance but the upstream framework doesn't
expose them as tools. Pulls them out into a single module so the framework
can use them via ToolNode.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_call(label: str, fn):
    try:
        result = fn()
        if result is None:
            return f"{label}: no data"
        return result
    except Exception as exc:
        return f"{label}: unavailable ({type(exc).__name__}: {exc})"


def get_earnings_calendar(ticker: str) -> str:
    """Upcoming earnings date + consensus EPS estimate.

    Free via yfinance. Critical for traders — earnings dates drive IV and
    the framework currently doesn't surface them.
    """
    def _fetch():
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None or (isinstance(cal, pd.DataFrame) and cal.empty):
            # yfinance changed to returning a dict in some versions
            if isinstance(cal, dict):
                cal_dict = cal
            else:
                return None
        else:
            cal_dict = cal.to_dict() if isinstance(cal, pd.DataFrame) else cal
        return cal_dict

    data = _safe_call("earnings_calendar", _fetch)
    if isinstance(data, str):
        return data
    if not data:
        return f"earnings_calendar: no upcoming earnings for {ticker}"
    lines = [f"Upcoming earnings for {ticker.upper()}:"]
    for k, v in data.items():
        try:
            v_str = v.iloc[0] if hasattr(v, "iloc") else v
        except Exception:
            v_str = v
        lines.append(f"  {k}: {v_str}")
    return "\n".join(lines)


def get_analyst_ratings(ticker: str, days: int = 90) -> str:
    """Recent analyst upgrades/downgrades.

    Free via yfinance `.upgrades_downgrades`. Shows whether the Street
    is becoming more bullish/bearish.
    """
    def _fetch():
        t = yf.Ticker(ticker)
        df = t.upgrades_downgrades
        if df is None or df.empty:
            return None
        df = df.sort_index(ascending=False).head(20)
        return df

    data = _safe_call("analyst_ratings", _fetch)
    if isinstance(data, str):
        return data
    lines = [f"Recent analyst ratings changes for {ticker.upper()} (last 20):"]
    try:
        for idx, row in data.iterrows():
            if hasattr(idx, "strftime"):
                date = idx.strftime("%Y-%m-%d")
            else:
                date = str(idx)
            firm = row.get("Firm", "?")
            action = row.get("Action", "?")
            to_grade = row.get("ToGrade", "?")
            from_grade = row.get("FromGrade", "?")
            lines.append(f"  {date} | {firm:30} | {action:12} | {from_grade} -> {to_grade}")
    except Exception as exc:
        return f"analyst_ratings: parse failed ({exc})"
    return "\n".join(lines)


def get_dividends_splits(ticker: str) -> str:
    """Recent dividend payments and stock splits.

    Free via yfinance. Surfaces yield-relevant info that fundamentals
    analyst should know.
    """
    def _fetch():
        t = yf.Ticker(ticker)
        divs = t.dividends
        splits = t.splits
        return divs, splits

    try:
        divs, splits = _fetch()
    except Exception as exc:
        return f"dividends_splits: unavailable ({type(exc).__name__}: {exc})"

    lines = [f"Dividends and splits for {ticker.upper()}:"]
    if divs is not None and not divs.empty:
        recent_divs = divs.sort_index(ascending=False).head(5)
        lines.append("  Recent dividends:")
        for idx, val in recent_divs.items():
            date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            lines.append(f"    {date} | ${val:.4f}/share")
    else:
        lines.append("  No dividend history (or no recent dividends).")

    if splits is not None and not splits.empty:
        recent_splits = splits.sort_index(ascending=False).head(5)
        lines.append("  Recent splits:")
        for idx, val in recent_splits.items():
            date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            lines.append(f"    {date} | {val:.4f}:1 ratio")
    else:
        lines.append("  No split history.")

    return "\n".join(lines)
