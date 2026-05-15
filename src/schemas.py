from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Decision(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCHLIST = "WATCHLIST"
    PAPER_TRADE = "PAPER_TRADE"
    POSITION_UPDATE = "POSITION_UPDATE"


class Action(StrEnum):
    NONE = "NONE"
    OPEN = "OPEN"
    ADD = "ADD"
    DCA = "DCA"
    REDUCE = "REDUCE"
    CUT = "CUT"
    CLOSE = "CLOSE"
    HOLD = "HOLD"


class Direction(StrEnum):
    NONE = "NONE"
    LONG = "LONG"
    SHORT = "SHORT"


class ExecutionType(StrEnum):
    NONE = "NONE"
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    CONDITIONAL = "CONDITIONAL"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class MarketCandle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorSnapshot(BaseModel):
    rsi_14: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    atr_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    bb_low: float | None = None
    bb_mid: float | None = None
    bb_high: float | None = None


class MarketState(BaseModel):
    symbol: str
    exchange: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_price: float
    timeframe: str
    candles: list[MarketCandle] = Field(default_factory=list)
    indicators: IndicatorSnapshot = Field(default_factory=IndicatorSnapshot)
    funding_rate: float | None = None
    open_interest: float | None = None
    regime: str = "unknown"
    news_sentiment: float = 0.0

    def compact(self) -> dict[str, Any]:
        latest = self.candles[-5:]
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timestamp": self.timestamp.isoformat(),
            "current_price": self.current_price,
            "timeframe": self.timeframe,
            "funding_rate": self.funding_rate,
            "open_interest": self.open_interest,
            "regime": self.regime,
            "news_sentiment": self.news_sentiment,
            "indicators": self.indicators.model_dump(),
            "recent_candles": [c.model_dump(mode="json") for c in latest],
        }


class PositionView(BaseModel):
    position_id: str
    agent_id: str
    direction: Direction
    status: PositionStatus
    leverage: float
    margin: float
    notional: float
    average_entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    dca_count: int = 0
    opened_at: datetime
    unrealized_pnl: float = 0.0


class AccountSummary(BaseModel):
    agent_id: str
    equity: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    open_margin: float = 0.0
    open_risk: float = 0.0
    daily_pnl: float = 0.0
    max_drawdown: float = 0.0
    open_positions: list[PositionView] = Field(default_factory=list)


class AgentSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decision: Decision
    action: Action = Action.NONE
    symbol: Literal["BTC"] = "BTC"
    position_id: str | None = None
    position_context: str | None = None
    direction: Direction = Direction.NONE
    execution_type: ExecutionType = ExecutionType.NONE
    leverage: float | None = None
    margin_used_usdt: float | None = None
    margin_used_percent: float | None = None
    notional_exposure_usdt: float | None = None
    total_margin_after_action_usdt: float | None = None
    total_notional_after_action_usdt: float | None = None
    average_entry_after_action: float | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    time_horizon: str | None = None
    account_risk_usdt: float | None = None
    account_risk_percent: float | None = None
    total_account_risk_after_action_usdt: float | None = None
    total_account_risk_after_action_percent: float | None = None
    dca_count_after_action: int | None = None
    open_positions_after_action: int | None = None
    daily_loss_status: str | None = None
    liquidation_risk_note: str | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    risk_reward_to_tp1: float | None = None
    risk_reward_to_tp2: float | None = None
    thesis: str | None = None
    invalidation: str | None = None
    counterargument: str | None = None
    data_used: list[str] = Field(default_factory=list)
    notes_for_ledger: str | None = None

    @field_validator("margin_used_percent", "account_risk_percent", "total_account_risk_after_action_percent")
    @classmethod
    def normalize_percent(cls, value: float | None) -> float | None:
        if value is None:
            return value
        return value / 100.0 if value > 1 else value

    @model_validator(mode="after")
    def validate_trade_fields(self) -> AgentSignal:
        if self.decision in {Decision.PAPER_TRADE, Decision.POSITION_UPDATE} and self.action not in {
            Action.REDUCE,
            Action.CUT,
            Action.CLOSE,
            Action.HOLD,
        }:
            required = {
                "leverage": self.leverage,
                "margin_used_usdt": self.margin_used_usdt,
                "entry": self.entry,
                "stop_loss": self.stop_loss,
                "take_profit_1": self.take_profit_1,
                "take_profit_2": self.take_profit_2,
                "account_risk_usdt": self.account_risk_usdt,
                "thesis": self.thesis,
                "invalidation": self.invalidation,
                "counterargument": self.counterargument,
            }
            missing = [name for name, value in required.items() if value in (None, "")]
            if missing:
                raise ValueError(f"missing required trade fields: {', '.join(missing)}")
        return self


class ValidationResult(BaseModel):
    accepted: bool
    reasons: list[str] = Field(default_factory=list)


class LeaderboardRow(BaseModel):
    agent_id: str
    equity: float
    total_return_pct: float
    realized_pnl: float
    unrealized_pnl: float
    win_rate: float
    profit_factor: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    rejected_signals: int
    rule_compliance: float
    api_cost_usd: float
    score: float
