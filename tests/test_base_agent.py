from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.agents.base_agent import OpenClawAgent, _model_is_compatible
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


def _session_dir(home: Path) -> Path:
    d = home / ".openclaw" / "agents" / "crypto-grok" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_session_model(home: Path, model: str, response_model: str | None = None, session_id: str = "s") -> None:
    actual = f'"responseModel": "{response_model}",' if response_model else ""
    (_session_dir(home) / f"{session_id}.jsonl").write_text(
        '{"timestamp":"2099-01-01T00:00:00Z","message":{"role":"assistant","model":"'
        + model
        + '",'
        + actual
        + '"usage":{"input":1,"output":1}}}\n',
        encoding="utf-8",
    )


def write_session_no_model(home: Path, session_id: str = "s") -> None:
    """Session file exists but assistant message carries no model field."""
    (_session_dir(home) / f"{session_id}.jsonl").write_text(
        '{"timestamp":"2099-01-01T00:00:00Z","message":{"role":"assistant","content":"ok","usage":{"input":1,"output":1}}}\n',
        encoding="utf-8",
    )


def write_session_model_change_event(home: Path, model_id: str, session_id: str = "s") -> None:
    """Session file has a model_change event (no assistant message)."""
    line = json.dumps({
        "type": "model_change",
        "timestamp": "2099-01-01T00:00:00Z",
        "modelId": model_id,
    })
    (_session_dir(home) / f"{session_id}.jsonl").write_text(line + "\n", encoding="utf-8")


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


# ── Model compatibility unit tests ───────────────────────────────────────────

def test_model_is_compatible_exact_match() -> None:
    assert _model_is_compatible("deepseek-v4-flash", "deepseek-v4-flash") is True


def test_model_is_compatible_versioned_suffix() -> None:
    # DashScope returns "qwen3-max-2026-01-23" when caller configures "qwen3-max"
    assert _model_is_compatible("qwen3-max-2026-01-23", "qwen3-max") is True


def test_model_is_compatible_completely_different() -> None:
    assert _model_is_compatible("gpt-4o", "qwen3-max") is False


def test_model_is_compatible_different_family() -> None:
    assert _model_is_compatible("deepseek-v4-flash", "qwen3-max") is False


# ── Integration tests for the session-model fallback logic ───────────────────

def test_versioned_model_suffix_passes(monkeypatch, tmp_path) -> None:
    """qwen3-max-2026-01-23 in session → configured qwen3-max → no error, actual recorded."""
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "qwen3-max-2026-01-23")
    agent = make_agent(model="qwen3-max")

    result = agent.run_with_metadata("prompt", max_retries=1)

    assert result.output == "ok"
    assert result.configured_model == "qwen3-max"
    assert result.actual_model == "qwen3-max-2026-01-23"


def test_missing_session_file_falls_back_to_configured(monkeypatch, tmp_path) -> None:
    """No session file at all → warning logged, actual_model = configured_model, no error."""
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # deliberately do NOT write any session file
    agent = make_agent(model="qwen3-max")

    result = agent.run_with_metadata("prompt", max_retries=1)

    assert result.output == "ok"
    assert result.configured_model == "qwen3-max"
    assert result.actual_model == "qwen3-max"


def test_no_model_in_session_falls_back_to_configured(monkeypatch, tmp_path) -> None:
    """Session file exists but assistant message has no model field → falls back to configured."""
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_no_model(tmp_path)
    agent = make_agent(model="qwen3-max")

    result = agent.run_with_metadata("prompt", max_retries=1)

    assert result.output == "ok"
    assert result.actual_model == "qwen3-max"


def test_model_change_event_used_as_source(monkeypatch, tmp_path) -> None:
    """model_change event in session → model extracted even without an assistant message."""
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model_change_event(tmp_path, model_id="qwen3-max-2026-01-23")
    agent = make_agent(model="qwen3-max")

    result = agent.run_with_metadata("prompt", max_retries=1)

    assert result.output == "ok"
    assert result.actual_model == "qwen3-max-2026-01-23"


def test_completely_different_model_still_raises(monkeypatch, tmp_path) -> None:
    """Provider returns a totally different model → still raises model-drift error."""
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    write_session_model(tmp_path, "gpt-4o")
    agent = make_agent(model="qwen3-max")

    with pytest.raises(RuntimeError, match="Configured model 'qwen3-max' is unavailable"):
        agent.run("prompt", max_retries=1)
