from __future__ import annotations

import json
from typing import Any


EMPTY = "-"


def pending_order_view(
    *,
    order_id: str,
    agent_id: str,
    status: str,
    created_at: Any = None,
    expires_at: Any = None,
    triggered_at: Any = None,
    position_id: str | None = None,
    trigger_json: str | dict[str, Any] | None = None,
    execution_signal_json: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    trigger = _safe_json(trigger_json)
    signal = _safe_json(execution_signal_json)
    action = _display(signal.get("action"))
    direction = _display(signal.get("direction"))
    thesis = _display(signal.get("thesis"))
    return {
        "id": order_id,
        "agent_id": agent_id,
        "status": status,
        "intent": _intent(action, direction),
        "action": action,
        "direction": direction,
        "entry_price": _number(signal.get("entry")),
        "stop_loss": _number(signal.get("stop_loss")),
        "take_profit_1": _number(signal.get("take_profit_1")),
        "leverage": _number(signal.get("leverage")),
        "trigger_summary": trigger_summary(trigger),
        "thesis": _truncate(thesis, 120),
        "created_at": _isoish(created_at),
        "expires_at": _isoish(expires_at),
        "triggered_at": _isoish(triggered_at),
        "position_id": position_id or EMPTY,
        "trigger_conditions": trigger,
        "normalized_signal": signal,
        "validation_details": {
            "source": "pending_orders.execution_signal_json",
            "normalized": bool(signal),
            "missing_fields": _missing_fields(signal),
        },
    }


def trigger_summary(trigger: str | dict[str, Any] | None) -> str:
    payload = _safe_json(trigger)
    if not payload:
        return EMPTY
    logic = str(payload.get("logic") or "AND").upper()
    conditions = payload.get("conditions") if isinstance(payload.get("conditions"), list) else []
    parts = [_condition_summary(item) for item in conditions if isinstance(item, dict)]
    parts = [part for part in parts if part != EMPTY]
    return f" {logic} ".join(parts) if parts else EMPTY


def _condition_summary(item: dict[str, Any]) -> str:
    field = str(item.get("field") or "").strip()
    op = str(item.get("op") or "").strip()
    value = item.get("value")
    if not field or not op:
        return EMPTY
    return f"{_field_label(field)} {_op_label(op)} {_format_value(value)}"


def _safe_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _intent(action: str, direction: str) -> str:
    if action == EMPTY and direction == EMPTY:
        return EMPTY
    if direction == EMPTY or direction == "NONE":
        return action
    return f"{action} {direction}"


def _field_label(field: str) -> str:
    return {"price": "Price", "rsi_14": "RSI14"}.get(field, field)


def _op_label(op: str) -> str:
    return {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "="}.get(op, op)


def _format_value(value: Any) -> str:
    try:
        number = float(value)
        return f"{number:g}"
    except (TypeError, ValueError):
        return str(value)


def _number(value: Any) -> float | str:
    try:
        return float(value)
    except (TypeError, ValueError):
        return EMPTY


def _display(value: Any) -> str:
    if value in (None, ""):
        return EMPTY
    return str(value).upper() if str(value).upper() in {"OPEN", "CLOSE", "ADD", "REDUCE", "CUT", "DCA", "LONG", "SHORT", "NONE", "HOLD"} else str(value)


def _truncate(value: str, limit: int) -> str:
    if value == EMPTY:
        return value
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _isoish(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _missing_fields(signal: dict[str, Any]) -> list[str]:
    if not signal:
        return ["execution_signal_json"]
    required = ["action", "direction", "entry", "stop_loss", "take_profit_1", "leverage", "thesis"]
    return [field for field in required if signal.get(field) in (None, "")]
