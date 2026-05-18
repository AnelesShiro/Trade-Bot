from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.schemas import AccountSummary, Direction, PositionStatus, PositionView
from src.storage.models import PositionRecord, TradeRecord
from src.storage.repository import ArenaRepository
from src.trading.pnl import calculate_pnl


@dataclass
class PaperAccount:
    agent_id: str
    initial_equity: float
    repository: ArenaRepository

    def open_positions(self) -> list[PositionRecord]:
        return self.repository.open_positions(self.agent_id)

    def realized_pnl(self) -> float:
        return sum(trade.realized_pnl for trade in self.repository.trades(self.agent_id))

    def unrealized_pnl(self, current_price: float) -> float:
        total = 0.0
        for position in self.open_positions():
            total += calculate_pnl(position.direction, position.notional, position.average_entry, current_price)
        return total

    def equity(self, current_price: float) -> float:
        return self.initial_equity + self.realized_pnl() + self.unrealized_pnl(current_price)

    def open_margin(self) -> float:
        return sum(position.margin for position in self.open_positions())

    def open_risk(self) -> float:
        risk = 0.0
        for position in self.open_positions():
            risk += abs(calculate_pnl(position.direction, position.notional, position.average_entry, position.stop_loss))
        return risk

    def summary(self, current_price: float) -> AccountSummary:
        realized = self.realized_pnl()
        unrealized = self.unrealized_pnl(current_price)
        positions = [
            PositionView(
                position_id=position.id,
                agent_id=position.agent_id,
                direction=Direction(position.direction),
                status=PositionStatus(position.status),
                leverage=position.leverage,
                margin=position.margin,
                notional=position.notional,
                average_entry=position.average_entry,
                stop_loss=position.stop_loss,
                take_profit_1=position.take_profit_1,
                take_profit_2=position.take_profit_2,
                dca_count=position.dca_count,
                opened_at=position.opened_at,
                unrealized_pnl=calculate_pnl(position.direction, position.notional, position.average_entry, current_price),
            )
            for position in self.open_positions()
        ]
        return AccountSummary(
            agent_id=self.agent_id,
            equity=self.initial_equity + realized + unrealized,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            open_margin=self.open_margin(),
            open_risk=self.open_risk(),
            daily_pnl=self.daily_pnl(current_price),
            open_positions=positions,
        )

    def daily_pnl(self, current_price: float) -> float:
        today = datetime.now(UTC).date()
        realized_today = sum(
            trade.realized_pnl
            for trade in self.repository.trades(self.agent_id)
            if (trade.execution_timestamp or trade.created_at).date() == today
        )
        return realized_today + self.unrealized_pnl(current_price)
