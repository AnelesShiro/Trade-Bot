from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.schemas import Direction
from src.storage.models import PositionRecord
from src.trading.risk_automation.types import BreakEvenConfig, PositionRiskAutomation, TimeExitConfig, TrailingStopConfig
from src.trading.pnl import calculate_pnl


def parse_position_risk(payload: str | dict[str, Any] | None) -> PositionRiskAutomation | None:
    if not payload:
        return None
    data = payload
    for _ in range(4):
        if not isinstance(data, str):
            break
        data = json.loads(data)
    if not data:
        return None
    return PositionRiskAutomation.model_validate(data)


def apply_trailing_stop(
    position: PositionRecord,
    current_price: float,
    config: TrailingStopConfig,
    state: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    if not config.enabled:
        return position.stop_loss, state
    new_sl = position.stop_loss
    if position.direction == Direction.LONG.value:
        candidate = new_sl
        if config.mode == "percent" and config.distance_pct:
            candidate = current_price * (1 - config.distance_pct)
        elif config.mode == "step" and config.step_pct:
            anchor = float(state.get("last_trail_anchor") or position.average_entry)
            if current_price >= anchor * (1 + config.step_pct):
                candidate = current_price * (1 - (config.distance_pct or config.step_pct))
                state["last_trail_anchor"] = current_price
        elif config.mode == "atr" and config.atr_multiple:
            atr = float(state.get("atr_14") or 0)
            if atr > 0:
                candidate = current_price - atr * config.atr_multiple
        new_sl = max(new_sl, candidate)
    else:
        candidate = new_sl
        if config.mode == "percent" and config.distance_pct:
            candidate = current_price * (1 + config.distance_pct)
        elif config.mode == "step" and config.step_pct:
            anchor = float(state.get("last_trail_anchor") or position.average_entry)
            if current_price <= anchor * (1 - config.step_pct):
                candidate = current_price * (1 + (config.distance_pct or config.step_pct))
                state["last_trail_anchor"] = current_price
        elif config.mode == "atr" and config.atr_multiple:
            atr = float(state.get("atr_14") or 0)
            if atr > 0:
                candidate = current_price + atr * config.atr_multiple
        new_sl = min(new_sl, candidate)
    state["trail_sl"] = new_sl
    state["trailing_active"] = True
    return new_sl, state


def apply_break_even(
    position: PositionRecord,
    current_price: float,
    config: BreakEvenConfig,
    state: dict[str, Any],
) -> tuple[float, dict[str, Any], bool]:
    if not config.enabled or state.get("break_even_applied"):
        return position.stop_loss, state, False
    entry = position.average_entry
    risk = abs(entry - position.stop_loss)
    if risk <= 0:
        return position.stop_loss, state, False
    activated = False
    buffer = entry * config.fee_buffer_pct
    if config.trigger == "tp1":
        hit = (
            position.direction == Direction.LONG.value
            and current_price >= position.take_profit_1
            or position.direction == Direction.SHORT.value
            and current_price <= position.take_profit_1
        )
    elif config.trigger == "percent" and config.percent_gain:
        move = (current_price - entry) / entry
        if position.direction == Direction.SHORT.value:
            move = -move
        hit = move >= config.percent_gain
    else:
        pnl = calculate_pnl(position.direction, position.notional, entry, current_price)
        account_risk = abs(calculate_pnl(position.direction, position.notional, entry, position.stop_loss))
        hit = account_risk > 0 and pnl >= account_risk * (config.r_multiple or 1.0)
    if not hit:
        return position.stop_loss, state, False
    if position.direction == Direction.LONG.value:
        new_sl = entry + buffer
        new_sl = max(new_sl, position.stop_loss)
    else:
        new_sl = entry - buffer
        new_sl = min(new_sl, position.stop_loss)
    state["break_even_applied"] = True
    return new_sl, state, True


def time_exit_due(
    position: PositionRecord,
    current_price: float,
    config: TimeExitConfig,
    state: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    if not config.enabled:
        return False
    opened = position.opened_at
    if opened and opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    deadline = state.get("max_hold_until")
    if deadline:
        expires = datetime.fromisoformat(deadline)
    else:
        expires = (opened or datetime.now(UTC)) + timedelta(hours=config.max_hold_hours)
    current = now or datetime.now(UTC)
    if current < expires.astimezone(UTC):
        return False
    if config.only_if_profit_pct_below is not None:
        move = (current_price - position.average_entry) / position.average_entry
        if position.direction == Direction.SHORT.value:
            move = -move
        if move >= config.only_if_profit_pct_below:
            return False
    return True


def default_max_hold_until(position: PositionRecord, config: TimeExitConfig) -> str:
    opened = position.opened_at or datetime.now(UTC)
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=UTC)
    return (opened + timedelta(hours=config.max_hold_hours)).isoformat()
