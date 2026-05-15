from __future__ import annotations

from src.config import Settings
from src.market.data_feed import MarketDataFeed


def get_open_interest(settings: Settings) -> float | None:
    return MarketDataFeed(settings.market).fetch_open_interest(settings.competition.symbol)
