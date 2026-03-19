---
name: P2PLendingVaultSecuritize.vy mutation testing - complete
description: Full mutation testing of P2PLendingVaultSecuritize.vy - 22 mutations tested, all 8 surviving now fixed with new tests in test_buy.py
type: project
---

## Session 2026-03-18: P2PLendingVaultSecuritize.vy

### Contract: contracts/v1/P2PLendingVaultSecuritize.vy
### Test file: tests/p2p_erc20_securitize/unit/test_buy.py

### Results
- 22 mutations tested across all functions
- 14 killed by existing tests
- 8 surviving mutations found and fixed with 8 new tests

### Functions covered
- initialise (L79-92)
- deposit (L96-118) - full-pending, partial-pending, no-pending branches
- withdraw (L121-146) - balance check, transfer failure handling
- withdrawable_balance (L151-157)
- withdraw_pending (L161-171)
- withdraw_funds (L175-184)
- transfer_funds (L188-199)
- buy (L203-228) - auth, min check, pending credits, refund logic
- _check_user (L231-232) - direct and proxy paths

### Key patterns found
- Test fixtures used owner == caller for vault initialization, missing access control mutations
- Boundary conditions (>= vs >) frequently survived in pending transfer comparisons
- The proxy authorization path (_check_user second branch) was never directly tested for the vault
- Need tokens that revert on zero-amount transfers to catch guard removal mutations

### New tests added (8)
1. test_deposit_with_pending_equals_amount
2. test_withdrawable_balance_subtracts_pending
3. test_withdraw_pending_exact_full_amount
4. test_buy_only_owner_can_call
5. test_buy_with_exact_min_ds_token_amount
6. test_buy_reverts_when_ds_token_below_min
7. test_transfer_funds_zero_amount_no_external_call
8. test_buy_credits_pending_to_owner_not_sender

### Status: COMPLETE - no remaining surviving mutations
