from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.analytics.lesson_analytics import contribution_frame, filter_lessons, lesson_summary, trend_frame


def render_lessons_to_follow_tab(rows: list[dict[str, Any]], agent_ids: list[str], date_range: tuple[Any, Any] | None = None) -> None:
    _render_lesson_tab(
        rows,
        agent_ids,
        title="Lessons to Follow",
        empty_message="No validated positive lessons meet the current filters yet.",
        accent="#22c55e",
        key_prefix="lessons_follow",
        date_range=date_range,
    )


def _render_lesson_tab(
    rows: list[dict[str, Any]],
    agent_ids: list[str],
    *,
    title: str,
    empty_message: str,
    accent: str,
    key_prefix: str,
    date_range: tuple[Any, Any] | None,
) -> None:
    st.subheader(title)
    filters = _filters(rows, agent_ids, accent, key_prefix)
    filtered = filter_lessons(
        rows,
        agents=filters["agents"],
        market_regime=filters["market_regime"],
        min_confidence=filters["min_confidence"],
        min_evidence=filters["min_evidence"],
        shared_only=filters["shared_only"],
        date_range=date_range,
    )
    summary = lesson_summary(filtered)
    _summary_cards(summary)
    if not filtered:
        st.info(empty_message)
        return
    _charts(filtered, accent)
    _agent_breakdown(filtered, accent)
    st.markdown("#### Ranked lesson cards")
    for row in filtered[:25]:
        _lesson_card(row, accent)


def _filters(rows: list[dict[str, Any]], agent_ids: list[str], accent: str, key_prefix: str) -> dict[str, Any]:
    regimes = sorted({str(row.get("market_regime") or "unknown") for row in rows})
    cols = st.columns([1.4, 1, 1, 1, 0.8])
    agents = cols[0].multiselect("Agent", options=agent_ids, default=agent_ids, key=f"{key_prefix}_agents")
    market_regime = cols[1].selectbox("Market regime", ["All"] + regimes, key=f"{key_prefix}_market_regime")
    min_confidence = cols[2].slider("Confidence threshold", 0.0, 1.0, 0.35, 0.05, key=f"{key_prefix}_confidence")
    min_evidence = cols[3].number_input("Minimum evidence", min_value=1, max_value=100, value=1, step=1, key=f"{key_prefix}_evidence")
    shared_only = cols[4].toggle("Shared only", value=False, key=f"{key_prefix}_shared_only")
    st.markdown(f"<div style='height:2px;background:{accent};opacity:.35;margin:4px 0 12px 0'></div>", unsafe_allow_html=True)
    return {
        "agents": agents,
        "market_regime": market_regime,
        "min_confidence": float(min_confidence),
        "min_evidence": int(min_evidence),
        "shared_only": bool(shared_only),
    }


def _summary_cards(summary: dict[str, Any]) -> None:
    cols = st.columns(5)
    cols[0].metric("Total validated", int(summary.get("total") or 0))
    cols[1].metric("Avg confidence", f"{float(summary.get('avg_confidence') or 0):.2f}")
    cols[2].metric("Avg impact", f"{float(summary.get('avg_impact') or 0):.2f}")
    cols[3].metric("Shared lessons", int(summary.get("shared_count") or 0))
    cols[4].metric("Most influential", _short(summary.get("most_influential_lesson"), 34))


def _charts(rows: list[dict[str, Any]], accent: str) -> None:
    trends = trend_frame(rows[:12])
    if trends.empty:
        return
    cols = st.columns(3)
    cols[0].plotly_chart(px.line(trends, x="timestamp", y="impact_score", color="lesson_text", title="Lesson impact over time", template="plotly_dark"), width="stretch")
    cols[1].plotly_chart(px.bar(trends, x="timestamp", y="frequency", color="lesson_text", title="Frequency of occurrence", template="plotly_dark"), width="stretch")
    fig = px.line(trends, x="timestamp", y="confidence_score", color="lesson_text", title="Confidence trend", template="plotly_dark")
    fig.update_traces(line=dict(width=2))
    cols[2].plotly_chart(fig, width="stretch")


def _agent_breakdown(rows: list[dict[str, Any]], accent: str) -> None:
    frame = contribution_frame(rows)
    st.markdown("#### Agent contribution breakdown")
    if frame.empty:
        st.info("No agent contribution data for the current filters.")
        return
    cols = st.columns([1, 1])
    cols[0].dataframe(frame, width="stretch", hide_index=True)
    cols[1].plotly_chart(px.bar(frame, x="agent_id", y="rank_score", color="agent_id", title="Weighted contribution", template="plotly_dark"), width="stretch")


def _lesson_card(row: dict[str, Any], accent: str) -> None:
    badges = " ".join(f"`{badge}`" for badge in row.get("badges", []))
    st.markdown(
        f"""
        <div style="border-left:4px solid {accent};border-top:1px solid rgba(148,163,184,.22);border-right:1px solid rgba(148,163,184,.22);border-bottom:1px solid rgba(148,163,184,.22);border-radius:8px;padding:12px 14px;margin:10px 0;background:rgba(15,23,42,.18)">
            <div style="font-size:1.05rem;font-weight:700;line-height:1.35">{row.get('lesson_text','')}</div>
            <div style="color:#94a3b8;margin-top:6px">{badges}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(6)
    cols[0].metric("Impact", f"{float(row.get('impact_score') or 0):.2f}")
    cols[1].metric("Confidence", f"{float(row.get('confidence_score') or 0):.2f}")
    cols[2].metric("Evidence", int(row.get("evidence_count") or 0))
    cols[3].metric("Agents", ", ".join(row.get("agents", [])) or "-")
    cols[4].metric("Win rate", f"{float(row.get('win_rate') or 0) * 100:.1f}%")
    cols[5].metric("Avg PnL", f"{float(row.get('avg_pnl') or 0):.2f}")
    st.caption(f"Last updated: {row.get('last_updated') or '-'} | Regime: {row.get('market_regime') or 'unknown'} | Rank score: {float(row.get('rank_score') or 0):.2f}")
    with st.expander("Detailed evidence", expanded=False):
        evidence = pd.DataFrame(row.get("evidence", []))
        if evidence.empty:
            st.info("No detailed evidence rows available.")
        else:
            display = evidence.drop(columns=[column for column in ["raw_text"] if column in evidence.columns])
            st.dataframe(display, width="stretch", hide_index=True)
    raw_values = [str(row.get("raw_text") or "")]
    raw_values.extend(str(item.get("raw_text") or "") for item in row.get("evidence", []) if isinstance(item, dict))
    raw_values = [value for value in raw_values if value and value != row.get("lesson_text")]
    if raw_values:
        with st.expander("View Raw Lesson", expanded=False):
            for value in raw_values[:5]:
                st.text(value)


def _short(value: Any, limit: int) -> str:
    text = str(value or "-")
    return text if len(text) <= limit else text[: limit - 1] + "..."
