---
name: facet-method-id-stale-loan-tuple
description: MultiVault main contract hardcodes the Loan tuple in method_id() strings used to delegatecall facets; adding a Loan field silently breaks the selector and reverts
metadata:
  type: project
---

P2PLendingMultiVaultErc20.vy forwards facet functions via
`raw_call(base.<facet>_addr, abi_encode(loan, ...), method_id("fn((<29-field Loan tuple>),...)"), is_delegate_call=True)`.
The Loan tuple type-string inside `method_id(...)` is HARDCODED (11 occurrences in the main
contract: transfer_loan, replace_loan, replace_loan_lender, liquidate_loan,
partially_liquidate_loan, simulate_partial_liquidation, extend_loan, extend_loan_lender,
cancel_redeem, and the PendingLoan-embedding start_loan / cancel_pending_loan).

**Why it bites:** when the `Loan` struct in P2PLendingMultiVaultBase.vy gained `create_time`
(field 9, between maturity and start_time → 30 fields), the `method_id` strings were NOT
updated, so the computed selector (e.g. transfer_loan → 0x01bb8239 for the 29-field string)
no longer matches the facet's real 30-field function. `abi_encode(loan)` still sends correct
30-field data, but the selector prefix is wrong → the facet's dispatcher finds no match →
bare `Revert(b'')`. boa surfaces this as `[113] Unknown contract <facet_addr>.<wrong_selector>`.

**How to apply / diagnose:** if facet-forwarded unit tests (replace, replace_lender, liquidate,
partially_liquidate, extend, transfer, settle/redeem variants, plus the config
"reverts_if_not_implemented" tests for start_loan/cancel_pending_loan/cancel_redeem) fail with
`Unknown contract <addr>.<selector>` while in-contract functions (create, settle,
add/remove_collateral, redeem, call) pass, suspect a stale `method_id` Loan/PendingLoan tuple
in the MAIN contract — NOT a test bug. No test-side change can fix it; the fix is to add the
missing field to the type-strings in P2PLendingMultiVaultErc20.vy. The facets themselves use
`base.Loan` directly (no hardcoded string) so they don't need changing.

Related: [[facet-event-decoding-quirk]] (different facet/main wiring gotcha).
