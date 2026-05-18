from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from src.trading.risk_automation.pending_order_view import pending_order_view


def render_pending_orders_tab(db_path: Path, agent_ids: list[str]) -> None:
    st.subheader("Pending Orders")
    if not db_path.exists():
        st.info("Database not found.")
        return
    with sqlite3.connect(db_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT id, agent_id, status, created_at, expires_at, triggered_at, position_id, trigger_json, execution_signal_json
            FROM pending_orders
            ORDER BY CASE status WHEN 'PENDING' THEN 0 ELSE 1 END, created_at DESC
            LIMIT 200
            """,
            connection,
        )
    if frame.empty:
        st.info("No pending orders recorded.")
        return
    if agent_ids:
        frame = frame[frame["agent_id"].isin(agent_ids)]
    views = [_view_from_record(record) for record in frame.to_dict("records")]
    display = pd.DataFrame(views)
    _summary_cards(display)
    columns = [
        "intent",
        "id",
        "agent_id",
        "status",
        "action",
        "direction",
        "entry_price",
        "stop_loss",
        "take_profit_1",
        "leverage",
        "trigger_summary",
        "thesis",
        "created_at",
        "expires_at",
        "triggered_at",
        "position_id",
    ]
    st.dataframe(display[[column for column in columns if column in display.columns]], width="stretch", hide_index=True)
    st.markdown("#### Order details")
    for row in views[:50]:
        _order_expander(row)


def _view_from_record(record: dict) -> dict:
    return pending_order_view(
        order_id=str(record.get("id") or ""),
        agent_id=str(record.get("agent_id") or ""),
        status=str(record.get("status") or ""),
        created_at=record.get("created_at"),
        expires_at=record.get("expires_at"),
        triggered_at=record.get("triggered_at"),
        position_id=record.get("position_id"),
        trigger_json=record.get("trigger_json"),
        execution_signal_json=record.get("execution_signal_json"),
    )


def _summary_cards(display: pd.DataFrame) -> None:
    pending = display[display["status"].astype(str).str.upper() == "PENDING"] if not display.empty else display
    open_long = int(((pending["action"] == "OPEN") & (pending["direction"] == "LONG")).sum()) if not pending.empty else 0
    open_short = int(((pending["action"] == "OPEN") & (pending["direction"] == "SHORT")).sum()) if not pending.empty else 0
    close_orders = int(pending["action"].isin(["CLOSE", "CUT", "REDUCE"]).sum()) if not pending.empty else 0
    expiring_soon = 0
    if not pending.empty and "expires_at" in pending.columns:
        expires = pd.to_datetime(pending["expires_at"], utc=True, errors="coerce")
        now = pd.Timestamp.now(tz="UTC")
        expiring_soon = int(((expires.notna()) & (expires <= now + pd.Timedelta(hours=6))).sum())
    cols = st.columns(4)
    cols[0].metric("Pending OPEN LONG", open_long)
    cols[1].metric("Pending OPEN SHORT", open_short)
    cols[2].metric("Pending CLOSE/REDUCE", close_orders)
    cols[3].metric("Expiring soon", expiring_soon)


def _order_expander(row: dict) -> None:
    intent = row.get("intent") or "-"
    accent = "#22c55e" if "LONG" in intent else "#ef4444" if "SHORT" in intent else "#94a3b8"
    st.markdown(
        f"<span style='border-left:4px solid {accent};padding:4px 8px;background:rgba(15,23,42,.18);border-radius:6px;font-weight:700'>{intent}</span>",
        unsafe_allow_html=True,
    )
    with st.expander(f"{row.get('id')} | {row.get('trigger_summary')} | {row.get('status')}", expanded=False):
        st.markdown(f"**Thesis:** {row.get('thesis') or '-'}")
        st.markdown("**Full trigger conditions**")
        st.json(row.get("trigger_conditions") or {})
        st.markdown("**Raw normalized signal JSON**")
        st.json(row.get("normalized_signal") or {})
        st.markdown("**Validation details**")
        st.json(row.get("validation_details") or {})
