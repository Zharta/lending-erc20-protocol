---
name: vault_securitize_session3
description: Mutation testing session 3 for P2PLendingVaultSecuritize.vy - 20 new mutations tested, 8 fixed (2026-03-19)
type: project
---

# P2PLendingVaultSecuritize.vy Mutation Testing - Session 3

## Date: 2026-03-19

## Summary
- 20 new mutations tested (continuing from sessions 1-2's 42)
- 11 killed by existing tests
- 9 surviving initially, 8 fixed with new tests, 1 semantically equivalent
- Total across all sessions: 62 mutations tested

## Surviving Mutations Fixed (8)
1. L143: `pending_transfers[wallet] += amount` -> `= amount` -- killed by test_withdraw_multiple_failures_accumulate_pending
2. L144: `pending_transfers_total += amount` -> `= amount` -- killed by test_withdraw_multiple_failures_accumulate_pending
3. L184: `transfer(self.caller, amount)` -> `transfer(self.caller, 0)` -- killed by test_withdraw_funds_transfers_correct_amount
4. L184: `IERC20(payment_token)` -> `IERC20(self.token)` -- killed by test_withdraw_funds_uses_payment_token_not_collateral
5. L223: `pending_transfers[self.owner] += ds` -> `= ds` -- killed by test_buy_twice_accumulates_pending
6. L224: `pending_transfers_total += ds` -> `= ds` -- killed by test_buy_twice_accumulates_pending
7. L112: `pending_transfers_total -= pending` -> `= 0` -- killed by test_deposit_partial_pending_multi_wallet
8. L232: remove `and user == tx.origin` -- killed by test_check_user_proxy_requires_tx_origin_match

## Semantically Equivalent (1)
- L220: `approve(securitize_swap_contract, ...)` -> `approve(self.token, ...)` -- in AcredMock getDSService returns self, so both addresses are the same. Would need a mock where DS token != swap contract to distinguish.

## Killed Mutations (11 new)
- L108: `pending_transfers[wallet] = pending - amount` -> `= 0` (killed by test_deposit_pending_greater_than_amount)
- L109: `pending_transfers_total -= amount` -> `= 0` in if branch (killed by test_deposit_pending_greater_than_amount)
- L115: transferFrom to msg.sender instead of self (killed by test_deposit_uses_partial_pending_and_transfer)
- L117: transferFrom to msg.sender in else branch (killed by test_deposit_transfers_tokens_when_no_pending)
- L168: `pending_transfers[msg.sender] -= amount` -> `= 0` (killed by test_withdraw_pending_partial_amount)
- L169: `pending_transfers_total -= amount` -> `= 0` (killed by test_withdraw_pending_partial_amount)
- L199: transfer(wallet, 0) (killed by test_transfer_funds_transfers_nonzero_amount)
- L215: calculateDsTokenAmount(min_ds_token_amount) wrong param (killed by test_buy_pending_transfers_credited_to_owner)
- L221: swap param swap (killed by test_buy_only_owner_can_call)
- L213: getDSService(1<<13) wrong service ID (killed by test_buy_only_owner_can_call)
- L88: delete initialise guard (killed by test_initialise_reverts_if_already_initialized)
- Plus 7 more (L109 delete, L168 delete, L170 wrong recipient, L219 amount=0, L226 wrong address, L228 wrong token, L199 wrong token)

## Invalid Mutations (1)
- L138: revert_on_failure=True -- doesn't compile

## Patterns Found
- **Accumulation gaps**: Tests that only do an operation once cannot distinguish `+=` from `=`. Need tests with multiple operations.
- **withdraw_funds undertested**: Only auth was tested, not actual transfer semantics (amount, token type).
- **Mock limitations**: AcredMock implements both SecuritizeDSToken and SecuritizeSwap (getDSService returns self), making it impossible to test approve spender mutations. Would need a separate swap mock contract.
- **Proxy tx.origin**: The `and user == tx.origin` guard in _check_user was untested because existing proxy tests always used tx.origin == user.

## New Tests Created (7)
All added to `tests/p2p_erc20_securitize/unit/test_vault_securitize.py`:
1. test_withdraw_multiple_failures_accumulate_pending
2. test_withdraw_funds_transfers_correct_amount
3. test_withdraw_funds_uses_payment_token_not_collateral
4. test_buy_twice_accumulates_pending
5. test_buy_approves_correct_spender (note: doesn't kill the mutation due to mock limitation)
6. test_deposit_partial_pending_multi_wallet
7. test_check_user_proxy_requires_tx_origin_match
