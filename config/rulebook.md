# Crypto Paper Trading Arena

This arena compares two OpenClaw crypto agents:

- `crypto-deepseek`
- `crypto-qwen`

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
- Trial period: 1 week
- Target: strive for +10% account PnL in 1 week
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

## Competition Loop

Run both agents from the same market state and as close together in time as possible.

1. Ask `crypto-deepseek` for a signal.
2. Ask `crypto-qwen` for a signal.
3. Paste both raw outputs into `SIGNALS.md`.
4. Accept only signals that follow this rulebook.
5. Record accepted paper trades in `LEDGER.csv`.
6. Review open trades at least once per day.
7. Evaluate results weekly in `EVALUATION.md`.

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
- Risk/reward to TP1 is at least 1:1.5.
- Risk/reward to TP2 is at least 1:2.0.
- Stop loss is defined before take profit.
- Margin used is stated in USDT and as percent of account.
- Account risk at stop loss is stated in USDT and percent of account.
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

### Local conditional orders (`PLACE_TRIGGER`)

Use only when the setup should execute automatically without another model call.

- `action` must be `PLACE_TRIGGER`.
- Include `trigger_order` with:
  - `trigger`: AND/OR tree of conditions on `price` or `rsi_14` (`gte`, `lte`, `gt`, `lt`, `eq`).
  - optional `expires_at` ISO timestamp.
  - `execution_signal`: full compliant JSON for the paper trade to execute when triggered (typically `OPEN` / `PAPER_TRADE`).
- The local engine monitors triggers; do not expect a follow-up cycle to enter the trade.

### Position risk automation (optional on `OPEN`)

You may include `position_risk` on an accepted `OPEN` signal:

- `trailing_stop`: `{enabled, mode: percent|atr|step, distance_pct, atr_multiple, step_pct}`
- `break_even`: `{enabled, trigger: tp1|r_multiple|percent, r_multiple, percent_gain, fee_buffer_pct}`
- `time_exit`: `{enabled, max_hold_hours, only_if_profit_pct_below}`

If omitted, only standard SL/TP/time-horizon rules apply. Automation never widens stop risk.

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
- Progress toward the +10% weekly target

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

## Winner Criteria

At the end of the trial, keep the agent with the best risk-adjusted performance.

Preferred winner profile:

- Reaches or gets closest to +10% account PnL in 1 week
- Lower drawdown
- Fewer invalid/rejected signals
- Better adherence to rules
- Clearer reasoning that can be audited later
