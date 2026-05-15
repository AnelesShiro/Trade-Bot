from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.storage.models import CheckpointRecord
from src.storage.repository import ArenaRepository
from src.trading.paper_account import PaperAccount


def build_checkpoint_payload(
    repository: ArenaRepository,
    agent_ids: list[str],
    initial_equity: float,
    current_price: float,
    cycle_number: int,
) -> dict[str, Any]:
    positions = [position_to_dict(position) for position in repository.all_positions()]
    open_positions = [position for position in positions if position.get("status") in {"OPEN", "PARTIAL"}]
    balances = {
        agent_id: PaperAccount(agent_id, initial_equity, repository).summary(current_price).model_dump(mode="json")
        for agent_id in agent_ids
    }
    watchlists = _watchlists(repository)
    lessons = {agent_id: repository.lessons(agent_id, limit=20) for agent_id in agent_ids}
    latest_snapshot = repository.first_market_snapshot()
    return {
        "checkpointed_at": datetime.now(UTC).isoformat(),
        "cycle_number": cycle_number,
        "current_price": current_price,
        "open_positions": open_positions,
        "all_positions": positions,
        "account_balances": balances,
        "pending_watchlists": watchlists,
        "memories": lessons,
        "latest_market_snapshot_id": latest_snapshot.id if latest_snapshot else None,
    }


def restore_from_checkpoint(repository: ArenaRepository, checkpoint: CheckpointRecord | None, downtime_threshold_seconds: int) -> int:
    if checkpoint is None:
        repository.save_health_check("resume", "PASS", False, "No checkpoint found; starting a fresh competition loop")
        return 0
    created = checkpoint.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    downtime = max(0.0, (now - created).total_seconds())
    if downtime >= downtime_threshold_seconds:
        repository.save_downtime_event(created, now, "automatic resume from latest checkpoint")
    repository.save_health_check("resume", "PASS", False, f"Restored checkpoint {checkpoint.id} from cycle {checkpoint.cycle_number}")
    return int(checkpoint.cycle_number)


def checkpoint_payload(record: CheckpointRecord | None) -> dict[str, Any]:
    if not record:
        return {}
    try:
        return json.loads(record.payload_json or "{}")
    except json.JSONDecodeError:
        return {}


def position_to_dict(position: Any) -> dict[str, Any]:
    return {
        "id": position.id,
        "agent_id": position.agent_id,
        "symbol": position.symbol,
        "direction": position.direction,
        "status": position.status,
        "leverage": position.leverage,
        "margin": position.margin,
        "notional": position.notional,
        "average_entry": position.average_entry,
        "stop_loss": position.stop_loss,
        "take_profit_1": position.take_profit_1,
        "take_profit_2": position.take_profit_2,
        "dca_count": position.dca_count,
        "opened_at": position.opened_at.isoformat() if position.opened_at else None,
        "closed_at": position.closed_at.isoformat() if position.closed_at else None,
        "realized_pnl": position.realized_pnl,
    }


def _watchlists(repository: ArenaRepository) -> list[dict[str, Any]]:
    with repository.session_factory() as session:
        from sqlalchemy import select

        from src.storage.models import SignalRecord

        rows = session.scalars(
            select(SignalRecord)
            .where(SignalRecord.decision == "WATCHLIST")
            .order_by(SignalRecord.created_at.desc())
            .limit(100)
        )
        return [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "created_at": row.created_at.isoformat(),
                "accepted": bool(row.accepted),
                "payload": _safe_json(row.payload_json),
            }
            for row in rows
        ]


def _safe_json(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
