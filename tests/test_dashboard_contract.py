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
    assert len(DASHBOARD_TAB_LABELS) == 17
    assert dashboard_tab_index("Pending Orders") < dashboard_tab_index("Configuration")
    assert dashboard_tab_index("Risk Automation") < dashboard_tab_index("Configuration")
    assert dashboard_tab_index("API Failover Events") < dashboard_tab_index("Configuration")
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
