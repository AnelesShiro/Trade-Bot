from __future__ import annotations

from src.analytics.calibration import get_calibration


def test_empty_when_no_data(repository) -> None:
    assert get_calibration(repository, "crypto-deepseek") == ""


def test_empty_when_missing_confidence_or_pnl(repository) -> None:
    repository.save_structured_lesson(
        "crypto-deepseek", "w", "y", "l", "avoid",
        realized_pnl_pct=-0.02,
        confidence_at_entry=None,  # missing
    )
    repository.save_structured_lesson(
        "crypto-deepseek", "w", "y", "l", "avoid",
        realized_pnl_pct=None,    # missing
        confidence_at_entry=0.8,
    )
    assert get_calibration(repository, "crypto-deepseek") == ""


def test_calibration_groups_by_bucket(repository) -> None:
    for pnl in [-0.02, -0.01, 0.03]:
        repository.save_structured_lesson(
            "crypto-deepseek", "w", "y", "l", "avoid" if pnl < 0 else "follow",
            realized_pnl_pct=pnl,
            confidence_at_entry=0.82,
        )
    result = get_calibration(repository, "crypto-deepseek", min_sample=3)
    assert "confidence=0.8" in result
    assert "33%" in result or "1 trades" in result or "3 trades" in result


def test_overconfident_flag(repository) -> None:
    for _ in range(5):
        repository.save_structured_lesson(
            "crypto-deepseek", "w", "y", "l", "avoid",
            realized_pnl_pct=-0.02,
            confidence_at_entry=0.9,
        )
    result = get_calibration(repository, "crypto-deepseek", min_sample=3)
    assert "OVERCONFIDENT" in result
