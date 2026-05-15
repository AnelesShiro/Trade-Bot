from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, text
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
    Base.metadata.create_all(engine)
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
