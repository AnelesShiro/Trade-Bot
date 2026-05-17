# Project Overview

## Quick Context For New Sessions

- Lowest-token entry point: read `PROJECT_BOOTSTRAP.md` first.
- Read this section first, then skim `logs/SESSION_UPDATES.md` from the bottom upward.
- Active agents are `crypto-deepseek` and `crypto-qwen`; legacy `crypto-grok` remains only for DB/history/audit.
- Current live runner process shape on Windows normally appears as two rows: `.venv\Scripts\python.exe` parent plus base Python child. Treat that as one runner process tree unless there are multiple unrelated parent trees.
- Latest verified live cycle: cycle `46` completed. DeepSeek succeeded; Qwen failed non-fatally because the supplied Qwen credential is rejected by the provider (`Provider qwen has auth issue`).
- Qwen model routing and OpenClaw agent registration are fixed. Remaining Qwen blocker is provider auth/key validity, not project config, agent id, or model routing.
- Model locking now works through OpenClaw agent registry plus post-response actual-model verification. Do not reintroduce per-request `--model` overrides; this Gateway rejects them.
- `LLM_MODEL` must match the provider response model id exactly, currently `deepseek-v4-flash` and `qwen3-max-2026-01-23`.
- `python -m src.cli init` syncs DB agents, OpenClaw agent registry, and OpenClaw auth profiles from `.env`.
- Runtime files in `outputs/` are live-generated and may remain dirty. Do not revert them unless explicitly asked.
- Use `.venv\Scripts\python.exe` for validation and tests.

- Project name: `crypto-paper-trading-arena`
- Purpose: Production-oriented paper trading competition platform for two OpenClaw AI agents trading BTCUSDT perpetual futures in paper mode only.
- Core features:
  - Runs two active agents: `crypto-deepseek` and `crypto-qwen`.
  - Fetches public BTCUSDT perpetual market data through CCXT.
  - Builds shared market context with indicators, regime, funding, open interest, and local tool results.
  - Asks each agent for strict JSON trading signals.
  - Validates signals against the rulebook before execution.
  - Executes accepted signals in a paper trading engine with simulated fees and slippage.
  - Stores state in SQLite and output files.
  - Shows a Streamlit dashboard for local and cloud monitoring.
  - Exports a compact cloud snapshot for Render-hosted read-only dashboards.
  - Tracks rejected signals, accepted signals, raw outputs, memory, reflections, token usage, API cost, workload attribution, leaderboard, and account summaries.
  - Maintains a project memory log at `logs/SESSION_UPDATES.md` so future sessions can quickly reconstruct recent chat decisions and implementation updates.
  - Uses strict model locking so provider-side model redirects cannot be accepted silently.
- Target users:
  - The project owner monitoring the AI trading competition.
  - Future Codex/OpenClaw development sessions.
  - Viewers of the read-only cloud dashboard.

# Goals

- Primary objectives:
  - Run a reliable BTCUSDT paper trading arena between DeepSeek and Qwen agents.
  - Keep the local runner alive across provider errors, restarts, and dashboard sync failures.
  - Provide a professional Streamlit dashboard that clearly shows competition status and trading performance.
  - Preserve full auditability for every accepted and rejected signal.
  - Keep dashboard cloud deployment read-only and safe, without secrets.
- Success criteria:
  - `python -m src.cli run-live --resume` can continue from the latest checkpoint.
  - A single provider failure must not stop the whole cycle.
  - Dashboard must not silently show incorrect signal counts.
  - Snapshot export contract must fail loudly instead of overwriting good data with incomplete data.
  - Existing dashboard UI/UX must remain stable unless the user explicitly asks for a redesign.
  - Tests pass with coverage target of at least 80% for core non-UI logic.
  - Every meaningful Codex/user discussion, decision, investigation, fix, and verification result is appended to `logs/SESSION_UPDATES.md`.

# Current Architecture

- Tech stack:
  - Python 3.11+
  - Streamlit
  - `streamlit-lightweight-charts` and Plotly
  - pandas, numpy
  - CCXT
  - SQLite through SQLAlchemy
  - Pydantic / pydantic-settings
  - Typer CLI
  - pytest / pytest-cov
  - loguru
  - ChromaDB, scikit-learn, xgboost for memory/vector/analytics support
- Folder structure:
  - `config/`: canonical configuration, including `settings.yaml` and `rulebook.md`.
  - `database/`: local SQLite database, usually `arena.db`.
  - `outputs/`: generated runtime reports such as `SIGNALS.md`, `LEDGER.csv`, and `EVALUATION.md`.
  - `cloud/`: generated `dashboard_snapshot.json` used by cloud dashboard.
  - `logs/`: runtime logs plus the human/Codex handoff log `SESSION_UPDATES.md`.
  - `state/`: checkpoints, backups, update queue, live state.
  - `prompts/`: active and versioned system prompts.
  - `rulebooks/`: versioned rulebook updates.
  - `scripts/`: support scripts such as watchdog.
  - `src/`: application source code.
  - `tests/`: unit and integration tests.
- Key modules:
  - `src/cli.py`: CLI entrypoint for init, live runs, dashboard, cloud sync, update management, workload reports.
  - `src/config.py`: settings loading.
  - `src/schemas.py`: core data contracts and typed models.
  - `src/agents/base_agent.py`: OpenClaw subprocess invocation, output parsing, timeout/retry handling.
  - `src/agents/deepseek_agent.py`: DeepSeek agent wrapper.
  - `src/agents/qwen_agent.py`: Qwen agent wrapper.
  - `src/agents/grok_agent.py`: legacy Grok/xAI wrapper retained for historical compatibility.
  - `src/agents/memory.py`, `reflection.py`, `shared_learning.py`: private memory, reflections, and lessons.
  - `src/market/data_feed.py`: CCXT market data.
  - `src/market/indicators.py`: indicators such as EMA/RSI.
  - `src/market/regime.py`: market regime detection.
  - `src/tools/`: approved local tools agents can request before final signal.
  - `src/validation/rule_engine.py` and `signal_validator.py`: strict signal validation.
  - `src/trading/execution.py`, `paper_account.py`, `position_manager.py`, `pnl.py`: paper execution and accounting.
  - `src/storage/repository.py`: SQLite persistence for core arena state.
  - `src/storage/signal_repository.py`: accepted/rejected signal audit persistence.
  - `src/competition/runner.py`: main competition loop, cycle orchestration, provider error handling, checkpoint/export/sync.
  - `src/competition/checkpoint.py`: crash-safe checkpointing and resume support.
  - `src/competition/evaluation.py`, `leaderboard.py`, `workload.py`: scoring, leaderboard, workload attribution.
  - `src/cloud/snapshot_exporter.py`: exports dashboard snapshot and validates snapshot contract.
  - `src/cloud/git_sync.py`: optional GitHub sync for cloud snapshot.
  - `src/dashboard/app.py`: Streamlit dashboard.
  - `src/dashboard/tabs/accepted_signals.py` and `rejected_signals.py`: signal audit dashboard tabs.
  - `src/dashboard/components/cycle_status_bar.py`: cycle status UI.
- Data flow:
  - CCXT public data is fetched and transformed into market state.
  - Indicators, market regime, funding, open interest, memory, and rulebook context are added.
  - Both agents receive the same frozen market snapshot per cycle.
  - Agents may request approved local tools.
  - Agents return final strict JSON signals.
  - Signals are parsed, repaired when possible, validated, and either accepted or rejected.
  - Accepted signals go to the paper execution engine.
  - Rejected signals are stored with validation errors and reasons.
  - SQLite and output files are updated.
  - Checkpoint is written after each completed cycle.
  - Snapshot is exported to `cloud/dashboard_snapshot.json`.
  - Optional Git sync commits and pushes snapshot to GitHub for Render.

# Design Principles

- UI/UX requirements:
  - Preserve the existing Arena Overview dashboard layout unless explicitly requested.
  - Required dashboard structure:
    - Header / competition status / countdown.
    - Overview tab with live BTC chart at the top.
    - Overview metric cards for both agents.
    - Sidebar controls.
    - Tabs: Overview, Live Positions, Trade History, Equity Curves, Leaderboard, Rejected Signals, Raw Model Outputs, Memory & Reflections, Token & Cost, Configuration.
  - Do not replace the dashboard with a standalone chart page.
  - Do not remove KPI cards, tabs, sidebar, status bar, or existing sections.
  - Live BTC chart should be additive and dominant inside the Overview tab.
  - Chart requirements:
    - BTCUSDT perpetual candlesticks.
    - Timeframes: 1m, 5m, 15m, 1h, 4h, 1d.
    - Dark theme matching the dashboard.
    - EMA 9, 21, 50, 200.
    - Volume panel.
    - RSI panel.
    - Historical trade overlays for both agents.
    - Open position overlays: entry, stop loss, TP1, TP2, liquidation estimate.
    - Height around 700-900px.
  - Marker conventions:
    - DeepSeek: blue markers.
    - Challenger/Qwen: green markers.
    - LONG entry: up marker.
    - SHORT entry: down marker.
    - Take profit: circle.
    - Stop loss: X.
- Performance requirements:
  - Dashboard initial load target under 3 seconds where feasible.
  - Cache expensive dashboard reads.
  - Handle thousands of candles and hundreds of trades.
  - Gracefully handle empty datasets.
  - Runner must keep operating when dashboard sync fails.
- Scalability requirements:
  - Persist canonical state in SQLite.
  - Keep cloud snapshot compact and non-secret.
  - Use checkpoints for crash-safe recovery.
  - Use update queue for safe changes at cycle boundaries.
- Security considerations:
  - Paper trading only; never place real orders.
  - `.env` must remain private and gitignored.
  - Snapshot must never contain provider API keys, `.env` values, or local secrets.
  - Render dashboard is read-only and should operate from `cloud/dashboard_snapshot.json`.
  - Git sync failures are logged and must not stop trading.

# Technical Constraints

- Things that must NOT be changed:
  - Do not remove or redesign the existing dashboard layout without explicit instruction.
  - Do not remove the existing tabs or KPI cards.
  - Do not convert the dashboard into a new standalone OKX clone page.
  - Do not overwrite or revert runtime files generated by the runner unless explicitly requested.
  - Do not commit secrets or `.env`.
  - Do not make one provider failure stop the full competition cycle.
  - Do not allow automatic model switching, fallback models, or provider default models.
  - Do not silently show wrong accepted/rejected signal counts.
  - Do not overwrite a valid dashboard snapshot with an incomplete snapshot.
- Dependencies and compatibility requirements:
  - Python 3.11+.
  - Render should use Python `3.11.11`.
  - Keep `pyproject.toml` `requires-python = ">=3.11"`.
  - Runtime files include `.python-version` and `runtime.txt`.
  - `streamlit-lightweight-charts` is preferred for charting but Plotly fallback is acceptable and was used to ensure visible charts.
  - Plotly color values must use valid color formats such as `rgba(...)`; avoid invalid hex alpha like `#22c55e66`.
  - Agent LLM configuration lives only under each agent's `llm` block in `config/settings.yaml` with `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_ALLOW_FALLBACK: false`.
- Deployment limitations:
  - Local machine runs agents, SQLite, memory, paper execution, and snapshots.
  - Render only hosts read-only Streamlit dashboard.
  - Cloud dashboard depends on latest committed `cloud/dashboard_snapshot.json`.
  - GitHub snapshot pushes may trigger Render auto-deploy.

# Completed Work

- Features already implemented:
  - CLI commands for init, preflight, run-once, run-live, resume, dashboard, backtest, evaluate, config reload, prompt/rulebook queueing, safe restart, rollback, version display, workload analysis, cloud snapshot export, GitHub sync, and deployment checks.
  - Paper trading engine with rule validation, simulated taker fees, and slippage.
  - Crash-safe checkpoints after completed cycles.
  - Position monitor that runs between cycles and auto-closes paper positions on TP/SL.
  - Dashboard with status, countdown, account summaries, positions, trade history, equity curves, leaderboard, rejected/accepted signals, raw outputs, memory/reflections, token/cost analytics, configuration, and workload attribution.
  - Cloud dashboard snapshot export and optional GitHub auto-push.
  - Snapshot contract validation.
  - Accepted and rejected signal history support in snapshots.
  - Workload attribution across Local Machine, DeepSeek, and the active challenger slot. The DB columns still use legacy `grok_*` names, but `crypto-qwen` maps into that second-agent workload slot.
  - Strict model governance: OpenClaw agents are registered with the locked provider/model pair, runtime responses verify actual model, and mismatches fail.
- Bugs fixed:
  - Dashboard timestamp was shown in UTC; changed to local Asia/Bangkok display where relevant.
  - Initial OKX-style dashboard attempt regressed layout; direction corrected to additive chart only.
  - BTC chart was not visible for the user; switched to reliable Plotly candlestick rendering/fallback.
  - Plotly volume color error from invalid `#RRGGBBAA` format; fixed with `rgba(...)`.
  - Snapshot could miss `signal_audit_summary` fields and silently show incorrect accepted counts; added contract guard.
  - Web dashboard previously rendered only `latest_accepted_signal`; added `recent_accepted_signals` and `recent_rejected_signals`.
  - Stop-loss cooldown blocked same-direction trades forever after the latest SL; limited cooldown to the next full decision cycle.
  - OpenClaw subprocess output handling hardened for Unicode and `stderr=None`.
  - Provider billing/API errors no longer crash the entire cycle; runner records rejected `INTERNAL_ERROR`, checkpoints, exports snapshot, syncs, and continues.
  - Silent xAI model redirect risk addressed with strict model mismatch failure.
  - Active challenger changed from `crypto-grok` to `crypto-qwen` with fresh 10,000 USDT paper equity because Qwen uses a new `agent_id` and does not inherit Grok trades.
- Refactors completed:
  - Signal audit repository and snapshot exporter were extended to support recent accepted/rejected signal lists.
  - Runner error handling was hardened so one agent provider failure does not block the other agent or the cycle lifecycle.

# Known Issues

- Current problems:
  - `crypto-qwen` currently fails provider auth with `Provider qwen has auth issue`. The project config and OpenClaw agent registration are fixed; replace/repair the Qwen provider credential before expecting Qwen signals.
  - Cloud dashboard can become stale if the local runner is offline, Git sync fails, or Render deployment lags.
  - Runtime output files may be modified continuously by live runner.
- Edge cases:
  - CCXT/Binance USD-M futures market data can fail depending on network availability or regional restrictions.
  - Empty SQLite tables or missing snapshots must render graceful dashboard states.
  - Old snapshots without new contract fields should show clear warnings rather than misleading counts.
  - Provider responses may contain malformed JSON and need repair/rejection.
  - Position monitor must never call agents or place real orders.
- Technical debt:
  - `src/dashboard/app.py` is large and should be changed carefully.
  - Dashboard UI tests are mostly smoke-style; full visual regression coverage is limited.
  - Runtime logs and generated outputs can be noisy and should not be treated as source files.

# Pending Tasks

- High priority:
  - Replace/repair the Qwen provider credential, then run `.\.venv\Scripts\python.exe -m src.cli init` and a small Qwen smoke call.
  - Keep checking dashboard snapshot contract after schema changes.
  - Ensure accepted/rejected signal tabs keep using recent signal lists, not only latest signal.
  - Validate live runner after restarts with `run-live --resume`.
- Medium priority:
  - Add targeted tests for dashboard snapshot rendering of accepted/rejected signal history.
  - Add tests for provider failure paths and cycle continuation.
  - Improve visual/manual validation checklist for the BTC chart in Overview tab.
  - Keep README and `PROJECT_CONTEXT.md` aligned after major architecture changes.
- Low priority:
  - Consider splitting dashboard code into more tab/component modules.
  - Add richer chart replay mode if explicitly requested.
  - Add more analytics around cost per profitable trade and agent efficiency.

# Coding Conventions

- Naming rules:
  - Active agents are identified as `crypto-deepseek` and `crypto-qwen`.
  - Legacy `crypto-grok` data remains in SQLite for audit/history and must not be merged into `crypto-qwen`.
  - Use clear snake_case for Python functions, variables, and file names.
  - Keep data model names explicit and domain-oriented.
- File organization:
  - Keep dashboard-specific code under `src/dashboard/`.
  - Keep signal persistence under `src/storage/`.
  - Keep validation logic under `src/validation/`.
  - Keep paper execution logic under `src/trading/`.
  - Keep cycle orchestration under `src/competition/`.
  - Keep cloud snapshot and Git sync under `src/cloud/`.
  - Keep tests next to the relevant behavior in `tests/`.
- Error handling style:
  - Fail loud for data contract violations that would mislead the dashboard.
  - Provider errors should be recorded as rejected/internal-error signals and must not stop the full runner.
  - Git sync errors should be logged and retried later, not fatal to trading.
  - Dashboard should show warnings for stale/missing data instead of crashing when possible.
- Logging style:
  - Use existing logging infrastructure.
  - Record operational health checks in SQLite where applicable.
  - Preserve enough context to diagnose provider, checkpoint, snapshot, and sync failures.

# Prompt Conventions

- Standard instructions when modifying the project:
  - Read `PROJECT_BOOTSTRAP.md` first for the shortest current-state briefing.
  - Read `PROJECT_CONTEXT.md` next only when deeper architecture, constraints, or conventions are needed.
  - Read the last 2-4 entries of `logs/SESSION_UPDATES.md` after `PROJECT_CONTEXT.md` to catch recent decisions without wasting tokens.
  - Prefer minimal, precise, production-ready changes.
  - Preserve existing UI/UX, architecture, and performance characteristics unless explicitly requested.
  - Verify behavior with focused tests.
  - Treat `config/rulebook.md` as canonical trading rules.
  - Treat `docs/MODEL_GOVERNANCE.md` as canonical model locking guidance.
  - Be careful with live runner state, checkpoints, and generated runtime outputs.
  - Append a concise entry to `logs/SESSION_UPDATES.md` whenever a session includes a meaningful user request, technical decision, code change, bug investigation, verification result, deployment action, or known issue.
- Rules to avoid unnecessary changes:
  - Do not refactor broad areas unless required for the task.
  - Do not change dashboard layout while fixing backend issues.
  - Do not change rulebook behavior unless the user asks.
  - Do not commit or expose secrets.
  - Do not delete or reset user/runtime state without explicit instruction.
  - Do not assume a stale cloud dashboard means the local runner is broken; check snapshot/sync/Render separately.

# Project Memory Log

- Canonical session/update log: `logs/SESSION_UPDATES.md`.
- Purpose:
  - Preserve project conversation context across Codex sessions.
  - Capture decisions that would otherwise live only in chat.
  - Make future sessions faster and safer by exposing recent work, known risks, and user preferences.
- Required logging protocol:
  - At the start of a new session, read `PROJECT_CONTEXT.md`, then read `logs/SESSION_UPDATES.md`.
  - During or at the end of each meaningful task, append a new dated entry.
  - Keep entries concise but complete enough for another Codex session to understand what happened.
  - Include files changed, commands/tests run, verification results, and remaining risks.
  - Do not log secrets, API keys, private tokens, or full provider responses that may contain sensitive data.
  - Do not use this log for high-volume runtime output; keep runtime logs in normal `.log` files.
- Entry template:
  ```markdown
  ## YYYY-MM-DD HH:mm TZ - Short Title

  - User request:
  - What changed:
  - Files touched:
  - Verification:
  - Notes / follow-ups:
  ```

# Important Decisions

- Paper-only architecture:
  - The system must never place real exchange orders. All execution is simulated.
- Frozen shared market snapshot:
  - Both agents receive the same market context per cycle for fairness.
- Strict JSON signal contract:
  - Agents must produce structured signals that can be validated and audited.
- Validation before execution:
  - Rule engine rejects invalid signals before any paper trade is recorded.
- SQLite as canonical local state:
  - Checkpoints support recovery, but database remains the source of operational truth.
- Snapshot-based cloud dashboard:
  - Render reads `cloud/dashboard_snapshot.json` and does not need local SQLite, logs, or secrets.
- Snapshot contract guard:
  - Incomplete snapshots should fail validation and not overwrite good dashboard data.
- Additive dashboard changes:
  - The live BTC chart belongs inside the existing Overview tab above performance cards.
  - The existing Arena Overview layout must be preserved.
- Provider failure isolation:
  - If Qwen, legacy Grok/xAI, or DeepSeek provider fails, the runner should continue the cycle lifecycle and record the failure.
- Strict model locking:
  - `python -m src.cli init` registers each OpenClaw agent with the configured provider/model pair.
  - Runtime calls use the locked OpenClaw agent model because this Gateway rejects per-request model overrides.
  - Actual provider response model must match `LLM_MODEL`.
  - `LLM_MODEL` should be the exact provider response model id, not necessarily the OpenClaw registry's provider-qualified `provider/model` string.
  - If a provider redirects to a different model, the request fails with: `Configured model '<LLM_MODEL>' is unavailable. Automatic model switching is disabled.`
  - `LLM_ALLOW_FALLBACK` must remain `false`.
- Stop-loss cooldown scope:
  - Cooldown after stop loss applies only to the next full decision cycle, not forever.
- Local timezone display:
  - Dashboard timestamps should be understandable locally, especially Asia/Bangkok for this setup.

# Testing Requirements

- Unit tests:
  - Signal parsing and repair.
  - Rule validation.
  - Paper execution and PnL calculations.
  - Repository persistence.
  - Signal audit storage and retrieval.
  - Snapshot export contract validation.
  - Stop-loss cooldown logic.
  - Provider error handling.
  - Workload attribution calculations.
- Integration tests:
  - Runner cycle with mocked OpenClaw calls.
  - `run-live --resume` checkpoint recovery behavior.
  - Cloud snapshot export and Git sync non-fatal failure path.
  - Dashboard smoke import/render path when possible.
- Manual validation checklist:
  - Run `python -m src.cli preflight-check`.
  - Run `python -m src.cli run-once` or verify live runner status.
  - Run `python -m src.cli export-snapshot`.
  - Run dashboard locally with `python -m src.cli dashboard` or `streamlit run src/dashboard/app.py`.
  - Confirm Overview tab keeps header, countdown, sidebar, tabs, KPI cards, and live BTC chart.
  - Confirm chart shows BTC candles, EMA overlays, volume, RSI, markers, and position lines when data exists.
  - Confirm accepted/rejected signal tabs show recent lists, not only latest signal.
  - Confirm cloud snapshot does not contain secrets.
  - Run `pytest --cov=src`.

# Deployment Information

- Hosting platform:
  - Local machine runs the trading engine and agents.
  - GitHub stores source and latest cloud dashboard snapshot.
  - Render hosts the read-only Streamlit dashboard.
- Build commands:
  - Install dependencies:
    ```powershell
    pip install -r requirements.txt
    ```
  - Initialize local state:
    ```powershell
    python -m src.cli init
    ```
  - Run one cycle:
    ```powershell
    python -m src.cli run-once
    ```
  - Run continuously:
    ```powershell
    python -m src.cli run-live
    ```
  - Resume:
    ```powershell
    python -m src.cli run-live --resume
    ```
  - Local dashboard:
    ```powershell
    python -m src.cli dashboard
    ```
  - Direct Streamlit dashboard:
    ```powershell
    streamlit run src/dashboard/app.py
    ```
  - Tests:
    ```powershell
    pytest --cov=src
    ```
  - Export cloud snapshot:
    ```powershell
    python -m src.cli export-snapshot
    ```
  - Export and push cloud update:
    ```powershell
    python -m src.cli cloud-update
    ```
- Render commands:
  - Build: `pip install -r requirements.txt`
  - Start: `streamlit run src/dashboard/app.py --server.port $PORT --server.address 0.0.0.0`
- Environment variables:
  - `DEEPSEEK_API_KEY`: optional setup helper for OpenClaw auth profile.
  - `QWEN_API_KEY`: optional setup helper for OpenClaw auth profile.
  - `OPENCLAW_BIN`: path to OpenClaw executable if not in PATH.
  - `ARENA_WARMUP_MODE=true`: optional warmup mode.
  - `ARENA_KILL_SWITCH=true`: global kill switch.
  - Render should set/use Python `3.11.11`.
- Important files:
  - `.env`: local secrets, gitignored.
  - `.env.example`: example env vars.
  - `render.yaml`, `Procfile`: cloud deployment.
  - `.python-version`, `runtime.txt`: Python runtime markers.

# Future Ideas

- Add richer trade replay mode with candles before/after entry, thesis, invalidation, exit, and reflection notes.
- Add visual regression tests for dashboard layout.
- Modularize large dashboard sections into smaller components.
- Add more cloud health diagnostics for Render deploy lag.
- Add alerting for stale snapshots, overdue cycles, provider billing errors, and daily loss limits.
- Improve analytics for profit per dollar of API cost, cost per trade, and decision efficiency.
- Add deeper strategy diversity visualization.

# Session Continuation Prompt

Read `PROJECT_BOOTSTRAP.md` first. If more context is needed, read `PROJECT_CONTEXT.md`, starting with `Quick Context For New Sessions`, then read the latest entries at the bottom of `logs/SESSION_UPDATES.md`; treat them together as the complete project memory and source of truth. Continue development without changing existing UI/UX, architecture, or performance characteristics unless explicitly requested. Append meaningful session updates back to `logs/SESSION_UPDATES.md`.

Reusable prompt for future Codex sessions:

```text
Read PROJECT_BOOTSTRAP.md first.
If more context is needed, read PROJECT_CONTEXT.md starting with the Quick Context For New Sessions section.
Then read only the latest relevant entries at the bottom of logs/SESSION_UPDATES.md unless deeper history is needed.
If additional details are needed, read the full shared ChatGPT conversation:
<PASTE_SHARED_LINK_HERE>

Treat PROJECT_BOOTSTRAP.md, PROJECT_CONTEXT.md, logs/SESSION_UPDATES.md, and the shared conversation as the source of truth.
Continue development without changing existing UI/UX unless explicitly requested.
Focus on minimal, precise, production-ready changes only.
At the end of every meaningful task, append a concise update to logs/SESSION_UPDATES.md.
```
