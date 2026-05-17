# Project TODO

## Completed

- [x] Local risk automation (conditional orders, trailing stop, break-even, time exit, cooldowns, API failover infrastructure)
- [x] Dashboard tabs: Pending Orders, Risk Automation, API Failover Events
- [x] CLI: `list-pending-orders`, `cancel-pending-order`, `list-cooldowns`, `clear-cooldown`, `show-failover-status`
- [x] Snapshot export `risk_automation` section
- [x] Tests: `tests/test_risk_automation.py`

## Open

- [ ] Enable `api_failover.enabled: true` on agents when fallback chains are verified in production
- [ ] Add agent prompt examples for `PLACE_TRIGGER` in a versioned prompt file if competition adopts conditional entries
- [ ] Cloud dashboard: mirror new tabs in snapshot-only render path (local DB tabs already work)
- [ ] Record canonical Render URL in this file once confirmed from Render dashboard
