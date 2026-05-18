from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from src.storage.models import (
    ApiFailoverEventRecord,
    AgentFailoverStateRecord,
    CooldownStateRecord,
    PendingOrderRecord,
    PositionRiskStateRecord,
    RiskNotificationRecord,
    SignalRecord,
    TradeRecord,
)
def new_pending_order_id(agent_id: str) -> str:
    return f"po-{agent_id}-{uuid4().hex[:10]}"


class RiskAutomationRepositoryMixin:
    def create_pending_order(
        self,
        agent_id: str,
        trigger_json: dict,
        execution_signal_json: dict,
        expires_at: datetime | None,
        source_signal_id: int | None,
    ) -> str:
        order_id = new_pending_order_id(agent_id)
        with self.session_factory() as session, session.begin():
            session.add(
                PendingOrderRecord(
                    id=order_id,
                    agent_id=agent_id,
                    status="PENDING",
                    trigger_json=json.dumps(trigger_json, default=str),
                    execution_signal_json=json.dumps(execution_signal_json, default=str),
                    expires_at=expires_at,
                    source_signal_id=source_signal_id,
                )
            )
        return order_id

    def list_pending_orders(self, status: str = "PENDING", agent_id: str | None = None, limit: int = 200) -> list[PendingOrderRecord]:
        with self.session_factory() as session:
            stmt = select(PendingOrderRecord).where(PendingOrderRecord.status == status).order_by(PendingOrderRecord.created_at.asc()).limit(limit)
            if agent_id:
                stmt = stmt.where(PendingOrderRecord.agent_id == agent_id)
            return list(session.scalars(stmt))

    def get_pending_order(self, order_id: str) -> PendingOrderRecord | None:
        with self.session_factory() as session:
            return session.get(PendingOrderRecord, order_id)

    def update_pending_order(
        self,
        order_id: str,
        *,
        status: str | None = None,
        triggered_at: datetime | None = None,
        position_id: str | None = None,
    ) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(PendingOrderRecord, order_id)
            if not record:
                return
            if status is not None:
                record.status = status
            if triggered_at is not None:
                record.triggered_at = triggered_at
            if position_id is not None:
                record.position_id = position_id

    def cancel_pending_order(self, order_id: str) -> bool:
        with self.session_factory() as session, session.begin():
            record = session.get(PendingOrderRecord, order_id)
            if not record or record.status != "PENDING":
                return False
            record.status = "CANCELLED"
            return True

    def upsert_position_risk_state(
        self,
        position_id: str,
        config_json: dict,
        state: dict,
        *,
        merge_state: bool = False,
    ) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(PositionRiskStateRecord, position_id)
            payload = json.dumps(config_json, default=str)
            state_payload = json.dumps(state, default=str)
            if record and merge_state:
                existing = json.loads(record.state_json or "{}")
                existing.update(state)
                state_payload = json.dumps(existing, default=str)
            if record:
                record.config_json = payload
                record.state_json = state_payload
                record.updated_at = datetime.now(UTC)
            else:
                session.add(
                    PositionRiskStateRecord(
                        position_id=position_id,
                        config_json=payload,
                        state_json=state_payload,
                    )
                )

    def get_position_risk_state(self, position_id: str) -> PositionRiskStateRecord | None:
        with self.session_factory() as session:
            return session.get(PositionRiskStateRecord, position_id)

    def list_position_risk_states(self, limit: int = 500) -> list[PositionRiskStateRecord]:
        with self.session_factory() as session:
            stmt = select(PositionRiskStateRecord).order_by(PositionRiskStateRecord.updated_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def active_cooldown(self, agent_id: str) -> CooldownStateRecord | None:
        with self.session_factory() as session:
            record = session.get(CooldownStateRecord, agent_id)
            if not record or not record.active:
                return None
            return record

    def list_cooldowns(self, active_only: bool = True) -> list[CooldownStateRecord]:
        with self.session_factory() as session:
            stmt = select(CooldownStateRecord).order_by(CooldownStateRecord.ends_at.asc())
            if active_only:
                stmt = stmt.where(CooldownStateRecord.active == 1)
            return list(session.scalars(stmt))

    def upsert_cooldown(self, agent_id: str, reason: str, ends_at: datetime, metadata: dict | None = None) -> None:
        is_new = False
        with self.session_factory() as session, session.begin():
            record = session.get(CooldownStateRecord, agent_id)
            payload = json.dumps(metadata or {}, default=str)
            if record:
                is_new = not bool(record.active)
                record.active = 1
                record.reason = reason
                record.started_at = datetime.now(UTC)
                record.ends_at = ends_at
                record.metadata_json = payload
            else:
                is_new = True
                session.add(
                    CooldownStateRecord(
                        agent_id=agent_id,
                        active=1,
                        reason=reason,
                        ends_at=ends_at,
                        metadata_json=payload,
                    )
                )
        if is_new:
            self.save_risk_notification(
                agent_id,
                "COOLDOWN_STARTED",
                f"Cooldown started: {reason}; ends at {ends_at.isoformat()}",
                severity="WARN",
                payload={"reason": reason, "ends_at": ends_at.isoformat(), **(metadata or {})},
            )

    def clear_cooldown(self, agent_id: str) -> bool:
        reason = ""
        with self.session_factory() as session, session.begin():
            record = session.get(CooldownStateRecord, agent_id)
            if not record:
                return False
            was_active = bool(record.active)
            reason = record.reason
            record.active = 0
        if was_active:
            self.save_risk_notification(
                agent_id,
                "COOLDOWN_ENDED",
                f"Cooldown ended: {reason}",
                severity="INFO",
                payload={"reason": reason},
            )
        return True

    def consecutive_losses(self, agent_id: str, count: int) -> int:
        with self.session_factory() as session:
            stmt = (
                select(TradeRecord)
                .where(TradeRecord.agent_id == agent_id, TradeRecord.exit_price.is_not(None))
                .order_by(func.coalesce(TradeRecord.execution_timestamp, TradeRecord.created_at).desc())
                .limit(count)
            )
            trades = list(session.scalars(stmt))
        streak = 0
        for trade in trades:
            if trade.realized_pnl < 0:
                streak += 1
            else:
                break
        return streak

    def signal_counts(self, agent_id: str, limit: int = 50) -> tuple[int, int]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(SignalRecord).where(SignalRecord.agent_id == agent_id).order_by(SignalRecord.created_at.desc()).limit(limit)
                )
            )
        total = len(rows)
        rejected = sum(1 for row in rows if not row.accepted)
        return total, rejected

    def recent_api_failures(self, agent_id: str, limit: int = 10) -> int:
        with self.session_factory() as session:
            from src.storage.models import ApiRequestRecord

            rows = list(
                session.scalars(
                    select(ApiRequestRecord)
                    .where(ApiRequestRecord.agent_name == agent_id)
                    .order_by(ApiRequestRecord.timestamp.desc())
                    .limit(limit)
                )
            )
        return sum(1 for row in rows if not row.success)

    def weekly_pnl(self, agent_id: str, days: int = 7) -> float:
        since = datetime.now(UTC) - timedelta(days=days)
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(TradeRecord).where(
                        TradeRecord.agent_id == agent_id,
                        func.coalesce(TradeRecord.execution_timestamp, TradeRecord.created_at) >= since,
                    )
                )
            )
        return float(sum(row.realized_pnl for row in rows))

    def save_failover_event(
        self,
        agent_id: str,
        event_type: str,
        *,
        from_provider: str,
        from_model: str,
        to_provider: str,
        to_model: str,
        message: str,
    ) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                ApiFailoverEventRecord(
                    agent_id=agent_id,
                    event_type=event_type,
                    from_provider=from_provider,
                    from_model=from_model,
                    to_provider=to_provider,
                    to_model=to_model,
                    message=message[:4000],
                )
            )
        severity = "WARN" if event_type == "FAILOVER" else "INFO"
        self.save_risk_notification(
            agent_id,
            f"API_{event_type}",
            f"{event_type}: {from_provider}/{from_model} -> {to_provider}/{to_model}",
            severity=severity,
            payload={
                "from_provider": from_provider,
                "from_model": from_model,
                "to_provider": to_provider,
                "to_model": to_model,
                "message": message[:1000],
            },
        )

    def failover_events(self, limit: int = 100) -> list[ApiFailoverEventRecord]:
        with self.session_factory() as session:
            stmt = select(ApiFailoverEventRecord).order_by(ApiFailoverEventRecord.created_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def save_risk_notification(
        self,
        agent_id: str,
        event_type: str,
        message: str,
        *,
        severity: str = "INFO",
        payload: dict | None = None,
    ) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                RiskNotificationRecord(
                    agent_id=agent_id,
                    event_type=event_type,
                    severity=severity,
                    message=message[:4000],
                    payload_json=json.dumps(payload or {}, default=str),
                )
            )

    def risk_notifications(self, limit: int = 100) -> list[RiskNotificationRecord]:
        with self.session_factory() as session:
            stmt = select(RiskNotificationRecord).order_by(RiskNotificationRecord.created_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def get_agent_failover_state(self, agent_id: str) -> AgentFailoverStateRecord | None:
        with self.session_factory() as session:
            return session.get(AgentFailoverStateRecord, agent_id)

    def upsert_agent_failover_state(
        self,
        agent_id: str,
        *,
        active_provider: str,
        active_model: str,
        primary_provider: str,
        primary_model: str,
        using_fallback: bool,
        primary_available: bool,
        fallback_index: int,
        last_retest_at: datetime | None = None,
    ) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(AgentFailoverStateRecord, agent_id)
            payload = {
                "active_provider": active_provider,
                "active_model": active_model,
                "primary_provider": primary_provider,
                "primary_model": primary_model,
                "using_fallback": 1 if using_fallback else 0,
                "primary_available": 1 if primary_available else 0,
                "fallback_index": fallback_index,
                "updated_at": datetime.now(UTC),
            }
            if last_retest_at is not None:
                payload["last_retest_at"] = last_retest_at
            if record:
                for key, value in payload.items():
                    setattr(record, key, value)
            else:
                session.add(AgentFailoverStateRecord(agent_id=agent_id, **payload))

    def pending_orders_count(self) -> int:
        with self.session_factory() as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(PendingOrderRecord).where(PendingOrderRecord.status == "PENDING")
                )
                or 0
            )

    def active_cooldown_count(self) -> int:
        with self.session_factory() as session:
            return int(
                session.scalar(select(func.count()).select_from(CooldownStateRecord).where(CooldownStateRecord.active == 1)) or 0
            )
