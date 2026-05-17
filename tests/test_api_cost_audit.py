from __future__ import annotations

from src.competition.api_cost_audit import diagnose_cost_spike, summarize_api_costs


def test_api_request_audit_flags_prompt_and_cost_spikes(repository) -> None:
    repository.save_api_request(
        {
            "agent_name": "crypto-qwen",
            "model_name": "qwen/qwen3-max-2026-01-23",
            "request_type": "signal",
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "token_cost_usd": 0.001,
            "total_cost_usd": 0.001,
            "prompt_characters": 400,
            "response_characters": 40,
            "prompt_hash": "p1",
            "response_hash": "r1",
        }
    )
    repository.save_api_request(
        {
            "agent_name": "crypto-qwen",
            "model_name": "qwen/qwen3-max-2026-01-23",
            "request_type": "signal",
            "prompt_tokens": 400,
            "completion_tokens": 40,
            "total_tokens": 440,
            "token_cost_usd": 0.004,
            "total_cost_usd": 0.004,
            "retry_count": 1,
            "prompt_characters": 1000,
            "response_characters": 120,
            "prompt_hash": "p2",
            "response_hash": "r2",
        }
    )

    rows = repository.api_requests(agent_name="crypto-qwen")
    assert len(rows) == 2
    assert "cost_gt_3x_previous" in rows[0].anomaly_flags_json
    assert "tokens_gt_3x_previous" in rows[0].anomaly_flags_json
    assert "prompt_size_gt_2x_previous" in rows[0].anomaly_flags_json
    assert "retry_count_gt_0" in rows[0].anomaly_flags_json


def test_api_cost_summary_compares_agents(repository) -> None:
    for agent_name, cost in [("crypto-deepseek", 0.001), ("crypto-qwen", 0.01)]:
        repository.save_api_request(
            {
                "agent_name": agent_name,
                "model_name": "model",
                "request_type": "signal",
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "token_cost_usd": cost,
                "total_cost_usd": cost,
                "prompt_characters": 500,
                "response_characters": 80,
                "prompt_hash": agent_name,
                "response_hash": agent_name,
            }
        )

    summary = summarize_api_costs(repository)

    assert summary["by_agent"]["crypto-qwen"]["request_count"] == 1
    assert any("Challenger estimated audit cost" in finding for finding in summary["diagnosis"])


def test_diagnosis_handles_empty_challenger_rows() -> None:
    assert diagnose_cost_spike([]) == ["No challenger API audit rows are recorded yet."]
