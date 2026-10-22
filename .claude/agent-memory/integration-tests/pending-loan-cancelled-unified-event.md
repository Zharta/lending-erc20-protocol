---
name: pending-loan-cancelled-unified-event
description: A1 fix folded PendingLoanLiquidated into a redefined PendingLoanCancelled with paired payment+collateral legs; how the loop tests assert it
metadata:
  type: project
---

The A1 fix on `contracts/v1/P2PLendingMultiVaultErc20.vy` REMOVED the `PendingLoanLiquidated`
event and REDEFINED `PendingLoanCancelled`. Every pending-loan unwind (pure cancel AND
fulfilled-below-min force-unwind) now emits ONE `PendingLoanCancelled`.

New fields (order):
`id, borrower, lender, collateral_claimed, payment_reclaimed, lender_payment, lender_collateral,
liquidation_fee_payment, liquidation_fee_collateral, protocol_fee_payment, protocol_fee_collateral,
borrower_payment, borrower_collateral, caller`

Each recipient (lender/liquidation_fee(keeper)/protocol/borrower) has a `_payment` leg AND a
`_collateral` leg. Estate totals: `collateral_claimed` (fulfilled shares) and `payment_reclaimed`
(reclaimed payment).

**How the two loop-test scenarios map (same in test_loop_dejaaa / dejtrsy / despxa — no shared
helper, each file inlines identical assertions):**

- `test_cancel_pending_unfilled_loan` (pure cancel, never fulfilled): PAYMENT legs carry the split,
  collateral legs all 0. `payment_reclaimed == mint_spend`; `collateral_claimed == 0`;
  `liquidation_fee_payment == keeper_fee`, `protocol_fee_payment == protocol_fee`,
  `lender_payment == lender_recovery`, `borrower_payment == borrower_surplus`.
  (old `payment_refunded` == new `payment_reclaimed`.)

- `test_force_unwind_fulfilled_below_min_collateral` (fulfilled below min, force-unwind): COLLATERAL
  legs carry the share split, payment legs all 0. `collateral_claimed` = ground-truth minted shares;
  `lender_collateral / liquidation_fee_collateral / protocol_fee_collateral / borrower_collateral`
  = the share legs; `payment_reclaimed == 0`. (old `PendingLoanLiquidated.lender_amount ->
  lender_collateral`, `.liquidation_fee -> liquidation_fee_collateral`, `.protocol_fee ->
  protocol_fee_collateral`, `.borrower_amount -> borrower_collateral`, `.collateral_claimed`
  keeps its name.)
