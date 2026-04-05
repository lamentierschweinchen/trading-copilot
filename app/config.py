from pydantic_settings import BaseSettings
from typing import ClassVar


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    finnhub_api_key: str = ""
    mock_synthesizer: bool = True  # set to False to use Claude API

    # Assets: Binance symbol mapping
    ASSETS: ClassVar[dict[str, dict]] = {
        "BTC": {"binance": "BTCUSDT"},
        "ETH": {"binance": "ETHUSDT"},
        "SOL": {"binance": "SOLUSDT"},
        "BNB": {"binance": "BNBUSDT"},
        "XRP": {"binance": "XRPUSDT"},
        "ADA": {"binance": "ADAUSDT"},
        "DOGE": {"binance": "DOGEUSDT"},
        "AVAX": {"binance": "AVAXUSDT"},
        "DOT": {"binance": "DOTUSDT"},
        "LINK": {"binance": "LINKUSDT"},
        "EGLD": {"binance": "EGLDUSDT"},
    }

    # Timeframes for kline data
    SCALP_TIMEFRAME: ClassVar[str] = "15m"
    PRIMARY_TIMEFRAME: ClassVar[str] = "1h"
    CONFIRMATION_TIMEFRAME: ClassVar[str] = "4h"
    KLINE_LIMIT: ClassVar[int] = 200  # enough for indicator computation

    # Macro tickers for Finnhub (ETF proxies)
    MACRO_TICKERS: ClassVar[dict[str, str]] = {
        "SPX": "SPY",
        "QQQ": "QQQ",
        "DXY": "UUP",
        "US10Y": "TLT",
        "DOW": "DIA",
        "GOLD": "GLD",
        "VIX": "VIXY",
    }

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
