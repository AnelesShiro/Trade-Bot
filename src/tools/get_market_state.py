from __future__ import annotations

from src.config import Settings
from src.market.data_feed import MarketDataFeed, candles_from_frame
from src.market.indicators import compute_indicators
from src.market.news import get_news_sentiment
from src.market.regime import detect_regime
from src.schemas import MarketState


def get_market_state(settings: Settings) -> MarketState:
    feed = MarketDataFeed(settings.market)
    frame = feed.fetch_ohlcv(
        settings.competition.symbol,
        timeframe=settings.competition.timeframe,
        limit=settings.competition.ohlcv_limit,
    )
    indicators = compute_indicators(frame)
    return MarketState(
        symbol=settings.competition.display_symbol,
        exchange=settings.market.exchange,
        current_price=float(frame["close"].iloc[-1]),
        timeframe=settings.competition.timeframe,
        candles=candles_from_frame(frame),
        indicators=indicators,
        funding_rate=feed.fetch_funding_rate(settings.competition.symbol)
        if settings.market.fetch_funding
        else None,
        open_interest=feed.fetch_open_interest(settings.competition.symbol)
        if settings.market.fetch_open_interest
        else None,
        regime=detect_regime(frame, indicators),
        news_sentiment=get_news_sentiment(),
    )
