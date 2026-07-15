"""EIA (US Energy Information Administration) integration.

Free, requires API key (register at https://www.eia.gov/opendata/register.php).
Falls back gracefully to a no-op message when key is missing.

Use case: energy prices are an indirect but real input to semiconductor
economics (TSMC fabs, MU fabs, data centers all consume massive power).
This module gives the LLM a single, formatted read on:
- Crude oil (WTI, Brent) — macro inflation signal
- Natural gas — power-cost signal for industrial users
- Electricity retail prices — direct fab-cost proxy
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_V2_URL = "https://api.eia.gov/v2/"


def _get_api_key() -> str | None:
    return os.environ.get("EIA_API_KEY") or os.environ.get("EIA_TOKEN")


# Series IDs (v2 API)
SERIES = {
    "wti_crude_oil": "PET.RWTC.W",          # Cushing WTI spot, $/bbl, daily
    "brent_crude_oil": "PET.RBRTE.W",       # Brent spot, $/bbl, daily
    "henry_hub_gas": "NG.RNGWHHD.W",        # Henry Hub natural gas, $/MMBtu, daily
    "us_electricity_residential": "ELEC.PRICE.RES.US.A",  # cents/kWh, annual
    "us_electricity_industrial": "ELEC.PRICE.IND.US.A",   # cents/kWh, annual
}


def _fetch_series(series_id: str, length: int = 30, api_key: str = "") -> list[dict[str, Any]]:
    """Fetch recent observations for a v2 series."""
    url = f"{API_V2_URL}seriesid/{series_id}"
    params = {
        "api_key": api_key,
        "frequency": "daily" if series_id in ("PET.RWTC.W", "PET.RBRTE.W", "NG.RNGWHHD.W") else "annual",
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": length,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("response", {}).get("data", [])
    return rows


def _format_series(name: str, unit: str, rows: list[dict[str, Any]]) -> str:
    """Format series rows for LLM consumption."""
    if not rows:
        return f"  {name}: no data"
    latest = rows[0]
    latest_val = latest.get("value", "?")
    latest_period = latest.get("period", "?")
    try:
        latest_val_str = f"{float(latest_val):,.2f} {unit}"
    except (TypeError, ValueError):
        latest_val_str = f"{latest_val} {unit}"
    line = f"  {name}: {latest_val_str} (period {latest_period})"

    if len(rows) >= 2:
        try:
            prev_val = float(rows[1].get("value", 0))
            curr_val = float(latest_val)
            if prev_val != 0:
                pct = (curr_val - prev_val) / prev_val * 100
                line += f"   (1-period change: {pct:+.2f}%)"
        except (TypeError, ValueError):
            pass
    return line


def get_energy_context() -> str:
    """Return a formatted snapshot of energy prices relevant to semis economics.

    Includes WTI/Brent crude, Henry Hub natural gas, and US retail/industrial
    electricity prices. All on the same scale (latest value + 1-period change).

    Free, requires EIA_API_KEY in environment. Returns a graceful "missing key"
    message when no key is set.
    """
    api_key = _get_api_key()
    if not api_key:
        return (
            "eia: EIA_API_KEY not set. Register free at "
            "https://www.eia.gov/opendata/register.php and add to ~/.zshrc."
        )

    lines = ["EIA Energy Snapshot (semiconductor cost inputs):"]
    targets = [
        ("WTI Crude Oil ($/bbl)", SERIES["wti_crude_oil"], "USD/bbl"),
        ("Brent Crude Oil ($/bbl)", SERIES["brent_crude_oil"], "USD/bbl"),
        ("Henry Hub Natural Gas ($/MMBtu)", SERIES["henry_hub_gas"], "USD/MMBtu"),
        ("US Avg Residential Electricity (¢/kWh)", SERIES["us_electricity_residential"], "¢/kWh"),
        ("US Avg Industrial Electricity (¢/kWh)", SERIES["us_electricity_industrial"], "¢/kWh"),
    ]
    for name, sid, unit in targets:
        try:
            rows = _fetch_series(sid, length=5, api_key=api_key)
            lines.append(_format_series(name, unit, rows))
        except Exception as exc:
            lines.append(f"  {name}: fetch failed ({type(exc).__name__}: {exc})")
    return "\n".join(lines)
