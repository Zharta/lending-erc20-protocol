---
name: vault_securitize_session5
description: Mutation testing session 5 for P2PLendingVaultSecuritize.vy - 45 new mutations tested, 4 surviving all fixed with new tests (2026-03-24)
type: project
---

# P2PLendingVaultSecuritize.vy Mutation Testing - Session 5

## Date: 2026-03-24

## Summary
- 45 new mutations tested (continuing from sessions 1-4's 86)
- 41 killed by existing tests
- 4 surviving -- all fixed with 3 new tests in test_vault_securitize.py
- Total across all sessions: 131 mutations tested

## Key Findings

### transfer_funds access control gap (CRITICAL)
The transfer_funds function had NO test verifying its auth check. Both deleting the auth assert entirely and weakening it to `_check_user(msg.sender)` (always True) survived. This is a critical gap because transfer_funds can drain any ERC20 from the vault.

### Swap minOutAmount not verified
The vault calls `swap(stable_coin_amount, min_ds_token_amount)` but no test verified that `min_ds_token_amount` was actually passed to the swap. Changing it to 0 survived because all tests either use min_ds_token_amount=0 or the AcredMock's swap happens to succeed anyway.

### Buy refund amount not properly tested with pre-existing balance
Changing `remaining_balance - initial_balance` to `remaining_balance` survived because all existing buy() tests start with zero payment token balance in the vault. When initial_balance=0, the subtraction makes no difference.

## Tests Created (3)
All added to `tests/p2p_erc20_securitize/unit/test_vault_securitize.py`:
1. test_transfer_funds_reverts_if_not_authorized -- kills L197 auth deletion AND weakening
2. test_buy_passes_min_ds_token_to_swap -- kills L221 swap min=0 (uses custom DS token mock with last_swap_min_out tracking)
3. test_buy_refund_only_excess_not_full_balance -- kills L228 refund full balance (uses pre-existing vault USDC balance)

## Killed Mutations (41 new, by existing tests)
- L110: event wallet swap (msg.sender) -- killed by test_deposit_full_pending_emits_correct_withdraw_pending_amount
- L114: event wallet swap (msg.sender) -- killed by test_deposit_partial_pending_emits_correct_withdraw_pending_amount
- L118: Deposit event wallet swap -- killed by test_deposit_emits_deposit_event
- L142: TransferFailed event wallet swap -- killed by test_withdraw_failure_emits_transfer_failed_event
- L146: Withdraw event wallet swap -- killed by test_withdraw_success_emits_withdraw_event
- L115: transferFrom source swap (wallet->msg.sender) -- killed by multiple deposit tests
- L117: transferFrom source swap (wallet->msg.sender) -- killed massively
- L129: <= to == -- killed by multiple tests
- L141: remove NOT from response check -- killed by test_withdraw_failure_credits_pending_to_wallet_not_sender
- L220: approve amount swap (min_ds_token_amount) -- killed by multiple buy tests
- L215: calculateDsTokenAmount(0) -- killed by multiple buy tests
- L171: WithdrawPending wallet swap (self.owner) -- killed by test_withdraw_pending_emits_event
- L108: pending - amount -> pending - 1 -- killed by test_deposit_pending_exact_match
- L227: remaining > initial -> remaining > 0 -- killed by test_buy_skips_refund_when_remaining_equals_initial_nonzero
- L228: remaining_balance - initial_balance -> remaining_balance (full balance) -- survived (now fixed)
- L219: transferFrom to msg.sender instead of self -- killed by multiple buy tests
- L199: transfer amount-1 -- killed by test_transfer_funds_transfers_nonzero_amount
- L184: transfer amount-1 -- killed by test_withdraw_funds_transfers_correct_amount
- L213: getDSService(1<<15) -- killed by multiple buy tests
- L220: approve max_value(uint256) -- killed by test_buy_approves_correct_spender
- L220: IERC20(self.token) approve -- killed by multiple buy tests (now killed, was previously semantically equivalent!)
- L157: balanceOf(msg.sender) -- killed by test_withdrawable_balance_subtracts_pending
- L226: balanceOf(msg.sender) -- killed by multiple buy tests
- L168: pending -= amount-1 -- killed by test_withdraw_pending_exact_amount
- L115: transferFrom amount instead of amount-pending -- killed by multiple deposit tests
- L129: delete balance check -- killed by test_withdraw_reverts_when_amount_plus_pending_exceeds_balance
- L104: delete deposit auth -- killed by test_deposit_reverts_if_not_caller
- L128: delete withdraw auth -- killed by test_withdraw_reverts_if_not_caller
- L183: delete withdraw_funds auth -- killed by test_withdraw_funds_reverts_if_not_authorized
- L211: delete buy auth -- killed by test_buy_only_owner_can_call, test_buy_reverts_if_unauthorized_caller
- L197: _check_user(self.owner) instead of self.caller -- killed by test_transfer_funds_skips_zero_amount
- L183: _check_user(msg.sender) -- killed by test_withdraw_funds_reverts_if_not_authorized
- L232: authorized_proxies on self.owner instead of self.caller -- killed by multiple buy tests
- L136: method_id swap transfer->approve -- killed by multiple tests
- Plus several more event param, amount, and source/target swap mutations

## Patterns Found
- **Access control tests must use unauthorized callers**: The key gap was that transfer_funds tests always used the authorized caller_addr, so auth check mutations survived.
- **Pre-existing balance needed for refund tests**: Without pre-existing balance, `remaining - initial == remaining - 0 == remaining`, masking refund amount mutations.
- **Custom mocks for parameter verification**: To verify swap parameters are forwarded correctly, a custom mock that records parameters is needed (AcredMock doesn't expose this).
- **Previously semantically equivalent mutation L220 (approve self.token) is now KILLED**: New tests from later sessions caught it, showing mutation equivalence can be transient.
