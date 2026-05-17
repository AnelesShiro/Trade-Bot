from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


def render_risk_automation_tab(db_path: Path, positions: pd.DataFrame) -> None:
    st.subheader("Risk Automation")
    if not db_path.exists():
        st.info("Database not found.")
        return
    with sqlite3.connect(db_path) as connection:
        risk = pd.read_sql_query(
            "SELECT position_id, config_json, state_json, updated_at FROM position_risk_state ORDER BY updated_at DESC LIMIT 200",
            connection,
        )
        cooldowns = pd.read_sql_query(
            "SELECT agent_id, reason, started_at, ends_at FROM cooldown_state WHERE active = 1",
            connection,
        )
        notifications = pd.read_sql_query(
            "SELECT created_at, agent_id, event_type, severity, message FROM risk_notifications ORDER BY created_at DESC LIMIT 100",
            connection,
        )
    if not risk.empty and not positions.empty:
        risk = risk.merge(positions[["id", "agent_id", "status", "stop_loss"]], left_on="position_id", right_on="id", how="left")
    if risk.empty:
        st.info("No automated risk state yet.")
    else:
        display = risk.copy()
        for column in ("config_json", "state_json"):
            if column in display.columns:
                display[column] = display[column].apply(lambda value: _short_json(value))
        st.dataframe(display, width="stretch", hide_index=True)
    st.subheader("Active Cooldowns")
    if cooldowns.empty:
        st.success("No active entry cooldowns.")
    else:
        st.dataframe(cooldowns, width="stretch", hide_index=True)
    st.subheader("Risk Notifications")
    if notifications.empty:
        st.info("No risk automation notifications yet.")
    else:
        st.dataframe(notifications, width="stretch", hide_index=True)


def _short_json(value: str) -> str:
    try:
        payload = json.loads(value or "{}")
        return json.dumps(payload, separators=(",", ":"))[:240]
    except Exception:
        return str(value)[:240]
