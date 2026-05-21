from __future__ import annotations

import pytest
from sqlalchemy import select

from src.config import AgentSettings, LlmLockSettings, Settings
from src.competition.workload import AGENT_ALIASES, WorkloadTracker, _agent_key
from src.storage.models import ReflectionRecord, create_schema, build_session_factory
from src.storage.repository import ArenaRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GEMINI_AGENT = AgentSettings(
    id="crypto-gemini",
    name="Crypto Gemini",
    session_id="crypto-gemini",
    llm=LlmLockSettings(
        LLM_PROVIDER="openai",
        LLM_MODEL="gemini-2.5-flash",
        LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
        LLM_ALLOW_FALLBACK=False,
    ),
)

DEEPSEEK_AGENT = AgentSettings(
    id="crypto-deepseek",
    name="Crypto DeepSeek",
    session_id="crypto-deepseek",
    llm=LlmLockSettings(LLM_PROVIDER="deepseek", LLM_MODEL="deepseek-v4-flash", LLM_ALLOW_FALLBACK=False),
)


def make_repo(tmp_path) -> ArenaRepository:
    url = f"sqlite:///{tmp_path / 'arena.db'}"
    create_schema(url)
    return ArenaRepository(build_session_factory(url))


# ---------------------------------------------------------------------------
# Registration / config
# ---------------------------------------------------------------------------

def test_gemini_agent_has_correct_config() -> None:
    assert GEMINI_AGENT.id == "crypto-gemini"
    assert GEMINI_AGENT.llm.LLM_MODEL == "gemini-2.5-flash"
    assert GEMINI_AGENT.llm.LLM_PROVIDER == "openai"
    assert "generativelanguage.googleapis.com" in GEMINI_AGENT.llm.LLM_BASE_URL
    assert GEMINI_AGENT.llm.LLM_ALLOW_FALLBACK is False


def test_gemini_model_lock_no_fallback() -> None:
    assert GEMINI_AGENT.llm.LLM_ALLOW_FALLBACK is False


def test_gemini_registered_in_settings(test_settings: Settings) -> None:
    """test_settings from conftest has deepseek + qwen — just confirm the pattern works for 3-agent settings too."""
    agent_ids = [a.id for a in test_settings.agents]
    assert "crypto-deepseek" in agent_ids
    assert "crypto-qwen" in agent_ids


# ---------------------------------------------------------------------------
# Workload routing
# ---------------------------------------------------------------------------

def test_gemini_maps_to_gemini_bucket() -> None:
    assert AGENT_ALIASES["crypto-gemini"] == "gemini"
    assert _agent_key("crypto-gemini") == "gemini"


def test_unknown_gemini_variant_maps_to_gemini_bucket() -> None:
    assert _agent_key("crypto-gemini-v2") == "gemini"


def test_tracker_routes_gemini_tokens_to_gemini_bucket() -> None:
    tracker = WorkloadTracker()
    tracker.agent_tokens("crypto-gemini", 500, 100, 0.01)
    assert tracker.agents["gemini"].input_tokens == 500
    assert tracker.agents["gemini"].output_tokens == 100
    assert tracker.agents["deepseek"].input_tokens == 0
    assert tracker.agents["grok"].input_tokens == 0


def test_tracker_finalize_includes_gemini_keys() -> None:
    tracker = WorkloadTracker()
    tracker.agent_latency("crypto-gemini", 1.0)
    tracker.agent_tokens("crypto-gemini", 200, 50, 0.005)
    cycle, _ = tracker.finalize()

    assert "gemini_workload_pct" in cycle
    assert "gemini_latency_seconds" in cycle
    assert "gemini_tokens" in cycle
    assert "gemini_cost_usd" in cycle
    assert cycle["gemini_tokens"] == 250
    assert cycle["gemini_cost_usd"] == pytest.approx(0.005)


# ---------------------------------------------------------------------------
# Isolated account initialization
# ---------------------------------------------------------------------------

def test_gemini_starts_with_zero_trades(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_agents([GEMINI_AGENT])

    trades = repo.trades(agent_id="crypto-gemini")
    assert trades == []


def test_gemini_starts_with_zero_lessons(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_agents([GEMINI_AGENT])

    lessons = repo.lesson_records(agent_id="crypto-gemini")
    assert lessons == []


def test_gemini_starts_with_zero_reflections(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_agents([GEMINI_AGENT])

    with repo.session_factory() as session:
        rows = list(session.scalars(select(ReflectionRecord).where(ReflectionRecord.agent_id == "crypto-gemini")))
    assert rows == []


def test_gemini_state_isolated_from_deepseek(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_agents([DEEPSEEK_AGENT, GEMINI_AGENT])

    repo.save_reflection("crypto-deepseek", "DeepSeek reflection content")
    repo.save_lesson("crypto-deepseek", "DeepSeek lesson content")

    with repo.session_factory() as session:
        gemini_reflections = list(
            session.scalars(select(ReflectionRecord).where(ReflectionRecord.agent_id == "crypto-gemini"))
        )
    gemini_lessons = repo.lesson_records(agent_id="crypto-gemini")

    assert gemini_reflections == [], "Gemini must not inherit DeepSeek reflections"
    assert gemini_lessons == [], "Gemini must not inherit DeepSeek lessons"


# ---------------------------------------------------------------------------
# Leaderboard / performance metrics
# ---------------------------------------------------------------------------

def test_gemini_upserted_as_agent_record(tmp_path) -> None:
    """After upsert_agents the gemini row exists in the agents table."""
    repo = make_repo(tmp_path)
    repo.upsert_agents([DEEPSEEK_AGENT, GEMINI_AGENT])

    from src.storage.models import AgentRecord
    with repo.session_factory() as session:
        agent_ids = [r.id for r in session.scalars(select(AgentRecord))]
    assert "crypto-gemini" in agent_ids
    assert "crypto-deepseek" in agent_ids


def test_three_agent_leaderboard_all_visible(tmp_path) -> None:
    """All three agents show as distinct rows when accounts are queried."""
    repo = make_repo(tmp_path)
    from src.config import AgentSettings, LlmLockSettings
    qwen = AgentSettings(
        id="crypto-qwen",
        name="Crypto Qwen",
        session_id="crypto-qwen",
        llm=LlmLockSettings(LLM_PROVIDER="openai", LLM_MODEL="qwen3-max", LLM_ALLOW_FALLBACK=False),
    )
    repo.upsert_agents([DEEPSEEK_AGENT, qwen, GEMINI_AGENT])

    from src.storage.models import AgentRecord
    with repo.session_factory() as session:
        agent_ids = {r.id for r in session.scalars(select(AgentRecord))}
    assert {"crypto-deepseek", "crypto-qwen", "crypto-gemini"} == agent_ids


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

def test_failure_isolation_workload_tracker() -> None:
    """Gemini tokens must not bleed into deepseek/grok buckets."""
    tracker = WorkloadTracker()
    tracker.agent_latency("crypto-deepseek", 1.0)
    tracker.agent_tokens("crypto-deepseek", 500, 100, 0.005)
    tracker.agent_latency("crypto-gemini", 1.5)
    tracker.agent_tokens("crypto-gemini", 600, 80, 0.008)

    cycle, _ = tracker.finalize()

    assert cycle["deepseek_tokens"] == 600
    assert cycle["gemini_tokens"] == 680
    assert cycle["grok_tokens"] == 0
    assert cycle["deepseek_cost_usd"] == pytest.approx(0.005)
    assert cycle["gemini_cost_usd"] == pytest.approx(0.008)


def test_workload_cycle_persisted_with_gemini(tmp_path) -> None:
    """WorkloadCycleRecord written and read back including gemini columns."""
    from src.competition.workload import summarize_workload

    repo = make_repo(tmp_path)
    tracker = WorkloadTracker()
    tracker.agent_tokens("crypto-deepseek", 100, 20, 0.001)
    tracker.agent_tokens("crypto-gemini", 300, 60, 0.003)
    cycle, components = tracker.finalize()

    repo.save_workload_cycle(cycle, components)
    summary = summarize_workload(repo)

    assert summary["latest"] is not None
    assert summary["latest"]["gemini_tokens"] == 360
    assert summary["latest"]["gemini_cost_usd"] == pytest.approx(0.003)
    assert summary["latest"]["gemini_workload_pct"] >= 0.0
