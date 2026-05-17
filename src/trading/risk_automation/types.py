from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TriggerCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["price", "rsi_14"]
    op: Literal["gte", "lte", "gt", "lt", "eq"]
    value: float


class TriggerExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic: Literal["AND", "OR"] = "AND"
    conditions: list[Any] = Field(default_factory=list)


class TrailingStopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: Literal["percent", "atr", "step"] = "percent"
    distance_pct: float | None = 0.01
    atr_multiple: float | None = None
    step_pct: float | None = None


class BreakEvenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    trigger: Literal["r_multiple", "percent", "tp1"] = "tp1"
    r_multiple: float | None = 1.0
    percent_gain: float | None = None
    fee_buffer_pct: float = 0.0005


class TimeExitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_hold_hours: float = 24.0
    only_if_profit_pct_below: float | None = None


class PositionRiskAutomation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trailing_stop: TrailingStopConfig | None = None
    break_even: BreakEvenConfig | None = None
    time_exit: TimeExitConfig | None = None


class TriggerOrderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: TriggerExpression
    expires_at: datetime | None = None
    execution_signal: dict[str, Any]
