---
name: centrifuge-async-vault-impl-rename
description: Why P2PLendingVaultDespxa was renamed to P2PLendingVaultCentrifugeAsync — on-fork probe showed deCRDX uses a different Centrifuge vault kind (SyncDepositVault) than the fully-async vault this impl drives
metadata:
  type: project
---

The Centrifuge vault impl `P2PLendingVaultDespxa.vy` was renamed to
`contracts/v1/P2PLendingVaultCentrifugeAsync.vy` (VERSION now
`"P2PLendingVaultCentrifugeAsync.20260714"`, String[40]) because the old name was misleading:
the impl is NOT deSPXA-specific, it drives Centrifuge's **fully-async AsyncVault**.

**Why:** An on-fork probe showed Centrifuge tokens split into TWO vault kinds:
- **deCRDX uses Centrifuge's `SyncDepositVault`** — sync deposit + async redeem. `previewDeposit`
  prices instantly; the async-deposit views (`pendingDepositRequest` etc.) REVERT. This impl's
  async-deposit state machine does NOT drive it.
- **deJAAA / deJTRSY / deSPXA use the fully-async `AsyncVault`** — async deposit AND async redeem.
  This is the kind `P2PLendingVaultCentrifugeAsync` drives.

**How to apply:** the impl name now names the VAULT KIND (Centrifuge async), not a token. When a
test fixture/helper denotes the vault kind, name it `centrifuge_*`; when it denotes a specific real
token (deSPXA, deJAAA, deJTRSY), keep the token name. Companion renames already done (compile-checked):
`AsyncVaultMock.vy` -> `contracts/auxiliary/CentrifugeAsyncVaultMock.vy`; deployment class
`VaultDespxaImpl` -> `VaultCentrifugeAsyncImpl` in `scripts/_helpers/contracts.py`.
See [[despxa-centrifuge-fork]] and [[despxa-base-fork]] for the two AsyncVault fork suites.

**Test-side rename map applied 2026-07-14 (all compile+run green):**
- Unit dir (`tests/p2p_erc20_multivault/unit/`, EVERY `despxa`-name there denoted the vault kind ->
  `centrifuge_*`): `despxa_vault_impl_contract_def`->`centrifuge_async_vault_impl_contract_def`,
  `despxa_vault_impl`->`centrifuge_async_vault_impl`,
  `async_vault_mock_contract_def`->`centrifuge_async_vault_mock_contract_def`,
  `async_vault_mock`->`centrifuge_async_vault_mock`, `p2p_usdc_weth_despxa`->`p2p_usdc_weth_centrifuge`,
  `sign_despxa_offer`->`sign_centrifuge_offer`, `fund_despxa_leveraged`->`fund_centrifuge_leveraged`,
  `despxa_signed_offer`->`centrifuge_signed_offer`,
  `expected_pending_despxa_loan`->`expected_pending_centrifuge_loan`, test fn
  `test_despxa_vault_*`->`test_centrifuge_async_vault_*`. Load paths ->
  `contracts/v1/P2PLendingVaultCentrifugeAsync.vy` + `contracts/auxiliary/CentrifugeAsyncVaultMock.vy`.
  (This supersedes the old `despxa_*` unit-fixture names mentioned in [[shared-fork-block-and-log-stuff]].)
- Integration conftest: `despxa_vault_impl_contract_def`->`centrifuge_async_vault_impl_contract_def`.
- `test_loop_dejaaa.py`: `despxa_vault_impl`->`centrifuge_async_vault_impl`,
  `_sign_despxa_offer`->`_sign_centrifuge_offer`.
- `test_loop_despxa.py`: ONLY `despxa_vault_impl_base`->`centrifuge_async_vault_impl_base`. KEPT the
  deSPXA-TOKEN names (`DESPXA_*`, `despxa_token/oracle/async_vault/manager/hook/asset_id`,
  `p2p_usdc_despxa`, `_sign_despxa_offer`, the filename) — there they honestly name the real deSPXA token,
  NOT the vault kind.
