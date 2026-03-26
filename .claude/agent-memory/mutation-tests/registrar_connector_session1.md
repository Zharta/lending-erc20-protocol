---
name: registrar_connector_session1
description: Mutation testing of SecuritizeRegistrarV1Connector.vy - 15 mutations tested, 3 surviving all fixed (2026-03-26)
type: project
---

## Session: SecuritizeRegistrarV1Connector.vy (2026-03-26)

Contract: `contracts/SecuritizeRegistrarV1Connector.vy`
Test file: `tests/registrar_connector/unit/test_registrar_connector.py`
Plan file: `.claude/plans/mutations_registrar_connector.md`

### Results
- Mutations tested: 15
- Killed by existing tests: 12
- Surviving: 3
- Fixed with new tests: 3
- Remaining: 0

### Surviving mutations (all fixed)
1. **event_constant L62**: `authorized=authorized` -> `authorized=True` -- event test only checked True case
   - Fixed by: `test_change_authorized_contracts_event_deauthorize`
2. **guard_removal L74-75**: Remove `if not isRegistered(...)` guard -- no test registered same vault twice
   - Fixed by: `test_register_vault_skips_if_already_registered` (uses TrackingVaultRegistrar mock)
3. **param_swap L74**: `isRegistered(vault, investor_wallet)` -> `isRegistered(investor_wallet, vault)` -- same root cause as #2
   - Fixed by: same test as #2

### Coverage patterns found
- The `register_vault` idempotency guard (isRegistered check) was completely untested -- no test ever called register_vault with an already-registered vault
- Event tests only checked the positive case (authorize=True), never deauthorize (authorize=False)
- The TrackingVaultRegistrar inline mock pattern (reverts on double-register) is effective for testing idempotency guards

### Contract is fully covered
All 15 mutation candidates were tested. 12 killed by existing tests, 3 surviving now killed by 2 new tests. The contract has comprehensive mutation test coverage.
