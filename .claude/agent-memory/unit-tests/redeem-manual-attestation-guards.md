---
name: redeem-manual-attestation-guards
description: How to unit-test the REDEEM_MANUAL attestation guards in settle_loan/liquidate_loan (bad sig vs vault mismatch) and which revert each surfaces
metadata:
  type: project
---

The REDEEM_MANUAL settle/liquidate path in `P2PLendingMultiVaultBase.vy` has three guards in
`_is_loan_redeem_concluded` (checked in order): (1) `redeem_result.result.timestamp >= loan.redeem_start`,
(2) `redeem_result.result.vault == _vault.address`, (3) `_validate_redeem_result_sig`. Only guard (3)
has its own message: `"invalid redeem result sig"` (the ecrecovered signer must == `self.owner`, the
vault owner). Guards (1) and (2) just return False, which surfaces via `_resolve_redeem_balances`'s
`assert _is_loan_redeem_concluded(...), "redeem not concluded"`.

**Two distinct revert tests (added to test_settle.py + test_liquidate.py, feat/despxa-loop):**
- bad-sig: sign the CORRECT redeem_result (right vault + timestamp >= redeem_start) with a NON-owner key
  (`lender_key`) -> `"invalid redeem result sig"`. Set vault + timestamp correctly or an earlier guard
  masks it.
- vault-mismatch: sign with the CORRECT `owner_key` but set `result.vault` to a stranger addr -> guard (2)
  returns False -> `"redeem not concluded"` (NOT its own message).

**Signing keys:** `owner_key` = the vault owner (the only key that produces a valid attestation).
`lender_key`/`borrower_key` are non-owner keys for the bad-sig case. `sign_redeem_result(result, key)`
(in `conftest_base.py`) is the helper.

**Reusing happy-path fixtures:** settle uses `redeemed_loan_for_settle`, liquidate uses
`redeemed_loan_with_payment` — both return `(redeemed_loan, redeem_result, payment_redeemed)` where
`redeem_result` already has the correct vault + `timestamp = now+1` (>= redeem_start = now). Just re-sign
(bad-sig) or copy-with-wrong-vault (mismatch). LIQUIDATE tests must time-travel past maturity
(`redeemed_loan.maturity - now + 1`) and use `sender=redeemed_loan.lender`; SETTLE must NOT default and
uses `sender=redeemed_loan.borrower`. Preconditions asserted: `redeem_start > 0`,
`timestamp >= redeem_start`, and (bad-sig only) `redeem_result.vault == vault_id_to_vault(...)`.

Related: [[multivault-mock-selectable-capabilities]] (REDEEM_MANUAL is the default `p2p_usdc_weth` market).
