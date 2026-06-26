---
name: cancel-pending-a1-mixed-terminal
description: Audit A1 — cancel_pending_loan now handles the MIXED terminal deposit (request_claimable>0 AND cancel_claimable>0); event folded into new-shape PendingLoanCancelled; committed freed by explicit covered/shortfall split (COVERED frees full loan.amount, SHORTFALL frees min(lender_value, loan.amount))
metadata:
  type: project
---

Audit fix A1 (feat/despxa-loop, `P2PLendingMultiVaultLoan.vy::cancel_pending_loan`): a Centrifuge
ERC-7540 deposit can be PARTIALLY FULFILLED and PARTIALLY CANCELLED at once
(`request_claimable>0 AND (cancel_pending>0 OR cancel_claimable>0)`). The OLD claimable branch asserted
`status.cancel_pending == 0 and status.cancel_claimable == 0, "cancel in flight"` and `start_loan`'s gate
is `request_claimable>0 and request_pending==0 and cancel_pending==0 and cancel_claimable==0, "mint not
settled"`, so a mixed loan was BOTH un-cancellable AND un-startable = permanently bricked (principal +
margin frozen, committed liquidity never freed).

**New cancel_pending_loan order** (all in `test_leveraged_async.py`):
1. `cancel_pending>0` -> return False (retry).
2. `request_pending>0` -> `cancel_mint`; return False.
3. Terminal (both pendings 0): claim `minted` from `claim_mint(True,False)` if `request_claimable>0`,
   and `reclaimed = payment_token.balanceOf(vault)` after `claim_mint(False,True)` if `cancel_claimable>0`;
   `assert minted>0 or reclaimed>0, "no pending mint"`.
4. Startability guard ONLY when `cancel_claimable==0`: `assert minted < min_collateral OR defaulted,
   "claimable mint, start instead"` (clean-fulfil case still must start, protects lender).
5. ONE combined waterfall over estate {reclaimed payment, minted collateral shares} via new `_carve`
   helper: priority caller-fee > protocol-fee > lender > borrower; each leg PAYMENT-FIRST then collateral
   (shares rounded DOWN); borrower absorbs dust. `debt = (amount - origination_fee) + capped_interest`.

**Event change (breaks old tests):** `PendingLoanLiquidated` DELETED, folded into new-shape
`PendingLoanCancelled` with per-recipient payment AND collateral legs: `id, borrower, lender,
collateral_claimed, payment_reclaimed, lender_payment, lender_collateral, liquidation_fee_payment,
liquidation_fee_collateral, protocol_fee_payment, protocol_fee_collateral, borrower_payment,
borrower_collateral, caller`. Pure-payment cancels: all `*_collateral==0`. Pure-collateral force-unwind:
all `*_payment==0, payment_reclaimed==0`.

**COMMITTED-LIQUIDITY FOLD-IN (was a bug, now FIXED on feat/despxa-loop):** The CORRECT behavior is an
explicit covered/shortfall split mirroring liquidate_loan (Loan.vy ~481-485):
`loan.amount if value_after_fee >= debt else min(lender_value, loan.amount)`.
- COVERED (`value_after_fee >= debt`): frees the FULL `loan.amount` — the origination-fee slice is NOT
  retained, consistent with settle/liquidate. Single-loan offer -> committed reaches EXACTLY 0.
  Aggregated offer -> committed drops by exactly P.
- SHORTFALL: frees `min(lender_value, loan.amount)` — the unrecovered principal is a genuine realized loss
  that STAYS committed (`committed_after == 2P - lender_value > P` on the aggregated shortfall test).

HISTORY / BUG THAT WAS FIXED: an earlier A1 revision used a BLANKET unconditional `min(lender_value,
loan.amount)`. Because `lender_value = debt - protocol_value` and `debt` uses
`lender_deployed = amount - origination_fee`, ANY nonzero origination fee made `lender_value < loan.amount`
EVEN WHEN COVERED, so committed could never reach 0 — the undeployed origination slice stayed committed
(under-free by ~origination_fee). This was WRONG. The three covered tests (pure-payment
`test_cancel_pending_covered_pays_keeper_lender_protocol_and_surplus` + both covered force-unwind tests)
temporarily asserted `== loan.amount - lender_value` to accommodate that bug; they now correctly assert
`commited_liquidity(...) == 0`. RED check (contract reverted to blanket-min, principal 1000e6 @ 1%
origination): committed retained **9999855 wei** (~origination_fee 10e6 minus a tiny protocol-fee bit)
instead of 0. If a single-loan COVERED cancel/force-unwind test asserts committed != 0, it's wrong now.
The aggregated covered test (origination_fee_bps=0) asserts `== P` and is unaffected by the fee subtlety.

**Reaching the MIXED terminal state (mock hooks are the off-chain issuer):**
`fulfill_deposit(vault, partial_assets, partial_shares)` (PARTIAL: mock asserts `pending>=assets`,
decrements) -> `cancelDepositRequest(0, vault)` (moves remaining pending into cancel pipeline) ->
`process_cancel_deposit(vault)` (-> cancel_claimable). Yields `request_claimable=partial_assets (with
partial_shares), cancel_claimable=mint_spend-partial_assets`, both pendings 0. Fund the mock with
`partial_shares` weth for the share claim; the usdc for the cancel-claim is already in the mock from
requestDeposit (`usdc.balanceOf(mock)==mint_spend` right before cancel). Helper `_drive_to_mixed_terminal`
+ `_mock_mint_status` (reads the mock getters, mirrors the vault's `mint_status` deposit leg). To reach
the TRANSIENT retry state (cancel still settling) do the `cancelDepositRequest` but SKIP
`process_cancel_deposit` -> `cancel_pending=1, request_claimable>0`.

**Independent split reproduction:** module-level python `_carve(target_value, pay, col)` and
`_distribute(reclaimed, minted, debt, interest, full_liq_fee, settlement_fee)` mirror the contract exactly
(payment-first, DOWN-rounded value->shares clamped to col, borrower gets dust); `_distribute` returns
per-leg `(pay, col)` tuples + scalar `lender_value` (for the committed assertion). The SHORTFALL
force-unwind test had to switch from "lender gets ALL remaining shares" to `_distribute` legs because
`_carve` gives lender `min(value_to_shares(lender_value), col)` and the BORROWER now absorbs the collateral
dust (old code gave borrower 0). Oracle: RATE_NUM=387780390000, RATE_DEN=1e8, PAY=1e6, COL=1e18.

**Concretes for a genuine TOKEN MIX in the core test:** reclaimed must be SMALL enough to run out
mid-waterfall. principal 1000e6, fees 5%/10%, interest ~161 wei (t=51) so protocol_value ~16 wei (tiny).
partial_assets=1400e6 (reclaimed=100e6), partial_shares=0.3 weth (~1163 USDC): keeper fee (~49.5e6) + protocol
(~16) fully in payment, lender leg (~990e6) SPLIT (100e6-ish payment then ~940e6 collateral), borrower dust
in collateral. A large reclaimed (e.g. 1470e6) pays lender fully in payment -> no mix.

**SHORTFALL on aggregated offer gotcha:** with `mint_spend = P+100`, cancelling a small remainder leaves a
HUGE reclaimed (~P) that alone covers debt -> covered, not shortfall. To crater: fulfil ~ALL assets at ~0
shares (`partial_assets=mint_spend-40, partial_shares=1000`), cancel the 40-wei remainder -> reclaimed=40,
shares~0 -> estate << P. Then committed drops by only `lender_value` (<P), `committed_after == 2P -
lender_value > P` (loss stays committed, mirrors liquidate_loan shortfall, audit #6).

**RED verification method:** `git stash push contracts/v1/P2PLendingMultiVaultLoan.vy
contracts/v1/P2PLendingMultiVaultErc20.vy` restores the OLD contract+events; the new tests revert INSIDE
cancel_pending_loan BEFORE any event read, so `boa.reverts` / the test's own cancel call catches it. OLD
reverts observed: cancel on mixed -> `"cancel in flight"` (Loan.vy:380); `start_loan` on mixed ->
`"mint not settled"` (Loan.vy:258, cancel_claimable!=0). `git stash pop` restores A1; verify `git diff
contracts/` shows only the A1 fix + the mock DOCSTRING comment (no redeem logic change — redeem already
mirrors deposit's partial-fulfill).

Related: [[cancel-pending-force-unwind-share-split]] (superseded event name: now PendingLoanCancelled),
[[committed-liquidity-freed-by-principal]], [[despxa-async-leveraged-tests]].
