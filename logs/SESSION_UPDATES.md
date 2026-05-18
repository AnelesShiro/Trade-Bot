# Session Updates

This file is the human/Codex project memory log. Read it after `PROJECT_CONTEXT.md` at the start of every future session.

Logging rules:

- Append a concise dated entry for every meaningful user request, technical decision, code change, bug investigation, deployment action, or verification result.
- Include files touched, tests/commands run, outcomes, and follow-ups.
- Do not include secrets, API keys, private tokens, or high-volume runtime output.
- Keep runtime logs in `.log` files; keep this file as curated handoff context.

Entry template:

```markdown
## YYYY-MM-DD HH:mm TZ - Short Title

- User request:
- What changed:
- Files touched:
- Verification:
- Notes / follow-ups:
```

## 2026-05-17 14:05 Asia/Bangkok - Created Project Handoff Context

- User request: Convert the old conversation log into a clean handoff package and remove the old `logs/Project_context.agent.md` file.
- What changed: Created `PROJECT_CONTEXT.md` as the single structured project memory file with architecture, constraints, completed work, known issues, deployment details, testing requirements, and reusable continuation prompts.
- Files touched:
  - `PROJECT_CONTEXT.md`
  - Deleted `logs/Project_context.agent.md`
- Verification: Read the start and end of `PROJECT_CONTEXT.md`; confirmed the old log path no longer exists.
- Notes / follow-ups: Runtime files `outputs/EVALUATION.md`, `outputs/LEDGER.csv`, and `outputs/SIGNALS.md` were already modified by the live runner and were intentionally not touched.

## 2026-05-17 14:15 Asia/Bangkok - Added Mandatory Session Update Log

- User request: From now on, every project chat/update should be recorded so other sessions can quickly understand context.
- What changed: Added this `logs/SESSION_UPDATES.md` file as the canonical curated session/update log. Updated `PROJECT_CONTEXT.md` to require reading and appending this file during future Codex sessions.
- Files touched:
  - `PROJECT_CONTEXT.md`
  - `logs/SESSION_UPDATES.md`
- Verification: Confirmed `logs/SESSION_UPDATES.md` is not ignored by `.gitignore`; confirmed `PROJECT_CONTEXT.md` references the new log and future-session protocol.
- Notes / follow-ups: Future sessions should append concise entries here after meaningful work, decisions, investigations, or verification results.

## 2026-05-17 15:58 Asia/Bangkok - Added Passive Grok API Cost Forensics

- User request: Diagnose why `crypto-grok` suddenly consumed full xAI/Grok API credit while `crypto-deepseek` cost stayed low, without changing trading behavior, prompts, rulebook, strategy, dashboard layout, or performance characteristics.
- What changed: Added passive request-level API audit logging with SQLite table `api_requests`, retry/latency metadata from OpenClaw calls, prompt/response hashes and sizes, token/cost estimates, prompt component cost breakdown, anomaly flags, and non-fatal audit error handling. Added CLI reports `audit-api-costs`, `analyze-grok-spike`, and `compare-agent-costs`. Added one new dashboard tab `API Cost Audit` using existing dashboard style only.
- Files touched:
  - `src/agents/base_agent.py`
  - `src/storage/models.py`
  - `src/storage/repository.py`
  - `src/competition/api_cost_audit.py`
  - `src/competition/runner.py`
  - `src/cli.py`
  - `src/dashboard/app.py`
  - `tests/test_base_agent.py`
  - `tests/test_api_cost_audit.py`
  - `logs/SESSION_UPDATES.md`
- Verification:
  - `.venv\Scripts\python.exe -m py_compile src/agents/base_agent.py src/storage/models.py src/storage/repository.py src/competition/api_cost_audit.py src/competition/runner.py src/cli.py src/dashboard/app.py`
  - `.venv\Scripts\python.exe -m pytest tests/test_base_agent.py tests/test_api_cost_audit.py -q` -> 6 passed
  - `.venv\Scripts\python.exe -m pytest tests/test_hot_reload.py tests/test_signal_audit.py tests/test_validator.py -q` -> 11 passed
  - `.venv\Scripts\python.exe -m pytest tests/test_runner_integration.py tests/test_base_agent.py tests/test_api_cost_audit.py -q` -> 10 passed
  - `.venv\Scripts\python.exe -m pytest -q` -> 45 passed
  - `.venv\Scripts\python.exe -m src.cli compare-agent-costs --limit 5` -> no rows yet, command works
  - `.venv\Scripts\python.exe -m src.cli analyze-grok-spike --limit 5` -> no Grok audit rows yet, command works
- Notes / follow-ups: Existing historical Grok spend cannot be reconstructed precisely unless prior prompts/responses and provider billing metadata exist. New forensic rows will be recorded from the next OpenClaw agent call onward. `reasoning_tokens`, `server_tool_calls`, and `server_tool_cost_usd` are recorded as zero unless provider/OpenClaw exposes those fields later.

## 2026-05-17 16:20 Asia/Bangkok - Diagnosed Grok $5 Credit Burn

- User request: Find why Grok burned the full $5 xAI credit overnight while DeepSeek stayed near plan.
- What changed: Diagnostic only; no trading behavior, prompt, rulebook, strategy, or dashboard changes.
- Files touched:
  - `logs/SESSION_UPDATES.md`
- Verification / evidence:
  - SQLite `responses`: `crypto-grok` local arena estimate was only 50 requests, 132,606 input tokens, 13,295 output tokens, ~$0.033 using old `grok-4-1-fast` assumptions. This does not explain $5.
  - xAI official docs say retired `grok-4-1-fast-*` slugs were redirected after May 15, 2026 12:00 PT to `grok-4.3`, billed at $1.25/1M input and $2.50/1M output, not the old $0.20/$0.50 fast-model rate.
  - OpenClaw Grok session file `~/.openclaw/agents/crypto-grok/sessions/crypto-grok.jsonl` has 247 messages, 167 assistant provider responses, and ~963k message characters. Grok had 116 assistant error responses after billing exhaustion.
  - Estimated cumulative OpenClaw conversation context sent after the redirect was ~26.64M context tokens. If charged as cached input, estimated cost is ~$5.36; if charged as full input, the estimate is much higher.
  - Before the first billing error at `2026-05-17T04:58:00Z`, post-redirect accumulated context was ~4.01M estimated input tokens plus ~12.4k response tokens. At `grok-4.3` full-input pricing this is about `$5.05`, matching the exhausted credit.
- Root cause: The arena's local cost accounting counted only the current prompt saved in SQLite, but OpenClaw used the persistent `session_id: crypto-grok`, causing accumulated conversation history/cache context to be included in provider-side billing. The May 15 xAI model retirement redirected `grok-4-1-fast` to higher-priced `grok-4.3`, turning the accumulated session context from a low-cost pattern into a ~$5 overnight burn.
- Notes / follow-ups: Fix options would require an explicit user request because they can affect agent continuity/trading behavior: rotate per-cycle Grok session IDs, clear/compact OpenClaw session history, change model slug to an intended replacement, lower retry count for provider billing errors, or cap prompt/session context.

## 2026-05-17 16:50 Asia/Bangkok - Implemented Strict Model Locking

- User request: Control model usage tightly so providers/OpenClaw cannot silently switch models again.
- What changed: Added strict model governance in `config/settings.yaml` under each agent's `llm` block with `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_ALLOW_FALLBACK: false`. OpenClaw calls now send `--model <LLM_MODEL>`, then verify the actual response model recorded by OpenClaw. A mismatch fails with `Configured model '<LLM_MODEL>' is unavailable. Automatic model switching is disabled.` Added request logging for configured/actual model, token estimate, and estimated cost. Added docs in `docs/MODEL_GOVERNANCE.md`.
- Files touched:
  - `config/settings.yaml`
  - `.env.example`
  - `src/config.py`
  - `src/agents/base_agent.py`
  - `src/competition/runner.py`
  - `src/storage/models.py`
  - `src/storage/repository.py`
  - `src/dashboard/app.py`
  - `src/utils/costs.py`
  - `config/rulebook.md`
  - `README.md`
  - `docs/MODEL_GOVERNANCE.md`
  - `tests/conftest.py`
  - `tests/test_base_agent.py`
  - `tests/test_api_cost_audit.py`
  - `tests/test_signal_audit.py`
  - `tests/test_tools_and_metrics.py`
  - `PROJECT_CONTEXT.md`
  - `logs/SESSION_UPDATES.md`
- Verification:
  - `.venv\Scripts\python.exe -m py_compile src/config.py src/agents/base_agent.py src/competition/runner.py src/storage/models.py src/storage/repository.py src/dashboard/app.py src/utils/costs.py`
  - `.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed
  - `.venv\Scripts\python.exe -m pytest -q` -> 49 passed
- Notes / follow-ups: `LLM_MODEL` is now the exact provider response model id without provider prefix, while `LLM_PROVIDER` stores the provider. If xAI redirects `grok-4-1-fast` to `grok-4.3`, the request will fail instead of being treated as a successful Grok response.

## 2026-05-17 18:05 Asia/Bangkok - Switched Active Challenger From Grok to Qwen

- User request: Replace Grok with Qwen/Gwen 3 Max so the next cycle continues under the same rules with a fresh 10,000 USDT paper account, and update DB/config/related compatibility.
- What changed: Active config now uses `crypto-qwen` with provider `qwen`, locked model `qwen/qwen3-max-2026-01-23`, and `QWEN_API_KEY`. `crypto-qwen` is a new agent id, so it starts from the standard 10,000 USDT initial equity and does not inherit legacy `crypto-grok` trades, responses, lessons, or open PnL. Rulebook, README, model governance docs, shared-learning default profile, auth sync, preflight API-key checks, workload aliasing, dashboard labels, snapshot filtering, and cost estimates were updated for Qwen.
- Compatibility decision: Existing workload DB columns still use legacy `grok_*` names. `crypto-qwen` maps into that second-agent workload slot to avoid a risky live DB migration. User-facing labels now show the active challenger/Qwen where practical.
- Safety decision: Legacy `crypto-grok` DB history remains intact. Position monitoring and cloud snapshot open-position export now filter to active configured agents, so the old Grok open position is not managed as part of the new Qwen competition.
- Dashboard decision: Local dashboard tables for prompts/tool calls/responses/signals/positions/trades/reflections/lessons are filtered to active configured agents so legacy Grok rows do not pollute the new Qwen competition view.
- Operational note: Local `.env` currently has `DEEPSEEK_API_KEY` and `XAI_API_KEY`, but no `QWEN_API_KEY`; add `QWEN_API_KEY` before starting live Qwen calls, then run `.\.venv\Scripts\python.exe -m src.cli init`.
- Files touched:
  - `config/settings.yaml`
  - `.env.example`
  - `config/rulebook.md`
  - `README.md`
  - `docs/MODEL_GOVERNANCE.md`
  - `PROJECT_CONTEXT.md`
  - `src/agents/qwen_agent.py`
  - `src/agents/shared_learning.py`
  - `src/competition/workload.py`
  - `src/competition/runner.py`
  - `src/competition/api_cost_audit.py`
  - `src/trading/position_manager.py`
  - `src/cloud/snapshot_exporter.py`
  - `src/dashboard/app.py`
  - `src/cli.py`
  - `src/operations/preflight.py`
  - `src/utils/costs.py`
  - `tests/conftest.py`
  - `tests/test_runner_integration.py`
  - `tests/test_workload.py`
  - `tests/test_api_cost_audit.py`
- Verification so far:
  - `.\.venv\Scripts\python.exe -X utf8 -c "from src.config import load_settings; ..."` -> active agents are `crypto-deepseek` and `crypto-qwen`.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_workload.py tests/test_runner_integration.py tests/test_api_cost_audit.py -q` -> 9 passed.
  - `.\.venv\Scripts\python.exe -m py_compile ...` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 49 passed.
  - SQLite upsert completed: active config agents are `crypto-deepseek` and `crypto-qwen`; DB retains legacy `crypto-grok` for history.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> exported `cloud/dashboard_snapshot.json`.
  - DB check after export: `crypto-qwen` has 0 trades and 0 signals, so it starts with fresh 10,000 USDT equity; active configured agents have no open positions. Legacy `crypto-grok` still has one historical open position (`id=3`) but it is filtered out of active position monitoring/snapshot.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> failed only on critical missing `QWEN_API_KEY`; database, market data, rulebook, prompts, dashboard import, directories, disk, and dependencies passed.
  - After dashboard active-agent filter: `.\.venv\Scripts\python.exe -m py_compile src/dashboard/app.py` -> passed; `.\.venv\Scripts\python.exe -m pytest tests/test_runner_integration.py tests/test_workload.py -q` -> 6 passed.
  - Final full regression: `.\.venv\Scripts\python.exe -m pytest -q` -> 49 passed.

## 2026-05-17 22:05 Asia/Bangkok - Clarified Runner Process Pair and Fixed OpenClaw Registry Flow

- User request: Explain why there appeared to be a "double cycle" and use the safer operational path.
- Finding: The two visible `run-live --resume` process rows are a Windows `.venv\Scripts\python.exe` parent process plus a Python base-interpreter child process. This is one live runner process tree, not two independent competition loops.
- Operational action: Stopped stale runner process tree and restarted one fresh live runner from `.venv`.
- Issue found during restart: `run-live --resume` immediately runs one cycle on process start. Cycle 45 completed after restart. It did not duplicate an existing checkpoint.
- Issue found in cycle 45:
  - DeepSeek failed because OpenClaw Gateway rejected per-request `--model` overrides.
  - Qwen failed because `crypto-qwen` existed on disk but was not registered in `openclaw agents list`.
- Fix:
  - Registered `crypto-qwen` with `openclaw agents add crypto-qwen --model qwen/qwen3-max-2026-01-23`.
  - Removed per-request `--model` override from `OpenClawAgent`; model governance now relies on OpenClaw agent registry plus post-response strict actual-model verification.
  - Updated `python -m src.cli init` to register missing OpenClaw agents from `config/settings.yaml`.
  - Set `LLM_MODEL` back to exact provider response ids: `deepseek-v4-flash` and `qwen3-max-2026-01-23`.
- Current operational state:
  - DeepSeek smoke passed with configured/actual model `deepseek-v4-flash`.
  - Qwen model routing works, but provider auth fails with `Provider qwen has auth issue`, meaning the supplied Qwen key is invalid/expired or not accepted by the provider account.
  - Cycle 46 completed: DeepSeek succeeded, Qwen failed non-fatally, checkpoint and snapshot were written.
- Verification:
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_base_agent.py tests/test_runner_integration.py tests/test_workload.py -q` -> 13 passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 49 passed.
  - Live cycle 46 checkpoint: `COMPLETED`.

## 2026-05-17 22:15 Asia/Bangkok - Optimized Project Memory For Low-Token Session Handoff

- User request: Record the latest discussion/work and update `PROJECT_CONTEXT.md` plus `logs/SESSION_UPDATES.md` so new sessions can understand project context quickly with minimal token cost.
- What changed:
  - Added `Quick Context For New Sessions` near the top of `PROJECT_CONTEXT.md`.
  - Clarified that the Windows live runner often appears as `.venv` parent + base Python child and that this is one runner process tree, not necessarily duplicate cycles.
  - Updated model-lock documentation in `PROJECT_CONTEXT.md`: OpenClaw registry carries provider/model routing; runtime calls do not use `--model`; responses are still verified against exact `LLM_MODEL`.
  - Recorded current operational truth: cycle 46 completed; DeepSeek succeeded; Qwen registration/model routing are fixed; Qwen remains blocked by provider auth/key rejection.
  - Updated future-session reading protocol: read `PROJECT_CONTEXT.md` quick context first, then only the latest relevant entries from the bottom of this file unless deeper history is needed.
- Files touched:
  - `PROJECT_CONTEXT.md`
  - `logs/SESSION_UPDATES.md`
- Verification:
  - Documentation-only change; no code tests required.
- Notes / follow-ups:
  - Do not log or commit provider API keys.
  - Next technical blocker is replacing/repairing the Qwen provider credential, then running `.\.venv\Scripts\python.exe -m src.cli init` and a Qwen smoke call.

## 2026-05-17 22:25 Asia/Bangkok - Added Ultra-Short Bootstrap Context

- User request: Ensure every new session can understand project context as quickly as possible with minimal token use.
- What changed:
  - Added `PROJECT_BOOTSTRAP.md` as the first file future sessions should read.
  - Kept `PROJECT_BOOTSTRAP.md` intentionally compact: current state, active agents, known Qwen auth blocker, live-runner process note, model governance, fast checks, and what to read next.
  - Updated `PROJECT_CONTEXT.md` continuation protocol to point new sessions to `PROJECT_BOOTSTRAP.md` before the full context file.
- Files touched:
  - `PROJECT_BOOTSTRAP.md`
  - `PROJECT_CONTEXT.md`
  - `logs/SESSION_UPDATES.md`
- Verification:
  - Documentation-only change; no code tests required.
- Notes / follow-ups:
  - Keep `PROJECT_BOOTSTRAP.md` short. Move long details to `PROJECT_CONTEXT.md` or `logs/SESSION_UPDATES.md`.

## 2026-05-17 22:35 Asia/Bangkok - Added Automatic Codex Startup Instructions

- User request: Make new sessions read project context automatically instead of requiring the user to ask.
- What changed:
  - Added repo-level `AGENTS.md` with mandatory Codex startup instructions.
  - Added parent workspace `AGENTS.md` pointing to `crypto-paper-trading-arena/PROJECT_BOOTSTRAP.md` so sessions that start from `d:\Project\OpenClaw` still know what to read first.
  - Updated `PROJECT_BOOTSTRAP.md` and `PROJECT_CONTEXT.md` to mention the automatic startup instruction flow.
- Files touched:
  - `AGENTS.md`
  - `PROJECT_BOOTSTRAP.md`
  - `PROJECT_CONTEXT.md`
  - `logs/SESSION_UPDATES.md`
  - `..\AGENTS.md` outside the repo, for workspace-level startup discovery.
- Verification:
  - Documentation/instruction change only; no code tests required.
- Notes / follow-ups:
  - The repo-level `AGENTS.md` is committed. The parent workspace `AGENTS.md` is outside this git repo and exists locally for Codex startup discovery.

## 2026-05-17 22:40 Asia/Bangkok - Verified New Qwen Standard Global API Key

- User request: Test a new Qwen3 Max API key against `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` and confirm it works.
- Finding:
  - Direct DashScope OpenAI-compatible test passed for model `qwen3-max-2026-01-23`; provider returned the exact same model and a minimal `OK` response.
  - Initial OpenClaw smoke still failed with HTTP 401 even though the key was valid directly.
  - Root cause: OpenClaw `qwen` needed to use the Standard Global DashScope endpoint. The key is a Standard Global key, not a Coding Plan endpoint credential.
- What changed:
  - Updated local `.env` with the new `QWEN_API_KEY` value. `.env` remains untracked and must not be committed.
  - Configured OpenClaw local provider config for `qwen` with base URL `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
  - Set `config/settings.yaml` Qwen `LLM_BASE_URL` to that Standard Global DashScope URL.
  - Updated `src.cli init` so it syncs configured `LLM_BASE_URL` values into OpenClaw `models.providers`, preventing future init runs from losing the Qwen endpoint override.
  - Updated `PROJECT_BOOTSTRAP.md` and `PROJECT_CONTEXT.md` to mark Qwen provider auth/base URL routing as resolved.
- Verification:
  - Direct provider request -> passed, actual model `qwen3-max-2026-01-23`.
  - `openclaw agent --agent crypto-qwen --session-id crypto-qwen-smoke-baseurl --message "Return exactly OK." --timeout 120` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli init` -> completed with locked DeepSeek/Qwen models.
  - `openclaw agent --agent crypto-qwen --session-id crypto-qwen-smoke-init-sync --message "Return exactly OK." --timeout 120` -> passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\cli.py` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_base_agent.py tests/test_runner_integration.py tests/test_workload.py -q` -> 13 passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 49 passed.
- Notes / follow-ups:
  - Do not log or commit the Qwen key.
  - The live runner has not been restarted in this task; the next live call should use the fixed OpenClaw Qwen endpoint after gateway restart/init.

## 2026-05-17 22:45 Asia/Bangkok - Competition Health Check After Qwen Fix

- User request: Check whether the competition is still OK, identify current cycle, confirm Grok is ignored, confirm DeepSeek still competes normally, host the local dashboard, and push code.
- Findings:
  - Active config agents are `crypto-deepseek` and `crypto-qwen`; legacy `crypto-grok` remains in DB history only.
  - Latest checkpoint is cycle `46` with status `COMPLETED` at `2026-05-17 15:02:39 UTC`; the next scheduled decision cycle is cycle `47`.
  - Live runner is active as one Windows process tree: `.venv\Scripts\python.exe` parent plus base Python child.
  - Local dashboard is already hosted on port `8501` and responds HTTP `200`.
  - DeepSeek health smoke passed with `OK`; DeepSeek is still competing normally.
  - Qwen health smoke passed with `OK`; the fixed Qwen endpoint/key path is ready for the next cycle.
  - Active open position: `crypto-deepseek` short `DS-SHORT-003`, entry `77979.401`, SL `78200`, TP1 `77000`, TP2 `76500`.
  - Legacy `crypto-grok` has no open position and is not part of active config.
- Verification:
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> passed all critical checks.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 49 passed.
  - `openclaw agent --agent crypto-deepseek --session-id crypto-deepseek-health-check --message "Return exactly OK." --timeout 120` -> passed.
  - `openclaw agent --agent crypto-qwen --session-id crypto-qwen-health-check --message "Return exactly OK." --timeout 120` -> passed.
- Notes / follow-ups:
  - Recent `api_requests` still show Qwen auth failure on cycle 46 because that cycle happened before the endpoint fix. Health smoke after the fix is successful.
  - `outputs/EVALUATION.md`, `outputs/LEDGER.csv`, and `outputs/SIGNALS.md` remain dirty runtime files and were intentionally not committed.

## 2026-05-18 01:20 Asia/Bangkok - New Session Project Context Briefing (Vietnamese)

- User request (Vietnamese): Read `AGENTS.md` and understand what this project does, what has been built, and what bugs/issues were fixed.
- Why this was done: New Cursor/Codex session onboarding per repo `AGENTS.md` / workspace `AGENTS.md` startup protocol; user wanted a human-readable handoff without digging through the whole repo first.
- Discussion / deliverable summary:
  - **`AGENTS.md` role**: Codex startup instructions only (read `PROJECT_BOOTSTRAP.md` first, then deeper context as needed). It is not the trading product spec.
  - **Project purpose**: `crypto-paper-trading-arena` — BTCUSDT perpetual **paper** competition between `crypto-deepseek` and `crypto-qwen` via OpenClaw; CCXT market data, rulebook validation, paper execution, SQLite + `outputs/`, Streamlit local dashboard, Git snapshot -> Render read-only cloud dashboard.
  - **Major work already in repo** (from prior sessions, summarized for user): project handoff files (`PROJECT_CONTEXT.md`, `PROJECT_BOOTSTRAP.md`, `SESSION_UPDATES.md`); Grok API cost forensics; Grok $5 credit root-cause analysis; strict model locking; Grok -> Qwen challenger migration with fresh 10k paper account; OpenClaw registry fix (no per-request `--model`); Qwen Standard Global DashScope endpoint + key verification; competition health check at cycle 46.
  - **Bugs/fixes highlighted**: silent model redirect blocked; Gateway `--model` rejection; unregistered `crypto-qwen`; Qwen 401/wrong endpoint; Windows double-process confusion (one runner tree); legacy Grok rows filtered from active competition views; snapshot contract validation.
  - **Doc drift called out**: Repo `AGENTS.md` still mentions `Provider qwen has auth issue`, but `PROJECT_BOOTSTRAP.md` and session `2026-05-17 22:40` record Qwen auth/endpoint as fixed after Standard Global key + `dashscope-intl` base URL. Prefer bootstrap/context over stale `AGENTS.md` line until `AGENTS.md` is updated.
- Files read (no code changes in this step):
  - `AGENTS.md`
  - `PROJECT_BOOTSTRAP.md`
  - `PROJECT_CONTEXT.md` (partial)
  - `logs/SESSION_UPDATES.md` (recent entries)
- Verification: Documentation-only briefing; no commands required.
- Notes / follow-ups: Optional housekeeping — sync `AGENTS.md` "Current High-Signal State" with `PROJECT_BOOTSTRAP.md` when user wants doc consistency.

## 2026-05-18 01:35 Asia/Bangkok - Restarted Local Streamlit Dashboard

- User request (Vietnamese): Re-host the local web because local was broken but Render (Git snapshot source) still worked.
- Why this was done: User could not use the full local SQLite dashboard while cloud read-only dashboard remained healthy; needed operational recovery without changing trading rules or cloud deploy.
- Discussion:
  - **Expected behavior**: Local Streamlit uses `database/arena.db` and live `outputs/` when `ARENA_DASHBOARD_MODE` is `auto` and DB exists. Render sets `RENDER` env and/or uses snapshot mode via `cloud/dashboard_snapshot.json` pushed to Git — explains why cloud could work while local failed.
  - **Hypothesis before fix**: Stale or wrong Python interpreter serving port 8501, not necessarily broken app code or DB.
- Finding:
  - Port `8501` was `LISTENING` with HTTP `200` on root, but owner was stale `C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe` (system Python), **not** `D:\Project\OpenClaw\crypto-paper-trading-arena\.venv\Scripts\python.exe`.
  - `preflight-check` reported dashboard import OK and port already in use.
  - `database/arena.db` and `cloud/dashboard_snapshot.json` both exist; local mode should use SQLite.
  - `streamlit_lightweight_charts` imports OK in `.venv`; SQLite tables (`signals`, `positions`, `trades`, `api_requests`) readable.
- What changed:
  - Stopped stale PID `18540` on port `8501`.
  - Started fresh dashboard: `.\.venv\Scripts\python.exe -m src.cli dashboard` (background Streamlit on `0.0.0.0:8501`).
- Files touched:
  - None (runtime/ops only).
- Verification:
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard non-critical note: port in use after restart.
  - `http://127.0.0.1:8501/_stcore/health` -> `200`.
  - `http://127.0.0.1:8501` -> `200`.
  - Streamlit log: `Local URL: http://localhost:8501`, `Network URL: http://192.168.1.3:8501`; no traceback in new process after startup.
- Notes / follow-ups:
  - If browser still shows old error UI, hard-refresh (`Ctrl+F5`) or new tab.
  - To restart manually later: `cd D:\Project\OpenClaw\crypto-paper-trading-arena` then `.\.venv\Scripts\python.exe -m src.cli dashboard`.
  - Do not commit dirty `outputs/*` unless explicitly requested.

## 2026-05-18 01:40 Asia/Bangkok - Recorded Full Cursor Session Handoff In Project Log

- User request (Vietnamese): Remember to update everything done, reasons, and discussion content into the project log.
- Why this was done: Per `AGENTS.md` / `PROJECT_CONTEXT.md` — curated `logs/SESSION_UPDATES.md` is the canonical handoff so future sessions reconstruct context without re-reading the whole chat.
- What changed:
  - Expanded this file with the two session entries above (context briefing + local dashboard restart) including user language, rationale, discussion points, findings, commands, and follow-ups.
- Files touched:
  - `logs/SESSION_UPDATES.md`
- Verification: Documentation-only; entries follow the file's entry template.
- Notes / follow-ups:
  - Consider updating repo `AGENTS.md` Qwen auth line to match `PROJECT_BOOTSTRAP.md` if user wants zero doc drift.
  - Live runner and `outputs/` were not modified in this Cursor session.

## 2026-05-18 - Professional Trade Management Features (Risk Automation)

- User request: Add institutional-grade local trade management (conditional orders, trailing stop, break-even, time exit, cooldowns, API failover) without redesigning dashboard UI, without changing existing signal behavior, without extra LLM tokens, backward compatible, fail-safe.
- Design:
  - New local `RiskAutomationEngine` runs on existing market snapshots/indicators and position monitor ticks; no additional model calls.
  - Features are opt-in per signal via `PLACE_TRIGGER`, `trigger_order`, and `position_risk` fields, or via config defaults (`apply_by_default: false` preserves legacy behavior).
  - Cooldown skips the LLM round entirely when active (saves tokens).
  - API failover is separate from `LLM_ALLOW_FALLBACK`; explicit logged route changes with optional per-agent `api_failover` chains (disabled by default on active agents).
- What changed:
  - Added `src/trading/risk_automation/` (triggers, position rules, cooldowns, engine).
  - Added `src/agents/api_failover.py` and runner integration with one retry on failover.
  - Added SQLite tables: `pending_orders`, `position_risk_state`, `cooldown_state`, `api_failover_events`, `agent_failover_state` via `create_schema`.
  - Extended `AgentSignal` with `PLACE_TRIGGER`, `trigger_order`, `position_risk`; extended `RuleEngine` validation for triggers.
  - Wired runner + position monitor to evaluate automation before SL/TP checks.
  - Added `risk_automation` config block in `config/settings.yaml`.
  - Dashboard: additive tabs `Pending Orders`, `Risk Automation`, `API Failover Events`; overview metrics for pending orders, cooldowns, fallback models.
  - Snapshot export: `risk_automation` section in `dashboard_snapshot.json`.
  - CLI: `list-pending-orders`, `cancel-pending-order`, `list-cooldowns`, `clear-cooldown`, `show-failover-status`.
- Files touched (high level):
  - `src/trading/risk_automation/*`, `src/agents/api_failover.py`, `src/storage/models.py`, `src/storage/risk_repository.py`, `src/storage/repository.py`, `src/competition/runner.py`, `src/schemas.py`, `src/config.py`, `src/validation/rule_engine.py`, `src/cloud/snapshot_exporter.py`, `src/cli.py`, `src/dashboard/app.py`, `src/dashboard/tabs/*`, `config/settings.yaml`, `tests/test_risk_automation.py`, `logs/SESSION_UPDATES.md`
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py -q` -> 7 passed
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 56 passed
- Notes / follow-ups:
  - Enable per-agent `api_failover.enabled: true` and configure `fallback_chain` when ready; defaults keep existing model-lock behavior.
  - Agents must include `trigger_order` / `position_risk` in JSON to use new features; otherwise behavior is unchanged.
  - After deploy, run `python -m src.cli init` if OpenClaw routes change via failover.

## 2026-05-18 - Post-Feature Workflow (Validate, Docs, Commit, Deploy)

- User request: After feature completion, run validate/tests/build, update PROJECT_CONTEXT and related docs/prompts/rules, commit, push, deploy, final report.
- Validation:
  - `pytest -q` -> 56 passed
  - `py_compile` on risk automation / runner / failover modules -> pass
  - `validate-update --no-smoke` -> pass
  - `preflight-check` -> all critical checks pass
- Documentation:
  - Updated `PROJECT_CONTEXT.md`, `PROJECT_BOOTSTRAP.md`, `AGENTS.md`, `config/rulebook.md`, `prompts/system_prompt.md`, `docs/MODEL_GOVERNANCE.md`
  - Added `DECISIONS.md`, `TODO.md`
- Git/deploy: commit and push on `main` (see final report commit hash); Render auto-deploy via `render.yaml`.

## 2026-05-18 - Refreshed Startup Context From AGENTS.md

- User request (Vietnamese): Read `AGENTS.md` and update the most recent project changes.
- What was checked:
  - Read `AGENTS.md`, `PROJECT_BOOTSTRAP.md`, latest `logs/SESSION_UPDATES.md`, and the quick-context section of `PROJECT_CONTEXT.md`.
  - Checked current git state and confirmed the committed risk automation work is already on `main`; working tree only has runtime `outputs/*` changes.
  - Queried SQLite/checkpoints for current competition state.
- Current state captured:
  - Active agents: `crypto-deepseek` and `crypto-qwen`.
  - Legacy `crypto-grok` remains history/audit only.
  - Latest checkpoint: cycle `50`, status `COMPLETED`, created at `2026-05-17 19:14:31 UTC`.
  - Recent `api_requests`: both DeepSeek and Qwen succeeded in cycles `48`, `49`, and `50`.
  - Active open positions: none at latest check.
  - Live runner is still one Windows process tree (`.venv` Python parent plus base Python child).
  - Risk automation infrastructure is enabled globally, but per-agent API failover remains disabled (`agents.*.api_failover.enabled: false`), so it is not silent model fallback.
- Files updated:
  - `AGENTS.md`
  - `PROJECT_BOOTSTRAP.md`
  - `PROJECT_CONTEXT.md`
  - `logs/SESSION_UPDATES.md`
- Notes:
  - Do not commit runtime `outputs/EVALUATION.md`, `outputs/LEDGER.csv`, or `outputs/SIGNALS.md` unless explicitly requested.

## 2026-05-18 - Risk Automation Audit And Hardening

- User request (Vietnamese): Check whether the `Professional Trade Management Features (Risk Automation)` update was developed perfectly and whether any bugs remain.
- Findings:
  - Core feature exists and tests pass, but two real hardening issues were found.
  - `PLACE_TRIGGER` stored nested `trigger_order.execution_signal` without validating that nested execution signal at placement time. A malformed pending order could be accepted and only fail later when the trigger fired.
  - API failover route switching would still call/audit with the primary agent model settings after failover, which could collide with strict model-lock verification and misreport model/cost audit data if per-agent failover is enabled later.
  - The later log note about `prompts/risk_automation_guide.md`, `src/competition/prompt_contracts.py`, and `tests/test_prompt_contracts.py` does not match the current repo or git history; those files are not present. The committed implementation uses the existing system prompt/rulebook/schema hint path.
- What changed:
  - `RiskAutomationEngine.handle_place_trigger()` now validates and normalizes nested `execution_signal` as an `AgentSignal` before creating a pending order.
  - Invalid nested trigger execution actions (`NONE` / nested `PLACE_TRIGGER`) are rejected immediately.
  - `ApiFailoverManager` can now build effective fallback `AgentSettings` with the fallback provider/model/base URL/API-key env while keeping `LLM_ALLOW_FALLBACK=false`.
  - Runner API auditing now records/costs the configured model from the actual `AgentRunResult`, so explicit failover routes do not get logged as the primary model.
  - OpenClaw route switching now uses `openclaw models --agent <id> set <provider/model>` first, with the old `agents add` call only as fallback; custom failover base URLs are synced into OpenClaw provider config.
  - Added regression tests for invalid nested `PLACE_TRIGGER` execution signals and fallback route model-lock settings.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py -q` -> 9 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\trading\risk_automation\engine.py src\agents\api_failover.py src\competition\runner.py` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 58 passed.
- Notes:
  - Per-agent API failover remains disabled in `config/settings.yaml`; this patch hardens it for future enablement without enabling silent fallback.
  - Runtime `outputs/*` files remain dirty and are intentionally not part of this code change.

## 2026-05-18 - Completed Risk Automation Coverage

- User request (Vietnamese): Update the missing parts so bots can use all Professional Trade Management / Risk Automation features fully and reliably.
- What changed:
  - Enabled explicit per-agent API failover in `config/settings.yaml`: `crypto-deepseek` can fail over to Qwen, and `crypto-qwen` can fail over to DeepSeek.
  - Kept strict model locking intact: `LLM_ALLOW_FALLBACK=false`; failover uses logged active routes and verifies the actual response model against the active route's exact model.
  - `python -m src.cli init` now syncs OpenClaw auth and base URLs for both primary routes and fallback chains, so an agent can authenticate to its configured fallback provider.
  - Runner now applies the active failover route before each agent request and uses fallback route settings for the retry/audit path.
  - Failover primary retest now probes the real primary route, restores the fallback route afterward when needed, and records failed retest timestamps to avoid rapid repeated probes.
  - Failover events now preserve the original primary provider/model even if a fallback route later fails over again.
  - Added weekly drawdown cooldown support (`weekly_drawdown_pct`, `pause_hours_weekly`).
  - Added local `risk_notifications` table and notifications for cooldown start/end plus API failover/restore events.
  - Added CLI `list-risk-notifications`.
  - Dashboard and snapshot now expose risk notifications; Overview shows latest notifications.
  - Added missing SHORT step-based trailing stop support.
  - Updated `PROJECT_BOOTSTRAP.md`, `PROJECT_CONTEXT.md`, `TODO.md`, `AGENTS.md`, and `docs/MODEL_GOVERNANCE.md` so future sessions read the correct current state.
- Verification so far:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py -q` -> 12 passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 61 passed.
  - `.\.venv\Scripts\python.exe -m py_compile ...` on modified modules -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
  - `.\.venv\Scripts\python.exe -m src.cli init` -> completed; active locked models printed as DeepSeek `deepseek-v4-flash` and Qwen `qwen3-max-2026-01-23`, both `fallback_allowed=False`.
  - `.\.venv\Scripts\python.exe -m src.cli show-failover-status` -> both active agents on primary routes, no active fallback.
  - `.\.venv\Scripts\python.exe -m src.cli list-risk-notifications --limit 5` -> no current notifications.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
- Notes:
  - Trading behavior for normal signals remains unchanged. New features are local/additive and only activate through config or optional signal fields.
  - Runtime `outputs/*` and generated snapshot files are live-generated and should not be reverted or committed unless explicitly requested.

## 2026-05-18 - Qwen No-Trade Health Check

- User request (Vietnamese): Check why Qwen has not entered trades for a long time; determine whether Qwen is healthy or producing invalid signals.
- Findings:
  - Qwen is healthy at the API/model layer. Latest checkpoint is cycle `60` completed; Qwen API requests succeeded in cycles `53` through `60`.
  - Qwen is currently on primary route `qwen/qwen3-max-2026-01-23`; no active fallback, no cooldown, and no risk notifications.
  - Latest Qwen signals cycles `56`-`60` are accepted `NO_TRADE` / `WATCHLIST`, not technical failures.
  - Qwen has `0` accepted `PAPER_TRADE OPEN` signals and `0` trades in DB so far.
  - Qwen attempted `OPEN` in cycles `51`, `54`, and `55`, but those signals were rejected by validation.
- Root cause of rejected Qwen entries:
  - Rejection code: `RISK_LIMIT_EXCEEDED`.
  - Main reason: `declared account risk differs from calculated risk by more than 25%`.
  - Examples:
    - Cycle `55`: entry `77000`, stop `76500`, notional `5000` -> calculated risk about `32.47 USDT`, but Qwen declared `135.14 USDT`.
    - Cycle `54`: entry `77800`, stop `77500`, notional `5000` -> calculated risk about `19.28 USDT`, but Qwen declared `193.55 USDT`.
    - Cycle `51`: short entry `78450`, stop `78650`, notional `5000` -> calculated risk about `12.75 USDT`, but Qwen declared `254.76 USDT`.
  - One rejected cycle also had `risk/reward to TP1 below 1:1.5`.
- Interpretation:
  - Qwen is not blocked and is not failing auth/model verification now.
  - Qwen is conservative in the recent downtrend and often chooses accepted `NO_TRADE`.
  - When Qwen does try to trade, it has been miscalculating `account_risk_usdt` versus the validator formula: `abs(entry - stop_loss) / entry * notional_exposure_usdt`.
- Commands/evidence:
  - `python -m src.cli show-failover-status` -> Qwen primary route, no fallback.
  - `python -m src.cli list-cooldowns` -> `[]`.
  - `python -m src.cli list-risk-notifications --limit 20` -> `[]`.
  - SQLite `api_requests` and `signals` queries confirmed the cycle and rejection details above.

## 2026-05-18 - Bot Rule/Feature Prompt Contract Update

- User request (Vietnamese): Fix Qwen's risk misunderstanding, check whether both bots understand all rules/features, and add examples/templates if needed.
- Diagnosis:
  - Project validator formula is correct for USDT linear perps.
  - Qwen was misreporting `account_risk_usdt`, likely treating it as risk budget or multiplying leverage again after notional.
  - Existing prompt/rulebook stated account risk was required but did not spell out the exact validator formula or provide complete feature examples.
  - Runner schema hint omitted `PLACE_TRIGGER` from the action enum even though schema/engine support it.
- What changed:
  - `prompts/system_prompt.md` now states exact risk math:
    - `notional_exposure_usdt = margin_used_usdt * leverage`
    - `account_risk_usdt = abs(entry - stop_loss) / entry * notional_exposure_usdt`
    - Do not multiply by leverage again after notional exposure.
    - Percent fields are decimal fractions.
  - `config/rulebook.md` now includes validated JSON templates for:
    - normal `OPEN` with correct risk math,
    - `OPEN` with `position_risk` (`trailing_stop`, `break_even`, `time_exit`),
    - `PLACE_TRIGGER` with nested compliant `execution_signal`,
    - `POSITION_UPDATE` / `HOLD`.
  - `src/competition/runner.py` schema hints now include `PLACE_TRIGGER`, risk formula, account risk percent guidance, and optional local automation summary.
  - Added `tests/test_prompt_contracts.py` to lock the prompt/rulebook formula and ensure the documented `OPEN` template passes validator.
  - Updated `PROJECT_BOOTSTRAP.md` and `PROJECT_CONTEXT.md` with the new bot-facing contract.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_prompt_contracts.py tests/test_validator.py tests/test_risk_automation.py -q` -> 19 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 64 passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed.
  - `.\.venv\Scripts\python.exe -m src.cli safe-restart --no-wait` -> queued safe restart `522e28cfcb97426892f216dd66c164b9` so the live runner picks up prompt/rulebook changes after the current cycle checkpoint.
- Notes:
  - No validator/trading-engine behavior changed; this is prompt/rulebook/schema-hint guidance plus regression tests.
  - Existing live runner keeps prompt/rulebook text in memory until restart; safe restart was queued instead of interrupting the active cycle.

## 2026-05-18 - Runner State Fix For False Overdue

- User request (Vietnamese): Dashboard/DB shows `OVERDUE` even though cycles complete, and it also shows overdue while bots are being called. Update DB/UI so users know the bot is processing; reserve overdue for real errors.
- Root cause:
  - Dashboard/snapshot computed `next_cycle_at = latest_checkpoint.created_at + poll_interval`.
  - During an active cycle, the new checkpoint is not written until the end, so the previous `next_cycle_at` can be in the past while DeepSeek/Qwen is still processing.
  - The UI had no persisted "current runner phase" source, so it rendered a false `OVERDUE`.
- What changed:
  - Added SQLite table `runner_state` with status, phase, cycle number, timestamps, next cycle time, message, and payload.
  - Runner now updates `runner_state` at cycle phase transitions:
    - `FETCHING_DATA`
    - `MANAGING_POSITIONS`
    - `CALLING_DEEPSEEK`
    - `CALLING_QWEN`
    - `POST_PROCESSING`
    - `WRITING_OUTPUTS`
    - `CHECKPOINTING`
    - `WAITING`
    - `ERROR`
  - Runner state updates are best-effort and non-fatal; trading continues if DB state write fails.
  - Local dashboard now reads `runner_state` from SQLite and prefers it over stale snapshot runner data.
  - Cloud snapshot runner payload now uses active `runner_state` and sets `next_cycle_at: null` while a cycle is processing.
  - Cycle status component now shows `IN PROGRESS` for active phases instead of `OVERDUE`.
- Live repair:
  - Before restart, no `run-live` process was detected. Latest checkpoint was cycle `61` completed at `2026-05-18 06:46:55 UTC`; current time was already `2026-05-18 08:09 UTC`, so the runner had actually stopped after the earlier no-wait safe restart.
  - Ran `python -m src.cli init` to create the new `runner_state` table and sync OpenClaw config.
  - Restarted live runner detached with `python -m src.cli run-live --resume`.
  - Verified Windows process tree is running.
  - Verified DB row: cycle `62`, status `RUNNING`, phase `CALLING_DEEPSEEK`, `next_cycle_at` null, message `Calling crypto-deepseek and validating its signal`.
  - Exported snapshot and verified runner payload shows active `CALLING_DEEPSEEK` with `current_cycle_started_at`, not stale overdue.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_hot_reload.py tests/test_prompt_contracts.py -q` -> 10 passed.
  - `.\.venv\Scripts\python.exe -m py_compile ...` on modified modules -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 66 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed.
- Notes:
  - `OVERDUE` should now mean no active processing phase is present and the scheduled next cycle time is truly past.
  - Runtime `outputs/*` and `cloud/dashboard_snapshot.json` may remain dirty from live/export operations.

## 2026-05-18 - Safe Restart No-Wait Root Cause

- User request (Vietnamese): Ask why `run-live` stopped even though it was expected to run continuously, and whether there was a problem.
- Finding:
  - It was not a trading crash.
  - A previous command queued `python -m src.cli safe-restart --no-wait`, creating CODE_RESTART update `522e28cfcb97426892f216dd66c164b9`.
  - At cycle boundary after checkpoint `61`, the update manager applied that restart request and the live runner correctly exited with log: `graceful restart requested; exiting live loop after completed cycle`.
  - Because the command used `--no-wait`, no foreground CLI process was waiting to start `run-live --resume`; this left the runner stopped until it was manually restarted.
- Evidence:
  - `state/update_queue.json`: update `522e28cfcb97426892f216dd66c164b9` status `APPLIED`, type `CODE_RESTART`, processed at `2026-05-18T06:46:58Z`.
  - `state/restart_requested.json` was still present until cleared.
  - `logs/arena.log`: `graceful restart requested; exiting live loop after completed cycle`.
  - Recent health checks show checkpoint and snapshot succeeded before the exit.
- Live state after repair:
  - Live runner is running again as one Windows process tree.
  - Latest verified checkpoint at the time: cycle `62` completed.
  - `runner_state` is `WAITING`, next cycle at `2026-05-18 09:11:43 UTC`.
- Hardening:
  - Updated `safe-restart --no-wait` so it now launches a detached `watch-safe-restart` helper.
  - The watcher waits for the existing update id to become `APPLIED`, waits for old runner PIDs to exit, starts `run-live --resume`, clears `restart_requested.json`, and records successful restart.
  - Added CLI command `watch-safe-restart <update_id>` for existing queued safe restarts.
  - Cleared the stale restart request and recorded `MANUAL_RESUME_AFTER_NO_WAIT_RESTART` for update `522e28cfcb97426892f216dd66c164b9`.
- Verification:
  - `.\.venv\Scripts\python.exe -m py_compile src\cli.py` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli --help` -> passed and shows `watch-safe-restart`.

## 2026-05-18 - Risk Automation Usage Check

- User request (Vietnamese): Ask whether all Professional Trade Management features are actually available and why the bots have not used them.
- Findings:
  - Implementation exists for all six requested features: conditional orders, trailing stop, break-even stop, time-based exit, cooldown rules, and explicit API failover.
  - Code/config/tests/docs contain support for `PLACE_TRIGGER`, `trigger_order`, `position_risk`, `trailing_stop`, `break_even`, `time_exit`, cooldowns, API failover, dashboard tabs, snapshot export, and CLI commands.
  - Targeted tests covering the feature area passed: `pytest tests/test_risk_automation.py tests/test_hot_reload.py tests/test_prompt_contracts.py -q` -> 22 passed.
  - Live DB usage check:
    - `pending_orders`: 0 rows.
    - `position_risk_state`: 0 rows.
    - `cooldown_state`: 0 rows.
    - `api_failover_events`: 0 rows.
    - `agent_failover_state`: 0 rows.
    - `risk_notifications`: 0 rows.
    - No historical `signals` rows have `action=PLACE_TRIGGER`, `trigger_order`, or `position_risk`.
  - Recent accepted/rejected `OPEN` signals also have no `position_risk` or `trigger_order`.
- Interpretation:
  - The features are implemented and available, but are optional/additive by design.
  - Config defaults keep `trailing_stop.apply_by_default`, `break_even.apply_by_default`, and `time_exit.apply_by_default` false to preserve existing trading behavior.
  - Bots will only use conditional orders or trade-management automation if they choose to include the optional JSON fields in their signal.
  - Cooldowns only appear after configured poor-performance triggers fire.
  - API failover only appears after billing/auth/rate-limit/timeout/provider outage conditions fire.
- Practical next step if the owner wants visible usage:
  - Either keep current conservative behavior and wait for bots to choose the features naturally, or explicitly request a config/prompt change that makes safe defaults apply to every accepted `OPEN` without extra LLM calls.

## 2026-05-18 - Agents Prompted To Actively Use Advanced Trade Management

- User request (Vietnamese/English): Update all agent prompts, prompt-building logic, rulebook wording, reflection guidance, and shared-learning instructions so DeepSeek, Qwen, and future models actively consider the implemented advanced trade-management features.
- Constraints honored:
  - No backend trading logic changes.
  - No dashboard UI/UX changes.
  - No database schema changes.
  - No config default changes; existing trading behavior remains unchanged unless an agent includes optional fields.
  - Added system-prompt guidance is compact: 73 words in the new active trade-management block.
- What changed:
  - `prompts/system_prompt.md` now says advanced trade management must be considered on every setup.
  - Agents are explicitly guided to prefer `PLACE_TRIGGER` when entry requires pullback, breakout, or RSI confirmation.
  - Agents are guided to usually include break-even and time-exit settings on appropriate `OPEN` trades, and to use trailing stops selectively for momentum/trend trades.
  - Prompt builder schema hint changed from passive `optional_local_automation` to concise `advanced_trade_management` with `consider_every_cycle: true`.
  - `config/rulebook.md` now has a compact priority ladder: `OPEN` now, `PLACE_TRIGGER` for future condition, trailing stop for trends, break-even around +1R/TP1, and time exit for known thesis windows.
  - `prompts/reflection_prompt.md`, `src/agents/reflection.py`, and `src/agents/shared_learning.py` now encourage lessons about conditional entries, trailing stops, break-even protection, and stale-trade exits when evidence supports them.
  - `tests/test_prompt_contracts.py` now locks the active advanced trade-management guidance into regression tests.
  - `PROJECT_BOOTSTRAP.md`, `PROJECT_CONTEXT.md`, and `TODO.md` were updated so future sessions can find the new prompt contract quickly.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_prompt_contracts.py tests/test_memory_repository_runner.py tests/test_shared_learning.py -q` -> 8 passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 66 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\competition\runner.py src\agents\reflection.py src\agents\shared_learning.py` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Live runner must reload prompt/rulebook text before agents see these changes; queue a safe restart at cycle boundary instead of interrupting the current cycle.
  - Runtime `outputs/*` files remain dirty and should not be committed.

## 2026-05-18 - Mandatory Break-Even Stop Default

- User request (Vietnamese): Make bots always use break-even stop, meaning move stop loss to breakeven when a position is profitably strong enough, for example +1R, even before take profit is hit.
- What changed:
  - `config/settings.yaml` now has `risk_automation.break_even.apply_by_default: true`.
  - Break-even default trigger changed from `tp1` to `r_multiple` with `r_multiple: 1.0`, so the local engine can move SL to breakeven after about +1R without waiting for TP1.
  - `src/config.py` defaults were aligned so new/test settings also default to mandatory +1R break-even protection.
  - `_resolve_position_risk()` now merges default automation with any agent-provided `position_risk`; mandatory break-even is re-applied after the merge so an agent cannot accidentally omit or disable it.
  - Prompt/rulebook/schema-hint wording now says break-even is enforced locally around +1R on every open trade.
  - `PROJECT_BOOTSTRAP.md` and `PROJECT_CONTEXT.md` were updated so future sessions know break-even is now a backend default, not just a prompt suggestion.
  - Added regression tests proving default break-even is attached to `OPEN` signals and cannot be disabled by an agent payload.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py tests/test_prompt_contracts.py -q` -> 17 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\config.py src\trading\risk_automation\engine.py src\competition\runner.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 68 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - This changes future accepted `OPEN` behavior by adding local break-even protection automatically.
  - Trailing stop and time exit remain opt-in unless separately configured.
  - Existing open positions only receive this default if they already have or later get a `position_risk_state`; the default is attached when new positions are opened.

## 2026-05-18 - Render Dashboard Risk Automation Tabs

- User request (Vietnamese): Local web already has tabs for the new risk-management features, but Render web does not; fix Render.
- Root cause:
  - Local dashboard reads SQLite and already renders DB-backed tabs: Pending Orders, Risk Automation, API Failover Events.
  - Render/cloud dashboard runs in snapshot mode from `cloud/dashboard_snapshot.json`; snapshot export already contained `risk_automation`, but `render_cloud_snapshot_dashboard()` did not create the three risk automation tabs.
- What changed:
  - Cloud snapshot dashboard now includes tabs:
    - Pending Orders
    - Risk Automation
    - API Failover Events
  - Cloud Overview now shows risk automation metric cards from the snapshot: pending orders, active cooldowns, active fallback models.
  - Added snapshot-mode render helpers that read `risk_automation.pending_orders`, `position_risk`, `cooldowns`, `notifications`, `active_models`, and `failover_events`.
  - Snapshot contract now requires top-level `risk_automation` and validates required subkeys so Render cannot silently lose these sections again.
  - `TODO.md`, `PROJECT_BOOTSTRAP.md`, and `PROJECT_CONTEXT.md` updated so future sessions know cloud dashboard mirrors the local risk tabs.
  - Exported a fresh `cloud/dashboard_snapshot.json`.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_hot_reload.py -q` -> 8 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\dashboard\app.py src\cloud\snapshot_exporter.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 69 passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` files remain dirty and should not be committed.
  - `cloud/dashboard_snapshot.json` was regenerated because Render reads it directly.

## 2026-05-18 - Dashboard UI Contract To Prevent Local/Render Drift

- User request (Vietnamese): Add a mechanism to ensure local DB dashboard UI/UX and Render dashboard UI/UX always stay synced, avoiding future mismatch.
- What changed:
  - Added `src/dashboard/contract.py` as the single source of truth for dashboard tab labels.
  - Both local SQLite dashboard mode and Render/cloud snapshot dashboard mode now call `st.tabs(DASHBOARD_TAB_LABELS)` instead of maintaining separate hardcoded tab lists.
  - Centralized required risk automation snapshot keys in the same contract module.
  - Snapshot exporter validates `risk_automation` against the shared contract keys.
  - Added `tests/test_dashboard_contract.py` to fail if the app stops using the shared tab contract or if required risk tabs are removed.
  - Updated `tests/test_hot_reload.py` to use shared snapshot contract constants.
  - Updated `PROJECT_BOOTSTRAP.md` and `PROJECT_CONTEXT.md` with the dashboard sync rule for future sessions.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_contract.py tests/test_hot_reload.py -q` -> 10 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\dashboard\contract.py src\dashboard\app.py src\cloud\snapshot_exporter.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 71 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - This does not redesign the dashboard; it only removes duplicate local/cloud tab definitions and adds regression protection.

## 2026-05-18 - Lessons To Follow / Lessons To Avoid Dashboard Tabs

- User request (English): Add two read-only dashboard tabs, `Lessons to Follow` and `Lessons to Avoid`, to visualize important validated lessons from all agents without changing trading logic or agent behavior.
- What changed:
  - Added `src/analytics/lesson_analytics.py` to aggregate existing `lessons`, `shared_lessons`, `reflections`, and `trades` into ranked lesson analytics.
  - Classification separates positive/follow lessons from negative/avoid lessons using existing shared-lesson metadata plus lightweight text/outcome heuristics.
  - Ranking combines impact, confidence, evidence count, and recency.
  - Added local/cloud reusable tab renderers:
    - `src/dashboard/tabs/lessons_to_follow.py`
    - `src/dashboard/tabs/lessons_to_avoid.py`
  - Each tab includes KPI cards, ranked lesson cards, trend charts, agent contribution breakdown, filters, and evidence expanders.
  - Dashboard tab contract now includes `Lessons to Follow` and `Lessons to Avoid` at the end of the tab list.
  - Snapshot export now includes `lesson_analytics` with `follow`, `avoid`, `follow_summary`, and `avoid_summary`, so Render shows the same read-only tabs.
  - Snapshot contract validates the new `lesson_analytics` payload.
  - Added tests:
    - `tests/test_lesson_analytics.py`
    - updated `tests/test_dashboard_contract.py`
    - updated `tests/test_hot_reload.py`
- Safety:
  - No trading logic changed.
  - No agent prompts/behavior changed.
  - No new model calls.
  - If lesson analytics fail to load locally, dashboard shows a warning and continues.
  - Snapshot export falls back to empty lesson lists if lesson analytics fail.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_lesson_analytics.py tests/test_dashboard_contract.py tests/test_hot_reload.py -q` -> 13 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\analytics\lesson_analytics.py src\dashboard\tabs\lessons_to_follow.py src\dashboard\tabs\lessons_to_avoid.py src\dashboard\app.py src\cloud\snapshot_exporter.py src\dashboard\contract.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 74 passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed; current snapshot has 8 follow lessons and 3 avoid lessons.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.

## 2026-05-18 - Render Lesson Tabs Duplicate Widget ID Fix

- User report: Render dashboard crashed with `streamlit.errors.StreamlitDuplicateElementId` in `Lessons to Avoid`; both lesson tabs created a `multiselect("Agent")` with identical auto-generated widget IDs.
- Root cause:
  - `Lessons to Follow` and `Lessons to Avoid` reused the same shared `_filters()` helper without passing explicit widget keys.
  - Streamlit generated the same internal ID for matching filter widgets across tabs.
- What changed:
  - Added `key_prefix` to lesson tab rendering.
  - `Lessons to Follow` uses `lessons_follow_*` widget keys.
  - `Lessons to Avoid` uses `lessons_avoid_*` widget keys.
  - Added regression test to ensure lesson filter widgets keep unique keys.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_contract.py tests/test_lesson_analytics.py -q` -> 5 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\dashboard\tabs\lessons_to_follow.py src\dashboard\tabs\lessons_to_avoid.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 75 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.

## 2026-05-18 - Pending Orders Intent Visibility

- User request: Improve the existing Pending Orders dashboard so each pending order clearly shows what action will execute when triggered.
- Constraints honored:
  - No trading logic changes.
  - No database schema changes.
  - No new model calls.
  - Existing dashboard theme/style preserved.
- What changed:
  - Added `src/trading/risk_automation/pending_order_view.py` to parse existing `trigger_json` and `execution_signal_json`.
  - Local Pending Orders tab now fetches `trigger_json` and `execution_signal_json` in the same table query and derives:
    - `intent`
    - `action`
    - `direction`
    - `entry_price`
    - `stop_loss`
    - `take_profit_1`
    - `leverage`
    - `trigger_summary`
    - `thesis`
  - Added summary cards: Pending OPEN LONG, Pending OPEN SHORT, Pending CLOSE/REDUCE, Expiring soon.
  - Added intent badge and per-order detail expanders with full trigger conditions, raw normalized signal JSON, and validation details.
  - Render/cloud Pending Orders tab now uses the same enriched snapshot fields.
  - Snapshot export now includes enriched pending order fields in `risk_automation.pending_orders`.
  - Added regression tests for trigger summary formatting, pending order intent extraction, and snapshot pending order fields.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py tests/test_hot_reload.py -q` -> 25 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\trading\risk_automation\pending_order_view.py src\dashboard\tabs\pending_orders.py src\dashboard\app.py src\cloud\snapshot_exporter.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 77 passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed; snapshot pending orders include `action`, `direction`, `entry_price`, `stop_loss`, `take_profit_1`, `leverage`, `trigger_summary`, and `thesis`.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.
  - `cloud/dashboard_snapshot.json` was regenerated for Render.

## 2026-05-18 - Risk Automation Lazy Import Hotfix

- User report: Dashboard failed with `ImportError: cannot import name 'RiskAutomationSettings' from 'src.config'` while importing `src.dashboard.tabs.pending_orders`.
- Root cause:
  - Importing `src.trading.risk_automation.pending_order_view` first executes package `src.trading.risk_automation.__init__`.
  - `__init__.py` eagerly imported `RiskAutomationEngine`, which pulled in `engine.py` and `src.config` even when the dashboard only needed the read-only pending-order view helper.
  - This created an unnecessary import-chain risk for dashboard/Render startup.
- What changed:
  - `src/trading/risk_automation/__init__.py` now lazy-loads `RiskAutomationEngine` via `__getattr__`.
  - Dashboard helper imports no longer eagerly import the risk automation engine/config path.
  - Existing runner import `from src.trading.risk_automation import RiskAutomationEngine` still works.
- Verification:
  - `from src.dashboard.tabs.pending_orders import render_pending_orders_tab` -> passed.
  - `from src.trading.risk_automation.pending_order_view import pending_order_view` -> passed.
  - `from src.trading.risk_automation import RiskAutomationEngine` -> passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\trading\risk_automation\__init__.py src\dashboard\tabs\pending_orders.py src\trading\risk_automation\pending_order_view.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py tests/test_hot_reload.py tests/test_dashboard_contract.py -q` -> 28 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.

## 2026-05-18 - Active Cycle Status Must Show TRADING, Not OVERDUE

- User report: `Next Cycle In` showed `OVERDUE`; if a cycle is truly overdue, fix immediately, but if the runner is calling a bot it must show `TRADING`.
- Investigation:
  - Reconfirmed the existing project rule: two visible `run-live --resume` process rows can be a normal Windows parent-child pair (`.venv` Python parent plus base Python child), which is one runner, not two.
  - Duplicate runner risk only exists when there are multiple unrelated parent process trees, not when the rows have a parent-child relationship.
  - Verified the current live runner is one valid parent-child tree: parent `4228`, child `41012`.
  - SQLite `runner_state` showed the runner was actively processing cycle `67` in `CALLING_QWEN`, so this was not a true overdue state during the bot-call phase.
  - Cycle `67` later completed successfully and `runner_state` moved to `WAITING` with `next_cycle_at=2026-05-18 13:31:07.708520`.
- What changed:
  - `src/dashboard/components/cycle_status_bar.py` now returns `TRADING` for active phases such as `CALLING_DEEPSEEK`, `CALLING_QWEN`, validation, execution, and snapshot export.
  - `OVERDUE` remains reserved for cases where there is no active processing phase and the next scheduled cycle is genuinely late.
  - `tests/test_hot_reload.py` now locks this behavior with a regression test.
  - `src/trading/risk_automation/position_rules.py` now tolerates double-encoded `position_risk` JSON so local automation parsing warnings do not pollute live-cycle diagnostics.
  - `PROJECT_BOOTSTRAP.md` updated with the new `TRADING` display contract and latest verified cycle `67`.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_hot_reload.py tests/test_risk_automation.py -q` -> 25 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\dashboard\components\cycle_status_bar.py src\trading\risk_automation\position_rules.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 77 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.
  - A normal Windows live runner appears as one parent `.venv` Python process plus one child base Python process; multiple unrelated parent trees should be treated as duplicate runners.

## 2026-05-18 - Trade History Execution Timestamp Accuracy

- User request: Fix Trade History so timestamps answer "when did this order actually execute?", especially for `PLACE_TRIGGER` fills and automated actions.
- Constraints honored:
  - No trading logic changes.
  - No PnL calculation changes.
  - No competition behavior changes.
  - Dashboard UI/UX style preserved.
  - Historical records remain backward compatible.
- What changed:
  - Added additive nullable columns on `trades`: `decision_timestamp` and `execution_timestamp`.
  - New trades set `execution_timestamp` at the moment the paper execution engine finalizes the fill.
  - Immediate orders set decision time from `AgentSignal.timestamp` and execution time from the local fill time.
  - Triggered pending orders now use one shared fill timestamp for both `pending_orders.triggered_at` and `trades.execution_timestamp`.
  - Automated `AUTO_REDUCE` / `AUTO_CLOSE` actions set `execution_timestamp` to their local TP/SL/time-exit execution time.
  - SQLite migration backfills historical records:
    - Legacy records fall back to `created_at`.
    - Pending-order OPEN fills use `pending_orders.triggered_at` as execution time.
    - `AUTO_*` rows always use their own trade `created_at` as execution time.
  - Dashboard local and Render snapshot modes derive `displayed_timestamp = execution_timestamp || created_at`.
  - Trade History date filtering, sorting, chart markers, equity curves, notifications, and snapshot export now use displayed/execution time.
  - Snapshot `recent_trades` now includes `decision_timestamp`, `execution_timestamp`, and `displayed_timestamp`.
- Verified live DB example:
  - Qwen pending OPEN `trade-crypto-qwen-09141b4426`: decision `2026-05-18 10:21:33.732795`, execution/display `2026-05-18 12:28:22.129891`.
  - Qwen `AUTO_REDUCE` `trade-crypto-qwen-d22f9edb0d`: execution/display `2026-05-18 12:39:16.602007`.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_position_manager.py tests/test_risk_automation.py tests/test_hot_reload.py -q` -> 29 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\storage\models.py src\storage\repository.py src\storage\risk_repository.py src\trading\execution.py src\trading\position_manager.py src\trading\risk_automation\engine.py src\dashboard\app.py src\cloud\snapshot_exporter.py src\trading\paper_account.py src\tools\retrieve_similar_trades.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 79 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.

## 2026-05-18 - Mandatory Break-Even Stop Enforcement Fix

- User report: Check whether both bots are actually executing mandatory Break-Even Stop; SL did not appear to move to entry even though a position was profitable.
- Findings:
  - `config/settings.yaml` already had `risk_automation.break_even.enabled: true` and `break_even.apply_by_default: true`.
  - Qwen position `crypto-qwen-8e6a3ee4e3` had `position_risk_state`, but SL was still `76200` after price reached/cleared TP1.
  - Root cause: `apply_break_even()` compared PnL in USDT against raw price distance `abs(entry - stop_loss)` instead of account-risk USDT. This made the +1R trigger too hard to reach.
  - DeepSeek position `DS-SHORT-004` was opened before mandatory break-even defaults were enabled, so it initially had no `position_risk_state`.
- What changed:
  - `apply_break_even()` now computes +1R using account-risk USDT: `abs(calculate_pnl(direction, notional, entry, stop_loss))`.
  - Risk automation now attaches default mandatory position-risk state to existing open positions that are missing it, so older positions can still receive mandatory break-even protection.
  - `parse_position_risk()` now unwraps multiple layers of JSON string encoding defensively.
  - Risk automation stores normalized dict config payloads instead of re-double-encoding `position_risk_state.config_json`.
- Live DB repair applied:
  - Ran one local risk tick using latest market snapshot price `77624.5`.
  - Qwen position `crypto-qwen-8e6a3ee4e3` moved SL from `76200` to `76853.76768` (`entry + fee_buffer`), with `break_even_applied: true`.
  - DeepSeek position `DS-SHORT-004` now has mandatory break-even risk state, but did not move SL yet because at `77624.5` it was about `0.75R` on the remaining partial position, below the +1R trigger.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_risk_automation.py -q` -> 18 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\trading\risk_automation\engine.py src\trading\risk_automation\position_rules.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 81 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.

## 2026-05-19 - Canonical Lesson Summaries With Raw Text Preservation

- User request: Store lessons in two forms: full `raw_text` for audit/debugging and concise canonical `summary` for dashboard and prompt use.
- Constraints honored:
  - No trading logic changes.
  - No signal generation changes.
  - No competition behavior changes.
  - No LLM/API calls for summarization.
  - Backward-compatible additive schema only.
- What changed:
  - Added deterministic local canonicalization utility: `src/agents/lesson_canonicalizer.py`.
  - New lesson records now store:
    - `raw_text`
    - `summary`
    - `category`
    - `sentiment`
    - `confidence`
    - `impact`
    - `evidence_count`
    - `source_agents_json`
    - `last_updated`
  - Added the same additive metadata fields to `shared_lessons`.
  - SQLite migration backfills legacy `lessons` and `shared_lessons` with canonical summaries and metadata.
  - `AgentMemory.retrieve_lessons()` and vector memory now use canonical summaries instead of noisy raw reflections.
  - Shared learning promotion/dedup/ranking now uses canonical summaries as the stable lesson key.
  - Lesson analytics deduplicates similar noisy lessons by canonical summary.
  - `Lessons to Follow` / `Lessons to Avoid` display canonical summaries as headlines and expose raw text in `View Raw Lesson` expanders.
  - `Memory & Reflections` displays summaries in tables and exposes raw lesson/reflection text through expanders.
  - Snapshot export includes summarized reflection rows and lesson analytics with both `summary` and `raw_text`.
  - `PROJECT_BOOTSTRAP.md` updated with the lesson memory contract.
- Example verified:
  - Raw: `Daily review: equity=10021.56, realized_pnl=21.56 ...`
  - Summary: `Trade only high-quality setups and maintain strict rule compliance.`
  - Raw: `SHORT loss: notes=CLOSED DS-SHORT-003 ... After-stop-loss wait rule ...`
  - Summary: `Pause new SHORT entries for one full cycle after a short stop-loss.`
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_lesson_canonicalizer.py tests/test_memory_repository_runner.py tests/test_lesson_analytics.py tests/test_shared_learning.py tests/test_hot_reload.py -q` -> 21 passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 85 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\agents\lesson_canonicalizer.py src\agents\memory.py src\agents\shared_learning.py src\analytics\lesson_analytics.py src\storage\models.py src\storage\repository.py src\dashboard\app.py src\dashboard\tabs\lessons_to_follow.py src\cloud\snapshot_exporter.py` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.

## 2026-05-19 - Local/Render Lesson Summary UI Sync

- User report: Render and local dashboard UI were not matching; lesson `summary` existed in DB but the local/Render views did not show the same content.
- Findings:
  - Local SQLite dashboard `Memory & Reflections` already used the canonical lesson display helper and raw expanders.
  - Render/cloud snapshot mode still rendered recent reflections directly as a raw dataframe.
  - `cloud/dashboard_snapshot.json` did not include recent lesson rows for the `Memory & Reflections` lesson column, so Render could not mirror local even when DB rows had summaries.
- What changed:
  - `src/cloud/snapshot_exporter.py` now exports `reflections_summary.recent_lessons` with `summary`, `raw_text`, metadata, and timestamps.
  - `src/dashboard/app.py` cloud snapshot mode now renders `Memory & Reflections` with the same two-column layout as local:
    - `Recent reflections`
    - `Lessons learned`
  - Both cloud columns use `lesson_display_frame()` and `render_raw_lesson_expanders()` so summaries are visible while raw text remains available for audit.
  - `tests/test_hot_reload.py` now verifies exported snapshots contain canonical reflection and lesson summaries plus raw text.
  - Regenerated `cloud/dashboard_snapshot.json` so Render receives the updated payload.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_hot_reload.py tests/test_dashboard_contract.py tests/test_lesson_analytics.py -q` -> 16 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\cloud\snapshot_exporter.py src\dashboard\app.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 85 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
  - Snapshot check confirmed `reflections_summary` keys: `by_agent`, `count_recent`, `recent`, `recent_lessons`; both recent collections include `summary` and `raw_text`.
- Notes:
  - Runtime `outputs/*` remain dirty from the live runner and should not be committed.
  - `cloud/dashboard_snapshot.json` was regenerated because Render reads it directly.

## 2026-05-19 - Lesson Card Headline Summary Guard

- User report: Local web `Lessons to Follow` ranked cards still showed noisy raw lesson text such as `equity=... realized_pnl=...` instead of the human-friendly summary.
- Root cause:
  - `Lessons to Follow` / `Lessons to Avoid` cards displayed `lesson_text` directly.
  - Analytics normally canonicalizes new rows, but stale/local rows or older snapshot-style payloads could still carry raw text in `lesson_text`.
- What changed:
  - Added `normalize_lesson_display_row()` in `src/analytics/lesson_analytics.py`.
  - `src/dashboard/tabs/lessons_to_follow.py` now normalizes all rows before filters, KPI cards, charts, and ranked cards render.
  - If `lesson_text` is raw account-status text, the card headline becomes the canonical summary.
  - Original raw text remains available in the `View Raw Lesson` expander.
  - Evidence excerpts are also canonicalized for readability while preserving raw evidence.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_lesson_analytics.py tests/test_dashboard_contract.py -q` -> 7 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\analytics\lesson_analytics.py src\dashboard\tabs\lessons_to_follow.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 86 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - Manual normalize check confirmed:
    - Raw `equity=10213.86...` becomes `Trade only high-quality setups and maintain strict rule compliance.`
    - Raw text is still preserved for audit.
- Notes:
  - Refresh local Streamlit after this change if the browser still shows the old card text.
