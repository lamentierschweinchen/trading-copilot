import logging

import yfinance as yf
from app.config import settings

logger = logging.getLogger(__name__)


def fetch_macro_data() -> dict:
    """
    Fetch macro indicators via yfinance.
    Returns dict of ticker -> {price, change_pct}.
    Runs synchronously (yfinance doesn't support async).
    """
    results = {}

    for label, ticker in settings.MACRO_TICKERS.items():
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="5d")

            if hist.empty or len(hist) < 2:
                results[label] = {"price": None, "change_pct": None}
                continue

            current = float(hist["Close"].iloc[-1])
            previous = float(hist["Close"].iloc[-2])
            change_pct = ((current - previous) / previous) * 100

            results[label] = {
                "price": round(current, 2),
                "change_pct": round(change_pct, 3),
            }
        except Exception:
            logger.warning("Failed to fetch macro data for %s (%s)", label, ticker)
            results[label] = {"price": None, "change_pct": None}

    return results
