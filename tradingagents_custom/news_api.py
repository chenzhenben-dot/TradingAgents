"""NewsAPI.org integration — global news with sentiment metadata.

Free tier: 100 requests/day, requires API key (register at https://newsapi.org).
Falls back gracefully to a no-op message when key is missing or rate-limited.

Use case: replaces the broken StockTwits/Reddit sentiment pipeline with
real news (80,000+ sources). Headline dates and source names give the LLM
proper time-aware sentiment reads that social posts can't.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_URL = "https://newsapi.org/v2/everything"
CACHE_DIR = None  # set in __init__ if you want local cache
_DAILY_LIMIT_WARNED = False


def _get_api_key() -> str | None:
    """Read NEWS_API_KEY from environment. Returns None if not set."""
    return os.environ.get("NEWS_API_KEY") or os.environ.get("NEWSAPI_KEY")


def _format_articles(articles: list[dict[str, Any]], ticker: str) -> str:
    """Format news articles for LLM consumption."""
    if not articles:
        return f"news_api: no articles for {ticker} in last 7 days"

    lines = [f"NewsAPI.org articles mentioning {ticker} (last 7 days, top {len(articles)}):"]
    lines.append("=" * 60)
    for i, art in enumerate(articles[:20], 1):
        source = art.get("source", {}).get("name", "?")
        title = art.get("title", "(no title)").replace("\n", " ").strip()
        desc = (art.get("description") or "").replace("\n", " ").strip()[:200]
        published = art.get("publishedAt", "?")[:10]
        url = art.get("url", "")
        lines.append(f"\n[{i}] {title}")
        lines.append(f"    Source: {source} | Published: {published}")
        if desc:
            lines.append(f"    {desc}")
        if url:
            lines.append(f"    {url}")
    return "\n".join(lines)


def get_news_sentiment(ticker: str, days: int = 7, max_articles: int = 20) -> str:
    """Pull recent news for ``ticker`` from NewsAPI.org.

    Args:
        ticker: e.g. "AAPL", "AAOI"
        days: look-back window in days
        max_articles: cap results

    Returns:
        Formatted string with headline + source + date + URL. Designed to be
        dropped directly into a news analyst prompt.
    """
    key = _get_api_key()
    if not key:
        return (
            f"news_api: NEWS_API_KEY not set in environment. "
            f"Register free at https://newsapi.org (100 req/day) and add "
            f"NEWS_API_KEY=... to ~/.zshrc to enable this source."
        )

    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "q": f'"{ticker}" OR "{ticker.split(".")[0]}"',
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": min(max_articles * 2, 100),
    }
    headers = {"X-Api-Key": key}

    try:
        resp = requests.get(API_URL, params=params, headers=headers, timeout=15)
        if resp.status_code == 401:
            return "news_api: invalid API key (401). Check NEWS_API_KEY."
        if resp.status_code == 429:
            global _DAILY_LIMIT_WARNED
            if not _DAILY_LIMIT_WARNED:
                logger.warning("news_api: daily rate limit hit (429)")
                _DAILY_LIMIT_WARNED = True
            return "news_api: daily rate limit hit (429). Free tier = 100 req/day."
        if resp.status_code != 200:
            return f"news_api: HTTP {resp.status_code} - {resp.text[:200]}"
        data = resp.json()
    except Exception as exc:
        return f"news_api: request failed ({type(exc).__name__}: {exc})"

    articles = data.get("articles", [])
    return _format_articles(articles[:max_articles], ticker)
