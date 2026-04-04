import asyncio
from datetime import datetime

from app.services.finnhub import fetch_macro_data
from app.services.fear_greed import fetch_fear_greed
from app.models.schemas import MacroSnapshot, MacroVerdict, Regime


async def run() -> MacroVerdict:
    """
    Macro Scout agent.
    Fetches macro indicators, determines the current risk regime.
    Runs once per session — macro doesn't change on 1h candles.
    """
    # Both are async now
    macro_task = fetch_macro_data()
    fg_task = fetch_fear_greed()

    macro_data, fg_data = await asyncio.gather(macro_task, fg_task)

    snapshot = MacroSnapshot(
        spx_price=macro_data.get("SPX", {}).get("price"),
        spx_change_pct=macro_data.get("SPX", {}).get("change_pct"),
        qqq_price=macro_data.get("QQQ", {}).get("price"),
        qqq_change_pct=macro_data.get("QQQ", {}).get("change_pct"),
        dxy_price=macro_data.get("DXY", {}).get("price"),
        dxy_change_pct=macro_data.get("DXY", {}).get("change_pct"),
        us10y_yield=macro_data.get("US10Y", {}).get("price"),
        us10y_change_pct=macro_data.get("US10Y", {}).get("change_pct"),
        dow_price=macro_data.get("DOW", {}).get("price"),
        dow_change_pct=macro_data.get("DOW", {}).get("change_pct"),
        gold_price=macro_data.get("GOLD", {}).get("price"),
        gold_change_pct=macro_data.get("GOLD", {}).get("change_pct"),
        vix_price=macro_data.get("VIX", {}).get("price"),
        vix_change_pct=macro_data.get("VIX", {}).get("change_pct"),
        fear_greed_index=fg_data.get("value"),
        fear_greed_label=fg_data.get("label"),
        fetched_at=datetime.now(),
    )

    regime, confidence, summary = _determine_regime(snapshot)

    return MacroVerdict(
        regime=regime,
        confidence=confidence,
        summary=summary,
        data=snapshot,
    )


def _determine_regime(snap: MacroSnapshot) -> tuple[Regime, float, str]:
    """
    Simple scoring model for macro regime.

    Bullish signals (risk-on):
      - SPX up, QQQ up
      - DXY down (weaker dollar = risk-on)
      - US10Y falling (dovish)
      - Fear & Greed > 50

    Bearish signals (risk-off):
      - SPX down, QQQ down
      - DXY up (flight to safety)
      - US10Y rising sharply
      - Fear & Greed < 30
    """
    score = 0
    signals = []

    # Equities
    if snap.spx_change_pct is not None:
        if snap.spx_change_pct > 0.3:
            score += 1
            signals.append("SPX trending up")
        elif snap.spx_change_pct < -0.3:
            score -= 1
            signals.append("SPX under pressure")

    if snap.qqq_change_pct is not None:
        if snap.qqq_change_pct > 0.3:
            score += 1
            signals.append("QQQ/tech strong")
        elif snap.qqq_change_pct < -0.3:
            score -= 1
            signals.append("QQQ/tech weak")

    # Dollar (inverse relationship with crypto)
    if snap.dxy_change_pct is not None:
        if snap.dxy_change_pct > 0.2:
            score -= 1
            signals.append("Dollar strengthening (headwind)")
        elif snap.dxy_change_pct < -0.2:
            score += 1
            signals.append("Dollar weakening (tailwind)")

    # Yields
    if snap.us10y_change_pct is not None:
        if snap.us10y_change_pct > 1.0:
            score -= 1
            signals.append("Yields rising sharply")
        elif snap.us10y_change_pct < -1.0:
            score += 1
            signals.append("Yields falling (dovish)")

    # Fear & Greed
    if snap.fear_greed_index is not None:
        if snap.fear_greed_index >= 65:
            score += 1
            signals.append(f"Market greed ({snap.fear_greed_index})")
        elif snap.fear_greed_index <= 15:
            score -= 2
            signals.append(f"Extreme fear ({snap.fear_greed_index})")
        elif snap.fear_greed_index <= 30:
            score -= 1
            signals.append(f"Market fear ({snap.fear_greed_index})")

    # Determine regime
    if score >= 2:
        regime = Regime.RISK_ON
    elif score <= -2:
        regime = Regime.RISK_OFF
    else:
        regime = Regime.NEUTRAL

    # Confidence based on how many signals agree
    max_possible = 5
    confidence = min(abs(score) / max_possible, 1.0)

    summary = (f"Regime: {regime.value} (confidence {confidence:.0%}). " + "; ".join(signals)) if signals else "Insufficient data for regime determination."

    return regime, round(confidence, 2), summary
