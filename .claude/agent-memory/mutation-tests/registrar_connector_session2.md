---
name: registrar_connector_session2
description: SecuritizeRegistrarV1Connector.vy session 2 - 19 additional mutations all killed, contract fully covered (2026-03-27)
type: project
---

## Session: SecuritizeRegistrarV1Connector.vy Session 2 (2026-03-27)

Contract: `contracts/SecuritizeRegistrarV1Connector.vy`
Test file: `tests/registrar_connector/unit/test_registrar_connector.py`

### Results
- Mutations tested: 19
- Killed by existing tests: 19
- Surviving: 0
- Remaining: 0

### Mutations Tested (all killed)

**Constructor (`__init__`)**
1. L47: `vault_registrar = msg.sender` (assignment swap) -- killed by test_init_vault_registrar
2. L48: `owner = _vault_registrar_addr` (assignment swap) -- killed by fixture setup (owner check fails)
3. L47-48: swap both assignments -- killed by fixture setup

**change_authorized_contract**
4. L60: `= True` (constant mutation, always authorize) -- killed by test_change_authorized_contracts_event_deauthorize
5. L60: `= False` (constant mutation, never authorize) -- killed by test_init_authorized_contracts
6. L60: `[msg.sender] = authorized` (key swap) -- killed by test_init_authorized_contracts
7. L60: delete line (statement deletion) -- killed by test_init_authorized_contracts
8. L59: `msg.sender != owner` (comparison inversion) -- killed by fixture setup
9. L59: delete assert (access control removal) -- killed by test_change_authorized_contracts_reverts_if_not_owner
10. L62: `contract_address=msg.sender` (event param swap) -- killed by test_change_authorized_contracts_event
11. L62: delete log (event deletion) -- killed by test_change_authorized_contracts_event

**register_vault**
12. L73: `not self.authorized_contracts[msg.sender]` (boolean inversion) -- killed by test_register_vault
13. L73: delete assert (access control removal) -- killed by test_register_vault_reverts_if_not_authorized
14. L73: `[vault]` (key swap to vault) -- killed by test_register_vault
15. L73: `[investor_wallet]` (key swap to investor_wallet) -- killed by test_register_vault
16. L74: remove `not` (register only when already registered) -- killed by test_register_vault
17. L75: `registerVault(investor_wallet, vault)` (param swap) -- killed by test_register_vault
18. L75: replace with `pass` (statement deletion) -- killed by test_register_vault
19. L74-75: remove if guard entirely (always register) -- killed by test_register_vault_skips_if_already_registered

### Combined Totals (sessions 1 + 2)
- Total mutations tested: 34 (15 session 1 + 19 session 2)
- Killed by pre-existing tests: 27 (12 + 19 after session 1 added 3 tests)
- Surviving (historical): 3 (all from session 1, all fixed)
- Contract is comprehensively covered -- all meaningful mutation candidates exhausted
