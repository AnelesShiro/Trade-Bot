from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


def render_rejected_signals_tab(database: str, agent_ids: list[str], default_date_range) -> None:
    st.subheader("Rejected Signals")
    filters = _filters(database, agent_ids, default_date_range)
    summary = _summary(database, filters)
    total = int(summary.get("total") or 0)
    accepted_all = int(summary.get("accepted_all") or 0)
    rejected_all = int(summary.get("rejected_all") or 0)
    all_signals = accepted_all + rejected_all
    cols = st.columns(4)
    cols[0].metric("Total rejected", f"{total:,}")
    cols[1].metric("Rejection rate", f"{(rejected_all / all_signals * 100) if all_signals else 0:.1f}%")
    cols[2].metric("Top rejection reasons", _compact_counts(summary.get("by_code", {})))
    cols[3].metric("Rejections by agent", _compact_counts(summary.get("by_agent", {})))

    page_size = st.selectbox("Rows per page", [25, 50, 100, 250], index=1, key="rejected_page_size")
    max_page = max(1, (total + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=max_page, value=1, step=1, key="rejected_page")
    rows = _rows(database, filters, int(page_size), (int(page) - 1) * int(page_size))
    if rows.empty:
        st.success("No rejected signals match the current filters.")
        return
    rows["raw_snippet"] = rows.apply(lambda row: str(row.get("raw_model_output") or row.get("raw_response") or "")[:220], axis=1)
    display_columns = [
        "timestamp_utc",
        "cycle_number",
        "agent_name",
        "rejection_reason_code",
        "rejection_reason_message",
        "confidence",
        "direction",
        "action",
        "raw_snippet",
    ]
    st.dataframe(rows[[column for column in display_columns if column in rows.columns]], width="stretch", hide_index=True)
    _details(rows)


def _filters(database: str, agent_ids: list[str], default_date_range) -> dict[str, Any]:
    meta = _filter_meta(database)
    cols = st.columns(4)
    selected_agents = cols[0].multiselect("Agent", options=agent_ids, default=agent_ids, key="rejected_agents")
    selected_code = cols[1].selectbox("Rejection code", ["All"] + meta.get("codes", []), key="rejected_code")
    selected_direction = cols[2].selectbox("Direction", ["All"] + meta.get("directions", []), key="rejected_direction")
    selected_action = cols[3].selectbox("Action", ["All"] + meta.get("actions", []), key="rejected_action")
    cols = st.columns(4)
    confidence = cols[0].slider("Confidence", 1, 5, (1, 5), key="rejected_confidence")
    selected_dates = cols[1].date_input("Date range", value=default_date_range, key="rejected_date_range")
    min_cycle, max_cycle = meta.get("cycle_min", 0), meta.get("cycle_max", 0)
    if max_cycle > min_cycle:
        cycle_range = cols[2].slider("Cycle range", min_cycle, max_cycle, (min_cycle, max_cycle), key="rejected_cycle")
    else:
        cols[2].caption("Cycle range unavailable")
        cycle_range = (min_cycle, max_cycle)
    search = cols[3].text_input("Search text", key="rejected_search")
    return {
        "agents": selected_agents,
        "code": selected_code,
        "direction": selected_direction,
        "action": selected_action,
        "confidence": confidence,
        "dates": selected_dates,
        "cycle_range": cycle_range,
        "search": search,
    }


def _rows(database: str, filters: dict[str, Any], limit: int, offset: int) -> pd.DataFrame:
    where, params = _where(filters)
    query = f"""
        select *
        from signals
        where {where}
        order by coalesce(timestamp_utc, created_at) desc, id desc
        limit ? offset ?
    """
    with sqlite3.connect(database) as connection:
        return pd.read_sql_query(query, connection, params=[*params, limit, offset])


def _summary(database: str, filters: dict[str, Any]) -> dict[str, Any]:
    where, params = _where(filters)
    with sqlite3.connect(database) as connection:
        total = connection.execute(f"select count(*) from signals where {where}", params).fetchone()[0]
        by_agent = connection.execute(f"select coalesce(agent_name, agent_id), count(*) from signals where {where} group by coalesce(agent_name, agent_id)", params).fetchall()
        by_code = connection.execute(f"select coalesce(rejection_reason_code,'UNKNOWN'), count(*) from signals where {where} group by coalesce(rejection_reason_code,'UNKNOWN') order by count(*) desc", params).fetchall()
        accepted_all = connection.execute("select count(*) from signals where coalesce(signal_status, case when accepted=1 then 'ACCEPTED' else 'REJECTED' end)='ACCEPTED'").fetchone()[0]
        rejected_all = connection.execute("select count(*) from signals where coalesce(signal_status, case when accepted=1 then 'ACCEPTED' else 'REJECTED' end)='REJECTED'").fetchone()[0]
    return {
        "total": total,
        "by_agent": {str(agent): int(count) for agent, count in by_agent},
        "by_code": {str(code): int(count) for code, count in by_code},
        "accepted_all": accepted_all,
        "rejected_all": rejected_all,
    }


def _where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = ["coalesce(signal_status, case when accepted=1 then 'ACCEPTED' else 'REJECTED' end)='REJECTED'"]
    params: list[Any] = []
    agents = filters.get("agents") or []
    if agents:
        clauses.append(f"agent_id in ({','.join(['?'] * len(agents))})")
        params.extend(agents)
    if filters.get("code") not in (None, "All"):
        clauses.append("rejection_reason_code=?")
        params.append(filters["code"])
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
        return {"directions": [], "actions": [], "codes": [], "cycle_min": 0, "cycle_max": 0}
    with sqlite3.connect(path) as connection:
        directions = [row[0] for row in connection.execute("select distinct direction from signals where direction is not null and direction != '' order by direction")]
        actions = [row[0] for row in connection.execute("select distinct action from signals where action is not null and action != '' order by action")]
        codes = [row[0] for row in connection.execute("select distinct rejection_reason_code from signals where rejection_reason_code is not null and rejection_reason_code != '' order by rejection_reason_code")]
        cycles = connection.execute("select coalesce(min(cycle_number),0), coalesce(max(cycle_number),0) from signals").fetchone()
    return {"directions": directions, "actions": actions, "codes": codes, "cycle_min": int(cycles[0]), "cycle_max": int(cycles[1])}


def _details(rows: pd.DataFrame) -> None:
    for _, row in rows.head(20).iterrows():
        label = f"{row.get('timestamp_utc') or row.get('created_at')} | {row.get('agent_name') or row.get('agent_id')} | {row.get('rejection_reason_code') or 'REJECTED'}"
        with st.expander(label, expanded=False):
            st.write(row.get("rejection_reason_message") or "No rejection message captured.")
            st.json(_safe_json(row.get("validation_details_json"), {}))
            st.json(_safe_json(row.get("parsed_json") or row.get("payload_json"), {}))
            st.code(row.get("raw_model_output") or row.get("raw_response") or "", language="json")


def _compact_counts(values: dict[str, int]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in list(values.items())[:3]) or "-"


def _date_iso(value: date) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _safe_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback
