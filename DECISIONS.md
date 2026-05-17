# Architecture Decisions

## 2026-05-18 — Local risk automation engine

- **Decision:** Implement conditional orders, trailing stop, break-even, time exit, cooldowns, and API failover as a local `RiskAutomationEngine` that reuses market snapshots and the position monitor. Do not add LLM rounds for automation.
- **Why:** Exchange-style execution (OKX/Binance) without increasing token cost or changing default agent behavior.
- **Backward compatibility:** `risk_automation.*.apply_by_default: false`; standard `OPEN`/`MARKET` path unchanged. Opt-in via `PLACE_TRIGGER`, `trigger_order`, `position_risk`.
- **Cooldown:** Skip the agent LLM call entirely while active (saves tokens); continue managing open positions locally.
- **API failover:** Separate from `LLM_ALLOW_FALLBACK`; explicit events in SQLite and optional per-agent `fallback_chain` (disabled by default on active agents).
- **Alternatives rejected:** Prompt-only WATCHLIST triggers (no execution); per-request `--model` overrides (Gateway rejects).
