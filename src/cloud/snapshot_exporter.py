from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from src.analytics.lesson_analytics import build_lesson_analytics, lesson_summary
from src.agents.lesson_canonicalizer import canonical_summary
from src.competition.evaluation import calculate_leaderboard
from src.competition.workload import summarize_workload
from src.config import Settings
from src.dashboard.contract import REQUIRED_LESSON_ANALYTICS_SNAPSHOT_KEYS, REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS
from src.logger import logger
from src.operations.update_manager import LiveUpdateManager
from src.storage.models import LessonRecord, ReflectionRecord, SharedLessonRecord, SignalRecord, TradeRecord
from src.trading.risk_automation.pending_order_view import pending_order_view
from src.storage.signal_repository import SignalAuditRepository
from src.storage.repository import ArenaRepository
from src.trading.paper_account import PaperAccount


def export_dashboard_snapshot(settings: Settings, repository: ArenaRepository) -> dict[str, Any]:
    latest_snapshot = repository.latest_market_snapshot()
    market = _market_payload(settings, latest_snapshot)
    btc_price = float(latest_snapshot.current_price) if latest_snapshot else float(market.get("current_price") or 0.0)
    generated_at = datetime.now(UTC)
    leaderboard = calculate_leaderboard(
        repository,
        [agent.id for agent in settings.agents],
        settings.accounts.initial_equity,
        btc_price,
    )
    leader = leaderboard[0].agent_id if leaderboard else None
    start_time, end_time = _competition_window(settings, repository)
    latest_cycle = _latest_cycle_timestamp(repository)
    status = _competition_status(generated_at, start_time, end_time, latest_cycle, settings.competition.poll_interval_seconds)
    agents = {
        agent.id: _account_summary(repository, agent.id, settings.accounts.initial_equity, btc_price)
        for agent in settings.agents
    }
    active_agent_ids = [agent.id for agent in settings.agents]
    open_positions = [
        _position_payload(position, btc_price)
        for position in repository.open_positions()
        if position.agent_id in active_agent_ids
    ]
    recent_trades = [_trade_payload(trade) for trade in repository.trades() if trade.agent_id in active_agent_ids][-50:]
    trade_history = _trade_history_summary(repository, [agent.id for agent in settings.agents])
    equity_curves = _equity_curves(repository, [agent.id for agent in settings.agents], settings.accounts.initial_equity, btc_price)
    drawdown_curves = _drawdown_curves(equity_curves)
    payload = {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "sync": {
            "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
            "source": "local-sqlite",
            "snapshot_path": settings.cloud_dashboard.snapshot_path,
        },
        "system_status": {
            "local_engine": "ONLINE_AT_EXPORT",
            "database": settings.paths.database,
            "latest_cycle_at": latest_cycle.isoformat().replace("+00:00", "Z") if latest_cycle else None,
        },
        "competition_status": status,
        "runner": _runner_payload(repository, status, settings.competition.poll_interval_seconds),
        "competition": {
            "name": settings.competition.name,
            "start_time": start_time.isoformat().replace("+00:00", "Z"),
            "end_time": end_time.isoformat().replace("+00:00", "Z") if end_time is not None else None,
            "duration_days": settings.competition.duration_days,
            "symbol": settings.competition.display_symbol,
            "continuous_mode": settings.competition.duration_days == 0,
            "uptime_seconds": (generated_at - start_time).total_seconds(),
            "weekly_target_pct": settings.competition.weekly_target_pct,
        },
        "leader": leader,
        "btc_price": btc_price,
        "market": market,
        "agents": agents,
        "open_positions": open_positions,
        "recent_trades": recent_trades,
        "trade_history_summary": trade_history,
        "equity_curves": equity_curves,
        "drawdown_curves": drawdown_curves,
        "leaderboard": [row.model_dump(mode="json") for row in leaderboard],
        "workload": _workload_payload(repository),
        "token_usage": _token_usage(repository, [agent.id for agent in settings.agents]),
        "api_costs": _api_costs(repository, [agent.id for agent in settings.agents]),
        "signal_audit_summary": SignalAuditRepository(repository).summary(),
        "rejected_signals_summary": _rejected_signals(repository),
        "reflections_summary": _reflections(repository),
        "downtime": _downtime_payload(repository),
        "strategy_diversity_metrics": _diversity_metrics(repository),
        "deployment": LiveUpdateManager(settings, repository).deployment_state(),
        "risk_automation": _risk_automation_payload(settings, repository),
        "lesson_analytics": _lesson_analytics_payload(repository),
    }
    return payload


def _risk_automation_payload(settings: Settings, repository: ArenaRepository) -> dict[str, Any]:
    pending = [
        pending_order_view(
            order_id=row.id,
            agent_id=row.agent_id,
            status=row.status,
            created_at=row.created_at,
            expires_at=row.expires_at,
            triggered_at=row.triggered_at,
            position_id=row.position_id,
            trigger_json=row.trigger_json,
            execution_signal_json=row.execution_signal_json,
        )
        for row in repository.list_pending_orders(status="PENDING", limit=100)
    ]
    cooldowns = [
        {
            "agent_id": row.agent_id,
            "reason": row.reason,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        }
        for row in repository.list_cooldowns(active_only=True)
    ]
    trailing = []
    position_sl_lookup = {p.id: p.stop_loss for p in repository.open_positions()}
    for row in repository.list_position_risk_states(limit=200):
        try:
            import json

            state = json.loads(row.state_json or "{}")
            config = json.loads(row.config_json or "{}")
        except Exception:
            state, config = {}, {}
        be_applied = bool(state.get("break_even_applied"))
        pos_sl = position_sl_lookup.get(row.position_id)
        trailing.append(
            {
                "position_id": row.position_id,
                "trailing_active": bool(state.get("trailing_active")),
                "trail_sl": state.get("trail_sl"),
                "break_even_applied": be_applied,
                "be_stop_price": float(pos_sl) if be_applied and pos_sl is not None else None,
                "max_hold_until": state.get("max_hold_until"),
                "config": config,
            }
        )
    failover_events = [
        {
            "agent_id": row.agent_id,
            "event_type": row.event_type,
            "from_provider": row.from_provider,
            "from_model": row.from_model,
            "to_provider": row.to_provider,
            "to_model": row.to_model,
            "message": row.message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in repository.failover_events(limit=50)
    ]
    notifications = [
        {
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "agent_id": row.agent_id,
            "event_type": row.event_type,
            "severity": row.severity,
            "message": row.message,
        }
        for row in repository.risk_notifications(limit=50)
    ]
    active_models = {}
    for agent in settings.agents:
        state = repository.get_agent_failover_state(agent.id)
        active_models[agent.id] = {
            "configured_model": agent.model,
            "active_model": state.active_model if state else agent.model,
            "using_fallback": bool(state.using_fallback) if state else False,
        }
    return {
        "pending_orders": pending,
        "pending_orders_count": len(pending),
        "cooldowns": cooldowns,
        "active_cooldown_count": len(cooldowns),
        "position_risk": trailing,
        "failover_events": failover_events,
        "notifications": notifications,
        "active_models": active_models,
    }


def write_dashboard_snapshot(settings: Settings, repository: ArenaRepository) -> Path:
    snapshot = export_dashboard_snapshot(settings, repository)
    contract_errors = validate_snapshot_contract(snapshot)
    if contract_errors:
        message = "dashboard snapshot contract failed: " + "; ".join(contract_errors)
        repository.save_health_check("dashboard_snapshot_contract", "FAIL", False, message[:1000])
        raise RuntimeError(message)
    path = settings.resolve_path(settings.cloud_dashboard.snapshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    repository.save_health_check("dashboard_snapshot_contract", "PASS", False, "Dashboard snapshot contract passed")
    logger.info("exported dashboard snapshot {}", path)
    return path


def validate_snapshot_contract(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_top_level = [
        "generated_at",
        "runner",
        "leaderboard",
        "signal_audit_summary",
        "rejected_signals_summary",
        "deployment",
        "risk_automation",
        "lesson_analytics",
    ]
    for key in required_top_level:
        if key not in snapshot:
            errors.append(f"missing top-level key {key}")
    audit = snapshot.get("signal_audit_summary")
    if not isinstance(audit, dict):
        errors.append("signal_audit_summary must be an object")
        return errors
    required_audit = [
        "accepted_signal_count",
        "rejected_signal_count",
        "acceptance_rate",
        "rejection_breakdown",
        "latest_accepted_signal",
        "latest_rejected_signal",
        "recent_accepted_signals",
        "recent_rejected_signals",
    ]
    for key in required_audit:
        if key not in audit:
            errors.append(f"missing signal_audit_summary.{key}")
    if not isinstance(audit.get("rejection_breakdown"), dict):
        errors.append("signal_audit_summary.rejection_breakdown must be an object")
    for key in ["recent_accepted_signals", "recent_rejected_signals"]:
        if not isinstance(audit.get(key), list):
            errors.append(f"signal_audit_summary.{key} must be a list")
    for key in ["accepted_signal_count", "rejected_signal_count"]:
        try:
            int(audit.get(key) or 0)
        except (TypeError, ValueError):
            errors.append(f"signal_audit_summary.{key} must be numeric")
    risk = snapshot.get("risk_automation")
    if not isinstance(risk, dict):
        errors.append("risk_automation must be an object")
    else:
        for key in REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS:
            if key not in risk:
                errors.append(f"missing risk_automation.{key}")
    lessons = snapshot.get("lesson_analytics")
    if not isinstance(lessons, dict):
        errors.append("lesson_analytics must be an object")
    else:
        for key in REQUIRED_LESSON_ANALYTICS_SNAPSHOT_KEYS:
            if key not in lessons:
                errors.append(f"missing lesson_analytics.{key}")
    return errors


def _competition_window(settings: Settings, repository: ArenaRepository) -> tuple[datetime, datetime | None]:
    official_start = repository.competition_start_time()
    start = _utc(official_start) if official_start else datetime.now(UTC)
    if settings.competition.duration_days == 0:
        return start, None
    return start, start + timedelta(days=settings.competition.duration_days)


def _competition_status(now: datetime, start_time: datetime, end_time: datetime | None, latest_cycle: datetime | None, poll_interval: int) -> str:
    if now < start_time:
        return "SCHEDULED"
    if end_time is not None and now >= end_time:
        return "COMPLETED"
    if not latest_cycle:
        return "PAUSED"
    return "RUNNING" if (now - latest_cycle).total_seconds() <= poll_interval * 2.5 else "PAUSED"


def _latest_cycle_timestamp(repository: ArenaRepository) -> datetime | None:
    checkpoint = repository.latest_checkpoint()
    if checkpoint:
        return _utc(checkpoint.created_at)
    snapshot = repository.latest_market_snapshot()
    return _utc(snapshot.created_at) if snapshot else None


def _account_summary(repository: ArenaRepository, agent_id: str, initial_equity: float, btc_price: float) -> dict[str, Any]:
    summary = PaperAccount(agent_id, initial_equity, repository).summary(btc_price)
    return {
        "equity": summary.equity,
        "roi_pct": ((summary.equity - initial_equity) / initial_equity * 100) if initial_equity else 0.0,
        "realized_pnl": summary.realized_pnl,
        "unrealized_pnl": summary.unrealized_pnl,
        "open_margin": summary.open_margin,
        "open_risk": summary.open_risk,
        "daily_pnl": summary.daily_pnl,
        "open_positions": len(summary.open_positions),
    }


def _market_payload(settings: Settings, snapshot: Any) -> dict[str, Any]:
    cached = _read_cached_candles(settings)
    if not snapshot:
        return {
            "symbol": settings.competition.display_symbol,
            "timeframe": settings.competition.timeframe,
            "candles": cached,
            "current_price": float(cached[-1]["close"]) if cached else 0.0,
        }
    payload = _safe_json(snapshot.payload_json, {})
    candles = payload.get("candles") if isinstance(payload, dict) else []
    if not isinstance(candles, list):
        candles = []
    merged = candles[-500:] if candles else cached
    current_price = snapshot.current_price if snapshot.current_price else (float(merged[-1]["close"]) if merged else 0.0)
    return {
        "symbol": snapshot.symbol,
        "timestamp": _iso(snapshot.timestamp),
        "current_price": current_price,
        "timeframe": payload.get("timeframe") if isinstance(payload, dict) else None,
        "regime": payload.get("regime") if isinstance(payload, dict) else None,
        "indicators": payload.get("indicators", {}) if isinstance(payload, dict) else {},
        "candles": merged,
    }


def _read_cached_candles(settings: Settings, limit: int = 500) -> list[dict[str, Any]]:
    path = settings.resolve_path(f"data/processed/btcusdt_{settings.competition.timeframe}.csv")
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path)
    except Exception:
        return []
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return []
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"]).tail(limit)
    return [
        {
            "timestamp": row.timestamp.isoformat().replace("+00:00", "Z"),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for row in frame.itertuples(index=False)
    ]


def _position_payload(position: Any, btc_price: float) -> dict[str, Any]:
    unrealized = 0.0
    if position.average_entry and position.notional and btc_price:
        if position.direction == "SHORT":
            unrealized = position.notional * ((position.average_entry - btc_price) / position.average_entry)
        else:
            unrealized = position.notional * ((btc_price - position.average_entry) / position.average_entry)
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
        "opened_at": _iso(position.opened_at),
        "closed_at": _iso(position.closed_at),
        "realized_pnl": position.realized_pnl,
        "unrealized_pnl": unrealized,
    }


def _trade_payload(trade: TradeRecord) -> dict[str, Any]:
    execution_timestamp = trade.execution_timestamp or trade.created_at
    decision_timestamp = trade.decision_timestamp or trade.created_at
    return {
        "id": trade.id,
        "agent_id": trade.agent_id,
        "position_id": trade.position_id,
        "created_at": _iso(trade.created_at),
        "decision_timestamp": _iso(decision_timestamp),
        "execution_timestamp": _iso(execution_timestamp),
        "displayed_timestamp": _iso(execution_timestamp),
        "action": trade.action,
        "direction": trade.direction,
        "leverage": trade.leverage,
        "margin": trade.margin,
        "notional": trade.notional,
        "entry": trade.entry,
        "exit_price": trade.exit_price,
        "realized_pnl": trade.realized_pnl,
        "config_version_id": trade.config_version_id,
        "config_hash": trade.config_hash,
        "code_version": trade.code_version,
        "notes": trade.notes,
    }


def _trade_history_summary(repository: ArenaRepository, agent_ids: list[str]) -> dict[str, Any]:
    summary = {}
    for agent_id in agent_ids:
        trades = repository.trades(agent_id)
        pnls = [trade.realized_pnl for trade in trades if trade.realized_pnl]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        summary[agent_id] = {
            "trade_count": len(trades),
            "closed_or_fee_events": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(pnls) if pnls else 0.0,
            "realized_pnl": sum(pnls),
        }
    return summary


def _equity_curves(repository: ArenaRepository, agent_ids: list[str], initial_equity: float, btc_price: float) -> dict[str, list[dict[str, Any]]]:
    curves: dict[str, list[dict[str, Any]]] = {}
    now = datetime.now(UTC)
    for agent_id in agent_ids:
        running = initial_equity
        points = [{"timestamp": _iso(now - timedelta(seconds=1)), "equity": initial_equity}]
        for trade in repository.trades(agent_id):
            running += float(trade.realized_pnl or 0)
            points.append({"timestamp": _iso(trade.execution_timestamp or trade.created_at), "equity": running})
        summary = PaperAccount(agent_id, initial_equity, repository).summary(btc_price)
        points.append({"timestamp": _iso(now), "equity": summary.equity})
        curves[agent_id] = points
    return curves


def _drawdown_curves(equity_curves: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    curves: dict[str, list[dict[str, Any]]] = {}
    for agent_id, points in equity_curves.items():
        peak = 0.0
        rows = []
        for point in points:
            equity = float(point["equity"])
            peak = max(peak, equity)
            drawdown = (equity - peak) / peak if peak else 0.0
            rows.append({"timestamp": point["timestamp"], "drawdown": drawdown})
        curves[agent_id] = rows
    return curves


def _workload_payload(repository: ArenaRepository) -> dict[str, Any]:
    summary = summarize_workload(repository, limit=50)
    latest = summary.get("latest") or {}
    return {
        "local_pct": latest.get("local_workload_pct", 0.0),
        "deepseek_pct": latest.get("deepseek_workload_pct", 0.0),
        "grok_pct": latest.get("grok_workload_pct", 0.0),
        "latest": latest,
        "averages": summary.get("averages", {}),
    }


def _runner_payload(repository: ArenaRepository, status: str, cycle_interval_seconds: int) -> dict[str, Any]:
    checkpoint = repository.latest_checkpoint()
    runner_state = repository.latest_runner_state()
    workload = repository.workload_cycles(limit=1)
    latest_workload = workload[0] if workload else None
    workload_payload = _safe_json(latest_workload.payload_json, {}) if latest_workload else {}
    last_duration = workload_payload.get("total_wall_time_seconds") if isinstance(workload_payload, dict) else None
    try:
        last_duration_seconds = float(last_duration)
    except (TypeError, ValueError):
        last_duration_seconds = None
    cycle_number = int(checkpoint.cycle_number) if checkpoint else 0
    last_completed_at = _utc(checkpoint.created_at) if checkpoint else None
    last_started_at = (
        last_completed_at - timedelta(seconds=last_duration_seconds)
        if last_completed_at and last_duration_seconds is not None
        else None
    )
    next_cycle_at = last_completed_at + timedelta(seconds=cycle_interval_seconds) if last_completed_at else None
    runner_status = "RUNNING" if status in {"RUNNING", "SCHEDULED"} else "OFFLINE" if status in {"PAUSED", "COMPLETED"} else "ERROR"
    if runner_state:
        state_phase = str(runner_state.phase or "").upper()
        state_status = str(runner_state.status or runner_status).upper()
        if state_phase and state_phase != "WAITING":
            return {
                "status": state_status,
                "cycle_number": int(runner_state.cycle_number or cycle_number),
                "phase": state_phase,
                "last_cycle_duration_seconds": last_duration_seconds,
                "cycle_interval_seconds": cycle_interval_seconds,
                "next_cycle_at": None,
                "last_cycle_started_at": _iso(runner_state.started_at),
                "current_cycle_started_at": _iso(runner_state.started_at),
                "state_updated_at": _iso(runner_state.updated_at),
                "message": runner_state.message,
                "total_cycles_completed": cycle_number,
            }
        if state_phase == "WAITING":
            next_cycle_at = _utc(runner_state.next_cycle_at) if runner_state.next_cycle_at else next_cycle_at
            runner_status = state_status
    return {
        "status": runner_status,
        "cycle_number": cycle_number,
        "phase": "WAITING" if runner_status == "RUNNING" else runner_status,
        "last_cycle_duration_seconds": last_duration_seconds,
        "cycle_interval_seconds": cycle_interval_seconds,
        "next_cycle_at": _iso(next_cycle_at),
        "last_cycle_started_at": _iso(last_started_at),
        "total_cycles_completed": cycle_number,
    }


def _token_usage(repository: ArenaRepository, agent_ids: list[str]) -> dict[str, Any]:
    return {agent_id: repository.response_usage(agent_id) for agent_id in agent_ids}


def _api_costs(repository: ArenaRepository, agent_ids: list[str]) -> dict[str, Any]:
    usage = _token_usage(repository, agent_ids)
    return {
        "by_agent": {agent_id: values.get("estimated_cost_usd", 0.0) for agent_id, values in usage.items()},
        "total": sum(values.get("estimated_cost_usd", 0.0) for values in usage.values()),
    }


def _downtime_payload(repository: ArenaRepository) -> dict[str, Any]:
    rows = repository.downtime_events(limit=20)
    recent = [
        {
            "started_at": _iso(row.started_at),
            "ended_at": _iso(row.ended_at),
            "duration_seconds": row.duration_seconds,
            "reason": row.reason,
            "missed_scheduled_cycle": "MISSED_SCHEDULED_CYCLE" in (row.reason or ""),
        }
        for row in rows
    ]
    missed = [row for row in recent if row["missed_scheduled_cycle"]]
    return {
        "recent": recent,
        "latest": recent[0] if recent else None,
        "latest_missed_cycle": missed[0] if missed else None,
        "missed_cycle_count_recent": len(missed),
    }


def _rejected_signals(repository: ArenaRepository) -> dict[str, Any]:
    with repository.session_factory() as session:
        rows = list(session.scalars(select(SignalRecord).order_by(SignalRecord.created_at.desc()).limit(200)))
    rejected = [row for row in rows if not row.accepted]
    return {
        "total_recent": len(rejected),
        "by_agent": _count_by(rejected, "agent_id"),
        "recent": [
            {
                "created_at": _iso(row.created_at),
                "agent_id": row.agent_id,
                "agent_name": row.agent_name or row.agent_id,
                "rejection_code": row.rejection_reason_code,
                "decision": row.decision,
                "action": row.action,
                "direction": row.direction,
                "confidence": row.confidence,
                "reasons": _safe_json(row.reasons_json, []),
                "message": row.rejection_reason_message,
            }
            for row in rejected[:25]
        ],
    }


def _reflections(repository: ArenaRepository) -> dict[str, Any]:
    with repository.session_factory() as session:
        rows = list(session.scalars(select(ReflectionRecord).order_by(ReflectionRecord.created_at.desc()).limit(50)))
        lessons = list(session.scalars(select(LessonRecord).order_by(LessonRecord.created_at.desc()).limit(50)))
    return {
        "count_recent": len(rows),
        "by_agent": _count_by(rows, "agent_id"),
        "recent": [
            {
                "created_at": _iso(row.created_at),
                "agent_id": row.agent_id,
                "summary": canonical_summary(row.content),
                "raw_text": row.content,
            }
            for row in rows[:20]
        ],
        "recent_lessons": [
            {
                "created_at": _iso(row.created_at),
                "agent_id": row.agent_id,
                "summary": canonical_summary(row.summary or row.raw_text or row.content),
                "raw_text": row.raw_text or row.content,
                "category": row.category,
                "sentiment": row.sentiment,
                "confidence": row.confidence,
                "impact": row.impact,
                "evidence_count": row.evidence_count,
                "last_updated": _iso(row.last_updated),
            }
            for row in lessons[:20]
        ],
    }


def _lesson_analytics_payload(repository: ArenaRepository) -> dict[str, Any]:
    try:
        with repository.session_factory() as session:
            lessons = pd.DataFrame(
                [
                    {
                        "id": row.id,
                        "agent_id": row.agent_id,
                        "created_at": _iso(row.created_at),
                        "content": row.content,
                        "raw_text": row.raw_text or row.content,
                        "summary": canonical_summary(row.summary or row.raw_text or row.content),
                        "category": row.category,
                        "sentiment": row.sentiment,
                        "confidence": row.confidence,
                        "impact": row.impact,
                        "evidence_count": row.evidence_count,
                    }
                    for row in session.scalars(select(LessonRecord).order_by(LessonRecord.created_at.desc()).limit(1000))
                ]
            )
            shared = pd.DataFrame(
                [
                    {
                        "id": row.id,
                        "source_agent": row.source_agent,
                        "market_regime": row.market_regime,
                        "lesson_text": row.lesson_text,
                        "raw_text": row.raw_text or row.lesson_text,
                        "summary": canonical_summary(row.summary or row.raw_text or row.lesson_text),
                        "category": row.category,
                        "sentiment": row.sentiment,
                        "impact": row.impact,
                        "evidence_count": row.evidence_count,
                        "lesson_type": row.lesson_type,
                        "confidence": row.confidence,
                        "sample_size": row.sample_size,
                        "win_rate": row.win_rate,
                        "profit_factor": row.profit_factor,
                        "usage_count": row.usage_count,
                        "promoted_at": _iso(row.promoted_at),
                    }
                    for row in session.scalars(select(SharedLessonRecord).order_by(SharedLessonRecord.promoted_at.desc()).limit(1000))
                ]
            )
            reflections = pd.DataFrame(
                [
                    {
                        "id": row.id,
                        "agent_id": row.agent_id,
                        "created_at": _iso(row.created_at),
                        "content": row.content,
                        "raw_text": row.content,
                        "summary": canonical_summary(row.content),
                    }
                    for row in session.scalars(select(ReflectionRecord).order_by(ReflectionRecord.created_at.desc()).limit(1000))
                ]
            )
            trades = pd.DataFrame(
                [
                    {"id": row.id, "agent_id": row.agent_id, "created_at": _iso(row.created_at), "realized_pnl": row.realized_pnl}
                    for row in session.scalars(select(TradeRecord).order_by(TradeRecord.created_at.desc()).limit(1000))
                ]
            )
        analytics = build_lesson_analytics(lessons, shared, reflections, trades, limit=100)
    except Exception as error:
        logger.warning("lesson analytics snapshot failed without blocking dashboard export: {}", error)
        analytics = {"follow": [], "avoid": []}
    follow = analytics.get("follow", [])
    avoid = analytics.get("avoid", [])
    return {
        "follow": follow[:100],
        "avoid": avoid[:100],
        "follow_summary": lesson_summary(follow),
        "avoid_summary": lesson_summary(avoid),
    }


def _diversity_metrics(repository: ArenaRepository) -> dict[str, Any]:
    metric = repository.latest_diversity_metric()
    if not metric:
        return {}
    return {
        "created_at": _iso(metric.created_at),
        "action_agreement_rate": metric.action_agreement_rate,
        "directional_agreement_rate": metric.directional_agreement_rate,
        "leverage_similarity": metric.leverage_similarity,
        "confidence_correlation": metric.confidence_correlation,
        "thesis_embedding_similarity": metric.thesis_embedding_similarity,
        "convergence_warning": bool(metric.convergence_warning),
        "shared_ratio_applied": metric.shared_ratio_applied,
    }


def _count_by(rows: list[Any], attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, attribute))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat().replace("+00:00", "Z") if value else None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
