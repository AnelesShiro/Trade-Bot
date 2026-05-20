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
  - `Lessons to Follow` / `Lessons to Avoid` display canonical summaries as headlines and expose raw text in `View Raw Lesson` expanders.l
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
  - Follow-up hot-reload fix: the tab no longer imports `normalize_lesson_display_row` from `src.analytics.lesson_analytics`; it keeps a local dashboard helper so Streamlit cannot crash if the analytics module was already cached from an older process.
  - If `lesson_text` is raw account-status text, the card headline becomes the canonical summary.
  - Original raw text remains available in the `View Raw Lesson` expander.
  - Evidence excerpts are also canonicalized for readability while preserving raw evidence.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_lesson_analytics.py tests/test_dashboard_contract.py -q` -> 7 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\analytics\lesson_analytics.py src\dashboard\tabs\lessons_to_follow.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 86 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - Import smoke confirmed `from src.dashboard.tabs.lessons_to_follow import render_lessons_to_follow_tab, normalize_lesson_display_row` works and normalizes raw `equity=...` text.
  - Manual normalize check confirmed:
    - Raw `equity=10213.86...` becomes `Trade only high-quality setups and maintain strict rule compliance.`
    - Raw text is still preserved for audit.
- Notes:
  - Refresh local Streamlit after this change if the browser still shows the old card text.

## 2026-05-19 - Post Power Reset Health Check And Local Dashboard Restart

- User report: Machine reset because of a power outage; requested full health check and local web hosting.
- Findings:
  - Live runner auto-recovered after reset as one normal Windows parent-child process tree:
    - `.venv\Scripts\python.exe -m src.cli run-live --resume`
    - base Python child process with the same command.
  - During the first check, runner was actively processing cycle `80` in `CALLING_QWEN`; this was a valid `TRADING` phase, not overdue.
  - Cycle `80` then completed successfully:
    - `runner_state`: `RUNNING / WAITING`
    - latest checkpoint: cycle `80`, status `COMPLETED`
    - next cycle: `2026-05-19 03:43:48 UTC`
  - Snapshot refreshed after cycle `80`:
    - `cloud/dashboard_snapshot.json` generated at `2026-05-19T02:43:48Z`
    - local modified time: `2026-05-19 09:43:49`
  - Open positions after reset check:
    - Qwen LONG `crypto-qwen-96784cce85` remains `OPEN`.
  - Active cooldowns: `0`.
  - Recent cycle `80` signals:
    - DeepSeek accepted `NO_TRADE`.
    - Qwen had two rejected `POSITION_UPDATE/HOLD` attempts with `LEVERAGE_LIMIT_EXCEEDED`, then self-repaired to accepted `NO_TRADE`.
- Local dashboard:
  - `preflight-check` reported all critical checks PASS and port `8501` free before launch.
  - Started local dashboard through `scripts/start_local_dashboard.ps1`.
  - Verified `http://127.0.0.1:8501` returns HTTP `200`.
  - Streamlit process is listening on port `8501`.
- Notes:
  - Runtime `outputs/*` remain dirty from live runner updates and were not reverted.

## 2026-05-19 - Missed Cycle Recovery Audit

- User concern: the gap between recent cycles looked close to 2 hours, suggesting one scheduled cycle may have been missed during the power outage.
- Findings:
  - Confirmed cycle numbering stayed continuous (`79 -> 80`), but there was a real scheduled-slot gap:
    - cycle `79` completed at `2026-05-19 00:56:05 UTC`
    - expected next scheduled slot was about `2026-05-19 01:56:05 UTC`
    - runner resumed at `2026-05-19 02:40:58 UTC`
    - cycle `80` completed at `2026-05-19 02:43:46 UTC`
  - Impact: one scheduled decision slot was missed while the machine was off; runner resumed safely and ran the next cycle immediately after reboot.
- What changed:
  - Added `audit_missed_scheduled_cycles()` in `src/competition/checkpoint.py`.
  - `run-live --resume` now compares persisted `runner_state.next_cycle_at` with actual resume time before overwriting runner state.
  - If resume is late beyond the downtime grace window, it records:
    - `downtime_events` reason `MISSED_SCHEDULED_CYCLE`
    - `health_checks` component `missed_cycle`
    - `risk_notifications` event `MISSED_SCHEDULED_CYCLE`
    - payload with missed slot count, delay seconds, expected next cycle time, and resume time.
  - Snapshot export now includes a `downtime` payload with `latest_missed_cycle`.
  - Render/cloud dashboard shows a warning when the snapshot contains a latest missed scheduled cycle.
  - Backfilled the actual outage event into the live SQLite DB:
    - missed slots: `1`
    - expected next cycle: `2026-05-19T01:56:05.668893Z`
    - resumed: `2026-05-19T02:40:58.078333Z`
    - delay: `2692.409s`
  - Regenerated `cloud/dashboard_snapshot.json` so the dashboard shows the missed-cycle audit immediately.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_checkpoint_resume.py tests/test_hot_reload.py tests/test_dashboard_contract.py -q` -> 16 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\competition\checkpoint.py src\competition\runner.py src\cloud\snapshot_exporter.py src\dashboard\app.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 87 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli export-snapshot` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` already in use.
- Notes:
  - This is observational/audit-only. It does not backfill trades, alter positions, or change strategy behavior.
  - Runtime `outputs/*` remain dirty from live runner updates and were not reverted.

## 2026-05-19 - Overdue Recovery And OpenClaw Timeout Tightening

- User report: both local dashboard and Render/cloud dashboard were stuck showing `OVERDUE`.
- Findings:
  - The earlier safe restart had exited the live loop after cycle `81`; no live runner remained until manual resume.
  - After resume, cycle `82` initially entered `CALLING_DEEPSEEK`, but `cloud/dashboard_snapshot.json` was still from cycle `81`, so both dashboards were reading stale runner state.
  - Manual `export-snapshot` + `sync-github` pushed a live `RUNNING / CALLING_DEEPSEEK` snapshot so dashboards could show `TRADING` instead of stale `OVERDUE`.
  - The first resumed runner used the old API limits: `timeout_seconds=600`, `max_retries=3`, allowing one hung OpenClaw call to stall a cycle for roughly 30 minutes.
- What changed:
  - `config/settings.yaml` API limits changed to `timeout_seconds: 180` and `max_retries: 1`.
  - `src/agents/base_agent.py` now passes `--timeout <seconds>` directly to `openclaw agent` in addition to the Python subprocess timeout.
  - `tests/test_base_agent.py` now verifies the OpenClaw CLI timeout argument is always sent.
  - Killed the stuck old runner process tree and restarted via `scripts/start_bot_live.ps1` using `run-live --resume`.
- Runtime result:
  - New runner process tree is active: `.venv\Scripts\python.exe -m src.cli run-live --resume` plus base Python child.
  - Cycle `82` completed safely despite provider timeouts:
    - DeepSeek signal recorded as rejected `INTERNAL_ERROR` due `OpenClaw timeout after 180s`.
    - Qwen signal recorded as rejected `INTERNAL_ERROR` due `OpenClaw timeout after 180s`.
    - Checkpoint `95` saved for cycle `82`.
    - `runner_state`: `RUNNING / WAITING`, next cycle `2026-05-19T14:38:21Z`.
    - Snapshot generated at `2026-05-19T13:38:21Z` and pushed to GitHub.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_base_agent.py -q` -> 8 passed.
  - `.\.venv\Scripts\python.exe -m pytest tests\test_base_agent.py tests\test_checkpoint_resume.py tests\test_hot_reload.py -q` -> 21 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\agents\base_agent.py` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - `.\.venv\Scripts\python.exe -m src.cli preflight-check` -> all critical checks passed; dashboard port `8501` in use.
  - `http://127.0.0.1:8501` returned HTTP `200`.
- Notes:
  - Trading logic, rulebook, prompts, and dashboard UI were not changed.
  - Runtime `outputs/*` remain dirty from live runner updates and were not reverted.

## 2026-05-19 22:xx BKT - DeepSeek Gateway Fix And Failover State Reset

- User request: Fix all current errors (Qwen billing intentionally not fixed), make project run normally when not all bots fail.
- Root cause investigation:
  - `crypto-deepseek` was timing out with `OpenClaw timeout after 180s` on every cycle.
  - Cause 1: OpenClaw Gateway at `ws://127.0.0.1:18789` was timing out (60s), triggering embedded Claude fallback.
  - Cause 2: With the full 5000-token trading prompt, embedded fallback exceeded the 180s subprocess timeout.
  - Cause 3 (critical): `crypto-deepseek` failover state was stuck on Qwen (`using_fallback=True, active_provider=qwen`). Since Qwen has billing error (HTTP 400), all DeepSeek calls were actually trying Qwen first then failing.
  - `crypto-qwen` billing failure confirmed as intentional (not fixed per user request). Failover to DeepSeek already configured.
  - DeepSeek API itself is healthy (direct REST test returned OK).
- What changed:
  - Ran `.\.venv\Scripts\python.exe -m src.cli init` → re-registered OpenClaw agents, refreshed gateway routing; DeepSeek calls now work via gateway.
  - Directly reset `agent_failover_state` for `crypto-deepseek`: `using_fallback=0, active_provider=deepseek, primary_available=1, fallback_index=-1`.
  - Applied `openclaw agents` model back to `deepseek/deepseek-v4-flash` for `crypto-deepseek`.
  - Logged `RESTORE_PRIMARY` event to `api_failover_events` audit trail.
  - Added `reset-failover <agent-id>` CLI command to `src/cli.py` so future stuck failover states can be manually reset without direct DB edits.
- Final state:
  - `crypto-deepseek`: primary DeepSeek, `using_fallback=False` ✅
  - `crypto-qwen`: using DeepSeek fallback (Qwen billing failed), `using_fallback=True` ✅
  - Both agents will produce signals via DeepSeek; runner continues normally.
- Verification:
  - Smoke test: `openclaw agent --agent crypto-deepseek --session-id smoke-ds-2 --message "Reply OK" --timeout 60` → OK, model `deepseek-v4-flash` ✅
  - `show-failover-status`: crypto-deepseek primary deepseek, crypto-qwen fallback deepseek ✅
  - `.\.venv\Scripts\python.exe -m pytest -q` → 88 passed ✅
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` → passed ✅
- Notes:
  - If DeepSeek gateway fails again in future, run `python -m src.cli init` then `python -m src.cli reset-failover crypto-deepseek`.
  - Runner was already handling individual bot failures gracefully (records INTERNAL_ERROR, continues cycle). The issue was BOTH bots failing because DeepSeek's failover was stuck pointing to Qwen (billing).
  - `PositionRiskAutomation` validation error seen in earlier logs was already fixed in current codebase (loop in `parse_position_risk`); no code change needed.

## 2026-05-19 - Graceful Degradation Hardening: Subprocess Timeout In Route Switching

- User request (Vietnamese): Ensure the competition keeps running normally as long as not ALL bots are dead — no hanging, no timeouts, no blocking issues from a dead bot.
- Analysis:
  - crypto-qwen is dead (billing expired) and runs on DeepSeek fallback.
  - Each Qwen cycle currently exits fast via INTERNAL_ERROR (RuntimeError caught by `_run_agent_round`); no repair loop runs.
  - `maybe_restore_primary` runs every 3600 s for Qwen, calling `_probe_primary` to test if billing recovered.
  - Root risk: `_apply_openclaw_route` (called twice inside `_probe_primary` and once in `handle_failure`) used `subprocess.run` with NO timeout. If the `openclaw` binary hangs at that moment, the live runner blocks forever.
  - Secondary checks: `base_agent.py` already has `timeout=timeout_seconds` (180 s) on the actual agent call subprocess; `_probe_primary` already has `timeout=75`; `_run_agent_round` catches all exceptions. These are safe.
- What changed:
  - `src/agents/api_failover.py` — `_apply_openclaw_route()` now uses `timeout=30` on both `subprocess.run` calls (`models set` and fallback `agents add`) and wraps them in try/except. If either command hangs or errors out, it logs a warning and continues; the runner does not block.
- Worst-case overhead per hour with a dead Qwen:
  - Probe (`maybe_restore_primary`): up to 30 s + 75 s + 30 s = 135 s, once per 3600 s.
  - Per-cycle Qwen failure: fast HTTP 400 on billing → INTERNAL_ERROR in seconds.
  - DeepSeek (primary) cycles: unaffected.
- Verification:
  - `.\.venv\Scripts\python.exe -m py_compile src\agents\api_failover.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 88 passed.

## 2026-05-19 - Bot Succession: crypto-qwen Replaced By crypto-challenger

- User request (Vietnamese): Replace the Qwen bot with a new bot that inherits Qwen's accumulated lessons and DeepSeek's shared learning. Model TBD; set everything up so only model/API key needs to be filled in.
- What changed:
  - `config/settings.yaml`: `crypto-qwen` agent entry replaced with `crypto-challenger` (with `FILL_IN_PROVIDER`, `FILL_IN_MODEL`, `FILL_IN_BASE_URL`, `CHALLENGER_API_KEY` placeholders). `crypto-deepseek` fallback chain also updated to point to challenger placeholders (was Qwen, now TBD).
  - `src/cli.py`: added `migrate-agent-lessons <from_agent> <to_agent>` command that copies all private lesson records (preserving summary, category, sentiment, confidence, impact, evidence_count, raw_text) from one agent to another without re-canonicalizing. Source lessons remain intact.
  - Migration executed: `python -m src.cli migrate-agent-lessons crypto-qwen crypto-challenger` → 50 lessons copied to `crypto-challenger`.
  - `PROJECT_BOOTSTRAP.md`: updated Current State section and added Activating crypto-challenger guide (4-step: fill YAML, set .env, run init + validate, smoke test).
  - `PROJECT_BOOTSTRAP.md`: updated smoke test command from Qwen to Challenger.
- Inheritance model:
  - `crypto-challenger` starts competition with `initial_equity: 10000` (fresh competitive slate).
  - Has all 50 private lessons from `crypto-qwen` available from cycle 1.
  - Shared lessons (cross-agent pool) are automatically visible to all agents once promoted.
  - `crypto-qwen` data preserved in SQLite for history/audit.
- Current state until activation:
  - `crypto-challenger` will call agent with placeholder model → OpenClaw will fail → `INTERNAL_ERROR` → cycle continues normally.
  - `crypto-deepseek` is unaffected and runs normally every cycle.
- Activation steps (when model is decided):
  1. Fill `FILL_IN_*` in `config/settings.yaml` (challenger block + deepseek fallback).
  2. Add `CHALLENGER_API_KEY=<key>` to `.env`.
  3. `python -m src.cli init` → registers agent in OpenClaw.
  4. `python -m src.cli validate-update --no-smoke` + `preflight-check`.
  5. Smoke: `openclaw agent --agent crypto-challenger --session-id challenger-smoke --message "Return exactly OK." --timeout 120`.
- Verification:
  - Migration: 50 lessons confirmed in `lessons` table for `crypto-challenger`.
  - `.\.venv\Scripts\python.exe -m py_compile src\cli.py` -> passed.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 88 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.

## 2026-05-20 - WorkloadTracker KeyError Fix (crypto-challenger)

- User report: DB showing phase=ERROR and N/A for important dashboard fields.
- Root cause: `runner_state` was stuck in ERROR/ERROR with `message="'crypto-challenger'"`. This was a `KeyError: 'crypto-challenger'` crashing `run_once` at the post-processing phase, preventing cycle counter increment (cycle 85 ran twice). Crash site: `workload.reflection("crypto-challenger")` in `_persist_daily_metrics`, which is outside `_run_agent_round`'s try-except.
- Specific bug: `_agent_key("crypto-challenger")` fell through all alias/substring checks and returned `"crypto-challenger"` as-is. Then `self.agents["crypto-challenger"]` raised `KeyError` because `WorkloadTracker.agents` is a fixed dict `{"deepseek": AgentWork(), "grok": AgentWork()}`.
- What changed:
  - `src/competition/workload.py` — added `"crypto-challenger": "grok"` to `AGENT_ALIASES`.
  - `_agent_key()` fallback changed from `else agent_id` (raw ID → crash) to `else "grok"` (safe second slot for any unknown agent, including future bots).
  - Cleared `runner_state` ERROR row directly in SQLite to restore dashboard visibility.
- Any future bot with a non-deepseek name automatically maps to the `"grok"` telemetry slot without crashing.
- Verification:
  - `_agent_key` + `WorkloadTracker.reflection()` tested for all current and hypothetical agent IDs — no KeyError.
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 88 passed.
  - `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke` -> passed.
  - Cycle 85 completed successfully after restart; checkpoint 85 saved; `runner_state = RUNNING/WAITING`.

## 2026-05-20 - Preflight api_keys Block Fix (CHALLENGER_API_KEY not set)

- Context: After workload.py fix, runner restart failed at preflight because `CHALLENGER_API_KEY` env var is not set (model TBD). `_check_api_keys` is a critical check → runner blocked in `_wait_for_live_preflight` loop indefinitely.
- What changed:
  - `src/operations/preflight.py` — `_check_api_keys` now skips agents whose `LLM_PROVIDER`, `LLM_MODEL`, or `LLM_BASE_URL` starts with `FILL_IN_`. These agents are placeholder-configured and their API keys don't need to exist yet.
  - Runner restarted; preflight passed; cycle 85 ran cleanly (DeepSeek NO_TRADE, Challenger INTERNAL_ERROR as expected) and completed with checkpoint 85 saved.
  - `next_cycle_at = 2026-05-19 19:40 UTC`; runner is `RUNNING / WAITING`.
- Verification:
  - `.\.venv\Scripts\python.exe -m pytest -q` -> 88 passed.
  - `.\.venv\Scripts\python.exe -m py_compile src\operations\preflight.py` -> passed.

## 2026-05-20 - Continuous Indefinite Trading Mode

- User request: Convert project from fixed 7-day competition model to continuous, indefinite operation. No end date. Agents never stop trading due to elapsed time. Weekly KPI +7% (soft, never forces trades). Dashboard shows Project Uptime / Rolling 7d Return / Weekly Target Progress / Project Start instead of countdown metrics.
- What changed:
  - `config/settings.yaml` — `duration_days: 0`, added `weekly_target_pct: 0.07`.
  - `src/config.py` — `CompetitionSettings`: `duration_days: int = 0`, new field `weekly_target_pct: float = 0.07`.
  - `src/competition/runner.py` — Loop changed from `while datetime.now(UTC).timestamp() < ends_at` to `while True` with kill-switch file check at each iteration. Post-loop `COMPLETED` writes removed. `_competition_time_pct()` now uses unbounded rolling 7-day window (can exceed 1.0).
  - `src/competition/evaluation.py` — Return benchmark normalization `0.10 → 0.07`.
  - `config/rulebook.md` — Removed "Trial period: 1 week", "+10% target". Added continuous mode description, +7% soft KPI, updated agent list to `crypto-challenger`. Updated "Winner Criteria" → "Performance Criteria" for continuous operation.
  - `prompts/system_prompt.md` — Added continuous mode preamble: no deadline, no final day, target +7% rolling 7-day as soft KPI, NO_TRADE always acceptable.
  - `prompts/reflection_prompt.md` — Added rolling 7-day framing; added note not to reference competition endings.
  - `src/dashboard/app.py` — `competition_times()` returns `(start, None)` when `duration_days==0`. `system_status()` guards `COMPLETED` behind `if end_time is not None`. Added `rolling_7d_return_pct()` helper. Replaced `elapsed/remaining/percent_complete` with `project_uptime/_rolling_7d/_weekly_progress`. Replaced 3 old banner metrics (Time remaining, Complete, Start/End) with Project Uptime, Rolling 7d Return, Project Start; `st.progress` now shows weekly target progress with label.
  - `src/cloud/snapshot_exporter.py` — `_competition_window()` returns `(start, None)` when continuous. `_competition_status()` guards `COMPLETED` behind `if end_time is not None`. Payload `competition` block: `end_time` null-safe, added `continuous_mode`, `uptime_seconds`, `weekly_target_pct`.
  - `tests/test_continuous_mode.py` — New test file: 14 tests covering config, runner time pct, snapshot status, rolling 7d return, prompt content.
  - `PROJECT_BOOTSTRAP.md` — Updated Current State: continuous mode, kill-switch only stop, +7% soft KPI, new dashboard metrics.
- Architecture notes:
  - Kill-switch (`KILL_SWITCH` file) is the only way to stop the runner (besides SIGTERM/process kill).
  - `competition_time_pct` DB field is preserved for compat; value is now unbounded rolling fraction (can exceed 1.0).
  - All existing historical data (trades, checkpoints, signals) continues to work unchanged.
- Verification: run `pytest -q` and `validate-update --no-smoke` after this session.


## 2026-05-20 - Break-Even Stop: End-to-End Fix & Implementation

- User request: Investigate and fix Break-Even Stop so it always activates correctly when a position reaches the configured profit threshold. Fix must cover trigger math, DB persistence, dashboard display, snapshot exporter, and agent context.
- Root cause: Two issues found in `apply_break_even()` — variable `risk` was misleadingly named (price distance, not USDT risk), and the persistence condition in engine.py checked `updated_sl != position.stop_loss` AFTER overwriting `position.stop_loss = updated_sl`, so the condition was always False. Break-even SL change was saved only because `state != original_state` happened to also be True. Fixed both.
- What changed:
  - `src/trading/risk_automation/position_rules.py` — Renamed `risk` → `stop_price_distance`; confirmed r_multiple trigger math uses `calculate_pnl()` on both sides (dimensionally correct USDT comparison).
  - `src/trading/risk_automation/engine.py` — Added `original_sl = position.stop_loss` before modifications; fixed persistence condition to `position.stop_loss != original_sl`; added `logger.info` + `save_risk_notification` on activation.
  - `src/dashboard/tabs/risk_automation.py` — Added structured `be_enabled`, `be_activated`, `be_stop` columns parsed from JSON blobs instead of raw JSON display.
  - `src/cloud/snapshot_exporter.py` — Added `be_stop_price` field to risk automation payload (float when activated, null otherwise).
  - `prompts/system_prompt.md` — Added note: "Local risk automation may automatically move stop loss to break-even and trailing levels after entry. Always use the current position context as the source of truth."
  - `tests/test_risk_automation.py` — Added 5 new tests: SHORT position activation, below-1R guard, no-duplicate activation, no-regression guard, engine persistence + notification.
- Verification:
  - `py_compile` on all modified sources → passed.
  - `pytest -q` → 120 passed (all existing + 5 new).
  - `validate-update --no-smoke` → PASS. `preflight-check` → all PASS.

## 2026-05-20 - Break-Even Stop: Diagnostic Logging & DCA Guard

- User request: Dashboard still showed original stop loss after break-even fix. Investigate end-to-end and fix any remaining gaps.
- Investigation: Data path (DB write → snapshot → dashboard) confirmed architecturally correct. Two new bugs found:
  1. No diagnostic logging when break-even evaluates but does not trigger — impossible to distinguish "not yet +1R", "already activated", or "exception swallowed".
  2. Agent DCA/ADD signal can overwrite break-even stop — `position_manager._add()` line 204 used `float(signal.stop_loss or position.stop_loss)` unconditionally, reverting break-even SL back to agent's original wider stop if agent recomputed it from scratch.
- What changed:
  - `src/trading/risk_automation/position_rules.py` — Added `from loguru import logger`; added `logger.debug` in every `apply_break_even` evaluation branch (r_multiple, tp1, percent) showing pnl/account_risk/threshold/hit on every tick; added `logger.debug` when skipping an already-activated position; added `logger.info` with full context (trigger, price, pnl, account_risk, old SL, new SL) on activation; removed unused `activated = False`.
  - `src/trading/risk_automation/engine.py` — Removed duplicate `logger.info` block (logging now in position_rules.py with richer fields); updated `save_risk_notification` message to include direction, trigger type, and current price.
  - `src/trading/position_manager.py` — Fixed `_add()` stop_loss guard: for LONG uses `max(signal_sl, position.stop_loss)`; for SHORT uses `min(signal_sl, position.stop_loss)`; zero/None signal leaves stop unchanged. Ensures break-even's tighter stop is never widened by a subsequent DCA signal.
  - `tests/test_risk_automation.py` — Added 2 imports (`_position_payload`, `PaperAccount`); added 4 new tests: snapshot exporter stop_loss after break-even, agent context stop_loss after break-even, DCA cannot widen LONG stop, DCA cannot widen SHORT stop.
- Verification:
  - `py_compile` on all 3 modified sources → passed.
  - `pytest -q` → 124 passed (all existing + 4 new, 0 regressions).
  - `validate-update --no-smoke` → all PASS. `preflight-check` → all PASS.
- Notes: Debug logs are `loguru.DEBUG` level — visible in dev with `LOGURU_LEVEL=DEBUG`, silent in prod default. The DCA guard is intentionally non-blocking: it preserves the agent's intent to update the stop, while ensuring the tighter of agent vs. break-even always wins.

## 2026-05-20 - crypto-qwen Re-Activated With qwen3-max (DashScope)

- Problem addressed: `crypto-qwen` was retired after its previous DashScope billing expired. The config had been replaced with a `crypto-challenger` placeholder (`FILL_IN_*` values). User supplied a new DashScope API key and wants the second agent slot running again as `crypto-qwen` with model `qwen3-max`.
- Root cause: Billing expiry of the previous `QWEN_API_KEY`; placeholder config was intentionally incomplete.
- Files changed:
  - `config/settings.yaml` — renamed `crypto-challenger` agent block back to `crypto-qwen` (id, name, session_id); set `LLM_PROVIDER: openai`, `LLM_MODEL: qwen3-max`, `LLM_BASE_URL: https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, `LLM_API_KEY: QWEN_API_KEY`; updated `crypto-deepseek` fallback chain from `FILL_IN_*` to qwen3-max / DashScope.
  - `.env` (local, not committed) — updated `QWEN_API_KEY` to new key.
  - `PROJECT_BOOTSTRAP.md` — updated active agents, removed crypto-challenger placeholder guide, added qwen re-activation recovery notes, updated fast checks.
  - `PROJECT_CONTEXT.md` — updated Quick Context model IDs; fixed stale known-issues entry for Qwen auth.
  - `logs/SESSION_UPDATES.md` — this entry.
- Key implementation details:
  - OpenClaw agent registered via `python -m src.cli init` → confirmed `provider=openai model=qwen3-max fallback_allowed=False` logged for `crypto-qwen`.
  - DashScope uses the OpenAI-compatible endpoint (`LLM_PROVIDER: openai`) with a custom `LLM_BASE_URL`.
  - `LLM_ALLOW_FALLBACK: false` preserved; actual-model verification will fire if DashScope returns a versioned model ID (e.g. `qwen3-max-2026-*`). If that happens, update `LLM_MODEL` to the versioned slug and re-run `init`.
  - Failover chain intact: DeepSeek → Qwen fallback; Qwen → DeepSeek fallback.
- Validation:
  - `python -m src.cli init` → OK, both agents registered.
  - `validate-update --no-smoke` → all 4 checks PASS.
  - `pytest -q` → 124 passed.
  - `preflight-check` → all 9 critical checks PASS.
  - Smoke: `openclaw agent --agent crypto-qwen --session-id qwen-smoke --message "Return exactly OK." --timeout 120` → `OK`.
- Deployment notes: Runner will pick up `crypto-qwen` automatically on the next cycle. No runner restart required unless the runner is currently holding the old config in memory.
- Known limitations / follow-ups:
  - If the live runner is currently mid-cycle it will continue with the old config until the next `init` call. Running `init` again after cycle completion is safe.
  - Monitor the first live cycle to confirm actual-model verification passes for `qwen3-max`. If model verification fails, update `LLM_MODEL` in `config/settings.yaml` to the exact versioned model ID returned by the API.

## 2026-05-20 - Mandatory Post-Task Workflow Setup

- Context: User requested a permanent, session-spanning workflow: (1) pre-implementation analysis before touching any file, (2) mandatory post-task log update + validation + git commit + push after every completed implementation task.
- Problem addressed: No enforced audit trail or commit discipline existed across sessions. Startup token cost could grow unbounded as SESSION_UPDATES.md grew.
- Root cause: Workflow rules were never written into a form that persists across sessions (memory or always-loaded config file).
- Files changed:
  - `d:\Project\OpenClaw\CLAUDE.md` (new) — always-loaded project-level instructions containing the full pre-implementation analysis requirement and the 7-step mandatory post-task workflow (update log → rotate if >500KB/1000 entries → update docs → run validation → git commit → push → final report).
  - `d:\Project\OpenClaw\.claude\settings.json` (updated) — replaced narrow specific allow entries with broad wildcard permissions covering git, Python/pytest, PowerShell file ops, Read/Write/Edit/Glob/Grep tools; avoids per-prompt permission prompts for standard dev operations.
  - `C:\Users\Admin\.claude\projects\d--Project-OpenClaw\memory\feedback_post_task_workflow.md` (new) — persistent auto-memory entry so the workflow rules survive future sessions even if CLAUDE.md is missed.
- Key implementation details:
  - CLAUDE.md is automatically loaded by Claude Code at session start — no user action required. It is the primary enforcement mechanism.
  - The feedback memory entry backs up the rules and is consulted by Claude when memory is loaded.
  - No hook was configured: the post-task workflow requires Claude's reasoning (writing contextual summaries, choosing what to stage, authoring commit messages). Shell hooks can only run blind commands; CLAUDE.md is the correct mechanism for Claude's own behavioral rules.
  - CLAUDE.md and .claude/settings.json reside in `d:\Project\OpenClaw\` (workspace root), which is NOT inside the crypto-paper-trading-arena git repo. These files cannot be tracked by git.
- Validation: No source code was changed; no pytest run required.
- Deployment notes: Rules are immediately active. No restart needed.
- Known limitations:
  - CLAUDE.md and .claude/settings.json are outside the git repo — not version-controlled. If the workspace is cloned fresh these files must be recreated.
  - The workflow is enforced by Claude's behavioral instructions, not by a hard technical lock. The user can bypass it with "do not commit" / "draft only" etc.

## 2026-05-20 - Project-Wide Permission Allow-List

- Context: Claude Code was prompting for permission on every standard development operation (pytest, git, file reads/writes, etc.), breaking the flow of multi-step tasks.
- Problem addressed: Excessive permission prompts for routine, safe dev operations.
- Root cause: `.claude/settings.json` only had three narrow, specific `Bash(...)` allow entries for previously-approved one-off commands.
- Files changed:
  - `d:\Project\OpenClaw\.claude\settings.json` — replaced the three specific entries with a broad wildcard allow-list covering: `Bash(git *)`, `Bash(.venv\Scripts\python.exe *)`, `Bash(python *)`, `Bash(pytest *)`, all PowerShell file-manipulation cmdlets (`Get-Content`, `Set-Content`, `Add-Content`, `Copy-Item`, `Move-Item`, `Remove-Item`, `Get-ChildItem`, `Test-Path`, `New-Item`), and all `Read(*)`, `Write(*)`, `Edit(*)`, `Glob(*)`, `Grep(*)` tool uses.
- Key implementation details: The three old specific entries are fully subsumed by the new wildcards — no previously-approved operation was removed.
- Validation: No source code changed; no test run required.
- Deployment notes: Active immediately for the current and all future sessions in this workspace.
- Known limitations: File is outside the git repo (workspace root, not inside `crypto-paper-trading-arena/`); not version-controlled.
