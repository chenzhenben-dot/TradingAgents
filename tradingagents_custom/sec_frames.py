"""SEC EDGAR cross-company comparison via Company Concept API.

Free, no auth. Uses the working `/api/xbrl/companyconcept/` endpoint
(the `/api/xbrl/frames/` bulk cross-company endpoint is deprecated).

The framework provides a "peer list" so the LLM can ask for a concept
like Revenues and get the same value for the user's ticker + N peer
companies side-by-side. Peer list is the intersection of (sector-relevant
defaults) and (tickers the LLM knows about).

Use case: when the framework says "AAOI forward PE 23.98 looks low",
this tool pulls Revenues / NetIncome for the semiconductor peer set
(MU, SNDK, NVDA, AMD, TSM, etc.) so the LLM has actual context.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "TradingAgentsCustom/0.1 chenzhen-trading@example.com"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}

# Default semiconductor / AI / tech peer set used when no specific peer
# list is requested. CIKs are looked up from the company_tickers map.
DEFAULT_PEERS = [
    "NVDA", "AMD", "INTC", "TSM", "MU", "SNDK", "MRVL", "AVGO", "TXN", "QCOM",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",  # hyperscaler customers
]

# Concept name aliases — EDGAR uses full us-gaap tag names, not short
# GAAP terms. Map the common short forms the LLM will use.
CONCEPT_ALIASES = {
    "Revenues": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "NetIncomeLoss": ["NetIncomeLoss", "ProfitLoss"],
    "Assets": ["Assets"],
    "Liabilities": ["Liabilities"],
    "StockholdersEquity": ["StockholdersEquity"],
    "CommonStockSharesOutstanding": ["CommonStockSharesOutstanding"],
}


def _get_company_ticker_map() -> dict[str, dict[str, Any]]:
    """Load SEC's full ticker -> CIK mapping (cached locally for 7 days)."""
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


def _ticker_to_cik(ticker: str, ticker_map: dict[str, dict]) -> str | None:
    """Resolve a ticker to its 10-digit zero-padded CIK."""
    t = ticker.upper().replace("-", ".")
    for entry in ticker_map.values():
        if entry.get("ticker", "").upper() == t:
            cik = entry.get("cik_str")
            if cik:
                return str(cik).zfill(10)
    return None


def _fetch_concept(cik: str, concept_candidates: list[str]) -> tuple[dict, str] | tuple[None, None]:
    """Fetch the most recent FY value for a concept for one company.

    Tries each concept name in order (since EDGAR uses verbose us-gaap tags).
    Returns (entry, concept_used) or (None, None) if all fail.
    """
    for concept in concept_candidates:
        url = (
            f"https://data.sec.gov/api/xbrl/companyconcept/"
            f"CIK{cik}/us-gaap/{concept}.json"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            units = data.get("units", {}).get("USD", [])
            # Filter to 10-K (full year) filings
            fy_entries = [e for e in units if e.get("form") == "10-K" and e.get("fp") == "FY"]
            if not fy_entries:
                continue
            fy_entries.sort(key=lambda e: e.get("end", ""), reverse=True)
            return fy_entries[0], concept
        except Exception:
            continue
    return None, None


def get_peer_comparison(
    ticker: str,
    concept: str = "Revenues",
    peers: list[str] | None = None,
    top_n: int = 8,
) -> str:
    """Cross-company comparison for a given XBRL concept.

    Args:
        ticker: the user's ticker (used to locate the user's company)
        concept: GAAP concept — accepts short names ("Revenues", "NetIncomeLoss",
            "Assets", "Liabilities", "StockholdersEquity")
        peers: list of peer tickers. None = use DEFAULT_PEERS
        top_n: max number of peers to show

    Returns:
        Formatted string with the user's company + peers side-by-side, sorted
        descending, ready for LLM context.
    """
    candidates = CONCEPT_ALIASES.get(concept, [concept])
    peer_list = peers or DEFAULT_PEERS
    target_peers = [p for p in peer_list if p.upper() != ticker.upper()][:top_n]

    ticker_map = _get_company_ticker_map()
    user_cik = _ticker_to_cik(ticker, ticker_map)
    user_entry = next(
        (e for e in ticker_map.values() if str(e.get("cik_str", "")).zfill(10) == user_cik),
        None,
    ) if user_cik else None

    def _fetch_for(t: str) -> dict:
        cik = _ticker_to_cik(t, ticker_map)
        if not cik:
            return {"ticker": t, "value": None, "name": t, "error": "CIK not found"}
        entry, used_concept = _fetch_concept(cik, candidates)
        if not entry:
            return {
                "ticker": t, "value": None, "name": t,
                "error": f"no data for concepts {candidates}",
            }
        name = next(
            (e.get("title", t) for e in ticker_map.values()
             if str(e.get("cik_str", "")).zfill(10) == cik),
            t,
        )
        return {
            "ticker": t,
            "name": name,
            "value": entry.get("val"),
            "end": entry.get("end"),
            "concept_used": used_concept,
        }

    user_data = _fetch_for(ticker) if user_cik else {"ticker": ticker, "error": "CIK not found"}
    peer_data = [_fetch_for(p) for p in target_peers]

    # Sort peers by value (descending); None at the end
    def _to_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("-inf")

    peer_data.sort(key=lambda r: _to_float(r.get("value")), reverse=True)

    lines = [
        f"SEC EDGAR peer comparison: {concept} (USD, latest FY)",
        f"Concept variants tried: {candidates}",
        f"Total peers requested: {len(peer_list)} | shown: {len(peer_data)}",
        "",
    ]

    if user_data.get("value") is not None:
        lines.append(f"USER: {ticker} ({user_entry.get('title', ticker) if user_entry else ticker})")
        lines.append(f"  Value: {float(user_data['value']):,.0f} USD (FY end: {user_data.get('end', '?')})")
        lines.append(f"  Concept: {user_data.get('concept_used', concept)}")
        lines.append("")
    else:
        lines.append(f"USER: {ticker} — {user_data.get('error', 'no data')}")
        lines.append("")

    lines.append(f"Peer comparison (top {len(peer_data)}):")
    for i, row in enumerate(peer_data, 1):
        if row.get("value") is None:
            lines.append(f"  {i:>2}. {row['ticker']:6} — {row.get('error', 'no data')}")
        else:
            try:
                val_str = f"{float(row['value']):>20,.0f}"
            except (TypeError, ValueError):
                val_str = str(row["value"])
            lines.append(
                f"  {i:>2}. {row['ticker']:6} {row['name'][:30]:30} {val_str:>22} USD  "
                f"(end: {row.get('end', '?')})"
            )

    return "\n".join(lines)
