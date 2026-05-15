from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.competition.checkpoint import build_checkpoint_payload, checkpoint_payload, restore_from_checkpoint
from src.storage.models import PositionRecord


def test_checkpoint_payload_contains_state(repository) -> None:
    repository.add_or_update_position(
        PositionRecord(
            id="p1",
            agent_id="crypto-deepseek",
            symbol="BTC",
            direction="LONG",
            status="OPEN",
            leverage=5,
            margin=100,
            notional=500,
            average_entry=100,
            stop_loss=90,
            take_profit_1=115,
            take_profit_2=120,
        )
    )
    repository.save_lesson("crypto-deepseek", "Keep breakout entries selective.")
    payload = build_checkpoint_payload(repository, ["crypto-deepseek"], 10000, 100, 3)
    checkpoint_id = repository.save_checkpoint(3, "COMPLETED", payload)
    latest = repository.latest_checkpoint()

    assert latest is not None
    assert latest.id == checkpoint_id
    restored = checkpoint_payload(latest)
    assert restored["cycle_number"] == 3
    assert restored["open_positions"][0]["id"] == "p1"
    assert "crypto-deepseek" in restored["account_balances"]
    assert restored["memories"]["crypto-deepseek"]


def test_resume_records_downtime(repository) -> None:
    old_payload = {"cycle_number": 5}
    checkpoint_id = repository.save_checkpoint(5, "COMPLETED", old_payload)
    latest = repository.latest_checkpoint()
    assert latest is not None
    latest.created_at = datetime.now(UTC) - timedelta(seconds=120)
    with repository.session_factory() as session, session.begin():
        record = session.get(type(latest), checkpoint_id)
        record.created_at = latest.created_at.replace(tzinfo=None)

    cycle = restore_from_checkpoint(repository, repository.latest_checkpoint(), downtime_threshold_seconds=60)

    assert cycle == 5
    assert repository.downtime_events()
