from __future__ import annotations

from src.competition.workload import AgentWork, WorkloadTracker, summarize_workload, workload_scores


def test_workload_scores_sum_to_one() -> None:
    deepseek = AgentWork(input_tokens=1000, output_tokens=200, latency_seconds=2.0, tool_requests=1, reflections_generated=1, lessons_generated=1)
    grok = AgentWork(input_tokens=900, output_tokens=150, latency_seconds=1.5, tool_requests=0, reflections_generated=1, lessons_generated=1)

    scores = workload_scores(
        local_wall_time_seconds=20.0,
        deepseek=deepseek,
        grok=grok,
        local_tool_calls=8,
        local_functions_executed=30,
        local_reflections_processed=2,
        local_lessons_promoted=1,
    )

    assert round(sum(scores.values()), 10) == 1.0
    assert scores["local"] > scores["deepseek"]
    assert scores["local"] > scores["grok"]


def test_workload_tracker_persists_summary(repository) -> None:
    tracker = WorkloadTracker()
    tracker.local_function("market_data", "get_market_state")
    tracker.local_tool("get_indicators")
    tracker.memory_retrieval()
    tracker.agent_latency("crypto-deepseek", 0.1)
    tracker.agent_tokens("crypto-deepseek", 100, 50, 0.01)
    tracker.agent_latency("crypto-qwen", 0.2)
    tracker.agent_tokens("crypto-qwen", 120, 60, 0.02)
    cycle, components = tracker.finalize()

    repository.save_workload_cycle(cycle, components)
    summary = summarize_workload(repository)

    assert summary["latest"] is not None
    latest = summary["latest"]
    assert round(latest["local_workload_pct"] + latest["deepseek_workload_pct"] + latest["grok_workload_pct"], 6) == 100.0
    assert latest["deepseek_tokens"] == 150
    assert latest["grok_tokens"] == 180
    assert summary["component_count"] >= 5
