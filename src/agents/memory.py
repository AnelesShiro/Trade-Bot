from __future__ import annotations

import math
from datetime import UTC, datetime

from src.agents.lesson_canonicalizer import canonical_summary
from src.storage.repository import ArenaRepository
from src.storage.vector_store import LocalVectorStore


class AgentMemory:
    def __init__(self, repository: ArenaRepository, vector_store: LocalVectorStore) -> None:
        self.repository = repository
        self.vector_store = vector_store

    def retrieve_lessons(self, agent_id: str, query: str, limit: int = 6) -> list[str]:
        """3-factor retrieval: recency × relevance × importance (Generative Agents pattern).

        Falls back to legacy canonicalized lessons when no structured lessons exist yet.
        """
        structured = self.repository.structured_lessons(agent_id, limit=200)
        if structured:
            query_tokens = set(query.lower().split())
            now = datetime.now(UTC)
            scored: list[tuple[float, str]] = []
            seen: set[str] = set()
            for rec in structured:
                age_days = max(0.0, (now - rec.created_at.replace(tzinfo=UTC)).total_seconds() / 86400)
                recency = math.exp(-0.1 * age_days)
                lesson_tokens = set((rec.lesson + " " + rec.what_happened + " " + (rec.regime or "") + " " + (rec.direction or "")).lower().split())
                overlap = len(query_tokens & lesson_tokens)
                relevance = min(1.0, overlap / max(len(query_tokens), 1))
                pnl = abs(rec.realized_pnl_pct or 0.0)
                importance = min(1.0, pnl * 10) if pnl > 0 else 0.1
                score = 0.3 * recency + 0.4 * relevance + 0.3 * importance
                tag = "[FOLLOW]" if rec.follow_or_avoid == "follow" else "[AVOID]"
                text = f"{tag} {rec.lesson} (regime={rec.regime or '?'}, dir={rec.direction or '?'})"
                if text not in seen:
                    seen.add(text)
                    scored.append((score, text))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [text for _, text in scored[:limit]]
        # Legacy fallback when structured_lessons table is empty
        vector_lessons = self.vector_store.query(agent_id, query, limit=limit)
        sql_lessons = self.repository.lessons(agent_id, limit=limit)
        merged: list[str] = []
        for lesson in [*vector_lessons, *sql_lessons]:
            summary = canonical_summary(lesson)
            if summary not in merged:
                merged.append(summary)
        return merged[:limit]

    def save_lesson(self, agent_id: str, content: str) -> None:
        summary = canonical_summary(content)
        self.repository.save_lesson(agent_id, content)
        self.vector_store.add_lesson(agent_id, f"{agent_id}-{abs(hash(summary))}", summary)
