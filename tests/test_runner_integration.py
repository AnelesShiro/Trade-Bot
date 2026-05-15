from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from src.competition import runner as runner_module
from src.competition.runner import CompetitionRunner
from src.schemas import IndicatorSnapshot, MarketCandle, MarketState


def market_state() -> MarketState:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        MarketCandle(
            timestamp=start + timedelta(hours=i),
            open=100000 + i,
            high=100100 + i,
            low=99900 + i,
            close=100000 + i,
            volume=1,
        )
        for i in range(60)
    ]
    return MarketState(
        symbol="BTCUSDT",
        exchange="binanceusdm",
        current_price=100059,
        timeframe="1h",
        candles=candles,
        indicators=IndicatorSnapshot(rsi_14=55, ema_20=100040, ema_50=100020, atr_14=500),
        funding_rate=0.0001,
        open_interest=1000,
        regime="uptrend_normal_vol",
    )


def final_signal(agent_id: str) -> str:
    return json.dumps(
        {
            "agent": agent_id,
            "decision": "PAPER_TRADE",
            "action": "OPEN",
            "symbol": "BTC",
            "direction": "LONG",
            "execution_type": "LIMIT",
            "position_id": f"{agent_id}-p1",
            "leverage": 5,
            "margin_used_usdt": 500,
            "margin_used_percent": 0.05,
            "notional_exposure_usdt": 2500,
            "entry": 100000,
            "stop_loss": 99000,
            "take_profit_1": 101500,
            "take_profit_2": 102000,
            "time_horizon": "6h",
            "account_risk_usdt": 25,
            "account_risk_percent": 0.0025,
            "total_account_risk_after_action_usdt": 25,
            "total_account_risk_after_action_percent": 0.0025,
            "liquidation_risk_note": "simulated leverage only",
            "confidence": 3,
            "risk_reward_to_tp1": 1.5,
            "risk_reward_to_tp2": 2.0,
            "thesis": "trend continuation",
            "invalidation": "break below stop",
            "counterargument": "range rejection",
            "data_used": ["shared_market_state", "indicators"],
        }
    )


def test_runner_run_once_with_tool_request(monkeypatch, tmp_path, test_settings) -> None:
    monkeypatch.delenv("ARENA_DATABASE_URL", raising=False)
    test_settings.resolve_path(test_settings.paths.rulebook).write_text("Paper trading only.", encoding="utf-8")
    monkeypatch.setattr(runner_module, "get_market_state", lambda settings: market_state())

    calls: dict[str, int] = {}

    def fake_run(self, prompt: str, timeout_seconds: int = 600) -> str:
        calls[self.settings.id] = calls.get(self.settings.id, 0) + 1
        if self.settings.id == "crypto-deepseek" and calls[self.settings.id] == 1:
            return '{"tool_requests":[{"tool":"get_indicators","arguments":{}}]}'
        if self.settings.id == "crypto-grok":
            return '{"agent":"crypto-grok","decision":"NO_TRADE","action":"NONE","symbol":"BTC","direction":"NONE","execution_type":"NONE"}'
        return final_signal(self.settings.id)

    monkeypatch.setattr(runner_module.OpenClawAgent, "run", fake_run)

    runner = CompetitionRunner(test_settings)
    runner.run_once()

    assert runner.repository.get_position("crypto-deepseek-p1") is not None
    assert runner.repository.response_usage("crypto-deepseek")["requests"] >= 2
    assert runner.repository.response_usage("crypto-grok")["requests"] >= 1
    assert len(runner.repository.workload_cycles()) == 1
    cycle = runner.repository.workload_cycles()[0]
    assert round(cycle.local_workload_pct + cycle.deepseek_workload_pct + cycle.grok_workload_pct, 6) == 100.0
    assert test_settings.resolve_path(test_settings.paths.ledger).exists()
    assert test_settings.resolve_path(test_settings.paths.evaluation).exists()


def test_runner_repairs_rejected_signal(monkeypatch, test_settings) -> None:
    monkeypatch.delenv("ARENA_DATABASE_URL", raising=False)
    test_settings.resolve_path(test_settings.paths.rulebook).write_text("Paper trading only.", encoding="utf-8")
    monkeypatch.setattr(runner_module, "get_market_state", lambda settings: market_state())

    calls: dict[str, int] = {}

    def fake_run(self, prompt: str, timeout_seconds: int = 600) -> str:
        calls[self.settings.id] = calls.get(self.settings.id, 0) + 1
        if self.settings.id == "crypto-deepseek" and calls[self.settings.id] == 1:
            return '{"agent":"crypto-deepseek","decision":"PAPER_TRADE","action":"OPEN","symbol":"BTC","instrument":"bad-extra","direction":"LONG","execution_type":"MARKET","data_used":"string"}'
        if self.settings.id == "crypto-deepseek":
            assert "REJECTED" in prompt
            return '{"agent":"crypto-deepseek","decision":"NO_TRADE","action":"NONE","symbol":"BTC","direction":"NONE","execution_type":"NONE","thesis":"validation repair fallback","invalidation":"valid setup appears","counterargument":"may miss a move","data_used":["validation_feedback"]}'
        return '{"agent":"crypto-grok","decision":"NO_TRADE","action":"NONE","symbol":"BTC","direction":"NONE","execution_type":"NONE","thesis":"stand aside","invalidation":"setup improves","counterargument":"could miss move","data_used":["market_state"]}'

    monkeypatch.setattr(runner_module.OpenClawAgent, "run", fake_run)

    runner = CompetitionRunner(test_settings)
    runner.run_once()

    assert calls["crypto-deepseek"] == 2
    assert runner.repository.rejected_signal_count("crypto-deepseek") == 1
    assert runner.repository.response_usage("crypto-deepseek")["requests"] == 2
