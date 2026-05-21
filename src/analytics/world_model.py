from __future__ import annotations

from src.storage.repository import ArenaRepository


def get_world_model(repository: ArenaRepository, agent_id: str, min_sample: int = 3) -> str:
    """Return a formatted regime×direction win-rate table from structured lesson history.

    Uses structured_lessons as the source since it captures regime at lesson time.
    Only includes buckets with at least `min_sample` entries.
    Returns empty string when insufficient data.
    """
    lessons = repository.structured_lessons(agent_id, limit=500)
    closed = [l for l in lessons if l.realized_pnl_pct is not None]
    if not closed:
        return ""

    buckets: dict[tuple[str, str], list[float]] = {}
    for rec in closed:
        regime = (rec.regime or "unknown").upper()
        direction = (rec.direction or "NONE").upper()
        buckets.setdefault((regime, direction), []).append(rec.realized_pnl_pct)

    lines: list[str] = []
    for (regime, direction), pnls in sorted(buckets.items()):
        if len(pnls) < min_sample:
            continue
        wins = sum(1 for p in pnls if p > 0)
        losses = len(pnls) - wins
        win_rate = wins / len(pnls)
        avg_pnl_pct = sum(pnls) / len(pnls) * 100
        lines.append(
            f"  {regime} × {direction}: {wins}W/{losses}L = {win_rate:.0%} win rate, avg {avg_pnl_pct:+.1f}% on margin"
        )

    if not lines:
        return ""

    return "HISTORICAL PERFORMANCE (your closed trades, ≥3 samples):\n" + "\n".join(lines)
