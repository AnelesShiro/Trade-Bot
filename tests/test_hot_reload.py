from __future__ import annotations

import yaml

from src.competition.config_manager import ConfigManager
from src.config import FeatureFlagSettings
from src.cloud.snapshot_exporter import export_dashboard_snapshot
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
        "rejected_signals_summary",
        "reflections_summary",
        "strategy_diversity_metrics",
        "sync",
    ]:
        assert key in snapshot
