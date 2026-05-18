from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


LessonSentiment = Literal["follow", "avoid"]


@dataclass(frozen=True)
class CanonicalLesson:
    raw_text: str
    summary: str
    category: str
    sentiment: LessonSentiment
    confidence: float
    impact: float
    evidence_count: int
    last_updated: str


def canonicalize_lesson(raw_text: str, *, evidence_count: int = 1, last_updated: datetime | None = None) -> CanonicalLesson:
    raw = str(raw_text or "").strip()
    cleaned = _clean(raw)
    summary = _template_summary(cleaned)
    summary = _limit_words(summary, 25)
    category = _category(summary, cleaned)
    sentiment = _sentiment(summary, cleaned)
    confidence = min(0.95, 0.45 + 0.08 * max(1, evidence_count))
    impact = min(0.95, 0.45 + 0.06 * max(1, evidence_count))
    updated = last_updated or datetime.now(UTC)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return CanonicalLesson(
        raw_text=raw,
        summary=summary,
        category=category,
        sentiment=sentiment,
        confidence=round(confidence, 4),
        impact=round(impact, 4),
        evidence_count=max(1, int(evidence_count or 1)),
        last_updated=updated.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    )


def canonical_summary(raw_text: str) -> str:
    return canonicalize_lesson(raw_text).summary


def lesson_key(raw_text: str) -> str:
    summary = canonical_summary(raw_text).lower()
    return " ".join(re.sub(r"[^a-z0-9+_ -]", " ", summary).split())


def _clean(text: str) -> str:
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b", " ", text)
    text = re.sub(r"\b[A-Z]{2,}-[A-Z]+-\d+\b", " ", text)
    text = re.sub(r"\b(?:trade|position|po)-[a-z0-9_-]+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:equity|realized_pnl|unrealized_pnl|pnl|fee|slippage_bps|entry|exit)=?-?\$?\d+(?:\.\d+)?\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:USDT|usd|days? remaining)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{4,}(?:\.\d+)?\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .;:-")
    return text


def _template_summary(text: str) -> str:
    lowered = text.lower()
    if "after-stop-loss wait rule" in lowered or ("short" in lowered and "stop" in lowered and "loss" in lowered):
        return "Pause new SHORT entries for one full cycle after a short stop-loss."
    if "keep valid setups only" in lowered or "preserve rule compliance" in lowered:
        return "Trade only high-quality setups and maintain strict rule compliance."
    if "place_trigger" in lowered or "pullback" in lowered or "confirmation" in lowered:
        return "Use PLACE_TRIGGER when waiting for pullback confirmation."
    if "break_even" in lowered or "break-even" in lowered or "+1r" in lowered:
        return "Move stop to break-even after +1R."
    if "trail" in lowered or "trailing" in lowered:
        return "Use trailing stops only when trend continuation is likely."
    if "time_exit" in lowered or "stale" in lowered:
        return "Exit stale trades when the thesis does not play out on time."
    if "overtrad" in lowered or "consecutive losses" in lowered:
        return "Avoid overtrading after consecutive losses."
    if "short" in lowered and any(term in lowered for term in ["loss", "failed", "weak", "caution"]):
        return "Recent SHORT setups are weakening; pause and reassess before shorting again."
    if "long" in lowered and any(term in lowered for term in ["loss", "failed", "weak", "caution"]):
        return "Recent LONG setups are weakening; pause and reassess before longing again."
    if any(term in lowered for term in ["loss", "avoid", "failed", "caution"]):
        return "Avoid repeating weak setups until risk and confirmation improve."
    if any(term in lowered for term in ["win", "repeat", "worked", "take_profit"]):
        return "Repeat only high-quality setups with clear thesis, invalidation, and risk/reward."
    return _first_sentence(text)


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    sentence = (parts[0] if parts else text).strip(" .;:-")
    if not sentence:
        return "Trade only clear, rule-compliant setups."
    return sentence[0].upper() + sentence[1:] + ("." if sentence[-1] not in ".!?" else "")


def _limit_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]).rstrip(" ,;:") + "."


def _category(summary: str, text: str) -> str:
    lowered = f"{summary} {text}".lower()
    if "rule compliance" in summary.lower() or "high-quality setups" in summary.lower():
        return "risk_management"
    if any(term in lowered for term in ["break-even", "+1r", "risk", "overtrad", "stop-loss", "stop loss"]):
        return "risk_management"
    if any(term in lowered for term in ["exit", "stale", "take_profit", "trailing"]):
        return "exit"
    if any(term in lowered for term in ["place_trigger", "pullback", "confirmation", "entry"]):
        return "entry"
    if any(term in lowered for term in ["trend", "range", "regime", "downtrend"]):
        return "market_regime"
    if any(term in lowered for term in ["slippage", "fee", "execution"]):
        return "execution"
    if any(term in lowered for term in ["discipline", "patience", "chase"]):
        return "psychology"
    return "system"


def _sentiment(summary: str, text: str) -> LessonSentiment:
    lowered = f"{summary} {text}".lower()
    avoid_terms = ["avoid", "pause", "caution", "loss", "failed", "weakening", "do not", "stop-loss"]
    return "avoid" if any(term in lowered for term in avoid_terms) else "follow"
