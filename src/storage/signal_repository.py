from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from src.storage.models import SignalRecord
from src.storage.repository import ArenaRepository


class SignalAuditRepository:
    """Read-optimized accessors for model signal audit records."""

    def __init__(self, repository: ArenaRepository) -> None:
        self.repository = repository

    def latest(self, status: str, limit: int = 1) -> list[dict[str, Any]]:
        with self.repository.session_factory() as session:
            rows = list(
                session.scalars(
                    select(SignalRecord)
                    .where(
                        or_(
                            SignalRecord.signal_status == status,
                            SignalRecord.signal_status.is_(None) & (SignalRecord.accepted == (1 if status == "ACCEPTED" else 0)),
                        )
                    )
                    .order_by(SignalRecord.created_at.desc())
                    .limit(limit)
                )
            )
        return [_signal_to_dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.repository.session_factory() as session:
            accepted = session.scalar(select(func.count(SignalRecord.id)).where(or_(SignalRecord.signal_status == "ACCEPTED", SignalRecord.signal_status.is_(None) & (SignalRecord.accepted == 1)))) or 0
            rejected = session.scalar(select(func.count(SignalRecord.id)).where(or_(SignalRecord.signal_status == "REJECTED", SignalRecord.signal_status.is_(None) & (SignalRecord.accepted == 0)))) or 0
        return {"ACCEPTED": int(accepted), "REJECTED": int(rejected)}

    def rejection_breakdown(self, limit: int = 10) -> dict[str, int]:
        with self.repository.session_factory() as session:
            rows = session.execute(
                select(SignalRecord.rejection_reason_code, func.count(SignalRecord.id))
                .where(or_(SignalRecord.signal_status == "REJECTED", SignalRecord.signal_status.is_(None) & (SignalRecord.accepted == 0)))
                .group_by(SignalRecord.rejection_reason_code)
                .order_by(func.count(SignalRecord.id).desc())
                .limit(limit)
            ).all()
        return {str(code or "UNKNOWN"): int(count) for code, count in rows}

    def summary(self) -> dict[str, Any]:
        counts = self.counts()
        accepted = counts.get("ACCEPTED", 0)
        rejected = counts.get("REJECTED", 0)
        total = accepted + rejected
        return {
            "accepted_signal_count": accepted,
            "rejected_signal_count": rejected,
            "acceptance_rate": accepted / total if total else 0.0,
            "rejection_breakdown": self.rejection_breakdown(),
            "latest_accepted_signal": (self.latest("ACCEPTED", 1) or [None])[0],
            "latest_rejected_signal": (self.latest("REJECTED", 1) or [None])[0],
        }


def _signal_to_dict(row: SignalRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "timestamp_utc": row.timestamp_utc or _iso(row.created_at),
        "timestamp_local": row.timestamp_local,
        "cycle_number": row.cycle_number,
        "agent_name": row.agent_name or row.agent_id,
        "model_name": row.model_name,
        "signal_status": row.signal_status or ("ACCEPTED" if row.accepted else "REJECTED"),
        "rejection_reason_code": row.rejection_reason_code,
        "rejection_reason_message": row.rejection_reason_message,
        "decision": row.decision,
        "action": row.action,
        "direction": row.direction,
        "confidence": row.confidence,
        "thesis": row.thesis,
        "entry_price": row.entry_price,
        "stop_loss": row.stop_loss,
        "take_profit_1": row.take_profit_1,
        "take_profit_2": row.take_profit_2,
        "leverage": row.leverage,
        "risk_pct": row.risk_pct,
        "notional_usdt": row.notional_usdt,
        "expected_rr": row.expected_rr,
        "market_regime": row.market_regime,
        "btc_price": row.btc_price,
        "raw_snippet": (row.raw_model_output or row.raw_response or "")[:240],
        "validation_details": _safe_json(row.validation_details_json, {}),
        "execution_result": _safe_json(row.execution_result_json, {}),
    }


def _safe_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
