"""SEC EDGAR data: real-time Form 4 insider transactions + recent filings.

Free, no API key. SEC requires a User-Agent header; we set one in the
session to identify ourselves. Rate limit is 10 requests/second.

Two public entry points:
- get_recent_form4(ticker, days=90): real-time insider transactions
  (replaces the delayed yfinance version)
- get_recent_filings(ticker, days=30, form_types=None): general SEC
  filings for the issuer — useful for news analyst to find 8-K material
  events the headline-news pipeline missed.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# SEC requires a User-Agent identifying the requester
USER_AGENT = "TradingAgentsCustom/0.1 chenzhen-trading@example.com"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

# Local cache directory for CIK mapping (saves HTTP roundtrip on repeat calls)
_CACHE_DIR = Path.home() / ".tradingagents" / "cache" / "edgar"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CIK_CACHE_PATH = _CACHE_DIR / "company_tickers.json"
_CIK_CACHE_MAX_AGE = timedelta(days=7)


def _http_get(url: str, timeout: float = 15.0) -> dict | list | str:
    """GET ``url`` with SEC headers. Returns parsed JSON or text."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    ct = resp.headers.get("Content-Type", "")
    if "json" in ct:
        return resp.json()
    return resp.text


def _load_cik_map() -> dict[str, dict[str, Any]]:
    """Load SEC's full ticker -> CIK mapping.

    Cached locally for 7 days. ~3 MB, ~10k tickers.
    """
    if _CIK_CACHE_PATH.exists():
        age = datetime.now() - datetime.fromtimestamp(_CIK_CACHE_PATH.stat().st_mtime)
        if age < _CIK_CACHE_MAX_AGE:
            try:
                with open(_CIK_CACHE_PATH) as f:
                    return json.load(f)
            except Exception:
                pass  # fall through to re-download

    try:
        data = _http_get("https://www.sec.gov/files/company_tickers.json")
        if isinstance(data, dict):
            with open(_CIK_CACHE_PATH, "w") as f:
                json.dump(data, f)
        return data
    except Exception as exc:
        logger.warning("edgar: could not load CIK map: %s", exc)
        return {}


def _ticker_to_cik(ticker: str) -> str | None:
    """Resolve a ticker to its 10-digit zero-padded CIK."""
    cik_map = _load_cik_map()
    if not cik_map:
        return None
    t = ticker.upper().replace("-", ".")
    # company_tickers.json: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    for entry in cik_map.values():
        if entry.get("ticker", "").upper() == t:
            cik = entry.get("cik_str")
            if cik:
                return str(cik).zfill(10)
    return None


def get_recent_filings(
    ticker: str,
    days: int = 30,
    form_types: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Return a formatted string of recent SEC filings for ``ticker``.

    Args:
        ticker: e.g. "AAPL", "AAOI"
        days: look-back window in days
        form_types: filter to these form types (e.g. ["8-K", "4"]). None = all
        limit: max rows to return

    Default form types if None: ["8-K", "10-K", "10-Q", "4"] (the materially
    relevant ones for trading).
    """
    if form_types is None:
        form_types = ["8-K", "10-K", "10-Q", "4"]

    try:
        cik = _ticker_to_cik(ticker)
        if not cik:
            return f"edgar: could not resolve CIK for {ticker}"

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = _http_get(url)
        if not isinstance(data, dict):
            return f"edgar: unexpected response for {ticker}"

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return f"edgar: no recent filings for {ticker}"

        accession = recent.get("accessionNumber", [])
        form = recent.get("form", [])
        filing_date = recent.get("filingDate", [])
        primary_doc = recent.get("primaryDocument", [])
        items = recent.get("items", [])

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = []
        for i in range(len(accession)):
            if form[i] not in form_types:
                continue
            if filing_date[i] < cutoff:
                continue
            acc_no_dashes = accession[i].replace("-", "")
            primary_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{acc_no_dashes}/{primary_doc[i]}"
            )
            row = f"- {filing_date[i]} | {form[i]:6} | {accession[i]} | {primary_url}"
            if items[i]:
                row += f" | items: {items[i]}"
            rows.append(row)
            if len(rows) >= limit:
                break

        if not rows:
            return f"edgar: no {form_types} filings for {ticker} in last {days} days"

        header = (
            f"Recent SEC filings for {ticker.upper()} (CIK {cik}) "
            f"in last {days} days, types={form_types}:\n"
        )
        return header + "\n".join(rows)
    except Exception as exc:
        return f"edgar.get_recent_filings({ticker}) failed: {type(exc).__name__}: {exc}"


def get_recent_form4(ticker: str, days: int = 90, limit: int = 20) -> str:
    """Return a formatted string of recent insider (Form 4) transactions.

    This is the FREE real-time replacement for yfinance's delayed insider
    data. Each Form 4 is filed within 2 business days of the trade.
    """
    return get_recent_filings(ticker, days=days, form_types=["4"], limit=limit)


def get_company_facts(ticker: str) -> str:
    """Return key XBRL company facts (latest revenue, net income, shares).

    Complements yfinance fundamentals with officially-reported numbers
    straight from SEC filings. Use this when yfinance is stale or wrong.
    """
    try:
        cik = _ticker_to_cik(ticker)
        if not cik:
            return f"edgar: could not resolve CIK for {ticker}"

        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = _http_get(url)
        if not isinstance(data, dict):
            return f"edgar: no XBRL facts for {ticker}"

        # Pull a few commonly-used US-GAAP facts
        facts = data.get("facts", {}).get("us-gaap", {})
        out_lines = [f"SEC XBRL company facts for {ticker.upper()} (CIK {cik}):"]

        for concept in ("Revenues", "NetIncomeLoss", "Assets", "Liabilities",
                        "StockholdersEquity", "CommonStockSharesOutstanding"):
            units = facts.get(concept, {}).get("units", {})
            # Try USD first, then shares
            for unit_name in ("USD", "shares", "USD/shares"):
                if unit_name not in units:
                    continue
                entries = units[unit_name]
                # Filter to 10-K/10-Q annual or quarterly filings
                filed = [e for e in entries if e.get("form") in ("10-K", "10-Q")]
                if not filed:
                    continue
                filed.sort(key=lambda e: e.get("end", ""), reverse=True)
                latest = filed[0]
                val = latest.get("val")
                end = latest.get("end")
                form = latest.get("form")
                fp = latest.get("fp", "")
                out_lines.append(
                    f"  {concept:32} | {val:>20,.0f} {unit_name:8} | end={end} | {form} {fp}"
                )
                break

        if len(out_lines) == 1:
            return f"edgar: no useful XBRL facts for {ticker}"

        return "\n".join(out_lines)
    except Exception as exc:
        return f"edgar.get_company_facts({ticker}) failed: {type(exc).__name__}: {exc}"
