from __future__ import annotations

import asyncio

from app.config import settings
from app.services.binance import fetch_klines, fetch_ticker_24h
from app.indicators.technical import analyze_klines
from app.models.schemas import AssetIntel, PriceLevel


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

    # Fetch all three timeframes + 24h stats concurrently
    scalp_klines, primary_klines, confirm_klines, ticker = await asyncio.gather(
        fetch_klines(binance_sym, settings.SCALP_TIMEFRAME, settings.KLINE_LIMIT),
        fetch_klines(binance_sym, settings.PRIMARY_TIMEFRAME, settings.KLINE_LIMIT),
        fetch_klines(binance_sym, settings.CONFIRMATION_TIMEFRAME, settings.KLINE_LIMIT),
        fetch_ticker_24h(binance_sym),
    )

    # Compute technicals
    primary_tf = analyze_klines(primary_klines, symbol, settings.PRIMARY_TIMEFRAME)

    scalp_tf = None
    if scalp_klines:
        scalp_tf = analyze_klines(scalp_klines, symbol, settings.SCALP_TIMEFRAME)

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

    # Extract last 24 close prices for sparkline (1h candles = 24h)
    sparkline = None
    if primary_klines and len(primary_klines) >= 24:
        sparkline = [float(k.close) for k in primary_klines[-24:]]

    # Compute key price levels from indicators
    price_levels = _compute_price_levels(primary_tf, confirmation_tf)

    return AssetIntel(
        symbol=symbol,
        price=primary_tf.price,
        change_24h_pct=change_24h,
        volume_24h=volume_24h,
        sparkline_24h=sparkline,
        price_levels=price_levels,
        scalp_tf=scalp_tf,
        primary_tf=primary_tf,
        confirmation_tf=confirmation_tf,
    )


def _compute_price_levels(primary_tf, confirmation_tf=None) -> list[PriceLevel]:
    """Extract key support/resistance levels from technical indicators."""
    levels = []
    price = primary_tf.price
    bb = primary_tf.bollinger

    # Bollinger Bands as levels
    levels.append(PriceLevel(
        label="BB Upper", price=bb.upper,
        level_type="resistance", source="bollinger",
    ))
    levels.append(PriceLevel(
        label="BB Middle", price=bb.middle,
        level_type="indicator", source="bollinger",
    ))
    levels.append(PriceLevel(
        label="BB Lower", price=bb.lower,
        level_type="support", source="bollinger",
    ))

    # VWAP as level
    if primary_tf.vwap:
        levels.append(PriceLevel(
            label="VWAP", price=round(primary_tf.vwap.value, 2),
            level_type="indicator", source="vwap",
        ))

    # ATR-based support/resistance
    if primary_tf.atr:
        atr_val = primary_tf.atr.value
        levels.append(PriceLevel(
            label="ATR Support", price=round(price - atr_val * 1.5, 2),
            level_type="support", source="atr",
        ))
        levels.append(PriceLevel(
            label="ATR Resistance", price=round(price + atr_val * 1.5, 2),
            level_type="resistance", source="atr",
        ))

    # 4h Bollinger as wider context
    if confirmation_tf and confirmation_tf.bollinger:
        cbb = confirmation_tf.bollinger
        levels.append(PriceLevel(
            label="4H BB Upper", price=cbb.upper,
            level_type="resistance", source="bollinger",
        ))
        levels.append(PriceLevel(
            label="4H BB Lower", price=cbb.lower,
            level_type="support", source="bollinger",
        ))

    # Sort by price
    levels.sort(key=lambda l: l.price)
    return levels
