from __future__ import annotations

from src.agents.memory import AgentMemory
from src.storage.models import TradeRecord


def reflect_on_trade(memory: AgentMemory, trade: TradeRecord) -> str:
    outcome = "win" if trade.realized_pnl > 0 else "loss" if trade.realized_pnl < 0 else "flat"
    lesson_tone = (
        "Repeat only when thesis, invalidation, and risk/reward remain clear."
        if trade.realized_pnl > 0
        else "Treat similar setups as cautionary unless invalidation and risk are improved."
    )
    lesson = (
        f"{trade.action} {trade.direction} {outcome}: "
        f"notes={trade.notes or 'no notes'}. "
        f"{lesson_tone} Review whether PLACE_TRIGGER, trailing_stop, break_even, or time_exit would have improved management."
    )
    memory.save_lesson(trade.agent_id, lesson)
    memory.repository.save_reflection(trade.agent_id, lesson)
    return lesson


def reflect_on_day(memory: AgentMemory, agent_id: str, equity: float, realized_pnl: float, unrealized_pnl: float) -> str:
    lesson = (
        f"Daily review: equity={equity:.2f}, realized_pnl={realized_pnl:.2f}, "
        f"unrealized_pnl={unrealized_pnl:.2f}. Keep valid setups only, preserve rule compliance, "
        "and note whether conditional entries, profit protection, or stale-trade exits would help."
    )
    memory.save_lesson(agent_id, lesson)
    memory.repository.save_reflection(agent_id, lesson)
    return lesson
