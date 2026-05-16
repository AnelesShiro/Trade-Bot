from datetime import UTC, datetime, timedelta

from src.config import RiskSettings
from src.schemas import Action, AgentSignal, Decision, Direction, ExecutionType
from src.storage.models import TradeRecord
from src.validation.rule_engine import RuleEngine


def valid_signal() -> AgentSignal:
    return AgentSignal(
        agent="crypto-deepseek",
        decision=Decision.PAPER_TRADE,
        action=Action.OPEN,
        direction=Direction.LONG,
        execution_type=ExecutionType.LIMIT,
        leverage=5,
        margin_used_usdt=500,
        margin_used_percent=0.05,
        notional_exposure_usdt=2500,
        entry=100000,
        stop_loss=99000,
        take_profit_1=101500,
        take_profit_2=102000,
        account_risk_usdt=25,
        account_risk_percent=0.0025,
        total_account_risk_after_action_usdt=25,
        total_account_risk_after_action_percent=0.0025,
        confidence=3,
        risk_reward_to_tp1=1.5,
        risk_reward_to_tp2=2,
        thesis="Breakout retest with defined risk.",
        invalidation="Lose the retest level.",
        counterargument="Range may reject.",
        data_used=["ohlcv", "indicators"],
    )


def test_valid_signal_is_accepted() -> None:
    engine = RuleEngine(RiskSettings(), 10000)
    result = engine.validate(valid_signal(), 10000, 0, 0, 0)
    assert result.accepted, result.reasons


def test_leverage_above_limit_rejected() -> None:
    signal = valid_signal().model_copy(update={"leverage": 11})
    engine = RuleEngine(RiskSettings(), 10000)
    result = engine.validate(signal, 10000, 0, 0, 0)
    assert not result.accepted
    assert any("leverage" in reason for reason in result.reasons)


def test_recent_stop_loss_same_direction_rejected() -> None:
    engine = RuleEngine(RiskSettings(), 10000)
    result = engine.validate(valid_signal(), 10000, 0, 0, 0, recent_stop_loss_same_direction=True)
    assert not result.accepted
    assert any("stop loss" in reason for reason in result.reasons)


def test_stop_loss_cooldown_only_counts_after_cycle_boundary(repository, test_settings) -> None:
    repository.upsert_agents(test_settings.agents)
    now = datetime.now(UTC)
    repository.add_trade(
        TradeRecord(
            id="old-stop",
            agent_id="crypto-grok",
            position_id="p1",
            created_at=now - timedelta(hours=2),
            action="AUTO_CLOSE",
            direction="LONG",
            leverage=10,
            margin=1000,
            notional=10000,
            entry=79000,
            exit_price=78000,
            realized_pnl=-100,
            notes="stop_loss",
        )
    )

    assert repository.latest_stop_loss_same_direction("crypto-grok", "LONG")
    assert not repository.latest_stop_loss_same_direction("crypto-grok", "LONG", since=now - timedelta(hours=1))

    repository.add_trade(
        TradeRecord(
            id="new-stop",
            agent_id="crypto-grok",
            position_id="p2",
            created_at=now,
            action="AUTO_CLOSE",
            direction="LONG",
            leverage=10,
            margin=1000,
            notional=10000,
            entry=79000,
            exit_price=78000,
            realized_pnl=-100,
            notes="stop_loss",
        )
    )

    assert repository.latest_stop_loss_same_direction("crypto-grok", "LONG", since=now - timedelta(minutes=1))
