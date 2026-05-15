from __future__ import annotations

import pandas as pd

from src.competition.evaluation import calculate_leaderboard
from src.market.indicators import compute_indicators
from src.market.regime import detect_regime
from src.schemas import MarketCandle, MarketState
from src.storage.models import ResponseRecord
from src.tools.backtest_pattern import backtest_pattern
from src.tools.calculate_position_size import calculate_position_size
from src.tools.toolbox import execute_local_tool
from src.utils.costs import estimate_cost_usd


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=80, freq="h", tz="UTC"),
            "open": range(100, 180),
            "high": range(101, 181),
            "low": range(99, 179),
            "close": range(100, 180),
            "volume": [10] * 80,
        }
    )


def sample_market_state() -> MarketState:
    frame = sample_frame()
    indicators = compute_indicators(frame)
    candles = [
        MarketCandle(
            timestamp=row.timestamp.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in frame.itertuples(index=False)
    ]
    return MarketState(
        symbol="BTCUSDT",
        exchange="binanceusdm",
        current_price=179,
        timeframe="1h",
        candles=candles,
        indicators=indicators,
        funding_rate=0.0001,
        open_interest=123,
        regime=detect_regime(frame, indicators),
    )


def test_indicators_regime_backtest_and_position_size() -> None:
    frame = sample_frame()
    indicators = compute_indicators(frame)
    assert indicators.ema_20 is not None
    assert detect_regime(frame, indicators).startswith("uptrend")
    diagnostic = backtest_pattern(frame, lookahead=3)
    assert diagnostic["sample_size"] > 0
    size = calculate_position_size(10000, 100000, 99000, 5, 0.02, 0.1, "LONG")
    assert size["margin_usdt"] <= 1000
    assert size["risk_pct"] <= 0.02


def test_toolbox_executes_allowed_tools(repository, test_settings) -> None:
    market_state = sample_market_state()
    result = execute_local_tool("get_market_state", {}, test_settings, repository, market_state, "crypto-deepseek")
    assert result["current_price"] == 179
    result = execute_local_tool(
        "calculate_position_size",
        {"equity": 10000, "entry": 100000, "stop_loss": 99000, "leverage": 5, "direction": "LONG"},
        test_settings,
        repository,
        market_state,
        "crypto-deepseek",
    )
    assert result["notional_usdt"] > 0


def test_leaderboard_uses_response_cost(repository) -> None:
    with repository.session_factory() as session, session.begin():
        session.add(
            ResponseRecord(
                agent_id="crypto-deepseek",
                raw_response="{}",
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=0.01,
            )
        )
    rows = calculate_leaderboard(repository, ["crypto-deepseek"], 10000, 100000)
    assert rows[0].api_cost_usd == 0.01


def test_cost_estimator() -> None:
    input_tokens, output_tokens, cost = estimate_cost_usd("deepseek/deepseek-v4-flash", "a" * 400, "b" * 200)
    assert input_tokens == 100
    assert output_tokens == 50
    assert cost > 0
