from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


def render_api_failover_tab(db_path: Path) -> None:
    st.subheader("API Failover Events")
    if not db_path.exists():
        st.info("Database not found.")
        return
    with sqlite3.connect(db_path) as connection:
        events = pd.read_sql_query(
            """
            SELECT agent_id, event_type, from_provider, from_model, to_provider, to_model, message, created_at
            FROM api_failover_events
            ORDER BY created_at DESC
            LIMIT 100
            """,
            connection,
        )
        states = pd.read_sql_query(
            "SELECT agent_id, active_provider, active_model, using_fallback, primary_available, fallback_index, updated_at FROM agent_failover_state",
            connection,
        )
    st.markdown("#### Active routes")
    if states.empty:
        st.info("All agents on primary models.")
    else:
        st.dataframe(states, width="stretch", hide_index=True)
    st.markdown("#### Recent events")
    if events.empty:
        st.info("No failover events recorded.")
    else:
        st.dataframe(events, width="stretch", hide_index=True)
