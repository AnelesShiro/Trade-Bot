from __future__ import annotations

from src.agents.lesson_canonicalizer import canonical_summary, lesson_key


def test_canonical_summary_removes_short_stop_noise() -> None:
    raw = "SHORT loss: notes=CLOSED DS-SHORT-003 fee=5.0 slippage_bps=2. After-stop-loss wait rule should apply."

    assert canonical_summary(raw) == "Pause new SHORT entries for one full cycle after a short stop-loss."


def test_canonical_summary_removes_account_status_noise() -> None:
    raw = "Daily review: equity=10000 realized_pnl=-5 unrealized_pnl=2. Keep valid setups only and preserve rule compliance."

    assert canonical_summary(raw) == "Trade only high-quality setups and maintain strict rule compliance."


def test_lesson_key_deduplicates_similar_raw_lessons() -> None:
    left = "SHORT loss: notes=CLOSED DS-SHORT-003 fee=5 slippage_bps=2 After-stop-loss wait rule."
    right = "SHORT loss: notes=CLOSED DS-SHORT-004 fee=7 slippage_bps=3 After-stop-loss wait rule."

    assert lesson_key(left) == lesson_key(right)
