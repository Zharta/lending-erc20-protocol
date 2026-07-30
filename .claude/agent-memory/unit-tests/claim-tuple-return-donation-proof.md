---
name: claim-tuple-return-donation-proof
description: Vault claim_mint/claim_redeem return (request_leg, cancel_leg) tuples; cancel_pending_loan's reclaimed comes from the cancel leg's DIRECT RETURN (not balanceOf), making the estate donation-proof
metadata:
  type: project
---

feat/despxa-loop: the canonical `base.Vault` interface `claim_mint` and `claim_redeem` return
`-> (uint256, uint256)` instead of `-> uint256`. Both legs in ONE call: request-claim amount AND
cancel-claim amount, each 0 if that leg wasn't requested.
- `P2PLendingVaultCentrifugeAsync.claim_mint` -> `(minted_shares, reclaimed_payment)`;
  `claim_redeem` -> `(assets, reclaimed_shares)`. Midas + SecuritizeMV are raising stubs (signature-only).
- `_resolve_redeem_balances` (Base): one `claim_redeem(addr, request_claimable>0, cancel_claimable>0)`
  unpacking both legs. Behavior identical to the old two-call form (A2 forward-resolve numbers unchanged).
- `cancel_pending_loan` (Loan, A1): one `minted, reclaimed = claim_mint(addr, request_claimable>0,
  cancel_claimable>0)`.
- `start_loan`: `minted, no_reclaim = claim_mint(addr, True, False)` (cancel leg 0).
- `transfer_loan` (Liquidation) + `cancel_redeem` (Loan) discard the tuple via bare extcall.

**DONATION-PROOFING (deliberate behavior change, the one non-refactor bit):** in `cancel_pending_loan`,
`reclaimed` now comes from the cancel leg's DIRECT RETURN, NOT `balanceOf(payment_token, vault)` after
the claim. So a payment-token (USDC) donation transferred directly into the per-loan vault BEFORE cancel
is NOT swept into the waterfall — it stays in the vault. Old balanceOf approach would have inflated
`payment_reclaimed` and handed the donation (mostly) to the borrower. Flow: the mock holds mint_spend
USDC after requestDeposit; claim_mint's cancel leg transfers exactly `reclaimed` into the vault, then
`withdraw_funds(payment_token, reclaimed)` pulls exactly `reclaimed` back out to distribute — a donation
sitting in the vault is orthogonal and survives.

**Regression result:** the tuple refactor is behavior-preserving. Existing A1 (`test_leveraged_async.py`)
and A2 (`test_async_redeem_settle.py`) suites stay GREEN with ZERO expected-number changes. Full
`tests/p2p_erc20_multivault/unit`: 521 passed (pre-change) -> 522 passed, 1 skipped (after adding the
one donation test). The 1 skip is the known pre-existing skip.

**Donation-proof test:** `test_cancel_pending_mixed_terminal_ignores_payment_donation_into_vault` in
test_leveraged_async.py (right after `test_cancel_pending_mixed_terminal_distributes_both_legs`, which it
copies verbatim + reuses `_drive_to_mixed_terminal`/`_distribute`/`_carve`/`_shares_to_value`). Only diff:
`usdc.mint(vault_addr, 500e6)` donation into the per-loan vault before cancel. Asserts (a) event +
balances byte-identical to no-donation base (`payment_reclaimed == reclaimed == 100e6`, borrower does NOT
get the donation) and (b) `usdc.balanceOf(vault_addr) == donation` before AND after cancel (survives).
RED (mutation: `reclaimed = staticcall IERC20(payment_token).balanceOf(_vault.address)` after the claim,
`rm -rf .cache/titanoboa`): payment_reclaimed became 600e6 (100 reclaimed + 500 donation), lender_payment
inflated to 550499976, first failing assert `event.payment_reclaimed == reclaimed` (600e6 != 100e6).

**No vault-level both-legs test exists** — the only vault-level claim_mint/claim_redeem refs are the
caller-gating reverts (`test_centrifuge_async_vault_caller_gated_functions_revert_for_stranger`, pass
`(m, True, False)` for access control only). The mixed-terminal contract test already documents the tuple
(both legs nonzero from one call). Did not invent a new vault-level test.

Related: [[cancel-pending-a1-mixed-terminal]], [[a2-mixed-redeem-forward-resolve]].
