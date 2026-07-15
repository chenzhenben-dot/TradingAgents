"""Custom extensions for TradingAgents.

Adds on top of upstream:
1. Chip / holder data (institutional, insider via EDGAR, short interest)
2. Leveraged-ETF detection with explicit warnings
3. Portfolio context injection (so the framework knows your positions)
4. SEC EDGAR real-time filings + Form 4 insider transactions
5. Earnings calendar + analyst ratings + dividends/splits (via yfinance)
6. NewsAPI.org (replaces broken StockTwits/Reddit for sentiment)
7. SEC XBRL Frames (cross-company peer comparison)
8. EIA energy context (semiconductor fab cost inputs)

Public surface:
- CustomTradingAgentsGraph: drop-in subclass of TradingAgentsGraph
- apply_patches(): monkey-patch the upstream class in place
- All utility functions
"""
from .chip_data import get_chip_context, get_institutional_holders, get_insider_transactions, get_short_interest
from .edgar import get_recent_filings, get_recent_form4, get_company_facts
from .eia import get_energy_context
from .leverage_detector import detect_leveraged_etf, leverage_warning_text
from .news_api import get_news_sentiment
from .portfolio_context import load_portfolio, build_portfolio_context, build_leverage_context
from .sec_frames import get_peer_comparison
from .yfinance_extras import get_earnings_calendar, get_analyst_ratings, get_dividends_splits
from .graph import CustomTradingAgentsGraph, apply_patches

__all__ = [
    "CustomTradingAgentsGraph",
    "apply_patches",
    "get_chip_context",
    "get_institutional_holders",
    "get_insider_transactions",
    "get_short_interest",
    "get_recent_filings",
    "get_recent_form4",
    "get_company_facts",
    "detect_leveraged_etf",
    "leverage_warning_text",
    "load_portfolio",
    "build_portfolio_context",
    "build_leverage_context",
    "get_earnings_calendar",
    "get_analyst_ratings",
    "get_dividends_splits",
    "get_news_sentiment",
    "get_peer_comparison",
    "get_energy_context",
]
