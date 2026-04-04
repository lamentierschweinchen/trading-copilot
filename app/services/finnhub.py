import asyncio
import logging
import time

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(5)
_cache: dict = {}
_cache_ttl = 300  # 5 minutes


async def fetch_macro_data() -> dict:
    """
    Fetch macro indicators via Finnhub API.
    Returns dict of label -> {price, change_pct} (same format as old yahoo.py).
    """
    now = time.time()
    if _cache and (now - _cache.get("_ts", 0)) < _cache_ttl:
        return _cache.get("data", {})

    results = {}

    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [
            _fetch_quote(client, label, symbol)
            for label, symbol in settings.MACRO_TICKERS.items()
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for resp in responses:
        if isinstance(resp, dict):
            results.update(resp)

    _cache["data"] = results
    _cache["_ts"] = now

    return results


async def _fetch_quote(client: httpx.AsyncClient, label: str, symbol: str) -> dict:
    """Fetch a single quote from Finnhub."""
    async with _semaphore:
        try:
            resp = await client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": symbol, "token": settings.finnhub_api_key},
            )
            resp.raise_for_status()
            data = resp.json()

            price = data.get("c")  # current price
            change_pct = data.get("dp")  # daily change percentage

            if price is None or price == 0:
                return {label: {"price": None, "change_pct": None}}

            return {label: {"price": round(price, 2), "change_pct": round(change_pct, 3) if change_pct else None}}
        except Exception:
            logger.warning("Failed to fetch Finnhub quote for %s (%s)", label, symbol)
            return {label: {"price": None, "change_pct": None}}
