# crypto-paper-trading-arena

Production-oriented paper trading competition platform for two OpenClaw agents trading BTCUSDT perpetual futures in paper mode only.

## Architecture

```text
CCXT public data
      |
      v
Market State + Indicators + Regime + Funding/OI
      |
      v
Prompt Composer ---- Private Agent Memory
      |                         |
      v                         v
OpenClaw crypto-deepseek   OpenClaw crypto-grok
      |                         |
      v                         v
Strict JSON Signal       Strict JSON Signal
      \                         /
       v                       v
        Validation Rule Engine
                 |
        accepted | rejected
                 v
        Paper Trading Engine
                 |
                 v
        SQLite + Outputs + Dashboard
```

## Rulebook

The canonical rules are loaded from [config/rulebook.md](config/rulebook.md). Key constraints:

- Paper trading only
- BTC only
- Starting equity: 10,000 USDT per agent
- Maximum leverage: 10x
- Max margin per OPEN/ADD/DCA: 10% equity
- Max total account risk: 2%
- Max concurrent positions: 3
- Max DCA per position: 2
- Daily loss limit: 3%
- Stop loss and take profit required
- TP1 minimum RR: 1:1.5
- TP2 minimum RR: 1:2.0

Invalid signals are stored and rejected automatically.

## Installation

Install Python 3.11+ first. On Windows, make sure `python --version` prints a real Python version, not the Microsoft Store app alias.

```powershell
cd D:\Project\OpenClaw\crypto-paper-trading-arena
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

OpenClaw agent API keys are normally stored in OpenClaw itself. This project calls:

- `openclaw agent --agent crypto-deepseek ...`
- `openclaw agent --agent crypto-grok ...`

If you set `DEEPSEEK_API_KEY` and `XAI_API_KEY` in `.env`, `python -m src.cli init` writes them into the matching OpenClaw per-agent auth profiles:

- `crypto-deepseek` -> `deepseek:manual`
- `crypto-grok` -> `xai:manual`

If `openclaw` is not in PATH, set:

```env
OPENCLAW_BIN=C:\path\to\openclaw.cmd
```

Main settings are in [config/settings.yaml](config/settings.yaml).

## Run

Initialize database and outputs:

```powershell
python -m src.cli init
```

Run one decision cycle:

```powershell
python -m src.cli run-once
```

Run continuously:

```powershell
python -m src.cli run-live
```

Resume from the latest checkpoint:

```powershell
python -m src.cli run-live --resume
```

Run the dashboard:

```powershell
python -m src.cli dashboard
```

Then open the Streamlit URL shown in the terminal.

## Outputs

- `database/arena.db`: SQLite database
- `outputs/SIGNALS.md`: raw agent outputs and validation status
- `outputs/LEDGER.csv`: trade ledger
- `outputs/EVALUATION.md`: current leaderboard
- `logs/arena.log`: runtime logs

## CLI

```powershell
python -m src.cli init
python -m src.cli preflight-check
python -m src.cli run-once
python -m src.cli run-live
python -m src.cli run-live --resume
python -m src.cli backtest
python -m src.cli evaluate
python -m src.cli reload-config
python -m src.cli queue-prompt-update .\prompts\system_prompt.v002.md
python -m src.cli queue-rulebook-update .\rulebooks\rulebook.v002.md
python -m src.cli validate-update
python -m src.cli safe-restart
python -m src.cli rollback --to previous
python -m src.cli show-versions
python -m src.cli analyze-workload
python -m src.cli workload-report
python -m src.cli dashboard
```

## Production Safeguards

Before live mode, run:

```powershell
python -m src.cli preflight-check
```

`run-live` also performs this preflight automatically when `safety.require_preflight_for_live` is true. Critical failures block live execution. The check verifies API key variables, database connectivity, public market data, rulebook loading, prompt loading, dashboard dependencies, required directories, disk space, and required Python packages.

Live safeguards include:

- frozen market snapshot per cycle, so both agents receive the exact same timestamped data
- OpenClaw timeout and retry with exponential backoff
- automatic JSON repair for common malformed model responses
- simulated taker fees and slippage in paper execution
- buy-and-hold BTC benchmark records
- health check records in SQLite
- prompt version hashing for auditability
- warm-up mode via `safety.warmup_cycles` or `ARENA_WARMUP_MODE=true`
- global kill switch via `ARENA_KILL_SWITCH=true` or a `KILL_SWITCH` file in the project root
- crash-safe checkpoints after every cycle with automatic resume support
- between-cycle position monitoring for automatic paper TP/SL exits without calling agents

Relevant settings live in [config/settings.yaml](config/settings.yaml):

```yaml
api:
  timeout_seconds: 600
  max_retries: 3

execution:
  taker_fee_rate: 0.0005
  slippage_bps: 2.0

safety:
  warmup_cycles: 0
  kill_switch_file: KILL_SWITCH
  require_preflight_for_live: true
  downtime_threshold_seconds: 60
  position_monitor_enabled: true
  position_monitor_interval_seconds: 15
```

During `run-live`, the position monitor runs while the runner is waiting for the next agent cycle. It polls public
ticker price, checks open paper positions against stop loss and take profit levels, applies the same simulated fees and
slippage, records `AUTO_REDUCE`/`AUTO_CLOSE` ledger entries when triggered, writes a monitor checkpoint, and refreshes
dashboard outputs. It never places real orders.

## Live Updates

Live updates are applied only at cycle boundaries, after SQLite state and filesystem checkpoints are written. The update
queue lives at `state/update_queue.json`; filesystem checkpoints are written to `state/checkpoints/latest.json` and
timestamped files under `state/checkpoints/`; backups are written under `state/backups/`.

Supported queue types:

- `CONFIG_RELOAD`: reloads `config/settings.yaml` without restarting.
- `PROMPT_UPDATE`: activates a versioned `prompts/system_prompt.vNNN.md` file for the next cycle.
- `RULEBOOK_UPDATE`: activates a versioned `rulebooks/rulebook.vNNN.md` file for the next cycle.
- `CODE_RESTART`: exits cleanly after a completed cycle so a supervisor or `safe-restart` can resume.
- `ROLLBACK`: restores the latest backup, then restarts with resume.

Useful commands:

```powershell
python -m src.cli validate-update
python -m src.cli show-versions
python -m src.cli queue-prompt-update .\path\to\new_prompt.md --agent crypto-deepseek
python -m src.cli queue-rulebook-update .\path\to\new_rulebook.md
python -m src.cli safe-restart
python -m src.cli rollback --to previous
```

`scripts/watchdog.py` can supervise the local runner and start `run-live --resume` if the process is not running.

## Crash-Safe Resume

The runner writes a checkpoint after every completed cycle. Each checkpoint contains open positions, account summaries, pending watchlists, recent private memories, and the latest market context needed to audit recovery. The canonical state remains in SQLite, so resume detects the latest checkpoint, records downtime if the gap exceeds `safety.downtime_threshold_seconds`, and continues from the persisted database state.

Use:

```powershell
python -m src.cli run-live --resume
```

The dashboard Configuration tab shows crash-safe checkpoints, downtime history, and current uptime since the latest checkpoint.

## Dashboard

The Streamlit dashboard shows:

- current balances
- open positions
- equity curves
- leaderboard inputs
- trade history
- rejected signals
- estimated token usage and API cost
- reflections and lessons
- strategy diversity
- workload attribution across local code, DeepSeek, and Grok

## Local Tool Loop

Agents can either return a final strict JSON signal or request local tools first:

```json
{
  "tool_requests": [
    {"tool": "get_indicators", "arguments": {}},
    {"tool": "calculate_position_size", "arguments": {"equity": 10000, "entry": 100000, "stop_loss": 99000, "leverage": 5, "direction": "LONG"}}
  ]
}
```

The runner executes approved local tools against the same shared market state, logs every tool call, then asks the agent for the final `AgentSignal` JSON.

## Workload Attribution

The arena records workload metrics for every competition cycle in SQLite tables:

- `workload_cycles`: normalized percentage split for Local Machine, DeepSeek, and Grok
- `workload_components`: per-category rows for local tools, validation, database writes, agent latency, token use, cost, reflections, lessons, promotion, and diversity analysis

The local machine normally performs most deterministic work: market data retrieval, indicator calculations, regime detection, local tool execution, vector and SQL retrieval, validation, risk checks, paper execution, database writes, evaluation, lesson promotion, diversity analysis, and dashboard generation. The agents focus on strategic reasoning: reading the prompt, deciding whether to request tools, producing a JSON signal, and generating lessons through reflection.

The dashboard tab **Workload Attribution** shows:

- current workload split
- historical workload percentages
- token trends
- latency trends
- API cost trends
- per-cycle and per-category breakdowns

The composite workload score is normalized so Local Machine + DeepSeek + Grok always sums to 100%:

```text
workload_score =
0.40 * wall_time_share
+ 0.25 * token_share
+ 0.20 * decision_share
+ 0.10 * reflection_share
+ 0.05 * lesson_share
```

Decision share starts from the architecture prior: local deterministic infrastructure 85%, DeepSeek 7.5%, Grok 7.5%, then adjusts for tool requests and local deterministic work. A healthy run should usually show Local Machine around 80-95%, with agents concentrated in high-value reasoning.

Use:

```powershell
python -m src.cli analyze-workload
python -m src.cli workload-report
```

## Cloud Dashboard with GitHub and Render

The trading engine can keep running on the local machine while Render hosts a read-only Streamlit dashboard from the latest GitHub snapshot.

```text
Local machine -> cloud/dashboard_snapshot.json -> GitHub -> Render -> browser/mobile
```

Local responsibilities stay unchanged: the runner, OpenClaw agents, paper execution, SQLite database, memory, reflections, and checkpoints continue to live on the local machine. After each completed cycle the runner exports a compact, non-secret dashboard snapshot to `cloud/dashboard_snapshot.json`. If `cloud_dashboard.git_auto_push` and `cloud_dashboard.push_after_each_cycle` are enabled, the runner commits and pushes that snapshot to GitHub. Git failures are logged and never stop trading.

Render hosts only Streamlit. When `cloud/dashboard_snapshot.json` exists, the dashboard reads that file and does not require SQLite, local logs, agent keys, or the local machine to be online. It shows the last sync timestamp and warns when the snapshot is older than 15 minutes or 60 minutes.

### GitHub Setup

1. Create a GitHub repository for this project.
2. Commit the project files, including `render.yaml`, `Procfile`, and the generated `cloud/dashboard_snapshot.json`.
3. Configure the local repo:

```powershell
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git branch -M main
git push -u origin main
```

4. Keep `.env` private. It is gitignored and must never be committed.

### Render Deployment

1. Create a Render account.
2. Connect the GitHub repository.
3. Create a Web Service from the repository.
4. Render uses Python `3.11.11` from the `PYTHON_VERSION` value in `render.yaml`. The repository also includes `.python-version` with `3.11.11` and `runtime.txt` with `python-3.11.11` as fallback markers. Keep `pyproject.toml` at `requires-python = ">=3.11"` so package metadata matches Render's runtime.
5. Render uses:
   - Build command: `pip install -r requirements.txt`
   - Start command: `streamlit run src/dashboard/app.py --server.port $PORT --server.address 0.0.0.0`
6. Auto-deploy stays enabled, so each snapshot push redeploys the dashboard.
7. Open the remote dashboard at:

```text
https://your-app-name.onrender.com
```

### Snapshot and Sync Commands

Export only:

```powershell
python -m src.cli export-snapshot
```

Commit and push an existing snapshot:

```powershell
python -m src.cli sync-github
```

Export, commit, and push:

```powershell
python -m src.cli cloud-update
```

Check deployment readiness:

```powershell
python -m src.cli deploy-check
```

Use `--skip-render` with `sync-github` or `cloud-update` only when you intentionally want the commit message `dashboard snapshot update [skip render]`.

### How Snapshot Syncing Works

Configuration lives in `config/settings.yaml`:

```yaml
cloud_dashboard:
  enabled: true
  snapshot_path: cloud/dashboard_snapshot.json
  git_auto_push: true
  git_branch: main
  push_after_each_cycle: true
  min_push_interval_seconds: 300
  render_enabled: true
```

The snapshot contains operational dashboard data only: system status, competition status, BTC price, account summaries, open positions, recent trades, equity and drawdown curves, leaderboard, workload attribution, token usage, API costs, rejected signal summaries, reflections summaries, strategy diversity metrics, and sync metadata. It does not contain provider API keys or `.env` values.

## Testing

```powershell
pytest --cov=src
```

The test suite covers PnL, signal parsing, validation, paper execution, tools, repository, memory, shared learning, workload attribution, metrics, and a runner integration flow with mocked OpenClaw calls. Coverage is configured to target at least 80% of core non-UI logic.

## Troubleshooting

`python` opens Microsoft Store:

- Install Python 3.11+ from python.org.
- Disable Windows App Execution Alias for Python.

OpenClaw call fails:

- Run `openclaw agents list`.
- Confirm `crypto-deepseek` and `crypto-grok` exist.
- Confirm their provider auth profiles are configured.

No market data:

- Check internet access.
- Binance USD-M futures may be blocked in some networks. Change `market.exchange` in `settings.yaml` if needed.

Agent response rejected:

- Read `outputs/SIGNALS.md`.
- The rule engine lists exact rejection reasons.

Dashboard empty:

- Run `python -m src.cli init`.
- Run at least one `run-once` cycle.

Cloud dashboard stale:

- The local runner may be offline, sync may be failing, or GitHub push may not have completed.
- Run `python -m src.cli cloud-update`.
- Inspect `health_checks` for `cloud_git_sync`; trading continues and retries on the next cycle if Git push fails.

Render build fails:

- Verify `requirements.txt` installs locally.
- Confirm Render is using this project directory and the checked-in `render.yaml`.
- Confirm `render.yaml` sets `PYTHON_VERSION=3.11.11` and `.python-version` contains `3.11.11`; Render should not try to build with Python 3.14 or another default runtime.
- If the log path contains `.venv/lib/python3.14`, Render is ignoring the repo runtime setting. Trigger a manual deploy from the latest commit or set `PYTHON_VERSION` to `3.11.11` directly in the Render service environment.
