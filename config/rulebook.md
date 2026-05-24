# Crypto Paper Trading Arena

This is a continuous, permanent trading arena with no end date. Two OpenClaw agents operate indefinitely:

- `crypto-deepseek`
- `crypto-challenger`

The exact provider/model for each agent is locked in `config/settings.yaml` under the agent `llm` block.

---

## Non-Negotiable Scope

- Paper trading only.
- No exchange API keys.
- No real orders.
- Futures leverage is simulated only.
- No financial advice language.
- The agents are analysts, not autonomous traders.

---

## Default Settings

- Starting paper equity per agent: 10,000 USDT
- Symbol: BTC only
- Instrument: BTCUSDT perpetual futures, paper trading
- Maximum leverage: 10x
- Operation: continuous, no end date — the system runs indefinitely until manually stopped
- Soft weekly target: approximately +7% account growth per rolling 7-day period when quality opportunities exist (this is a KPI only; it must never force trades or override risk rules)
- Position sizing: agent may choose, but must state margin used, notional exposure, and account risk
- Max margin per OPEN/ADD/DCA action: 10% of account equity (1,000 USDT initially)
- Maximum total account risk across all open positions: 2% of account equity
- Maximum simultaneous open positions: 3
- Maximum DCA actions per position: 2
- Daily loss limit: 3% of account equity
- Agents may DCA, cut, scale in, scale out, or open additional BTC positions when the market supports it
- Stop loss: required for every trade
- Take profit: required for every trade
- Entry timing: agent may enter only when it finds a reasonable setup; standing aside is allowed
- Default timeframe: agent may choose, but must state expected holding period
- Stablecoin quote: USDT

---

## Trading Loop

Run both agents from the same market state and as close together in time as possible.

1. Ask `crypto-deepseek` for a signal.
2. Ask `crypto-challenger` for a signal.
3. Paste both raw outputs into `SIGNALS.md`.
4. Accept only signals that follow this rulebook.
5. Record accepted paper trades in `LEDGER.csv`.
6. Review open trades at least once per day.
7. Evaluate rolling 7-day performance in `EVALUATION.md`.

---

## Required Data Discipline

Agents must state what data they used. If they do not have current market data, they must either:

- Ask the user to provide current prices, or
- Give a conditional setup with explicit trigger levels, or
- Return `NO_TRADE`

No agent may invent current prices, funding rates, liquidation levels, or news.

---

## Trade Quality Gate

A trade idea is valid only if:

- Symbol is BTC only.
- Leverage is stated and is 10x or lower.
- Action is stated: `OPEN`, `ADD`, `DCA`, `REDUCE`, `CUT`, `CLOSE`, or `HOLD`.
- Any `OPEN`, `ADD`, or `DCA` action uses 10% account margin or less.
- Total account risk after the action is 2% of equity or less.
- Risk/reward to TP1 is at least 1:1.19.
- Risk/reward to TP2 is at least 1:2.0.
- Stop loss is defined before take profit.
- Margin used is stated in USDT and as percent of account.
- Account risk at stop loss is stated in USDT and percent of account.
- Account risk must equal the validator formula in the Futures PnL Convention section.
- If modifying an existing position, the target position ID or context is stated.
- Thesis and invalidation are both clear.
- Counterargument is present.

If any required element is missing, record the output as rejected in `SIGNALS.md` and do not add it to `LEDGER.csv`.

---

## Signal Requirements

Each trade idea must include:

- agent
- timestamp
- symbol
- decision (`PAPER_TRADE`, `WATCHLIST`, `NO_TRADE`, or `POSITION_UPDATE`)
- action
- position ID or position context
- direction
- entry
- leverage
- margin used
- notional exposure
- stop loss
- take profit 1
- take profit 2
- time horizon
- risk percent
- liquidation-risk note
- confidence (1-5)
- thesis
- invalidation
- counterargument
- data used
- execution type (`MARKET`, `LIMIT`, or `CONDITIONAL`)

### Confidence Scale

- 1 = Very Low
- 2 = Low
- 3 = Moderate
- 4 = High
- 5 = Very High

---

## Valid Decisions

Agents may return only:

- `NO_TRADE`
- `WATCHLIST`
- `PAPER_TRADE`
- `POSITION_UPDATE`

`WATCHLIST` means the setup is not active yet and should not be entered into the ledger.

`POSITION_UPDATE` means the agent is managing an existing paper position using `ADD`, `DCA`, `REDUCE`, `CUT`, `CLOSE`, or `HOLD`.

---

## Exit Rules

Paper trades close when one of these happens:

- Stop loss hit
- Take profit hit
- Time horizon expires
- Invalidation condition occurs
- Manual review closes the trade and records the reason

Partial exits are allowed only if TP1 and TP2 are clearly specified.

---

## Position Management

Allowed actions:

- `OPEN`
- `ADD`
- `DCA`
- `REDUCE`
- `CUT`
- `CLOSE`
- `HOLD`
- `PLACE_TRIGGER` (optional local conditional entry; does not open until trigger fires)

### Advanced trade-management priority

1. Attractive setup right now -> `OPEN`.
2. Future pullback, breakout, or RSI condition needed -> `PLACE_TRIGGER`.
3. Momentum or trend continuation -> consider `trailing_stop`.
4. Break-even stop is enforced locally by default around +1R, before TP if needed.
5. Thesis has a time horizon -> set `time_exit.max_hold_hours`.

Cooldowns are enforced locally; if cooldown context is active, do not request new entries. API failover is automatic and should not affect strategy reasoning.

### Local conditional orders (`PLACE_TRIGGER`)

Use when the setup should execute automatically without another model call.

- `action` must be `PLACE_TRIGGER`.
- Include `trigger_order` with:
  - `trigger`: AND/OR tree of conditions on `price` or `rsi_14` (`gte`, `lte`, `gt`, `lt`, `eq`).
  - optional `expires_at` ISO timestamp.
  - `execution_signal`: full compliant JSON for the paper trade to execute when triggered (typically `OPEN` / `PAPER_TRADE`).
- The local engine monitors triggers; do not expect a follow-up cycle to enter the trade.

### Position risk automation (available on `OPEN`)

Include `position_risk` when it improves trade quality without changing the core setup:

- `trailing_stop`: `{enabled, mode: percent|atr|step, distance_pct, atr_multiple, step_pct}`
- `break_even`: `{enabled, trigger: tp1|r_multiple|percent, r_multiple, percent_gain, fee_buffer_pct}`
- `time_exit`: `{enabled, max_hold_hours, only_if_profit_pct_below}`

If omitted, break-even still applies by default at `r_multiple=1.0`; other automation remains opt-in unless configured. Automation never widens stop risk.

### Valid JSON Templates

Use these templates as shape examples. Replace prices with the live market setup. Do not copy stale prices blindly.

#### Normal market entry with correct risk math

```json
{
  "agent": "crypto-challenger",
  "decision": "PAPER_TRADE",
  "action": "OPEN",
  "symbol": "BTC",
  "direction": "LONG",
  "execution_type": "MARKET",
  "leverage": 5,
  "margin_used_usdt": 1000,
  "margin_used_percent": 0.10,
  "notional_exposure_usdt": 5000,
  "entry": 77000,
  "stop_loss": 76500,
  "take_profit_1": 77800,
  "take_profit_2": 78200,
  "time_horizon": "6-12h",
  "account_risk_usdt": 32.47,
  "account_risk_percent": 0.003247,
  "total_account_risk_after_action_usdt": 32.47,
  "total_account_risk_after_action_percent": 0.003247,
  "liquidation_risk_note": "5x simulated paper leverage; stop is far from liquidation.",
  "confidence": 3,
  "risk_reward_to_tp1": 1.6,
  "risk_reward_to_tp2": 2.4,
  "thesis": "Price reclaimed support with improving momentum.",
  "invalidation": "Close back below support or stop loss hit.",
  "counterargument": "Trend may remain weak and reject the reclaim.",
  "data_used": ["market_state", "indicators", "recent_candles"],
  "notes_for_ledger": "Risk formula: abs(77000-76500)/77000*5000 = 32.47 USDT."
}
```

#### Open with local risk automation

```json
{
  "agent": "crypto-challenger",
  "decision": "PAPER_TRADE",
  "action": "OPEN",
  "symbol": "BTC",
  "direction": "LONG",
  "execution_type": "MARKET",
  "leverage": 5,
  "margin_used_usdt": 1000,
  "margin_used_percent": 0.10,
  "notional_exposure_usdt": 5000,
  "entry": 77000,
  "stop_loss": 76500,
  "take_profit_1": 77800,
  "take_profit_2": 78200,
  "time_horizon": "6-12h",
  "account_risk_usdt": 32.47,
  "account_risk_percent": 0.003247,
  "total_account_risk_after_action_usdt": 32.47,
  "total_account_risk_after_action_percent": 0.003247,
  "liquidation_risk_note": "5x simulated paper leverage; stop is far from liquidation.",
  "confidence": 3,
  "risk_reward_to_tp1": 1.6,
  "risk_reward_to_tp2": 2.4,
  "thesis": "Breakout continuation setup.",
  "invalidation": "Breakout fails and stop loss is reached.",
  "counterargument": "Breakout may be a liquidity sweep.",
  "data_used": ["market_state", "indicators", "recent_candles"],
  "position_risk": {
    "trailing_stop": {"enabled": true, "mode": "percent", "distance_pct": 0.01},
    "break_even": {"enabled": true, "trigger": "tp1", "fee_buffer_pct": 0.0005},
    "time_exit": {"enabled": true, "max_hold_hours": 12, "only_if_profit_pct_below": 0.002}
  }
}
```

#### Conditional order

```json
{
  "agent": "crypto-challenger",
  "decision": "PAPER_TRADE",
  "action": "PLACE_TRIGGER",
  "symbol": "BTC",
  "direction": "NONE",
  "execution_type": "CONDITIONAL",
  "thesis": "Enter only if price confirms the breakout.",
  "invalidation": "Trigger expires or price breaks the invalidation level first.",
  "counterargument": "Waiting for trigger may miss the first move.",
  "data_used": ["market_state", "indicators", "recent_candles"],
  "trigger_order": {
    "trigger": {
      "logic": "AND",
      "conditions": [
        {"field": "price", "op": "gte", "value": 77000},
        {"field": "rsi_14", "op": "gte", "value": 45}
      ]
    },
    "expires_at": "2026-05-18T18:00:00Z",
    "execution_signal": {
      "agent": "crypto-challenger",
      "decision": "PAPER_TRADE",
      "action": "OPEN",
      "symbol": "BTC",
      "direction": "LONG",
      "execution_type": "MARKET",
      "leverage": 5,
      "margin_used_usdt": 1000,
      "margin_used_percent": 0.10,
      "notional_exposure_usdt": 5000,
      "entry": 77000,
      "stop_loss": 76500,
      "take_profit_1": 77800,
      "take_profit_2": 78200,
      "time_horizon": "6-12h",
      "account_risk_usdt": 32.47,
      "account_risk_percent": 0.003247,
      "total_account_risk_after_action_usdt": 32.47,
      "total_account_risk_after_action_percent": 0.003247,
      "liquidation_risk_note": "5x simulated paper leverage; stop is far from liquidation.",
      "confidence": 3,
      "risk_reward_to_tp1": 1.6,
      "risk_reward_to_tp2": 2.4,
      "thesis": "Triggered breakout entry.",
      "invalidation": "Stop loss is reached after trigger.",
      "counterargument": "Trigger may activate into a failed breakout.",
      "data_used": ["market_state", "indicators", "trigger_order"]
    }
  }
}
```

#### Position update / hold

```json
{
  "agent": "crypto-challenger",
  "decision": "POSITION_UPDATE",
  "action": "HOLD",
  "symbol": "BTC",
  "position_id": "existing-position-id",
  "position_context": "Existing LONG remains above invalidation and has not reached TP/SL.",
  "direction": "LONG",
  "execution_type": "NONE",
  "thesis": "Original thesis remains intact.",
  "invalidation": "Close below support or stop loss hit.",
  "counterargument": "Momentum is slowing and may require reduce/cut next cycle.",
  "data_used": ["open_positions", "market_state", "indicators"]
}
```

### Constraints

- Each `OPEN`, `ADD`, or `DCA` uses no more than 10% account equity as new margin.
- Maximum DCA actions per position: 2.
- DCA is not allowed solely to avoid recognizing a losing trade.
- After `ADD` or `DCA`, the agent must restate total margin, total notional exposure, average entry if known, and updated account risk.
- If updated risk is unclear, the signal is rejected.
- After a stop loss, the agent must wait at least one full decision cycle before opening a new position in the same direction.

---

## Daily Risk Controls

- If cumulative realized + unrealized losses reach 3% in one UTC day, no new positions may be opened until the next UTC day.
- Existing positions may still be reduced or closed.

---

## Futures PnL Convention

For paper tracking:

- Notional exposure = margin used x leverage
- Long PnL = notional exposure x ((exit price - entry price) / entry price)
- Short PnL = notional exposure x ((entry price - exit price) / entry price)
- Account risk at stop = abs(entry price - stop loss) / entry price x notional exposure
- Do not multiply by leverage again after notional exposure has already been calculated.
- Example: margin 1,000 USDT at 5x means notional 5,000 USDT. Long entry 77,000 and stop 76,500 gives risk = 500 / 77,000 x 5,000 = 32.47 USDT, or 0.3247% of a 10,000 USDT account. In JSON, write `account_risk_percent: 0.003247`.
- Account PnL % = PnL USDT / 10,000 x 100

Fees and funding are ignored unless added later.

---

## Evaluation

Winner is determined by risk-adjusted behavior, not profit alone.

Score these together:

- Total return
- Max drawdown
- Win rate
- Average win / average loss
- Risk/reward quality
- Rule compliance
- Clarity and repeatability
- Number of rejected signals
- Avoidance of low-quality trades
- Rolling 7-day return progress toward the +7% soft weekly target

---

## Disqualification

An agent may be disqualified for:

- Suggesting real-money execution
- Ignoring stop loss or risk percent
- Using leverage above 10x
- Trading symbols other than BTC
- Repeatedly forcing low-quality trades
- Inventing market data
- Asking for exchange credentials
- Treating paper trades as real-money instructions

---

## Performance Criteria

Agents are evaluated continuously on risk-adjusted performance.

Preferred agent profile:

- Consistent rolling 7-day return closest to +7% soft target
- Lower drawdown
- Fewer invalid/rejected signals
- Better adherence to rules
- Clearer reasoning that can be audited later
- Sustainable compounding over time, not short-term gambling
