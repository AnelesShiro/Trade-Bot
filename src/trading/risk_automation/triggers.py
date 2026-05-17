from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.trading.risk_automation.types import TriggerCondition, TriggerExpression


def evaluate_trigger(expression: dict[str, Any] | TriggerExpression, *, price: float, rsi_14: float | None) -> bool:
    if isinstance(expression, TriggerExpression):
        payload = expression.model_dump()
    else:
        payload = expression
    logic = str(payload.get("logic", "AND")).upper()
    conditions = payload.get("conditions") or []
    if not conditions:
        return False
    results = [_evaluate_node(node, price=price, rsi_14=rsi_14) for node in conditions]
    if logic == "OR":
        return any(results)
    return all(results)


def _evaluate_node(node: Any, *, price: float, rsi_14: float | None) -> bool:
    if isinstance(node, dict) and "conditions" in node:
        return evaluate_trigger(node, price=price, rsi_14=rsi_14)
    if isinstance(node, TriggerExpression):
        return evaluate_trigger(node, price=price, rsi_14=rsi_14)
    condition = TriggerCondition.model_validate(node)
    value = price if condition.field == "price" else rsi_14
    if value is None:
        return False
    if condition.op == "gte":
        return value >= condition.value
    if condition.op == "lte":
        return value <= condition.value
    if condition.op == "gt":
        return value > condition.value
    if condition.op == "lt":
        return value < condition.value
    return abs(value - condition.value) < 1e-9


def trigger_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(UTC)
    expires = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    return current >= expires.astimezone(UTC)
