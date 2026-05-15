from __future__ import annotations

from src.schemas import AgentSignal
from src.trading.position_manager import PositionManager


class PaperExecutionEngine:
    def __init__(self, position_manager: PositionManager) -> None:
        self.position_manager = position_manager

    def execute(self, signal: AgentSignal, current_price: float) -> str | None:
        return self.position_manager.apply_signal(signal, current_price)
