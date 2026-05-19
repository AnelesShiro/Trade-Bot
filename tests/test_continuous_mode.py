from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── Config ─────────────────────────────────────────────────────────────────────

def test_weekly_target_is_7pct() -> None:
    from src.config import load_settings
    s = load_settings()
    assert s.competition.weekly_target_pct == pytest.approx(0.07)


def test_duration_days_is_zero_for_continuous_mode() -> None:
    from src.config import load_settings
    s = load_settings()
    assert s.competition.duration_days == 0


# ── Runner: competition_time_pct is unbounded ───────────────────────────────────

def test_competition_time_pct_unbounded_after_8_days() -> None:
    from src.competition.runner import CompetitionRunner
    from unittest.mock import MagicMock
    from src.config import load_settings

    settings = load_settings()
    start = datetime.now(UTC) - timedelta(days=8)

    repo_mock = MagicMock()
    repo_mock.competition_start_time.return_value = start

    runner = CompetitionRunner.__new__(CompetitionRunner)
    runner.settings = settings
    runner.repository = repo_mock

    result = runner._competition_time_pct()
    assert result > 1.0, f"Expected > 1.0 for 8-day uptime, got {result}"


# ── Snapshot exporter: no COMPLETED when continuous ────────────────────────────

def test_competition_status_never_completed_when_end_time_none() -> None:
    from src.cloud.snapshot_exporter import _competition_status
    now = datetime.now(UTC)
    start = now - timedelta(days=30)
    latest_cycle = now - timedelta(minutes=30)
    poll_interval = 3600

    status = _competition_status(now, start, None, latest_cycle, poll_interval)
    assert status != "COMPLETED"
    assert status in ("RUNNING", "PAUSED", "SCHEDULED")


def test_competition_status_completed_only_when_end_time_set() -> None:
    from src.cloud.snapshot_exporter import _competition_status
    now = datetime.now(UTC)
    start = now - timedelta(days=8)
    end = now - timedelta(days=1)

    status = _competition_status(now, start, end, now - timedelta(minutes=30), 3600)
    assert status == "COMPLETED"


def test_competition_window_returns_none_end_when_continuous() -> None:
    from src.cloud.snapshot_exporter import _competition_window
    from src.config import load_settings
    from unittest.mock import MagicMock

    settings = load_settings()
    assert settings.competition.duration_days == 0

    repo_mock = MagicMock()
    repo_mock.competition_start_time.return_value = datetime.now(UTC) - timedelta(days=5)

    start, end = _competition_window(settings, repo_mock)
    assert end is None, f"Expected end_time=None in continuous mode, got {end}"


# ── Rolling 7-day return helper ─────────────────────────────────────────────────

def _make_trades_df(entries: list[tuple[datetime, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"execution_timestamp": ts, "realized_pnl": pnl} for ts, pnl in entries]
    )


def test_rolling_7d_return_empty_trades() -> None:
    from src.dashboard.app import rolling_7d_return_pct
    result = rolling_7d_return_pct(pd.DataFrame(), 10_000)
    assert result == 0.0


def test_rolling_7d_return_only_recent_trades_counted() -> None:
    from src.dashboard.app import rolling_7d_return_pct
    now = datetime.now(UTC)
    trades = _make_trades_df([
        (now - timedelta(days=1), 100.0),   # within 7d → counted
        (now - timedelta(days=8), 500.0),   # older than 7d → excluded
    ])
    result = rolling_7d_return_pct(trades, 10_000)
    assert result == pytest.approx(100.0 / 10_000)


def test_rolling_7d_return_all_trades_recent() -> None:
    from src.dashboard.app import rolling_7d_return_pct
    now = datetime.now(UTC)
    trades = _make_trades_df([
        (now - timedelta(hours=2), 200.0),
        (now - timedelta(hours=10), 150.0),
    ])
    result = rolling_7d_return_pct(trades, 10_000)
    assert result == pytest.approx(350.0 / 10_000)


# ── Prompts: no competition-ending language ────────────────────────────────────

FORBIDDEN_PHRASES = [
    "competition ended",
    "trial period has ended",
    "no new trades should be entered",
    "days remaining",
    "final equity",
    "trial period: 1 week",
    "target: strive for +10%",
    "+10% weekly target",
]


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_system_prompt_no_competition_end_language(phrase: str) -> None:
    content = (PROJECT_ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8").lower()
    assert phrase.lower() not in content, f"Found forbidden phrase in system_prompt.md: '{phrase}'"


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_rulebook_no_competition_end_language(phrase: str) -> None:
    content = (PROJECT_ROOT / "config" / "rulebook.md").read_text(encoding="utf-8").lower()
    assert phrase.lower() not in content, f"Found forbidden phrase in rulebook.md: '{phrase}'"


def test_rulebook_mentions_7pct_target() -> None:
    content = (PROJECT_ROOT / "config" / "rulebook.md").read_text(encoding="utf-8")
    assert "+7%" in content, "rulebook.md should mention the +7% soft weekly target"


def test_system_prompt_mentions_no_deadline() -> None:
    content = (PROJECT_ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    assert "no end date" in content.lower() or "no deadline" in content.lower(), \
        "system_prompt.md should state there is no deadline"
