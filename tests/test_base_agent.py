from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.agents.base_agent import OpenClawAgent
from src.config import AgentSettings, LlmLockSettings


def make_agent(model: str = "grok-test", session_id: str = "s") -> OpenClawAgent:
    return OpenClawAgent(
        AgentSettings(
            id="crypto-grok",
            name="Grok",
            session_id=session_id,
            llm=LlmLockSettings(LLM_PROVIDER="xai", LLM_MODEL=model, LLM_ALLOW_FALLBACK=False),
        )
    )


def write_session_model(home: Path, model: str, response_model: str | None = None, session_id: str = "s") -> None:
    session = home / ".openclaw" / "agents" / "crypto-grok" / "sessions"
    session.mkdir(parents=True, exist_ok=True)
    actual = f'"responseModel": "{response_model}",' if response_model else ""
    (session / f"{session_id}.jsonl").write_text(
        '{"timestamp":"2099-01-01T00:00:00Z","message":{"role":"assistant","model":"'
        + model
        + '",'
        + actual
        + '"usage":{"input":1,"output":1}}}\n',
        encoding="utf-8",
    )


def test_openclaw_agent_handles_missing_stderr(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr=None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = make_agent()

    with pytest.raises(RuntimeError, match="OpenClaw exited with code 1"):
        agent.run("prompt", max_retries=1)


def test_openclaw_agent_decodes_output_with_replacement(monkeypatch, tmp_path) -> None:
    seen_kwargs = {}

    def fake_run(*args, **kwargs):
        seen_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=" ok \n", stderr=None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "grok-test")
    agent = make_agent()

    assert agent.run("prompt", max_retries=1) == "ok"
    assert seen_kwargs["encoding"] == "utf-8"
    assert seen_kwargs["errors"] == "replace"


def test_openclaw_agent_reports_retry_count(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="temporary")
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=" ok ", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "grok-test")
    agent = make_agent()

    result = agent.run_with_metadata("prompt", max_retries=2)

    assert result.output == "ok"
    assert result.retry_count == 1
    assert result.latency_ms >= 0
    assert result.configured_model == "grok-test"
    assert result.actual_model == "grok-test"


def test_openclaw_agent_does_not_use_gateway_model_override(monkeypatch, tmp_path) -> None:
    seen_command = {}

    def fake_run(*args, **kwargs):
        seen_command["command"] = args[0]
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "exact-model")
    agent = make_agent(model="exact-model")

    assert agent.run("prompt", max_retries=1) == "ok"
    assert "--model" not in seen_command["command"]


def test_openclaw_agent_passes_cli_timeout(monkeypatch, tmp_path) -> None:
    seen_command = {}

    def fake_run(*args, **kwargs):
        seen_command["command"] = args[0]
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "exact-model")
    agent = make_agent(model="exact-model")

    assert agent.run("prompt", timeout_seconds=123, max_retries=1) == "ok"
    timeout_index = seen_command["command"].index("--timeout")
    assert seen_command["command"][timeout_index + 1] == "123"


def test_openclaw_agent_model_mismatch_throws(monkeypatch, tmp_path) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "requested", response_model="redirected")
    agent = make_agent(model="requested")

    with pytest.raises(RuntimeError, match="Configured model 'requested' is unavailable"):
        agent.run("prompt", max_retries=1)


def test_missing_model_throws() -> None:
    with pytest.raises(ValueError, match="LLM_MODEL is required"):
        LlmLockSettings(LLM_PROVIDER="xai", LLM_MODEL="", LLM_ALLOW_FALLBACK=False)


def test_fallback_never_allowed() -> None:
    with pytest.raises(ValueError, match="LLM_ALLOW_FALLBACK must be false"):
        LlmLockSettings(LLM_PROVIDER="xai", LLM_MODEL="xai/model", LLM_ALLOW_FALLBACK=True)
