from __future__ import annotations

import html
import os
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st


PHASE_LABELS = {
    "FETCHING_DATA": "Fetching Data",
    "MANAGING_POSITIONS": "Managing Positions",
    "BUILDING_PROMPTS": "Building Prompts",
    "CALLING_DEEPSEEK": "Calling DeepSeek",
    "CALLING_QWEN": "Calling Qwen",
    "CALLING_GROK": "Calling Grok",
    "VALIDATING_SIGNALS": "Validating Signals",
    "EXECUTING_TRADES": "Executing Trades",
    "POST_PROCESSING": "Post Processing",
    "WRITING_MEMORY": "Writing Memory",
    "WRITING_OUTPUTS": "Writing Outputs",
    "CHECKPOINTING": "Checkpointing",
    "EXPORTING_SNAPSHOT": "Exporting Snapshot",
    "SYNCING_GITHUB": "Syncing GitHub",
    "WAITING": "Waiting",
    "ERROR": "Error",
}


def render_cycle_status(runner: dict[str, Any]) -> None:
    """Render a compact operational cycle status bar."""
    runner = runner if isinstance(runner, dict) else {}
    if hasattr(st, "fragment"):
        _fragment_runner(runner)
    else:
        _render_cycle_status_inner(runner)


def _render_cycle_status_fragment(runner: dict[str, Any]) -> None:
    _render_cycle_status_inner(runner)


_fragment_runner = st.fragment(run_every="1s")(_render_cycle_status_fragment) if hasattr(st, "fragment") else _render_cycle_status_fragment


def _render_cycle_status_inner(runner: dict[str, Any]) -> None:
    with st.container():
        status = str(runner.get("status") or "N/A").upper()
        raw_phase = str(runner.get("phase") or "").upper()
        phase = _phase_label(raw_phase)
        next_cycle_at = _parse_time(runner.get("next_cycle_at"))
        next_in, overdue = _countdown(next_cycle_at, raw_phase)
        fields = [
            _field("Status", _status_badge(status), "Runner process state", raw=True),
            _field("Cycle #", _prefixed_number(runner.get("cycle_number")), "Current cycle number"),
            _field("Phase", phase, "Current pipeline stage"),
            _field("Last Duration", _seconds(runner.get("last_cycle_duration_seconds")), "Time taken by previous cycle"),
            _field("Next Cycle In", next_in, "Countdown to next scheduled cycle", value_class="cycle-status-overdue" if overdue else ""),
            _field("Next Run Time", _time_only(next_cycle_at), "Next scheduled run time"),
            _field("Total Cycles", _number(runner.get("total_cycles_completed")), "Total completed cycles"),
        ]
        st.markdown(_css(), unsafe_allow_html=True)
        st.markdown(
            f"""
            <section class="cycle-status-card" aria-label="Cycle status">
                {''.join(fields)}
            </section>
            """,
            unsafe_allow_html=True,
        )


def _css() -> str:
    return """
    <style>
        .cycle-status-card {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 12px;
            width: 100%;
            min-height: 84px;
            margin: 4px 0 12px 0;
            padding: 16px 20px;
            border: 1px solid rgba(148, 163, 184, .25);
            border-radius: 8px;
            background: rgba(15, 23, 42, .18);
            box-sizing: border-box;
        }
        .cycle-status-item {
            min-width: 0;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 5px;
        }
        .cycle-status-label {
            color: #94a3b8;
            font-size: 11px;
            font-weight: 650;
            letter-spacing: .03em;
            line-height: 1.15;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .cycle-status-value {
            color: #f8fafc;
            font-size: 24px;
            font-weight: 800;
            line-height: 1.05;
            letter-spacing: 0;
            overflow-wrap: anywhere;
        }
        .cycle-status-badge {
            display: inline-flex;
            align-items: center;
            width: fit-content;
            max-width: 100%;
            padding: 5px 10px;
            border-radius: 999px;
            font-size: 14px;
            font-weight: 800;
            line-height: 1;
            letter-spacing: .02em;
            white-space: nowrap;
        }
        .cycle-status-running {
            color: #22c55e;
            background: rgba(34, 197, 94, .14);
            border: 1px solid rgba(34, 197, 94, .28);
        }
        .cycle-status-waiting {
            color: #38bdf8;
            background: rgba(56, 189, 248, .14);
            border: 1px solid rgba(56, 189, 248, .28);
        }
        .cycle-status-error {
            color: #ef4444;
            background: rgba(239, 68, 68, .14);
            border: 1px solid rgba(239, 68, 68, .30);
        }
        .cycle-status-offline,
        .cycle-status-na {
            color: #94a3b8;
            background: rgba(148, 163, 184, .12);
            border: 1px solid rgba(148, 163, 184, .22);
        }
        .cycle-status-overdue {
            color: #ef4444;
        }
        @media (max-width: 1200px) {
            .cycle-status-card { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        }
        @media (max-width: 760px) {
            .cycle-status-card {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                padding: 14px 16px;
            }
            .cycle-status-value { font-size: 21px; }
        }
        @media (max-width: 420px) {
            .cycle-status-card { grid-template-columns: 1fr; }
        }
    </style>
    """


def _field(label: str, value: str, tooltip: str, value_class: str = "", raw: bool = False) -> str:
    safe_label = html.escape(label)
    safe_tooltip = html.escape(tooltip)
    safe_value = value if raw else html.escape(value)
    classes = "cycle-status-value" + (f" {value_class}" if value_class else "")
    return (
        f'<div class="cycle-status-item" title="{safe_tooltip}">'
        f'<div class="cycle-status-label">{safe_label}</div>'
        f'<div class="{classes}">{safe_value}</div>'
        "</div>"
    )


def _status_badge(status: str) -> str:
    key = status.lower()
    if key not in {"running", "waiting", "error", "offline"}:
        key = "na"
    return f'<span class="cycle-status-badge cycle-status-{key}">{html.escape(status)}</span>'


def _phase_label(value: Any) -> str:
    phase = str(value or "").upper()
    return PHASE_LABELS.get(phase, "N/A" if not phase else phase.replace("_", " ").title())


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _countdown(next_cycle_at: datetime | None, phase: str = "") -> tuple[str, bool]:
    if phase and phase not in {"WAITING", "ERROR", "OFFLINE"}:
        return "TRADING", False
    if not next_cycle_at:
        return "N/A", False
    remaining = int((next_cycle_at - datetime.now(UTC)).total_seconds())
    if remaining < 0:
        return "OVERDUE", True
    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}", False
    return f"{minutes:02d}:{seconds:02d}", False


def _time_only(value: datetime | None) -> str:
    if not value:
        return "N/A"
    local = value.astimezone(ZoneInfo(os.getenv("ARENA_DISPLAY_TIMEZONE", "Asia/Bangkok")))
    return local.strftime("%H:%M:%S")


def _seconds(value: Any) -> str:
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return "N/A"


def _number(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "N/A"


def _prefixed_number(value: Any) -> str:
    number = _number(value)
    return f"#{number}" if number != "N/A" else number
