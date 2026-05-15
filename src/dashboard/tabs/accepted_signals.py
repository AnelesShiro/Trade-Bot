from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


def render_accepted_signals_tab(database: str, agent_ids: list[str], default_date_range) -> None:
    st.subheader("Accepted Signals")
    filters = _filters(database, agent_ids, default_date_range, "accepted")
    summary = _summary(database, filters, "ACCEPTED")
    total = int(summary.get("total") or 0)
    accepted_all = int(summary.get("accepted_all") or 0)
    rejected_all = int(summary.get("rejected_all") or 0)
    all_signals = accepted_all + rejected_all
    cols = st.columns(5)
    cols[0].metric("Total accepted", f"{total:,}")
    cols[1].metric("Acceptance rate", f"{(accepted_all / all_signals * 100) if all_signals else 0:.1f}%")
    cols[2].metric("Accepted by agent", _agent_counts(summary.get("by_agent", {})))
    cols[3].metric("Avg confidence", f"{float(summary.get('avg_confidence') or 0):.2f}")
    cols[4].metric("Avg expected R:R", f"{float(summary.get('avg_rr') or 0):.2f}")

    page_size = st.selectbox("Rows per page", [25, 50, 100, 250], index=1, key="accepted_page_size")
    max_page = max(1, (total + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=max_page, value=1, step=1, key="accepted_page")
    rows = _rows(database, filters, "ACCEPTED", int(page_size), (int(page) - 1) * int(page_size))
    if rows.empty:
        st.info("No accepted signals match the current filters.")
        return
    rows["executed"] = rows["execution_result_json"].apply(lambda value: "Yes" if _safe_json(value, {}).get("executed") else "No")
    display_columns = [
        "timestamp_utc",
        "cycle_number",
        "agent_name",
        "direction",
        "action",
        "confidence",
        "entry_price",
        "stop_loss",
        "take_profit_1",
        "risk_pct",
        "leverage",
        "expected_rr",
        "signal_status",
        "executed",
    ]
    st.dataframe(rows[[column for column in display_columns if column in rows.columns]], width="stretch", hide_index=True)
    _details(rows, accepted=True)


def _filters(database: str, agent_ids: list[str], default_date_range, prefix: str) -> dict[str, Any]:
    meta = _filter_meta(database)
    cols = st.columns(4)
    selected_agents = cols[0].multiselect("Agent", options=agent_ids, default=agent_ids, key=f"{prefix}_agents")
    selected_direction = cols[1].selectbox("Direction", ["All"] + meta.get("directions", []), key=f"{prefix}_direction")
    selected_action = cols[2].selectbox("Action", ["All"] + meta.get("actions", []), key=f"{prefix}_action")
    confidence = cols[3].slider("Confidence", 1, 5, (1, 5), key=f"{prefix}_confidence")
    cols = st.columns(4)
    selected_dates = cols[0].date_input("Date range", value=default_date_range, key=f"{prefix}_date_range")
    min_cycle, max_cycle = meta.get("cycle_min", 0), meta.get("cycle_max", 0)
    if max_cycle > min_cycle:
        cycle_range = cols[1].slider("Cycle range", min_cycle, max_cycle, (min_cycle, max_cycle), key=f"{prefix}_cycle")
    else:
        cols[1].caption("Cycle range unavailable")
        cycle_range = (min_cycle, max_cycle)
    search = cols[2].text_input("Search text", key=f"{prefix}_search")
    return {
        "agents": selected_agents,
        "direction": selected_direction,
        "action": selected_action,
        "confidence": confidence,
        "dates": selected_dates,
        "cycle_range": cycle_range,
        "search": search,
    }


def _rows(database: str, filters: dict[str, Any], status: str, limit: int, offset: int) -> pd.DataFrame:
    where, params = _where(filters, status)
    query = f"""
        select *
        from signals
        where {where}
        order by coalesce(timestamp_utc, created_at) desc, id desc
        limit ? offset ?
    """
    with sqlite3.connect(database) as connection:
        frame = pd.read_sql_query(query, connection, params=[*params, limit, offset])
    return frame


def _summary(database: str, filters: dict[str, Any], status: str) -> dict[str, Any]:
    where, params = _where(filters, status)
    with sqlite3.connect(database) as connection:
        total = connection.execute(f"select count(*) from signals where {where}", params).fetchone()[0]
        avg = connection.execute(f"select avg(confidence), avg(expected_rr) from signals where {where}", params).fetchone()
        by_agent = connection.execute(f"select coalesce(agent_name, agent_id), count(*) from signals where {where} group by coalesce(agent_name, agent_id)", params).fetchall()
        accepted_all = connection.execute("select count(*) from signals where coalesce(signal_status, case when accepted=1 then 'ACCEPTED' else 'REJECTED' end)='ACCEPTED'").fetchone()[0]
        rejected_all = connection.execute("select count(*) from signals where coalesce(signal_status, case when accepted=1 then 'ACCEPTED' else 'REJECTED' end)='REJECTED'").fetchone()[0]
    return {
        "total": total,
        "avg_confidence": avg[0],
        "avg_rr": avg[1],
        "by_agent": {str(agent): int(count) for agent, count in by_agent},
        "accepted_all": accepted_all,
        "rejected_all": rejected_all,
    }


def _where(filters: dict[str, Any], status: str) -> tuple[str, list[Any]]:
    clauses = ["coalesce(signal_status, case when accepted=1 then 'ACCEPTED' else 'REJECTED' end)=?"]
    params: list[Any] = [status]
    agents = filters.get("agents") or []
    if agents:
        clauses.append(f"agent_id in ({','.join(['?'] * len(agents))})")
        params.extend(agents)
    if filters.get("direction") not in (None, "All"):
        clauses.append("direction=?")
        params.append(filters["direction"])
    if filters.get("action") not in (None, "All"):
        clauses.append("action=?")
        params.append(filters["action"])
    low, high = filters.get("confidence", (1, 5))
    clauses.append("(confidence is null or confidence between ? and ?)")
    params.extend([low, high])
    cycle_low, cycle_high = filters.get("cycle_range", (0, 0))
    if cycle_high > 0:
        clauses.append("(cycle_number is null or cycle_number between ? and ?)")
        params.extend([cycle_low, cycle_high])
    dates = filters.get("dates")
    if isinstance(dates, tuple) and len(dates) == 2:
        clauses.append("date(coalesce(timestamp_utc, created_at)) between date(?) and date(?)")
        params.extend([_date_iso(dates[0]), _date_iso(dates[1])])
    search = str(filters.get("search") or "").strip()
    if search:
        clauses.append("(thesis like ? or raw_model_output like ? or raw_response like ? or rejection_reason_message like ?)")
        params.extend([f"%{search}%"] * 4)
    return " and ".join(clauses), params


@st.cache_data(ttl=15)
def _filter_meta(database: str) -> dict[str, Any]:
    path = Path(database)
    if not path.exists():
        return {"directions": [], "actions": [], "cycle_min": 0, "cycle_max": 0}
    with sqlite3.connect(path) as connection:
        directions = [row[0] for row in connection.execute("select distinct direction from signals where direction is not null and direction != '' order by direction")]
        actions = [row[0] for row in connection.execute("select distinct action from signals where action is not null and action != '' order by action")]
        cycles = connection.execute("select coalesce(min(cycle_number),0), coalesce(max(cycle_number),0) from signals").fetchone()
    return {"directions": directions, "actions": actions, "cycle_min": int(cycles[0]), "cycle_max": int(cycles[1])}


def _details(rows: pd.DataFrame, accepted: bool) -> None:
    for _, row in rows.head(20).iterrows():
        label = f"{row.get('timestamp_utc') or row.get('created_at')} | {row.get('agent_name') or row.get('agent_id')} | {row.get('decision')}/{row.get('action')}"
        with st.expander(label, expanded=False):
            if accepted:
                st.write(row.get("thesis") or "No thesis captured.")
                st.json(_safe_json(row.get("normalized_signal_json") or row.get("payload_json"), {}))
                st.json(_safe_json(row.get("validation_details_json"), {}))
                st.json(_safe_json(row.get("execution_result_json"), {}))
            else:
                st.write(row.get("rejection_reason_message") or "No rejection message captured.")
                st.json(_safe_json(row.get("validation_details_json"), {}))
                st.json(_safe_json(row.get("parsed_json") or row.get("payload_json"), {}))
            st.code(row.get("raw_model_output") or row.get("raw_response") or "", language="json")


def _agent_counts(values: dict[str, int]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in values.items()) or "-"


def _date_iso(value: date) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _safe_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback
