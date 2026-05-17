from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.config import CooldownSettings
from src.storage.repository import ArenaRepository


class CooldownManager:
    def __init__(self, repository: ArenaRepository, settings: CooldownSettings) -> None:
        self.repository = repository
        self.settings = settings

    def blocks_new_entries(self, agent_id: str) -> bool:
        if not self.settings.enabled:
            return False
        state = self.repository.active_cooldown(agent_id)
        if not state:
            return False
        ends_at = state.ends_at
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= ends_at.astimezone(UTC):
            self.repository.clear_cooldown(agent_id)
            return False
        return True

    def evaluate_after_cycle(self, agent_id: str, *, equity: float, daily_pnl: float, rejection_rate: float, api_failures: int) -> None:
        if not self.settings.enabled:
            return
        if self.blocks_new_entries(agent_id):
            return
        reason = None
        hours = 0.0
        if self.settings.consecutive_losses and self.settings.pause_hours_after_losses:
            losses = self.repository.consecutive_losses(agent_id, self.settings.consecutive_losses)
            if losses >= self.settings.consecutive_losses:
                reason = f"{losses} consecutive losses"
                hours = self.settings.pause_hours_after_losses
        if reason is None and self.settings.daily_loss_pct and daily_pnl <= -(equity * self.settings.daily_loss_pct):
            reason = f"daily drawdown >= {self.settings.daily_loss_pct:.1%}"
            hours = self.settings.pause_hours_daily or self.settings.pause_hours_after_losses
        if reason is None and self.settings.rejection_rate_threshold and rejection_rate >= self.settings.rejection_rate_threshold:
            reason = f"rejection rate {rejection_rate:.1%}"
            hours = self.settings.pause_hours_after_losses
        if reason is None and self.settings.api_failure_threshold and api_failures >= self.settings.api_failure_threshold:
            reason = f"{api_failures} API failures in recent window"
            hours = self.settings.pause_hours_after_losses
        if reason and hours > 0:
            self.start(agent_id, reason, hours)

    def start(self, agent_id: str, reason: str, hours: float) -> None:
        ends_at = datetime.now(UTC) + timedelta(hours=hours)
        self.repository.upsert_cooldown(agent_id, reason=reason, ends_at=ends_at, metadata={"hours": hours})
