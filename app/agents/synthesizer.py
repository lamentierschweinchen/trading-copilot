from __future__ import annotations

import json
import logging

from anthropic import AsyncAnthropic

from app.config import settings
from app.models.schemas import (
    MacroVerdict, AssetIntel, LeverageContext,
    TradeRecommendation, SessionBrief, FeedbackStats,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a crypto leverage trading analyst. You receive structured market data from three specialized agents and synthesize it into actionable SHORT-TERM leverage trade recommendations.

These are scalps and quick swings — in and out within hours. Funding rates are a real cost, not just a signal.

## Framework

1. MACRO FILTER: If the macro regime is risk_off, reduce conviction on all longs by 2 points and increase conviction on shorts. Vice versa for risk_on. Neutral = no adjustment.

2. TECHNICAL CONFLUENCE: A strong setup requires at least 2 of 3 indicators aligning:
   - MACD crossover (bullish or bearish)
   - Bollinger Band position (below lower = bounce candidate, above upper = mean reversion)
   - RSI extreme (oversold < 30 = long candidate, overbought > 70 = short candidate)

3. LEVERAGE CONTEXT: This is your risk filter AND cost filter.
   - If funding is heavily positive and you're going long, reduce conviction — you're paying to hold AND the market is crowded.
   - If funding is negative and you're going long, that's contrarian — increase conviction if technicals confirm.
   - High funding rates in either direction mean the position is expensive to hold. Tighter timeframes.

4. TIMEFRAME ALIGNMENT: If the 1h and 4h signals agree, increase conviction. If they conflict, note it and reduce conviction.

## Leverage Sizing (conviction → leverage)

Map conviction directly to position leverage:
- Conviction 5: 3x leverage (minimum viable edge)
- Conviction 6: 5x
- Conviction 7: 7x
- Conviction 8: 10x
- Conviction 9-10: 12-15x (exceptional setups only)

Higher leverage = tighter invalidation required. At 10x+, invalidation must be within 1-2% of entry.

## Output Rules

- Only recommend trades with conviction >= 5.
- Every recommendation MUST include an invalidation level — the exact price where the thesis is dead. This is non-negotiable.
- Include leverage as a string like "5x" or "10x".
- Entry zone should be a tight range (these are short-term trades).
- Target should be realistic for a hours-long hold (1-3% moves, not moonshots).
- Provide a clear, concise rationale (2-3 sentences max).
- If no setups meet the conviction threshold, say so. "No trade" is always valid.
- Maximum 3 recommendations per session. Quality over quantity.
- These trades expire after 12 hours. If the setup hasn't triggered, it's dead.

## Risk Reminders
- Leverage amplifies losses. Invalidation is life or death at 10x+.
- Funding rate extremes often precede violent reversals.
- Never fade the macro regime with high conviction.
- At 10x, a 10% move against you is a liquidation. Size accordingly.

Respond ONLY with valid JSON matching this schema:
{
  "recommendations": [
    {
      "symbol": "BTC",
      "direction": "long" | "short",
      "conviction": 5-10,
      "leverage": "5x",
      "entry_zone": "$66,800-$67,000",
      "target": "$68,500",
      "invalidation": "$66,200",
      "rationale": "string",
      "macro_alignment": true | false
    }
  ],
  "market_summary": "1-2 sentence overall market read"
}"""


async def run(
    macro: MacroVerdict,
    assets: list[AssetIntel],
    leverage: list[LeverageContext],
    feedback: FeedbackStats | None = None,
) -> list[TradeRecommendation]:
    """
    Synthesizer agent.
    Routes to local rule-based engine or Claude API based on config.
    """
    if settings.mock_synthesizer:
        logger.info("Using local synthesizer (MOCK_SYNTHESIZER=true)")
        return _run_local(macro, assets, leverage)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Build the data payload
    user_message = _build_prompt(macro, assets, leverage, feedback)

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # Parse response
    response_text = response.content[0].text

    # Strip markdown code fences if present
    clean = response_text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        logger.error("Failed to parse synthesizer JSON response: %s", clean[:500])
        return []

    recommendations = []
    for rec in data.get("recommendations", []):
        if rec.get("conviction", 0) < 5:
            continue
        try:
            conv = rec["conviction"]
            recommendations.append(
                TradeRecommendation(
                    symbol=rec["symbol"],
                    direction=rec["direction"],
                    conviction=conv,
                    leverage=rec.get("leverage", _conviction_to_leverage(conv)),
                    entry_zone=rec["entry_zone"],
                    target=rec["target"],
                    invalidation=rec["invalidation"],
                    rationale=rec["rationale"],
                    macro_alignment=rec.get("macro_alignment", False),
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed recommendation: %s — %s", rec, e)
            continue

    return recommendations


def _build_prompt(
    macro: MacroVerdict,
    assets: list[AssetIntel],
    leverage: list[LeverageContext],
    feedback: FeedbackStats | None = None,
) -> str:
    """Build the structured prompt for the synthesizer."""

    sections = []

    # Macro context
    def _fmt(val, fmt="+.2f", suffix="%"):
        return f"{val:{fmt}}{suffix}" if val is not None else "N/A"

    d = macro.data
    sections.append(f"""## MACRO REGIME
Regime: {macro.regime.value}
Confidence: {macro.confidence:.0%}
Summary: {macro.summary}
Data: SPX {d.spx_price or 'N/A'} ({_fmt(d.spx_change_pct)}) | QQQ {d.qqq_price or 'N/A'} ({_fmt(d.qqq_change_pct)}) | DXY {d.dxy_price or 'N/A'} ({_fmt(d.dxy_change_pct)}) | US10Y {d.us10y_yield or 'N/A'}% ({_fmt(d.us10y_change_pct)}) | Fear & Greed: {d.fear_greed_index or 'N/A'} ({d.fear_greed_label or 'N/A'})""")

    # Asset technicals
    asset_lines = []
    for a in assets:
        tf = a.primary_tf
        conf = a.confirmation_tf
        change_str = f"{a.change_24h_pct:+.1f}%" if a.change_24h_pct is not None else "N/A"
        line = f"""### {a.symbol} — ${a.price:,.2f} ({change_str} 24h)
Primary ({tf.timeframe}): Signal={tf.signal.value} (strength {tf.signal_strength}) | MACD: histogram={tf.macd.histogram}, crossover={tf.macd.crossover} | BB: position={tf.bollinger.position}, bandwidth={tf.bollinger.bandwidth} | RSI: {tf.rsi.value} ({tf.rsi.condition})"""
        if conf:
            line += f"""
Confirmation ({conf.timeframe}): Signal={conf.signal.value} (strength {conf.signal_strength}) | MACD crossover={conf.macd.crossover} | BB position={conf.bollinger.position} | RSI: {conf.rsi.value} ({conf.rsi.condition})"""
        asset_lines.append(line)

    sections.append("## ASSET TECHNICALS\n" + "\n\n".join(asset_lines))

    # Leverage context
    lev_lines = []
    for lc in leverage:
        line = f"- {lc.symbol}: {lc.positioning_summary}"
        lev_lines.append(line)

    sections.append("## LEVERAGE CONTEXT\n" + "\n".join(lev_lines))

    # Feedback (if available)
    if feedback and feedback.total_trades > 0:
        win_rate_str = f"{feedback.win_rate:.0%}" if feedback.win_rate is not None else "N/A"
        sections.append(f"""## HISTORICAL PERFORMANCE
Total trades: {feedback.total_trades} | Resolved: {feedback.resolved_trades} | Win rate: {win_rate_str}
Avg conviction on winners: {feedback.avg_conviction_winners or 'N/A'} | Avg conviction on losers: {feedback.avg_conviction_losers or 'N/A'}
Best asset: {feedback.best_asset or 'N/A'} | Worst asset: {feedback.worst_asset or 'N/A'}
Regime breakdown: {json.dumps(feedback.regime_performance)}
Note: {feedback.summary}""")

    return "\n\n".join(sections)


def _conviction_to_leverage(conviction: int) -> str:
    """Map conviction score to leverage multiplier."""
    if conviction <= 5:
        return "3x"
    elif conviction == 6:
        return "5x"
    elif conviction == 7:
        return "7x"
    elif conviction == 8:
        return "10x"
    elif conviction == 9:
        return "12x"
    else:
        return "15x"


def _run_local(
    macro: MacroVerdict,
    assets: list[AssetIntel],
    leverage: list[LeverageContext],
) -> list[TradeRecommendation]:
    """
    Local rule-based synthesizer. Applies the same confluence framework
    as the system prompt without calling the API.
    """
    from app.models.schemas import Signal, Regime, Direction

    lev_map = {lc.symbol: lc for lc in leverage}
    candidates = []

    for asset in assets:
        tf = asset.primary_tf
        conf = asset.confirmation_tf

        # --- 1. Technical confluence: count aligned indicators ---
        bullish_count = 0
        bearish_count = 0

        if tf.macd.crossover == "bullish":
            bullish_count += 1
        elif tf.macd.crossover == "bearish":
            bearish_count += 1

        if tf.bollinger.position == "below_lower":
            bullish_count += 1
        elif tf.bollinger.position == "above_upper":
            bearish_count += 1

        if tf.rsi.condition == "oversold":
            bullish_count += 1
        elif tf.rsi.condition == "overbought":
            bearish_count += 1

        # Need at least 2 of 3 indicators aligning
        if bullish_count < 2 and bearish_count < 2:
            continue

        is_long = bullish_count >= 2
        direction = Direction.LONG if is_long else Direction.SHORT
        conviction = 5 + max(bullish_count, bearish_count) - 2  # base 5, +1 per extra indicator

        # --- 2. Timeframe alignment ---
        if conf:
            primary_bullish = tf.signal in (Signal.STRONG_BUY, Signal.BUY)
            conf_bullish = conf.signal in (Signal.STRONG_BUY, Signal.BUY)
            primary_bearish = tf.signal in (Signal.STRONG_SELL, Signal.SELL)
            conf_bearish = conf.signal in (Signal.STRONG_SELL, Signal.SELL)

            if (is_long and primary_bullish and conf_bullish) or (not is_long and primary_bearish and conf_bearish):
                conviction += 1  # timeframes agree
            elif (is_long and conf_bearish) or (not is_long and conf_bullish):
                conviction -= 1  # timeframes conflict

        # --- 3. Macro filter ---
        macro_aligned = True
        if macro.regime == Regime.RISK_OFF and is_long:
            conviction -= 2
            macro_aligned = False
        elif macro.regime == Regime.RISK_OFF and not is_long:
            conviction += 1
        elif macro.regime == Regime.RISK_ON and is_long:
            conviction += 1
        elif macro.regime == Regime.RISK_ON and not is_long:
            conviction -= 2
            macro_aligned = False

        # --- 4. Leverage context ---
        lc = lev_map.get(asset.symbol)
        if lc and lc.funding_sentiment:
            if is_long and lc.funding_sentiment == "longs_paying":
                conviction -= 1  # crowded, squeeze risk
            elif is_long and lc.funding_sentiment == "shorts_paying":
                conviction += 1  # contrarian
            elif not is_long and lc.funding_sentiment == "shorts_paying":
                conviction -= 1
            elif not is_long and lc.funding_sentiment == "longs_paying":
                conviction += 1

        conviction = max(1, min(10, conviction))
        if conviction < 5:
            continue

        # --- Build recommendation ---
        price = asset.price
        bb = tf.bollinger
        lev_str = _conviction_to_leverage(conviction)
        lev_mult = int(lev_str.replace("x", ""))

        # Tighter spreads at higher leverage
        spread_pct = 0.003  # 0.3% entry zone for scalps
        # Target scales inversely with leverage (higher lev = tighter target)
        target_pct = max(0.01, 0.03 / (lev_mult / 5))  # ~1-3%
        # Invalidation must be tight at high leverage
        inval_pct = max(0.005, 0.02 / (lev_mult / 5))  # ~0.5-2%

        if is_long:
            entry_lo = price * (1 - spread_pct)
            entry_hi = price
            target_price = price * (1 + target_pct)
            invalidation = price * (1 - inval_pct)
            rationale_parts = []
            if tf.macd.crossover == "bullish":
                rationale_parts.append("bullish MACD crossover")
            if tf.rsi.condition == "oversold":
                rationale_parts.append(f"RSI oversold at {tf.rsi.value}")
            if tf.bollinger.position == "below_lower":
                rationale_parts.append("price below lower BB")
        else:
            entry_lo = price
            entry_hi = price * (1 + spread_pct)
            target_price = price * (1 - target_pct)
            invalidation = price * (1 + inval_pct)
            rationale_parts = []
            if tf.macd.crossover == "bearish":
                rationale_parts.append("bearish MACD crossover")
            if tf.rsi.condition == "overbought":
                rationale_parts.append(f"RSI overbought at {tf.rsi.value}")
            if tf.bollinger.position == "above_upper":
                rationale_parts.append("price above upper BB")

        rationale = f"{lev_str} {direction.value} — {asset.symbol} shows {' + '.join(rationale_parts)} on {tf.timeframe}."
        if conf:
            rationale += f" {conf.timeframe} confirms with {conf.signal.value} signal."
        if lc and lc.funding_sentiment and lc.funding_sentiment != "neutral":
            rationale += f" Funding: {lc.funding_sentiment}."
        if not macro_aligned:
            rationale += f" Caution: against {macro.regime.value} macro."

        candidates.append(TradeRecommendation(
            symbol=asset.symbol,
            direction=direction,
            conviction=conviction,
            leverage=lev_str,
            entry_zone=f"${entry_lo:,.2f}-${entry_hi:,.2f}",
            target=f"${target_price:,.2f}",
            invalidation=f"${invalidation:,.2f}",
            rationale=rationale,
            macro_alignment=macro_aligned,
        ))

    # Sort by conviction descending, cap at 3
    candidates.sort(key=lambda r: r.conviction, reverse=True)
    return candidates[:3]
