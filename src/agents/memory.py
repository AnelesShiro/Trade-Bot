from __future__ import annotations

from src.storage.repository import ArenaRepository
from src.storage.vector_store import LocalVectorStore


class AgentMemory:
    def __init__(self, repository: ArenaRepository, vector_store: LocalVectorStore) -> None:
        self.repository = repository
        self.vector_store = vector_store

    def retrieve_lessons(self, agent_id: str, query: str, limit: int = 6) -> list[str]:
        vector_lessons = self.vector_store.query(agent_id, query, limit=limit)
        sql_lessons = self.repository.lessons(agent_id, limit=limit)
        merged: list[str] = []
        for lesson in [*vector_lessons, *sql_lessons]:
            if lesson not in merged:
                merged.append(lesson)
        return merged[:limit]

    def save_lesson(self, agent_id: str, content: str) -> None:
        self.repository.save_lesson(agent_id, content)
        self.vector_store.add_lesson(agent_id, f"{agent_id}-{abs(hash(content))}", content)
