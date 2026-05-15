from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT, Settings
from src.logger import logger
from src.storage.repository import ArenaRepository


@dataclass
class GitSyncResult:
    attempted: bool
    changed: bool
    committed: bool
    pushed: bool
    message: str


TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "could not resolve",
    "failed to connect",
    "remote end hung up",
    "network",
    "temporarily unavailable",
)


def sync_dashboard_snapshot(
    settings: Settings,
    repository: ArenaRepository,
    *,
    skip_render: bool = False,
    max_retries: int = 3,
) -> GitSyncResult:
    snapshot_path = settings.resolve_path(settings.cloud_dashboard.snapshot_path)
    relative_snapshot = snapshot_path.relative_to(PROJECT_ROOT).as_posix()
    if not snapshot_path.exists():
        result = GitSyncResult(False, False, False, False, f"snapshot missing: {relative_snapshot}")
        _log_attempt(repository, "FAIL", result.message)
        return result
    if not _is_git_repository(PROJECT_ROOT):
        result = GitSyncResult(False, False, False, False, "project is not inside a git repository")
        _log_attempt(repository, "FAIL", result.message)
        return result
    if not snapshot_changed(relative_snapshot):
        result = GitSyncResult(True, False, False, False, "snapshot unchanged")
        _log_attempt(repository, "PASS", result.message)
        return result

    commit_message = "dashboard snapshot update [skip render]" if skip_render else "dashboard snapshot update"
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            _run_git(["add", "--", relative_snapshot])
            _run_git(["commit", "-m", commit_message, "--", relative_snapshot])
            _run_git(["push", "origin", settings.cloud_dashboard.git_branch])
            result = GitSyncResult(True, True, True, True, f"pushed {relative_snapshot} to {settings.cloud_dashboard.git_branch}")
            _log_attempt(repository, "PASS", result.message)
            return result
        except RuntimeError as error:
            last_error = str(error)
            logger.warning("dashboard snapshot sync attempt {}/{} failed: {}", attempt, max_retries, last_error)
            if attempt >= max_retries or not _looks_transient(last_error):
                break
            time.sleep(min(30, 2**attempt))

    result = GitSyncResult(True, True, False, False, last_error or "git sync failed")
    _log_attempt(repository, "FAIL", result.message)
    return result


def snapshot_changed(relative_snapshot: str) -> bool:
    status = _run_git(["status", "--porcelain", "--", relative_snapshot])
    return bool(status.strip())


def _is_git_repository(path: Path) -> bool:
    result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, capture_output=True, text=True, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _run_git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise RuntimeError(output.strip() or f"git {' '.join(args)} failed")
    return output


def _looks_transient(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


def _log_attempt(repository: ArenaRepository, status: str, message: str) -> None:
    logger.info("dashboard git sync {}: {}", status, message)
    repository.save_health_check("cloud_git_sync", status, False, message[:1000])
