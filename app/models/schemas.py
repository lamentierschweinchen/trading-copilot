from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


# --- Enums ---

class Regime(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


class Signal(str, Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    NEUTRAL = "neutral"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


# --- Service-level data ---

class Kline(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class MacroSnapshot(BaseModel):
    spx_price: float | None = None
    spx_change_pct: float | None = None
    qqq_price: float | None = None
    qqq_change_pct: float | None = None
    dxy_price: float | None = None
    dxy_change_pct: float | None = None
    us10y_yield: float | None = None
    us10y_change_pct: float | None = None
    dow_price: float | None = None
    dow_change_pct: float | None = None
    gold_price: float | None = None
    gold_change_pct: float | None = None
    vix_price: float | None = None
    vix_change_pct: float | None = None
    fear_greed_index: int | None = None
    fear_greed_label: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.now)


class FundingRate(BaseModel):
    symbol: str
    rate: float
    timestamp: int


class OpenInterest(BaseModel):
    symbol: str
    open_interest: float
    open_interest_usd: float | None = None


# --- Indicator outputs ---

class MACDResult(BaseModel):
    macd_line: float
    signal_line: float
    histogram: float
    crossover: str  # "bullish", "bearish", "none"


class BollingerResult(BaseModel):
    upper: float
    middle: float
    lower: float
    price: float
    position: str  # "above_upper", "upper_half", "lower_half", "below_lower"
    bandwidth: float


class RSIResult(BaseModel):
    value: float
    condition: str  # "overbought", "neutral", "oversold"


class ATRResult(BaseModel):
    value: float     # absolute ATR value
    pct: float       # ATR as percentage of current price
    period: int = 14


class VWAPResult(BaseModel):
    value: float
    price_vs_vwap: str    # "above", "below", "at"
    distance_pct: float   # percentage distance from VWAP


class VolumeResult(BaseModel):
    current: float           # current bar volume
    avg_20: float            # 20-period average volume
    ratio: float             # current / avg — >1.5 = high, <0.5 = low
    trend: str               # "high", "above_avg", "normal", "low"


class TechnicalSnapshot(BaseModel):
    symbol: str
    timeframe: str
    price: float
    macd: MACDResult
    bollinger: BollingerResult
    rsi: RSIResult
    atr: ATRResult | None = None
    vwap: VWAPResult | None = None
    volume: VolumeResult | None = None
    signal: Signal
    signal_strength: float = Field(ge=0, le=1)


# --- Agent outputs ---

class MacroVerdict(BaseModel):
    regime: Regime
    confidence: float = Field(ge=0, le=1)
    summary: str
    data: MacroSnapshot


class AssetIntel(BaseModel):
    symbol: str
    price: float
    change_24h_pct: float | None = None
    volume_24h: float | None = None
    sparkline_24h: list[float] | None = None
    price_levels: list[PriceLevel] | None = None      # key S/R levels
    scalp_tf: TechnicalSnapshot | None = None          # 15m
    primary_tf: TechnicalSnapshot                      # 1h
    confirmation_tf: TechnicalSnapshot | None = None   # 4h


class LeverageContext(BaseModel):
    symbol: str
    funding_rate: float | None = None
    funding_sentiment: str | None = None  # "longs_paying", "shorts_paying", "neutral"
    open_interest: float | None = None
    oi_change_pct: float | None = None
    positioning_summary: str | None = None


# --- Synthesizer output ---

class TradeScenario(BaseModel):
    """Conservative / Moderate / Aggressive tier for a trade."""
    tier: str                  # "conservative", "moderate", "aggressive"
    leverage: str              # e.g. "3x", "5x", "10x"
    entry: str                 # entry price or zone
    target: str                # take-profit level
    stop_loss: str             # stop-loss level
    risk_reward: float         # R:R ratio
    position_size_pct: float   # suggested % of portfolio


class ConvictionBreakdown(BaseModel):
    """What contributed to the recommendation's conviction score."""
    macd_score: float = 0       # -1 to +1
    bollinger_score: float = 0  # -1 to +1
    rsi_score: float = 0       # -1 to +1
    volume_score: float = 0    # -1 to +1
    tf_alignment: float = 0   # 0 to +1 (multi-timeframe agreement)
    macro_score: float = 0    # -1 to +1
    total: float = 0


class PriceLevel(BaseModel):
    """Key price level for an asset (support/resistance/alert)."""
    label: str                 # "Support 1", "Resistance 1", "BB Upper", etc.
    price: float
    level_type: str            # "support", "resistance", "indicator"
    source: str                # "bollinger", "vwap", "atr", "round_number"


class TradeRecommendation(BaseModel):
    symbol: str
    direction: Direction
    conviction: int = Field(ge=1, le=10)
    leverage: str  # e.g. "5x", "10x" — mapped from conviction
    entry_zone: str
    target: str
    invalidation: str  # THE most important field
    rationale: str
    macro_alignment: bool
    scenarios: list[TradeScenario] | None = None
    conviction_breakdown: ConvictionBreakdown | None = None
    expires_after_hours: int = 12  # auto-expire if not entered
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionBrief(BaseModel):
    macro: MacroVerdict
    assets: list[AssetIntel]
    leverage: list[LeverageContext]
    recommendations: list[TradeRecommendation]
    feedback_summary: str | None = None
    generated_at: datetime = Field(default_factory=datetime.now)


class SessionSummary(BaseModel):
    """Lightweight summary for session history timeline."""
    id: int
    timestamp: str
    regime: str | None = None
    confidence: float | None = None
    rec_count: int = 0
    symbols: list[str] | None = None


# --- Feedback loop ---

class TradeLog(BaseModel):
    id: str
    recommendation: TradeRecommendation
    logged_at: datetime
    resolved: bool = False
    outcome: str | None = None  # "target_hit", "invalidated", "manual_close"
    actual_exit_price: float | None = None
    pnl_pct: float | None = None
    resolved_at: datetime | None = None
    notes: str | None = None


class FeedbackStats(BaseModel):
    total_trades: int
    resolved_trades: int
    win_rate: float | None = None
    avg_conviction_winners: float | None = None
    avg_conviction_losers: float | None = None
    best_asset: str | None = None
    worst_asset: str | None = None
    regime_performance: dict[str, float] | None = None
    summary: str
