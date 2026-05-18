from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.agents.lesson_canonicalizer import canonical_summary, canonicalize_lesson, lesson_key


FOLLOW_TERMS = {
    "win",
    "repeat",
    "worked",
    "best",
    "confirm",
    "breakout",
    "trend",
    "break-even",
    "break_even",
    "trail",
    "trailing",
    "place_trigger",
    "support",
    "volume",
    "momentum",
}
AVOID_TERMS = {
    "loss",
    "avoid",
    "caution",
    "failed",
    "do not",
    "don't",
    "wrong",
    "overtrade",
    "chase",
    "downtrend",
    "rejected",
    "low-quality",
    "stop loss",
}
REGIME_TERMS = ("breakout", "trend", "range", "exhaustion", "mean reversion", "strong_trend", "unknown")


def build_lesson_analytics(
    lessons: pd.DataFrame,
    shared_lessons: pd.DataFrame,
    reflections: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    limit: int = 500,
) -> dict[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_shared_lesson_rows(shared_lessons))
    rows.extend(_private_lesson_rows(lessons, reflections, trades))
    prepared = [_finalize_row(row) for row in rows]
    prepared = [row for row in prepared if row["confidence_score"] >= 0.35 and row["evidence_count"] >= 1]
    follow = sorted([row for row in prepared if row["lesson_kind"] == "follow"], key=lambda row: row["rank_score"], reverse=True)[:limit]
    avoid = sorted([row for row in prepared if row["lesson_kind"] == "avoid"], key=lambda row: row["rank_score"], reverse=True)[:limit]
    return {"follow": follow, "avoid": avoid}


def lesson_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "total": 0,
            "avg_confidence": 0.0,
            "avg_impact": 0.0,
            "shared_count": 0,
            "most_influential_lesson": None,
        }
    top = max(rows, key=lambda row: float(row.get("rank_score") or 0))
    return {
        "total": len(rows),
        "avg_confidence": _avg(row.get("confidence_score") for row in rows),
        "avg_impact": _avg(row.get("impact_score") for row in rows),
        "shared_count": sum(1 for row in rows if row.get("is_shared")),
        "most_influential_lesson": top.get("lesson_text"),
    }


def filter_lessons(
    rows: list[dict[str, Any]],
    *,
    agents: list[str] | None = None,
    market_regime: str = "All",
    min_confidence: float = 0.35,
    min_evidence: int = 1,
    shared_only: bool = False,
    date_range: tuple[Any, Any] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    selected = set(agents or [])
    for row in rows:
        if selected and not selected.intersection(set(row.get("agents", []))):
            continue
        if market_regime != "All" and str(row.get("market_regime") or "unknown") != market_regime:
            continue
        if float(row.get("confidence_score") or 0) < min_confidence:
            continue
        if int(row.get("evidence_count") or 0) < min_evidence:
            continue
        if shared_only and not row.get("is_shared"):
            continue
        if date_range and len(date_range) == 2:
            last = pd.to_datetime(row.get("last_updated"), utc=True, errors="coerce")
            if pd.notna(last):
                start, end = date_range
                if last.date() < start or last.date() > end:
                    continue
        filtered.append(row)
    return filtered


def trend_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    points: list[dict[str, Any]] = []
    for row in rows:
        for point in row.get("trend", []):
            points.append({"lesson_id": row.get("lesson_id"), "lesson_text": row.get("lesson_text"), **point})
    frame = pd.DataFrame(points)
    if not frame.empty and "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame


def contribution_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    counts: dict[str, dict[str, float]] = {}
    for row in rows:
        for agent in row.get("agents", []):
            entry = counts.setdefault(agent, {"agent_id": agent, "lesson_count": 0, "rank_score": 0.0})
            entry["lesson_count"] += 1
            entry["rank_score"] += float(row.get("rank_score") or 0)
    return pd.DataFrame(counts.values()).sort_values("rank_score", ascending=False) if counts else pd.DataFrame()


def _shared_lesson_rows(shared_lessons: pd.DataFrame) -> list[dict[str, Any]]:
    if shared_lessons.empty:
        return []
    rows = []
    for _, item in shared_lessons.head(1000).iterrows():
        raw_text = str(item.get("raw_text") or item.get("lesson_text") or "").strip()
        text = canonical_summary(str(item.get("summary") or raw_text or item.get("lesson_text") or "")).strip()
        if not text:
            continue
        lesson_type = str(item.get("lesson_type") or "best_practice")
        win_rate = _float(item.get("win_rate"))
        profit_factor = _float(item.get("profit_factor"))
        confidence = _float(item.get("confidence"))
        evidence = max(1, int(_float(item.get("sample_size")) or 1))
        kind = "avoid" if lesson_type == "failure_caution" or _negative_score(text) > _positive_score(text) + 1 else "follow"
        rows.append(
            {
                "lesson_id": f"shared-{item.get('id')}",
                "lesson_text": text,
                "summary": text,
                "raw_text": raw_text or text,
                "category": str(item.get("category") or ""),
                "sentiment": str(item.get("sentiment") or kind),
                "lesson_kind": kind,
                "source_type": "shared",
                "is_shared": True,
                "confidence_score": confidence,
                "impact_score": _shared_impact(kind, win_rate, profit_factor, confidence),
                "evidence_count": evidence,
                "agents": [str(item.get("source_agent") or "unknown")],
                "win_rate": win_rate,
                "avg_pnl": 0.0,
                "market_regime": str(item.get("market_regime") or _infer_regime(text)),
                "last_updated": _iso(item.get("promoted_at")),
                "evidence": [
                    {
                        "type": "validated_shared_lesson",
                        "agent_id": str(item.get("source_agent") or "unknown"),
                        "excerpt": text[:500],
                        "raw_text": (raw_text or text)[:1500],
                        "sample_size": evidence,
                        "profit_factor": profit_factor,
                    }
                ],
            }
        )
    return rows


def _private_lesson_rows(lessons: pd.DataFrame, reflections: pd.DataFrame, trades: pd.DataFrame) -> list[dict[str, Any]]:
    frames = []
    if not lessons.empty:
        frame = lessons.copy()
        frame["content"] = frame.get("content", "")
        frame["summary"] = frame["summary"] if "summary" in frame.columns else ""
        frame["raw_text"] = frame["raw_text"] if "raw_text" in frame.columns else ""
        frame["source_type"] = "private_lesson"
        frames.append(frame[["agent_id", "created_at", "content", "summary", "raw_text", "source_type"]])
    if not reflections.empty:
        frame = reflections.copy()
        frame["content"] = frame.get("content", "")
        frame["summary"] = frame["summary"] if "summary" in frame.columns else ""
        frame["raw_text"] = frame["raw_text"] if "raw_text" in frame.columns else ""
        frame["source_type"] = "reflection"
        frames.append(frame[["agent_id", "created_at", "content", "summary", "raw_text", "source_type"]])
    if not frames:
        return []
    combined = pd.concat(frames, ignore_index=True).dropna(subset=["content"]).tail(2000)
    trade_stats = _trade_stats_by_agent(trades)
    grouped: dict[str, dict[str, Any]] = {}
    for _, item in combined.iterrows():
        raw_text = str(item.get("raw_text") or item.get("content") or "").strip()
        text = canonical_summary(str(item.get("summary") or raw_text)).strip()
        if not raw_text and not text:
            continue
        key = lesson_key(text)
        entry = grouped.setdefault(
            key,
            {
                "lesson_id": f"derived-{abs(hash(key))}",
                "lesson_text": text,
                "raw_texts": [],
                "sources": [],
                "agents": set(),
                "dates": [],
            },
        )
        agent_id = str(item.get("agent_id") or "unknown")
        entry["agents"].add(agent_id)
        entry["dates"].append(pd.to_datetime(item.get("created_at"), utc=True, errors="coerce"))
        entry["raw_texts"].append(raw_text or text)
        entry["sources"].append(
            {
                "type": item.get("source_type"),
                "agent_id": agent_id,
                "excerpt": text[:500],
                "raw_text": (raw_text or text)[:1500],
                "created_at": _iso(item.get("created_at")),
            }
        )
    rows = []
    for entry in grouped.values():
        text = entry["lesson_text"]
        canonical = canonicalize_lesson(entry["raw_texts"][0] if entry.get("raw_texts") else text, evidence_count=len(entry["sources"]))
        positive = _positive_score(text)
        negative = _negative_score(text)
        kind = "avoid" if negative > positive else "follow"
        agents = sorted(entry["agents"])
        stats = [_agent_stats(agent, trade_stats) for agent in agents]
        avg_win_rate = _avg(stat["win_rate"] for stat in stats)
        avg_pnl = _avg(stat["avg_pnl"] for stat in stats)
        evidence = len(entry["sources"])
        confidence = min(0.90, 0.35 + 0.08 * evidence + 0.06 * len(agents))
        impact = min(1.0, abs(avg_pnl) / 100.0 + (avg_win_rate if kind == "follow" else 1 - avg_win_rate) * 0.5 + evidence / 20.0)
        dates = [date for date in entry["dates"] if pd.notna(date)]
        rows.append(
            {
                "lesson_id": entry["lesson_id"],
                "lesson_text": text,
                "summary": text,
                "raw_text": entry["raw_texts"][0] if entry.get("raw_texts") else text,
                "category": canonical.category,
                "sentiment": canonical.sentiment,
                "lesson_kind": kind,
                "source_type": "derived",
                "is_shared": len(agents) > 1,
                "confidence_score": confidence,
                "impact_score": impact,
                "evidence_count": evidence,
                "agents": agents,
                "win_rate": avg_win_rate,
                "avg_pnl": avg_pnl,
                "market_regime": _infer_regime(text),
                "last_updated": _iso(max(dates).to_pydatetime() if dates else datetime.now(UTC)),
                "evidence": entry["sources"][:8],
            }
        )
    return rows


def _finalize_row(row: dict[str, Any]) -> dict[str, Any]:
    evidence = int(row.get("evidence_count") or 0)
    confidence = max(0.0, min(1.0, float(row.get("confidence_score") or 0)))
    impact = max(0.0, min(1.0, float(row.get("impact_score") or 0)))
    recency = _recency_score(row.get("last_updated"))
    row["rank_score"] = round(0.42 * impact + 0.28 * confidence + 0.18 * min(1.0, evidence / 10.0) + 0.12 * recency, 4)
    row["confidence_score"] = round(confidence, 4)
    row["impact_score"] = round(impact, 4)
    row["agents"] = sorted(set(row.get("agents") or []))
    row["agent_count"] = len(row["agents"])
    row["badges"] = _badges(row)
    row["trend"] = _synthetic_trend(row)
    return row


def _badges(row: dict[str, Any]) -> list[str]:
    badges = []
    if row.get("is_shared") and int(row.get("agent_count") or 0) >= 2:
        badges.append("Shared")
    if float(row.get("confidence_score") or 0) >= 0.75:
        badges.append("High Confidence")
    if _recency_score(row.get("last_updated")) >= 0.85:
        badges.append("Recently Improved")
    if row.get("lesson_kind") == "avoid" and float(row.get("impact_score") or 0) >= 0.65:
        badges.append("Critical Warning")
    return badges


def _synthetic_trend(row: dict[str, Any]) -> list[dict[str, Any]]:
    last = pd.to_datetime(row.get("last_updated"), utc=True, errors="coerce")
    if pd.isna(last):
        last = pd.Timestamp.now(tz=UTC)
    evidence = max(1, int(row.get("evidence_count") or 1))
    points = []
    for index in range(min(6, evidence)):
        factor = (index + 1) / min(6, evidence)
        points.append(
            {
                "timestamp": (last - pd.Timedelta(days=(min(6, evidence) - index - 1))).isoformat(),
                "impact_score": round(float(row.get("impact_score") or 0) * factor, 4),
                "confidence_score": round(float(row.get("confidence_score") or 0) * (0.75 + 0.25 * factor), 4),
                "frequency": index + 1,
            }
        )
    return points


def _trade_stats_by_agent(trades: pd.DataFrame) -> dict[str, dict[str, float]]:
    if trades.empty or "agent_id" not in trades.columns:
        return {}
    frame = trades.copy()
    frame["realized_pnl"] = pd.to_numeric(frame.get("realized_pnl", 0), errors="coerce").fillna(0)
    stats = {}
    for agent_id, group in frame.groupby("agent_id"):
        pnls = group["realized_pnl"].tolist()
        wins = [pnl for pnl in pnls if pnl > 0]
        stats[str(agent_id)] = {"win_rate": len(wins) / len(pnls) if pnls else 0.0, "avg_pnl": _avg(pnls)}
    return stats


def _agent_stats(agent_id: str, stats: dict[str, dict[str, float]]) -> dict[str, float]:
    return stats.get(agent_id, {"win_rate": 0.0, "avg_pnl": 0.0})


def _shared_impact(kind: str, win_rate: float, profit_factor: float, confidence: float) -> float:
    pf_score = min(1.0, max(0.0, profit_factor / 3.0))
    if kind == "avoid":
        return min(1.0, 0.45 * (1 - win_rate) + 0.35 * confidence + 0.20 * pf_score)
    return min(1.0, 0.45 * win_rate + 0.35 * confidence + 0.20 * pf_score)


def _positive_score(text: str) -> int:
    lowered = text.lower()
    return sum(term in lowered for term in FOLLOW_TERMS)


def _negative_score(text: str) -> int:
    lowered = text.lower()
    return sum(term in lowered for term in AVOID_TERMS)


def _lesson_key(text: str) -> str:
    text = _clean_lesson_text(text).lower()
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "", text)
    return " ".join(text.split())[:180]


def _clean_lesson_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(daily review:|paper_trade|open|close|hold)\s+", "", text, flags=re.IGNORECASE)
    return text[:420]


def _infer_regime(text: str) -> str:
    lowered = text.lower()
    for term in REGIME_TERMS:
        if term != "unknown" and term in lowered:
            return term
    return "unknown"


def _recency_score(value: Any) -> float:
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return 0.4
    age_days = max(0.0, (pd.Timestamp.now(tz=UTC) - ts).total_seconds() / 86400)
    return max(0.0, min(1.0, math.exp(-age_days / 14.0)))


def _avg(values: Any) -> float:
    nums = [float(value) for value in values if value is not None and not pd.isna(value)]
    return sum(nums) / len(nums) if nums else 0.0


def _float(value: Any) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> str | None:
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.isoformat().replace("+00:00", "Z")
