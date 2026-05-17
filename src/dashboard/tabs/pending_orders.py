from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


def render_pending_orders_tab(db_path: Path, agent_ids: list[str]) -> None:
    st.subheader("Pending Orders")
    if not db_path.exists():
        st.info("Database not found.")
        return
    with sqlite3.connect(db_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT id, agent_id, status, created_at, expires_at, triggered_at, position_id
            FROM pending_orders
            ORDER BY created_at DESC
            LIMIT 200
            """,
            connection,
        )
    if frame.empty:
        st.info("No pending orders recorded.")
        return
    if agent_ids:
        frame = frame[frame["agent_id"].isin(agent_ids)]
    st.dataframe(frame, width="stretch", hide_index=True)
    with st.expander("Trigger payloads (latest 5)"):
        with sqlite3.connect(db_path) as connection:
            rows = connection.execute(
                "SELECT id, trigger_json, execution_signal_json FROM pending_orders ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        for row in rows:
            st.markdown(f"**{row[0]}**")
            st.json({"trigger": json.loads(row[1] or "{}"), "execution": json.loads(row[2] or "{}")})
