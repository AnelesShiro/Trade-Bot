from __future__ import annotations

import json

from src.agents.shared_learning import (
    DEFAULT_PROFILES,
    SharedLearningManager,
    calculate_diversity_metrics,
    compatibility_score,
    is_generalized_lesson,
)
from src.storage.models import SignalRecord, TradeRecord


def test_lesson_promotion_rules(repository, test_settings) -> None:
    repository.upsert_agents(test_settings.agents)
    for index in range(10):
        repository.add_trade(
            TradeRecord(
                id=f"t{index}",
                agent_id="crypto-deepseek",
                position_id=f"p{index}",
                action="CLOSE",
                direction="LONG",
                leverage=5,
                margin=100,
                notional=500,
                entry=100,
                exit_price=110 if index < 7 else 95,
                realized_pnl=30 if index < 7 else -10,
                notes="breakout strong_trend",
            )
        )
    repository.save_lesson("crypto-deepseek", "In strong trend breakouts, wait for EMA alignment and volume confirmation before adding.")

    manager = SharedLearningManager(repository, test_settings)
    manager.ensure_storage()
    result = manager.promote_lessons()

    assert result["promoted"] == 1
    assert repository.shared_lessons()[0].source_agent == "crypto-deepseek"
    assert not is_generalized_lesson("entry=69000 exit=70000 pnl=100")


def test_compatibility_filtering_and_shared_ratio(repository, test_settings) -> None:
    repository.upsert_agents(test_settings.agents)
    manager = SharedLearningManager(repository, test_settings)
    manager.ensure_storage()
    repository.save_shared_lesson(
        source_agent="crypto-grok",
        market_regime="breakout",
        lesson_text="Breakout momentum lessons work best when EMA trend, OI, and volume confirm continuation.",
        confidence=0.9,
        sample_size=20,
        win_rate=0.7,
        profit_factor=2.0,
    )
    repository.save_shared_lesson(
        source_agent="crypto-grok",
        market_regime="range",
        lesson_text="Mean reversion near Bollinger resistance is preferred during range exhaustion.",
        confidence=0.9,
        sample_size=20,
        win_rate=0.7,
        profit_factor=2.0,
    )

    retrieved = manager.retrieve_for_prompt("crypto-deepseek", "BTC breakout EMA volume", ["p1", "p2", "p3", "p4", "p5", "p6"], total_limit=8)

    assert len(retrieved.shared_lessons) == 1
    assert "Breakout momentum" in retrieved.shared_lessons[0]
    assert len(retrieved.private_lessons) >= len(retrieved.shared_lessons)
    assert compatibility_score(DEFAULT_PROFILES["crypto-deepseek"], retrieved.shared_lessons[0], "breakout") >= test_settings.shared_learning.compatibility_threshold


def test_agreement_detection_and_anti_convergence(repository, test_settings) -> None:
    left = []
    right = []
    for index in range(20):
        payload = {
            "direction": "LONG",
            "leverage": 5,
            "confidence": 4,
            "thesis": "EMA breakout continuation with volume confirmation",
        }
        left.append(SignalRecord(agent_id="crypto-deepseek", decision="PAPER_TRADE", action="OPEN", accepted=1, payload_json=json.dumps(payload), raw_response="{}"))
        right.append(SignalRecord(agent_id="crypto-grok", decision="PAPER_TRADE", action="OPEN", accepted=1, payload_json=json.dumps(payload), raw_response="{}"))

    metrics = calculate_diversity_metrics({"crypto-deepseek": left, "crypto-grok": right}, test_settings.shared_learning)

    assert metrics["action_agreement_rate"] == 1.0
    assert metrics["convergence_warning"] == 1
    assert metrics["shared_ratio_applied"] == test_settings.shared_learning.reduced_shared_ratio
