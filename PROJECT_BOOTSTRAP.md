# Project Bootstrap

Read this file first in every new Codex session. `AGENTS.md` in this repo and in the parent workspace instruct Codex to do this proactively so the user should not need to ask. This is the low-token entry point; read `PROJECT_CONTEXT.md` only when deeper architecture/context is needed, then read the latest entries at the bottom of `logs/SESSION_UPDATES.md`.

## Current State

- Project: `crypto-paper-trading-arena`, BTCUSDT paper-trading competition.
- Active agents: `crypto-deepseek` and `crypto-qwen`.
- Legacy `crypto-grok` data remains in SQLite for history/audit only. Do not merge it into Qwen.
- Latest verified live cycle/checkpoint: `50` completed.
- Recent API audit shows both DeepSeek and Qwen succeeded in cycles `48`, `49`, and `50`.
- Current active open positions: none at last check.
- DeepSeek currently works with strict model lock: `deepseek-v4-flash`.
- Qwen routing/registration and provider auth now work after switching OpenClaw Qwen to the Standard Global DashScope endpoint.
- Qwen model lock expected actual response model: `qwen3-max-2026-01-23`.
- Qwen base URL source of truth: `LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
- Risk automation: enabled in `config/settings.yaml` (`risk_automation`). Optional agent fields: `PLACE_TRIGGER`, `trigger_order`, `position_risk`. Default trading unchanged without those fields.
- API failover is explicitly enabled per active agent with configured DeepSeek <-> Qwen fallback chains, logged `api_failover_events`, active-route state, and risk notifications. This is separate from `LLM_ALLOW_FALLBACK`; silent model fallback remains impossible.
- Prompt/rulebook now include validated signal templates and the exact risk formula: `account_risk_usdt = abs(entry - stop_loss) / entry * notional_exposure_usdt`. Do not multiply leverage again after computing notional.

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

Qwen smoke after fixing key:

```powershell
.\.venv\Scripts\python.exe -m src.cli init
openclaw agent --agent crypto-qwen --session-id crypto-qwen-smoke --message "Return exactly OK." --timeout 120
```

## Read Next

- `PROJECT_CONTEXT.md`: full project memory, architecture, constraints, testing/deployment info.
- `logs/SESSION_UPDATES.md`: curated recent session history. Read from the bottom upward.
- `docs/MODEL_GOVERNANCE.md`: model locking details.
