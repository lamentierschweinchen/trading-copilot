from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from datetime import datetime

from app.models.schemas import TradeRecommendation, TradeLog, FeedbackStats

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
TRADES_FILE = DATA_DIR / "trades.json"


def _ensure_file():
    """Ensure data directory and file exist."""
    DATA_DIR.mkdir(exist_ok=True)
    if not TRADES_FILE.exists():
        TRADES_FILE.write_text("[]")


def _load_trades() -> list[dict]:
    """Load all trade logs from disk."""
    _ensure_file()
    return json.loads(TRADES_FILE.read_text())


def _save_trades(trades: list[dict]):
    """Save trade logs to disk."""
    _ensure_file()
    TRADES_FILE.write_text(json.dumps(trades, indent=2, default=str))


def log_recommendation(rec: TradeRecommendation) -> TradeLog:
    """Log a new trade recommendation for tracking."""
    trades = _load_trades()

    log = TradeLog(
        id=str(uuid.uuid4())[:8],
        recommendation=rec,
        logged_at=datetime.now(),
    )

    trades.append(json.loads(log.model_dump_json()))
    _save_trades(trades)

    return log


def resolve_trade(
    trade_id: str,
    outcome: str,
    exit_price: float,
    notes: str | None = None,
) -> TradeLog | None:
    """Resolve an open trade with its outcome."""
    trades = _load_trades()

    for t in trades:
        if t["id"] == trade_id:
            entry_price = _parse_entry_price(t["recommendation"]["entry_zone"])
            direction = t["recommendation"]["direction"]

            pnl_pct = None
            if entry_price is not None:
                if direction == "long":
                    pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
                else:
                    pnl_pct = round(((entry_price - exit_price) / entry_price) * 100, 2)
            else:
                logger.warning("Could not parse entry price from '%s' for trade %s", t["recommendation"]["entry_zone"], trade_id)

            t["resolved"] = True
            t["outcome"] = outcome
            t["actual_exit_price"] = exit_price
            t["pnl_pct"] = pnl_pct
            t["resolved_at"] = datetime.now().isoformat()
            t["notes"] = notes

            _save_trades(trades)
            return TradeLog(**t)

    return None


def _parse_entry_price(entry_zone: str) -> float | None:
    """Extract entry price from entry_zone string. Handles formats like '$68,000-$69,000', '68000-68500', 'around $68,000'."""
    try:
        # Try the original approach: split on dash, take first part
        price_str = entry_zone.split("-")[0].replace("$", "").replace(",", "").strip()
        return float(price_str)
    except (ValueError, IndexError):
        pass
    # Fallback: extract first number from the string
    match = re.search(r"[\d,]+\.?\d*", entry_zone.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


def expire_stale_trades() -> int:
    """Auto-expire trades past their expiry window. Returns count expired."""
    trades = _load_trades()
    now = datetime.now()
    expired_count = 0

    for t in trades:
        if t.get("resolved", False):
            continue
        rec = t.get("recommendation", {})
        expires_hours = rec.get("expires_after_hours", 12)
        logged_at = datetime.fromisoformat(t["logged_at"])
        if (now - logged_at).total_seconds() > expires_hours * 3600:
            t["resolved"] = True
            t["outcome"] = "expired"
            t["resolved_at"] = now.isoformat()
            t["notes"] = f"Auto-expired after {expires_hours}h — setup window passed"
            expired_count += 1

    if expired_count > 0:
        _save_trades(trades)
        logger.info("Auto-expired %d stale trades", expired_count)
    return expired_count


def get_open_trades() -> list[TradeLog]:
    """Get all unresolved trades."""
    expire_stale_trades()
    trades = _load_trades()
    return [TradeLog(**t) for t in trades if not t.get("resolved", False)]


def get_all_trades() -> list[TradeLog]:
    """Get all trades."""
    trades = _load_trades()
    return [TradeLog(**t) for t in trades]


def compute_feedback_stats() -> FeedbackStats:
    """Compute performance statistics from trade history."""
    trades = _load_trades()

    total = len(trades)
    resolved = [t for t in trades if t.get("resolved", False)]
    resolved_count = len(resolved)

    if resolved_count == 0:
        return FeedbackStats(
            total_trades=total,
            resolved_trades=0,
            summary="No resolved trades yet. Track record building.",
        )

    winners = [t for t in resolved if (t.get("pnl_pct") or 0) > 0]
    losers = [t for t in resolved if (t.get("pnl_pct") or 0) <= 0]
    win_rate = len(winners) / resolved_count

    avg_conv_win = (
        sum(t["recommendation"]["conviction"] for t in winners) / len(winners)
        if winners else None
    )
    avg_conv_lose = (
        sum(t["recommendation"]["conviction"] for t in losers) / len(losers)
        if losers else None
    )

    # Per-asset performance
    asset_pnl: dict[str, list[float]] = {}
    for t in resolved:
        sym = t["recommendation"]["symbol"]
        asset_pnl.setdefault(sym, []).append(t.get("pnl_pct", 0))

    asset_avg = {sym: sum(pnls) / len(pnls) for sym, pnls in asset_pnl.items()}
    best_asset = max(asset_avg, key=asset_avg.get) if asset_avg else None
    worst_asset = min(asset_avg, key=asset_avg.get) if asset_avg else None

    # Regime performance (requires the macro_alignment field)
    aligned = [t for t in resolved if t["recommendation"].get("macro_alignment")]
    misaligned = [t for t in resolved if not t["recommendation"].get("macro_alignment")]

    regime_perf = {}
    if aligned:
        regime_perf["aligned_with_macro"] = round(
            len([t for t in aligned if (t.get("pnl_pct") or 0) > 0]) / len(aligned), 2
        )
    if misaligned:
        regime_perf["against_macro"] = round(
            len([t for t in misaligned if (t.get("pnl_pct") or 0) > 0]) / len(misaligned), 2
        )

    # Build summary
    parts = [f"Win rate: {win_rate:.0%} across {resolved_count} trades."]
    if avg_conv_win and avg_conv_lose:
        parts.append(f"Avg conviction: {avg_conv_win:.1f} on wins vs {avg_conv_lose:.1f} on losses.")
    if regime_perf and "aligned_with_macro" in regime_perf:
        parts.append(f"Macro-aligned trades win {regime_perf['aligned_with_macro']:.0%} of the time.")
    if best_asset:
        parts.append(f"Best: {best_asset}, Worst: {worst_asset}.")

    return FeedbackStats(
        total_trades=total,
        resolved_trades=resolved_count,
        win_rate=round(win_rate, 3),
        avg_conviction_winners=round(avg_conv_win, 1) if avg_conv_win else None,
        avg_conviction_losers=round(avg_conv_lose, 1) if avg_conv_lose else None,
        best_asset=best_asset,
        worst_asset=worst_asset,
        regime_performance=regime_perf if regime_perf else None,
        summary=" ".join(parts),
    )
