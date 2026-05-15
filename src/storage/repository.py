from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.config import AgentSettings
from src.schemas import AgentSignal, ValidationResult
from src.storage.models import (
    AgentRecord,
    BenchmarkRecord,
    CheckpointRecord,
    CompetitionResultRecord,
    ConfigVersionRecord,
    ControlCommandRecord,
    DailyMetricRecord,
    DowntimeEventRecord,
    DiversityMetricRecord,
    HealthCheckRecord,
    LessonRecord,
    LessonPromotionRecord,
    MarketSnapshotRecord,
    PositionRecord,
    PromptRecord,
    PromptVersionRecord,
    ReflectionRecord,
    ResponseRecord,
    SharedLessonRecord,
    SignalRecord,
    StrategyProfileRecord,
    ToolCallRecord,
    TradeRecord,
    WorkloadComponentRecord,
    WorkloadCycleRecord,
)


class ArenaRepository:
    """Database access layer for arena state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def upsert_agents(self, agents: Iterable[AgentSettings]) -> None:
        with self.session_factory() as session, session.begin():
            for agent in agents:
                existing = session.get(AgentRecord, agent.id)
                if existing:
                    existing.name = agent.name
                    existing.model = agent.model
                else:
                    session.add(AgentRecord(id=agent.id, name=agent.name, model=agent.model))

    def save_prompt(self, agent_id: str, prompt: str) -> int:
        with self.session_factory() as session, session.begin():
            record = PromptRecord(agent_id=agent_id, prompt=prompt)
            session.add(record)
            session.flush()
            return int(record.id)

    def save_tool_call(self, agent_id: str, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                ToolCallRecord(
                    agent_id=agent_id,
                    tool_name=tool_name,
                    arguments_json=json.dumps(arguments, default=str),
                    result_json=json.dumps(result, default=str),
                )
            )

    def save_response(
        self,
        agent_id: str,
        raw_response: str,
        prompt_id: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                ResponseRecord(
                    agent_id=agent_id,
                    raw_response=raw_response,
                    prompt_id=prompt_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost_usd=estimated_cost_usd,
                )
            )

    def save_signal(
        self,
        agent_id: str,
        signal: AgentSignal | None,
        validation: ValidationResult,
        raw_response: str,
    ) -> int:
        payload = signal.model_dump(mode="json") if signal else {}
        with self.session_factory() as session, session.begin():
            record = SignalRecord(
                agent_id=agent_id,
                decision=signal.decision.value if signal else "PARSE_ERROR",
                action=signal.action.value if signal else "NONE",
                accepted=int(validation.accepted),
                reasons_json=json.dumps(validation.reasons),
                payload_json=json.dumps(payload),
                raw_response=raw_response,
            )
            session.add(record)
            session.flush()
            return int(record.id)

    def open_positions(self, agent_id: str | None = None) -> list[PositionRecord]:
        with self.session_factory() as session:
            stmt = select(PositionRecord).where(PositionRecord.status.in_(["OPEN", "PARTIAL"]))
            if agent_id:
                stmt = stmt.where(PositionRecord.agent_id == agent_id)
            return list(session.scalars(stmt).all())

    def all_positions(self) -> list[PositionRecord]:
        with self.session_factory() as session:
            return list(session.scalars(select(PositionRecord)).all())

    def trades(self, agent_id: str | None = None) -> list[TradeRecord]:
        with self.session_factory() as session:
            stmt = select(TradeRecord).order_by(TradeRecord.created_at.asc())
            if agent_id:
                stmt = stmt.where(TradeRecord.agent_id == agent_id)
            return list(session.scalars(stmt).all())

    def latest_trade_for_position(self, position_id: str) -> TradeRecord | None:
        with self.session_factory() as session:
            stmt = (
                select(TradeRecord)
                .where(TradeRecord.position_id == position_id)
                .order_by(TradeRecord.created_at.desc())
                .limit(1)
            )
            return session.scalars(stmt).first()

    def has_trade_note(self, position_id: str, note: str) -> bool:
        with self.session_factory() as session:
            stmt = select(TradeRecord).where(TradeRecord.position_id == position_id)
            return any(note in (trade.notes or "") for trade in session.scalars(stmt))

    def latest_stop_loss_same_direction(self, agent_id: str, direction: str) -> bool:
        with self.session_factory() as session:
            stmt = (
                select(TradeRecord)
                .where(TradeRecord.agent_id == agent_id)
                .order_by(TradeRecord.created_at.desc())
                .limit(1)
            )
            trade = session.scalars(stmt).first()
            return bool(trade and trade.direction == direction and "stop_loss" in (trade.notes or ""))

    def add_or_update_position(self, position: PositionRecord) -> None:
        with self.session_factory() as session, session.begin():
            session.merge(position)

    def add_trade(self, trade: TradeRecord) -> None:
        with self.session_factory() as session, session.begin():
            session.add(trade)

    def get_position(self, position_id: str) -> PositionRecord | None:
        with self.session_factory() as session:
            return session.get(PositionRecord, position_id)

    def save_lesson(self, agent_id: str, content: str) -> None:
        with self.session_factory() as session, session.begin():
            session.add(LessonRecord(agent_id=agent_id, content=content))

    def save_reflection(self, agent_id: str, content: str) -> None:
        with self.session_factory() as session, session.begin():
            session.add(ReflectionRecord(agent_id=agent_id, content=content))

    def lessons(self, agent_id: str, limit: int = 8) -> list[str]:
        with self.session_factory() as session:
            stmt = (
                select(LessonRecord)
                .where(LessonRecord.agent_id == agent_id)
                .order_by(LessonRecord.created_at.desc())
                .limit(limit)
            )
            return [item.content for item in session.scalars(stmt)]

    def lesson_records(self, agent_id: str, limit: int = 200) -> list[LessonRecord]:
        with self.session_factory() as session:
            stmt = (
                select(LessonRecord)
                .where(LessonRecord.agent_id == agent_id)
                .order_by(LessonRecord.created_at.desc())
                .limit(limit)
            )
            return list(session.scalars(stmt))

    def save_shared_lesson(
        self,
        source_agent: str,
        market_regime: str,
        lesson_text: str,
        confidence: float,
        sample_size: int,
        win_rate: float,
        profit_factor: float,
        lesson_type: str = "best_practice",
    ) -> int | None:
        normalized = " ".join(lesson_text.lower().split())
        with self.session_factory() as session, session.begin():
            existing = list(session.scalars(select(SharedLessonRecord)).all())
            for item in existing:
                if " ".join(item.lesson_text.lower().split()) == normalized:
                    session.add(
                        LessonPromotionRecord(
                            source_agent=source_agent,
                            shared_lesson_id=item.id,
                            status="deduplicated",
                            reason="matching shared lesson already exists",
                        )
                    )
                    return None
            record = SharedLessonRecord(
                source_agent=source_agent,
                market_regime=market_regime,
                lesson_text=lesson_text,
                lesson_type=lesson_type,
                confidence=confidence,
                sample_size=sample_size,
                win_rate=win_rate,
                profit_factor=profit_factor,
            )
            session.add(record)
            session.flush()
            session.add(
                LessonPromotionRecord(
                    source_agent=source_agent,
                    shared_lesson_id=record.id,
                    status="promoted",
                    reason="passed quality gates",
                )
            )
            return int(record.id)

    def save_lesson_promotion(self, source_agent: str, lesson_id: int | None, status: str, reason: str) -> None:
        with self.session_factory() as session, session.begin():
            session.add(LessonPromotionRecord(source_agent=source_agent, lesson_id=lesson_id, status=status, reason=reason))

    def shared_lessons(self, exclude_source_agent: str | None = None, limit: int = 100) -> list[SharedLessonRecord]:
        with self.session_factory() as session:
            stmt = select(SharedLessonRecord).order_by(SharedLessonRecord.confidence.desc(), SharedLessonRecord.promoted_at.desc())
            if exclude_source_agent:
                stmt = stmt.where(SharedLessonRecord.source_agent != exclude_source_agent)
            return list(session.scalars(stmt.limit(limit)))

    def increment_shared_lesson_usage(self, lesson_ids: list[int]) -> None:
        if not lesson_ids:
            return
        with self.session_factory() as session, session.begin():
            for lesson_id in lesson_ids:
                record = session.get(SharedLessonRecord, lesson_id)
                if record:
                    record.usage_count += 1

    def save_strategy_profile(self, agent_id: str, profile: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            existing = session.get(StrategyProfileRecord, agent_id)
            payload = json.dumps(profile, default=str)
            if existing:
                existing.profile_json = payload
                existing.updated_at = datetime.now(UTC)
            else:
                session.add(StrategyProfileRecord(agent_id=agent_id, profile_json=payload))

    def strategy_profile(self, agent_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            record = session.get(StrategyProfileRecord, agent_id)
            return json.loads(record.profile_json) if record else None

    def save_diversity_metric(self, payload: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            session.add(DiversityMetricRecord(**payload))

    def latest_diversity_metric(self) -> DiversityMetricRecord | None:
        with self.session_factory() as session:
            stmt = select(DiversityMetricRecord).order_by(DiversityMetricRecord.created_at.desc()).limit(1)
            return session.scalars(stmt).first()

    def rejected_signal_count(self, agent_id: str) -> int:
        with self.session_factory() as session:
            stmt = select(SignalRecord).where(SignalRecord.agent_id == agent_id, SignalRecord.accepted == 0)
            return len(list(session.scalars(stmt).all()))

    def response_usage(self, agent_id: str) -> dict[str, float]:
        with self.session_factory() as session:
            stmt = select(ResponseRecord).where(ResponseRecord.agent_id == agent_id)
            responses = list(session.scalars(stmt).all())
            return {
                "input_tokens": float(sum(item.input_tokens for item in responses)),
                "output_tokens": float(sum(item.output_tokens for item in responses)),
                "estimated_cost_usd": float(sum(item.estimated_cost_usd for item in responses)),
                "requests": float(len(responses)),
            }

    def save_daily_metric(
        self,
        agent_id: str,
        equity: float,
        realized_pnl: float,
        unrealized_pnl: float,
        max_drawdown: float,
    ) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                DailyMetricRecord(
                    agent_id=agent_id,
                    day=datetime.now(UTC).date().isoformat(),
                    equity=equity,
                    realized_pnl=realized_pnl,
                    unrealized_pnl=unrealized_pnl,
                    max_drawdown=max_drawdown,
                )
            )

    def save_competition_result(self, winner_agent_id: str, payload: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                CompetitionResultRecord(
                    winner_agent_id=winner_agent_id,
                    payload_json=json.dumps(payload, default=str),
                )
            )

    def save_workload_cycle(self, cycle: dict[str, Any], components: list[dict[str, Any]]) -> int:
        with self.session_factory() as session, session.begin():
            record = WorkloadCycleRecord(
                local_workload_pct=cycle["local_workload_pct"],
                deepseek_workload_pct=cycle["deepseek_workload_pct"],
                grok_workload_pct=cycle["grok_workload_pct"],
                local_wall_time_seconds=cycle["local_wall_time_seconds"],
                local_cpu_time_seconds=cycle["local_cpu_time_seconds"],
                deepseek_latency_seconds=cycle["deepseek_latency_seconds"],
                grok_latency_seconds=cycle["grok_latency_seconds"],
                deepseek_tokens=int(cycle["deepseek_tokens"]),
                grok_tokens=int(cycle["grok_tokens"]),
                deepseek_cost_usd=cycle["deepseek_cost_usd"],
                grok_cost_usd=cycle["grok_cost_usd"],
                payload_json=json.dumps(cycle.get("payload", {}), default=str),
            )
            session.add(record)
            session.flush()
            for component in components:
                session.add(
                    WorkloadComponentRecord(
                        cycle_id=record.id,
                        owner=str(component["owner"]),
                        category=str(component["category"]),
                        metric_name=str(component["metric_name"]),
                        metric_value=float(component["metric_value"]),
                        details_json=json.dumps(component.get("details", {}), default=str),
                    )
                )
            return int(record.id)

    def save_market_snapshot(self, market_state: Any) -> int:
        with self.session_factory() as session, session.begin():
            record = MarketSnapshotRecord(
                symbol=market_state.symbol,
                timestamp=market_state.timestamp,
                current_price=float(market_state.current_price),
                payload_json=json.dumps(market_state.model_dump(mode="json"), default=str),
            )
            session.add(record)
            session.flush()
            return int(record.id)

    def first_market_snapshot(self) -> MarketSnapshotRecord | None:
        with self.session_factory() as session:
            stmt = select(MarketSnapshotRecord).order_by(MarketSnapshotRecord.created_at.asc()).limit(1)
            return session.scalars(stmt).first()

    def latest_market_snapshot(self) -> MarketSnapshotRecord | None:
        with self.session_factory() as session:
            stmt = select(MarketSnapshotRecord).order_by(MarketSnapshotRecord.created_at.desc()).limit(1)
            return session.scalars(stmt).first()

    def save_health_check(self, component: str, status: str, critical: bool, message: str) -> None:
        with self.session_factory() as session, session.begin():
            session.add(HealthCheckRecord(component=component, status=status, critical=int(critical), message=message))

    def latest_health_checks(self, limit: int = 100) -> list[HealthCheckRecord]:
        with self.session_factory() as session:
            stmt = select(HealthCheckRecord).order_by(HealthCheckRecord.created_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def save_prompt_version(self, prompt_hash: str, system_prompt_hash: str, rulebook_hash: str, prompt_preview: str) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                PromptVersionRecord(
                    prompt_hash=prompt_hash,
                    system_prompt_hash=system_prompt_hash,
                    rulebook_hash=rulebook_hash,
                    prompt_preview=prompt_preview[:1000],
                )
            )

    def save_config_version(self, version_hash: str, code_version: str, payload: dict[str, Any], source: str) -> int:
        with self.session_factory() as session, session.begin():
            for record in session.scalars(select(ConfigVersionRecord).where(ConfigVersionRecord.active == 1)):
                record.active = 0
            existing = session.scalars(
                select(ConfigVersionRecord)
                .where(ConfigVersionRecord.version_hash == version_hash, ConfigVersionRecord.code_version == code_version)
                .order_by(ConfigVersionRecord.created_at.desc())
                .limit(1)
            ).first()
            if existing:
                existing.active = 1
                existing.source = source
                existing.payload_json = json.dumps(payload, default=str)
                record_id = int(existing.id)
            else:
                record = ConfigVersionRecord(
                    version_hash=version_hash,
                    code_version=code_version,
                    payload_json=json.dumps(payload, default=str),
                    source=source,
                    active=1,
                )
                session.add(record)
                session.flush()
                record_id = int(record.id)
            return record_id

    def latest_config_version(self) -> ConfigVersionRecord | None:
        with self.session_factory() as session:
            stmt = select(ConfigVersionRecord).order_by(ConfigVersionRecord.created_at.desc()).limit(1)
            return session.scalars(stmt).first()

    def config_versions(self, limit: int = 50) -> list[ConfigVersionRecord]:
        with self.session_factory() as session:
            stmt = select(ConfigVersionRecord).order_by(ConfigVersionRecord.created_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def queue_control_command(self, command: str, payload: dict[str, Any] | None = None) -> int:
        with self.session_factory() as session, session.begin():
            record = ControlCommandRecord(command=command, payload_json=json.dumps(payload or {}, default=str))
            session.add(record)
            session.flush()
            return int(record.id)

    def pending_control_commands(self) -> list[ControlCommandRecord]:
        with self.session_factory() as session:
            stmt = select(ControlCommandRecord).where(ControlCommandRecord.status == "PENDING").order_by(ControlCommandRecord.created_at.asc())
            return list(session.scalars(stmt))

    def mark_control_command(self, command_id: int, status: str, result: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(ControlCommandRecord, command_id)
            if record:
                record.status = status
                record.result_json = json.dumps(result, default=str)
                record.processed_at = datetime.now(UTC)

    def save_benchmark(self, benchmark_name: str, start_price: float, current_price: float, payload: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                BenchmarkRecord(
                    benchmark_name=benchmark_name,
                    start_price=start_price,
                    current_price=current_price,
                    return_pct=(current_price - start_price) / start_price if start_price else 0.0,
                    payload_json=json.dumps(payload, default=str),
                )
            )

    def save_checkpoint(self, cycle_number: int, status: str, payload: dict[str, Any]) -> int:
        with self.session_factory() as session, session.begin():
            record = CheckpointRecord(cycle_number=cycle_number, status=status, payload_json=json.dumps(payload, default=str))
            session.add(record)
            session.flush()
            return int(record.id)

    def latest_checkpoint(self) -> CheckpointRecord | None:
        with self.session_factory() as session:
            stmt = select(CheckpointRecord).order_by(CheckpointRecord.created_at.desc()).limit(1)
            return session.scalars(stmt).first()

    def checkpoints(self, limit: int = 100) -> list[CheckpointRecord]:
        with self.session_factory() as session:
            stmt = select(CheckpointRecord).order_by(CheckpointRecord.created_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def save_downtime_event(self, started_at: datetime, ended_at: datetime, reason: str) -> None:
        if started_at.tzinfo is not None:
            started_at = started_at.replace(tzinfo=None)
        if ended_at.tzinfo is not None:
            ended_at = ended_at.replace(tzinfo=None)
        duration = max(0.0, (ended_at - started_at).total_seconds())
        with self.session_factory() as session, session.begin():
            session.add(DowntimeEventRecord(started_at=started_at, ended_at=ended_at, duration_seconds=duration, reason=reason))

    def downtime_events(self, limit: int = 100) -> list[DowntimeEventRecord]:
        with self.session_factory() as session:
            stmt = select(DowntimeEventRecord).order_by(DowntimeEventRecord.ended_at.desc()).limit(limit)
            return list(session.scalars(stmt))

    def workload_cycles(self, limit: int = 200) -> list[WorkloadCycleRecord]:
        with self.session_factory() as session:
            stmt = select(WorkloadCycleRecord).order_by(WorkloadCycleRecord.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt))

    def workload_components(self, limit: int = 1000) -> list[WorkloadComponentRecord]:
        with self.session_factory() as session:
            stmt = select(WorkloadComponentRecord).order_by(WorkloadComponentRecord.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt))


def new_position_id(agent_id: str) -> str:
    return f"{agent_id}-{uuid4().hex[:10]}"


def new_trade_id(agent_id: str) -> str:
    return f"trade-{agent_id}-{uuid4().hex[:10]}"
