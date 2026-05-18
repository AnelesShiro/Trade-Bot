from __future__ import annotations

from typing import Any

from src.dashboard.tabs.lessons_to_follow import _render_lesson_tab


def render_lessons_to_avoid_tab(rows: list[dict[str, Any]], agent_ids: list[str], date_range: tuple[Any, Any] | None = None) -> None:
    _render_lesson_tab(
        rows,
        agent_ids,
        title="Lessons to Avoid",
        empty_message="No validated negative lessons meet the current filters yet.",
        accent="#ef4444",
        key_prefix="lessons_avoid",
        date_range=date_range,
    )
