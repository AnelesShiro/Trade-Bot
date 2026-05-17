from __future__ import annotations

from src.schemas import Action, AgentSignal, Decision, Direction, ExecutionType, ValidationResult
from src.storage.signal_repository import SignalAuditRepository
from src.validation.signal_logger import rejection_code, signal_audit_metadata


def test_signal_audit_persists_extended_metadata(repository) -> None:
    signal = AgentSignal(
        agent="crypto-deepseek",
        decision=Decision.PAPER_TRADE,
        action=Action.OPEN,
        direction=Direction.SHORT,
        execution_type=ExecutionType.LIMIT,
        entry=100000,
        stop_loss=101000,
        take_profit_1=98500,
        take_profit_2=98000,
        leverage=5,
        margin_used_usdt=500,
        margin_used_percent=0.05,
        notional_exposure_usdt=2500,
        account_risk_usdt=25,
        account_risk_percent=0.0025,
        total_account_risk_after_action_usdt=25,
        total_account_risk_after_action_percent=0.0025,
        confidence=4,
        risk_reward_to_tp1=1.5,
        risk_reward_to_tp2=2.0,
        thesis="breakdown continuation",
        invalidation="reclaim invalidates",
        counterargument="could fake out",
        data_used=["market_state"],
    )
    validation = ValidationResult(accepted=True)
    metadata = signal_audit_metadata(
        agent_name="Crypto DeepSeek",
        model_name="deepseek/deepseek-v4-flash",
        cycle_number=12,
        competition_time_pct=0.25,
        market_regime="downtrend_low_vol",
        btc_price=100000,
        timeframe="1h",
        prompt_version="prompt-hash",
        rulebook_version="rulebook-hash",
        config_version="config-hash",
        signal=signal,
        validation=validation,
        raw_response=signal.model_dump_json(),
        input_tokens=100,
        output_tokens=50,
        api_cost_usd=0.001,
        latency_ms=1234,
    )
    signal_id = repository.save_signal("crypto-deepseek", signal, validation, signal.model_dump_json(), metadata=metadata)
    repository.update_signal_execution(signal_id, {"executed": True, "position_id": "p1"})

    summary = SignalAuditRepository(repository).summary()
    assert summary["accepted_signal_count"] == 1
    latest = summary["latest_accepted_signal"]
    assert latest["direction"] == "SHORT"
    assert latest["cycle_number"] == 12
    assert latest["execution_result"]["executed"] is True
    assert summary["recent_accepted_signals"][0]["cycle_number"] == 12
    assert summary["recent_rejected_signals"] == []


def test_rejection_code_mapping() -> None:
    assert rejection_code(["leverage must be <= 10x"], signal=object()) == "LEVERAGE_LIMIT_EXCEEDED"
    assert rejection_code(["max simultaneous open positions reached"], signal=object()) == "POSITION_LIMIT_EXCEEDED"
    assert rejection_code(["parse/schema error: no JSON object found"], signal=None) == "PARSE_ERROR"
    assert rejection_code(["AGENT_RUNTIME_ERROR: GatewayClientRequestError: billing error"], signal=None) == "INTERNAL_ERROR"
