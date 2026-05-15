from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select

from src.competition.evaluation import calculate_leaderboard
from src.competition.workload import summarize_workload
from src.config import Settings
from src.logger import logger
from src.storage.models import ReflectionRecord, SignalRecord, TradeRecord
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
    status = _competition_status(generated_at, end_time, latest_cycle, settings.competition.poll_interval_seconds)
    agents = {
        agent.id: _account_summary(repository, agent.id, settings.accounts.initial_equity, btc_price)
        for agent in settings.agents
    }
    open_positions = [_position_payload(position, btc_price) for position in repository.open_positions()]
    recent_trades = [_trade_payload(trade) for trade in repository.trades()[-50:]]
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
        "competition": {
            "name": settings.competition.name,
            "start_time": start_time.isoformat().replace("+00:00", "Z"),
            "end_time": end_time.isoformat().replace("+00:00", "Z"),
            "duration_days": settings.competition.duration_days,
            "symbol": settings.competition.display_symbol,
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
        "rejected_signals_summary": _rejected_signals(repository),
        "reflections_summary": _reflections(repository),
        "strategy_diversity_metrics": _diversity_metrics(repository),
    }
    return payload


def write_dashboard_snapshot(settings: Settings, repository: ArenaRepository) -> Path:
    snapshot = export_dashboard_snapshot(settings, repository)
    path = settings.resolve_path(settings.cloud_dashboard.snapshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    logger.info("exported dashboard snapshot {}", path)
    return path


def _competition_window(settings: Settings, repository: ArenaRepository) -> tuple[datetime, datetime]:
    candidates: list[datetime] = []
    first_snapshot = repository.first_market_snapshot()
    if first_snapshot:
        candidates.append(_utc(first_snapshot.created_at))
    trades = repository.trades()
    if trades:
        candidates.append(_utc(trades[0].created_at))
    start = min(candidates) if candidates else datetime.now(UTC)
    return start, start + timedelta(days=settings.competition.duration_days)


def _competition_status(now: datetime, end_time: datetime, latest_cycle: datetime | None, poll_interval: int) -> str:
    if now >= end_time:
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
    return {
        "id": trade.id,
        "agent_id": trade.agent_id,
        "position_id": trade.position_id,
        "created_at": _iso(trade.created_at),
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
            points.append({"timestamp": _iso(trade.created_at), "equity": running})
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


def _token_usage(repository: ArenaRepository, agent_ids: list[str]) -> dict[str, Any]:
    return {agent_id: repository.response_usage(agent_id) for agent_id in agent_ids}


def _api_costs(repository: ArenaRepository, agent_ids: list[str]) -> dict[str, Any]:
    usage = _token_usage(repository, agent_ids)
    return {
        "by_agent": {agent_id: values.get("estimated_cost_usd", 0.0) for agent_id, values in usage.items()},
        "total": sum(values.get("estimated_cost_usd", 0.0) for values in usage.values()),
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
                "decision": row.decision,
                "action": row.action,
                "reasons": _safe_json(row.reasons_json, []),
            }
            for row in rejected[:25]
        ],
    }


def _reflections(repository: ArenaRepository) -> dict[str, Any]:
    with repository.session_factory() as session:
        rows = list(session.scalars(select(ReflectionRecord).order_by(ReflectionRecord.created_at.desc()).limit(50)))
    return {
        "count_recent": len(rows),
        "by_agent": _count_by(rows, "agent_id"),
        "recent": [{"created_at": _iso(row.created_at), "agent_id": row.agent_id, "content": row.content[:500]} for row in rows[:20]],
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
