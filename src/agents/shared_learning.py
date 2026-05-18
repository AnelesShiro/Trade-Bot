from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from src.config import Settings, SharedLearningSettings
from src.storage.models import SignalRecord, TradeRecord
from src.storage.repository import ArenaRepository


IDENTITY_BLOCK = (
    "You have a unique trading identity.\n"
    "Use shared lessons as optional guidance.\n"
    "Do not imitate the other agent.\n"
    "Prioritize your own historical edge and strategy profile.\n"
    "Maintain distinct decision-making behavior."
)

SHARED_LESSON_DISCLAIMER = (
    "The following are optional cross-agent insights.\n"
    "Use them only when they align with your own strategy and evidence.\n"
    "Evidence-backed lessons about PLACE_TRIGGER, trailing stops, break-even, and time exits are valid."
)


class StrategyProfile(BaseModel):
    agent_id: str
    archetype: str
    preferred_indicators: list[str] = Field(default_factory=list)
    preferred_regimes: list[str] = Field(default_factory=list)
    aggressiveness: str = "moderate"
    confidence_calibration: str = "balanced"

    def strategy_identity_statement(self) -> str:
        indicators = ", ".join(self.preferred_indicators) or "agent-specific evidence"
        regimes = ", ".join(self.preferred_regimes) or "validated regimes"
        return (
            f"Strategy profile for {self.agent_id}: archetype={self.archetype}; "
            f"preferred_indicators={indicators}; preferred_regimes={regimes}; "
            f"aggressiveness={self.aggressiveness}; confidence_calibration={self.confidence_calibration}."
        )


@dataclass(frozen=True)
class RetrievedLessons:
    private_lessons: list[str]
    shared_lessons: list[str]
    shared_lesson_ids: list[int]
    shared_ratio_applied: float
    convergence_warning: bool


DEFAULT_PROFILES = {
    "crypto-deepseek": StrategyProfile(
        agent_id="crypto-deepseek",
        archetype="trend_following",
        preferred_indicators=["EMA", "MACD", "OI", "volume"],
        preferred_regimes=["breakout", "strong_trend"],
        aggressiveness="moderate",
        confidence_calibration="evidence_weighted",
    ),
    "crypto-grok": StrategyProfile(
        agent_id="crypto-grok",
        archetype="mean_reversion",
        preferred_indicators=["RSI", "Bollinger Bands", "support/resistance"],
        preferred_regimes=["range", "exhaustion"],
        aggressiveness="selective",
        confidence_calibration="skeptical",
    ),
    "crypto-qwen": StrategyProfile(
        agent_id="crypto-qwen",
        archetype="mean_reversion",
        preferred_indicators=["RSI", "Bollinger Bands", "support/resistance"],
        preferred_regimes=["range", "exhaustion"],
        aggressiveness="selective",
        confidence_calibration="skeptical",
    ),
}


class SharedLearningManager:
    """Hybrid private/shared lesson manager with anti-convergence controls."""

    def __init__(self, repository: ArenaRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.config = settings.shared_learning
        self.profile_dir = settings.resolve_path("data/profiles")
        self.private_dir = settings.resolve_path("data/private")
        self.shared_dir = settings.resolve_path("data/shared")

    def ensure_storage(self) -> None:
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_shared_db()
        for agent in self.settings.agents:
            (self.private_dir / _short_agent(agent.id)).mkdir(parents=True, exist_ok=True)
            profile = self.profile(agent.id)
            profile_path = self.profile_dir / f"{_short_agent(agent.id)}_profile.json"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
            self.repository.save_strategy_profile(agent.id, profile.model_dump())

    def profile(self, agent_id: str) -> StrategyProfile:
        stored = self.repository.strategy_profile(agent_id)
        if stored:
            return StrategyProfile.model_validate(stored)
        return DEFAULT_PROFILES.get(
            agent_id,
            StrategyProfile(agent_id=agent_id, archetype="balanced", preferred_indicators=[], preferred_regimes=[]),
        )

    def retrieve_for_prompt(
        self,
        agent_id: str,
        query: str,
        private_lessons: list[str],
        total_limit: int = 8,
    ) -> RetrievedLessons:
        if not self.config.enabled:
            return RetrievedLessons(private_lessons[:total_limit], [], [], 0.0, False)
        metric = self.repository.latest_diversity_metric()
        convergence_warning = bool(metric and metric.convergence_warning)
        shared_ratio = self.config.reduced_shared_ratio if convergence_warning else self.config.shared_ratio
        shared_limit = max(1, math.floor(total_limit * shared_ratio)) if total_limit > 1 else 0
        private_limit = max(1, total_limit - shared_limit)
        if convergence_warning:
            shared_limit = min(shared_limit, max(1, math.floor(total_limit * self.config.reduced_shared_ratio)))
            private_limit = total_limit - shared_limit

        profile = self.profile(agent_id)
        ranked = self._rank_shared_lessons(agent_id, query, profile, shared_limit)
        shared_ids = [item["id"] for item in ranked]
        self.repository.increment_shared_lesson_usage(shared_ids)
        return RetrievedLessons(
            private_lessons=private_lessons[:private_limit],
            shared_lessons=[item["text"] for item in ranked],
            shared_lesson_ids=shared_ids,
            shared_ratio_applied=shared_ratio,
            convergence_warning=convergence_warning,
        )

    def promote_lessons(self) -> dict[str, Any]:
        results: dict[str, Any] = {"promoted": 0, "rejected": 0, "deduplicated_or_existing": 0}
        for agent in self.settings.agents:
            stats = _trade_stats(self.repository.trades(agent.id))
            for lesson in self.repository.lesson_records(agent.id, limit=200):
                accepted, reason = self._promotion_reason(lesson.content, stats)
                if not accepted:
                    self.repository.save_lesson_promotion(agent.id, lesson.id, "rejected", reason)
                    results["rejected"] += 1
                    continue
                shared_id = self.repository.save_shared_lesson(
                    source_agent=agent.id,
                    market_regime=_infer_regime(lesson.content),
                    lesson_text=_generalize_lesson(lesson.content),
                    confidence=_confidence(stats),
                    sample_size=stats["sample_size"],
                    win_rate=stats["win_rate"],
                    profit_factor=stats["profit_factor"],
                    lesson_type="failure_caution" if _is_failure_lesson(lesson.content) else "best_practice",
                )
                if shared_id is None:
                    results["deduplicated_or_existing"] += 1
                else:
                    results["promoted"] += 1
        self._sync_shared_db()
        return results

    def rebuild_shared_knowledge(self) -> dict[str, Any]:
        return self.promote_lessons()

    def analyze_diversity(self, window_size: int = 50) -> dict[str, Any]:
        signals = self._recent_signals(window_size)
        payload = calculate_diversity_metrics(signals, self.config)
        self.repository.save_diversity_metric(payload)
        return payload

    def _promotion_reason(self, lesson: str, stats: dict[str, Any]) -> tuple[bool, str]:
        if stats["sample_size"] < self.config.min_sample_size:
            return False, f"sample_size {stats['sample_size']} below {self.config.min_sample_size}"
        if stats["win_rate"] < self.config.min_win_rate:
            return False, f"win_rate {stats['win_rate']:.2f} below {self.config.min_win_rate:.2f}"
        if stats["profit_factor"] < self.config.min_profit_factor:
            return False, f"profit_factor {stats['profit_factor']:.2f} below {self.config.min_profit_factor:.2f}"
        if not is_generalized_lesson(lesson):
            return False, "lesson is tied to exact prices or raw ledger details"
        return True, "passed"

    def _rank_shared_lessons(
        self,
        agent_id: str,
        query: str,
        profile: StrategyProfile,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        candidates = []
        for lesson in self.repository.shared_lessons(exclude_source_agent=agent_id, limit=100):
            compatibility = compatibility_score(profile, lesson.lesson_text, lesson.market_regime)
            if compatibility < self.config.compatibility_threshold:
                continue
            score = (
                0.35 * text_similarity(query, lesson.lesson_text)
                + 0.25 * min(1.0, lesson.profit_factor / 3.0)
                + 0.20 * lesson.win_rate
                + 0.10 * min(1.0, lesson.sample_size / 50.0)
                + 0.10 * compatibility
            )
            candidates.append({"id": lesson.id, "text": lesson.lesson_text, "score": score})
        return sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]

    def _recent_signals(self, window_size: int) -> dict[str, list[SignalRecord]]:
        with self.repository.session_factory() as session:
            data: dict[str, list[SignalRecord]] = {}
            for agent in self.settings.agents:
                stmt = (
                    select(SignalRecord)
                    .where(SignalRecord.agent_id == agent.id)
                    .order_by(SignalRecord.created_at.desc())
                    .limit(window_size)
                )
                data[agent.id] = list(reversed(list(session.scalars(stmt))))
            return data

    def _ensure_shared_db(self) -> None:
        db_path = self.shared_dir / "validated_lessons.db"
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """
                create table if not exists shared_lessons (
                    id integer primary key,
                    source_agent text not null,
                    market_regime text not null,
                    lesson_text text not null,
                    lesson_type text not null,
                    confidence real not null,
                    sample_size integer not null,
                    win_rate real not null,
                    profit_factor real not null,
                    usage_count integer not null,
                    promoted_at text not null
                )
                """
            )

    def _sync_shared_db(self) -> None:
        self._ensure_shared_db()
        db_path = self.shared_dir / "validated_lessons.db"
        lessons = self.repository.shared_lessons(limit=10000)
        with sqlite3.connect(db_path) as connection:
            connection.execute("delete from shared_lessons")
            connection.executemany(
                """
                insert into shared_lessons (
                    id, source_agent, market_regime, lesson_text, lesson_type, confidence,
                    sample_size, win_rate, profit_factor, usage_count, promoted_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        lesson.id,
                        lesson.source_agent,
                        lesson.market_regime,
                        lesson.lesson_text,
                        lesson.lesson_type,
                        lesson.confidence,
                        lesson.sample_size,
                        lesson.win_rate,
                        lesson.profit_factor,
                        lesson.usage_count,
                        lesson.promoted_at.isoformat(),
                    )
                    for lesson in lessons
                ],
            )


def calculate_diversity_metrics(signals_by_agent: dict[str, list[SignalRecord]], config: SharedLearningSettings) -> dict[str, Any]:
    agents = list(signals_by_agent)
    if len(agents) < 2:
        return _empty_diversity(config.shared_ratio)
    left = signals_by_agent[agents[0]]
    right = signals_by_agent[agents[1]]
    pairs = list(zip(left[-50:], right[-50:], strict=False))
    if not pairs:
        return _empty_diversity(config.shared_ratio)
    action_agree = mean([1.0 if a.action == b.action else 0.0 for a, b in pairs])
    direction_agree = mean([1.0 if _payload(a).get("direction") == _payload(b).get("direction") else 0.0 for a, b in pairs])
    leverage_similarity = mean([_numeric_similarity(_payload(a).get("leverage"), _payload(b).get("leverage"), 10.0) for a, b in pairs])
    confidence_correlation = _correlation([float(_payload(a).get("confidence") or 0) for a, _ in pairs], [float(_payload(b).get("confidence") or 0) for _, b in pairs])
    thesis_similarity = mean([text_similarity(str(_payload(a).get("thesis") or ""), str(_payload(b).get("thesis") or "")) for a, b in pairs])
    warning = action_agree > config.agreement_threshold
    return {
        "window_size": len(pairs),
        "action_agreement_rate": float(action_agree),
        "directional_agreement_rate": float(direction_agree),
        "leverage_similarity": float(leverage_similarity),
        "confidence_correlation": float(confidence_correlation),
        "thesis_embedding_similarity": float(thesis_similarity),
        "convergence_warning": int(warning),
        "shared_ratio_applied": config.reduced_shared_ratio if warning else config.shared_ratio,
    }


def compatibility_score(profile: StrategyProfile, lesson_text: str, market_regime: str = "") -> float:
    text = f"{lesson_text} {market_regime}".lower()
    trend_terms = {"breakout", "trend", "momentum", "ema", "macd", "oi", "open interest", "volume", "continuation"}
    reversion_terms = {"range", "mean reversion", "rsi", "bollinger", "support", "resistance", "exhaustion", "overbought", "oversold"}
    trend_hits = sum(term in text for term in trend_terms)
    reversion_hits = sum(term in text for term in reversion_terms)
    if profile.archetype == "trend_following":
        return max(0.0, min(1.0, 0.45 + 0.12 * trend_hits - 0.10 * reversion_hits))
    if profile.archetype == "mean_reversion":
        return max(0.0, min(1.0, 0.45 + 0.12 * reversion_hits - 0.10 * trend_hits))
    return 0.60


def is_generalized_lesson(text: str) -> bool:
    cleaned = text.lower()
    if re.search(r"\b\d{4,}(?:\.\d+)?\b", cleaned):
        return False
    ledger_terms = ["entry=", "exit=", "pnl=", "position_id"]
    return not any(term in cleaned for term in ledger_terms)


def text_similarity(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _trade_stats(trades: list[TradeRecord]) -> dict[str, Any]:
    closed = [trade.realized_pnl for trade in trades if trade.exit_price is not None or trade.realized_pnl != 0]
    wins = [pnl for pnl in closed if pnl > 0]
    losses = [abs(pnl) for pnl in closed if pnl < 0]
    return {
        "sample_size": len(closed),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": sum(wins) / sum(losses) if losses else (99.0 if wins else 0.0),
    }


def _confidence(stats: dict[str, Any]) -> float:
    return min(1.0, 0.40 * min(1.0, stats["sample_size"] / 50) + 0.30 * stats["win_rate"] + 0.30 * min(1.0, stats["profit_factor"] / 3))


def _generalize_lesson(text: str) -> str:
    generalized = re.sub(r"\b\d{4,}(?:\.\d+)?\b", "the relevant level", text)
    generalized = re.sub(r"\b(entry|exit|pnl)=[^,\s]+", "", generalized, flags=re.IGNORECASE)
    return " ".join(generalized.split())


def _is_failure_lesson(text: str) -> bool:
    return any(term in text.lower() for term in ["loss", "avoid", "failed", "do not", "wrong"])


def _infer_regime(text: str) -> str:
    lowered = text.lower()
    for term in ["breakout", "strong_trend", "trend", "range", "exhaustion"]:
        if term in lowered:
            return term
    return "unknown"


def _payload(signal: SignalRecord) -> dict[str, Any]:
    try:
        return json.loads(signal.payload_json or "{}")
    except json.JSONDecodeError:
        return {}


def _numeric_similarity(left: Any, right: Any, scale: float) -> float:
    try:
        return max(0.0, 1.0 - abs(float(left or 0) - float(right or 0)) / scale)
    except (TypeError, ValueError):
        return 0.0


def _correlation(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or len(right) < 2 or pstdev(left) == 0 or pstdev(right) == 0:
        return 0.0
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=False))
    denominator = len(left) * pstdev(left) * pstdev(right)
    return numerator / denominator if denominator else 0.0


def _terms(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "when", "that", "this", "from", "only", "into", "your", "own"}
    return {term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9_/.-]+", text.lower()) if term not in stop}


def _empty_diversity(shared_ratio: float) -> dict[str, Any]:
    return {
        "window_size": 0,
        "action_agreement_rate": 0.0,
        "directional_agreement_rate": 0.0,
        "leverage_similarity": 0.0,
        "confidence_correlation": 0.0,
        "thesis_embedding_similarity": 0.0,
        "convergence_warning": 0,
        "shared_ratio_applied": shared_ratio,
    }


def _short_agent(agent_id: str) -> str:
    lowered = agent_id.lower()
    return "deepseek" if "deepseek" in lowered else "grok" if "grok" in lowered else "qwen" if "qwen" in lowered else agent_id.replace("crypto-", "")
