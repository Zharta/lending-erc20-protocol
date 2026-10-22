---
name: feedback-nonzero-fees-in-math-tests
description: Tests that validate money math or assert Loan-struct fee fields must use nonzero fees, not 0
metadata:
  type: feedback
---

Keeping protocol/origination fees at 0 in tests that do math validation is a footgun.

**Why:** With all fees at 0, fee-basis bugs are invisible. Concrete case (feat/despxa-loop):
the leveraged expected-loan helpers computed `origination_fee_amount` /
`protocol_upfront_fee_amount` on the RECONCILED principal, but the contract
(`P2PLendingMultiVaultLoan._validate_and_build_loan`, `fee_principal` arg) snapshots them on the
ORIGINAL offer principal (see the "Fees are charged on the ORIGINAL principal ... (D13/D7)" comments).
The mismatch only surfaces in the sync flexible-principal partial-mint path (reconciled != original),
and every test exercising it kept fees at 0, hiding the bug.

**How to apply:** Any unit test asserting balance deltas or Loan-struct fee fields (a
`compute_loan_hash` assertion includes the fee fields) should have at least one nonzero fee in play —
`origination_fee_bps=100` on the offer and/or `p2p.set_protocol_fee(upfront, settlement)` (owner-gated;
capped by the `max_protocol_*_fee` deploy args, 10000 in the multivault fixtures). Fees that must be
snapshotted onto the loan must be set BEFORE create. Pure revert tests and event-shape (plumbing) tests
may stay at 0. Keep the fee amounts concrete in the test body per [[feedback-concrete-tests]].

Contract fee facts (multivault leveraged):
- Sync flexible + refund: lender deploys `principal - origination_fee` to vault, `lender_refund =
  min(refunded, principal)`, `new_principal = principal - lender_refund`; fee fields stay on the
  ORIGINAL principal.
- Sync fixed + refund: leftover refunds the borrower; principal + fee fields unchanged.
- `cancel_pending_loan` payout: `lender_deployed = loan.amount - loan.origination_fee_amount`,
  `debt = lender_deployed + capped_interest` — differs from `loan.amount + interest` only when
  origination fee is nonzero.
- Protocol upfront fee is transferred lender -> protocol_wallet at create (both sync + async branches);
  lender's total spend = `(principal - origination_fee) + protocol_upfront`.
