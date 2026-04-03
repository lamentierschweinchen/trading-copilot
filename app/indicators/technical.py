from __future__ import annotations

import pandas as pd
import numpy as np
from app.models.schemas import (
    Kline, MACDResult, BollingerResult, RSIResult,
    TechnicalSnapshot, Signal,
)


def klines_to_df(klines: list[Kline]) -> pd.DataFrame:
    """Convert kline list to pandas DataFrame."""
    df = pd.DataFrame([k.model_dump() for k in klines])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp")
    return df


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """Compute MACD indicator."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    # Detect crossover
    crossover = "none"
    if len(histogram) >= 2:
        if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0:
            crossover = "bullish"
        elif histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0:
            crossover = "bearish"

    return MACDResult(
        macd_line=round(float(macd_line.iloc[-1]), 6),
        signal_line=round(float(signal_line.iloc[-1]), 6),
        histogram=round(float(histogram.iloc[-1]), 6),
        crossover=crossover,
    )


def compute_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    """Compute Bollinger Bands."""
    sma = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()

    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    price = float(df["close"].iloc[-1])
    middle = float(sma.iloc[-1])
    upper_val = float(upper.iloc[-1])
    lower_val = float(lower.iloc[-1])

    # Determine position
    if price > upper_val:
        position = "above_upper"
    elif price > middle:
        position = "upper_half"
    elif price > lower_val:
        position = "lower_half"
    else:
        position = "below_lower"

    bandwidth = (upper_val - lower_val) / middle if middle != 0 else 0

    return BollingerResult(
        upper=round(upper_val, 2),
        middle=round(middle, 2),
        lower=round(lower_val, 2),
        price=round(price, 2),
        position=position,
        bandwidth=round(bandwidth, 4),
    )


def compute_rsi(df: pd.DataFrame, period: int = 14) -> RSIResult:
    """Compute RSI."""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # Use Wilder's smoothing after initial SMA
    for i in range(period, len(avg_gain)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1])

    if rsi_val >= 70:
        condition = "overbought"
    elif rsi_val <= 30:
        condition = "oversold"
    else:
        condition = "neutral"

    return RSIResult(value=round(rsi_val, 2), condition=condition)


def compute_signal(
    macd: MACDResult,
    bb: BollingerResult,
    rsi: RSIResult,
) -> tuple[Signal, float]:
    """
    Combine indicators into a composite signal and strength score.

    Scoring:
      MACD crossover:     bullish +2, bearish -2, histogram direction ±1
      Bollinger position:  below_lower +2, above_upper -2, halves ±1
      RSI:                oversold +2, overbought -2, neutral 0

    Score range: [-6, +6] → mapped to Signal enum and 0-1 strength.
    """
    score = 0.0

    # MACD contribution
    if macd.crossover == "bullish":
        score += 2
    elif macd.crossover == "bearish":
        score -= 2
    elif macd.histogram > 0:
        score += 0.5
    elif macd.histogram < 0:
        score -= 0.5

    # Bollinger contribution
    if bb.position == "below_lower":
        score += 2  # potential bounce
    elif bb.position == "above_upper":
        score -= 2  # potential mean reversion
    elif bb.position == "lower_half":
        score += 1
    elif bb.position == "upper_half":
        score -= 1

    # RSI contribution
    if rsi.condition == "oversold":
        score += 2
    elif rsi.condition == "overbought":
        score -= 2

    # Map to signal
    if score >= 4:
        signal = Signal.STRONG_BUY
    elif score >= 2:
        signal = Signal.BUY
    elif score <= -4:
        signal = Signal.STRONG_SELL
    elif score <= -2:
        signal = Signal.SELL
    else:
        signal = Signal.NEUTRAL

    # Strength: absolute score normalized to 0-1
    strength = min(abs(score) / 6.0, 1.0)

    return signal, round(strength, 2)


def analyze_klines(
    klines: list[Kline], symbol: str, timeframe: str
) -> TechnicalSnapshot:
    """Full technical analysis pipeline for a set of klines."""
    df = klines_to_df(klines)

    macd = compute_macd(df)
    bb = compute_bollinger(df)
    rsi = compute_rsi(df)
    signal, strength = compute_signal(macd, bb, rsi)

    return TechnicalSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        price=round(float(df["close"].iloc[-1]), 2),
        macd=macd,
        bollinger=bb,
        rsi=rsi,
        signal=signal,
        signal_strength=strength,
    )
