from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agents import macro_scout, market_intel, leverage_context, synthesizer

logger = logging.getLogger(__name__)
from app.feedback.loop import (
    log_recommendation,
    resolve_trade,
    get_open_trades,
    get_all_trades,
    compute_feedback_stats,
)
from app.models.schemas import SessionBrief, TradeLog, FeedbackStats
from fastapi.responses import PlainTextResponse


# --- Cache for macro data (refreshed once per session) ---
_macro_cache: dict = {"data": None, "fetched_at": None}
MACRO_TTL_MINUTES = 30


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n🚀 Trading Copilot backend starting...")
    print("   Run a session:  POST /session")
    print("   Check macro:    GET  /macro")
    print("   View trades:    GET  /trades")
    print("   Resolve trade:  POST /trades/{id}/resolve\n")
    yield


app = FastAPI(
    title="Trading Copilot",
    description="Multi-agent crypto trading assistant",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Endpoints ---


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/macro")
async def get_macro():
    """Fetch macro regime (cached for 30 min)."""
    now = datetime.now()
    if (
        _macro_cache["data"] is not None
        and _macro_cache["fetched_at"] is not None
        and (now - _macro_cache["fetched_at"]).total_seconds() < MACRO_TTL_MINUTES * 60
    ):
        return _macro_cache["data"].model_dump()

    macro = await macro_scout.run()
    _macro_cache["data"] = macro
    _macro_cache["fetched_at"] = now
    return macro.model_dump()


@app.get("/assets")
async def get_assets(symbols: str = Query(default=None, description="Comma-separated symbols, e.g. BTC,ETH,SOL")):
    """Fetch technical analysis for assets."""
    sym_list = symbols.split(",") if symbols else None
    assets = await market_intel.run(sym_list)
    return [a.model_dump() for a in assets]


@app.get("/leverage")
async def get_leverage(symbols: str = Query(default=None)):
    """Fetch leverage context (funding rates, OI)."""
    sym_list = symbols.split(",") if symbols else None
    lev = await leverage_context.run(sym_list)
    return [l.model_dump() for l in lev]


@app.post("/session")
async def run_session(symbols: str = Query(default=None)):
    """
    Run a full trading session.
    Spins up all agents, synthesizes recommendations.
    This is the main endpoint.
    """
    sym_list = symbols.split(",") if symbols else None

    # Run all agents concurrently (macro is cached)
    macro_task = _get_or_fetch_macro()
    market_task = market_intel.run(sym_list)
    leverage_task = leverage_context.run(sym_list)

    results = await asyncio.gather(
        macro_task, market_task, leverage_task, return_exceptions=True
    )

    # Handle partial failures
    macro = results[0] if not isinstance(results[0], Exception) else None
    assets = results[1] if not isinstance(results[1], Exception) else []
    leverage_data = results[2] if not isinstance(results[2], Exception) else []

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error("Agent %d failed: %s", i, r)

    if macro is None:
        raise HTTPException(502, "Macro agent failed — cannot run session without macro context")

    # Get feedback stats for the synthesizer
    feedback = compute_feedback_stats()

    # Run synthesizer
    recommendations = await synthesizer.run(
        macro=macro,
        assets=assets,
        leverage=leverage_data,
        feedback=feedback if feedback.total_trades > 0 else None,
    )

    # Auto-log recommendations
    for rec in recommendations:
        log_recommendation(rec)

    brief = SessionBrief(
        macro=macro,
        assets=assets,
        leverage=leverage_data,
        recommendations=recommendations,
        feedback_summary=feedback.summary if feedback.total_trades > 0 else None,
    )

    return brief.model_dump()


async def _get_or_fetch_macro():
    """Get cached macro or fetch fresh."""
    now = datetime.now()
    if (
        _macro_cache["data"] is not None
        and _macro_cache["fetched_at"] is not None
        and (now - _macro_cache["fetched_at"]).total_seconds() < MACRO_TTL_MINUTES * 60
    ):
        return _macro_cache["data"]

    macro = await macro_scout.run()
    _macro_cache["data"] = macro
    _macro_cache["fetched_at"] = now
    return macro


# --- Trade management ---


@app.get("/trades")
async def list_trades(open_only: bool = Query(default=False)):
    """List trade logs."""
    if open_only:
        trades = get_open_trades()
    else:
        trades = get_all_trades()
    return [t.model_dump() for t in trades]


class ResolveRequest(BaseModel):
    outcome: str  # "target_hit", "invalidated", "manual_close"
    exit_price: float
    notes: str | None = None


@app.post("/trades/{trade_id}/resolve")
async def resolve_trade_endpoint(trade_id: str, req: ResolveRequest):
    """Resolve an open trade with outcome."""
    result = resolve_trade(
        trade_id=trade_id,
        outcome=req.outcome,
        exit_price=req.exit_price,
        notes=req.notes,
    )
    if result is None:
        raise HTTPException(404, f"Trade {trade_id} not found")
    return result.model_dump()


@app.get("/feedback")
async def get_feedback():
    """Get performance statistics."""
    stats = compute_feedback_stats()
    return stats.model_dump()


@app.get("/brief", response_class=PlainTextResponse)
async def get_brief(symbols: str = Query(default=None)):
    """
    Gather all agent data and return a formatted prompt
    ready to paste into a Claude Code session.
    """
    sym_list = symbols.split(",") if symbols else None

    results = await asyncio.gather(
        _get_or_fetch_macro(),
        market_intel.run(sym_list),
        leverage_context.run(sym_list),
        return_exceptions=True,
    )

    macro = results[0] if not isinstance(results[0], Exception) else None
    assets = results[1] if not isinstance(results[1], Exception) else []
    leverage_data = results[2] if not isinstance(results[2], Exception) else []

    if macro is None:
        raise HTTPException(502, "Macro agent failed")

    feedback = compute_feedback_stats()
    fb = feedback if feedback.total_trades > 0 else None

    data_prompt = synthesizer._build_prompt(macro, assets, leverage_data, fb)

    brief = f"""You are a crypto trading analyst. I'm going to show you live market data from three agents: macro regime, technical indicators, and leverage positioning.

Analyze this data and tell me:
1. Are there any high-conviction setups right now? (need 2+ indicators aligning)
2. For each setup: direction, entry zone, target, and invalidation level.
3. If nothing looks good, say so — "no trade" is always valid.

These are SHORT-TERM leverage trades (hours, not days). Funding rates are a real cost.

Key rules:
- Macro regime filters everything: risk_off = reduce long conviction, boost shorts. Vice versa for risk_on.
- Funding rate context: if longs are paying and you want to go long, that's crowded AND expensive. Reduce conviction.
- Timeframe alignment (1h + 4h agreeing) increases conviction.
- Invalidation level is the most important output — the price where the thesis is dead.
- Max 3 recommendations. Conviction 1-10 scale, only recommend >= 5.
- Map conviction to leverage: 5=3x, 6=5x, 7=7x, 8=10x, 9+=12-15x.
- Higher leverage = tighter invalidation. At 10x+, invalidation must be within 1-2% of entry.
- Targets should be realistic for hours-long holds (1-3% moves).

---

{data_prompt}

---

What setups do you see? Be specific with price levels."""

    return brief
