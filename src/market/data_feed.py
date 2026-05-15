from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import ccxt
import pandas as pd

from src.config import MarketSettings
from src.schemas import MarketCandle


class MarketDataFeed:
    """Public CCXT market data client. It never uses exchange credentials."""

    def __init__(self, settings: MarketSettings) -> None:
        exchange_cls = getattr(ccxt, settings.exchange)
        self.exchange = exchange_cls({"enableRateLimit": True})
        if settings.sandbox and hasattr(self.exchange, "set_sandbox_mode"):
            self.exchange.set_sandbox_mode(True)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        rows = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return frame

    def fetch_ticker_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close")
        if price is None:
            raise RuntimeError(f"No ticker price returned for {symbol}")
        return float(price)

    def fetch_funding_rate(self, symbol: str) -> float | None:
        try:
            data = self.exchange.fetch_funding_rate(symbol)
            value = data.get("fundingRate")
            return float(value) if value is not None else None
        except Exception:
            return None

    def fetch_open_interest(self, symbol: str) -> float | None:
        try:
            data: dict[str, Any] = self.exchange.fetch_open_interest(symbol)
            value = data.get("openInterestAmount") or data.get("openInterestValue") or data.get("openInterest")
            return float(value) if value is not None else None
        except Exception:
            return None


def candles_from_frame(frame: pd.DataFrame) -> list[MarketCandle]:
    return [
        MarketCandle(
            timestamp=row.timestamp.to_pydatetime()
            if hasattr(row.timestamp, "to_pydatetime")
            else datetime.fromtimestamp(row.timestamp / 1000, tz=UTC),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in frame.itertuples(index=False)
    ]
