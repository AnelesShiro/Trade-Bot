from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from src.schemas import AgentSignal, ValidationResult


REJECTION_CODES = {
    "PARSE_ERROR",
    "INVALID_JSON",
    "MISSING_FIELD",
    "INVALID_DIRECTION",
    "INVALID_ACTION",
    "LOW_CONFIDENCE",
    "RISK_LIMIT_EXCEEDED",
    "LEVERAGE_LIMIT_EXCEEDED",
    "POSITION_LIMIT_EXCEEDED",
    "DUPLICATE_SIGNAL",
    "RULEBOOK_VIOLATION",
    "INTERNAL_ERROR",
}


def signal_audit_metadata(
    *,
    agent_name: str,
    model_name: str,
    cycle_number: int,
    competition_time_pct: float,
    market_regime: str,
    btc_price: float,
    timeframe: str,
    prompt_version: str,
    rulebook_version: str,
    config_version: str,
    signal: AgentSignal | None,
    validation: ValidationResult,
    raw_response: str,
    input_tokens: int,
    output_tokens: int,
    api_cost_usd: float,
    latency_ms: int | None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    timestamp_utc = now.isoformat().replace("+00:00", "Z")
    timestamp_local = now.astimezone(timezone(timedelta(hours=7))).isoformat()
    payload = signal.model_dump(mode="json") if signal else {}
    reasons = validation.reasons or []
    status = "ACCEPTED" if validation.accepted else "REJECTED"
    code = None if validation.accepted else rejection_code(reasons, signal)
    return {
        "timestamp_utc": timestamp_utc,
        "timestamp_local": timestamp_local,
        "cycle_number": cycle_number,
        "competition_time_pct": competition_time_pct,
        "agent_name": agent_name,
        "model_name": model_name,
        "signal_status": status,
        "rejection_reason_code": code,
        "rejection_reason_message": "; ".join(reasons)[:2000] if reasons else None,
        "direction": _enum_value(getattr(signal, "direction", None)),
        "confidence": float(signal.confidence) if signal and signal.confidence is not None else None,
        "thesis": signal.thesis if signal else None,
        "entry_price": float(signal.entry) if signal and signal.entry is not None else None,
        "stop_loss": float(signal.stop_loss) if signal and signal.stop_loss is not None else None,
        "take_profit_1": float(signal.take_profit_1) if signal and signal.take_profit_1 is not None else None,
        "take_profit_2": float(signal.take_profit_2) if signal and signal.take_profit_2 is not None else None,
        "leverage": float(signal.leverage) if signal and signal.leverage is not None else None,
        "risk_pct": float(signal.account_risk_percent) if signal and signal.account_risk_percent is not None else None,
        "position_size_usdt": float(signal.margin_used_usdt) if signal and signal.margin_used_usdt is not None else None,
        "notional_usdt": float(signal.notional_exposure_usdt) if signal and signal.notional_exposure_usdt is not None else None,
        "expected_rr": _expected_rr(signal),
        "market_regime": market_regime,
        "btc_price": btc_price,
        "timeframe": timeframe,
        "prompt_version": prompt_version,
        "rulebook_version": rulebook_version,
        "config_version": config_version,
        "raw_model_output": raw_response,
        "parsed_json": json.dumps(payload, default=str),
        "normalized_signal_json": json.dumps(payload, default=str),
        "validation_details_json": json.dumps(
            {
                "accepted": validation.accepted,
                "reasons": reasons,
                "rejection_code": code,
            },
            default=str,
        ),
        "execution_result_json": json.dumps({"executed": False, "position_id": None, "reason": "not evaluated yet"}),
        "token_usage": json.dumps({"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}),
        "api_cost_usd": api_cost_usd,
        "latency_ms": latency_ms,
    }


def rejection_code(reasons: list[str], signal: AgentSignal | None) -> str:
    text = " ".join(reasons).lower()
    if "agent_runtime_error" in text or "gatewayclientrequesterror" in text or "billing error" in text or "openclaw exited" in text:
        return "INTERNAL_ERROR"
    if signal is None:
        if "invalid json" in text or "jsondecode" in text or "json decode" in text:
            return "INVALID_JSON"
        return "PARSE_ERROR"
    if "missing required trade fields" in text:
        return "MISSING_FIELD"
    if "direction" in text:
        return "INVALID_DIRECTION"
    if "action" in text:
        return "INVALID_ACTION"
    if "leverage" in text:
        return "LEVERAGE_LIMIT_EXCEEDED"
    if "max simultaneous open positions" in text:
        return "POSITION_LIMIT_EXCEEDED"
    if "risk" in text or "loss limit" in text or "margin exceeds" in text:
        return "RISK_LIMIT_EXCEEDED"
    if "duplicate" in text:
        return "DUPLICATE_SIGNAL"
    if "confidence" in text:
        return "LOW_CONFIDENCE"
    return "RULEBOOK_VIOLATION"


def _expected_rr(signal: AgentSignal | None) -> float | None:
    if not signal:
        return None
    values = [value for value in [signal.risk_reward_to_tp1, signal.risk_reward_to_tp2] if value is not None]
    return float(max(values)) if values else None


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", str(value))
