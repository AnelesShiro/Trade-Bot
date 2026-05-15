from __future__ import annotations

from pathlib import Path


class LocalVectorStore:
    """Small durable memory wrapper.

    ChromaDB is used when installed. If it is unavailable, lessons are still
    persisted in SQLite by the repository and this class returns an empty
    retrieval result instead of failing the competition runner.
    """

    def __init__(self, persist_dir: str | Path) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        except Exception:
            self._client = None

    def add_lesson(self, agent_id: str, lesson_id: str, content: str) -> None:
        if not self._client:
            return
        collection = self._client.get_or_create_collection(agent_id)
        collection.upsert(ids=[lesson_id], documents=[content])

    def query(self, agent_id: str, text: str, limit: int = 5) -> list[str]:
        if not self._client:
            return []
        collection = self._client.get_or_create_collection(agent_id)
        result = collection.query(query_texts=[text], n_results=limit)
        return list(result.get("documents", [[]])[0])
