from pydantic_settings import BaseSettings
from typing import ClassVar


class Settings(BaseSettings):
    anthropic_api_key: str = ""
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
    }

    # Timeframes for kline data
    PRIMARY_TIMEFRAME: ClassVar[str] = "1h"
    CONFIRMATION_TIMEFRAME: ClassVar[str] = "4h"
    KLINE_LIMIT: ClassVar[int] = 200  # enough for indicator computation

    # Macro tickers for yfinance
    MACRO_TICKERS: ClassVar[dict[str, str]] = {
        "SPX": "^GSPC",
        "QQQ": "QQQ",
        "DXY": "DX-Y.NYB",
        "US10Y": "^TNX",
    }

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
