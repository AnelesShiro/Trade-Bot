from __future__ import annotations

from datetime import UTC, datetime

import yaml

from src.competition.config_manager import ConfigManager
from src.config import FeatureFlagSettings
from src.cloud.snapshot_exporter import export_dashboard_snapshot, validate_snapshot_contract
from src.dashboard.components.cycle_status_bar import _countdown
from src.dashboard.contract import REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS
from src.schemas import Action
from src.trading.position_manager import PositionManager

from tests.test_position_manager import make_signal


def test_config_manager_records_and_reloads_versions(repository, test_settings, tmp_path) -> None:
    config_path = tmp_path / "settings.yaml"
    payload = test_settings.model_dump(mode="json")
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    manager = ConfigManager(repository, config_path)
    first_hash = manager.config_hash
    payload["risk"]["max_leverage"] = 7
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    reloaded = manager.reload_if_changed(test_settings)

    assert reloaded.risk.max_leverage == 7
    assert manager.config_hash != first_hash
    assert len(repository.config_versions()) >= 2


def test_trade_records_config_and_code_versions(repository) -> None:
    manager = PositionManager(repository)
    manager.set_version_context(12, "config123", "code456")
    position_id = manager.apply_signal(make_signal(position_id="p-hot"), 100000)
    manager.apply_signal(make_signal(action=Action.CLOSE, position_id=position_id, entry=101000), 101000)

    trade = repository.latest_trade_for_position("p-hot")

    assert trade is not None
    assert trade.config_version_id == 12
    assert trade.config_hash == "config123"
    assert trade.code_version == "code456"


def test_feature_flags_can_target_one_agent(test_settings) -> None:
    test_settings.feature_flags["new-risk"] = FeatureFlagSettings(enabled=True, agents=["crypto-deepseek"])

    assert test_settings.feature_enabled("new-risk", "crypto-deepseek")
    assert not test_settings.feature_enabled("new-risk", "crypto-grok")


def test_cloud_snapshot_contains_required_dashboard_sections(repository, test_settings) -> None:
    snapshot = export_dashboard_snapshot(test_settings, repository)

    for key in [
        "system_status",
        "competition_status",
        "leaderboard",
        "workload",
        "token_usage",
        "api_costs",
        "signal_audit_summary",
        "rejected_signals_summary",
        "reflections_summary",
        "strategy_diversity_metrics",
        "sync",
        "runner",
        "deployment",
        "risk_automation",
    ]:
        assert key in snapshot
    for key in [
        "status",
        "cycle_number",
        "phase",
        "last_cycle_duration_seconds",
        "cycle_interval_seconds",
        "next_cycle_at",
        "last_cycle_started_at",
        "total_cycles_completed",
    ]:
        assert key in snapshot["runner"]
    for key in [
        "accepted_signal_count",
        "rejected_signal_count",
        "acceptance_rate",
        "rejection_breakdown",
        "latest_accepted_signal",
        "latest_rejected_signal",
        "recent_accepted_signals",
        "recent_rejected_signals",
    ]:
        assert key in snapshot["signal_audit_summary"]
    assert isinstance(snapshot["signal_audit_summary"]["recent_accepted_signals"], list)
    assert isinstance(snapshot["signal_audit_summary"]["recent_rejected_signals"], list)
    for key in REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS:
        assert key in snapshot["risk_automation"]
    assert validate_snapshot_contract(snapshot) == []


def test_cloud_snapshot_reports_active_runner_phase(repository, test_settings) -> None:
    started_at = datetime(2026, 5, 18, 6, 0, tzinfo=UTC)
    repository.save_runner_state(
        status="RUNNING",
        phase="CALLING_QWEN",
        cycle_number=12,
        started_at=started_at,
        message="Calling crypto-qwen and validating its signal",
    )

    snapshot = export_dashboard_snapshot(test_settings, repository)

    assert snapshot["runner"]["status"] == "RUNNING"
    assert snapshot["runner"]["phase"] == "CALLING_QWEN"
    assert snapshot["runner"]["cycle_number"] == 12
    assert snapshot["runner"]["next_cycle_at"] is None
    assert snapshot["runner"]["current_cycle_started_at"] == "2026-05-18T06:00:00Z"


def test_cycle_status_does_not_mark_active_phase_overdue() -> None:
    label, overdue = _countdown(None, "CALLING_QWEN")

    assert label == "IN PROGRESS"
    assert overdue is False


def test_snapshot_contract_rejects_missing_signal_audit() -> None:
    errors = validate_snapshot_contract({"generated_at": "now", "runner": {}, "leaderboard": [], "rejected_signals_summary": {}, "deployment": {}, "risk_automation": {}})

    assert any("signal_audit_summary" in error for error in errors)


def test_snapshot_contract_rejects_missing_risk_automation() -> None:
    errors = validate_snapshot_contract(
        {
            "generated_at": "now",
            "runner": {},
            "leaderboard": [],
            "rejected_signals_summary": {},
            "deployment": {},
            "signal_audit_summary": {
                "accepted_signal_count": 0,
                "rejected_signal_count": 0,
                "acceptance_rate": 0,
                "rejection_breakdown": {},
                "latest_accepted_signal": None,
                "latest_rejected_signal": None,
                "recent_accepted_signals": [],
                "recent_rejected_signals": [],
            },
        }
    )

    assert any("risk_automation" in error for error in errors)
