from __future__ import annotations

import asyncio

from app.config import settings
from app.services.binance import fetch_funding_rate, fetch_open_interest
from app.models.schemas import LeverageContext


async def run(symbols: list[str] | None = None) -> list[LeverageContext]:
    """
    Leverage Context agent.
    Fetches funding rates and open interest to understand market positioning.
    """
    if symbols is None:
        symbols = list(settings.ASSETS.keys())

    tasks = [_analyze_positioning(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, LeverageContext)]


async def _analyze_positioning(symbol: str) -> LeverageContext:
    """Fetch leverage data for a single asset."""
    asset_config = settings.ASSETS[symbol]
    binance_sym = asset_config["binance"]

    funding, oi = await asyncio.gather(
        fetch_funding_rate(binance_sym),
        fetch_open_interest(binance_sym),
    )

    # Interpret funding rate
    funding_rate = None
    funding_sentiment = None
    if funding:
        funding_rate = funding.rate
        if funding.rate > 0.0005:
            funding_sentiment = "longs_paying"
        elif funding.rate < -0.0005:
            funding_sentiment = "shorts_paying"
        else:
            funding_sentiment = "neutral"

    oi_value = oi.open_interest if oi else None

    # Build summary
    parts = []
    if funding_sentiment == "longs_paying":
        parts.append(f"longs paying {funding_rate:.4%} funding (crowded long)")
    elif funding_sentiment == "shorts_paying":
        parts.append(f"shorts paying {abs(funding_rate):.4%} funding (crowded short)")
    else:
        parts.append("funding neutral")

    if oi_value:
        parts.append(f"OI: {oi_value:,.0f} contracts")

    return LeverageContext(
        symbol=symbol,
        funding_rate=funding_rate,
        funding_sentiment=funding_sentiment,
        open_interest=oi_value,
        positioning_summary="; ".join(parts) if parts else None,
    )
