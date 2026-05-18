from __future__ import annotations

import json

from src.competition.runner import CompetitionRunner
from src.config import PROJECT_ROOT
from src.schemas import AgentSignal
from src.validation.rule_engine import RuleEngine
from src.validation.signal_validator import validate_signal


def test_prompt_docs_pin_risk_formula_and_feature_templates() -> None:
    system_prompt = (PROJECT_ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    rulebook = (PROJECT_ROOT / "config" / "rulebook.md").read_text(encoding="utf-8")
    combined = system_prompt + "\n" + rulebook

    assert "account_risk_usdt = abs(entry - stop_loss) / entry * notional_exposure_usdt" in combined
    assert "Do not multiply by leverage again" in combined
    assert "PLACE_TRIGGER" in combined
    assert "position_risk" in combined
    assert '"trailing_stop"' in combined
    assert '"break_even"' in combined
    assert '"time_exit"' in combined
    assert '"account_risk_percent": 0.003247' in combined


def test_runner_schema_hint_exposes_trigger_and_risk_math(test_settings) -> None:
    test_settings.resolve_path(test_settings.paths.rulebook).write_text("Paper trading only.", encoding="utf-8")
    runner = CompetitionRunner(test_settings)
    prompt = runner._compose_prompt(
        "crypto-qwen",
        {
            "market_state": {"symbol": "BTC", "current_price": 77000},
            "private_lessons": [],
            "shared_lessons": [],
            "shared_learning": {},
            "account": {"equity": 10000},
            "open_positions": [],
        },
    )

    assert "NONE|OPEN|ADD|DCA|REDUCE|CUT|CLOSE|HOLD|PLACE_TRIGGER" in prompt
    assert "abs(entry - stop_loss) / entry * notional_exposure_usdt" in prompt
    assert "Do not multiply by leverage again" in prompt


def test_documented_open_template_risk_math_passes_validator(test_settings) -> None:
    payload = {
        "agent": "crypto-qwen",
        "decision": "PAPER_TRADE",
        "action": "OPEN",
        "symbol": "BTC",
        "direction": "LONG",
        "execution_type": "MARKET",
        "leverage": 5,
        "margin_used_usdt": 1000,
        "margin_used_percent": 0.10,
        "notional_exposure_usdt": 5000,
        "entry": 77000,
        "stop_loss": 76500,
        "take_profit_1": 77800,
        "take_profit_2": 78200,
        "time_horizon": "6-12h",
        "account_risk_usdt": 32.47,
        "account_risk_percent": 0.003247,
        "total_account_risk_after_action_usdt": 32.47,
        "total_account_risk_after_action_percent": 0.003247,
        "liquidation_risk_note": "5x simulated paper leverage; stop is far from liquidation.",
        "confidence": 3,
        "risk_reward_to_tp1": 1.6,
        "risk_reward_to_tp2": 2.4,
        "thesis": "Price reclaimed support with improving momentum.",
        "invalidation": "Close back below support or stop loss hit.",
        "counterargument": "Trend may remain weak and reject the reclaim.",
        "data_used": ["market_state", "indicators", "recent_candles"],
    }
    rule_engine = RuleEngine(test_settings.risk, test_settings.accounts.initial_equity)

    signal, validation = validate_signal(
        json.dumps(payload),
        rule_engine,
        current_equity=10000,
        open_positions_count=0,
        current_total_risk=0,
        daily_pnl=0,
    )

    assert isinstance(signal, AgentSignal)
    assert validation.accepted
