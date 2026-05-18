# Project TODO

## Completed

- [x] Local risk automation (conditional orders, trailing stop, break-even, time exit, cooldowns, explicit API failover)
- [x] Dashboard tabs: Pending Orders, Risk Automation, API Failover Events
- [x] CLI: `list-pending-orders`, `cancel-pending-order`, `list-cooldowns`, `clear-cooldown`, `show-failover-status`, `list-risk-notifications`
- [x] Snapshot export `risk_automation` section
- [x] Tests: `tests/test_risk_automation.py`
- [x] Per-agent failover enabled with DeepSeek <-> Qwen fallback chains, primary retests, OpenClaw auth/base URL sync, and risk notifications
- [x] Agent prompt/rulebook guidance for active use of `PLACE_TRIGGER`, `position_risk`, `trailing_stop`, `break_even`, and `time_exit`

## Open

- [ ] Cloud dashboard: mirror new tabs in snapshot-only render path (local DB tabs already work)
- [ ] Record canonical Render URL in this file once confirmed from Render dashboard
