from __future__ import annotations

from src.competition.evaluation import calculate_leaderboard
from src.schemas import LeaderboardRow
from src.storage.repository import ArenaRepository


def get_leaderboard(
    repository: ArenaRepository,
    agent_ids: list[str],
    initial_equity: float,
    current_price: float,
) -> list[LeaderboardRow]:
    return calculate_leaderboard(repository, agent_ids, initial_equity, current_price)
