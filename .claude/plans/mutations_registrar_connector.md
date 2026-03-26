# Mutation Testing Results -- SecuritizeRegistrarV1Connector.vy

## Summary
- Mutations tested: 15
- Killed (by existing tests): 12
- Surviving: 3
- Fixed (killed by new tests): 3
- Remaining to fix: 0

## Surviving Mutations (all fixed)

- [x] **[event_constant]** `SecuritizeRegistrarV1Connector.vy:62` -- `authorized=authorized` changed to `authorized=True` in ContractAuthorizationChanged event
  - Original: `log ContractAuthorizationChanged(contract_address=contract_address, authorized=authorized)`
  - Mutated: `log ContractAuthorizationChanged(contract_address=contract_address, authorized=True)`
  - Impact: Event always reports `authorized=True` even when deauthorizing a contract. Off-chain systems relying on events would never see deauthorization.
  - Test: `test_change_authorized_contracts_event_deauthorize` in test_registrar_connector.py

- [x] **[guard_removal]** `SecuritizeRegistrarV1Connector.vy:74-75` -- Remove `if not isRegistered(...)` guard, always call registerVault
  - Original: `if not staticcall VaultRegistrar(vault_registrar).isRegistered(vault, investor_wallet): extcall VaultRegistrar(vault_registrar).registerVault(vault, investor_wallet)`
  - Mutated: `extcall VaultRegistrar(vault_registrar).registerVault(vault, investor_wallet)`
  - Impact: Already-registered vaults would be re-registered on every call, wasting gas and potentially causing issues if the registrar doesn't handle double registration gracefully
  - Test: `test_register_vault_skips_if_already_registered` in test_registrar_connector.py (uses TrackingVaultRegistrar mock that reverts on double-register)

- [x] **[param_swap]** `SecuritizeRegistrarV1Connector.vy:74` -- Swap params in isRegistered: `isRegistered(investor_wallet, vault)` instead of `isRegistered(vault, investor_wallet)`
  - Original: `if not staticcall VaultRegistrar(vault_registrar).isRegistered(vault, investor_wallet):`
  - Mutated: `if not staticcall VaultRegistrar(vault_registrar).isRegistered(investor_wallet, vault):`
  - Impact: The guard checks the wrong registration key, so already-registered vaults would always appear unregistered and get re-registered
  - Test: `test_register_vault_skips_if_already_registered` in test_registrar_connector.py (same test kills both guard_removal and param_swap mutations)

## Killed Mutations (12, caught by pre-existing tests)

- L47: `vault_registrar = _vault_registrar_addr` -> `vault_registrar = msg.sender` (killed by test_init_vault_registrar)
- L48: `owner = msg.sender` -> `owner = _vault_registrar_addr` (killed by connector fixture -- change_authorized_contract reverts)
- L59: `msg.sender == owner` -> `msg.sender != owner` (killed by connector fixture -- change_authorized_contract reverts)
- L59: delete `assert msg.sender == owner` (killed by test_change_authorized_contracts_reverts_if_not_owner)
- L60: `= authorized` -> `= not authorized` (killed by test_init_authorized_contracts)
- L60: delete state assignment (killed by test_init_authorized_contracts)
- L62: delete event log (killed by test_change_authorized_contracts_event)
- L62: event `contract_address=msg.sender` (killed by test_change_authorized_contracts_event)
- L73: delete auth assert (killed by test_register_vault_reverts_if_not_authorized)
- L74: remove `not` from isRegistered (killed by test_register_vault)
- L74-75: delete entire if block (killed by test_register_vault)
- L75: swap vault/investor_wallet in registerVault (killed by test_register_vault)
