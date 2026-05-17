from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from src.storage.repository import ArenaRepository


def prompt_component_breakdown(prompt: str) -> dict[str, int]:
    markers = [
        ("system_prompt", "RULEBOOK:\n"),
        ("rulebook", "STRATEGY IDENTITY:\n"),
        ("strategy_identity", "PRIVATE LESSONS"),
        ("private_lessons", "SHARED LESSONS"),
        ("shared_lessons", "STRICT JSON SCHEMA HINT"),
        ("schema_hint", "CURRENT CONTEXT:\n"),
        ("market_snapshot", None),
    ]
    breakdown: dict[str, int] = {}
    cursor = 0
    for name, next_marker in markers:
        if next_marker is None:
            breakdown[name] = max(0, len(prompt) - cursor)
            break
        marker_index = prompt.find(next_marker, cursor)
        if marker_index < 0:
            breakdown[name] = 0
            continue
        breakdown[name] = max(0, marker_index - cursor)
        cursor = marker_index
    if not any(breakdown.values()):
        breakdown["unknown_prompt"] = len(prompt)
    return breakdown


def prompt_audit_context(context: dict[str, Any]) -> dict[str, int]:
    private_lessons = context.get("private_lessons") if isinstance(context.get("private_lessons"), list) else []
    shared_lessons = context.get("shared_lessons") if isinstance(context.get("shared_lessons"), list) else []
    similar_trades = context.get("similar_trades") if isinstance(context.get("similar_trades"), list) else []
    reflections = context.get("reflections") if isinstance(context.get("reflections"), list) else []
    private_text = json.dumps(private_lessons, default=str, separators=(",", ":"))
    shared_text = json.dumps(shared_lessons, default=str, separators=(",", ":"))
    reflection_text = json.dumps(reflections, default=str, separators=(",", ":"))
    return {
        "private_lessons_count": len(private_lessons),
        "shared_lessons_count": len(shared_lessons),
        "recent_trades_included": len(similar_trades),
        "memory_size_characters": len(private_text) + len(shared_text),
        "reflection_characters": len(reflection_text),
    }


def summarize_api_costs(repository: ArenaRepository, limit: int = 1000) -> dict[str, Any]:
    requests = list(reversed(repository.api_requests(limit=limit)))
    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "max_single_request_cost_usd": 0.0,
            "retry_count": 0,
            "prompt_characters_first": 0,
            "prompt_characters_last": 0,
            "prompt_growth_ratio": 0.0,
        }
    )
    anomalies = []
    breakdown_totals: dict[str, float] = defaultdict(float)
    for item in requests:
        agent = item.agent_name
        row = by_agent[agent]
        row["request_count"] += 1
        row["prompt_tokens"] += int(item.prompt_tokens or 0)
        row["completion_tokens"] += int(item.completion_tokens or 0)
        row["total_tokens"] += int(item.total_tokens or 0)
        row["total_cost_usd"] += float(item.total_cost_usd or 0.0)
        row["max_single_request_cost_usd"] = max(row["max_single_request_cost_usd"], float(item.total_cost_usd or 0.0))
        row["retry_count"] += int(item.retry_count or 0)
        if not row["prompt_characters_first"]:
            row["prompt_characters_first"] = int(item.prompt_characters or 0)
        row["prompt_characters_last"] = int(item.prompt_characters or 0)
        try:
            flags = json.loads(item.anomaly_flags_json or "[]")
        except Exception:
            flags = []
        if flags:
            anomalies.append(
                {
                    "timestamp": item.timestamp.isoformat() if item.timestamp else "",
                    "cycle_number": item.cycle_number,
                    "agent_name": item.agent_name,
                    "request_type": item.request_type,
                    "flags": flags,
                    "total_cost_usd": item.total_cost_usd,
                    "total_tokens": item.total_tokens,
                    "prompt_characters": item.prompt_characters,
                    "retry_count": item.retry_count,
                }
            )
        try:
            breakdown = json.loads(item.cost_breakdown_json or "{}")
        except Exception:
            breakdown = {}
        if isinstance(breakdown, dict):
            for key, value in breakdown.items():
                if key.endswith("_cost_usd"):
                    breakdown_totals[key] += float(value or 0.0)
    for row in by_agent.values():
        count = max(1, int(row["request_count"]))
        row["average_prompt_tokens"] = row["prompt_tokens"] / count
        row["average_completion_tokens"] = row["completion_tokens"] / count
        row["average_total_cost_usd"] = row["total_cost_usd"] / count
        first = float(row["prompt_characters_first"] or 0)
        row["prompt_growth_ratio"] = (float(row["prompt_characters_last"] or 0) / first) if first else 0.0
    return {
        "by_agent": dict(by_agent),
        "anomalies": anomalies[-50:],
        "diagnosis": diagnose_cost_spike(requests),
        "cost_breakdown_totals": dict(breakdown_totals),
    }


def diagnose_cost_spike(requests: list[Any]) -> list[str]:
    findings: list[str] = []
    challenger = [
        item
        for item in requests
        if "grok" in str(item.agent_name).lower() or "qwen" in str(item.agent_name).lower()
    ]
    deepseek = [item for item in requests if "deepseek" in str(item.agent_name).lower()]
    if not challenger:
        return ["No challenger API audit rows are recorded yet."]
    challenger_cost = sum(float(item.total_cost_usd or 0.0) for item in challenger)
    deepseek_cost = sum(float(item.total_cost_usd or 0.0) for item in deepseek)
    if deepseek_cost and challenger_cost > deepseek_cost * 3:
        findings.append(f"Challenger estimated audit cost is {challenger_cost / deepseek_cost:.1f}x DeepSeek.")
    if any("cost_gt_3x_previous" in _flags(item) for item in challenger):
        findings.append("At least one challenger request cost exceeded 3x its previous challenger request.")
    if any("tokens_gt_3x_previous" in _flags(item) for item in challenger):
        findings.append("At least one challenger request token count exceeded 3x its previous challenger request.")
    if any("prompt_size_gt_2x_previous" in _flags(item) for item in challenger):
        findings.append("Challenger prompt size more than doubled between adjacent requests.")
    retry_total = sum(int(item.retry_count or 0) for item in challenger)
    if retry_total:
        findings.append(f"Challenger had {retry_total} retry attempt(s), which can multiply provider-side spend.")
    server_tool_cost = sum(float(item.server_tool_cost_usd or 0.0) for item in challenger)
    if server_tool_cost:
        findings.append(f"Challenger has ${server_tool_cost:.4f} recorded server-side tool cost.")
    if len(challenger) >= 2:
        first_prompt = float(challenger[0].prompt_characters or 0)
        last_prompt = float(challenger[-1].prompt_characters or 0)
        if first_prompt and last_prompt > first_prompt * 2:
            findings.append(f"Challenger prompt characters grew from {int(first_prompt)} to {int(last_prompt)}.")
    if not findings:
        findings.append("No local audit anomaly explains the challenger spike yet; compare provider billing for hidden reasoning or server-side charges.")
    return findings


def _flags(item: Any) -> list[str]:
    try:
        value = json.loads(item.anomaly_flags_json or "[]")
    except Exception:
        return []
    return value if isinstance(value, list) else []
