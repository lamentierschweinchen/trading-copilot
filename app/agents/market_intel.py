from __future__ import annotations

import asyncio

from app.config import settings
from app.services.binance import fetch_klines, fetch_ticker_24h
from app.indicators.technical import analyze_klines
from app.models.schemas import AssetIntel


async def run(symbols: list[str] | None = None) -> list[AssetIntel]:
    """
    Market Intel agent.
    Fetches klines for all tracked assets, computes technical indicators.
    """
    if symbols is None:
        symbols = list(settings.ASSETS.keys())

    tasks = [_analyze_asset(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, AssetIntel)]


async def _analyze_asset(symbol: str) -> AssetIntel:
    """Fetch data and run analysis for a single asset."""
    asset_config = settings.ASSETS[symbol]
    binance_sym = asset_config["binance"]

    # Fetch primary and confirmation timeframe klines + 24h stats concurrently
    primary_klines, confirm_klines, ticker = await asyncio.gather(
        fetch_klines(binance_sym, settings.PRIMARY_TIMEFRAME, settings.KLINE_LIMIT),
        fetch_klines(binance_sym, settings.CONFIRMATION_TIMEFRAME, settings.KLINE_LIMIT),
        fetch_ticker_24h(binance_sym),
    )

    # Compute technicals
    primary_tf = analyze_klines(primary_klines, symbol, settings.PRIMARY_TIMEFRAME)

    confirmation_tf = None
    if confirm_klines:
        confirmation_tf = analyze_klines(
            confirm_klines, symbol, settings.CONFIRMATION_TIMEFRAME
        )

    # 24h stats
    change_24h = None
    volume_24h = None
    if ticker:
        change_24h = float(ticker.get("priceChangePercent", 0))
        volume_24h = float(ticker.get("quoteVolume", 0))

    return AssetIntel(
        symbol=symbol,
        price=primary_tf.price,
        change_24h_pct=change_24h,
        volume_24h=volume_24h,
        primary_tf=primary_tf,
        confirmation_tf=confirmation_tf,
    )
