from __future__ import annotations

import asyncio
import logging

import httpx
from app.models.schemas import Kline, FundingRate, OpenInterest

logger = logging.getLogger(__name__)

BASE_SPOT = "https://api.binance.com"
BASE_FUTURES = "https://fapi.binance.com"

# Shared semaphore to avoid Binance rate limits (max 10 concurrent requests)
_semaphore = asyncio.Semaphore(10)

# Reusable client (created lazily, closed on shutdown)
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=15, limits=httpx.Limits(max_connections=20))
    return _client


async def close_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def fetch_klines(
    symbol: str, interval: str = "1h", limit: int = 200
) -> list[Kline]:
    """Fetch candlestick data from Binance spot API."""
    try:
        async with _semaphore:
            client = await _get_client()
            resp = await client.get(
                f"{BASE_SPOT}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            Kline(
                timestamp=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            )
            for k in data
        ]
    except Exception as e:
        logger.warning("Failed to fetch klines for %s (%s): %s", symbol, interval, e)
        return []


async def fetch_funding_rate(symbol: str) -> FundingRate | None:
    """Fetch latest funding rate from Binance Futures."""
    try:
        async with _semaphore:
            client = await _get_client()
            resp = await client.get(
                f"{BASE_FUTURES}/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return None

        latest = data[-1]
        return FundingRate(
            symbol=symbol,
            rate=float(latest["fundingRate"]),
            timestamp=int(latest["fundingTime"]),
        )
    except Exception as e:
        logger.warning("Failed to fetch funding rate for %s: %s", symbol, e)
        return None


async def fetch_open_interest(symbol: str) -> OpenInterest | None:
    """Fetch open interest from Binance Futures."""
    try:
        async with _semaphore:
            client = await _get_client()
            resp = await client.get(
                f"{BASE_FUTURES}/fapi/v1/openInterest",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            data = resp.json()

        return OpenInterest(
            symbol=symbol,
            open_interest=float(data["openInterest"]),
        )
    except Exception as e:
        logger.warning("Failed to fetch open interest for %s: %s", symbol, e)
        return None


async def fetch_ticker_24h(symbol: str) -> dict | None:
    """Fetch 24h price change stats."""
    try:
        async with _semaphore:
            client = await _get_client()
            resp = await client.get(
                f"{BASE_SPOT}/api/v3/ticker/24hr",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("Failed to fetch 24h ticker for %s: %s", symbol, e)
        return None
