from __future__ import annotations

import pandas as pd

from src.analytics.lesson_analytics import build_lesson_analytics, filter_lessons, lesson_summary


def test_lesson_analytics_separates_follow_and_avoid() -> None:
    shared = pd.DataFrame(
        [
            {
                "id": 1,
                "source_agent": "crypto-deepseek",
                "market_regime": "breakout",
                "lesson_text": "Use PLACE_TRIGGER for confirmed breakout pullback entries.",
                "lesson_type": "best_practice",
                "confidence": 0.8,
                "sample_size": 4,
                "win_rate": 0.75,
                "profit_factor": 2.0,
                "promoted_at": "2026-05-18T00:00:00Z",
            },
            {
                "id": 2,
                "source_agent": "crypto-qwen",
                "market_regime": "trend",
                "lesson_text": "Avoid chasing overextended candles after repeated losses.",
                "lesson_type": "failure_caution",
                "confidence": 0.78,
                "sample_size": 3,
                "win_rate": 0.25,
                "profit_factor": 0.5,
                "promoted_at": "2026-05-18T00:00:00Z",
            },
        ]
    )
    lessons = pd.DataFrame()
    reflections = pd.DataFrame()
    trades = pd.DataFrame()

    analytics = build_lesson_analytics(lessons, shared, reflections, trades)

    assert analytics["follow"]
    assert analytics["avoid"]
    assert "PLACE_TRIGGER" in analytics["follow"][0]["lesson_text"]
    assert "Avoid" in analytics["avoid"][0]["lesson_text"]
    assert lesson_summary(analytics["follow"])["total"] == 1


def test_lesson_filters_apply_thresholds() -> None:
    rows = [
        {
            "lesson_text": "Use break-even after +1R.",
            "agents": ["crypto-qwen"],
            "market_regime": "trend",
            "confidence_score": 0.8,
            "evidence_count": 3,
            "is_shared": True,
            "last_updated": "2026-05-18T00:00:00Z",
        }
    ]

    assert filter_lessons(rows, agents=["crypto-qwen"], market_regime="trend", min_confidence=0.7, min_evidence=2, shared_only=True)
    assert not filter_lessons(rows, agents=["crypto-deepseek"], market_regime="trend", min_confidence=0.7, min_evidence=2, shared_only=True)


def test_private_lessons_deduplicate_by_canonical_summary() -> None:
    lessons = pd.DataFrame(
        [
            {
                "id": 1,
                "agent_id": "crypto-deepseek",
                "created_at": "2026-05-18T00:00:00Z",
                "content": "SHORT loss: notes=CLOSED DS-SHORT-003 fee=5 slippage_bps=2 After-stop-loss wait rule.",
            },
            {
                "id": 2,
                "agent_id": "crypto-deepseek",
                "created_at": "2026-05-18T01:00:00Z",
                "content": "SHORT loss: notes=CLOSED DS-SHORT-004 fee=7 slippage_bps=3 After-stop-loss wait rule.",
            },
        ]
    )

    analytics = build_lesson_analytics(lessons, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    avoid = analytics["avoid"]

    assert len(avoid) == 1
    assert avoid[0]["lesson_text"] == "Pause new SHORT entries for one full cycle after a short stop-loss."
    assert avoid[0]["evidence_count"] == 2
    assert "raw_text" in avoid[0]["evidence"][0]
