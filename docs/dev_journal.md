# Dev Journal — Generative Memory Upgrade

> **Status**: AWAITING APPROVAL  
> **Last updated**: 2026-05-22  
> **Goal**: Replace broken lesson pipeline with Generative Agents memory architecture (recency × relevance × importance retrieval + Statistical World Model + Confidence Calibration)

---

## Problem Summary

| # | Problem | Impact |
|---|---------|--------|
| P1 | `reflect_on_day()` runs every 4h cycle → writes identical "Daily review: equity=..." string | 147/156 lessons are noise |
| P2 | `lesson_canonicalizer.py` has 11 hardcoded templates → collapses all lessons to 4 strings | ChromaDB holds near-identical docs |
| P3 | `retrieve_lessons()` orders by `created_at DESC` → always returns most recent = always the noise | Bot gets 2 generic lines per cycle |
| P4 | `shared_lessons` promotion gate: requires win_rate ≥ 0.60, DeepSeek win_rate ≈ 0.40 | 15,416 rejections, 0 promotions ever |
| P5 | `AUTO_CLOSE` / `AUTO_REDUCE` events not captured in any lesson | Richest learning signal is lost |
| P6 | No regime×direction win rate table | Bot has no statistical grounding |
| P7 | No confidence calibration | Bot overconfident at 0.8 confidence (actual ~35% win rate) |

---

## Architecture: What We're Building

```
Current:  reflect_on_day() ──noise──> lessons table ──recency──> 2 generic lines in prompt
                                                                         ↓
                                                               Bot ignores history

Proposed: trade CLOSE/CUT ──bot writes──> structured_lessons ──3-factor score──> top 4-6 relevant lessons
          AUTO_CLOSE      ──Python writes──>     ↑                                        ↓
                                                                         FOLLOW / AVOID sections in prompt
                                                                         + World Model (~150 tokens)
                                                                         + Calibration (~80 tokens)
```

**Retrieval formula** (Generative Agents, Stanford 2023):
```
score = 0.3 × recency + 0.4 × relevance + 0.3 × importance

recency    = exp(-0.1 × days_since_creation)        # time decay, no LLM
relevance  = keyword_overlap(query, lesson_text)     # regime + direction + setup_type
importance = min(1.0, abs(realized_pnl_pct) × 10)   # PnL magnitude, no LLM
```

---

## Implementation Plan

### Phase 1 — Stop Noise Source
**Goal**: Eliminate 147/156 garbage lessons from pipeline.

| Step | File | Change |
|------|------|--------|
| 1.1 | `src/agents/reflection.py` | `reflect_on_day()`: remove `memory.save_lesson()` + `repository.save_reflection()` calls; keep return value for backward compat |

**Risk**: Low. `reflect_on_day()` return value is not used by any caller beyond runner logging.

---

### Phase 2 — New StructuredLesson Storage
**Goal**: Dedicated table for high-signal lessons (bot-written on close, system-written on AUTO events).

| Step | File | Change |
|------|------|--------|
| 2.1 | `src/storage/models.py` | Add `StructuredLessonRecord` ORM model |
| 2.2 | `src/storage/models.py` | Add `_migrate_sqlite()` block to CREATE the new table |
| 2.3 | `src/storage/repository.py` | Add `save_structured_lesson()` and `structured_lessons(agent_id, limit, regime, direction)` methods |

**Schema** of `StructuredLessonRecord`:
```
id, agent_id, created_at,
what_happened TEXT,     ← "SHORT failed at resistance when BTC reversed"
why TEXT,               ← "No volume confirmation in RANGING market"
lesson TEXT,            ← "Require volume spike before SHORT in RANGING"
follow_or_avoid TEXT,   ← "follow" | "avoid"
regime TEXT,            ← "RANGING" | "TRENDING" | etc.
direction TEXT,         ← "LONG" | "SHORT" | "NONE"
setup_type TEXT,        ← from signal or AUTO_CLOSE context
realized_pnl_pct FLOAT, ← for importance scoring
confidence_at_entry FLOAT,
source TEXT             ← "bot_signal" | "auto_close" | "auto_reduce"
```

---

### Phase 3 — Bot Writes Lessons on Close/Cut
**Goal**: Bot produces structured lesson in same LLM call when closing a trade.

| Step | File | Change |
|------|------|--------|
| 3.1 | `src/schemas.py` | Add optional `structured_lesson: StructuredLessonPayload \| None = None` field to `AgentSignal` |
| 3.2 | `prompts/system_prompt.md` | Add instruction: on CLOSE/CUT, include `structured_lesson` object in JSON with required fields |
| 3.3 | `src/competition/runner.py` | After signal accepted: if `structured_lesson` present → `repository.save_structured_lesson()` |

**Zero extra LLM calls** — structured_lesson is part of the existing signal JSON response.

---

### Phase 4 — Python Lessons for AUTO Events
**Goal**: Capture AUTO_CLOSE / AUTO_REDUCE events (currently invisible to lesson system).

| Step | File | Change |
|------|------|--------|
| 4.1 | `src/trading/risk_automation/engine.py` | On AUTO_CLOSE / AUTO_REDUCE: generate `StructuredLessonPayload` from trade data and call `repository.save_structured_lesson()` |

**Lesson generated** (example):
```
what_happened: "AUTO_CLOSE triggered after 8h hold, stop-loss breached"
why: "Position held past invalidation point without time_exit rule"
lesson: "Set time_exit ≤ 6h when no trend confirmation in RANGING"
follow_or_avoid: "avoid"
source: "auto_close"
```

---

### Phase 5 — Generative Agents Retrieval
**Goal**: Replace recency-only retrieval with 3-factor scoring.

| Step | File | Change |
|------|------|--------|
| 5.1 | `src/agents/memory.py` | Replace `retrieve_lessons()` with 3-factor scored retrieval from `structured_lessons` table |
| 5.2 | `src/agents/memory.py` | Importance score: `min(1.0, abs(pnl_pct) * 10)`, loss weighted slightly higher |
| 5.3 | `src/competition/runner.py` | Enrich retrieval query: `f"{regime} {direction} {setup_type}"` instead of `f"{regime} BTC"` |

**Before**: `ORDER BY created_at DESC LIMIT 6` → always same 6 recent noise  
**After**: `scored_list[:6]` → 6 most recency+relevant+important lessons for current context

---

### Phase 6 — Statistical World Model
**Goal**: Show bot regime×direction win rate from actual trade history.

| Step | File | Change |
|------|------|--------|
| 6.1 | `src/analytics/world_model.py` | New file: `get_world_model(repository, agent_id)` → SQL GROUP BY regime, direction; returns formatted string |
| 6.2 | `src/competition/runner.py` | Include world model block in context when `sample_size >= 3` |

**Output example** (~150 tokens):
```
HISTORICAL PERFORMANCE (your trade history):
RANGING × SHORT: 2W/5L = 28.6% win rate, avg PnL -1.2%
TRENDING × LONG: 3W/2L = 60.0% win rate, avg PnL +2.1%
(only regimes with ≥3 trades shown)
```

---

### Phase 7 — Confidence Calibration
**Goal**: Show bot whether its stated confidence matches actual outcomes.

| Step | File | Change |
|------|------|--------|
| 7.1 | `src/analytics/calibration.py` | New file: `get_calibration(repository, agent_id)` → buckets confidence by 0.1 steps; compares to actual win rate |
| 7.2 | `src/competition/runner.py` | Include calibration block in context when `sample_size >= 5` |

**Output example** (~80 tokens):
```
CONFIDENCE CALIBRATION:
confidence=0.8 → actual win rate 33% (3 trades) ← reconsider high confidence
confidence=0.6 → actual win rate 50% (4 trades)
```

---

### Phase 8 — Update Prompt Builder
**Goal**: Prompt shows FOLLOW / AVOID sections separately + World Model + Calibration.

| Step | File | Change |
|------|------|--------|
| 8.1 | `src/competition/runner.py` | Split retrieved lessons into FOLLOW / AVOID by `follow_or_avoid` field |
| 8.2 | `src/competition/runner.py` | Format prompt sections: `### LESSONS TO FOLLOW`, `### LESSONS TO AVOID`, `### REGIME STATS`, `### CONFIDENCE CALIBRATION` |

**Token overhead**: +~300 tokens/cycle total (World Model + Calibration). Lessons section stays ≤ same size.

---

### Phase 9 — Fix Shared Lessons Threshold
**Goal**: Allow shared lessons to actually promote.

| Step | File | Change |
|------|------|--------|
| 9.1 | `config/settings.yaml` | `min_win_rate: 0.60 → 0.40` |

---

### Phase 10 — Tests
**Goal**: Cover all new components without breaking existing suite.

| Test file | Tests |
|-----------|-------|
| `tests/test_structured_lessons.py` | save + retrieve structured lessons; importance scoring |
| `tests/test_world_model.py` | SQL aggregation with mock trades; min sample_size gate |
| `tests/test_calibration.py` | bucket grouping; empty data edge case |
| `tests/test_lesson_retrieval.py` | 3-factor scoring ranks correctly; dedup |
| `tests/test_reflect_on_day_no_save.py` | `reflect_on_day()` returns string but does NOT write to DB |

---

## File Change Map

```
MODIFIED:
  src/agents/reflection.py         [Phase 1]  — stop daily lesson spam
  src/agents/memory.py             [Phase 5]  — 3-factor retrieval
  src/storage/models.py            [Phase 2]  — new StructuredLessonRecord + migration
  src/storage/repository.py        [Phase 2]  — new repo methods
  src/schemas.py                   [Phase 3]  — optional structured_lesson in AgentSignal
  src/competition/runner.py        [Phases 3,5,6,7,8] — context builder updates
  src/trading/risk_automation/engine.py [Phase 4] — auto event lessons
  prompts/system_prompt.md         [Phase 3]  — instruct bot to write structured_lesson
  config/settings.yaml             [Phase 9]  — lower promotion threshold

NEW:
  src/analytics/world_model.py     [Phase 6]
  src/analytics/calibration.py     [Phase 7]
  tests/test_structured_lessons.py [Phase 10]
  tests/test_world_model.py        [Phase 10]
  tests/test_calibration.py        [Phase 10]
  tests/test_lesson_retrieval.py   [Phase 10]
  tests/test_reflect_on_day_no_save.py [Phase 10]
```

---

## Dependencies Between Phases

```
Phase 1 (stop noise)
    └── independent — do first
Phase 2 (storage)
    └── must precede Phase 3, 4, 5
Phase 3 (bot lesson schema)
    └── depends on Phase 2
Phase 4 (auto event lessons)
    └── depends on Phase 2
Phase 5 (retrieval)
    └── depends on Phase 2
Phase 6, 7 (World Model, Calibration)
    └── independent — read existing trades table only
Phase 8 (prompt builder)
    └── depends on Phases 5, 6, 7
Phase 9 (threshold)
    └── independent
Phase 10 (tests)
    └── after all above
```

---

## What This Does NOT Change

- Trading strategy or rulebook — untouched
- Risk automation logic — only adds lesson writing, no behavior change
- Dashboard UI/UX — lesson tabs will auto-improve as structured_lessons fills
- Existing lessons table — preserved for audit; new pipeline uses structured_lessons
- Token budget — net change ≈ +300 tokens/cycle (acceptable)

---

## Progress Log

| Date | Phase | Status | Notes |
|------|-------|--------|-------|
| 2026-05-22 | Plan | DONE | Plan created and approved |
| 2026-05-22 | Phase 1 | DONE | `src/agents/reflection.py` — `reflect_on_day()` no longer writes to lessons/ChromaDB |
| 2026-05-22 | Phase 2 | DONE | `models.py` + `repository.py` — `StructuredLessonRecord`, migration, `save_structured_lesson()`, `structured_lessons()` |
| 2026-05-22 | Phase 3 | DONE | `schemas.py` + `system_prompt.md` + `runner.py` — bot writes `structured_lesson` on CLOSE/CUT, saved to DB |
| 2026-05-22 | Phase 4 | DONE | `engine.py` time-exit lesson + `runner.py` `_save_auto_trade_lesson()` for stop-loss/TP/AUTO events |
| 2026-05-22 | Phase 5 | DONE | `memory.py` 3-factor retrieval; `runner.py` enriched query with direction |
| 2026-05-22 | Phase 6 | DONE | `src/analytics/world_model.py` — regime×direction win-rate from structured_lessons |
| 2026-05-22 | Phase 7 | DONE | `src/analytics/calibration.py` — confidence bucket → actual win-rate |
| 2026-05-22 | Phase 8 | DONE | `runner.py` — `_format_lesson_blocks()`, `_format_stat_blocks()`, World Model + Calibration injected |
| 2026-05-22 | Phase 9 | DONE | `config/settings.yaml` — `min_win_rate: 0.60 → 0.40` |
| 2026-05-22 | Phase 10 | DONE | 4 new test files + updated existing test; 169 passed, validate-update PASS |
| 2026-05-22 | All phases | COMPLETE | Implementation done, tests green, committing |
