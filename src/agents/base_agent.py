from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

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
            *_openclaw_command_prefix(self.openclaw_bin),
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
                    return stdout
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
