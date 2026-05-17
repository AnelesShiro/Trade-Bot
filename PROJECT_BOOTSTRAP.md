# Project Bootstrap

Read this file first in every new Codex session. `AGENTS.md` in this repo and in the parent workspace instruct Codex to do this proactively so the user should not need to ask. This is the low-token entry point; read `PROJECT_CONTEXT.md` only when deeper architecture/context is needed, then read the latest entries at the bottom of `logs/SESSION_UPDATES.md`.

## Current State

- Project: `crypto-paper-trading-arena`, BTCUSDT paper-trading competition.
- Active agents: `crypto-deepseek` and `crypto-qwen`.
- Legacy `crypto-grok` data remains in SQLite for history/audit only. Do not merge it into Qwen.
- Latest verified live cycle: `46` completed.
- DeepSeek currently works with strict model lock: `deepseek-v4-flash`.
- Qwen routing/registration works, but Qwen provider auth currently fails: `Provider qwen has auth issue`.
- Qwen model lock expected actual response model: `qwen3-max-2026-01-23`.
- Remaining blocker for Qwen: replace/repair `QWEN_API_KEY`, then run init and smoke test.

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
- `python -m src.cli init` registers OpenClaw agents with provider/model routing.
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
