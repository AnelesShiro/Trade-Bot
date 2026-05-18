from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.agents.lesson_canonicalizer import canonicalize_lesson, canonical_summary
from src.config import AgentSettings
from src.schemas import AgentSignal, ValidationResult
from src.storage.risk_repository import RiskAutomationRepositoryMixin
from src.storage.models import (
    AgentRecord,
    ApiRequestRecord,
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
    RunnerStateRecord,
    SharedLessonRecord,
    SignalRecord,
    StrategyProfileRecord,
    ToolCallRecord,
    TradeRecord,
    WorkloadComponentRecord,
    WorkloadCycleRecord,
)


class ArenaRepository(RiskAutomationRepositoryMixin):
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

    def save_api_request(self, payload: dict[str, Any]) -> int | None:
        with self.session_factory() as session, session.begin():
            previous = session.scalars(
                select(ApiRequestRecord)
                .where(ApiRequestRecord.agent_name == str(payload["agent_name"]))
                .order_by(ApiRequestRecord.timestamp.desc(), ApiRequestRecord.id.desc())
                .limit(1)
            ).first()
            prompt_chars = int(payload.get("prompt_characters") or 0)
            response_chars = int(payload.get("response_characters") or 0)
            total_tokens = int(payload.get("total_tokens") or 0)
            total_cost = float(payload.get("total_cost_usd") or 0.0)
            flags: list[str] = []
            prompt_ratio = None
            response_ratio = None
            cost_delta = None
            if previous:
                if previous.prompt_characters:
                    prompt_ratio = prompt_chars / previous.prompt_characters
                if previous.response_characters:
                    response_ratio = response_chars / previous.response_characters
                cost_delta = total_cost - float(previous.total_cost_usd or 0.0)
                if previous.total_cost_usd and total_cost > float(previous.total_cost_usd) * 3:
                    flags.append("cost_gt_3x_previous")
                if previous.total_tokens and total_tokens > int(previous.total_tokens) * 3:
                    flags.append("tokens_gt_3x_previous")
                if previous.prompt_characters and prompt_chars > int(previous.prompt_characters) * 2:
                    flags.append("prompt_size_gt_2x_previous")
            if int(payload.get("retry_count") or 0) > 0:
                flags.append("retry_count_gt_0")
            if float(payload.get("server_tool_cost_usd") or 0.0) > 0:
                flags.append("server_tool_cost_gt_0")
            record = ApiRequestRecord(
                timestamp=payload.get("timestamp") or datetime.now(UTC),
                cycle_number=payload.get("cycle_number"),
                agent_name=str(payload["agent_name"]),
                model_name=str(payload.get("model_name") or ""),
                actual_model_name=payload.get("actual_model_name"),
                request_type=str(payload.get("request_type") or "unknown"),
                prompt_tokens=int(payload.get("prompt_tokens") or 0),
                completion_tokens=int(payload.get("completion_tokens") or 0),
                total_tokens=total_tokens,
                reasoning_tokens=int(payload.get("reasoning_tokens") or 0),
                server_tool_calls=int(payload.get("server_tool_calls") or 0),
                server_tool_cost_usd=float(payload.get("server_tool_cost_usd") or 0.0),
                token_cost_usd=float(payload.get("token_cost_usd") or 0.0),
                total_cost_usd=total_cost,
                latency_ms=int(payload.get("latency_ms") or 0),
                retry_count=int(payload.get("retry_count") or 0),
                prompt_characters=prompt_chars,
                response_characters=response_chars,
                prompt_hash=str(payload.get("prompt_hash") or ""),
                response_hash=str(payload.get("response_hash") or ""),
                prompt_version=payload.get("prompt_version"),
                rulebook_version=payload.get("rulebook_version"),
                config_version=payload.get("config_version"),
                success=int(bool(payload.get("success", True))),
                error_message=payload.get("error_message"),
                prompt_size_ratio=prompt_ratio,
                response_size_ratio=response_ratio,
                memory_size_characters=int(payload.get("memory_size_characters") or 0),
                private_lessons_count=int(payload.get("private_lessons_count") or 0),
                shared_lessons_count=int(payload.get("shared_lessons_count") or 0),
                recent_trades_included=int(payload.get("recent_trades_included") or 0),
                reflection_characters=int(payload.get("reflection_characters") or 0),
                local_tool_invocation_count=int(payload.get("local_tool_invocation_count") or 0),
                cost_delta_usd=cost_delta,
                anomaly_flags_json=json.dumps(flags),
                cost_breakdown_json=json.dumps(payload.get("cost_breakdown") or {}, default=str),
            )
            session.add(record)
            session.flush()
            return int(record.id)

    def api_requests(self, limit: int = 1000, agent_name: str | None = None) -> list[ApiRequestRecord]:
        with self.session_factory() as session:
            stmt = select(ApiRequestRecord).order_by(ApiRequestRecord.timestamp.desc(), ApiRequestRecord.id.desc())
            if agent_name:
                stmt = stmt.where(ApiRequestRecord.agent_name == agent_name)
            stmt = stmt.limit(limit)
            return list(session.scalars(stmt))

    def save_signal(
        self,
        agent_id: str,
        signal: AgentSignal | None,
        validation: ValidationResult,
        raw_response: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        payload = signal.model_dump(mode="json") if signal else {}
        audit = metadata or {}
        with self.session_factory() as session, session.begin():
            record = SignalRecord(
                agent_id=agent_id,
                decision=signal.decision.value if signal else "PARSE_ERROR",
                action=signal.action.value if signal else "NONE",
                accepted=int(validation.accepted),
                reasons_json=json.dumps(validation.reasons),
                payload_json=json.dumps(payload),
                raw_response=raw_response,
                timestamp_utc=audit.get("timestamp_utc"),
                timestamp_local=audit.get("timestamp_local"),
                cycle_number=audit.get("cycle_number"),
                competition_time_pct=audit.get("competition_time_pct"),
                agent_name=audit.get("agent_name"),
                model_name=audit.get("model_name"),
                signal_status=audit.get("signal_status") or ("ACCEPTED" if validation.accepted else "REJECTED"),
                rejection_reason_code=audit.get("rejection_reason_code"),
                rejection_reason_message=audit.get("rejection_reason_message"),
                direction=audit.get("direction"),
                confidence=audit.get("confidence"),
                thesis=audit.get("thesis"),
                entry_price=audit.get("entry_price"),
                stop_loss=audit.get("stop_loss"),
                take_profit_1=audit.get("take_profit_1"),
                take_profit_2=audit.get("take_profit_2"),
                leverage=audit.get("leverage"),
                risk_pct=audit.get("risk_pct"),
                position_size_usdt=audit.get("position_size_usdt"),
                notional_usdt=audit.get("notional_usdt"),
                expected_rr=audit.get("expected_rr"),
                market_regime=audit.get("market_regime"),
                btc_price=audit.get("btc_price"),
                timeframe=audit.get("timeframe"),
                prompt_version=audit.get("prompt_version"),
                rulebook_version=audit.get("rulebook_version"),
                config_version=audit.get("config_version"),
                raw_model_output=audit.get("raw_model_output") or raw_response,
                parsed_json=audit.get("parsed_json"),
                normalized_signal_json=audit.get("normalized_signal_json"),
                validation_details_json=audit.get("validation_details_json"),
                execution_result_json=audit.get("execution_result_json"),
                token_usage=audit.get("token_usage"),
                api_cost_usd=audit.get("api_cost_usd"),
                latency_ms=audit.get("latency_ms"),
            )
            session.add(record)
            session.flush()
            return int(record.id)

    def update_signal_execution(self, signal_id: int, execution_result: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(SignalRecord, signal_id)
            if record:
                record.execution_result_json = json.dumps(execution_result, default=str)

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
            stmt = select(TradeRecord).order_by(func.coalesce(TradeRecord.execution_timestamp, TradeRecord.created_at).asc())
            if agent_id:
                stmt = stmt.where(TradeRecord.agent_id == agent_id)
            return list(session.scalars(stmt).all())

    def latest_trade_for_position(self, position_id: str) -> TradeRecord | None:
        with self.session_factory() as session:
            stmt = (
                select(TradeRecord)
                .where(TradeRecord.position_id == position_id)
                .order_by(func.coalesce(TradeRecord.execution_timestamp, TradeRecord.created_at).desc())
                .limit(1)
            )
            return session.scalars(stmt).first()

    def has_trade_note(self, position_id: str, note: str) -> bool:
        with self.session_factory() as session:
            stmt = select(TradeRecord).where(TradeRecord.position_id == position_id)
            return any(note in (trade.notes or "") for trade in session.scalars(stmt))

    def latest_stop_loss_same_direction(self, agent_id: str, direction: str, since: datetime | None = None) -> bool:
        if since and since.tzinfo is not None:
            since = since.astimezone(UTC).replace(tzinfo=None)
        with self.session_factory() as session:
            stmt = (
                select(TradeRecord)
                .where(
                    TradeRecord.agent_id == agent_id,
                    TradeRecord.direction == direction,
                    TradeRecord.notes.contains("stop_loss"),
                )
                .order_by(func.coalesce(TradeRecord.execution_timestamp, TradeRecord.created_at).desc())
                .limit(1)
            )
            if since:
                stmt = stmt.where(func.coalesce(TradeRecord.execution_timestamp, TradeRecord.created_at) > since)
            trade = session.scalars(stmt).first()
            return bool(trade)

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
        canonical = canonicalize_lesson(content, evidence_count=1)
        with self.session_factory() as session, session.begin():
            session.add(
                LessonRecord(
                    agent_id=agent_id,
                    content=canonical.summary,
                    raw_text=canonical.raw_text,
                    summary=canonical.summary,
                    category=canonical.category,
                    sentiment=canonical.sentiment,
                    confidence=canonical.confidence,
                    impact=canonical.impact,
                    evidence_count=canonical.evidence_count,
                    source_agents_json=json.dumps([agent_id]),
                    last_updated=datetime.now(UTC),
                )
            )

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
            return [canonical_summary(item.summary or item.raw_text or item.content) for item in session.scalars(stmt)]

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
        canonical = canonicalize_lesson(lesson_text, evidence_count=sample_size or 1)
        normalized = " ".join(canonical.summary.lower().split())
        with self.session_factory() as session, session.begin():
            existing = list(session.scalars(select(SharedLessonRecord)).all())
            for item in existing:
                item_summary = item.summary or canonical_summary(item.raw_text or item.lesson_text)
                if " ".join(item_summary.lower().split()) == normalized:
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
                lesson_text=canonical.summary,
                raw_text=canonical.raw_text,
                summary=canonical.summary,
                category=canonical.category,
                sentiment=canonical.sentiment,
                impact=canonical.impact,
                evidence_count=canonical.evidence_count,
                source_agents_json=json.dumps([source_agent]),
                last_updated=datetime.now(UTC),
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

    def competition_start_time(self) -> datetime | None:
        with self.session_factory() as session:
            marker = session.scalars(
                select(HealthCheckRecord)
                .where(HealthCheckRecord.component == "competition_start", HealthCheckRecord.status == "PASS")
                .order_by(HealthCheckRecord.created_at.asc())
                .limit(1)
            ).first()
            if marker:
                return marker.created_at

            candidates: list[datetime] = []
            workload = session.scalars(select(WorkloadCycleRecord).order_by(WorkloadCycleRecord.timestamp.asc()).limit(1)).first()
            checkpoint = session.scalars(select(CheckpointRecord).order_by(CheckpointRecord.created_at.asc()).limit(1)).first()
            snapshot = session.scalars(select(MarketSnapshotRecord).order_by(MarketSnapshotRecord.created_at.asc()).limit(1)).first()
            for record, field in [
                (workload, "timestamp"),
                (checkpoint, "created_at"),
                (snapshot, "created_at"),
            ]:
                if record:
                    candidates.append(getattr(record, field))
            return min(candidates) if candidates else None

    def ensure_competition_started(self, source: str) -> datetime:
        existing = self.competition_start_time()
        if existing:
            return existing
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            session.add(
                HealthCheckRecord(
                    created_at=now,
                    component="competition_start",
                    status="PASS",
                    critical=0,
                    message=f"Official arena start recorded by {source}",
                )
            )
        return now

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

    def save_runner_state(
        self,
        *,
        status: str,
        phase: str,
        cycle_number: int,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        next_cycle_at: datetime | None = None,
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(RunnerStateRecord, 1)
            values = {
                "updated_at": datetime.now(UTC),
                "status": status,
                "phase": phase,
                "cycle_number": cycle_number,
                "started_at": _naive_utc(started_at),
                "completed_at": _naive_utc(completed_at),
                "next_cycle_at": _naive_utc(next_cycle_at),
                "message": message[:4000],
                "payload_json": json.dumps(payload or {}, default=str),
            }
            if record:
                for key, value in values.items():
                    setattr(record, key, value)
            else:
                session.add(RunnerStateRecord(id=1, **values))

    def latest_runner_state(self) -> RunnerStateRecord | None:
        with self.session_factory() as session:
            return session.get(RunnerStateRecord, 1)

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


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
