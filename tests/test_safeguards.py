from __future__ import annotations

from src.operations.preflight import CheckResult, has_critical_failures
from src.validation.signal_validator import repair_json


def test_json_repair_handles_common_model_errors() -> None:
    repaired = repair_json('{"agent":"crypto-grok","decision":"NO_TRADE","action":"NONE",}')
    assert repaired == '{"agent":"crypto-grok","decision":"NO_TRADE","action":"NONE"}'
    assert repair_json('{"ok": True, "value": None}') == '{"ok": true, "value": null}'


def test_preflight_critical_failure_detection() -> None:
    results = [
        CheckResult("dashboard", "FAIL", False, "port busy"),
        CheckResult("database", "PASS", True, "ok"),
    ]
    assert not has_critical_failures(results)
    results.append(CheckResult("api_keys", "FAIL", True, "missing"))
    assert has_critical_failures(results)
