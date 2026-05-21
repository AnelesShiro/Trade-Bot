from __future__ import annotations

import pytest

from src.storage.models import create_schema


def test_save_and_retrieve_structured_lesson(repository) -> None:
    repository.save_structured_lesson(
        agent_id="crypto-deepseek",
        what_happened="SHORT hit stop-loss at resistance",
        why="No volume confirmation in RANGING regime",
        lesson="Require volume spike before SHORT in RANGING",
        follow_or_avoid="avoid",
        regime="RANGING",
        direction="SHORT",
        setup_type="breakout_attempt",
        realized_pnl_pct=-0.032,
        confidence_at_entry=0.8,
        source="bot_signal",
    )
    lessons = repository.structured_lessons("crypto-deepseek", limit=10)
    assert len(lessons) == 1
    rec = lessons[0]
    assert rec.follow_or_avoid == "avoid"
    assert rec.regime == "RANGING"
    assert rec.direction == "SHORT"
    assert rec.realized_pnl_pct == pytest.approx(-0.032)
    assert rec.confidence_at_entry == pytest.approx(0.8)
    assert rec.source == "bot_signal"


def test_invalid_follow_or_avoid_defaults_to_avoid(repository) -> None:
    repository.save_structured_lesson(
        agent_id="crypto-deepseek",
        what_happened="test",
        why="test",
        lesson="test",
        follow_or_avoid="invalid_value",
    )
    lessons = repository.structured_lessons("crypto-deepseek", limit=10)
    assert lessons[0].follow_or_avoid == "avoid"


def test_text_truncated_at_500_chars(repository) -> None:
    long_text = "x" * 600
    repository.save_structured_lesson(
        agent_id="crypto-deepseek",
        what_happened=long_text,
        why=long_text,
        lesson=long_text,
        follow_or_avoid="follow",
    )
    rec = repository.structured_lessons("crypto-deepseek", limit=1)[0]
    assert len(rec.what_happened) == 500
    assert len(rec.why) == 500
    assert len(rec.lesson) == 500


def test_per_agent_isolation(repository) -> None:
    repository.save_structured_lesson("crypto-deepseek", "a", "b", "c", "avoid")
    repository.save_structured_lesson("crypto-qwen", "d", "e", "f", "follow")
    ds = repository.structured_lessons("crypto-deepseek", limit=10)
    qw = repository.structured_lessons("crypto-qwen", limit=10)
    assert len(ds) == 1
    assert len(qw) == 1
    assert ds[0].lesson == "c"
    assert qw[0].lesson == "f"
