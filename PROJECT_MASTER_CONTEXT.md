# PROJECT_MASTER_CONTEXT.md
> Auto-generated AI-to-AI handoff document. Last updated: 2026-05-22.
> Purpose: enable any AI engineer to understand and continue this project with minimal confusion.

---

## 1. Executive Summary

**crypto-paper-trading-arena** is a continuous, autonomous paper-trading competition for BTCUSDT perpetual futures. Three AI agents powered by different LLM providers (DeepSeek, Qwen/DashScope, Gemini/Google) each manage a simulated $10,000 USDT account indefinitely (no end date). Every hour the system fetches live BTC market data from Binance, builds a shared frozen market snapshot, calls each agent for a trading signal, validates it against the rulebook, simulates execution, and updates all metrics.

**What makes it non-trivial:**
- All three agents receive the same frozen market snapshot per cycle (fairness constraint)
- Each agent has private lessons plus access to a shared lesson pool (cross-agent learning)
- Local Python risk automation handles break-even stops, trailing stops, time exits, conditional orders, and cooldowns — no extra LLM calls for risk management
- The runner never executes real exchange orders; it is paper-only by design and constraint
- A read-only cloud dashboard (Render) reads a JSON snapshot pushed to GitHub after each cycle; it has no runner of its own

**Current production state (as of 2026-05-22):** 1 runner pair running (PIDs 45536+15564), cycle 147+, all three agents active, DeepSeek and Qwen healthy, Gemini returning HTTP 401 each cycle. Dashboard shows live data at `cloud/dashboard_snapshot.json` synced to GitHub main branch.

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  LOCAL MACHINE (Windows, Python venv)                              │
│                                                                    │
│  python -m src.cli run-live --resume                               │
│         │                                                          │
│         ▼                                                          │
│  CompetitionRunner (src/competition/runner.py)                     │
│    ├─ fetch market data (Binance via ccxt)                         │
│    ├─ risk_engine.run_market_tick()  ← local, no LLM              │
│    ├─ position_manager.update_stops_and_targets()                  │
│    ├─ for each agent → _run_agent_round()                          │
│    │     ├─ build prompt (market + memory + lessons + positions)   │
│    │     ├─ openclaw agent --agent <id> ...  ← subprocess         │
│    │     │        ▲                                                │
│    │     │  OpenClaw Gateway (Node.js CLI, separate process)       │
│    │     │  calls LLM API (DeepSeek / DashScope / Google)         │
│    │     │  writes ~/.openclaw/agents/<id>/sessions/<sid>.jsonl    │
│    │     ├─ parse + validate AgentSignal (Pydantic)                │
│    │     ├─ rule-check (rulebook)                                  │
│    │     ├─ paper execute or reject                                │
│    │     └─ save signal, lesson, api_request to SQLite             │
│    ├─ promote_lessons(), analyze_diversity()                       │
│    ├─ write SIGNALS.md, LEDGER.csv, EVALUATION.md                  │
│    ├─ save checkpoint                                              │
│    └─ export_dashboard_snapshot() → cloud/dashboard_snapshot.json │
│         └─ git push main → GitHub                                  │
│                                                                    │
│  SQLite: database/arena.db  (canonical state)                      │
│  File checkpoint: state/checkpoints/latest.json                    │
└────────────────────────────────────────────────────────────────────┘
                              │ git push
                              ▼
                    GitHub repository (main branch)
                    cloud/dashboard_snapshot.json
                              │ reads JSON
                              ▼
                    Render.com (read-only web dashboard)
                    No runner, no DB, no secrets
```

**Key design rules:**
- SQLite is the single source of truth for all state
- `latest.json` is a secondary checkpoint used only to accelerate `--resume` restarts
- The Render deployment is 100% read-only; it never writes anything
- OpenClaw gateway is a local Node.js CLI; Python calls it via subprocess (not HTTP)
- `LLM_ALLOW_FALLBACK: false` is enforced both in YAML config and at Pydantic parse time

---

## 3. Folder & File Map

```
crypto-paper-trading-arena/
├── config/
│   ├── settings.yaml          ← main config (hot-reload capable)
│   └── rulebook.md            ← trading rules for agents (hot-reload capable)
├── database/
│   └── arena.db               ← SQLite canonical state (never commit)
├── state/
│   └── checkpoints/
│       └── latest.json        ← secondary cycle counter checkpoint
├── outputs/                   ← runtime-generated, never commit
│   ├── SIGNALS.md
│   ├── LEDGER.csv
│   └── EVALUATION.md
├── cloud/
│   └── dashboard_snapshot.json ← exported each cycle, pushed to GitHub
├── logs/
│   ├── SESSION_UPDATES.md     ← append-only implementation log
│   └── SESSION_ARCHIVE_*.md   ← archived old entries
├── prompts/
│   ├── system_prompt.md       ← agent system prompt (hot-reload capable)
│   ├── reflection_prompt.md
│   ├── referee_prompt.md
│   └── system_prompt.v001.md  ← version archive
├── tests/                     ← 28 test files
│   └── test_dashboard_contract.py  ← critical: validates tab labels
├── src/
│   ├── cli.py                 ← entry point: `python -m src.cli`
│   ├── config.py              ← Pydantic settings models + loaders
│   ├── schemas.py             ← AgentSignal, MarketState, all domain types
│   ├── logger.py              ← loguru configuration
│   ├── agents/
│   │   ├── base_agent.py      ← OpenClawAgent, subprocess call, JSONL reader
│   │   ├── memory.py          ← AgentMemory, retrieve_lessons() 3-factor score
│   │   ├── lesson_canonicalizer.py
│   │   └── ...
│   ├── analytics/
│   │   ├── world_model.py     ← regime×direction win-rate table
│   │   ├── calibration.py     ← confidence → actual win-rate
│   │   └── lesson_analytics.py
│   ├── cloud/
│   │   ├── snapshot_exporter.py  ← export_dashboard_snapshot()
│   │   └── git_push.py
│   ├── competition/
│   │   ├── runner.py          ← CompetitionRunner (main loop)
│   │   ├── evaluation.py      ← leaderboard, PnL calculations
│   │   ├── preflight.py       ← run_preflight(), has_critical_failures()
│   │   └── workload.py        ← WorkloadTracker
│   ├── dashboard/
│   │   ├── contract.py        ← DASHBOARD_TAB_LABELS (19 tabs)
│   │   └── ...
│   ├── market/
│   │   └── ...                ← get_market_state(), ccxt integration
│   ├── operations/
│   │   ├── config_manager.py  ← hot-reload config
│   │   └── update_manager.py  ← LiveUpdateManager, pending updates
│   ├── storage/
│   │   ├── models.py          ← all SQLAlchemy ORM models
│   │   ├── repository.py      ← ArenaRepository (all DB queries)
│   │   └── signal_repository.py
│   ├── trading/
│   │   ├── execution.py       ← PaperExecutionEngine
│   │   ├── paper_account.py   ← PaperAccount, equity tracking
│   │   ├── position_manager.py
│   │   └── risk_automation/
│   │       ├── engine.py      ← RiskAutomationEngine
│   │       ├── cooldown.py    ← CooldownManager
│   │       ├── position_rules.py ← break_even, trailing_stop, time_exit
│   │       ├── triggers.py    ← evaluate_trigger(), trigger_expired()
│   │       └── types.py
│   ├── utils/
│   └── validation/
│       └── rule_engine.py     ← rulebook validation against signals
├── PROJECT_BOOTSTRAP.md       ← current system state briefing
├── PROJECT_CONTEXT.md         ← architecture + conventions reference
├── PROJECT_MASTER_CONTEXT.md  ← this file
├── TODO.md
├── AGENTS.md                  ← AI startup instructions
├── pyproject.toml
├── .env                       ← API keys (never commit)
└── requirements.txt
```

---

## 4. Runtime Flow

### Single cycle (run_once)

```
cycle_number = _cycle_count + 1

1. FETCHING_DATA
   get_market_state(settings)
     → ccxt fetch OHLCV (240 candles, 1h) from Binance futures
     → compute indicators: RSI-14, ATR-14, Bollinger, volume, funding rate, OI
     → classify market regime (TRENDING_UP / TRENDING_DOWN / RANGING / VOLATILE)
     → save frozen MarketSnapshot to DB

2. MANAGING_POSITIONS
   risk_engine.run_market_tick(market_state)
     → evaluate pending_orders (PLACE_TRIGGER conditions)
     → apply trailing stop updates
     → check time exits
   position_manager.update_stops_and_targets(current_price)
     → check TP1/TP2 hits, SL hits
     → generate auto-trades (AUTO_CLOSE, AUTO_TP1, etc.)
     → save trades, update positions
     → reflect_on_trade() → AgentMemory.save_lesson()

3. CALLING_AGENTS (per agent: deepseek, qwen, gemini)
   _run_agent_round(agent_id, market_state)
     → check risk_engine.blocks_new_entries(agent_id)  [cooldown]
     → build prompt:
         system_prompt.md + rulebook.md
         + market snapshot (frozen)
         + memory.retrieve_lessons(top_k=5)
         + recent trades
         + open positions
         + equity summary
     → subprocess: openclaw agent --agent <id> --session-id <sid> --message <prompt> --timeout 180
     → read ~/.openclaw/agents/<id>/sessions/<sid>.jsonl for actual model + token usage
     → validate actual_model against configured model (prefix match)
     → parse JSON from raw response → AgentSignal (Pydantic, extra="forbid")
     → rule_engine.validate(signal, market_state, positions)
     → if ACCEPTED: paper_execution.execute(signal)
     → save SignalRecord to DB (accepted/rejected, all metadata)
     → save ApiRequestRecord (tokens, cost, latency)

4. POST_PROCESSING
   _persist_daily_metrics()
   shared_learning.promote_lessons()
   shared_learning.analyze_diversity()

5. WRITING_OUTPUTS
   write SIGNALS.md, LEDGER.csv, EVALUATION.md
   _save_benchmark() (BTC buy-and-hold)

6. CHECKPOINTING
   _save_checkpoint() → checkpoints table + state/checkpoints/latest.json
   _cycle_count += 1

7. WAITING
   _mark_runner_state(WAITING, next_cycle_at=now+3600)
   _cloud_update_after_cycle()
     → export_dashboard_snapshot()
     → write cloud/dashboard_snapshot.json
     → git push main (if min_push_interval elapsed)
   _process_cycle_boundary_updates()
     → check for pending CONFIG_RELOAD / PROMPT_UPDATE / CODE_RESTART / ROLLBACK
   _sleep_with_position_monitor(3600)
     → wakes every 15s to check position hits during the wait
```

### Startup sequence (`run-live --resume`)

```
1. load_settings() from config/settings.yaml
2. _apply_settings() → wire up all subsystems
3. _sync_openclaw_system_prompt_overrides()
4. run_preflight() → check exchange connectivity, disk space, etc.
5. _cycle_count = max(
       restore_from_checkpoint(DB latest checkpoint),
       file_checkpoint.cycle_number
   )
6. ensure_competition_started() → read/create competition start time
7. enter while-True loop → run_once() → sleep(3600) → repeat
```

### Kill switch

Create file `KILL_SWITCH` at project root → runner exits cleanly after current cycle completes.

---

## 5. AI System Design

### Agents

| Agent ID | Name | Provider | Model | Base URL | API Key Env |
|---|---|---|---|---|---|
| `crypto-deepseek` | Crypto DeepSeek | `deepseek` | `deepseek-v4-flash` | (default DeepSeek) | `DEEPSEEK_API_KEY` |
| `crypto-qwen` | Crypto Qwen | `openai` | `qwen3-max` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `QWEN_API_KEY` |
| `crypto-gemini` | Crypto Gemini | `openai` | `gemini-3.5-flash` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `GEMINI_API_KEY` |

All three agents:
- Use `LLM_ALLOW_FALLBACK: false` — no automatic model switching ever
- Have `system_prompt_override: "You are a crypto paper trading analyst. Output only valid JSON signals."` (15 tokens vs 7,054 default; overrides OpenClaw's verbose system prompt)
- Get a fresh `session_id` each cycle (prevents conversation history accumulation)

### OpenClaw Gateway

- Node.js CLI tool at the OS level (`openclaw` command in PATH)
- Python calls it via `subprocess.run(["openclaw", "agent", "--agent", agent_id, "--session-id", sid, "--message", prompt, "--timeout", "180"])`
- OpenClaw manages API routing, retries, and writes a session JSONL to `~/.openclaw/agents/<id>/sessions/<sid>.jsonl`
- The JSONL file is the only place to get actual model name and token usage
- OpenClaw config file: `~/.openclaw/config.json` (agent list, system prompt overrides)

### Model verification

After each OpenClaw call:
- `_latest_session_model()` reads the JSONL to find `model` field from the last assistant message
- `_model_is_compatible(actual, configured)` does prefix match: `qwen3-max-2026-01-23` matches configured `qwen3-max`
- If mismatch: logs a warning and records as anomaly in `ApiRequestRecord.anomaly_flags_json`
- Missing JSONL = no contradictory evidence (treated as OK, not an error)

### API Failover

Each agent has an explicit `api_failover.fallback_chain`:
- `crypto-deepseek` → falls back to `qwen3-max` via DashScope
- `crypto-qwen` → falls back to `deepseek-v4-flash`
- `crypto-gemini` → no fallover (`api_failover.enabled: false`)

Failover state persisted in `agent_failover_state` table. Primary retested every `retest_interval_seconds: 3600`.

### Signal format

Agents must output **only** a JSON object conforming to `AgentSignal` (Pydantic, `extra="forbid"`):

```json
{
  "decision": "PAPER_TRADE",
  "action": "OPEN",
  "direction": "LONG",
  "confidence": 0.72,
  "leverage": 5,
  "margin_used_usdt": 500,
  "entry": 67500,
  "stop_loss": 66000,
  "take_profit_1": 69500,
  "take_profit_2": 71000,
  "account_risk_usdt": 100,
  "thesis": "...",
  "invalidation": "...",
  "counterargument": "...",
  "structured_lesson": {
    "what_happened": "...",
    "why": "...",
    "lesson": "...",
    "follow_or_avoid": "follow",
    "regime": "TRENDING_UP",
    "direction": "LONG",
    "setup_type": "breakout"
  }
}
```

`structured_lesson` is **required** in the signal for any CLOSE or CUT action. For OPEN it is optional but encouraged. For HOLD/NO_TRADE it is optional.

Valid `action` values: `OPEN`, `ADD`, `DCA`, `REDUCE`, `CUT`, `CLOSE`, `HOLD`, `NO_TRADE`, `PLACE_TRIGGER`

`PLACE_TRIGGER` requires an additional `trigger_order` field with entry conditions and execution payload (used for conditional entry orders).

### Prompt construction

Each cycle's prompt includes:
1. System prompt (`prompts/system_prompt.md`) — continuous mode preamble, risk math, structured_lesson schema
2. Rulebook (`config/rulebook.md`) — trading rules
3. Market snapshot — OHLCV summary, indicators, regime, funding rate, OI
4. Agent memory — top-5 structured lessons (3-factor scored)
5. Recent trades — last N closed trades for context
6. Open positions — current positions with PnL
7. Equity summary — current equity, daily P&L, weekly performance

---

## 6. Memory & State Management

### Structured lessons (primary)

- Written by agent on CLOSE/CUT via `structured_lesson` JSON in signal
- Also written automatically by `_save_auto_trade_lesson()` when a stop/target hit triggers a position close
- Stored in `structured_lessons` table
- Retrieved with 3-factor scoring:
  - `0.3 × recency` (exponential decay, half-life ≈ 10 cycles)
  - `0.4 × relevance` (regime + direction match)
  - `0.3 × importance` (`min(1.0, abs(pnl_pct) × 10)`)
- Each agent only retrieves its own lessons (private memory)

### Legacy lessons (secondary)

- `lessons` table: per-agent, free-text, with canonical fields (summary, category, sentiment, confidence, impact)
- `shared_lessons` table: cross-agent, promoted from private lessons that meet quality thresholds
- Promotion criteria: `min_sample_size: 10`, `min_win_rate: 0.40`, `min_profit_factor: 1.5`
- Agent sees `private_ratio: 0.70` of its own lessons + `shared_ratio: 0.30` from shared pool

### Diversity monitoring

- `diversity_metrics` table: tracks agreement rate, leverage similarity, confidence correlation across agents
- `convergence_warning` flag triggers `reduced_shared_ratio: 0.10` to reduce cross-contamination
- `shared_learning.analyze_diversity()` called each cycle

### Checkpoints

- `checkpoints` table: each cycle writes a row with `cycle_number` and full state JSON
- `state/checkpoints/latest.json`: mirror of the latest checkpoint, used to speed up `--resume`
- On `--resume`: `_cycle_count = max(DB max cycle, file cycle)` — SQLite is canonical

### runner_state (single row)

- `runner_state` table has `id=1` always (single row, upserted)
- Fields: `status` (RUNNING/ERROR), `phase` (FETCHING_DATA/CALLING_DEEPSEEK/WAITING/etc.), `cycle_number`, `next_cycle_at`, `message`
- Dashboard reads this to show TRADING vs OVERDUE
- OVERDUE = `next_cycle_at` is more than `poll_interval_seconds` in the past
- **Critical**: Only one runner should ever write this table. Two independent runners cause race conditions and false OVERDUE.

---

## 7. Database & Storage

**File:** `database/arena.db` (SQLite)
**Connection:** `sqlite:///database/arena.db` (relative to project root)
**ORM:** SQLAlchemy 2.0 with `mapped_column` / `Mapped` type annotations (in `src/storage/models.py`)

### Complete table inventory

| Table | Purpose | Key columns |
|---|---|---|
| `agents` | Agent registry | id, name, model |
| `signals` | Every agent signal (accepted + rejected) | cycle_number, agent_id, decision, action, accepted, signal_status, rejection_reason_code |
| `positions` | Open/closed positions | agent_id, direction, status, leverage, margin, stop_loss, tp1, tp2 |
| `trades` | Individual fills | agent_id, position_id, action, entry, exit_price, realized_pnl |
| `checkpoints` | Per-cycle state snapshots | cycle_number, status, payload_json |
| `runner_state` | Single-row runner heartbeat | id=1, phase, next_cycle_at, status |
| `api_requests` | LLM call records | cycle_number, agent_name, model_name, actual_model_name, tokens, cost, latency |
| `market_snapshots` | Frozen market data per cycle | symbol, current_price, payload_json |
| `lessons` | Per-agent private lessons | agent_id, summary, category, sentiment, confidence, impact |
| `shared_lessons` | Cross-agent promoted lessons | source_agent, win_rate, profit_factor, sample_size |
| `structured_lessons` | Structured lesson JSON | agent_id, regime, direction, follow_or_avoid, realized_pnl_pct |
| `pending_orders` | Conditional entry orders (PLACE_TRIGGER) | agent_id, status, expires_at, trigger_json, execution_signal_json |
| `position_risk_state` | Per-position automation state | position_id, state_json (trailing_active, break_even_applied), config_json |
| `cooldown_state` | Per-agent cooldown periods | agent_id, active, ends_at, reason |
| `api_failover_events` | Failover log | agent_id, event_type, from/to provider+model |
| `agent_failover_state` | Current failover status per agent | agent_id, using_fallback, active_provider, active_model |
| `risk_notifications` | Risk event alerts | agent_id, event_type, severity, message |
| `workload_cycles` | Per-cycle compute/API stats | deepseek/qwen/gemini tokens, costs, latencies |
| `workload_components` | Granular workload breakdowns | cycle_id, owner, category, metric_name, metric_value |
| `daily_metrics` | Daily equity/PnL per agent | agent_id, day, equity, realized_pnl, max_drawdown |
| `diversity_metrics` | Cross-agent strategy divergence | agreement_rate, convergence_warning |
| `health_checks` | Preflight/resume check log | component, status, critical, message |
| `config_versions` | Config change audit trail | version_hash, source, active, payload_json |
| `downtime_events` | Runner downtime periods | started_at, ended_at, duration_seconds |
| `benchmarks` | BTC buy-and-hold reference | benchmark_name, start_price, return_pct |
| `competition_results` | Final results (if competition ends) | winner_agent_id |
| `control_commands` | Queued operational commands | command, status, payload_json |
| `reflections` | Agent reflection text | agent_id, content |
| `lesson_promotions` | Promotion audit log | source_agent, status, reason |
| `strategy_profiles` | Agent strategy summaries | agent_id, profile_json |
| `prompt_versions` | Prompt hash audit | prompt_hash, system_prompt_hash, rulebook_hash |

### Migration strategy

Schema migrations run automatically on every startup via `_migrate_sqlite()` in `models.py`. It uses `PRAGMA table_info()` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` — safe for additive changes. For data migrations, write standalone Python scripts in the project root, run manually, never automate destructive updates.

---

## 8. APIs & Integrations

### Binance (market data, read-only)

- Via `ccxt` library, exchange: `binanceusdm` (USDT-margined futures)
- `sandbox: false` — real market data, simulated trades only
- Fetches: OHLCV (240 × 1h candles), funding rate, open interest
- Timeout: `api.timeout_seconds: 180`, retries: `api.max_retries: 1`
- No Binance API key required for public market data

### DeepSeek LLM

- Provider: `deepseek` (native DeepSeek SDK via OpenClaw)
- Model: `deepseek-v4-flash`
- API key: `DEEPSEEK_API_KEY` in `.env`
- Failover → Qwen via DashScope

### Qwen / DashScope LLM

- Provider: `openai` (OpenAI-compatible endpoint)
- Model: `qwen3-max`
- Base URL: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
- API key: `QWEN_API_KEY` in `.env`
- Failover → DeepSeek

### Gemini / Google LLM

- Provider: `openai` (OpenAI-compatible endpoint)
- Model: `gemini-3.5-flash`
- Base URL: `https://generativelanguage.googleapis.com/v1beta/openai/`
- API key: `GEMINI_API_KEY` in `.env`
- No failover configured
- **Current status: HTTP 401 every cycle — needs investigation**

### GitHub (snapshot sync)

- `git push` after each cycle (if `min_push_interval_seconds: 300` elapsed)
- Branch: `main`
- Only pushes `cloud/dashboard_snapshot.json`
- No secrets in snapshot (validated before push)

### Render.com (read-only dashboard)

- Web service reads `cloud/dashboard_snapshot.json` from GitHub
- No runner, no DB, no API keys
- Shows STALE warning after 15 min, CRITICAL after 60 min with no update

---

## 9. Configuration System

### Primary config: `config/settings.yaml`

Loaded at startup by `load_settings()` → `Settings` Pydantic model. Key sections:

```yaml
competition:
  duration_days: 0           # 0 = continuous mode (no end date)
  weekly_target_pct: 0.07    # soft KPI, never forces trades
  poll_interval_seconds: 3600 # 1 hour between cycles

accounts:
  initial_equity: 10000.0

risk:
  max_leverage: 10.0
  max_margin_per_action_pct: 0.10   # 10% of equity per OPEN/ADD/DCA
  max_total_account_risk_pct: 0.02  # 2% total account risk across all positions
  max_open_positions: 3
  max_dca_per_position: 2
  daily_loss_limit_pct: 0.03

risk_automation:
  break_even:
    apply_by_default: true
    trigger: r_multiple
    r_multiple: 1.0              # move SL to break-even when +1R profit
  cooldown:
    consecutive_losses: 3
    pause_hours_after_losses: 1.1
    daily_loss_pct: 0.05
    pause_hours_daily: 24.0

api:
  timeout_seconds: 180
  max_retries: 1

execution:
  taker_fee_rate: 0.0005
  slippage_bps: 2.0
```

### Hot-reload

These files can be changed while runner is running; changes take effect at next cycle boundary:
- `config/settings.yaml` → CONFIG_RELOAD update type
- `config/rulebook.md` → RULEBOOK_UPDATE update type
- `prompts/system_prompt.md` → PROMPT_UPDATE update type

Python source changes (`.py` files) require a CODE_RESTART update or manual runner restart.

### Environment variables (`.env`)

```
DEEPSEEK_API_KEY=...
QWEN_API_KEY=...
GEMINI_API_KEY=...
ARENA_DATABASE_URL=sqlite:///database/arena.db  # optional override
```

Never commit `.env`. The `load_settings()` function calls `load_dotenv()` automatically.

### Pydantic enforcement

`LlmLockSettings` validates at parse time:
- `LLM_MODEL` must be non-empty and not an alias ("auto", "default", "latest", "best")
- `LLM_ALLOW_FALLBACK: false` is enforced — raising a `ValueError` if `true`

This means you cannot accidentally enable model fallback by editing the YAML.

---

## 10. Deployment & Infrastructure

### Local runner

```powershell
cd crypto-paper-trading-arena
.\.venv\Scripts\python.exe -m src.cli run-live --resume
```

**Critical rules:**
- Always use `--resume` to restore cycle counter from checkpoint
- Only run ONE runner process tree at a time. Two runners cause `runner_state` race conditions and dashboard showing OVERDUE.
- To verify: `Get-Process python | Select-Object Id, CommandLine` — should see exactly 1 python.exe running `run-live`
- To stop: create `KILL_SWITCH` file at project root → runner exits after current cycle

### Virtual environment

```powershell
cd crypto-paper-trading-arena
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

### Preflight check

On every `run-live` startup, `run_preflight()` validates:
- Exchange connectivity (Binance market data)
- Disk space (>500 MB free)
- Database accessibility
- OpenClaw gateway reachable

If exchange connectivity fails, runner retries indefinitely (60s intervals). Other critical failures block startup.

### CLI commands

```powershell
python -m src.cli run-live --resume     # start/resume runner
python -m src.cli run-once              # single cycle, then exit
python -m src.cli validate-update --no-smoke  # validate config+code
python -m src.cli init                  # initialize/re-initialize DB and OpenClaw agents
python -m src.cli reset-failover <agent-id>  # reset failover state
python -m src.cli export-snapshot       # manually push dashboard snapshot
python -m src.cli show-state            # show runner_state row
python -m src.cli show-checkpoint       # show latest checkpoint
```

### Render deployment

- Service type: web service (free tier)
- Build command: `pip install -r requirements.txt` (or similar)
- Start command: `python -m src.cli serve-dashboard` (or equivalent)
- Environment: no API keys, no DB, reads only from GitHub snapshot URL
- **Never add a runner to the Render deployment** — paper trading must run locally only

---

## 11. Observability & Debugging

### Logs

- `loguru` logger configured in `src/logger.py`
- Runtime logs written to `logs/` directory (not committed)
- `SESSION_UPDATES.md` is the human-readable implementation log (committed)

### Dashboard

The cloud dashboard at Render shows:
1. **Overview** — competition status, cycle count, leader, BTC price
2. **Leaderboard** — equity, PnL, win rate per agent
3. **Positions** — open positions with unrealized PnL
4. **Trades** — recent trade history
5. **Signals** — accepted/rejected signal log
6. **Equity Curves** — per-agent equity over time
7. **Drawdown** — max drawdown curves
8. **Risk Automation** — pending orders, cooldowns, trailing stops
9. **Token Usage** — API cost and latency per agent
10. **API Costs** — cumulative cost breakdown
11. **Signal Audit** — signal acceptance rate analysis
12. **Rejected Signals** — rejection reason breakdown
13. **Market** — market regime, price context
14. **Workload** — compute time breakdown
15. **Downtime** — missed cycles log
16. **Strategy Diversity** — cross-agent divergence metrics
17. **Deployment** — config version, last push, update queue
18. **Lessons** — structured lesson analytics
19. **Lessons to Avoid** — negative lessons

**IMPORTANT:** `DASHBOARD_TAB_LABELS` tuple (19 items) in `src/dashboard/contract.py` must match exactly between local and Render. Tested by `tests/test_dashboard_contract.py`. Never add/remove/rename tabs without updating both.

### Runner health

```powershell
# Check if runner is alive
Get-Process python | Select-Object Id

# Check runner_state in DB
python -m src.cli show-state

# Check latest checkpoint
python -m src.cli show-checkpoint

# Manual snapshot export
python -m src.cli export-snapshot
```

### OVERDUE diagnosis checklist

1. Is the runner process alive? → `Get-Process python`
2. Is it a single runner or duplicate? → check PIDs and parent PIDs
3. What does `runner_state` show? → `python -m src.cli show-state`
4. What is `next_cycle_at`? If far in the past → runner crashed during sleep
5. What was the last error in logs?
6. Is OpenClaw responding? → `openclaw agent --agent crypto-deepseek --message "test" --timeout 10`

---

## 12. Important Workflows

### Restart runner safely

```powershell
# 1. Create kill switch to stop current runner gracefully
New-Item -ItemType File -Path crypto-paper-trading-arena\KILL_SWITCH -Force

# 2. Wait for runner to exit (it finishes current cycle first)
# Watch logs or check: Get-Process python

# 3. Remove kill switch
Remove-Item crypto-paper-trading-arena\KILL_SWITCH

# 4. Restart with --resume
cd crypto-paper-trading-arena
.\.venv\Scripts\python.exe -m src.cli run-live --resume
```

### Add a new agent

1. Add entry to `agents:` list in `config/settings.yaml`
2. Add `LLM_API_KEY` to `.env`
3. Run `python -m src.cli init` to register agent in DB and OpenClaw
4. Restart runner (kill switch → resume)
5. Update `WorkloadCycleRecord` in `src/storage/models.py` if you need per-agent workload columns

### Update system prompt

1. Edit `prompts/system_prompt.md`
2. Insert PROMPT_UPDATE via `control_commands` table OR restart runner
3. With hot-reload enabled, change is picked up at next cycle boundary automatically

### Roll back config

```powershell
# Insert ROLLBACK command into control_commands
python -m src.cli rollback --backup-path <path>
```

Or manually: restore `config/settings.yaml` from backup in `state/backups/`, then restart runner.

### Manual DB migration

Write a standalone Python script in project root. Use SQLite UPDATE statements directly:

```python
import sqlite3
conn = sqlite3.connect("database/arena.db")
# make changes
conn.commit()
conn.close()
```

**Never use destructive SQL (DROP, DELETE) without a backup.** Always validate with `SELECT COUNT(*)` before and after.

### Post-task mandatory workflow

After every implementation task:
1. Append to `logs/SESSION_UPDATES.md` (date, title, problem, root cause, files, details, validation, deployment notes)
2. Run: `cd crypto-paper-trading-arena && .\.venv\Scripts\python.exe -m pytest -q`
3. Run: `.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke`
4. If tests pass: `git -C crypto-paper-trading-arena add <specific files>`
5. `git -C crypto-paper-trading-arena commit -m "<message>"`
6. `git -C crypto-paper-trading-arena push`

---

## 13. Coding Standards & Patterns

### Python style

- All new files: `from __future__ import annotations` at the top
- Type hints everywhere (Python 3.12+)
- `loguru` for all logging (`from src.logger import logger`)
- Pydantic v2 for all data models (`BaseModel`, `model_validator`, `Field`)
- SQLAlchemy 2.0 ORM style (`Mapped[T]`, `mapped_column`)
- `pathlib.Path` for all file operations, never `os.path`
- UTC everywhere: `datetime.now(UTC)`, never `datetime.utcnow()`

### Error handling philosophy

- Risk automation failures are non-fatal: wrap in `try/except Exception` and log warning, trading continues
- LLM call failures: retry up to `max_retries: 1`, then log and skip agent for that cycle
- Market data failures: preflight catches them; during live loop, exception is caught, state marked ERROR, runner waits and retries next cycle
- Never use `except:` (bare), always `except Exception`

### No real trading

- Never add real exchange order execution methods
- `PaperExecutionEngine` is the only execution path
- Fee simulation: `taker_fee_rate: 0.0005`, slippage: `2.0 bps`

### Schema validation

- `AgentSignal` uses `model_config = ConfigDict(extra="forbid")` — any extra fields in agent JSON cause rejection
- Signals are validated through `rule_engine.validate()` before execution
- Rule violations are logged with a rejection reason code (LEVERAGE_LIMIT_EXCEEDED, RISK_LIMIT_EXCEEDED, etc.)

### Test coverage requirements

- Dashboard contract tests (`tests/test_dashboard_contract.py`) must pass before any commit
- Run full test suite with: `.\.venv\Scripts\python.exe -m pytest -q`
- Never skip failing tests — fix the underlying issue

### Commit discipline

- Never commit: `outputs/`, `.env`, `database/arena.db`, `state/`, `logs/` (except SESSION_UPDATES.md)
- Always commit: `src/`, `tests/`, `config/`, `prompts/`, `PROJECT_*.md`, `TODO.md`
- Use `git -C crypto-paper-trading-arena add <specific files>` — never `git add -A`

---

## 14. Known Problems / Technical Debt

### Active issues

1. **Gemini HTTP 401 each cycle** — `GEMINI_API_KEY` may be invalid or expired for `gemini-3.5-flash` at `generativelanguage.googleapis.com/v1beta/openai/`. Investigate key validity and endpoint compatibility. Gemini has no failover configured.

2. **Qwen auth profile** — After reinstating `crypto-qwen`, OpenClaw may need `python -m src.cli init` to re-register the agent profile with correct API key. If 403 errors appear, run init and check `.env` for `QWEN_API_KEY`.

3. **rulebook.md references `crypto-challenger`** — The rulebook still mentions `crypto-challenger` (a removed placeholder agent). The agent list in `settings.yaml` is correct (3 agents), but the rulebook should be updated to list the actual 3 agents. This is cosmetic but creates confusion for new engineers reading the rulebook.

4. **WorkloadCycleRecord has hardcoded `grok_*` columns** — These were for a previously active agent (crypto-grok/xAI). The columns remain in the schema for backward compatibility but new agent `crypto-qwen` maps to them. This is a naming inconsistency.

### Technical debt

- `_backfill_lesson_canonical_columns()` and `_backfill_signal_audit_columns()` in `models.py` run on every startup (limited to 5000 rows each). With a large DB this adds startup latency. Should be run once and then disabled.
- `WorldModel` and `Calibration` analytics modules exist (`src/analytics/`) but their integration into the prompt context is partial.
- `advanced_risk_model: false` in features — this flag exists but the advanced model is not yet implemented.
- `canary.enabled: false` — canary deployment infrastructure exists but is unused.
- Session JSONL path hardcoded to `~/.openclaw/agents/<id>/sessions/<sid>.jsonl` — if OpenClaw changes its storage layout, model verification silently breaks.

---

## 15. Future Roadmap & Planned Features

_(Based on TODO.md and feature_flags in settings.yaml)_

- **Advanced risk model** (`features.advanced_risk_model: false`) — more sophisticated position sizing based on regime and win-rate calibration data from `WorldModel`
- **Canary deployment** (`canary.enabled: false`) — route a subset of cycles to an experimental agent before full rollout
- **Multi-symbol support** — current architecture hardcodes `BTC/USDT:USDT`; extending to ETH or other assets would require significant refactoring of the market snapshot and signal schemas
- **Referee agent** — `prompts/referee_prompt.md` exists for a meta-agent that evaluates agent quality; not yet wired into the runner
- **Reflection prompt** — `prompts/reflection_prompt.md` exists; partially wired into `reflect_on_trade()` but uses a lightweight local heuristic, not a full LLM call
- **Portfolio mode** — currently each agent manages an independent account; a portfolio view aggregating all agents is a planned dashboard feature

---

## 16. How To Continue Development Safely

### Before making any change

1. Read `PROJECT_BOOTSTRAP.md` for current system state
2. Check bottom of `logs/SESSION_UPDATES.md` for recent changes
3. Run tests: `.\.venv\Scripts\python.exe -m pytest -q`
4. Verify runner is alive and healthy: `python -m src.cli show-state`

### Pre-implementation analysis (MANDATORY per CLAUDE.md)

Before touching any file, write out:
1. Problem in plain language
2. Root cause
3. Files that will change and why
4. Step-by-step plan
5. Why the fix is safe and unlikely to cause regressions
6. What will be observably different after

### High-risk areas (extra care required)

| Area | Risk | Mitigation |
|---|---|---|
| `src/storage/models.py` — `_migrate_sqlite()` | Additive migrations only; destructive changes corrupt DB | Always test with a copy of arena.db first |
| `runner_state` table | Single row; concurrent writes from 2 runners corrupt state | Kill old runner before starting new one |
| `state/checkpoints/latest.json` | Cycle counter source; wrong value causes wrong `--resume` | Read DB directly to verify: `SELECT MAX(cycle_number) FROM checkpoints` |
| `src/dashboard/contract.py` — tab labels | Render and local must match exactly | Run `pytest tests/test_dashboard_contract.py` after any change |
| `config/settings.yaml` — `agents` list | Agent removal can orphan DB records; agent addition needs `init` | Add only, never remove; run `init` after adding |
| `prompts/system_prompt.md` | All 3 agents use this; bad prompt = 0 valid signals per cycle | Test with `run-once` before committing |
| `.env` | Contains API keys; must never be committed | Check `git status` carefully before staging |

### Safe development flow

```powershell
# 1. Make code changes
# 2. Run tests
cd crypto-paper-trading-arena
.\.venv\Scripts\python.exe -m pytest -q

# 3. Validate config
.\.venv\Scripts\python.exe -m src.cli validate-update --no-smoke

# 4. For prompt/rulebook/config changes: test with single cycle
.\.venv\Scripts\python.exe -m src.cli run-once

# 5. Restart runner (if code changes)
New-Item -ItemType File -Path KILL_SWITCH -Force
# wait for exit
Remove-Item KILL_SWITCH
.\.venv\Scripts\python.exe -m src.cli run-live --resume

# 6. Commit and push
git -C . add <specific files>
git -C . commit -m "..."
git -C . push
```

---

## 17. Full Dependency Analysis

### Python package dependencies

| Package | Role |
|---|---|
| `pydantic>=2.0` | All data models, settings validation, signal validation |
| `sqlalchemy>=2.0` | ORM + migrations for `arena.db` |
| `ccxt` | Binance market data (OHLCV, funding rate, OI) |
| `loguru` | Structured logging |
| `python-dotenv` | `.env` loading |
| `pyyaml` | `settings.yaml` parsing |
| `pandas` | Equity curve and analytics computations |
| `numpy` | Numerical computations in analytics |
| `click` | CLI commands in `src/cli.py` |
| `httpx` or `requests` | HTTP calls (for any direct API calls beyond ccxt) |
| `pytest` | Test runner |

### External service dependencies

| Service | Type | Required | Fallback |
|---|---|---|---|
| Binance (binanceusdm) | Market data | Yes — runner blocks without it | Preflight retries 60s intervals |
| DeepSeek API | LLM | Yes for crypto-deepseek | Falls back to Qwen via DashScope |
| DashScope (Qwen) | LLM | Yes for crypto-qwen | Falls back to DeepSeek |
| Google AI (Gemini) | LLM | Yes for crypto-gemini | No fallback configured |
| OpenClaw (Node.js) | LLM gateway | Yes — all LLM calls go through it | No fallback (must be in PATH) |
| GitHub | Snapshot sync | No — dashboard goes stale | Shows STALE warning, trading continues |
| Render.com | Dashboard | No — local runner is independent | Dashboard shows nothing |

### Internal module dependencies (key paths)

```
src/cli.py
  → src/competition/runner.py (CompetitionRunner)
    → src/config.py (Settings)
    → src/storage/repository.py (ArenaRepository)
      → src/storage/models.py (all ORM models)
    → src/market/*.py (get_market_state)
    → src/agents/base_agent.py (OpenClawAgent)
      → subprocess: openclaw CLI
    → src/agents/memory.py (AgentMemory)
    → src/trading/execution.py (PaperExecutionEngine)
    → src/trading/position_manager.py (PositionManager)
    → src/trading/risk_automation/engine.py (RiskAutomationEngine)
    → src/validation/rule_engine.py
    → src/cloud/snapshot_exporter.py
      → src/competition/evaluation.py
      → src/analytics/*.py
    → src/operations/update_manager.py (LiveUpdateManager)
    → src/operations/config_manager.py
```

---

## 18. Glossary

| Term | Definition |
|---|---|
| **Arena** | The overall system: competition + agents + runner |
| **Cycle** | One full iteration: fetch data → call agents → execute → checkpoint (1 hour) |
| **Agent** | An LLM-backed trading analyst identified by `agent_id` (e.g., `crypto-deepseek`) |
| **OpenClaw** | Node.js CLI gateway that routes LLM API calls; called via subprocess by Python |
| **Session ID** | Fresh UUID per cycle passed to OpenClaw; prevents conversation history buildup |
| **Frozen snapshot** | Market data captured once per cycle; all agents see the same data for fairness |
| **AgentSignal** | Pydantic model for the JSON trading signal an agent outputs |
| **PLACE_TRIGGER** | Signal action that places a conditional order (executes when price condition is met) |
| **structured_lesson** | JSON object in a signal (or auto-generated) capturing what happened, why, and the lesson |
| **Runner state** | Single DB row tracking current phase (FETCHING_DATA, WAITING, etc.) and next cycle time |
| **OVERDUE** | Dashboard state when `next_cycle_at` is more than `poll_interval_seconds` in the past |
| **Break-even stop** | Automatically moves SL to entry price when +1R profit is reached |
| **Trailing stop** | Follows price up (for LONG) or down (for SHORT) by a fixed distance |
| **Cooldown** | Temporary pause on new entries for an agent after N consecutive losses or daily loss limit |
| **DCA** | Dollar Cost Average — adding to an existing losing position |
| **R-multiple** | Risk unit: 1R = distance from entry to stop loss × position size. +1R means the trade earned one risk unit |
| **Regime** | Market classification: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE |
| **latest.json** | Secondary checkpoint file at `state/checkpoints/latest.json`; mirrors DB checkpoint |
| **Kill switch** | File named `KILL_SWITCH` at project root; causes runner to exit cleanly after current cycle |
| **Hot reload** | Configuration/prompt changes picked up at cycle boundaries without restarting Python |
| **Shared lessons** | Cross-agent lessons promoted from private lessons meeting quality thresholds |
| **Diversity metrics** | Measures how different the agents' strategies are (prevents groupthink) |
| **Leaderboard** | Ranking of agents by equity and risk-adjusted PnL |
| **Benchmark** | BTC buy-and-hold from competition start, used to compare agent performance |
| **Snapshot** | `cloud/dashboard_snapshot.json` — serialized DB state pushed to GitHub for Render |
| **Render** | Cloud platform hosting the read-only public dashboard; reads only the GitHub snapshot |
| **LLM lock** | Pydantic enforcement that `LLM_ALLOW_FALLBACK: false` and model is an exact ID, not an alias |
