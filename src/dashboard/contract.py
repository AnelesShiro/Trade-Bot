from __future__ import annotations

DASHBOARD_TAB_LABELS: tuple[str, ...] = (
    "Overview",
    "Live Positions",
    "Trade History",
    "Equity Curves",
    "Leaderboard",
    "Accepted Signals",
    "Rejected Signals",
    "Raw Model Outputs",
    "Memory & Reflections",
    "Token & Cost",
    "API Cost Audit",
    "Workload Attribution",
    "Strategy Diversity",
    "Pending Orders",
    "Risk Automation",
    "API Failover Events",
    "Configuration",
    "Lessons to Follow",
    "Lessons to Avoid",
)

REQUIRED_RISK_AUTOMATION_SNAPSHOT_KEYS: tuple[str, ...] = (
    "pending_orders",
    "cooldowns",
    "position_risk",
    "failover_events",
    "notifications",
    "active_models",
)

REQUIRED_LESSON_ANALYTICS_SNAPSHOT_KEYS: tuple[str, ...] = (
    "follow",
    "avoid",
    "follow_summary",
    "avoid_summary",
)


def dashboard_tab_index(label: str) -> int:
    return DASHBOARD_TAB_LABELS.index(label)


def validate_dashboard_contract() -> list[str]:
    errors: list[str] = []
    if len(DASHBOARD_TAB_LABELS) != len(set(DASHBOARD_TAB_LABELS)):
        errors.append("DASHBOARD_TAB_LABELS contains duplicate labels")
    for label in ("Pending Orders", "Risk Automation", "API Failover Events", "Lessons to Follow", "Lessons to Avoid"):
        if label not in DASHBOARD_TAB_LABELS:
            errors.append(f"missing required dashboard tab {label}")
    return errors
