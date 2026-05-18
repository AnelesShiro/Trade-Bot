from __future__ import annotations

from src.config import PROJECT_ROOT
from src.dashboard.contract import (
    DASHBOARD_TAB_LABELS,
    REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS,
    dashboard_tab_index,
    validate_dashboard_contract,
)


def test_dashboard_tab_contract_is_single_source_of_truth() -> None:
    app_source = (PROJECT_ROOT / "src" / "dashboard" / "app.py").read_text(encoding="utf-8")

    assert validate_dashboard_contract() == []
    assert len(DASHBOARD_TAB_LABELS) == 19
    assert dashboard_tab_index("Pending Orders") < dashboard_tab_index("Configuration")
    assert dashboard_tab_index("Risk Automation") < dashboard_tab_index("Configuration")
    assert dashboard_tab_index("API Failover Events") < dashboard_tab_index("Configuration")
    assert dashboard_tab_index("Lessons to Follow") > dashboard_tab_index("Configuration")
    assert dashboard_tab_index("Lessons to Avoid") > dashboard_tab_index("Lessons to Follow")
    assert app_source.count("st.tabs(DASHBOARD_TAB_LABELS)") == 2


def test_render_dashboard_risk_tabs_have_snapshot_contract_keys() -> None:
    assert REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS == (
        "pending_orders",
        "cooldowns",
        "position_risk",
        "failover_events",
        "notifications",
        "active_models",
    )


def test_lesson_filter_widgets_have_unique_keys() -> None:
    source = (PROJECT_ROOT / "src" / "dashboard" / "tabs" / "lessons_to_follow.py").read_text(encoding="utf-8")
    avoid_source = (PROJECT_ROOT / "src" / "dashboard" / "tabs" / "lessons_to_avoid.py").read_text(encoding="utf-8")

    assert "key_prefix=\"lessons_follow\"" in source
    assert "key_prefix=\"lessons_avoid\"" in avoid_source
    for suffix in ["agents", "market_regime", "confidence", "evidence", "shared_only"]:
        assert f"key=f\"{{key_prefix}}_{suffix}\"" in source
