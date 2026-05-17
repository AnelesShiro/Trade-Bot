from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class AgentRecord(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class PromptRecord(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    prompt: Mapped[str] = mapped_column(Text)


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    tool_name: Mapped[str] = mapped_column(String)
    arguments_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)


class ResponseRecord(Base):
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    raw_response: Mapped[str] = mapped_column(Text)
    prompt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("prompts.id"), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ApiRequestRecord(Base):
    __tablename__ = "api_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)
    cycle_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String, index=True)
    model_name: Mapped[str] = mapped_column(String)
    actual_model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    request_type: Mapped[str] = mapped_column(String)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    server_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    server_tool_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    token_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_characters: Mapped[int] = mapped_column(Integer, default=0)
    response_characters: Mapped[int] = mapped_column(Integer, default=0)
    prompt_hash: Mapped[str] = mapped_column(String)
    response_hash: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    rulebook_version: Mapped[str | None] = mapped_column(String, nullable=True)
    config_version: Mapped[str | None] = mapped_column(String, nullable=True)
    success: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_size_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_size_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_size_characters: Mapped[int] = mapped_column(Integer, default=0)
    private_lessons_count: Mapped[int] = mapped_column(Integer, default=0)
    shared_lessons_count: Mapped[int] = mapped_column(Integer, default=0)
    recent_trades_included: Mapped[int] = mapped_column(Integer, default=0)
    reflection_characters: Mapped[int] = mapped_column(Integer, default=0)
    local_tool_invocation_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_delta_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    cost_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    decision: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_json: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[str] = mapped_column(Text)
    timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_local: Mapped[str | None] = mapped_column(String, nullable=True)
    cycle_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competition_time_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_status: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason_code: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    leverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_size_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_rr: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String, nullable=True)
    btc_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    rulebook_version: Mapped[str | None] = mapped_column(String, nullable=True)
    config_version: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_model_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_signal_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PositionRecord(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String, default="BTC")
    direction: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OPEN")
    leverage: Mapped[float] = mapped_column(Float)
    margin: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    average_entry: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit_1: Mapped[float] = mapped_column(Float)
    take_profit_2: Mapped[float] = mapped_column(Float)
    dca_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    trades: Mapped[list["TradeRecord"]] = relationship(back_populates="position")


class TradeRecord(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    position_id: Mapped[str] = mapped_column(String, ForeignKey("positions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    action: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    leverage: Mapped[float] = mapped_column(Float)
    margin: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    entry: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    config_version_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("config_versions.id"), nullable=True)
    config_hash: Mapped[str] = mapped_column(String, default="")
    code_version: Mapped[str] = mapped_column(String, default="")

    position: Mapped[PositionRecord] = relationship(back_populates="trades")


class ReflectionRecord(Base):
    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    content: Mapped[str] = mapped_column(Text)


class LessonRecord(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    content: Mapped[str] = mapped_column(Text)


class SharedLessonRecord(Base):
    __tablename__ = "shared_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_agent: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    market_regime: Mapped[str] = mapped_column(String, default="unknown")
    lesson_text: Mapped[str] = mapped_column(Text)
    lesson_type: Mapped[str] = mapped_column(String, default="best_practice")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    promoted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class StrategyProfileRecord(Base):
    __tablename__ = "strategy_profiles"

    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    profile_json: Mapped[str] = mapped_column(Text)


class DiversityMetricRecord(Base):
    __tablename__ = "diversity_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    window_size: Mapped[int] = mapped_column(Integer, default=50)
    action_agreement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    directional_agreement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    leverage_similarity: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_correlation: Mapped[float] = mapped_column(Float, default=0.0)
    thesis_embedding_similarity: Mapped[float] = mapped_column(Float, default=0.0)
    convergence_warning: Mapped[int] = mapped_column(Integer, default=0)
    shared_ratio_applied: Mapped[float] = mapped_column(Float, default=0.30)


class LessonPromotionRecord(Base):
    __tablename__ = "lesson_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    source_agent: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    lesson_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("lessons.id"), nullable=True)
    shared_lesson_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("shared_lessons.id"), nullable=True)
    status: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text, default="")


class WorkloadCycleRecord(Base):
    __tablename__ = "workload_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    local_workload_pct: Mapped[float] = mapped_column(Float, default=0.0)
    deepseek_workload_pct: Mapped[float] = mapped_column(Float, default=0.0)
    grok_workload_pct: Mapped[float] = mapped_column(Float, default=0.0)
    local_wall_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    local_cpu_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    deepseek_latency_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    grok_latency_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    deepseek_tokens: Mapped[int] = mapped_column(Integer, default=0)
    grok_tokens: Mapped[int] = mapped_column(Integer, default=0)
    deepseek_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    grok_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class WorkloadComponentRecord(Base):
    __tablename__ = "workload_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[int] = mapped_column(Integer, ForeignKey("workload_cycles.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    owner: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    metric_name: Mapped[str] = mapped_column(String)
    metric_value: Mapped[float] = mapped_column(Float, default=0.0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class MarketSnapshotRecord(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    symbol: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    current_price: Mapped[float] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text)


class HealthCheckRecord(Base):
    __tablename__ = "health_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    component: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    critical: Mapped[int] = mapped_column(Integer, default=1)
    message: Mapped[str] = mapped_column(Text, default="")


class PromptVersionRecord(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    prompt_hash: Mapped[str] = mapped_column(String)
    system_prompt_hash: Mapped[str] = mapped_column(String)
    rulebook_hash: Mapped[str] = mapped_column(String)
    prompt_preview: Mapped[str] = mapped_column(Text, default="")


class ConfigVersionRecord(Base):
    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    version_hash: Mapped[str] = mapped_column(String, index=True)
    code_version: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="startup")
    active: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ControlCommandRecord(Base):
    __tablename__ = "control_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    command: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BenchmarkRecord(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    benchmark_name: Mapped[str] = mapped_column(String)
    start_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class CheckpointRecord(Base):
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    cycle_number: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="COMPLETED")
    payload_json: Mapped[str] = mapped_column(Text)


class DowntimeEventRecord(Base):
    __tablename__ = "downtime_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime] = mapped_column(DateTime)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")


class DailyMetricRecord(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    day: Mapped[str] = mapped_column(String)
    equity: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)


class CompetitionResultRecord(Base):
    __tablename__ = "competition_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    winner_agent_id: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)


def build_engine(database_url: str):
    if database_url.startswith("sqlite:///"):
        from pathlib import Path

        db_path = Path(database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def build_session_factory(database_url: str):
    return sessionmaker(bind=build_engine(database_url), expire_on_commit=False, future=True)


def create_schema(database_url: str) -> None:
    engine = build_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    except OperationalError as error:
        if "already exists" not in str(error).lower():
            raise
    if database_url.startswith("sqlite"):
        _migrate_sqlite(engine)


def _migrate_sqlite(engine) -> None:
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(trades)")).mappings().all()
        columns = {row["name"] for row in rows}
        additions = {
            "config_version_id": "INTEGER",
            "config_hash": "VARCHAR DEFAULT ''",
            "code_version": "VARCHAR DEFAULT ''",
        }
        for column, ddl in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE trades ADD COLUMN {column} {ddl}"))
        signal_rows = connection.execute(text("PRAGMA table_info(signals)")).mappings().all()
        signal_columns = {row["name"] for row in signal_rows}
        signal_additions = {
            "timestamp_utc": "VARCHAR",
            "timestamp_local": "VARCHAR",
            "cycle_number": "INTEGER",
            "competition_time_pct": "FLOAT",
            "agent_name": "VARCHAR",
            "model_name": "VARCHAR",
            "signal_status": "VARCHAR",
            "rejection_reason_code": "VARCHAR",
            "rejection_reason_message": "TEXT",
            "direction": "VARCHAR",
            "confidence": "FLOAT",
            "thesis": "TEXT",
            "entry_price": "FLOAT",
            "stop_loss": "FLOAT",
            "take_profit_1": "FLOAT",
            "take_profit_2": "FLOAT",
            "leverage": "FLOAT",
            "risk_pct": "FLOAT",
            "position_size_usdt": "FLOAT",
            "notional_usdt": "FLOAT",
            "expected_rr": "FLOAT",
            "market_regime": "VARCHAR",
            "btc_price": "FLOAT",
            "timeframe": "VARCHAR",
            "prompt_version": "VARCHAR",
            "rulebook_version": "VARCHAR",
            "config_version": "VARCHAR",
            "raw_model_output": "TEXT",
            "parsed_json": "TEXT",
            "normalized_signal_json": "TEXT",
            "validation_details_json": "TEXT",
            "execution_result_json": "TEXT",
            "token_usage": "TEXT",
            "api_cost_usd": "FLOAT",
            "latency_ms": "INTEGER",
        }
        for column, ddl in signal_additions.items():
            if column not in signal_columns:
                connection.execute(text(f"ALTER TABLE signals ADD COLUMN {column} {ddl}"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_signals_timestamp_utc ON signals(timestamp_utc)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_signals_cycle_number ON signals(cycle_number)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_signals_agent_name ON signals(agent_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_signals_signal_status ON signals(signal_status)"))
        api_rows = connection.execute(text("PRAGMA table_info(api_requests)")).mappings().all()
        api_columns = {row["name"] for row in api_rows}
        api_additions = {
            "prompt_size_ratio": "FLOAT",
            "actual_model_name": "VARCHAR",
            "response_size_ratio": "FLOAT",
            "memory_size_characters": "INTEGER DEFAULT 0",
            "private_lessons_count": "INTEGER DEFAULT 0",
            "shared_lessons_count": "INTEGER DEFAULT 0",
            "recent_trades_included": "INTEGER DEFAULT 0",
            "reflection_characters": "INTEGER DEFAULT 0",
            "local_tool_invocation_count": "INTEGER DEFAULT 0",
            "cost_delta_usd": "FLOAT",
            "anomaly_flags_json": "TEXT DEFAULT '[]'",
            "cost_breakdown_json": "TEXT DEFAULT '{}'",
        }
        for column, ddl in api_additions.items():
            if api_rows and column not in api_columns:
                connection.execute(text(f"ALTER TABLE api_requests ADD COLUMN {column} {ddl}"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_api_requests_agent_name ON api_requests(agent_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_api_requests_timestamp ON api_requests(timestamp)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_api_requests_cycle_number ON api_requests(cycle_number)"))
        _backfill_signal_audit_columns(connection)


def _backfill_signal_audit_columns(connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT id, agent_id, created_at, decision, action, accepted, reasons_json, payload_json, raw_response
            FROM signals
            WHERE signal_status IS NULL
               OR raw_model_output IS NULL
               OR direction IS NULL
               OR cycle_number IS NULL
               OR timestamp_local IS NULL
               OR timestamp_local = timestamp_utc
            LIMIT 5000
            """
        )
    ).mappings().all()
    checkpoints = [
        (_parse_db_datetime(row["created_at"]), int(row["cycle_number"] or 0))
        for row in connection.execute(text("SELECT created_at, cycle_number FROM checkpoints ORDER BY created_at ASC")).mappings().all()
    ]
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        try:
            reasons = json.loads(row["reasons_json"] or "[]")
        except Exception:
            reasons = []
        accepted = int(row["accepted"] or 0) == 1
        status = "ACCEPTED" if accepted else "REJECTED"
        rejection_message = "; ".join(str(reason) for reason in reasons)[:2000] if reasons else None
        created_at = _parse_db_datetime(row["created_at"])
        cycle_number = _cycle_for_signal(created_at, checkpoints)
        timestamp_utc = _utc_iso(created_at)
        timestamp_local = _local_iso(created_at)
        connection.execute(
            text(
                """
                UPDATE signals
                SET
                    timestamp_utc = :timestamp_utc,
                    timestamp_local = :timestamp_local,
                    cycle_number = coalesce(cycle_number, :cycle_number),
                    agent_name = coalesce(agent_name, :agent_name),
                    signal_status = coalesce(signal_status, :signal_status),
                    rejection_reason_code = coalesce(rejection_reason_code, :rejection_reason_code),
                    rejection_reason_message = coalesce(rejection_reason_message, :rejection_reason_message),
                    direction = coalesce(direction, :direction),
                    confidence = coalesce(confidence, :confidence),
                    thesis = coalesce(thesis, :thesis),
                    entry_price = coalesce(entry_price, :entry_price),
                    stop_loss = coalesce(stop_loss, :stop_loss),
                    take_profit_1 = coalesce(take_profit_1, :take_profit_1),
                    take_profit_2 = coalesce(take_profit_2, :take_profit_2),
                    leverage = coalesce(leverage, :leverage),
                    risk_pct = coalesce(risk_pct, :risk_pct),
                    position_size_usdt = coalesce(position_size_usdt, :position_size_usdt),
                    notional_usdt = coalesce(notional_usdt, :notional_usdt),
                    expected_rr = coalesce(expected_rr, :expected_rr),
                    raw_model_output = coalesce(raw_model_output, :raw_model_output),
                    parsed_json = coalesce(parsed_json, :parsed_json),
                    normalized_signal_json = coalesce(normalized_signal_json, :normalized_signal_json),
                    validation_details_json = coalesce(validation_details_json, :validation_details_json),
                    execution_result_json = coalesce(execution_result_json, :execution_result_json)
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "timestamp_utc": timestamp_utc,
                "timestamp_local": timestamp_local,
                "cycle_number": cycle_number,
                "agent_name": row["agent_id"],
                "signal_status": status,
                "rejection_reason_code": None if accepted else _legacy_rejection_code(reasons),
                "rejection_reason_message": rejection_message,
                "direction": payload.get("direction"),
                "confidence": payload.get("confidence"),
                "thesis": payload.get("thesis"),
                "entry_price": payload.get("entry"),
                "stop_loss": payload.get("stop_loss"),
                "take_profit_1": payload.get("take_profit_1"),
                "take_profit_2": payload.get("take_profit_2"),
                "leverage": payload.get("leverage"),
                "risk_pct": payload.get("account_risk_percent"),
                "position_size_usdt": payload.get("margin_used_usdt"),
                "notional_usdt": payload.get("notional_exposure_usdt"),
                "expected_rr": payload.get("risk_reward_to_tp2") or payload.get("risk_reward_to_tp1"),
                "raw_model_output": row["raw_response"],
                "parsed_json": json.dumps(payload, default=str),
                "normalized_signal_json": json.dumps(payload, default=str),
                "validation_details_json": json.dumps({"accepted": accepted, "reasons": reasons}, default=str),
                "execution_result_json": json.dumps({"executed": accepted and row["decision"] in {"PAPER_TRADE", "POSITION_UPDATE"} and row["action"] not in {"NONE", "HOLD"}}, default=str),
            },
        )


def _legacy_rejection_code(reasons: list[str]) -> str:
    text_value = " ".join(str(reason).lower() for reason in reasons)
    if "json" in text_value or "parse" in text_value or "schema" in text_value:
        return "PARSE_ERROR"
    if "missing" in text_value:
        return "MISSING_FIELD"
    if "direction" in text_value:
        return "INVALID_DIRECTION"
    if "action" in text_value:
        return "INVALID_ACTION"
    if "leverage" in text_value:
        return "LEVERAGE_LIMIT_EXCEEDED"
    if "position" in text_value:
        return "POSITION_LIMIT_EXCEEDED"
    if "risk" in text_value or "margin" in text_value:
        return "RISK_LIMIT_EXCEEDED"
    return "RULEBOOK_VIOLATION"


def _parse_db_datetime(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _cycle_for_signal(created_at: datetime, checkpoints: list[tuple[datetime, int]]) -> int | None:
    for checkpoint_time, cycle_number in checkpoints:
        if created_at <= checkpoint_time:
            return cycle_number
    return checkpoints[-1][1] if checkpoints else None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _local_iso(value: datetime) -> str:
    return value.astimezone(timezone(timedelta(hours=7))).isoformat()
