---
name: transferred-loan-vault-id-zero
description: A transferred loan's new vault is vault_id_to_vault(new_borrower, 0), NOT wallet_to_vault(new_borrower) — transfer bumps vault_count so wallet_to_vault points at the wrong (next) vault
metadata:
  type: project
---

`transfer_loan` migrates a loan to a fresh vault for the new borrower at `vault_id =
vault_count[new_borrower]` (0 for a first-time recipient), then increments `vault_count`. So AFTER the
transfer:
- `p2p.wallet_to_vault(new_borrower)` returns the vault for `vault_count[new_borrower]` == 1 (the NEXT,
  empty vault) — WRONG address for the migrated loan.
- `p2p.vault_id_to_vault(new_borrower, 0)` returns the migrated loan's actual vault (holds the
  collateral / migrated payment proceeds).

Use `vault_id_to_vault(new_borrower, 0)` (matching the migrated loan's `vault_id == 0`) when asserting
balances on a transferred loan's vault. Mirrors `test_transfer.py`, which uses
`vault_id_to_vault(new_borrower, 0)`. Trap hit while writing the Fix-A async-redeem transfer test
(`test_transfer_loan_async_redeem_claims_and_migrates_proceeds`): the migrated USDC proceeds land in
`vault_id_to_vault(new_borrower, 0)`, and `wallet_to_vault` read 0 there.

**Fix A (transfer_loan of a REDEEM_ASYNC loan mid-redemption)** — the async ERC-7540 redeem request is
keyed to the OLD vault as controller. `transfer_loan` now, for a fulfilled async redemption
(`request_claimable > 0`), `claim_redeem`s the proceeds into the old vault BEFORE migrating (else the
proceeds strand). `_resolve_redeem_balances` gained an already-claimed fallback: async branch is
`if status.request_claimable > 0:` (live claim) `else:` assert request fully gone and read the vault's
payment-token balance. So a transferred redeeming loan reaches settle with no live request but proceeds
already in the (new) vault. The pre-fix stale test
`test_transfer_loan_reverts_for_async_redeem_even_with_valid_attestation` (D29, asserted the OLD
"redeem not concluded" revert) was DELETED. Test file `test_leveraged_async.py` section "4b. transfer_loan"
now holds `test_transfer_loan_async_redeem_claims_and_migrates_proceeds` (happy: claim+migrate+settle) and
`test_transfer_loan_async_redeem_reverts_if_not_settled` ("redeem not settled" when not fulfilled). The
async fulfil helper `_fulfil_redeem` is LOCAL to test_leveraged_async.py (also in test_async_redeem_settle.py).

Related: [[despxa-async-leveraged-tests]] (redeeming_loan fixture), [[boa-get-logs-last-computation]]
(read the LoanBorrowerTransferred event before the vault_id_to_vault view call).
