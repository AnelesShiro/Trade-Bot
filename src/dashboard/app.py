from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

try:
    from streamlit_lightweight_charts import renderLightweightCharts
except Exception:
    renderLightweightCharts = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_settings, safe_canary, safe_features  # noqa: E402
from src.dashboard.components.cycle_status_bar import render_cycle_status  # noqa: E402
from src.dashboard.tabs.accepted_signals import render_accepted_signals_tab  # noqa: E402
from src.dashboard.tabs.api_failover import render_api_failover_tab  # noqa: E402
from src.dashboard.tabs.pending_orders import render_pending_orders_tab  # noqa: E402
from src.dashboard.tabs.rejected_signals import render_rejected_signals_tab  # noqa: E402
from src.dashboard.tabs.risk_automation import render_risk_automation_tab  # noqa: E402
from src.market.indicators import ema, rsi  # noqa: E402
from src.operations.update_manager import LiveUpdateManager  # noqa: E402
from src.storage.models import build_session_factory, create_schema  # noqa: E402
from src.storage.repository import ArenaRepository  # noqa: E402


st.set_page_config(
    page_title="Crypto Paper Trading Arena",
    page_icon="BTC",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = load_settings()
create_schema(settings.database_url)
LOCAL_TZ = ZoneInfo(os.getenv("ARENA_DISPLAY_TIMEZONE", "Asia/Bangkok"))
db_path = settings.resolve_path(settings.paths.database)
cloud_snapshot_path = settings.resolve_path(settings.cloud_dashboard.snapshot_path)
signals_path = settings.resolve_path(settings.paths.signals)
ledger_path = settings.resolve_path(settings.paths.ledger)
evaluation_path = settings.resolve_path(settings.paths.evaluation)
rulebook_path = settings.resolve_path(settings.paths.rulebook)
initial_equity = float(settings.accounts.initial_equity)
agent_ids = [agent.id for agent in settings.agents]
agent_names = {agent.id: agent.name for agent in settings.agents}
agent_models = {agent.id: agent.model for agent in settings.agents}
challenger_agent_id = agent_ids[1] if len(agent_ids) > 1 else (agent_ids[0] if agent_ids else "")
challenger_label = agent_names.get(challenger_agent_id, "Challenger")
challenger_short_label = challenger_label.replace("Crypto ", "") or "Challenger"

CSS = """
<style>
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 100%; }
    [data-testid="stMetricValue"] { font-size: 1.55rem; }
    .arena-banner {
        border: 1px solid rgba(148, 163, 184, .25);
        border-radius: 8px;
        padding: 14px 16px;
        background: rgba(15, 23, 42, .18);
        margin-bottom: 12px;
    }
    .chart-shell {
        border: 1px solid rgba(148, 163, 184, .25);
        border-radius: 8px;
        padding: 8px;
        background: #05070a;
        margin: 8px 0 16px 0;
    }
    .chart-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        padding: 4px 4px 10px 4px;
        color: #94a3b8;
        font-size: .9rem;
    }
    .status-running { color: #22c55e; font-weight: 700; }
    .status-paused { color: #f59e0b; font-weight: 700; }
    .status-completed { color: #38bdf8; font-weight: 700; }
    .status-error { color: #ef4444; font-weight: 700; }
    .positive { color: #22c55e; font-weight: 700; }
    .negative { color: #ef4444; font-weight: 700; }
    .muted { color: #94a3b8; }
    .small-note { font-size: .86rem; color: #94a3b8; }
    div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def utc_now() -> datetime:
    return datetime.now(UTC)


def fmt_time(value: datetime | pd.Timestamp | None, include_tz: bool = True) -> str:
    if value is None or pd.isna(value):
        return "none yet"
    ts = value.to_pydatetime() if isinstance(value, pd.Timestamp) else value
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    local = ts.astimezone(LOCAL_TZ)
    suffix = f" {LOCAL_TZ.key}" if include_tz and hasattr(LOCAL_TZ, "key") else ""
    return local.strftime("%Y-%m-%d %H:%M:%S") + suffix


def fmt_short_time(value: datetime | pd.Timestamp | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    ts = value.to_pydatetime() if isinstance(value, pd.Timestamp) else value
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(LOCAL_TZ).strftime("%m-%d %H:%M")


def fmt_money(value: float | int | None) -> str:
    return f"{float(value or 0):,.2f} USDT"


def fmt_pct(value: float | int | None) -> str:
    return f"{float(value or 0) * 100:.2f}%"


def human_duration(delta: timedelta | pd.Timedelta | None) -> str:
    if delta is None or pd.isna(delta):
        return "-"
    seconds = max(0, int(delta.total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@st.cache_data(ttl=3)
def read_table(name: str, database: str) -> pd.DataFrame:
    path = Path(database)
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as connection:
        try:
            frame = pd.read_sql_query(f"select * from {name}", connection)
        except Exception:
            return pd.DataFrame()
    for column in frame.columns:
        if column.endswith("_at") or column in {"created_at", "opened_at", "closed_at", "timestamp", "timestamp_utc", "timestamp_local", "day"}:
            parsed = pd.to_datetime(frame[column], utc=True, errors="coerce")
            if parsed.notna().any():
                frame[column] = parsed.dt.tz_convert(LOCAL_TZ)
    return frame


@st.cache_data(ttl=5)
def read_text(path_value: str) -> str:
    path = Path(path_value)
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


@st.cache_data(ttl=5)
def read_csv(path_value: str) -> pd.DataFrame:
    path = Path(path_value)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def queue_control_command(database: str, command: str, payload: dict[str, Any] | None = None) -> int:
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            create table if not exists control_commands (
                id integer primary key autoincrement,
                created_at datetime,
                command varchar,
                status varchar default 'PENDING',
                payload_json text default '{}',
                result_json text default '{}',
                processed_at datetime
            )
            """
        )
        cursor = connection.execute(
            "insert into control_commands (created_at, command, status, payload_json) values (?, ?, 'PENDING', ?)",
            (utc_now().isoformat(), command, json.dumps(payload or {})),
        )
        connection.commit()
        return int(cursor.lastrowid)


@st.cache_data(ttl=25)
def fetch_ohlcv(timeframe: str, limit: int = 900) -> pd.DataFrame:
    cache_dir = PROJECT_ROOT / "data" / "processed"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"btcusdt_{timeframe}.csv"
    try:
        import ccxt

        exchange_cls = getattr(ccxt, settings.market.exchange)
        exchange = exchange_cls({"enableRateLimit": True})
        rows = exchange.fetch_ohlcv(settings.competition.symbol, timeframe=timeframe, limit=limit)
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        frame.to_csv(cache_path, index=False)
        return frame
    except Exception:
        if cache_path.exists():
            frame = pd.read_csv(cache_path)
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
            return frame.dropna(subset=["timestamp"])
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


def safe_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else fallback
    except Exception:
        return fallback


def signal_payloads(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty or "payload_json" not in signals.columns:
        return signals.copy()
    rows = []
    for record in signals.to_dict("records"):
        payload = safe_json(record.get("payload_json"), {})
        if isinstance(payload, dict):
            record.update({f"payload_{key}": value for key, value in payload.items()})
        rows.append(record)
    return pd.DataFrame(rows)


def position_unrealized(row: pd.Series, price: float | None) -> float:
    if price is None or pd.isna(price):
        return 0.0
    entry = float(row.get("average_entry") or 0)
    notional = float(row.get("notional") or 0)
    if entry <= 0 or notional <= 0:
        return 0.0
    if str(row.get("direction", "")).upper() == "SHORT":
        return notional * ((entry - price) / entry)
    return notional * ((price - entry) / entry)


def position_risk_pct(row: pd.Series) -> float:
    entry = float(row.get("average_entry") or 0)
    stop = float(row.get("stop_loss") or 0)
    notional = float(row.get("notional") or 0)
    return abs(notional * ((entry - stop) / entry)) / initial_equity if entry and stop and notional else 0.0


def liquidation_estimate(row: pd.Series) -> float:
    entry = float(row.get("average_entry") or 0)
    leverage = float(row.get("leverage") or 1)
    if entry <= 0 or leverage <= 0:
        return 0.0
    buffer = 1 / leverage
    return entry * (1 - buffer) if str(row.get("direction", "")).upper() == "LONG" else entry * (1 + buffer)


def build_position_view(positions: pd.DataFrame, current_price: float | None) -> pd.DataFrame:
    if positions.empty:
        return pd.DataFrame()
    frame = positions.copy()
    frame["current_price"] = current_price
    frame["unrealized_pnl"] = frame.apply(lambda row: position_unrealized(row, current_price), axis=1)
    frame["risk_pct"] = frame.apply(position_risk_pct, axis=1)
    frame["liq_estimate"] = frame.apply(liquidation_estimate, axis=1)
    now = pd.Timestamp(utc_now())
    frame["holding_time"] = frame["opened_at"].apply(lambda value: human_duration(now - value if pd.notna(value) else None))
    return frame


def equity_curve(trades: pd.DataFrame, positions_view: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for agent_id in agent_ids:
        rows.append({"agent_id": agent_id, "timestamp": pd.Timestamp(utc_now()) - pd.Timedelta(seconds=1), "equity": initial_equity})
        running = initial_equity
        if not trades.empty:
            for _, trade in trades[trades["agent_id"] == agent_id].sort_values("created_at").iterrows():
                running += float(trade.get("realized_pnl") or 0)
                rows.append({"agent_id": agent_id, "timestamp": trade.get("created_at"), "equity": running})
        if not positions_view.empty:
            unrealized = float(
                positions_view[
                    (positions_view["agent_id"] == agent_id) & (positions_view["status"].isin(["OPEN", "PARTIAL"]))
                ]["unrealized_pnl"].sum()
            )
            rows.append({"agent_id": agent_id, "timestamp": pd.Timestamp(utc_now()), "equity": running + unrealized})
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.dropna(subset=["timestamp"]).sort_values(["agent_id", "timestamp"])


def drawdown_curve(curve: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for agent_id, group in curve.groupby("agent_id"):
        group = group.sort_values("timestamp").copy()
        group["peak"] = group["equity"].cummax()
        group["drawdown"] = (group["equity"] - group["peak"]) / group["peak"]
        frames.append(group[["agent_id", "timestamp", "drawdown"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def daily_returns(curve: pd.DataFrame) -> pd.DataFrame:
    if curve.empty:
        return pd.DataFrame()
    frame = curve.copy()
    frame["day"] = frame["timestamp"].dt.date
    daily = frame.sort_values("timestamp").groupby(["agent_id", "day"], as_index=False).tail(1)
    daily["daily_return"] = daily.groupby("agent_id")["equity"].pct_change().fillna(0)
    return daily[["agent_id", "day", "daily_return"]]


def api_usage(responses: pd.DataFrame) -> pd.DataFrame:
    if responses.empty:
        return pd.DataFrame(columns=["agent_id", "requests", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd"])
    frame = responses.copy()
    for column in ["input_tokens", "output_tokens", "estimated_cost_usd"]:
        frame[column] = pd.to_numeric(frame.get(column, 0), errors="coerce").fillna(0)
    grouped = frame.groupby("agent_id", as_index=False).agg(
        requests=("id", "count"),
        input_tokens=("input_tokens", "sum"),
        output_tokens=("output_tokens", "sum"),
        estimated_cost_usd=("estimated_cost_usd", "sum"),
    )
    grouped["total_tokens"] = grouped["input_tokens"] + grouped["output_tokens"]
    return grouped


def metrics_table(trades: pd.DataFrame, signals: pd.DataFrame, responses: pd.DataFrame, positions_view: pd.DataFrame, curve: pd.DataFrame) -> pd.DataFrame:
    usage = api_usage(responses).set_index("agent_id") if not responses.empty else pd.DataFrame()
    dd = drawdown_curve(curve)
    rows = []
    for agent_id in agent_ids:
        pnls = []
        if not trades.empty:
            pnls = [float(v) for v in pd.to_numeric(trades[trades["agent_id"] == agent_id]["realized_pnl"], errors="coerce").fillna(0) if v != 0]
        realized = sum(pnls)
        unrealized = 0.0
        if not positions_view.empty:
            unrealized = float(
                positions_view[
                    (positions_view["agent_id"] == agent_id) & (positions_view["status"].isin(["OPEN", "PARTIAL"]))
                ]["unrealized_pnl"].sum()
            )
        equity = initial_equity + realized + unrealized
        wins = [p for p in pnls if p > 0]
        losses = [abs(p) for p in pnls if p < 0]
        returns = [p / initial_equity for p in pnls]
        sharpe = mean(returns) / pstdev(returns) if len(returns) > 1 and pstdev(returns) else 0.0
        sortino = 0.0
        downside = [r for r in returns if r < 0]
        if returns and not downside:
            sortino = float(mean(returns) > 0)
        elif len(downside) > 1 and pstdev(downside):
            sortino = mean(returns) / pstdev(downside)
        max_dd = abs(float(dd[dd["agent_id"] == agent_id]["drawdown"].min())) if not dd.empty and not dd[dd["agent_id"] == agent_id].empty else 0.0
        rejected = 0
        total_signals = 0
        if not signals.empty:
            agent_signals = signals[signals["agent_id"] == agent_id]
            total_signals = len(agent_signals)
            rejected = int((pd.to_numeric(agent_signals["accepted"], errors="coerce").fillna(0) == 0).sum())
        compliance = 1 - (rejected / total_signals) if total_signals else 1.0
        cost = float(usage.loc[agent_id, "estimated_cost_usd"]) if not usage.empty and agent_id in usage.index else 0.0
        tokens = int(usage.loc[agent_id, "total_tokens"]) if not usage.empty and agent_id in usage.index else 0
        requests = int(usage.loc[agent_id, "requests"]) if not usage.empty and agent_id in usage.index else 0
        profit_per_cost = realized / cost if cost > 0 else 0.0
        score = (
            0.40 * max(0, min(1, (equity - initial_equity) / initial_equity / 0.10))
            + 0.20 * max(0, min(1, sharpe / 2 if math.isfinite(sharpe) else 0))
            + 0.20 * max(0, min(1, 1 - max_dd / 0.10))
            + 0.10 * compliance
            + 0.10 * (max(0, min(1, profit_per_cost / 100)) if cost else 1)
        )
        rows.append(
            {
                "agent_id": agent_id,
                "agent": agent_names.get(agent_id, agent_id),
                "model": agent_models.get(agent_id, ""),
                "current_equity": equity,
                "total_return_pct": (equity - initial_equity) / initial_equity,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "max_drawdown": max_dd,
                "win_rate": len(wins) / len(pnls) if pnls else 0.0,
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "profit_factor": sum(wins) / sum(losses) if losses else float(sum(wins) > 0),
                "rule_compliance": compliance,
                "rejected_signals": rejected,
                "token_usage": tokens,
                "requests": requests,
                "estimated_api_cost": cost,
                "profit_per_api_dollar": profit_per_cost,
                "score": score,
            }
        )
    return pd.DataFrame(rows).sort_values("score", ascending=False)


def competition_times(
    health_checks: pd.DataFrame,
    checkpoints: pd.DataFrame,
    workload_cycles: pd.DataFrame,
) -> tuple[datetime, datetime]:
    start = pd.NaT
    if not health_checks.empty and {"component", "created_at"}.issubset(health_checks.columns):
        markers = health_checks[health_checks["component"] == "competition_start"]
        if not markers.empty:
            start = pd.to_datetime(markers["created_at"], utc=True, errors="coerce").min()
    if pd.isna(start):
        candidates = []
        for frame, column in [(workload_cycles, "timestamp"), (checkpoints, "created_at")]:
            if not frame.empty and column in frame.columns:
                candidate = pd.to_datetime(frame[column], utc=True, errors="coerce").min()
                if pd.notna(candidate):
                    candidates.append(candidate)
        start = min(candidates) if candidates else pd.Timestamp(utc_now())
    start_time = start.to_pydatetime()
    return start_time, start_time + timedelta(days=float(settings.competition.duration_days))


def last_cycle_timestamp(*frames: pd.DataFrame) -> pd.Timestamp | pd.NaT:
    timestamps = []
    for frame in frames:
        if frame.empty:
            continue
        for column in ["created_at", "timestamp"]:
            if column in frame.columns:
                timestamps.extend(pd.to_datetime(frame[column], utc=True, errors="coerce").dropna().tolist())
    return max(timestamps) if timestamps else pd.NaT


def system_status(last_cycle: pd.Timestamp | pd.NaT, end_time: datetime, start_time: datetime | None = None) -> str:
    if not db_path.exists():
        return "ERROR"
    if start_time and utc_now() < start_time:
        return "SCHEDULED"
    if utc_now() >= end_time:
        return "COMPLETED"
    if pd.isna(last_cycle):
        return "PAUSED"
    return "RUNNING" if (utc_now() - last_cycle.to_pydatetime()).total_seconds() <= settings.competition.poll_interval_seconds * 2.5 else "PAUSED"


def status_class(status: str) -> str:
    return {"RUNNING": "status-running", "SCHEDULED": "status-completed", "PAUSED": "status-paused", "COMPLETED": "status-completed", "ERROR": "status-error"}.get(status, "status-paused")


def render_deployment_panel(deployment: dict[str, Any]) -> None:
    versions = deployment.get("versions", {}) if isinstance(deployment, dict) else {}
    prompt = versions.get("system_prompt", {}) if isinstance(versions, dict) else {}
    rulebook = versions.get("rulebook", {}) if isinstance(versions, dict) else {}
    latest_checkpoint = deployment.get("latest_checkpoint", {}) if isinstance(deployment, dict) else {}
    pending = deployment.get("pending_updates", []) if isinstance(deployment, dict) else []
    cols = st.columns(4)
    cols[0].metric("Code", str(versions.get("code_version") or "-")[:12])
    cols[1].metric("Config", str(versions.get("config_version") or "-")[:12])
    cols[2].metric("Checkpoint", latest_checkpoint.get("cycle_number") if latest_checkpoint else "-")
    cols[3].metric("Pending updates", len(pending) if isinstance(pending, list) else 0)
    detail_cols = st.columns(2)
    with detail_cols[0]:
        st.caption(f"Prompt: {str(prompt.get('hash') or '-')[:12]} · {prompt.get('path', '-')}")
        st.caption(f"Rulebook: {str(rulebook.get('hash') or '-')[:12]} · {rulebook.get('path', '-')}")
        st.caption(f"Active checkpoint timestamp: {deployment.get('active_checkpoint_timestamp') or '-'}")
    with detail_cols[1]:
        st.caption(f"Last successful restart: {deployment.get('last_successful_restart') or '-'}")
        st.caption(f"Canary: {deployment.get('canary', {})}")
        st.caption(f"Feature flags: {deployment.get('features', {})}")
    if pending:
        st.dataframe(pd.DataFrame(pending), width="stretch", hide_index=True)


def local_runner_status(
    status: str,
    checkpoints: pd.DataFrame,
    workload_cycles: pd.DataFrame,
    next_run: datetime | None,
) -> dict[str, Any]:
    if checkpoints.empty:
        return {"status": "OFFLINE" if status in {"PAUSED", "COMPLETED"} else status, "phase": "WAITING" if status == "RUNNING" else status}
    latest_checkpoint = checkpoints.sort_values("created_at", ascending=False).iloc[0]
    cycle_number = int(latest_checkpoint.get("cycle_number") or 0)
    last_completed_at = pd.to_datetime(latest_checkpoint.get("created_at"), utc=True, errors="coerce")
    last_duration = None
    if not workload_cycles.empty:
        latest_workload = workload_cycles.sort_values("timestamp", ascending=False).iloc[0]
        payload = safe_json(latest_workload.get("payload_json"), {})
        if isinstance(payload, dict) and payload.get("total_wall_time_seconds") is not None:
            last_duration = float(payload.get("total_wall_time_seconds"))
        elif {"local_wall_time_seconds", "deepseek_latency_seconds", "grok_latency_seconds"}.issubset(workload_cycles.columns):
            last_duration = float(latest_workload.get("local_wall_time_seconds") or 0) + float(latest_workload.get("deepseek_latency_seconds") or 0) + float(latest_workload.get("grok_latency_seconds") or 0)
    started_at = last_completed_at.to_pydatetime() - timedelta(seconds=last_duration) if pd.notna(last_completed_at) and last_duration is not None else None
    runner_state = "RUNNING" if status in {"RUNNING", "SCHEDULED"} else "OFFLINE" if status in {"PAUSED", "COMPLETED"} else "ERROR"
    return {
        "status": runner_state,
        "cycle_number": cycle_number,
        "phase": "WAITING" if runner_state == "RUNNING" else runner_state,
        "last_cycle_duration_seconds": last_duration,
        "cycle_interval_seconds": settings.competition.poll_interval_seconds,
        "next_cycle_at": next_run.isoformat().replace("+00:00", "Z") if next_run else None,
        "last_cycle_started_at": started_at.isoformat().replace("+00:00", "Z") if started_at else None,
        "total_cycles_completed": cycle_number,
    }


def build_markers(trades: pd.DataFrame, visible_agents: list[str]) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    markers = []
    for _, trade in trades[trades["agent_id"].isin(visible_agents)].iterrows():
        agent = str(trade.get("agent_id"))
        is_deepseek = "deepseek" in agent
        color = "#3b82f6" if is_deepseek else "#00c076"
        prefix = "D" if is_deepseek else "G"
        action = str(trade.get("action", "")).upper()
        direction = str(trade.get("direction", "")).upper()
        ts = trade.get("created_at")
        if pd.isna(ts):
            continue
        notes = str(trade.get("notes", ""))
        pnl = float(trade.get("realized_pnl") or 0)
        if "OPEN" in action or action in {"ADD", "DCA"}:
            shape = "arrowUp" if direction == "LONG" else "arrowDown"
            position = "belowBar" if direction == "LONG" else "aboveBar"
            text = f"{prefix} LONG" if direction == "LONG" else f"{prefix} SHORT"
        elif "stop_loss" in notes:
            shape, position, text = "cross", "belowBar", f"{prefix} SL"
        elif "take_profit_1" in notes:
            shape, position, text = "circle", "aboveBar", f"{prefix} TP1"
        elif "take_profit_2" in notes or pnl > 0:
            shape, position, text = "circle", "aboveBar", f"{prefix} TP"
        else:
            shape, position, text = "circle", "aboveBar", f"{prefix} EXIT"
        markers.append({"time": int(pd.Timestamp(ts).timestamp()), "position": position, "color": color, "shape": shape, "text": text})
    return markers


def chart_price_lines(positions_view: pd.DataFrame) -> list[dict[str, Any]]:
    if positions_view.empty:
        return []
    lines = []
    for _, position in positions_view[positions_view["status"].isin(["OPEN", "PARTIAL"])].iterrows():
        prefix = "D" if "deepseek" in str(position.get("agent_id")) else "G"
        pnl = float(position.get("unrealized_pnl") or 0)
        lines.extend(
            [
                {"price": float(position["average_entry"]), "color": "#e5e7eb", "lineWidth": 1, "axisLabelVisible": True, "title": f"{prefix} ENTRY PnL {pnl:.2f}"},
                {"price": float(position["stop_loss"]), "color": "#ef4444", "lineWidth": 2, "axisLabelVisible": True, "title": f"{prefix} SL"},
                {"price": float(position["take_profit_1"]), "color": "#22c55e", "lineWidth": 1, "axisLabelVisible": True, "title": f"{prefix} TP1"},
                {"price": float(position["take_profit_2"]), "color": "#22c55e", "lineWidth": 1, "lineStyle": 2, "axisLabelVisible": True, "title": f"{prefix} TP2"},
                {"price": float(position["liq_estimate"]), "color": "#f59e0b", "lineWidth": 1, "lineStyle": 1, "axisLabelVisible": True, "title": f"{prefix} LIQ est"},
            ]
        )
    return lines


def render_live_chart(ohlcv: pd.DataFrame, trades: pd.DataFrame, positions_view: pd.DataFrame, visible_agents: list[str]) -> None:
    if ohlcv.empty:
        st.warning("No BTCUSDT candles available from CCXT or cache.")
        return
    frame = ohlcv.tail(900).copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    if frame.empty:
        st.warning("BTCUSDT candle data is present but could not be parsed.")
        return
    frame["ema9"] = ema(frame["close"], 9)
    frame["ema21"] = ema(frame["close"], 21)
    frame["ema50"] = ema(frame["close"], 50)
    frame["ema200"] = ema(frame["close"], 200)
    frame["rsi"] = rsi(frame["close"], 14).fillna(50)
    price_lines = chart_price_lines(positions_view)

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.70, 0.16, 0.14],
        specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
    )
    fig.add_trace(
        go.Candlestick(
            x=frame["timestamp"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            increasing=dict(line=dict(color="#22c55e"), fillcolor="#22c55e"),
            decreasing=dict(line=dict(color="#ef4444"), fillcolor="#ef4444"),
            name="BTCUSDT Perpetual",
        ),
        row=1,
        col=1,
    )
    for label, color in [("ema9", "#f59e0b"), ("ema21", "#38bdf8"), ("ema50", "#a855f7"), ("ema200", "#e5e7eb")]:
        fig.add_trace(
            go.Scatter(x=frame["timestamp"], y=frame[label], mode="lines", line=dict(color=color, width=1.25), name=label.upper()),
            row=1,
            col=1,
        )

    chart_trades = trades.copy()
    if not chart_trades.empty and "agent_id" in chart_trades.columns:
        chart_trades = chart_trades[chart_trades["agent_id"].isin(visible_agents)]
    for _, trade in chart_trades.iterrows():
        ts = pd.to_datetime(trade.get("created_at"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        price = float(trade.get("entry") or trade.get("exit") or 0)
        if price <= 0:
            continue
        agent = str(trade.get("agent_id", ""))
        is_deepseek = "deepseek" in agent
        color = "#3b82f6" if is_deepseek else "#00c076"
        prefix = "D" if is_deepseek else "G"
        direction = str(trade.get("direction", "")).upper()
        action = str(trade.get("action", "")).upper()
        notes = str(trade.get("notes", "")).lower()
        symbol = "triangle-up" if direction == "LONG" else "triangle-down"
        label = f"{prefix} LONG" if direction == "LONG" else f"{prefix} SHORT"
        if action in {"CLOSE", "CUT", "REDUCE"} or "take_profit" in notes or "stop_loss" in notes:
            symbol = "x" if "stop_loss" in notes else "circle"
            label = f"{prefix} SL" if "stop_loss" in notes else f"{prefix} TP"
        fig.add_trace(
            go.Scatter(
                x=[ts],
                y=[price],
                mode="markers+text",
                marker=dict(color=color, size=12, symbol=symbol, line=dict(color="#e5e7eb", width=1)),
                text=[label],
                textposition="top center" if symbol != "triangle-up" else "bottom center",
                textfont=dict(color=color, size=11),
                name=label,
                showlegend=False,
                hovertemplate=f"{label}<br>%{{x}}<br>%{{y:,.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    for line in price_lines:
        fig.add_hline(
            y=line["price"],
            row=1,
            col=1,
            line_color=line["color"],
            line_width=line.get("lineWidth", 1),
            line_dash="dash" if line.get("lineStyle") else "solid",
            annotation_text=line["title"],
            annotation_position="right",
            annotation_font_color=line["color"],
        )

    volume_colors = [
        "rgba(34, 197, 94, 0.40)" if close >= open_ else "rgba(239, 68, 68, 0.40)"
        for open_, close in zip(frame["open"], frame["close"], strict=False)
    ]
    fig.add_trace(go.Bar(x=frame["timestamp"], y=frame["volume"], marker_color=volume_colors, name="Volume"), row=2, col=1)
    fig.add_trace(go.Scatter(x=frame["timestamp"], y=frame["rsi"], mode="lines", line=dict(color="#22c55e", width=1.25), name="RSI 14"), row=3, col=1)
    fig.add_hline(y=70, row=3, col=1, line_color="#ef4444", line_width=1, line_dash="dot")
    fig.add_hline(y=30, row=3, col=1, line_color="#22c55e", line_width=1, line_dash="dot")
    fig.update_layout(
        template="plotly_dark",
        height=860,
        margin=dict(l=0, r=0, t=8, b=0),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#05070a",
        plot_bgcolor="#05070a",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1, bgcolor="rgba(5,7,10,.65)"),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#10161d", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#10161d", zeroline=False, side="right")
    fig.update_yaxes(title_text="BTCUSDT", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    st.plotly_chart(fig, width="stretch")


def r_multiple(trade: pd.Series, positions_frame: pd.DataFrame, signals: pd.DataFrame) -> float:
    pnl = float(trade.get("realized_pnl") or 0)
    entry = float(trade.get("entry") or 0)
    notional = float(trade.get("notional") or 0)
    stop = find_signal_field(signals, str(trade.get("position_id")), "stop_loss", entry)
    risk = abs(notional * ((entry - stop) / entry)) if entry and notional else 0.0
    return pnl / risk if risk else 0.0


def find_signal_field(signals: pd.DataFrame, position_id: str, field: str, default: float) -> float:
    payloads = signal_payloads(signals)
    if payloads.empty or f"payload_{field}" not in payloads.columns:
        return float(default)
    ids = payloads.get("payload_position_id", pd.Series(dtype=str)).astype(str)
    match = payloads[ids == str(position_id)]
    if match.empty:
        return float(default)
    value = pd.to_numeric(pd.Series([match.iloc[-1].get(f"payload_{field}")]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) else float(default)


def trade_holding_time(trade: pd.Series, positions_frame: pd.DataFrame) -> str:
    pos_id = trade.get("position_id")
    if positions_frame.empty or not pos_id:
        return "-"
    match = positions_frame[positions_frame["id"] == pos_id]
    if match.empty:
        return "-"
    opened = match.iloc[0].get("opened_at")
    closed = match.iloc[0].get("closed_at")
    end = closed if pd.notna(closed) else trade.get("created_at")
    return human_duration(end - opened if pd.notna(opened) and pd.notna(end) else None)


def notifications(signals: pd.DataFrame, trades: pd.DataFrame, positions: pd.DataFrame, metric_frame: pd.DataFrame) -> list[str]:
    notes = []
    if not trades.empty:
        latest = trades.sort_values("created_at", ascending=False).head(5)
        for _, trade in latest.iterrows():
            action = str(trade.get("action", ""))
            pnl = float(trade.get("realized_pnl") or 0)
            if action:
                notes.append(f"{trade.get('agent_id')} {action} {trade.get('direction')} at {trade.get('entry')}")
            if pnl > 0:
                notes.append(f"{trade.get('agent_id')} realized profit {fmt_money(pnl)}")
            if pnl < 0:
                notes.append(f"{trade.get('agent_id')} realized loss {fmt_money(pnl)}")
    if not signals.empty:
        status_series = signals.get("signal_status")
        if status_series is None:
            status_series = pd.Series([""] * len(signals), index=signals.index)
        accepted = signals[(status_series.fillna("").eq("ACCEPTED")) | (pd.to_numeric(signals["accepted"], errors="coerce").fillna(0) == 1)]
        if not accepted.empty:
            row = accepted.sort_values("created_at", ascending=False).iloc[0]
            notes.append(f"ACCEPTED: {row.get('agent_name') or row.get('agent_id')} {row.get('decision')}/{row.get('action')}")
        rejected = signals[(status_series.fillna("").eq("REJECTED")) | (pd.to_numeric(signals["accepted"], errors="coerce").fillna(0) == 0)]
        if not rejected.empty:
            row = rejected.sort_values("created_at", ascending=False).iloc[0]
            code = row.get("rejection_reason_code") or "REJECTED"
            notes.append(f"REJECTED: {row.get('agent_name') or row.get('agent_id')} {code}")
    if not metric_frame.empty:
        for _, row in metric_frame.iterrows():
            if float(row.get("total_return_pct") or 0) <= -float(settings.risk.daily_loss_limit_pct):
                notes.append(f"{row.get('agent_id')} is near or beyond daily loss limit threshold.")
    if not positions.empty:
        closed = positions[positions["status"].astype(str).str.upper() == "CLOSED"]
        if not closed.empty:
            row = closed.sort_values("closed_at", ascending=False).iloc[0]
            notes.append(f"Position closed: {row.get('agent_id')} {row.get('id')}")
    return notes[:8]


def download_frame(label: str, frame: pd.DataFrame, filename: str) -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8") if not frame.empty else b"", filename, "text/csv", disabled=frame.empty)


def download_text(label: str, text: str, filename: str) -> None:
    st.download_button(label, text.encode("utf-8"), filename, "text/markdown", disabled=not bool(text.strip()))


@st.cache_data(ttl=10)
def read_snapshot(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def render_cloud_snapshot_dashboard(snapshot: dict[str, Any]) -> None:
    generated = pd.to_datetime(snapshot.get("generated_at"), utc=True, errors="coerce")
    age = utc_now() - generated.to_pydatetime() if pd.notna(generated) else None
    stale_warning = timedelta(minutes=settings.cloud_dashboard.stale_warning_minutes)
    stale_critical = timedelta(minutes=settings.cloud_dashboard.stale_critical_minutes)
    competition = snapshot.get("competition", {})
    start_time = pd.to_datetime(competition.get("start_time"), utc=True, errors="coerce")
    end_time = pd.to_datetime(competition.get("end_time"), utc=True, errors="coerce")
    start_dt = start_time.to_pydatetime() if pd.notna(start_time) else utc_now()
    end_dt = end_time.to_pydatetime() if pd.notna(end_time) else start_dt + timedelta(days=float(settings.competition.duration_days))
    elapsed = max(timedelta(0), utc_now() - start_dt)
    duration = max(timedelta(seconds=1), end_dt - start_dt)
    remaining = max(timedelta(0), end_dt - utc_now())
    percent_complete = min(1.0, elapsed.total_seconds() / duration.total_seconds())

    agents = snapshot.get("agents", {})
    snapshot_agent_ids = list(agents) or agent_ids
    market = snapshot.get("market", {})
    chart_frame = _snapshot_candles(snapshot)
    if not chart_frame.empty and "timestamp" in chart_frame.columns:
        chart_frame["timestamp"] = pd.to_datetime(chart_frame["timestamp"], utc=True, errors="coerce")
    current_price = float(snapshot.get("btc_price") or market.get("current_price") or 0.0)
    open_positions = pd.DataFrame(snapshot.get("open_positions", []))
    if not open_positions.empty:
        for column in ["opened_at", "closed_at"]:
            if column in open_positions.columns:
                open_positions[column] = pd.to_datetime(open_positions[column], utc=True, errors="coerce")
        open_positions = build_position_view(open_positions, current_price)
    recent_trades = pd.DataFrame(snapshot.get("recent_trades", []))
    if not recent_trades.empty and "created_at" in recent_trades.columns:
        recent_trades["created_at"] = pd.to_datetime(recent_trades["created_at"], utc=True, errors="coerce")
    metric_frame = _snapshot_metric_frame(snapshot, snapshot_agent_ids)
    workload_cycles = _snapshot_workload_cycles(snapshot)
    equity_rows = _flatten_snapshot_series(snapshot.get("equity_curves", {}), "equity")
    drawdown_rows = _flatten_snapshot_series(snapshot.get("drawdown_curves", {}), "drawdown")
    rejected_recent = pd.DataFrame(snapshot.get("rejected_signals_summary", {}).get("recent", []))
    reflections = pd.DataFrame(snapshot.get("reflections_summary", {}).get("recent", []))
    token_usage = pd.DataFrame.from_dict(snapshot.get("token_usage", {}), orient="index").reset_index(names="agent_id")
    diversity = snapshot.get("strategy_diversity_metrics", {})
    workload = snapshot.get("workload", {})
    audit_missing = "signal_audit_summary" not in snapshot
    audit_summary = _snapshot_audit_summary(snapshot)
    latest_cycle_at = pd.to_datetime(snapshot.get("system_status", {}).get("latest_cycle_at"), utc=True, errors="coerce")
    next_run = latest_cycle_at.to_pydatetime() + timedelta(seconds=settings.competition.poll_interval_seconds) if pd.notna(latest_cycle_at) else None
    status = "SCHEDULED" if utc_now() < start_dt else snapshot.get("competition_status", "UNKNOWN")
    spent = float(snapshot.get("api_costs", {}).get("total") or 0.0)
    api_budget = os.getenv("ARENA_API_BUDGET_USD")
    remaining_budget = (float(api_budget) - spent) if api_budget else None

    with st.sidebar:
        st.title("Arena Control")
        selected_agents = st.multiselect("Agents", options=snapshot_agent_ids, default=snapshot_agent_ids, format_func=lambda aid: agent_names.get(aid, aid))
        chart_timeframe = st.selectbox("Chart timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"], index=3)
        auto_refresh = st.selectbox("Auto refresh", options=["Off", "10 sec", "30 sec", "60 sec"], index=0)
        if st.button("Refresh Now", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.caption("Date range")
        st.date_input("Filter range", value=(datetime.now().date() - timedelta(days=7), datetime.now().date()))
        st.divider()
        st.metric("Status", status)
        st.metric("Open positions", len(open_positions))
        st.metric("API spent", f"${spent:.4f}")
        st.metric("Uptime", "-")
        st.caption(f"Last updated: {fmt_time(generated) if pd.notna(generated) else 'unknown'}")

    if auto_refresh != "Off":
        seconds = int(auto_refresh.split()[0])
        st.markdown(f"<meta http-equiv='refresh' content='{seconds}'>", unsafe_allow_html=True)

    st.title("Crypto Paper Trading Arena")
    st.caption("BTCUSDT perpetual futures paper competition")

    sync_note = ""
    if age is None:
        sync_note = "Snapshot timestamp is missing or invalid."
    elif age > stale_critical:
        sync_note = f"Snapshot is stale: {human_duration(age)} since last successful sync."
    elif age > stale_warning:
        sync_note = f"Snapshot is getting stale: {human_duration(age)} since last successful sync."
    else:
        sync_note = f"Last successful sync: {fmt_time(generated)} ({human_duration(age)} ago)"
    st.markdown(
        f"""
        <div class="arena-banner">
            <span class="{status_class(status)}">{status}</span>
            <span class="muted"> | Last cycle: {fmt_time(latest_cycle_at) if pd.notna(latest_cycle_at) else 'none yet'}
            | Next run: {fmt_time(next_run) if next_run else 'not scheduled'}
            | Open positions: {len(open_positions)}
            | Uptime since checkpoint: -
            | Remaining API budget: {fmt_money(remaining_budget) if remaining_budget is not None else 'not configured'}
            | Price: {current_price:,.2f} ({competition.get('timeframe') or chart_timeframe})</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if age is None or age > stale_critical:
        st.error(sync_note)
    elif age > stale_warning:
        st.warning(sync_note)
    if audit_missing:
        st.error("Snapshot is missing the signal audit contract. Trading data is still visible, but Accepted/Rejected Signals are waiting for the next valid snapshot.")

    banner_cols = st.columns(4)
    banner_cols[0].metric("Current leader", snapshot.get("leader") or "-")
    banner_cols[1].metric("Time remaining", human_duration(remaining))
    banner_cols[2].metric("Complete", f"{percent_complete * 100:.1f}%")
    banner_cols[3].metric("Start / End", f"{fmt_short_time(start_dt)} -> {fmt_short_time(end_dt)}")
    st.progress(percent_complete)
    render_cycle_status(snapshot.get("runner", {}))

    tabs = st.tabs(
        [
            "Overview",
            "Live Positions",
            "Trade History",
            "Equity Curves",
            "Leaderboard",
            "Accepted Signals",
            "Rejected Signals",
            "Raw Model Outputs",
            "Memory & Reflections",
            "Token & Cost",
            "API Cost Audit",
            "Workload Attribution",
            "Strategy Diversity",
            "Configuration",
        ]
    )

    with tabs[0]:
        st.subheader("Overview")
        st.markdown('<div class="chart-shell">', unsafe_allow_html=True)
        st.markdown(
            f"<div class='chart-head'><strong>BTCUSDT Perpetual</strong><span>{chart_timeframe} | EMA 9/21/50/200 | Volume | RSI | Trade overlays</span></div>",
            unsafe_allow_html=True,
        )
        render_live_chart(chart_frame, recent_trades, open_positions, selected_agents or snapshot_agent_ids)
        st.markdown("</div>", unsafe_allow_html=True)
        if metric_frame.empty:
            st.info("No metrics yet. Run the competition once to populate the dashboard.")
        else:
            for _, row in metric_frame[metric_frame["agent_id"].isin(selected_agents or snapshot_agent_ids)].iterrows():
                st.markdown(f"#### {row['agent']}  `{row['model']}`")
                cols = st.columns(6)
                cols[0].metric("Current equity", fmt_money(row["current_equity"]), fmt_pct(row["total_return_pct"]))
                cols[1].metric("Unrealized PnL", fmt_money(row["unrealized_pnl"]))
                cols[2].metric("Realized PnL", fmt_money(row["realized_pnl"]))
                cols[3].metric("Max drawdown", fmt_pct(row["max_drawdown"]))
                cols[4].metric("Win rate", fmt_pct(row["win_rate"]))
                cols[5].metric("Sharpe", f"{row['sharpe_ratio']:.2f}")
                cols = st.columns(6)
                cols[0].metric("Profit factor", f"{row['profit_factor']:.2f}")
                cols[1].metric("Rule compliance", fmt_pct(row["rule_compliance"]))
                cols[2].metric("Rejected signals", int(row["rejected_signals"]))
                cols[3].metric("Token usage", f"{int(row['token_usage']):,}")
                cols[4].metric("API cost", f"${row['estimated_api_cost']:.4f}")
                cols[5].metric("Profit / $ API", f"{row['profit_per_api_dollar']:.2f}")

    with tabs[1]:
        st.subheader("Live Positions")
        if selected_agents and not open_positions.empty:
            open_positions = open_positions[open_positions["agent_id"].isin(selected_agents)]
        st.dataframe(open_positions, width="stretch", hide_index=True) if not open_positions.empty else st.info("No live positions.")

    with tabs[2]:
        st.subheader("Trade History")
        if selected_agents and not recent_trades.empty:
            recent_trades = recent_trades[recent_trades["agent_id"].isin(selected_agents)]
        st.dataframe(recent_trades, width="stretch", hide_index=True) if not recent_trades.empty else st.info("No recent trades.")
        st.subheader("Trade History Summary")
        summary = pd.DataFrame.from_dict(snapshot.get("trade_history_summary", {}), orient="index").reset_index(names="agent_id")
        st.dataframe(summary, width="stretch", hide_index=True) if not summary.empty else st.info("No trade summary yet.")

    with tabs[3]:
        st.subheader("Equity Curves")
        equity_rows = _flatten_snapshot_series(snapshot.get("equity_curves", {}), "equity")
        if equity_rows.empty:
            st.info("No equity curve data yet.")
        else:
            st.plotly_chart(px.line(equity_rows, x="timestamp", y="equity", color="agent_id", template="plotly_dark"), width="stretch")
        drawdown_rows = _flatten_snapshot_series(snapshot.get("drawdown_curves", {}), "drawdown")
        if not drawdown_rows.empty:
            fig = px.area(drawdown_rows, x="timestamp", y="drawdown", color="agent_id", template="plotly_dark")
            fig.update_yaxes(tickformat=".1%")
            st.plotly_chart(fig, width="stretch")

    with tabs[4]:
        st.subheader("Leaderboard")
        columns = ["agent_id", "current_equity", "total_return_pct", "sharpe_ratio", "max_drawdown", "rule_compliance", "profit_per_api_dollar", "score"]
        st.dataframe(metric_frame[[column for column in columns if column in metric_frame.columns]], width="stretch", hide_index=True) if not metric_frame.empty else st.info("No leaderboard yet.")

    with tabs[5]:
        st.subheader("Accepted Signals")
        audit = audit_summary
        cols = st.columns(5)
        cols[0].metric("Total accepted", int(audit.get("accepted_signal_count") or 0))
        cols[1].metric("Acceptance rate", fmt_pct(audit.get("acceptance_rate")))
        cols[2].metric("Total rejected", int(audit.get("rejected_signal_count") or 0))
        cols[3].metric("Avg confidence", "-")
        cols[4].metric("Avg expected R:R", "-")
        latest = audit.get("latest_accepted_signal")
        if audit_missing:
            st.error("Signal audit summary is missing from this snapshot. The exporter now blocks malformed snapshots so this clears after the next valid sync.")
        accepted_rows = pd.DataFrame(audit.get("recent_accepted_signals") or ([latest] if latest else []))
        if not accepted_rows.empty:
            display_cols = [
                "timestamp_local",
                "cycle_number",
                "agent_name",
                "decision",
                "action",
                "direction",
                "confidence",
                "entry_price",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "risk_pct",
                "leverage",
                "expected_rr",
                "signal_status",
            ]
            st.dataframe(accepted_rows[[col for col in display_cols if col in accepted_rows.columns]], width="stretch", hide_index=True)
            with st.expander("Latest accepted signal details", expanded=False):
                st.json(latest)
        else:
            st.info("No accepted signals in the current snapshot.")

    with tabs[6]:
        st.subheader("Rejected Signals")
        audit = audit_summary
        cols = st.columns(4)
        cols[0].metric("Total rejected", int(audit.get("rejected_signal_count") or 0))
        cols[1].metric("Rejection rate", fmt_pct(1 - float(audit.get("acceptance_rate") or 0)))
        cols[2].metric("Top rejection reasons", ", ".join(f"{k}: {v}" for k, v in (audit.get("rejection_breakdown") or {}).items()) or "-")
        cols[3].metric("Recent rejected", len(rejected_recent))
        if audit_missing:
            st.error("Signal audit summary is missing from this snapshot. Rejected rows below may be legacy-only.")
        rejected_rows = pd.DataFrame(audit.get("recent_rejected_signals") or rejected_recent.to_dict("records"))
        if not rejected_rows.empty:
            display_cols = [
                "timestamp_local",
                "cycle_number",
                "agent_name",
                "rejection_reason_code",
                "rejection_reason_message",
                "decision",
                "action",
                "direction",
                "confidence",
            ]
            st.dataframe(rejected_rows[[col for col in display_cols if col in rejected_rows.columns]], width="stretch", hide_index=True)
        else:
            st.success("No rejected signals.")
        latest = audit.get("latest_rejected_signal")
        if latest:
            with st.expander("Latest rejected signal details", expanded=False):
                st.json(latest)

    with tabs[7]:
        st.subheader("Raw Model Outputs")
        st.info("Raw prompts and model outputs are not included in the cloud snapshot yet.")

    with tabs[8]:
        st.subheader("Memory & Reflections")
        st.dataframe(reflections, width="stretch", hide_index=True) if not reflections.empty else st.info("No recent reflections.")

    with tabs[9]:
        st.subheader("Token & Cost Analytics")
        st.dataframe(token_usage, width="stretch", hide_index=True) if not token_usage.empty else st.info("No token usage yet.")
        st.json(snapshot.get("api_costs", {}))

    with tabs[10]:
        st.subheader("API Cost Audit")
        st.info("Request-level API audit is available on the local dashboard after `api_requests` rows are recorded in SQLite.")

    with tabs[11]:
        st.subheader("Workload Attribution")
        latest = workload.get("latest") or {}
        kpis = st.columns(5)
        kpis[0].metric("Local Machine", f"{float(workload.get('local_pct') or 0):.1f}%")
        kpis[1].metric("DeepSeek", f"{float(workload.get('deepseek_pct') or 0):.1f}%")
        kpis[2].metric(challenger_short_label, f"{float(workload.get('grok_pct') or 0):.1f}%")
        kpis[3].metric("Total API Cost", f"${spent:.4f}")
        kpis[4].metric("Profit / $ API", f"{float(metric_frame['profit_per_api_dollar'].mean()) if not metric_frame.empty else 0.0:.2f}")
        st.dataframe(workload_cycles, width="stretch", hide_index=True) if not workload_cycles.empty else st.info("No workload cycles recorded in snapshot.")
        if latest:
            st.json(latest)

    with tabs[12]:
        st.subheader("Strategy Diversity")
        if diversity:
            cols = st.columns(5)
            cols[0].metric("Action agreement", fmt_pct(diversity.get("action_agreement_rate")))
            cols[1].metric("Direction agreement", fmt_pct(diversity.get("directional_agreement_rate")))
            cols[2].metric("Leverage similarity", fmt_pct(diversity.get("leverage_similarity")))
            cols[3].metric("Confidence corr.", f"{float(diversity.get('confidence_correlation') or 0):.2f}")
            cols[4].metric("Shared ratio", fmt_pct(diversity.get("shared_ratio_applied")))
            st.json(diversity)
        else:
            st.info("No diversity metrics yet.")

    with tabs[13]:
        st.subheader("Configuration")
        st.markdown("#### Deployment & Versions")
        render_deployment_panel(snapshot.get("deployment", {}))
        st.markdown("#### Active settings")
        st.json(
            {
                "models": agent_models,
                "symbol": competition.get("symbol", settings.competition.display_symbol),
                "chart_timeframe": chart_timeframe,
                "poll_interval_seconds": settings.competition.poll_interval_seconds,
                "competition_duration_days": competition.get("duration_days", settings.competition.duration_days),
                "initial_equity": settings.accounts.initial_equity,
                "cloud_snapshot_generated_at": snapshot.get("generated_at"),
                "sync_note": sync_note,
            }
        )


def render_cloud_price_chart(snapshot: dict[str, Any]) -> None:
    frame = _snapshot_candles(snapshot)
    if frame.empty:
        try:
            frame = fetch_ohlcv(settings.competition.timeframe, limit=500)
        except Exception:
            frame = pd.DataFrame()
    if frame.empty:
        st.info("No BTCUSDT candle data available in the latest snapshot.")
        return
    frame = frame.tail(500).copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    if frame.empty:
        st.info("BTCUSDT candle timestamps are unavailable.")
        return
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=frame["timestamp"],
                open=frame["open"],
                high=frame["high"],
                low=frame["low"],
                close=frame["close"],
                name="BTCUSDT",
                increasing_line_color="#22c55e",
                decreasing_line_color="#ef4444",
            )
        ]
    )
    for length, color in [(9, "#f59e0b"), (21, "#38bdf8"), (50, "#a855f7"), (200, "#e5e7eb")]:
        if len(frame) >= length:
            fig.add_trace(
                go.Scatter(
                    x=frame["timestamp"],
                    y=ema(frame["close"], length),
                    mode="lines",
                    name=f"EMA {length}",
                    line=dict(color=color, width=1),
                )
            )
    fig.update_layout(
        template="plotly_dark",
        height=520,
        margin=dict(l=8, r=8, t=24, b=8),
        xaxis_rangeslider_visible=False,
        yaxis_title="BTCUSDT",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width="stretch")


def _snapshot_metric_frame(snapshot: dict[str, Any], snapshot_agent_ids: list[str]) -> pd.DataFrame:
    rows = []
    leaderboard = {str(row.get("agent_id")): row for row in snapshot.get("leaderboard", []) if isinstance(row, dict)}
    agents = snapshot.get("agents", {})
    usage = snapshot.get("token_usage", {})
    rejected = snapshot.get("rejected_signals_summary", {}).get("by_agent", {})
    for agent_id in snapshot_agent_ids:
        account = agents.get(agent_id, {}) if isinstance(agents, dict) else {}
        board = leaderboard.get(agent_id, {})
        token = usage.get(agent_id, {}) if isinstance(usage, dict) else {}
        equity = float(account.get("equity") or board.get("equity") or initial_equity)
        realized = float(account.get("realized_pnl") or board.get("realized_pnl") or 0.0)
        unrealized = float(account.get("unrealized_pnl") or board.get("unrealized_pnl") or 0.0)
        total_return = float(board.get("total_return_pct") or ((equity - initial_equity) / initial_equity if initial_equity else 0.0))
        cost = float(token.get("estimated_cost_usd") or snapshot.get("api_costs", {}).get("by_agent", {}).get(agent_id) or 0.0)
        rows.append(
            {
                "agent_id": agent_id,
                "agent": agent_names.get(agent_id, agent_id),
                "model": agent_models.get(agent_id, ""),
                "current_equity": equity,
                "total_return_pct": total_return,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "max_drawdown": float(board.get("max_drawdown_pct") or board.get("max_drawdown") or 0.0),
                "win_rate": float(board.get("win_rate") or 0.0),
                "sharpe_ratio": float(board.get("sharpe") or board.get("sharpe_ratio") or 0.0),
                "profit_factor": float(board.get("profit_factor") or 0.0),
                "rule_compliance": float(board.get("rule_compliance") or 1.0),
                "rejected_signals": int(rejected.get(agent_id) or board.get("rejected_signals") or 0),
                "token_usage": int(float(token.get("input_tokens") or 0) + float(token.get("output_tokens") or 0)),
                "requests": int(float(token.get("requests") or 0)),
                "estimated_api_cost": cost,
                "profit_per_api_dollar": realized / cost if cost > 0 else 0.0,
                "score": float(board.get("score") or 0.0),
            }
        )
    return pd.DataFrame(rows).sort_values("score", ascending=False) if rows else pd.DataFrame()


def _snapshot_audit_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    audit = snapshot.get("signal_audit_summary")
    if isinstance(audit, dict):
        return audit
    rejected_summary = snapshot.get("rejected_signals_summary", {}) if isinstance(snapshot.get("rejected_signals_summary"), dict) else {}
    rejected_count = int(rejected_summary.get("total_recent") or 0)
    return {
        "accepted_signal_count": 0,
        "rejected_signal_count": rejected_count,
        "acceptance_rate": 0.0,
        "rejection_breakdown": {},
        "latest_accepted_signal": None,
        "latest_rejected_signal": (rejected_summary.get("recent") or [None])[0],
        "recent_accepted_signals": [],
        "recent_rejected_signals": rejected_summary.get("recent") or [],
    }


def _snapshot_workload_cycles(snapshot: dict[str, Any]) -> pd.DataFrame:
    latest = snapshot.get("workload", {}).get("latest") or {}
    if not latest:
        return pd.DataFrame()
    row = dict(latest)
    if "timestamp" not in row:
        row["timestamp"] = snapshot.get("system_status", {}).get("latest_cycle_at") or snapshot.get("generated_at")
    return pd.DataFrame([row])


def _snapshot_candles(snapshot: dict[str, Any]) -> pd.DataFrame:
    candles = snapshot.get("market", {}).get("candles", [])
    if not isinstance(candles, list) or not candles:
        return pd.DataFrame()
    frame = pd.DataFrame(candles)
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    for column in ["open", "high", "low", "close", "volume"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"])


def _flatten_snapshot_series(series: dict[str, list[dict[str, Any]]], value_column: str) -> pd.DataFrame:
    rows = []
    for agent_id, points in series.items():
        for point in points:
            rows.append({"agent_id": agent_id, "timestamp": point.get("timestamp"), value_column: point.get(value_column)})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame


dashboard_mode = os.getenv("ARENA_DASHBOARD_MODE", "auto").lower()
render_runtime = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
use_snapshot_dashboard = dashboard_mode == "cloud" or (
    dashboard_mode == "auto" and (render_runtime or not db_path.exists())
)

snapshot_payload = read_snapshot(str(cloud_snapshot_path)) if use_snapshot_dashboard else {}
if snapshot_payload:
    render_cloud_snapshot_dashboard(snapshot_payload)
    st.stop()


with st.sidebar:
    st.title("Arena Control")
    selected_agents = st.multiselect("Agents", options=agent_ids, default=agent_ids, format_func=lambda aid: agent_names.get(aid, aid))
    chart_timeframe = st.selectbox("Chart timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"], index=3)
    auto_refresh = st.selectbox("Auto refresh", options=["Off", "10 sec", "30 sec", "60 sec"], index=0)
    if st.button("Refresh Now", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Date range")
    date_range = st.date_input("Filter range", value=(datetime.now().date() - timedelta(days=7), datetime.now().date()))

if auto_refresh != "Off":
    seconds = int(auto_refresh.split()[0])
    st.markdown(f"<meta http-equiv='refresh' content='{seconds}'>", unsafe_allow_html=True)

prompts = read_table("prompts", str(db_path))
tool_calls = read_table("tool_calls", str(db_path))
responses = read_table("responses", str(db_path))
signals = read_table("signals", str(db_path))
positions = read_table("positions", str(db_path))
trades = read_table("trades", str(db_path))
reflections = read_table("reflections", str(db_path))
lessons = read_table("lessons", str(db_path))
shared_lessons = read_table("shared_lessons", str(db_path))
strategy_profiles = read_table("strategy_profiles", str(db_path))
diversity_metrics = read_table("diversity_metrics", str(db_path))
lesson_promotions = read_table("lesson_promotions", str(db_path))
workload_cycles = read_table("workload_cycles", str(db_path))
workload_components = read_table("workload_components", str(db_path))
api_requests = read_table("api_requests", str(db_path))
health_checks = read_table("health_checks", str(db_path))
benchmarks = read_table("benchmarks", str(db_path))
prompt_versions = read_table("prompt_versions", str(db_path))
config_versions = read_table("config_versions", str(db_path))
control_commands = read_table("control_commands", str(db_path))
checkpoints = read_table("checkpoints", str(db_path))
downtime_events = read_table("downtime_events", str(db_path))
ledger = read_csv(str(ledger_path))
for frame_name in ["prompts", "tool_calls", "responses", "signals", "positions", "trades", "reflections", "lessons"]:
    frame = globals()[frame_name]
    if not frame.empty and "agent_id" in frame.columns:
        globals()[frame_name] = frame[frame["agent_id"].isin(agent_ids)].copy()
signals_md = read_text(str(signals_path))
evaluation_md = read_text(str(evaluation_path))
rulebook_md = read_text(str(rulebook_path))
ohlcv = fetch_ohlcv(chart_timeframe)
current_price = float(ohlcv["close"].iloc[-1]) if not ohlcv.empty else None
positions_view = build_position_view(positions, current_price)
curve = equity_curve(trades, positions_view)
metric_frame = metrics_table(trades, signals, responses, positions_view, curve)
start_time, end_time = competition_times(health_checks, checkpoints, workload_cycles)
last_cycle = last_cycle_timestamp(prompts, responses, signals, trades, checkpoints, workload_cycles)
latest_checkpoint_time = pd.to_datetime(checkpoints["created_at"], utc=True, errors="coerce").max() if not checkpoints.empty and "created_at" in checkpoints.columns else pd.NaT
system_uptime = utc_now() - latest_checkpoint_time.to_pydatetime() if pd.notna(latest_checkpoint_time) else None
next_run = last_cycle.to_pydatetime() + timedelta(seconds=settings.competition.poll_interval_seconds) if pd.notna(last_cycle) else None
status = system_status(last_cycle, end_time, start_time)
elapsed = max(timedelta(0), utc_now() - start_time)
duration = max(timedelta(seconds=1), end_time - start_time)
remaining = max(timedelta(0), end_time - utc_now())
percent_complete = min(1.0, elapsed.total_seconds() / duration.total_seconds())
open_count = 0 if positions_view.empty else int(positions_view["status"].isin(["OPEN", "PARTIAL"]).sum())
api_budget = os.getenv("ARENA_API_BUDGET_USD")
spent = float(metric_frame["estimated_api_cost"].sum()) if not metric_frame.empty else 0.0
remaining_budget = (float(api_budget) - spent) if api_budget else None
deployment_state = LiveUpdateManager(settings, ArenaRepository(build_session_factory(settings.database_url))).deployment_state()

with st.sidebar:
    st.divider()
    st.metric("Status", status)
    st.metric("Open positions", open_count)
    st.metric("API spent", f"${spent:.4f}")
    st.metric("Uptime", human_duration(system_uptime) if system_uptime else "-")
    st.caption(f"Last updated: {fmt_time(utc_now())}")

st.title("Crypto Paper Trading Arena")
st.caption("BTCUSDT perpetual futures paper competition")
st.markdown(
    f"""
    <div class="arena-banner">
        <span class="{status_class(status)}">{status}</span>
        <span class="muted"> | Last cycle: {fmt_time(last_cycle) if pd.notna(last_cycle) else 'none yet'}
        | Next run: {fmt_time(next_run) if next_run else 'not scheduled'}
        | Open positions: {open_count}
        | Uptime since checkpoint: {human_duration(system_uptime) if system_uptime else '-'}
        | Remaining API budget: {f'${remaining_budget:.2f}' if remaining_budget is not None else 'not configured'}
        | Price: {f'{current_price:,.2f}' if current_price else 'unavailable'} ({chart_timeframe})</span>
    </div>
    """,
    unsafe_allow_html=True,
)

pending_orders_count = 0
active_cooldown_count = 0
active_fallback_models = 0
try:
    with sqlite3.connect(str(db_path)) as _conn:
        pending_orders_count = int(
            _conn.execute("SELECT COUNT(*) FROM pending_orders WHERE status = 'PENDING'").fetchone()[0]
        )
        active_cooldown_count = int(
            _conn.execute("SELECT COUNT(*) FROM cooldown_state WHERE active = 1").fetchone()[0]
        )
        active_fallback_models = int(
            _conn.execute("SELECT COUNT(*) FROM agent_failover_state WHERE using_fallback = 1").fetchone()[0]
        )
except Exception:
    pass

banner_cols = st.columns(7)
leader = metric_frame.iloc[0]["agent_id"] if not metric_frame.empty else "-"
banner_cols[0].metric("Current leader", leader)
banner_cols[1].metric("Time remaining", human_duration(remaining))
banner_cols[2].metric("Complete", f"{percent_complete * 100:.1f}%")
banner_cols[3].metric("Pending orders", pending_orders_count)
banner_cols[4].metric("Cooldowns", active_cooldown_count)
banner_cols[5].metric("Fallback models", active_fallback_models)
banner_cols[6].metric("Start / End", f"{fmt_short_time(start_time)} -> {fmt_short_time(end_time)}")
st.progress(percent_complete)

alerts = notifications(signals, trades, positions, metric_frame)
if alerts:
    with st.expander("Notifications", expanded=True):
        for note in alerts:
            if str(note).startswith("ACCEPTED:"):
                st.success(note)
            elif str(note).startswith("REJECTED:"):
                st.warning(note)
            else:
                st.warning(note)

snapshot_for_status = read_snapshot(str(cloud_snapshot_path))
runner_payload = snapshot_for_status.get("runner") if isinstance(snapshot_for_status, dict) else {}
if not runner_payload:
    runner_payload = local_runner_status(status, checkpoints, workload_cycles, next_run)
render_cycle_status(runner_payload)

tabs = st.tabs(
    [
        "Overview",
        "Live Positions",
        "Trade History",
        "Equity Curves",
        "Leaderboard",
        "Accepted Signals",
        "Rejected Signals",
        "Raw Model Outputs",
        "Memory & Reflections",
        "Token & Cost",
        "API Cost Audit",
        "Workload Attribution",
        "Strategy Diversity",
        "Pending Orders",
        "Risk Automation",
        "API Failover Events",
        "Configuration",
    ]
)

with tabs[0]:
    st.subheader("Overview")
    st.markdown('<div class="chart-shell">', unsafe_allow_html=True)
    st.markdown(
        f"<div class='chart-head'><strong>BTCUSDT Perpetual</strong><span>{chart_timeframe} | EMA 9/21/50/200 | Volume | RSI | Trade overlays</span></div>",
        unsafe_allow_html=True,
    )
    render_live_chart(ohlcv, trades, positions_view, selected_agents or agent_ids)
    st.markdown("</div>", unsafe_allow_html=True)
    if metric_frame.empty:
        st.info("No metrics yet. Run the competition once to populate the dashboard.")
    else:
        for _, row in metric_frame[metric_frame["agent_id"].isin(selected_agents or agent_ids)].iterrows():
            st.markdown(f"#### {row['agent']}  `{row['model']}`")
            cols = st.columns(6)
            cols[0].metric("Current equity", fmt_money(row["current_equity"]), fmt_pct(row["total_return_pct"]))
            cols[1].metric("Unrealized PnL", fmt_money(row["unrealized_pnl"]))
            cols[2].metric("Realized PnL", fmt_money(row["realized_pnl"]))
            cols[3].metric("Max drawdown", fmt_pct(row["max_drawdown"]))
            cols[4].metric("Win rate", fmt_pct(row["win_rate"]))
            cols[5].metric("Sharpe", f"{row['sharpe_ratio']:.2f}")
            cols = st.columns(6)
            cols[0].metric("Profit factor", f"{row['profit_factor']:.2f}")
            cols[1].metric("Rule compliance", fmt_pct(row["rule_compliance"]))
            cols[2].metric("Rejected signals", int(row["rejected_signals"]))
            cols[3].metric("Token usage", f"{int(row['token_usage']):,}")
            cols[4].metric("API cost", f"${row['estimated_api_cost']:.4f}")
            cols[5].metric("Profit / $ API", f"{row['profit_per_api_dollar']:.2f}")

with tabs[1]:
    st.subheader("Live Positions")
    open_positions = positions_view[positions_view["status"].isin(["OPEN", "PARTIAL"])] if not positions_view.empty else pd.DataFrame()
    if selected_agents and not open_positions.empty:
        open_positions = open_positions[open_positions["agent_id"].isin(selected_agents)]
    if open_positions.empty:
        st.info("No live positions.")
    else:
        display = open_positions.rename(columns={"id": "position_id", "take_profit_1": "tp1", "take_profit_2": "tp2", "margin": "margin_used", "notional": "notional_exposure"})
        columns = ["position_id", "agent_id", "direction", "average_entry", "current_price", "stop_loss", "tp1", "tp2", "leverage", "margin_used", "notional_exposure", "unrealized_pnl", "risk_pct", "liq_estimate", "holding_time"]
        st.dataframe(display[[column for column in columns if column in display.columns]], width="stretch", hide_index=True)

with tabs[2]:
    st.subheader("Trade History")
    filtered = trades.copy()
    if not filtered.empty:
        if selected_agents:
            filtered = filtered[filtered["agent_id"].isin(selected_agents)]
        directions = sorted([value for value in filtered.get("direction", pd.Series(dtype=str)).dropna().unique()])
        cols = st.columns(3)
        selected_direction = cols[0].selectbox("Direction", ["All"] + directions)
        selected_outcome = cols[1].selectbox("Outcome", ["All", "Win", "Loss", "Breakeven"])
        export_scope = cols[2].selectbox("Export scope", ["Filtered", "All"])
        if selected_direction != "All":
            filtered = filtered[filtered["direction"] == selected_direction]
        pnl_values = pd.to_numeric(filtered["realized_pnl"], errors="coerce").fillna(0)
        if selected_outcome == "Win":
            filtered = filtered[pnl_values > 0]
        elif selected_outcome == "Loss":
            filtered = filtered[pnl_values < 0]
        elif selected_outcome == "Breakeven":
            filtered = filtered[pnl_values == 0]
        if isinstance(date_range, tuple) and len(date_range) == 2 and "created_at" in filtered.columns:
            created = pd.to_datetime(filtered["created_at"], utc=True, errors="coerce")
            filtered = filtered[(created.dt.date >= date_range[0]) & (created.dt.date <= date_range[1])]
    if filtered.empty:
        st.info("No trades match the current filters.")
    else:
        display = filtered.copy()
        display["outcome"] = pd.to_numeric(display["realized_pnl"], errors="coerce").fillna(0).map(lambda pnl: "Win" if pnl > 0 else "Loss" if pnl < 0 else "Open/Flat")
        display["r_multiple"] = display.apply(lambda row: r_multiple(row, positions, signals), axis=1)
        display["holding_time"] = display.apply(lambda row: trade_holding_time(row, positions), axis=1)
        st.dataframe(display, width="stretch", hide_index=True)
        download_frame("Download trades CSV", filtered if export_scope == "Filtered" else trades, "trades.csv")
        download_frame("Download ledger CSV", ledger, "LEDGER.csv")

with tabs[3]:
    st.subheader("Equity Curves")
    if curve.empty:
        st.info("No equity data yet.")
    else:
        chart_curve = curve[curve["agent_id"].isin(selected_agents)] if selected_agents else curve
        st.plotly_chart(px.line(chart_curve, x="timestamp", y="equity", color="agent_id", title="Equity over time", template="plotly_dark"), width="stretch")
        dd = drawdown_curve(chart_curve)
        if not dd.empty:
            fig_dd = px.area(dd, x="timestamp", y="drawdown", color="agent_id", title="Drawdown over time", template="plotly_dark")
            fig_dd.update_yaxes(tickformat=".1%")
            st.plotly_chart(fig_dd, width="stretch")
        daily = daily_returns(chart_curve)
        if not daily.empty:
            fig_daily = px.bar(daily, x="day", y="daily_return", color="agent_id", barmode="group", title="Daily returns", template="plotly_dark")
            fig_daily.update_yaxes(tickformat=".2%")
            st.plotly_chart(fig_daily, width="stretch")

with tabs[4]:
    st.subheader("Leaderboard")
    if metric_frame.empty:
        st.info("No leaderboard yet.")
    else:
        columns = ["agent_id", "current_equity", "total_return_pct", "sharpe_ratio", "max_drawdown", "rule_compliance", "profit_per_api_dollar", "score"]
        st.dataframe(metric_frame[columns], width="stretch", hide_index=True)
        score_fig = go.Figure()
        for component, weight in [("return", 0.40), ("sharpe", 0.20), ("drawdown", 0.20), ("compliance", 0.10), ("api", 0.10)]:
            values = []
            for _, row in metric_frame.iterrows():
                if component == "return":
                    values.append(weight * max(0, min(1, row["total_return_pct"] / 0.10)))
                elif component == "sharpe":
                    values.append(weight * max(0, min(1, row["sharpe_ratio"] / 2 if math.isfinite(row["sharpe_ratio"]) else 0)))
                elif component == "drawdown":
                    values.append(weight * max(0, min(1, 1 - row["max_drawdown"] / 0.10)))
                elif component == "compliance":
                    values.append(weight * max(0, min(1, row["rule_compliance"])))
                else:
                    values.append(weight * max(0, min(1, row["profit_per_api_dollar"] / 100 if row["profit_per_api_dollar"] > 0 else 1)))
            score_fig.add_trace(go.Bar(name=component, x=metric_frame["agent_id"], y=values))
        score_fig.update_layout(barmode="stack", title="Weighted score breakdown", yaxis_title="Score", template="plotly_dark")
        st.plotly_chart(score_fig, width="stretch")

with tabs[5]:
    render_accepted_signals_tab(str(db_path), agent_ids, date_range)

with tabs[6]:
    render_rejected_signals_tab(str(db_path), agent_ids, date_range)
    download_text("Download SIGNALS.md", signals_md, "SIGNALS.md")

with tabs[7]:
    st.subheader("Raw Model Outputs")
    if responses.empty and prompts.empty and tool_calls.empty:
        st.info("No model outputs logged yet.")
    else:
        response_view = responses.copy()
        if selected_agents and not response_view.empty:
            response_view = response_view[response_view["agent_id"].isin(selected_agents)]
        joined = response_view.merge(prompts[["id", "prompt"]] if not prompts.empty else pd.DataFrame(columns=["id", "prompt"]), left_on="prompt_id", right_on="id", how="left", suffixes=("", "_prompt"))
        st.dataframe(joined[[column for column in ["created_at", "agent_id", "prompt_id", "prompt", "raw_response", "input_tokens", "output_tokens", "estimated_cost_usd"] if column in joined.columns]], width="stretch", hide_index=True)
        st.markdown("#### Tool Calls")
        st.dataframe(tool_calls[tool_calls["agent_id"].isin(selected_agents)] if selected_agents and not tool_calls.empty else tool_calls, width="stretch", hide_index=True) if not tool_calls.empty else st.info("No tool calls logged.")
        st.markdown("#### Validation Results")
        st.dataframe(signals[["created_at", "agent_id", "decision", "action", "accepted", "reasons_json"]], width="stretch", hide_index=True) if not signals.empty else st.info("No validation records.")

with tabs[8]:
    st.subheader("Memory & Reflections")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("#### Recent reflections")
        if reflections.empty:
            st.info("No reflections yet.")
        else:
            view = reflections[reflections["agent_id"].isin(selected_agents)] if selected_agents else reflections
            st.dataframe(view.sort_values("created_at", ascending=False), width="stretch", hide_index=True)
            download_frame("Download reflections", view, "reflections.csv")
    with cols[1]:
        st.markdown("#### Lessons learned")
        if lessons.empty:
            st.info("No lessons yet.")
        else:
            view = lessons[lessons["agent_id"].isin(selected_agents)] if selected_agents else lessons
            st.dataframe(view.sort_values("created_at", ascending=False), width="stretch", hide_index=True)
            download_frame("Download lessons", view, "lessons.csv")
    st.markdown("#### Best and worst setups")
    if trades.empty:
        st.info("No setup statistics yet.")
    else:
        setup = trades.copy()
        setup["realized_pnl"] = pd.to_numeric(setup["realized_pnl"], errors="coerce").fillna(0)
        if selected_agents:
            setup = setup[setup["agent_id"].isin(selected_agents)]
        left, right = st.columns(2)
        left.dataframe(setup.sort_values("realized_pnl", ascending=False).head(5), width="stretch", hide_index=True)
        right.dataframe(setup.sort_values("realized_pnl", ascending=True).head(5), width="stretch", hide_index=True)
    st.markdown("#### Regime statistics")
    expanded = signal_payloads(signals)
    if expanded.empty or "payload_data_used" not in expanded.columns:
        st.info("No regime statistics available yet.")
    else:
        st.dataframe(expanded[["created_at", "agent_id", "payload_data_used"]].tail(50), width="stretch", hide_index=True)

with tabs[9]:
    st.subheader("Token & Cost Analytics")
    usage = api_usage(responses)
    if usage.empty:
        st.info("No token usage logged yet.")
    else:
        st.dataframe(usage, width="stretch", hide_index=True)
        daily_usage = responses.copy()
        daily_usage["day"] = pd.to_datetime(daily_usage["created_at"], utc=True, errors="coerce").dt.date
        for column in ["input_tokens", "output_tokens", "estimated_cost_usd"]:
            daily_usage[column] = pd.to_numeric(daily_usage[column], errors="coerce").fillna(0)
        grouped = daily_usage.groupby(["agent_id", "day"], as_index=False).agg(requests=("id", "count"), tokens=("input_tokens", "sum"), output_tokens=("output_tokens", "sum"), cost=("estimated_cost_usd", "sum"))
        grouped["tokens"] = grouped["tokens"] + grouped["output_tokens"]
        st.plotly_chart(px.bar(grouped, x="day", y="requests", color="agent_id", barmode="group", title="Requests per day", template="plotly_dark"), width="stretch")
        st.plotly_chart(px.bar(grouped, x="day", y="tokens", color="agent_id", barmode="group", title="Tokens per day", template="plotly_dark"), width="stretch")
        st.plotly_chart(px.line(grouped, x="day", y="cost", color="agent_id", markers=True, title="Estimated API cost", template="plotly_dark"), width="stretch")
        per_trade = metric_frame[["agent_id", "requests", "token_usage", "estimated_api_cost", "profit_per_api_dollar"]].copy()
        trade_counts = trades.groupby("agent_id").size().rename("trade_count") if not trades.empty else pd.Series(dtype=int)
        per_trade["trade_count"] = per_trade["agent_id"].map(trade_counts).fillna(0).astype(int)
        per_trade["cost_per_trade"] = per_trade.apply(lambda row: row["estimated_api_cost"] / row["trade_count"] if row["trade_count"] else 0, axis=1)
        st.dataframe(per_trade, width="stretch", hide_index=True)

with tabs[10]:
    st.subheader("API Cost Audit")
    if api_requests.empty:
        st.info("No request-level API audit rows recorded yet. New rows will appear after the next agent call.")
    else:
        audit = api_requests.copy()
        if selected_agents and "agent_name" in audit.columns:
            audit = audit[audit["agent_name"].isin(selected_agents)]
        for column in [
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "reasoning_tokens",
            "server_tool_calls",
            "server_tool_cost_usd",
            "token_cost_usd",
            "total_cost_usd",
            "latency_ms",
            "retry_count",
            "prompt_characters",
            "response_characters",
            "memory_size_characters",
            "private_lessons_count",
            "shared_lessons_count",
            "recent_trades_included",
            "reflection_characters",
            "local_tool_invocation_count",
            "cost_delta_usd",
        ]:
            if column in audit.columns:
                audit[column] = pd.to_numeric(audit[column], errors="coerce").fillna(0)
        summary = audit.groupby("agent_name", as_index=False).agg(
            requests=("id", "count"),
            total_cost_usd=("total_cost_usd", "sum"),
            avg_prompt_tokens=("prompt_tokens", "mean"),
            avg_completion_tokens=("completion_tokens", "mean"),
            max_request_cost_usd=("total_cost_usd", "max"),
            retries=("retry_count", "sum"),
            avg_prompt_characters=("prompt_characters", "mean"),
        )
        cols = st.columns(5)
        cols[0].metric("Audit Rows", f"{len(audit):,}")
        cols[1].metric("Total Cost", f"${float(audit['total_cost_usd'].sum()):.4f}")
        challenger_mask = (
            audit["agent_name"].astype(str).eq(challenger_agent_id)
            | audit["agent_name"].astype(str).str.contains("qwen|grok", case=False, na=False)
        )
        cols[2].metric(f"{challenger_short_label} Cost", f"${float(audit[challenger_mask]['total_cost_usd'].sum()):.4f}")
        cols[3].metric("Retries", f"{int(audit['retry_count'].sum())}")
        cols[4].metric("Anomalies", f"{int(audit['anomaly_flags_json'].astype(str).ne('[]').sum())}" if "anomaly_flags_json" in audit.columns else "0")

        st.markdown("#### Agent comparison")
        st.dataframe(summary, width="stretch", hide_index=True)

        diagnosis = []
        grok_rows = audit[challenger_mask]
        deepseek_rows = audit[audit["agent_name"].astype(str).str.contains("deepseek", case=False, na=False)]
        grok_cost = float(grok_rows["total_cost_usd"].sum()) if not grok_rows.empty else 0.0
        deepseek_cost = float(deepseek_rows["total_cost_usd"].sum()) if not deepseek_rows.empty else 0.0
        if deepseek_cost and grok_cost > deepseek_cost * 3:
            diagnosis.append(f"{challenger_short_label} audit cost is {grok_cost / deepseek_cost:.1f}x DeepSeek.")
        if not grok_rows.empty and "anomaly_flags_json" in grok_rows.columns:
            grok_flags = " ".join(grok_rows["anomaly_flags_json"].astype(str).tolist())
            if "prompt_size_gt_2x_previous" in grok_flags:
                diagnosis.append(f"{challenger_short_label} prompt size more than doubled between adjacent requests.")
            if "tokens_gt_3x_previous" in grok_flags:
                diagnosis.append(f"{challenger_short_label} token count exceeded 3x its previous request.")
            if "cost_gt_3x_previous" in grok_flags:
                diagnosis.append(f"{challenger_short_label} request cost exceeded 3x its previous request.")
            if "retry_count_gt_0" in grok_flags:
                diagnosis.append(f"{challenger_short_label} had retries, which can multiply provider-side spend.")
            if "server_tool_cost_gt_0" in grok_flags:
                diagnosis.append(f"{challenger_short_label} has recorded server-side tool cost.")
        if not diagnosis:
            diagnosis.append("No local audit anomaly has been recorded yet; compare provider billing for hidden reasoning or server-side charges.")
        st.markdown("#### Root cause diagnosis")
        for item in diagnosis:
            st.write(f"- {item}")

        timeline = audit.sort_values("timestamp") if "timestamp" in audit.columns else audit
        st.plotly_chart(px.line(timeline, x="timestamp", y="total_cost_usd", color="agent_name", markers=True, title="Cost spike timeline", template="plotly_dark"), width="stretch")
        st.plotly_chart(px.line(timeline, x="timestamp", y="prompt_characters", color="agent_name", markers=True, title="Prompt size timeline", template="plotly_dark"), width="stretch")

        retry_stats = audit.groupby(["agent_name", "request_type"], as_index=False).agg(requests=("id", "count"), retries=("retry_count", "sum"), avg_latency_ms=("latency_ms", "mean"))
        st.markdown("#### Retry statistics")
        st.dataframe(retry_stats, width="stretch", hide_index=True)

        st.markdown("#### Top most expensive requests")
        display_cols = [
            "timestamp",
            "cycle_number",
            "agent_name",
            "model_name",
            "actual_model_name",
            "request_type",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "total_cost_usd",
            "retry_count",
            "prompt_characters",
            "response_characters",
            "private_lessons_count",
            "shared_lessons_count",
            "recent_trades_included",
            "local_tool_invocation_count",
            "anomaly_flags_json",
            "error_message",
        ]
        st.dataframe(audit.sort_values("total_cost_usd", ascending=False)[[column for column in display_cols if column in audit.columns]].head(50), width="stretch", hide_index=True)

        st.markdown("#### Cost breakdown by component")
        breakdown_rows = []
        if "cost_breakdown_json" in audit.columns:
            for _, row in audit.iterrows():
                payload = safe_json(row.get("cost_breakdown_json"), {})
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        breakdown_rows.append({"agent_name": row.get("agent_name"), "component": key, "cost_usd": float(value or 0)})
        if breakdown_rows:
            breakdown = pd.DataFrame(breakdown_rows)
            breakdown_summary = breakdown.groupby(["agent_name", "component"], as_index=False)["cost_usd"].sum().sort_values("cost_usd", ascending=False)
            st.dataframe(breakdown_summary, width="stretch", hide_index=True)
            st.plotly_chart(px.bar(breakdown_summary, x="component", y="cost_usd", color="agent_name", barmode="group", title="Cost breakdown by component", template="plotly_dark"), width="stretch")
        else:
            st.info("No component cost breakdown rows yet.")

        st.markdown("#### Per-request table")
        st.dataframe(audit[[column for column in display_cols + ["prompt_hash", "response_hash"] if column in audit.columns]].sort_values("timestamp", ascending=False), width="stretch", hide_index=True)
        download_frame("Download API request audit CSV", audit, "api_requests.csv")

with tabs[11]:
    st.subheader("Workload Attribution")
    if workload_cycles.empty:
        st.info("No workload cycles recorded yet. Run `python -m src.cli run-once` or `python -m src.cli analyze-workload` after a cycle.")
    else:
        cycles = workload_cycles.copy()
        cycles["timestamp"] = pd.to_datetime(cycles["timestamp"], utc=True, errors="coerce")
        cycles = cycles.sort_values("timestamp", ascending=False)
        latest = cycles.iloc[0]
        total_api_cost = float(cycles["deepseek_cost_usd"].sum() + cycles["grok_cost_usd"].sum())
        profit_per_cost = float(metric_frame["profit_per_api_dollar"].replace([float("inf"), -float("inf")], 0).mean()) if not metric_frame.empty else 0.0
        kpis = st.columns(5)
        kpis[0].metric("Local Machine", f"{float(latest['local_workload_pct']):.1f}%")
        kpis[1].metric("DeepSeek", f"{float(latest['deepseek_workload_pct']):.1f}%")
        kpis[2].metric(challenger_short_label, f"{float(latest['grok_workload_pct']):.1f}%")
        kpis[3].metric("Total API Cost", f"${total_api_cost:.4f}")
        kpis[4].metric("Profit / $ API", f"{profit_per_cost:.2f}")
        st.info(
            "The local machine is currently performing "
            f"{float(latest['local_workload_pct']):.1f}% of the total workload. "
            f"DeepSeek contributes {float(latest['deepseek_workload_pct']):.1f}% and "
            f"{challenger_short_label} contributes {float(latest['grok_workload_pct']):.1f}%."
        )

        split = pd.DataFrame(
            [
                {"component": "Local Machine", "workload_pct": float(latest["local_workload_pct"])},
                {"component": "DeepSeek", "workload_pct": float(latest["deepseek_workload_pct"])},
                {"component": challenger_short_label, "workload_pct": float(latest["grok_workload_pct"])},
            ]
        )
        chart_cols = st.columns(2)
        chart_cols[0].plotly_chart(px.pie(split, names="component", values="workload_pct", hole=0.55, title="Current workload split", template="plotly_dark"), width="stretch")
        trend = cycles.sort_values("timestamp")
        trend_long = trend.melt(
            id_vars=["timestamp"],
            value_vars=["local_workload_pct", "deepseek_workload_pct", "grok_workload_pct"],
            var_name="component",
            value_name="workload_pct",
        )
        trend_long["component"] = trend_long["component"].replace(
            {
                "local_workload_pct": "Local Machine",
                "deepseek_workload_pct": "DeepSeek",
                "grok_workload_pct": challenger_short_label,
            }
        )
        chart_cols[1].plotly_chart(px.line(trend_long, x="timestamp", y="workload_pct", color="component", markers=True, title="Historical workload percentages", template="plotly_dark"), width="stretch")

        token_trend = trend[["timestamp", "deepseek_tokens", "grok_tokens"]].melt(id_vars=["timestamp"], var_name="agent", value_name="tokens")
        latency_trend = trend[["timestamp", "local_wall_time_seconds", "deepseek_latency_seconds", "grok_latency_seconds"]].melt(id_vars=["timestamp"], var_name="component", value_name="seconds")
        cost_trend = trend[["timestamp", "deepseek_cost_usd", "grok_cost_usd"]].melt(id_vars=["timestamp"], var_name="agent", value_name="cost_usd")
        token_trend["agent"] = token_trend["agent"].replace({"deepseek_tokens": "DeepSeek", "grok_tokens": challenger_short_label})
        latency_trend["component"] = latency_trend["component"].replace(
            {
                "local_wall_time_seconds": "Local Machine",
                "deepseek_latency_seconds": "DeepSeek",
                "grok_latency_seconds": challenger_short_label,
            }
        )
        cost_trend["agent"] = cost_trend["agent"].replace({"deepseek_cost_usd": "DeepSeek", "grok_cost_usd": challenger_short_label})
        st.plotly_chart(px.bar(token_trend, x="timestamp", y="tokens", color="agent", barmode="group", title="Token usage trends", template="plotly_dark"), width="stretch")
        st.plotly_chart(px.line(latency_trend, x="timestamp", y="seconds", color="component", markers=True, title="Latency trends", template="plotly_dark"), width="stretch")
        st.plotly_chart(px.line(cost_trend, x="timestamp", y="cost_usd", color="agent", markers=True, title="API cost trends", template="plotly_dark"), width="stretch")

        st.markdown("#### Per-cycle breakdown")
        display_cols = [
            "timestamp",
            "local_workload_pct",
            "deepseek_workload_pct",
            "grok_workload_pct",
            "local_wall_time_seconds",
            "deepseek_latency_seconds",
            "grok_latency_seconds",
            "deepseek_tokens",
            "grok_tokens",
            "deepseek_cost_usd",
            "grok_cost_usd",
        ]
        st.dataframe(cycles[[column for column in display_cols if column in cycles.columns]], width="stretch", hide_index=True)
        download_frame("Download workload cycles CSV", cycles, "workload_cycles.csv")

        st.markdown("#### Per-category breakdown")
        if workload_components.empty:
            st.info("No workload component rows yet.")
        else:
            components = workload_components.copy()
            components["timestamp"] = pd.to_datetime(components["timestamp"], utc=True, errors="coerce")
            category_summary = components.groupby(["owner", "category", "metric_name"], as_index=False)["metric_value"].sum().sort_values("metric_value", ascending=False)
            st.dataframe(category_summary, width="stretch", hide_index=True)
            st.markdown("#### Top most expensive tasks")
            expensive = components[components["metric_name"].isin(["latency_seconds", "api_cost_usd"])].sort_values("metric_value", ascending=False).head(20)
            st.dataframe(expensive, width="stretch", hide_index=True)
            download_frame("Download workload components CSV", components, "workload_components.csv")

with tabs[12]:
    st.subheader("Strategy Diversity")
    if diversity_metrics.empty:
        st.info("No diversity metrics yet. Run `python -m src.cli analyze-diversity` or a competition cycle.")
    else:
        latest = diversity_metrics.sort_values("created_at", ascending=False).iloc[0]
        cols = st.columns(5)
        cols[0].metric("Action agreement", fmt_pct(latest.get("action_agreement_rate")))
        cols[1].metric("Direction agreement", fmt_pct(latest.get("directional_agreement_rate")))
        cols[2].metric("Leverage similarity", fmt_pct(latest.get("leverage_similarity")))
        cols[3].metric("Confidence corr.", f"{float(latest.get('confidence_correlation') or 0):.2f}")
        cols[4].metric("Shared ratio", fmt_pct(latest.get("shared_ratio_applied")))
        if int(latest.get("convergence_warning") or 0):
            st.error("Convergence warning: shared lessons are reduced and private memory should dominate.")
        else:
            st.success("Strategy diversity is within the configured threshold.")
        st.dataframe(diversity_metrics.sort_values("created_at", ascending=False), width="stretch", hide_index=True)

    st.markdown("#### Strategy Profiles")
    if strategy_profiles.empty:
        st.info("No profiles stored yet.")
    else:
        profile_rows = []
        for _, row in strategy_profiles.iterrows():
            payload = safe_json(row.get("profile_json"), {})
            profile_rows.append({"agent_id": row.get("agent_id"), **payload})
        st.dataframe(pd.DataFrame(profile_rows), width="stretch", hide_index=True)

    st.markdown("#### Shared Knowledge Base")
    if shared_lessons.empty:
        st.info("No promoted shared lessons yet.")
    else:
        st.dataframe(shared_lessons.sort_values("promoted_at", ascending=False), width="stretch", hide_index=True)
        download_frame("Download shared lessons CSV", shared_lessons, "shared_lessons.csv")

    st.markdown("#### Unique Private Lessons")
    if lessons.empty:
        st.info("No private lessons recorded yet.")
    else:
        for agent_id in selected_agents or agent_ids:
            agent_lessons = lessons[lessons["agent_id"] == agent_id].sort_values("created_at", ascending=False).head(8)
            with st.expander(agent_names.get(agent_id, agent_id), expanded=False):
                if agent_lessons.empty:
                    st.caption("No lessons yet.")
                else:
                    for _, row in agent_lessons.iterrows():
                        st.write(f"- {row.get('content')}")

    st.markdown("#### Lesson Promotion Audit")
    if lesson_promotions.empty:
        st.info("No promotion attempts recorded yet.")
    else:
        st.dataframe(lesson_promotions.sort_values("created_at", ascending=False).head(200), width="stretch", hide_index=True)

with tabs[13]:
    render_pending_orders_tab(db_path, selected_agents or agent_ids)

with tabs[14]:
    render_risk_automation_tab(db_path, positions)

with tabs[15]:
    render_api_failover_tab(db_path)

with tabs[16]:
    st.subheader("Configuration")
    st.markdown("#### Deployment & Versions")
    render_deployment_panel(deployment_state)
    config_cols = st.columns(2)
    with config_cols[0]:
        st.markdown("#### Active settings")
        st.json(
            {
                "models": agent_models,
                "symbol": settings.competition.display_symbol,
                "chart_timeframe": chart_timeframe,
                "poll_interval_seconds": settings.competition.poll_interval_seconds,
                "competition_duration_days": settings.competition.duration_days,
                "initial_equity": settings.accounts.initial_equity,
                "risk": settings.risk.model_dump(),
                "market": settings.market.model_dump(),
                "shared_learning": settings.shared_learning.model_dump(),
                "hot_reload": settings.hot_reload.model_dump(),
                "features": safe_features(settings).model_dump(),
                "canary": safe_canary(settings).model_dump(),
                "feature_flags": {name: flag.model_dump() for name, flag in settings.feature_flags.items()},
            }
        )
    with config_cols[1]:
        st.markdown("#### Runtime controls")
        control_cols = st.columns(2)
        with control_cols[0]:
            if st.button("Reload Config", width="stretch"):
                command_id = queue_control_command(str(db_path), "reload-config", {"source": "dashboard"})
                st.success(f"Queued reload command {command_id}.")
                st.cache_data.clear()
        with control_cols[1]:
            if st.button("Rollback Config", width="stretch"):
                command_id = queue_control_command(str(db_path), "rollback-config", {"source": "dashboard"})
                st.warning(f"Queued rollback command {command_id}.")
                st.cache_data.clear()
        latest_config = config_versions.sort_values("created_at", ascending=False).iloc[0] if not config_versions.empty else None
        if latest_config is not None:
            st.caption(f"Active config: {str(latest_config.get('version_hash', ''))[:12]} · code: {latest_config.get('code_version', '')}")
        pending = control_commands[control_commands["status"] == "PENDING"] if not control_commands.empty and "status" in control_commands.columns else pd.DataFrame()
        if not pending.empty:
            st.caption(f"Pending control commands: {len(pending)}")
        st.markdown("#### Rulebook summary")
        st.markdown(
            f"""
            - Paper trading only, no exchange API keys, no real orders.
            - BTCUSDT perpetual futures only.
            - Starting equity: {fmt_money(initial_equity)} per agent.
            - Maximum leverage: {settings.risk.max_leverage:g}x.
            - Max margin per OPEN/ADD/DCA: {settings.risk.max_margin_per_action_pct * 100:.1f}% equity.
            - Max total account risk: {settings.risk.max_total_account_risk_pct * 100:.1f}% equity.
            - Max open positions: {settings.risk.max_open_positions}.
            - Max DCA per position: {settings.risk.max_dca_per_position}.
            - Daily loss limit: {settings.risk.daily_loss_limit_pct * 100:.1f}%.
            - TP1 RR >= {settings.risk.min_rr_tp1:g}; TP2 RR >= {settings.risk.min_rr_tp2:g}.
            """
        )
    with st.expander("Full rulebook"):
        st.markdown(rulebook_md or "Rulebook file is empty or missing.")
    with st.expander("Evaluation report"):
        st.markdown(evaluation_md or "No evaluation report yet.")
    with st.expander("Health checks"):
        if health_checks.empty:
            st.info("No health checks recorded yet.")
        else:
            st.dataframe(health_checks.sort_values("created_at", ascending=False).head(50), width="stretch", hide_index=True)
    with st.expander("Crash-safe checkpoints"):
        if checkpoints.empty:
            st.info("No checkpoints recorded yet.")
        else:
            st.dataframe(checkpoints.sort_values("created_at", ascending=False).head(50), width="stretch", hide_index=True)
    with st.expander("Downtime history"):
        if downtime_events.empty:
            st.info("No downtime events recorded yet.")
        else:
            st.dataframe(downtime_events.sort_values("ended_at", ascending=False).head(50), width="stretch", hide_index=True)
    with st.expander("Buy-and-hold benchmark"):
        if benchmarks.empty:
            st.info("No benchmark records yet.")
        else:
            st.dataframe(benchmarks.sort_values("created_at", ascending=False).head(50), width="stretch", hide_index=True)
    with st.expander("Prompt versions"):
        if prompt_versions.empty:
            st.info("No prompt versions recorded yet.")
        else:
            st.dataframe(prompt_versions.sort_values("created_at", ascending=False).head(50), width="stretch", hide_index=True)
    with st.expander("Configuration versions"):
        if config_versions.empty:
            st.info("No config versions recorded yet.")
        else:
            st.dataframe(config_versions.sort_values("created_at", ascending=False).head(50), width="stretch", hide_index=True)
    with st.expander("Control commands"):
        if control_commands.empty:
            st.info("No control commands recorded yet.")
        else:
            st.dataframe(control_commands.sort_values("created_at", ascending=False).head(50), width="stretch", hide_index=True)
    export_cols = st.columns(3)
    with export_cols[0]:
        download_text("Download evaluation", evaluation_md, "EVALUATION.md")
    with export_cols[1]:
        download_text("Download rulebook", rulebook_md, "rulebook.md")
    with export_cols[2]:
        download_frame("Download metrics CSV", metric_frame, "arena_metrics.csv")
