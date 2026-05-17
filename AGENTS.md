# Codex Startup Instructions

This repository is stateful and has a live trading runner. At the start of every new Codex session in this repo, read context before making changes.

## Required Startup Context

1. Read `PROJECT_BOOTSTRAP.md` first. It is the low-token current-state briefing.
2. If the task needs architecture, constraints, or project conventions, read `PROJECT_CONTEXT.md`.
3. If the task depends on recent work, read only the latest relevant entries from the bottom of `logs/SESSION_UPDATES.md`.

Do this proactively. The user should not need to ask for project context.

## Operating Guardrails

- Preserve existing dashboard UI/UX unless explicitly requested.
- Do not change trading rules, strategy behavior, prompts, or rulebook unless explicitly requested.
- Do not commit `.env`, API keys, secrets, or provider tokens.
- Runtime files in `outputs/` may be dirty because the live runner writes them. Do not revert them unless explicitly requested.
- Use `.venv\Scripts\python.exe` for Python commands and tests on this machine.
- Append meaningful decisions, investigations, fixes, verification results, and deployment actions to `logs/SESSION_UPDATES.md`.

## Current High-Signal State

- Active agents: `crypto-deepseek` and `crypto-qwen`.
- Legacy `crypto-grok` data is retained for history/audit only.
- Qwen model routing, OpenClaw registration, and provider auth are fixed (Standard Global DashScope URL). See `PROJECT_BOOTSTRAP.md` if auth regresses.
- Local risk automation is enabled; see `PROJECT_CONTEXT.md` → Risk Automation.
- Model locking uses OpenClaw agent registry plus post-response actual-model verification. Do not reintroduce per-request `--model` overrides.
