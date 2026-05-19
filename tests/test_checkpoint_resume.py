from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.competition.checkpoint import (
    audit_missed_scheduled_cycles,
    build_checkpoint_payload,
    checkpoint_payload,
    restore_from_checkpoint,
)
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


def test_resume_audits_missed_scheduled_cycle(repository) -> None:
    expected_at = datetime.now(UTC) - timedelta(minutes=90)
    resumed_at = datetime.now(UTC)
    repository.save_runner_state(
        status="RUNNING",
        phase="WAITING",
        cycle_number=12,
        completed_at=expected_at - timedelta(hours=1),
        next_cycle_at=expected_at,
        message="waiting before power loss",
    )

    result = audit_missed_scheduled_cycles(
        repository,
        cycle_interval_seconds=3600,
        grace_seconds=60,
        now=resumed_at,
    )

    assert result["missed_slots"] == 2
    assert result["recorded"] is True
    assert "MISSED_SCHEDULED_CYCLE" in repository.downtime_events(limit=1)[0].reason
    assert repository.risk_notifications(limit=1)[0].event_type == "MISSED_SCHEDULED_CYCLE"
