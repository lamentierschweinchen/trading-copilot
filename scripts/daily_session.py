#!/usr/bin/env python3
"""
Daily self-review script for Trading Copilot.

Runs every morning:
1. Expires stale trades
2. Auto-resolves trades that hit target or invalidation overnight
3. Runs a new session
4. Writes structured daily log to the journal repo
5. Commits and pushes

The journal is the model's memory — it reads its own history
to calibrate future recommendations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.agents import macro_scout, market_intel, leverage_context, synthesizer
from app.feedback.loop import (
    log_recommendation,
    expire_stale_trades,
    get_all_trades,
    get_open_trades,
    compute_feedback_stats,
    _load_trades,
    _save_trades,
)
from app.services.binance import fetch_klines, fetch_ticker_24h
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("daily_session")

# Where the journal lives — set via env or default
JOURNAL_DIR = Path(PROJECT_ROOT / "journal")


def _parse_price_from_str(s: str) -> float | None:
    """Extract a numeric price from strings like '$66,800.00' or '$1.32'."""
    match = re.search(r"[\d,]+\.?\d*", s.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


async def auto_resolve_trades():
    """
    Check open trades against current prices.
    If price hit target → resolve as win.
    If price hit invalidation → resolve as loss.
    """
    trades = _load_trades()
    open_trades = [t for t in trades if not t.get("resolved", False)]

    if not open_trades:
        logger.info("No open trades to check")
        return 0

    # Get current prices for all symbols with open trades
    symbols = list(set(t["recommendation"]["symbol"] for t in open_trades))
    resolved_count = 0

    for symbol in symbols:
        binance_sym = settings.ASSETS.get(symbol, {}).get("binance")
        if not binance_sym:
            continue

        ticker = await fetch_ticker_24h(binance_sym)
        if not ticker:
            continue

        current_price = float(ticker.get("lastPrice", 0))
        high_24h = float(ticker.get("highPrice", 0))
        low_24h = float(ticker.get("lowPrice", 0))

        for t in open_trades:
            if t["recommendation"]["symbol"] != symbol:
                continue

            rec = t["recommendation"]
            direction = rec["direction"]
            target = _parse_price_from_str(rec.get("target", ""))
            invalidation = _parse_price_from_str(rec.get("invalidation", ""))
            entry = _parse_price_from_str(rec.get("entry_zone", ""))

            if not entry:
                continue

            # Check if price hit target or invalidation using 24h high/low
            hit_target = False
            hit_invalidation = False

            if direction == "long":
                if target and high_24h >= target:
                    hit_target = True
                if invalidation and low_24h <= invalidation:
                    hit_invalidation = True
            else:  # short
                if target and low_24h <= target:
                    hit_target = True
                if invalidation and high_24h >= invalidation:
                    hit_invalidation = True

            # If both hit, invalidation takes priority (conservative)
            if hit_invalidation:
                exit_price = invalidation
                if direction == "long":
                    pnl_pct = ((exit_price - entry) / entry) * 100
                else:
                    pnl_pct = ((entry - exit_price) / entry) * 100

                t["resolved"] = True
                t["outcome"] = "invalidated"
                t["actual_exit_price"] = exit_price
                t["pnl_pct"] = round(pnl_pct, 2)
                t["resolved_at"] = datetime.now().isoformat()
                t["notes"] = f"Auto-resolved: price hit invalidation at ${invalidation:,.2f}"
                resolved_count += 1
                logger.info("INVALIDATED: %s %s %s at $%.2f (PnL: %.2f%%)",
                            rec.get("leverage", ""), direction, symbol, exit_price, pnl_pct)

            elif hit_target:
                exit_price = target
                if direction == "long":
                    pnl_pct = ((exit_price - entry) / entry) * 100
                else:
                    pnl_pct = ((entry - exit_price) / entry) * 100

                t["resolved"] = True
                t["outcome"] = "target_hit"
                t["actual_exit_price"] = exit_price
                t["pnl_pct"] = round(pnl_pct, 2)
                t["resolved_at"] = datetime.now().isoformat()
                t["notes"] = f"Auto-resolved: price hit target at ${target:,.2f}"
                resolved_count += 1
                logger.info("TARGET HIT: %s %s %s at $%.2f (PnL: %.2f%%)",
                            rec.get("leverage", ""), direction, symbol, exit_price, pnl_pct)

    if resolved_count > 0:
        _save_trades(trades)

    return resolved_count


def write_daily_log(session_data: dict, stats: dict):
    """Write structured daily log to journal directory."""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # JSON log (machine-readable — this is what the model parses)
    json_path = JOURNAL_DIR / f"{today}.json"
    log_data = {
        "date": today,
        "timestamp": timestamp,
        "macro": session_data.get("macro"),
        "recommendations": session_data.get("recommendations", []),
        "feedback": stats,
        "assets_analyzed": len(session_data.get("assets", [])),
        "assets_summary": [
            {
                "symbol": a["symbol"],
                "price": a["price"],
                "signal_1h": a["primary_tf"]["signal"],
                "signal_4h": a.get("confirmation_tf", {}).get("signal") if a.get("confirmation_tf") else None,
                "rsi_1h": a["primary_tf"]["rsi"]["value"],
            }
            for a in session_data.get("assets", [])
        ],
    }
    json_path.write_text(json.dumps(log_data, indent=2, default=str))

    # Markdown log (human-readable)
    md_path = JOURNAL_DIR / f"{today}.md"
    macro = session_data.get("macro", {})
    recs = session_data.get("recommendations", [])

    md_lines = [
        f"# Daily Session — {today}",
        f"*Generated at {timestamp}*",
        "",
        f"## Macro: {macro.get('regime', 'unknown')} ({macro.get('confidence', 0):.0%} confidence)",
        f"{macro.get('summary', 'No summary')}",
        "",
    ]

    if recs:
        md_lines.append(f"## Recommendations ({len(recs)})")
        md_lines.append("")
        for r in recs:
            md_lines.extend([
                f"### {r['leverage']} {r['direction'].upper()} {r['symbol']}",
                f"- **Conviction:** {r['conviction']}/10",
                f"- **Entry:** {r['entry_zone']}",
                f"- **Target:** {r['target']}",
                f"- **Invalidation:** {r['invalidation']}",
                f"- **Macro aligned:** {'Yes' if r.get('macro_alignment') else 'No'}",
                f"- *{r['rationale']}*",
                "",
            ])
    else:
        md_lines.extend([
            "## No Recommendations",
            "No setups met the confluence threshold. No trade.",
            "",
        ])

    if stats.get("total_trades", 0) > 0:
        md_lines.extend([
            "## Track Record",
            f"- Total: {stats['total_trades']} | Resolved: {stats['resolved_trades']}",
            f"- Win rate: {stats.get('win_rate', 'N/A')}",
            f"- Best: {stats.get('best_asset', 'N/A')} | Worst: {stats.get('worst_asset', 'N/A')}",
            "",
        ])

    md_path.write_text("\n".join(md_lines))
    logger.info("Journal written: %s", json_path)
    return json_path, md_path


async def run_daily():
    """Full daily pipeline."""
    logger.info("=" * 60)
    logger.info("DAILY SESSION — %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 60)

    # Step 1: Expire stale trades
    expired = expire_stale_trades()
    if expired:
        logger.info("Expired %d stale trades", expired)

    # Step 2: Auto-resolve trades against market
    resolved = await auto_resolve_trades()
    if resolved:
        logger.info("Auto-resolved %d trades", resolved)

    # Step 3: Run all agents
    logger.info("Running agents...")
    results = await asyncio.gather(
        macro_scout.run(),
        market_intel.run(),
        leverage_context.run(),
        return_exceptions=True,
    )

    macro = results[0] if not isinstance(results[0], Exception) else None
    assets = results[1] if not isinstance(results[1], Exception) else []
    leverage_data = results[2] if not isinstance(results[2], Exception) else []

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Agent %d failed: %s", i, r)

    if macro is None:
        logger.error("Macro agent failed — aborting session")
        return

    # Step 4: Get feedback for synthesizer context
    feedback = compute_feedback_stats()

    # Step 5: Run synthesizer
    logger.info("Running synthesizer...")
    recommendations = await synthesizer.run(
        macro=macro,
        assets=assets,
        leverage=leverage_data,
        feedback=feedback if feedback.total_trades > 0 else None,
    )

    logger.info("Got %d recommendations", len(recommendations))

    # Step 6: Log recommendations
    for rec in recommendations:
        logged = log_recommendation(rec)
        logger.info("Logged: %s %s %s (conviction %d, %s)",
                     rec.leverage, rec.direction.value, rec.symbol,
                     rec.conviction, logged.id)

    # Step 7: Write journal
    session_data = {
        "macro": macro.model_dump() if macro else {},
        "assets": [a.model_dump() for a in assets],
        "leverage": [l.model_dump() for l in leverage_data],
        "recommendations": [r.model_dump() for r in recommendations],
    }
    stats = feedback.model_dump()
    json_path, md_path = write_daily_log(session_data, stats)

    # Summary
    logger.info("-" * 40)
    logger.info("SESSION COMPLETE")
    logger.info("  Macro: %s (%s)", macro.regime.value, macro.confidence)
    logger.info("  Assets analyzed: %d", len(assets))
    logger.info("  Recommendations: %d", len(recommendations))
    for r in recommendations:
        logger.info("    %s %s %s — conviction %d, invalidation %s",
                     r.leverage, r.direction.value, r.symbol, r.conviction, r.invalidation)
    logger.info("  Journal: %s", json_path)
    logger.info("-" * 40)


if __name__ == "__main__":
    asyncio.run(run_daily())
