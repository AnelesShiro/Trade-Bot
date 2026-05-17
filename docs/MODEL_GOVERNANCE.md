# Model Governance

This project uses strict model locking for every OpenClaw agent request.

## Source of Truth

The only source of truth for agent LLM configuration is `config/settings.yaml`.

Each agent must define:

```yaml
llm:
  LLM_PROVIDER: qwen
  LLM_MODEL: qwen3-max-2026-01-23
  LLM_BASE_URL: ""
  LLM_API_KEY: QWEN_API_KEY
  LLM_ALLOW_FALLBACK: false
```

`LLM_MODEL` must be the exact model id returned by the provider response. Aliases such as `auto`, `default`, `latest`, or `best` are rejected at startup.

`LLM_ALLOW_FALLBACK` must remain `false`. Startup validation fails if fallback is enabled.

## Runtime Enforcement

For every request, the runner:

- Ensures `python -m src.cli init` registers the OpenClaw agent with the configured provider/model pair.
- Calls the locked OpenClaw agent without fallback or alternate model selection.
- Reads the recorded OpenClaw response model from the session file.
- Fails the request if the actual response model differs from `LLM_MODEL`.
- Logs configured model, actual model, token estimate, and estimated cost.

If a provider redirects a retired model to a newer model, the request fails with:

```text
Configured model '<LLM_MODEL>' is unavailable. Automatic model switching is disabled.
```

The competition runner treats this as an agent provider failure and continues the rest of the cycle according to the existing non-fatal provider failure policy.

## Changing Models Intentionally

To change a model intentionally:

1. Edit only `config/settings.yaml`.
2. Update the target agent's `llm.LLM_MODEL` to the exact provider/model id.
3. Confirm `llm.LLM_ALLOW_FALLBACK: false`.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m src.cli validate-update
.\.venv\Scripts\python.exe -m pytest tests/test_base_agent.py -q
```

5. Restart or queue a safe config reload according to the normal live update process.

Do not change prompts, rulebook, dashboard UI, or strategy logic just to change a model.

## Why This Exists

The Grok/xAI credit spike was caused by a provider-side model redirect from a retired `grok-4-1-fast` slug to a higher-priced model while OpenClaw kept a persistent session history. Strict model locking prevents silent redirects from being accepted as normal successful requests.

## API Failover (Explicit, Not Silent Fallback)

`LLM_ALLOW_FALLBACK` must remain `false`. That flag blocks **silent** provider-side redirects.

Separate explicit infrastructure failover is configured per agent under `agents.<id>.api_failover`.
Active agents currently use checked-in DeepSeek <-> Qwen fallback chains:

```yaml
api_failover:
  enabled: true
  retest_interval_seconds: 3600
  fallback_chain:
    - provider: deepseek
      model: deepseek-v4-flash
      LLM_BASE_URL: ""
      LLM_API_KEY: DEEPSEEK_API_KEY
```

When `enabled: true` and a billing/auth/rate-limit/timeout error occurs:

1. The runner records an `api_failover_events` row.
2. OpenClaw agent routing switches to the next `fallback_chain` entry (logged).
3. The current request retries once.
4. The response model is still verified against the active route's exact model.
5. `show-failover-status`, `list-risk-notifications`, and dashboard tab **API Failover Events** show active routes and notifications.
6. The primary route is periodically retested and restored only after a successful probe.

Failover does **not** change prompts, rulebook, or strategy. After changing any primary or fallback provider/model/base URL/auth env, run `python -m src.cli init` so OpenClaw routing and auth profiles match `config/settings.yaml`.
