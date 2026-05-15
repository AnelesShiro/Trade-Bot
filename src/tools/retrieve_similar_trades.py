from __future__ import annotations

from src.storage.repository import ArenaRepository


def retrieve_similar_trades(repository: ArenaRepository, agent_id: str, limit: int = 5) -> list[str]:
    trades = repository.trades(agent_id)[-limit:]
    return [
        f"{trade.created_at.isoformat()} {trade.action} {trade.direction} entry={trade.entry} pnl={trade.realized_pnl}"
        for trade in trades
    ]
