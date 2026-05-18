from __future__ import annotations

__all__ = ["RiskAutomationEngine"]


def __getattr__(name: str):
    if name == "RiskAutomationEngine":
        from src.trading.risk_automation.engine import RiskAutomationEngine

        return RiskAutomationEngine
    raise AttributeError(name)
