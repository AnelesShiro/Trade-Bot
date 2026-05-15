from __future__ import annotations

from typing import Any

import pandas as pd

from src.config import Settings
from src.market.news import get_news_sentiment
from src.schemas import MarketState
from src.storage.repository import ArenaRepository
from src.tools.backtest_pattern import backtest_pattern
from src.tools.calculate_position_size import calculate_position_size
from src.tools.retrieve_similar_trades import retrieve_similar_trades


ALLOWED_TOOLS = {
    "get_market_state",
    "get_indicators",
    "get_funding",
    "get_open_interest",
    "retrieve_similar_trades",
    "backtest_pattern",
    "calculate_position_size",
    "get_market_regime",
    "get_news_sentiment",
}


def execute_local_tool(
    tool_name: str,
    arguments: dict[str, Any],
    settings: Settings,
    repository: ArenaRepository,
    market_state: MarketState,
    agent_id: str,
) -> Any:
    """Execute a safe local read/compute tool against the shared market state."""
    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(f"unsupported tool: {tool_name}")

    if tool_name == "get_market_state":
        return market_state.compact()
    if tool_name == "get_indicators":
        return market_state.indicators.model_dump()
    if tool_name == "get_funding":
        return {"funding_rate": market_state.funding_rate}
    if tool_name == "get_open_interest":
        return {"open_interest": market_state.open_interest}
    if tool_name == "get_market_regime":
        return {"regime": market_state.regime}
    if tool_name == "get_news_sentiment":
        return {"news_sentiment": get_news_sentiment(), "source": "configured local news sentiment provider"}
    if tool_name == "retrieve_similar_trades":
        limit = int(arguments.get("limit", 5))
        return retrieve_similar_trades(repository, agent_id, limit=limit)
    if tool_name == "backtest_pattern":
        lookahead = int(arguments.get("lookahead", 6))
        return backtest_pattern(_candles_to_frame(market_state), lookahead=lookahead)
    if tool_name == "calculate_position_size":
        return calculate_position_size(
            equity=float(arguments["equity"]),
            entry=float(arguments["entry"]),
            stop_loss=float(arguments["stop_loss"]),
            leverage=float(arguments["leverage"]),
            max_risk_pct=float(arguments.get("max_risk_pct", settings.risk.max_total_account_risk_pct)),
            max_margin_pct=float(arguments.get("max_margin_pct", settings.risk.max_margin_per_action_pct)),
            direction=str(arguments["direction"]),
        )
    raise ValueError(f"unhandled tool: {tool_name}")


def _candles_to_frame(market_state: MarketState) -> pd.DataFrame:
    return pd.DataFrame([c.model_dump() for c in market_state.candles])
