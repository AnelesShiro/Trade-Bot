# Project Bootstrap

Read this file first in every new Codex session. `AGENTS.md` in this repo and in the parent workspace instruct Codex to do this proactively so the user should not need to ask. This is the low-token entry point; read `PROJECT_CONTEXT.md` only when deeper architecture/context is needed, then read the latest entries at the bottom of `logs/SESSION_UPDATES.md`.

## Current State

- Project: `crypto-paper-trading-arena`, BTCUSDT continuous paper-trading system. **No end date — runs indefinitely.**
- Active agents: `crypto-deepseek` (running, model `deepseek-v4-flash`) and `crypto-qwen` (running, model `qwen3-max` via DashScope Standard Global URL).
- Legacy `crypto-grok` data remains in SQLite for history/audit only.
- Latest verified live cycle/checkpoint: `84` completed at `2026-05-19T15:51:10Z`.
- Current live runner is one normal Windows parent-child process tree.
- Current active open positions at last check: none.
- DeepSeek model lock: `deepseek-v4-flash`. Qwen model lock: `qwen3-max`.
- Risk automation: enabled in `config/settings.yaml` (`risk_automation`). Optional agent fields: `PLACE_TRIGGER`, `trigger_order`, `position_risk`. Default trading unchanged without those fields.
- API failover is explicitly enabled per active agent. DeepSeek -> Qwen fallback; Qwen -> DeepSeek fallback. Silent model switching remains impossible (`LLM_ALLOW_FALLBACK: false`).
- **Continuous mode**: `duration_days: 0` in config. The runner loops forever with `while True`; only a kill-switch file (`KILL_SWITCH`) or graceful restart stops it. No `COMPLETED` status is ever emitted.
- **Soft weekly KPI**: `weekly_target_pct: 0.07` (+7% per rolling 7-day period). Never a hard requirement; never forces trades; never used as a validator rejection condition.
- Dashboard shows **Project Uptime**, **Rolling 7d Return**, **Weekly Target Progress**, and **Project Start** instead of time-remaining/end-date metrics.

## Re-activating crypto-qwen (already done as of 2026-05-20)

Both agents are active. To restore after a credential rotation:

**Step 1** — Update `QWEN_API_KEY` in `.env`.

**Step 2** — Re-register:

```powershell
.\.venv\Scripts\python.exe -m src.cli init
.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke
.\.venv\Scripts\python.exe -m src.cli preflight-check
```

**Step 3** — Smoke test:

```powershell
openclaw agent --agent crypto-qwen --session-id qwen-smoke --message "Return exactly OK." --timeout 120
```

- Prompt/rulebook include validated signal templates, the exact risk formula, and concise guidance that agents must consider advanced trade management on every setup: prefer `PLACE_TRIGGER` for future conditions, break-even is enforced locally around +1R on every open trade, use time exits when useful, and trailing stops selectively for trends. Risk formula: `account_risk_usdt = abs(entry - stop_loss) / entry * notional_exposure_usdt`. Do not multiply leverage again after computing notional.
- Runner now writes `runner_state` to SQLite during every live cycle (`CALLING_DEEPSEEK`, `CALLING_QWEN`, etc.). Dashboard/snapshot should show `TRADING` while bots are processing; `OVERDUE` should only appear when no active processing state exists and the next scheduled cycle is genuinely late.
- Missed-cycle audit: on `run-live --resume`, the runner compares persisted `runner_state.next_cycle_at` with actual resume time. If a scheduled slot was missed during downtime, it records `MISSED_SCHEDULED_CYCLE` in downtime events, health checks, risk notifications, and snapshot `downtime.latest_missed_cycle`. This is audit-only and does not backfill trades.
- Render/cloud dashboard snapshot mode mirrors the local risk automation tabs: Pending Orders, Risk Automation, and API Failover Events. Snapshot contract requires the `risk_automation` payload.
- Dashboard UI contract: local SQLite mode and Render snapshot mode must use the same `DASHBOARD_TAB_LABELS` from `src/dashboard/contract.py`; `tests/test_dashboard_contract.py` prevents tab-list drift.
- Read-only lesson analytics tabs are available in both local and Render dashboards: Lessons to Follow and Lessons to Avoid. They use existing lessons/shared lessons/reflections/trades only; no model calls and no trading behavior changes.
- Local SQLite mode and Render snapshot mode must both render lesson memory through canonical summaries with raw-text expanders. Snapshot payload includes `reflections_summary.recent` and `reflections_summary.recent_lessons` so Render can mirror local `Memory & Reflections`.
- Pending Orders dashboard now exposes order intent at a glance in both local and Render modes: action, direction, entry, stop, TP1, leverage, trigger summary, thesis, and expandable raw trigger/signal evidence.
- Trade History timestamp contract: display `execution_timestamp`/`displayed_timestamp` as the fill time. Preserve `decision_timestamp` for when the agent created the signal and fall back to legacy `created_at` only if execution time is unavailable.
- Lesson memory contract: lessons keep full `raw_text` for audit and deterministic canonical `summary` for prompts, shared learning, dashboard lesson cards, and memory tables. No LLM calls are used for summarization.

## Operating Rules

- Paper trading only. Never add real exchange order execution.
- Preserve dashboard UI/UX unless explicitly requested.
- Do not edit strategy/rulebook/trading behavior unless explicitly requested.
- Do not commit `.env`, API keys, or secrets.
- Runtime files in `outputs/` can be dirty because the live runner writes them. Do not revert them unless explicitly requested.
- Use `.venv\Scripts\python.exe` for commands and tests on this machine.

## Live Runner Notes

- On Windows, one live runner often appears as two process rows:
  `.venv\Scripts\python.exe` parent plus base Python child.
- Treat that as one runner process tree unless there are multiple unrelated parent trees.
- `run-live --resume` runs a cycle immediately on process start, then continues the schedule.
- One provider failure must not stop the full cycle; it should be recorded and checkpoint/snapshot should still complete.
- OpenClaw agent calls are bounded by `api.timeout_seconds: 180` and `api.max_retries: 1`; the CLI call also receives `--timeout <seconds>`. This prevents one hung provider call from blocking a live cycle for ~30 minutes.

## Model Governance

- Config source of truth: `config/settings.yaml` agent `llm` blocks.
- `LLM_ALLOW_FALLBACK` must remain `false`.
- Runtime calls do not use per-request `--model`; this OpenClaw Gateway rejects model overrides.
- `python -m src.cli init` registers OpenClaw agents with provider/model routing, syncs primary and fallback provider base URLs, and writes each agent's primary/fallback auth profiles from `.env`.
- After each OpenClaw call, code verifies actual response model equals `LLM_MODEL`.

## Fast Checks

```powershell
.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m src.cli preflight-check
```

Qwen smoke test:

```powershell
.\.venv\Scripts\python.exe -m src.cli init
openclaw agent --agent crypto-qwen --session-id qwen-smoke --message "Return exactly OK." --timeout 120
```

## Read Next

- `PROJECT_CONTEXT.md`: full project memory, architecture, constraints, testing/deployment info.
- `logs/SESSION_UPDATES.md`: curated recent session history. Read from the bottom upward.
- `docs/MODEL_GOVERNANCE.md`: model locking details.
