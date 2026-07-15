"""Custom TradingAgentsGraph subclass — drop-in replacement with several upgrades.

1. ``get_chip_context`` tool added to fundamentals + news (institutional, EDGAR Form 4, short)
2. ``get_recent_filings`` tool added to news (8-K, 10-K, 10-Q, 4)
3. ``get_company_facts``, ``get_earnings_calendar``, ``get_analyst_ratings``,
   ``get_dividends_splits`` tools added to fundamentals
4. ``get_news_sentiment`` tool added to news (NewsAPI.org, replaces broken StockTwits)
5. ``get_peer_comparison`` tool added to fundamentals (SEC XBRL Frames, peer benchmarking)
6. ``get_energy_context`` tool added to news (EIA, semiconductor fab cost inputs)
7. ``detect_leveraged_etf`` runs before propagate; warning text is injected
   into the analyst state
8. ``load_portfolio`` runs before propagate; user's position in the ticker
   is injected into the analyst state

Usage:
    from tradingagents_custom import CustomTradingAgentsGraph
    ta = CustomTradingAgentsGraph(debug=True)
    _, signal = ta.propagate("AAOX", "2026-07-08")

The original ``TradingAgentsGraph`` is never modified, so upstream updates
land cleanly — only this file and the ``tradingagents_custom/`` package are
custom code.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.prebuilt import ToolNode

from tradingagents.graph.trading_graph import TradingAgentsGraph

from .chip_data import get_chip_context
from .edgar import get_company_facts, get_recent_filings
from .eia import get_energy_context
from .leverage_detector import detect_leveraged_etf, leverage_warning_text
from .news_api import get_news_sentiment
from .portfolio_context import (
    build_leverage_context,
    build_portfolio_context,
    load_portfolio,
)
from .sec_frames import get_peer_comparison
from .yfinance_extras import (
    get_analyst_ratings,
    get_dividends_splits,
    get_earnings_calendar,
)

logger = logging.getLogger(__name__)


# Tools added per analyst. Centralized so both the class and the
# standalone patch function stay in sync.
EXTRA_TOOLS = {
    "fundamentals": [
        get_chip_context,
        get_company_facts,
        get_earnings_calendar,
        get_analyst_ratings,
        get_dividends_splits,
        get_peer_comparison,
    ],
    "news": [
        get_chip_context,
        get_recent_filings,
        get_news_sentiment,
        get_energy_context,
    ],
}


class CustomTradingAgentsGraph(TradingAgentsGraph):
    """TradingAgentsGraph with chip data, leverage warnings, and portfolio context.

    Overrides the bare minimum to keep upstream churn low:
    - ``_create_tool_nodes`` adds the EXTRA_TOOLS to relevant analysts
    - ``_run_graph`` injects leverage warnings + portfolio context into state
    - ``_run_graph`` auto-saves the upstream-default report tree to
      ``~/.tradingagents/logs/reports/{ticker}_{timestamp}/`` and stores the
      path on ``self._last_report_path``
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set in _run_graph after propagate; lets callers find the latest report
        self._last_report_path: Path | None = None

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Add custom tools to the analysts where they matter.

        ToolNode doesn't expose a public ``.tools`` list, so we reconstruct
        each patched node by extracting the underlying callables from
        ``tools_by_name`` (which maps tool name -> StructuredTool, and
        ``StructuredTool.func`` is the original Python function).
        """
        nodes = super()._create_tool_nodes()
        for analyst_name, extras in EXTRA_TOOLS.items():
            if analyst_name not in nodes:
                continue
            existing = nodes[analyst_name]
            original_funcs = [t.func for t in existing.tools_by_name.values()]
            nodes[analyst_name] = ToolNode([*extras, *original_funcs])
        return nodes

    def _run_graph(self, company_name: str, trade_date: str, asset_type: str = "stock"):
        """Inject portfolio + leverage context into initial state.

        We piggyback on ``instrument_context`` (which upstream already supports)
        so no upstream state schema needs to change. Concatenation preserves the
        upstream content while adding our layer.
        """
        # Pre-compute context once; reuse if propagate() is called multiple times.
        self._custom_context_cache = self._build_custom_context(company_name, asset_type)

        # Run the upstream pipeline (which builds init_agent_state with
        # instrument_context already populated). We then splice in our context.
        result = super()._run_graph(company_name, trade_date, asset_type=asset_type)

        # Auto-save the upstream-default report tree so every run lands in
        # ~/.tradingagents/logs/reports/{ticker}_{timestamp}/. Set
        # self._last_report_path so callers can find the latest run.
        try:
            self._last_report_path = self.save_reports(result[0], company_name)
            logger.info("custom: report tree saved to %s", self._last_report_path)
        except Exception as exc:
            logger.warning("custom: save_reports failed: %s", exc)
            self._last_report_path = None

        return result

    def _build_custom_context(self, ticker: str, asset_type: str) -> str:
        """Build the additional context string to inject.

        Cached on the instance so it's only computed once per run, and the
        cache is cleared by ``propagate()`` (which is the only entry point).
        """
        # Leverage detection (works for ETFs and underlying single stocks)
        try:
            leverage_info = detect_leveraged_etf(ticker)
        except Exception as exc:
            logger.warning("custom: leverage detection failed for %s: %s", ticker, exc)
            leverage_info = {"is_leveraged": False}

        leverage_warning = leverage_warning_text(leverage_info)
        portfolio_ctx = build_portfolio_context(ticker)
        leverage_ctx = build_leverage_context(leverage_info)

        sections = [s for s in (leverage_warning, portfolio_ctx, leverage_ctx) if s]
        if not sections:
            return ""
        header = "=== CUSTOM CONTEXT (auto-generated, do not invent around it) ==="
        return header + "\n\n" + "\n\n".join(sections)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        """Wrap upstream to also include our custom context."""
        upstream = super().resolve_instrument_context(ticker, asset_type)
        custom = self._build_custom_context(ticker, asset_type)
        if custom:
            return upstream + "\n\n" + custom
        return upstream


def apply_patches() -> None:
    """Monkey-patch the upstream ``TradingAgentsGraph`` with the custom behaviour.

    After calling this, ``from tradingagents.graph.trading_graph import
    TradingAgentsGraph`` will already behave like ``CustomTradingAgentsGraph``.
    Use this if you don't want to change imports in your scripts.
    """
    from tradingagents.graph import trading_graph

    trading_graph.TradingAgentsGraph._create_tool_nodes = _patched_create_tool_nodes
    trading_graph.TradingAgentsGraph.resolve_instrument_context = _patched_resolve_instrument_context
    logger.info("tradingagents_custom: patches applied to TradingAgentsGraph")


def _patched_create_tool_nodes(self):
    """Standalone (unbound) version of CustomTradingAgentsGraph._create_tool_nodes."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    # Re-bind to the upstream class so super() works correctly
    cls = TradingAgentsGraph
    original = cls._create_tool_nodes

    nodes = original(self)
    for analyst_name, extras in EXTRA_TOOLS.items():
        if analyst_name not in nodes:
            continue
        existing = nodes[analyst_name]
        original_funcs = [t.func for t in existing.tools_by_name.values()]
        nodes[analyst_name] = ToolNode([*extras, *original_funcs])
    return nodes


def _patched_resolve_instrument_context(self, ticker: str, asset_type: str = "stock"):
    """Standalone (unbound) version of CustomTradingAgentsGraph.resolve_instrument_context."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    cls = TradingAgentsGraph
    upstream = cls.resolve_instrument_context(self, ticker, asset_type)
    leverage_info = detect_leveraged_etf(ticker)
    leverage_warning = leverage_warning_text(leverage_info)
    portfolio_ctx = build_portfolio_context(ticker)
    leverage_ctx = build_leverage_context(leverage_info)
    custom_sections = [s for s in (leverage_warning, portfolio_ctx, leverage_ctx) if s]
    if not custom_sections:
        return upstream
    header = "=== CUSTOM CONTEXT (auto-generated, do not invent around it) ==="
    return upstream + "\n\n" + header + "\n\n" + "\n\n".join(custom_sections)
