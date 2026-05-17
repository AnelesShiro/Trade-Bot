from __future__ import annotations

import os
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.config import AgentSettings
from src.logger import logger


@dataclass
class AgentRunResult:
    output: str
    retry_count: int
    latency_ms: int
    configured_model: str
    actual_model: str


@dataclass
class OpenClawAgent:
    settings: AgentSettings
    openclaw_bin: str = os.getenv("OPENCLAW_BIN", "openclaw")

    def run(
        self,
        prompt: str,
        timeout_seconds: int = 600,
        max_retries: int = 3,
        backoff_initial_seconds: float = 1.0,
        backoff_multiplier: float = 2.0,
    ) -> str:
        return self.run_with_metadata(
            prompt,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            backoff_initial_seconds=backoff_initial_seconds,
            backoff_multiplier=backoff_multiplier,
        ).output

    def run_with_metadata(
        self,
        prompt: str,
        timeout_seconds: int = 600,
        max_retries: int = 3,
        backoff_initial_seconds: float = 1.0,
        backoff_multiplier: float = 2.0,
    ) -> AgentRunResult:
        command = [
            *_openclaw_command_prefix(self.openclaw_bin),
            "agent",
            "--agent",
            self.settings.id,
            "--session-id",
            self.settings.session_id,
            "--model",
            self.settings.model,
            "--message",
            prompt,
        ]
        delay = backoff_initial_seconds
        last_error = ""
        started = time.perf_counter()
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("calling OpenClaw agent {} attempt {}/{}", self.settings.id, attempt, max_retries)
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    check=False,
                )
                stdout = (completed.stdout or "").strip()
                stderr = (completed.stderr or "").strip()
                if completed.returncode == 0:
                    actual_model = _latest_session_model(self.settings.id, self.settings.session_id, started)
                    if actual_model != self.settings.model:
                        raise RuntimeError(
                            f"Configured model '{self.settings.model}' is unavailable. Automatic model switching is disabled."
                        )
                    input_tokens, output_tokens, estimated_cost = _estimate_usage(self.settings.model, prompt, stdout)
                    logger.info(
                        "OpenClaw model lock agent={} provider={} configured_model={} actual_model={} input_tokens={} output_tokens={} estimated_cost_usd={:.6f}",
                        self.settings.id,
                        self.settings.provider,
                        self.settings.model,
                        actual_model,
                        input_tokens,
                        output_tokens,
                        estimated_cost,
                    )
                    return AgentRunResult(
                        output=stdout,
                        retry_count=max(0, attempt - 1),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        configured_model=self.settings.model,
                        actual_model=actual_model,
                    )
                last_error = stderr or stdout or f"OpenClaw exited with code {completed.returncode}"
            except subprocess.TimeoutExpired as error:
                last_error = f"OpenClaw timeout after {timeout_seconds}s: {error}"
            if attempt < max_retries:
                time.sleep(delay)
                delay *= backoff_multiplier
        raise RuntimeError(last_error or f"OpenClaw agent {self.settings.id} failed after {max_retries} attempts")


def _openclaw_command_prefix(openclaw_bin: str) -> list[str]:
    executable = os.getenv("OPENCLAW_BIN", openclaw_bin)
    resolved = shutil.which(executable) or executable
    path = Path(resolved)
    if path.name.lower() == "openclaw.cmd":
        module_path = path.parent / "node_modules" / "openclaw" / "openclaw.mjs"
        node = shutil.which("node")
        if module_path.exists() and node:
            return [node, str(module_path)]
    return [resolved]


def _latest_session_model(agent_id: str, session_id: str, started: float) -> str:
    session_file = Path.home() / ".openclaw" / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"
    if not session_file.exists():
        raise RuntimeError(f"Unable to verify OpenClaw response model; session file not found: {session_file}")
    started_wall = datetime.now(UTC).timestamp() - max(0.0, time.perf_counter() - started) - 5
    latest_model = ""
    for line in session_file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except Exception:
            continue
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        timestamp = _parse_timestamp(payload.get("timestamp"))
        if timestamp and timestamp < started_wall:
            continue
        actual = message.get("responseModel") or message.get("model")
        if actual:
            latest_model = str(actual)
    if not latest_model:
        raise RuntimeError("Unable to verify OpenClaw response model; response model was not recorded")
    return latest_model


def _parse_timestamp(value) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _estimate_usage(model: str, prompt: str, response: str) -> tuple[int, int, float]:
    try:
        from src.utils.costs import estimate_cost_usd

        return estimate_cost_usd(model, prompt, response)
    except Exception:
        input_tokens = max(1, len(prompt) // 4)
        output_tokens = max(1, len(response) // 4)
        return input_tokens, output_tokens, 0.0
