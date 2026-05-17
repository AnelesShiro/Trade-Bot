from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from src.storage.repository import ArenaRepository


AGENT_ALIASES = {
    "crypto-deepseek": "deepseek",
    "crypto-grok": "grok",
    "crypto-qwen": "grok",
}


@dataclass
class AgentWork:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0
    tool_requests: int = 0
    reflections_generated: int = 0
    lessons_generated: int = 0
    api_cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class WorkloadTracker:
    started_wall: float = field(default_factory=time.perf_counter)
    started_cpu: float = field(default_factory=time.process_time)
    local_tool_calls: int = 0
    local_functions_executed: int = 0
    local_database_queries: int = 0
    local_memory_retrievals: int = 0
    local_reflections_processed: int = 0
    local_lessons_promoted: int = 0
    components: list[dict[str, Any]] = field(default_factory=list)
    agents: dict[str, AgentWork] = field(default_factory=lambda: {"deepseek": AgentWork(), "grok": AgentWork()})

    def component(self, owner: str, category: str, metric_name: str, metric_value: float = 1.0, **details: Any) -> None:
        self.components.append(
            {
                "owner": owner,
                "category": category,
                "metric_name": metric_name,
                "metric_value": float(metric_value),
                "details": details,
            }
        )

    def local_function(self, category: str, name: str, count: int = 1, **details: Any) -> None:
        self.local_functions_executed += count
        self.component("local", category, name, count, **details)

    def database_query(self, category: str, count: int = 1, **details: Any) -> None:
        self.local_database_queries += count
        self.component("local", category, "database_query", count, **details)

    def memory_retrieval(self, count: int = 1, **details: Any) -> None:
        self.local_memory_retrievals += count
        self.component("local", "memory", "memory_retrieval", count, **details)

    def local_tool(self, tool_name: str, **details: Any) -> None:
        self.local_tool_calls += 1
        self.component("local", "tool_execution", tool_name, 1, **details)

    def agent_latency(self, agent_id: str, seconds: float) -> None:
        self.agents[_agent_key(agent_id)].latency_seconds += seconds
        self.component(_agent_key(agent_id), "agent_inference", "latency_seconds", seconds)

    def agent_tokens(self, agent_id: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        agent = self.agents[_agent_key(agent_id)]
        agent.input_tokens += int(input_tokens)
        agent.output_tokens += int(output_tokens)
        agent.api_cost_usd += float(cost_usd)
        self.component(_agent_key(agent_id), "agent_inference", "input_tokens", input_tokens)
        self.component(_agent_key(agent_id), "agent_inference", "output_tokens", output_tokens)
        self.component(_agent_key(agent_id), "agent_inference", "api_cost_usd", cost_usd)

    def agent_tool_requests(self, agent_id: str, count: int) -> None:
        self.agents[_agent_key(agent_id)].tool_requests += count
        self.component(_agent_key(agent_id), "tool_selection", "tool_requests", count)

    def reflection(self, agent_id: str, lessons_generated: int = 1) -> None:
        agent = self.agents[_agent_key(agent_id)]
        agent.reflections_generated += 1
        agent.lessons_generated += lessons_generated
        self.local_reflections_processed += 1
        self.component(_agent_key(agent_id), "reflection", "reflections_generated", 1)
        self.component(_agent_key(agent_id), "reflection", "lessons_generated", lessons_generated)
        self.component("local", "reflection_processing", "reflections_processed", 1, agent_id=agent_id)

    def lesson_promotion(self, promoted: int) -> None:
        self.local_lessons_promoted += promoted
        self.component("local", "lesson_promotion", "lessons_promoted", promoted)

    def finalize(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        total_wall = max(0.000001, time.perf_counter() - self.started_wall)
        total_cpu = max(0.0, time.process_time() - self.started_cpu)
        deepseek = self.agents["deepseek"]
        grok = self.agents["grok"]
        agent_latency = deepseek.latency_seconds + grok.latency_seconds
        local_wall = max(0.0, total_wall - agent_latency)
        scores = workload_scores(
            local_wall_time_seconds=local_wall,
            deepseek=deepseek,
            grok=grok,
            local_tool_calls=self.local_tool_calls,
            local_functions_executed=self.local_functions_executed,
            local_reflections_processed=self.local_reflections_processed,
            local_lessons_promoted=self.local_lessons_promoted,
        )
        cycle = {
            "local_workload_pct": scores["local"] * 100,
            "deepseek_workload_pct": scores["deepseek"] * 100,
            "grok_workload_pct": scores["grok"] * 100,
            "local_wall_time_seconds": local_wall,
            "local_cpu_time_seconds": total_cpu,
            "deepseek_latency_seconds": deepseek.latency_seconds,
            "grok_latency_seconds": grok.latency_seconds,
            "deepseek_tokens": deepseek.total_tokens,
            "grok_tokens": grok.total_tokens,
            "deepseek_cost_usd": deepseek.api_cost_usd,
            "grok_cost_usd": grok.api_cost_usd,
            "payload": {
                "total_wall_time_seconds": total_wall,
                "local_tool_calls": self.local_tool_calls,
                "local_functions_executed": self.local_functions_executed,
                "local_database_queries": self.local_database_queries,
                "local_memory_retrievals": self.local_memory_retrievals,
                "deepseek_input_tokens": deepseek.input_tokens,
                "deepseek_output_tokens": deepseek.output_tokens,
                "deepseek_tool_requests": deepseek.tool_requests,
                "deepseek_reflections_generated": deepseek.reflections_generated,
                "deepseek_lessons_generated": deepseek.lessons_generated,
                "deepseek_api_cost_usd": deepseek.api_cost_usd,
                "grok_input_tokens": grok.input_tokens,
                "grok_output_tokens": grok.output_tokens,
                "grok_tool_requests": grok.tool_requests,
                "grok_reflections_generated": grok.reflections_generated,
                "grok_lessons_generated": grok.lessons_generated,
                "grok_api_cost_usd": grok.api_cost_usd,
            },
        }
        return cycle, self.components


def workload_scores(
    *,
    local_wall_time_seconds: float,
    deepseek: AgentWork,
    grok: AgentWork,
    local_tool_calls: int,
    local_functions_executed: int,
    local_reflections_processed: int,
    local_lessons_promoted: int,
) -> dict[str, float]:
    total_time = max(0.000001, local_wall_time_seconds + deepseek.latency_seconds + grok.latency_seconds)
    wall = {
        "local": local_wall_time_seconds / total_time,
        "deepseek": deepseek.latency_seconds / total_time,
        "grok": grok.latency_seconds / total_time,
    }
    total_tokens = max(1, deepseek.total_tokens + grok.total_tokens)
    tokens = {
        "local": 0.0,
        "deepseek": deepseek.total_tokens / total_tokens,
        "grok": grok.total_tokens / total_tokens,
    }
    decision = _decision_share(
        local_tool_calls=local_tool_calls,
        local_functions_executed=local_functions_executed,
        deepseek_tool_requests=deepseek.tool_requests,
        grok_tool_requests=grok.tool_requests,
    )
    total_reflections = max(1, local_reflections_processed + deepseek.reflections_generated + grok.reflections_generated)
    reflection = {
        "local": local_reflections_processed / total_reflections,
        "deepseek": deepseek.reflections_generated / total_reflections,
        "grok": grok.reflections_generated / total_reflections,
    }
    total_lessons = max(1, local_lessons_promoted + deepseek.lessons_generated + grok.lessons_generated)
    lesson = {
        "local": local_lessons_promoted / total_lessons,
        "deepseek": deepseek.lessons_generated / total_lessons,
        "grok": grok.lessons_generated / total_lessons,
    }
    raw = {
        owner: (
            0.40 * wall[owner]
            + 0.25 * tokens[owner]
            + 0.20 * decision[owner]
            + 0.10 * reflection[owner]
            + 0.05 * lesson[owner]
        )
        for owner in ["local", "deepseek", "grok"]
    }
    total = sum(raw.values()) or 1.0
    return {owner: raw[owner] / total for owner in raw}


def summarize_workload(repository: ArenaRepository, limit: int = 50) -> dict[str, Any]:
    cycles = repository.workload_cycles(limit=limit)
    components = repository.workload_components(limit=1000)
    if not cycles:
        return {"latest": None, "averages": {}, "component_count": 0}
    latest = cycles[0]
    averages = {
        "local_workload_pct": sum(c.local_workload_pct for c in cycles) / len(cycles),
        "deepseek_workload_pct": sum(c.deepseek_workload_pct for c in cycles) / len(cycles),
        "grok_workload_pct": sum(c.grok_workload_pct for c in cycles) / len(cycles),
        "total_api_cost_usd": sum(c.deepseek_cost_usd + c.grok_cost_usd for c in cycles),
    }
    return {
        "latest": {
            "timestamp": latest.timestamp.isoformat(),
            "local_workload_pct": latest.local_workload_pct,
            "deepseek_workload_pct": latest.deepseek_workload_pct,
            "grok_workload_pct": latest.grok_workload_pct,
            "deepseek_tokens": latest.deepseek_tokens,
            "grok_tokens": latest.grok_tokens,
            "api_cost_usd": latest.deepseek_cost_usd + latest.grok_cost_usd,
            "payload": json.loads(latest.payload_json or "{}"),
        },
        "averages": averages,
        "component_count": len(components),
    }


def _decision_share(
    *,
    local_tool_calls: int,
    local_functions_executed: int,
    deepseek_tool_requests: int,
    grok_tool_requests: int,
) -> dict[str, float]:
    local = 0.85 + 0.01 * min(10, local_tool_calls + local_functions_executed)
    deepseek = 0.075 + 0.02 * deepseek_tool_requests
    grok = 0.075 + 0.02 * grok_tool_requests
    total = local + deepseek + grok
    return {"local": local / total, "deepseek": deepseek / total, "grok": grok / total}


def _agent_key(agent_id: str) -> str:
    lowered = agent_id.lower()
    return AGENT_ALIASES.get(
        agent_id,
        "deepseek" if "deepseek" in lowered else "grok" if "grok" in lowered or "qwen" in lowered else agent_id,
    )
