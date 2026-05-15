from __future__ import annotations

import math
from statistics import mean, pstdev

from src.schemas import LeaderboardRow
from src.storage.repository import ArenaRepository
from src.trading.paper_account import PaperAccount


def calculate_leaderboard(
    repository: ArenaRepository,
    agent_ids: list[str],
    initial_equity: float,
    current_price: float,
) -> list[LeaderboardRow]:
    rows: list[LeaderboardRow] = []
    for agent_id in agent_ids:
        account = PaperAccount(agent_id, initial_equity, repository)
        summary = account.summary(current_price)
        trades = repository.trades(agent_id)
        closed_pnls = [trade.realized_pnl for trade in trades if trade.exit_price is not None or trade.realized_pnl != 0]
        wins = [p for p in closed_pnls if p > 0]
        losses = [abs(p) for p in closed_pnls if p < 0]
        win_rate = len(wins) / len(closed_pnls) if closed_pnls else 0.0
        profit_factor = sum(wins) / sum(losses) if losses else float(sum(wins) > 0)
        returns = [p / initial_equity for p in closed_pnls]
        sharpe = _sharpe(returns)
        sortino = _sortino(returns)
        total_return_pct = (summary.equity - initial_equity) / initial_equity
        max_drawdown_pct = max(0.0, -min(_equity_curve_drawdowns(closed_pnls, initial_equity), default=0.0))
        rejected = repository.rejected_signal_count(agent_id)
        total_signals = rejected + max(len(trades), 1)
        rule_compliance = 1 - (rejected / total_signals)
        usage = repository.response_usage(agent_id)
        api_cost = usage["estimated_cost_usd"]
        api_efficiency = (summary.realized_pnl / api_cost) if api_cost > 0 else 1.0
        score = (
            0.40 * _bounded(total_return_pct / 0.10)
            + 0.20 * _bounded(sharpe / 2 if math.isfinite(sharpe) else 0)
            + 0.20 * _bounded(1 - max_drawdown_pct / 0.10)
            + 0.10 * rule_compliance
            + 0.10 * _bounded(api_efficiency / 100 if api_efficiency > 0 else 0)
        )
        rows.append(
            LeaderboardRow(
                agent_id=agent_id,
                equity=summary.equity,
                total_return_pct=total_return_pct,
                realized_pnl=summary.realized_pnl,
                unrealized_pnl=summary.unrealized_pnl,
                win_rate=win_rate,
                profit_factor=profit_factor,
                sharpe=sharpe,
                sortino=sortino,
                max_drawdown_pct=max_drawdown_pct,
                rejected_signals=rejected,
                rule_compliance=rule_compliance,
                api_cost_usd=api_cost,
                score=score,
            )
        )
    return sorted(rows, key=lambda row: row.score, reverse=True)


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    sd = pstdev(returns)
    return mean(returns) / sd if sd else 0.0


def _sortino(returns: list[float]) -> float:
    if not returns:
        return 0.0
    downside = [r for r in returns if r < 0]
    if not downside:
        return float(mean(returns) > 0)
    sd = pstdev(downside)
    return mean(returns) / sd if sd else 0.0


def _equity_curve_drawdowns(pnls: list[float], initial: float) -> list[float]:
    equity = initial
    peak = initial
    drawdowns = []
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdowns.append((equity - peak) / peak)
    return drawdowns


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))
