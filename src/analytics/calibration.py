from __future__ import annotations

from src.storage.repository import ArenaRepository


def get_calibration(repository: ArenaRepository, agent_id: str, min_sample: int = 3) -> str:
    """Return a confidence bucket → actual win-rate calibration table.

    Uses structured_lessons that have both confidence_at_entry and realized_pnl_pct.
    Returns empty string when insufficient data.
    """
    lessons = repository.structured_lessons(agent_id, limit=500)
    calibrated = [
        l for l in lessons
        if l.confidence_at_entry is not None and l.realized_pnl_pct is not None
    ]
    if not calibrated:
        return ""

    buckets: dict[float, list[float]] = {}
    for rec in calibrated:
        bucket = round(rec.confidence_at_entry * 10) / 10
        buckets.setdefault(bucket, []).append(rec.realized_pnl_pct)

    lines: list[str] = []
    for bucket in sorted(buckets):
        pnls = buckets[bucket]
        if len(pnls) < min_sample:
            continue
        wins = sum(1 for p in pnls if p > 0)
        actual_wr = wins / len(pnls)
        flag = " ← OVERCONFIDENT" if bucket >= 0.7 and actual_wr < 0.45 else ""
        lines.append(
            f"  confidence={bucket:.1f} → actual win rate {actual_wr:.0%} ({len(pnls)} trades){flag}"
        )

    if not lines:
        return ""

    return "CONFIDENCE CALIBRATION (your stated vs actual):\n" + "\n".join(lines)
