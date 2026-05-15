from __future__ import annotations

import json
import re

from pydantic import ValidationError

from src.schemas import AgentSignal, ValidationResult
from src.validation.rule_engine import RuleEngine


def parse_agent_signal(raw: str) -> tuple[AgentSignal | None, ValidationResult]:
    try:
        payload = json.loads(repair_json(_extract_json(raw)))
        return AgentSignal.model_validate(payload), ValidationResult(accepted=True)
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        return None, ValidationResult(accepted=False, reasons=[f"parse/schema error: {error}"])


def validate_signal(
    raw: str,
    rule_engine: RuleEngine,
    current_equity: float,
    open_positions_count: int,
    current_total_risk: float,
    daily_pnl: float,
    dca_count_for_position: int = 0,
    recent_stop_loss_same_direction: bool = False,
) -> tuple[AgentSignal | None, ValidationResult]:
    signal, parsed = parse_agent_signal(raw)
    if not signal:
        return None, parsed
    result = rule_engine.validate(
        signal,
        current_equity=current_equity,
        open_positions_count=open_positions_count,
        current_total_risk=current_total_risk,
        daily_pnl=daily_pnl,
        dca_count_for_position=dca_count_for_position,
        recent_stop_loss_same_direction=recent_stop_loss_same_direction,
    )
    return signal, result


def _extract_json(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    if cleaned.startswith("{"):
        return cleaned
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object found")
    return match.group(0)


def repair_json(raw_json: str) -> str:
    """Repair common model formatting mistakes without changing semantic fields."""
    cleaned = raw_json.strip()
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'")
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"\bNone\b", "null", cleaned)
    cleaned = re.sub(r"\bTrue\b", "true", cleaned)
    cleaned = re.sub(r"\bFalse\b", "false", cleaned)
    return cleaned
