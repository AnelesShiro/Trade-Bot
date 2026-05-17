from __future__ import annotations

import subprocess

import pytest

from src.agents.base_agent import OpenClawAgent
from src.config import AgentSettings


def test_openclaw_agent_handles_missing_stderr(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr=None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = OpenClawAgent(AgentSettings(id="crypto-grok", name="Grok", model="xai/grok", session_id="s"))

    with pytest.raises(RuntimeError, match="OpenClaw exited with code 1"):
        agent.run("prompt", max_retries=1)


def test_openclaw_agent_decodes_output_with_replacement(monkeypatch) -> None:
    seen_kwargs = {}

    def fake_run(*args, **kwargs):
        seen_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=" ok \n", stderr=None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    agent = OpenClawAgent(AgentSettings(id="crypto-grok", name="Grok", model="xai/grok", session_id="s"))

    assert agent.run("prompt", max_retries=1) == "ok"
    assert seen_kwargs["encoding"] == "utf-8"
    assert seen_kwargs["errors"] == "replace"
