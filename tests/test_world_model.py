from __future__ import annotations

from src.analytics.world_model import get_world_model


def test_empty_when_no_structured_lessons(repository) -> None:
    result = get_world_model(repository, "crypto-deepseek")
    assert result == ""


def test_empty_when_below_min_sample(repository) -> None:
    repository.save_structured_lesson(
        "crypto-deepseek", "w", "y", "l", "avoid",
        regime="RANGING", direction="SHORT", realized_pnl_pct=-0.02,
    )
    repository.save_structured_lesson(
        "crypto-deepseek", "w", "y", "l", "avoid",
        regime="RANGING", direction="SHORT", realized_pnl_pct=-0.01,
    )
    # Only 2 entries for RANGING×SHORT — below default min_sample=3
    result = get_world_model(repository, "crypto-deepseek", min_sample=3)
    assert result == ""


def test_shows_stats_at_min_sample(repository) -> None:
    for pnl in [-0.02, -0.01, 0.03]:
        repository.save_structured_lesson(
            "crypto-deepseek", "w", "y", "l", "avoid" if pnl < 0 else "follow",
            regime="TRENDING", direction="LONG", realized_pnl_pct=pnl,
        )
    result = get_world_model(repository, "crypto-deepseek", min_sample=3)
    assert "TRENDING" in result
    assert "LONG" in result
    assert "1W/2L" in result or "33%" in result or "1W" in result


def test_per_agent_isolation(repository) -> None:
    for pnl in [0.02, 0.03, 0.04]:
        repository.save_structured_lesson(
            "crypto-qwen", "w", "y", "l", "follow",
            regime="RANGING", direction="LONG", realized_pnl_pct=pnl,
        )
    assert get_world_model(repository, "crypto-deepseek", min_sample=3) == ""
    assert get_world_model(repository, "crypto-qwen", min_sample=3) != ""
