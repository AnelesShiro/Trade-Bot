from __future__ import annotations

import time

from src.agents.memory import AgentMemory
from src.storage.vector_store import LocalVectorStore


def test_3factor_prefers_relevant_lesson(repository, tmp_path) -> None:
    memory = AgentMemory(repository, LocalVectorStore(tmp_path / "vectors"))
    # High-relevance lesson: matches query terms, high pnl magnitude
    repository.save_structured_lesson(
        "crypto-deepseek",
        what_happened="SHORT failed at resistance in RANGING",
        why="No volume",
        lesson="Avoid SHORT without volume in RANGING",
        follow_or_avoid="avoid",
        regime="RANGING",
        direction="SHORT",
        realized_pnl_pct=-0.05,
    )
    # Low-relevance lesson: different regime/direction, low pnl
    repository.save_structured_lesson(
        "crypto-deepseek",
        what_happened="LONG in TRENDING worked",
        why="Strong momentum",
        lesson="Follow momentum in TRENDING",
        follow_or_avoid="follow",
        regime="TRENDING",
        direction="LONG",
        realized_pnl_pct=0.01,
    )
    lessons = memory.retrieve_lessons("crypto-deepseek", "RANGING SHORT", limit=6)
    assert len(lessons) >= 1
    # RANGING SHORT lesson should be ranked first
    assert "[AVOID]" in lessons[0]
    assert "RANGING" in lessons[0]


def test_follow_avoid_tags_present(repository, tmp_path) -> None:
    memory = AgentMemory(repository, LocalVectorStore(tmp_path / "vectors"))
    repository.save_structured_lesson(
        "crypto-deepseek", "win setup", "good entry", "Use momentum",
        "follow", regime="TRENDING", direction="LONG", realized_pnl_pct=0.04,
    )
    repository.save_structured_lesson(
        "crypto-deepseek", "loss setup", "bad entry", "Avoid RANGING short",
        "avoid", regime="RANGING", direction="SHORT", realized_pnl_pct=-0.03,
    )
    lessons = memory.retrieve_lessons("crypto-deepseek", "RANGING SHORT", limit=6)
    tags = {l.split("]")[0].strip("[") for l in lessons}
    assert "FOLLOW" in tags or "AVOID" in tags


def test_falls_back_to_legacy_when_no_structured(repository, tmp_path) -> None:
    memory = AgentMemory(repository, LocalVectorStore(tmp_path / "vectors"))
    memory.save_lesson("crypto-deepseek", "short stop-loss hit in ranging market")
    lessons = memory.retrieve_lessons("crypto-deepseek", "RANGING SHORT", limit=6)
    assert len(lessons) >= 1


def test_reflect_on_day_does_not_write_lesson(repository, tmp_path) -> None:
    from src.agents.reflection import reflect_on_day
    memory = AgentMemory(repository, LocalVectorStore(tmp_path / "vectors"))
    count_before = len(repository.lessons("crypto-deepseek", limit=100))
    reflect_on_day(memory, "crypto-deepseek", 10000, 0, 0)
    assert len(repository.lessons("crypto-deepseek", limit=100)) == count_before
