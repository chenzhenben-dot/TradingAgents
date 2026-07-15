"""SEC XBRL Frames API — cross-company comparison for a given concept.

Free, no auth. Goes beyond single-company EDGAR facts by letting the LLM
ask "show me Revenues for ALL filers in Q1 2026" — useful for peer
benchmarking during valuation analysis.

Use case: when the framework says "AAOI forward PE 23.98 looks low",
this tool pulls the same PE concept for the semiconductor peer set
(MU, SNDK, NVDA, AMD, TSM, etc.) so the LLM has actual context.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "TradingAgentsCustom/0.1 chenzhen-trading@example.com"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}


def _fetch_frame(concept: str, period_fiscal_year: int, period_fiscal_period: str) -> list[dict[str, Any]]:
    """Pull the XBRL frame for a concept and a given fiscal period.

    Args:
        concept: e.g. "Revenues", "NetIncomeLoss", "Assets"
        period_fiscal_year: e.g. 2026
        period_fiscal_period: e.g. "FY" or "Q1"

    Returns:
        list of company facts for that concept/period
    """
    url = (
        f"https://data.sec.gov/api/xbrl/frames/"
        f"{concept}/USD/{period_fiscal_year}-{period_fiscal_period}.json"
    )
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json().get("data", [])


def _get_company_ticker_map() -> dict[str, str]:
    """Load SEC's ticker -> CIK map (cached locally for 7 days)."""
    import json
    from pathlib import Path
    from datetime import datetime, timedelta

    cache_path = Path.home() / ".tradingagents" / "cache" / "edgar" / "company_tickers.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age < timedelta(days=7):
            try:
                with open(cache_path) as f:
                    return json.load(f)
            except Exception:
                pass

    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=HEADERS, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache_path, "w") as f:
            json.dump(data, f)
        return data
    except Exception as exc:
        logger.warning("sec_frames: could not load ticker map: %s", exc)
        return {}


def _cik_to_name(cik: str, ticker_map: dict[str, dict]) -> str:
    """Look up company name by CIK from the SEC ticker map."""
    for entry in ticker_map.values():
        if str(entry.get("cik_str", "")).zfill(10) == cik:
            return entry.get("title", "Unknown")
    return f"CIK {cik}"


def get_peer_comparison(
    ticker: str,
    concept: str = "Revenues",
    period_fiscal_year: int = 2026,
    period_fiscal_period: str = "FY",
    top_n: int = 10,
) -> str:
    """Cross-company comparison for a given XBRL concept.

    Args:
        ticker: the user's ticker (used only to locate the user's company
            in the comparison; peers are determined by the universe of filers
            reporting this concept for the given period)
        concept: GAAP concept to compare (e.g. "Revenues", "NetIncomeLoss",
            "Assets", "StockholdersEquity", "Liabilities")
        period_fiscal_year: e.g. 2026
        period_fiscal_period: "FY" or "Q1".."Q4"
        top_n: number of top companies by value to show

    Returns:
        Formatted string with the user's company value + top peers,
        sorted descending, ready for LLM context.
    """
    try:
        all_data = _fetch_frame(concept, period_fiscal_year, period_fiscal_period)
    except Exception as exc:
        return f"sec_frames: fetch failed ({type(exc).__name__}: {exc})"

    if not all_data:
        return (
            f"sec_frames: no data for {concept} "
            f"{period_fiscal_year}-{period_fiscal_period}"
        )

    # Sort by val (descending) — values are strings, need to handle
    def _to_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("-inf")

    sorted_data = sorted(all_data, key=lambda r: _to_float(r.get("val")), reverse=True)
    ticker_map = _get_company_ticker_map()

    # Find user's company by ticker
    user_cik = None
    user_entry = None
    for entry in ticker_map.values():
        if entry.get("ticker", "").upper() == ticker.upper().replace(".", "-"):
            user_cik = str(entry.get("cik_str", "")).zfill(10)
            user_entry = entry
            break

    user_rank = None
    user_val = None
    for i, row in enumerate(sorted_data):
        if str(row.get("cik", "")).zfill(10) == user_cik:
            user_rank = i + 1
            user_val = row.get("val")
            break

    lines = [
        f"SEC XBRL Frame: {concept} (USD, {period_fiscal_year}-{period_fiscal_period})",
        f"Total filers in frame: {len(sorted_data)}",
        "",
    ]

    if user_val is not None:
        company_name = user_entry.get("title", ticker) if user_entry else ticker
        lines.append(f"USER COMPANY: {ticker} ({company_name})")
        lines.append(f"  Value: {user_val:,.0f} USD")
        lines.append(f"  Rank: #{user_rank} out of {len(sorted_data)}")
        lines.append("")
    else:
        lines.append(f"USER COMPANY: {ticker} — not found in this frame")
        lines.append("")

    lines.append(f"Top {top_n} filers by {concept}:")
    for i, row in enumerate(sorted_data[:top_n], 1):
        cik = str(row.get("cik", "")).zfill(10)
        entity = row.get("entityName") or _cik_to_name(cik, ticker_map)
        val = row.get("val", "?")
        try:
            val_str = f"{float(val):>20,.0f}"
        except (TypeError, ValueError):
            val_str = str(val)
        lines.append(f"  {i:>2}. {entity[:40]:40} {val_str:>22} USD")

    if user_rank is not None and user_rank > top_n:
        lines.append("")
        lines.append(f"  ... ({ticker} is ranked #{user_rank}, beyond top {top_n})")

    return "\n".join(lines)
