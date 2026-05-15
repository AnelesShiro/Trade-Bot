from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass

from src.config import AgentSettings
from src.logger import logger


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
        command = [
            self.openclaw_bin,
            "agent",
            "--agent",
            self.settings.id,
            "--session-id",
            self.settings.session_id,
            "--message",
            prompt,
        ]
        delay = backoff_initial_seconds
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                logger.info("calling OpenClaw agent {} attempt {}/{}", self.settings.id, attempt, max_retries)
                completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
                if completed.returncode == 0:
                    return completed.stdout.strip()
                last_error = completed.stderr.strip() or completed.stdout.strip()
            except subprocess.TimeoutExpired as error:
                last_error = f"OpenClaw timeout after {timeout_seconds}s: {error}"
            if attempt < max_retries:
                time.sleep(delay)
                delay *= backoff_multiplier
        raise RuntimeError(last_error or f"OpenClaw agent {self.settings.id} failed after {max_retries} attempts")
