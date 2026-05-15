from src.schemas import Decision
from src.validation.signal_validator import parse_agent_signal


def test_parse_no_trade_json() -> None:
    raw = '{"agent":"crypto-grok","decision":"NO_TRADE","action":"NONE","symbol":"BTC","data_used":["ohlcv"]}'
    signal, result = parse_agent_signal(raw)
    assert result.accepted
    assert signal is not None
    assert signal.decision == Decision.NO_TRADE
