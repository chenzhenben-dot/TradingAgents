# tradingagents_custom — Custom extensions for TradingAgents v0.3.1

Personal fork of [tauricresearch/tradingagents](https://github.com/tauricresearch/tradingagents)
at v0.3.1 (commit 01477f9). Adds portfolio-aware analysis, chip data, and
extra free data sources on top of the upstream framework.

## What's in here

| Module | What it does |
|---|---|
| `graph.py` | `CustomTradingAgentsGraph` — drop-in subclass with custom tool injection, auto-save, leverage/portfolio context |
| `chip_data.py` | Combined chip / institutional / short-interest report for any ticker (resolves leveraged ETFs to underlying) |
| `edgar.py` | Real-time SEC Form 4 + recent filings + XBRL company facts (free, no key) |
| `leverage_detector.py` | Detects 2X/3X/inverse ETFs and emits a warning the LLM can read |
| `portfolio_context.py` | Reads `~/.tradingagents/portfolio.json` and injects user's positions + rules into the prompt |
| `yfinance_extras.py` | Earnings calendar, analyst ratings, dividends/splits via yfinance |
| `news_api.py` | NewsAPI.org news (free tier, 100 req/day, optional key) |
| `sec_frames.py` | SEC XBRL Frames API for cross-company peer comparison (no key) |
| `eia.py` | EIA energy context (oil/gas/power) for semiconductor fab cost inputs (optional key) |

## Public surface

```python
from tradingagents_custom import (
    # Main graph class
    CustomTradingAgentsGraph,
    apply_patches,
    # Chip / holder data
    get_chip_context, get_institutional_holders, get_insider_transactions, get_short_interest,
    # EDGAR
    get_recent_filings, get_recent_form4, get_company_facts,
    # Leverage detection
    detect_leveraged_etf, leverage_warning_text,
    # Portfolio context
    load_portfolio, build_portfolio_context, build_leverage_context,
    # Yfinance extras
    get_earnings_calendar, get_analyst_ratings, get_dividends_splits,
    # New free sources
    get_news_sentiment, get_peer_comparison, get_energy_context,
)
```

## Quick start

```python
import copy
from tradingagents_custom import CustomTradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = CustomTradingAgentsGraph(debug=False, config=copy.deepcopy(DEFAULT_CONFIG))
_, signal = ta.propagate("AAPL", "2024-05-10")
print(signal)
# After propagate, the report tree auto-saves to:
#   ~/.tradingagents/logs/reports/AAPL_<timestamp>/complete_report.md
```

## Portfolio format

Edit `~/.tradingagents/portfolio.json`:

```json
{
  "MRVL": {
    "qty": 14,
    "avg_cost": 274.29,
    "current_price": 239.04,
    "rules": {
      "stop": 204.00,
      "trim_zones": [233.00, 237.00],
      "add_zones": [200.00, 210.00]
    },
    "notes": "Marvell. Trim 2-3 shares on bounce."
  }
}
```

## Optional API keys

Set in `~/.zshrc`:

```bash
export NEWS_API_KEY="..."  # https://newsapi.org (100 req/day free)
export EIA_API_KEY="..."   # https://www.eia.gov/opendata/register.php (free)
```

Missing keys → modules gracefully degrade to "register at ..." messages.

## Auto-save behavior

Every `propagate()` call auto-saves the upstream-default report tree
(`5_section complete_report.md` + 12 .md files per analyst) to
`~/.tradingagents/logs/reports/{ticker}_{timestamp}/`. Set
`ta._last_report_path` after each run to find the latest.

## Syncing with upstream

```bash
# One-time setup (already done in this repo):
# git remote add upstream https://github.com/tauricresearch/tradingagents.git
# git remote add fork    https://github.com/chenzhenben-dot/TradingAgents.git

# To pull upstream's latest:
git fetch upstream
git checkout v0.3.2  # or whatever upstream's new tag is
git checkout -b custom/v0.3.2-with-extensions
# tradingagents_custom/ is untouched, no merge needed
```

## File counts

- 10 modules, ~1,500 lines of Python
- 0 modifications to upstream code
- Drop-in subclass design — `CustomTradingAgentsGraph(TradingAgentsGraph)`
- `apply_patches()` available for monkey-patching the upstream class
