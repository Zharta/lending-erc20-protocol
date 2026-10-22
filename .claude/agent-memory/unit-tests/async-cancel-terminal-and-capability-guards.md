---
name: async-cancel-terminal-and-capability-guards
description: Unit tests for the async cancel state-machine terminal reverts (no pending mint/redeem, redeem still pending) + capability guards (cancel not supported / redeem cancel not supported) on a non-async market, in test_leveraged_async.py
metadata:
  type: project
---

Coverage added to `tests/p2p_erc20_multivault/unit/test_leveraged_async.py` (feat/despxa-loop) for
previously-untested branches of `P2PLendingMultiVaultLoan.vy` cancel state machines + capability guards.
All contract-correct (tests PASS). No conftest changes — helpers are local to the file.

**Terminal "all four counters zero" reverts (drive the MOCK's ERC-7887 surface DIRECTLY to drain):**
- `test_cancel_pending_reverts_when_no_pending_mint` -> `"no pending mint"` (Loan.vy:411). From
  `pending_loan`: `mock.cancelDepositRequest(0, vault)` -> `mock.process_cancel_deposit(vault)` ->
  `mock.claimCancelDepositRequest(0, vault, vault)` drains reclaimable payment. All 4 mint counters 0,
  loan still stored pending. `claim_mint(False,False)` returns (0,0) -> revert.
- `test_cancel_redeem_reverts_when_no_pending_redeem` -> `"no pending redeem"` (Loan.vy:593). From
  `redeeming_loan` (redeem_pending==1e18): cancelRedeemRequest -> process_cancel_redeem ->
  `claimCancelRedeemRequest(0, vault, vault)` drains shares. All 4 redeem counters 0 -> the else `raise`.
- `test_cancel_redeem_reverts_if_request_still_pending` -> `"redeem still pending"` (Loan.vy:539). Need
  `cancel_claimable>0 AND request_pending>0 AND request_claimable==0` (so the earlier `"claimable redeem"`
  guard at 535 passes). Recipe: cancelRedeemRequest+process (settles cancel_claimable, drains pending to 0),
  THEN re-float a fresh pending via `mock.requestRedeem(shares, vault, borrower)` — fund the `owner` param
  (mint weth to borrower + approve the MOCK) since requestRedeem transferFroms shares from owner.
  The cancel_claimable branch then hits its `assert request_pending==0`.

Local helper `_mock_redeem_status(mock, vault_addr)` mirrors `_mock_mint_status` for the redeem side
(redeem_pending/redeem_claimable/redeem_cancel_pending(->0/1)/redeem_cancel_claimable).

**Capability guards on the Midas sync market `p2p_usdc_weth_sync` (caps MINT_SYNC|REDEEM_SYNC):** both
asserts sit AFTER loan-valid/state/sender but BEFORE `_get_vault`, so NO real mint/redeem scaffolding is
needed — fabricate a self-consistent Loan and seed its hash straight into storage.
- `_fabricated_loan(usdc, weth, oracle, borrower, lender, now, **overrides)` builds a Loan with real
  token/oracle addrs, then sets `id = compute_loan_hash(loan)`. `_seed_loan(p2p, loan)` does
  `p2p.eval("base.loans[<0xid>] = <0xhash>")`. (`_is_loan_valid` only checks stored hash == keccak.)
- `test_cancel_pending_reverts_cancel_not_supported` -> `"cancel not supported"` (Loan.vy:391). Fabricated
  PENDING loan (start_time 0), call as borrower.
- `test_cancel_redeem_reverts_redeem_cancel_not_supported` -> `"redeem cancel not supported"` (Loan.vy:529).
  Fabricated STARTED redeeming loan (start_time==create_time==now, redeem_start=now), call as borrower.

**Async create-guard variants:**
- `test_create_leveraged_async_zero_borrower_margin`: mint_spend==principal (orig fee 0) -> borrower_margin
  0; fund ONLY the lender, borrower holds 0 & no allowance -> proves the `if borrower_margin>0` transferFrom
  is skipped; `LeveragedLoanCreated.borrower_margin==0`, borrower balance unchanged.
- `test_create_leveraged_async_reverts_if_origination_fee_gt_bps` -> `"origination fee gt principal"`
  (Loan.vy:928, the async builder's own guard). Build the offer INLINE with the `Offer` NamedTuple
  (conftest's `_async_offer` is NOT importable) with origination_fee_bps=BPS+1, duration 100 > window 50.

**Centrifuge vault unsupported-op stubs** (`P2PLendingVaultCentrifugeAsync.vy` raises with NO caller guard):
`test_centrifuge_vault_unsupported_ops_revert` — one test, a `boa.reverts` block per op:
`"mint_sync not supported"` / `"mint_manual not supported"` / `"redeem_sync not supported"` /
`"redeem_manual not supported"`. Deploy standalone via `_standalone_vault` (already in the file); any sender.

**`_carve` (`_take_from_payment_then_collateral`) col==0 early-return NOT added (unreachable via the public
waterfall):** the `remaining_value>0 AND col==0` early-return at Loan.vy:341 is a defensive guard. Through
`cancel_pending_loan`'s waterfall the leg targets (fee+protocol+lender) always sum <= estate_value = pay +
col_value, so when col==0 estate_value==pay and every leg's `remaining_value` hits 0 exactly (the sibling
`remaining_value==0` early-return, which IS covered by the pure-payment cancel tests). Reaching col==0 with
remaining_value>0 requires an inconsistent estate the contract never produces — did not add a contrived test.

Suite after: `test_leveraged_async.py` 75 -> 83 passed; full `tests/p2p_erc20_multivault/unit`
540 passed, 1 skipped (pre-existing skip). ruff check + format clean.

Related: [[cancel-pending-a1-mixed-terminal]], [[a2-mixed-redeem-forward-resolve]],
[[despxa-async-leveraged-tests]], [[multivault-mock-selectable-capabilities]] (real-vault markets,
`_seed_loan` hash-write pattern), [[despxa-loop-revert-message-renames]].
