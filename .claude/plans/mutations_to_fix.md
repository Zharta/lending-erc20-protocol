# Mutation Testing Results -- P2PLendingVaultSecuritize.vy

## Summary
- Mutations tested: 22
- Killed (by existing tests): 14
- Surviving (found): 8
- Fixed (killed by new tests): 8

## Fixed Mutations (all 8 surviving mutations now have tests)

- [x] **[boundary_comparison]** `P2PLendingVaultSecuritize.vy:107` -- `>=` changed to `>` in deposit full-pending branch
  - Original: `if pending >= amount:`
  - Mutated: `if pending > amount:`
  - Impact: When pending == amount exactly, the deposit would take the partial-pending path instead of the full-pending path, causing an unnecessary transferFrom(wallet, self, 0) call
  - Test: `test_deposit_with_pending_equals_amount` -- uses ERC20 that reverts on zero-amount transferFrom

- [x] **[arithmetic_swap]** `P2PLendingVaultSecuritize.vy:157` -- `-` changed to `+` in withdrawable_balance
  - Original: `return staticcall IERC20(self.token).balanceOf(self) - self.pending_transfers_total`
  - Mutated: `return staticcall IERC20(self.token).balanceOf(self) + self.pending_transfers_total`
  - Impact: withdrawable_balance would return inflated balance (balance + pending instead of balance - pending)
  - Test: `test_withdrawable_balance_subtracts_pending` -- verifies result equals balance - pending, not balance + pending

- [x] **[boundary_comparison]** `P2PLendingVaultSecuritize.vy:167` -- `>=` changed to `>` in withdraw_pending
  - Original: `assert self.pending_transfers[msg.sender] >= amount`
  - Mutated: `assert self.pending_transfers[msg.sender] > amount`
  - Impact: Users cannot withdraw their exact full pending amount
  - Test: `test_withdraw_pending_exact_full_amount` -- withdraws exactly pending_transfers[sender]

- [x] **[access_control_swap]** `P2PLendingVaultSecuritize.vy:211` -- `self.owner` changed to `self.caller` in buy auth check
  - Original: `assert self._check_user(self.owner), "unauthorized"`
  - Mutated: `assert self._check_user(self.caller), "unauthorized"`
  - Impact: Would authorize lending contract (caller) instead of borrower (owner) to buy DS tokens
  - Test: `test_buy_only_owner_can_call` -- vault where owner != caller, verifies only owner can buy

- [x] **[boundary_comparison]** `P2PLendingVaultSecuritize.vy:216` -- `>=` changed to `>` in buy min_ds_token check
  - Original: `assert ds_token_amount.ds_token_amount >= min_ds_token_amount`
  - Mutated: `assert ds_token_amount.ds_token_amount > min_ds_token_amount`
  - Impact: Buy would revert when calculated ds_token_amount == min_ds_token_amount exactly
  - Test: `test_buy_with_exact_min_ds_token_amount` -- uses 1:1 oracle rate, passes exact min

- [x] **[condition_removal]** `P2PLendingVaultSecuritize.vy:198` -- `amount > 0` changed to `amount >= 0` in transfer_funds
  - Original: `if amount > 0:`
  - Mutated: `if amount >= 0:` (always true for uint256)
  - Impact: Would call ERC20 transfer even for amount=0, which can fail on some tokens
  - Test: `test_transfer_funds_zero_amount_no_external_call` -- uses token that reverts on transfer(0)

- [x] **[assignment_target_swap]** `P2PLendingVaultSecuritize.vy:223` -- `self.owner` changed to `msg.sender` in buy pending_transfers credit
  - Original: `self.pending_transfers[self.owner] += ds_token_amount.ds_token_amount`
  - Mutated: `self.pending_transfers[msg.sender] += ds_token_amount.ds_token_amount`
  - Impact: DS tokens would be credited to caller (proxy) instead of vault owner (borrower)
  - Test: `test_buy_credits_pending_to_owner_not_sender` -- calls buy through proxy, verifies credit goes to owner

- [x] **[comparison_swap]** `P2PLendingVaultSecuritize.vy:232` -- `==` changed to `!=` in _check_user tx.origin check
  - Original: `user == tx.origin`
  - Mutated: `user != tx.origin`
  - Impact: Proxy authorization would accept wrong user, breaking access control
  - Test: `test_buy_credits_pending_to_owner_not_sender` -- exercises proxy path where user == tx.origin must hold

## Killed Mutations (14, caught by pre-existing tests)
- L112: `pending_transfers_total -= pending` -> `pending_transfers_total -= amount` (killed by test_deposit_with_partial_pending)
- L109: `pending_transfers_total -= amount` -> `pending_transfers_total -= pending` (killed by test_deposit_with_pending_covers_full_amount)
- L129: `<=` -> `<` in withdraw balance check (killed by test_withdraw_creates_pending_on_transfer_failure)
- L141: `or` -> `and` in withdraw failure check (killed by test_withdraw_creates_pending_on_transfer_failure)
- L183: `_check_user(self.caller)` -> `_check_user(self.owner)` in withdraw_funds (killed by test_liquidate)
- L197: `_check_user(self.caller)` -> `_check_user(self.owner)` in transfer_funds (killed by test_transfer_loan)
- L88: `==` -> `!=` in initialise guard (killed by fixture setup)
- L184: `transfer(self.caller)` -> `transfer(self.owner)` in withdraw_funds (killed by test_liquidate)
- L104: `==` -> `!=` in deposit auth (killed by test_deposit_with_pending)
- L108: `pending - amount` -> `amount - pending` (killed by test_deposit_with_pending)
- L128: `==` -> `!=` in withdraw auth (killed by test_withdraw_creates_pending)
- L144: delete `pending_transfers_total += amount` in withdraw fail (killed by test_withdraw_creates_pending)
- L169: delete `pending_transfers_total -= amount` in withdraw_pending (killed by test_withdraw_pending)
- L115: `amount - pending` -> `amount + pending` (killed by test_deposit_with_partial_pending)
- L213: `getDSService(1<<14)` -> `getDSService(0)` (killed by test_buy)
- L227: `>` -> `>=` in buy refund check (killed by test_buy_no_transfer)
- L228: `remaining - initial` -> `initial - remaining` (killed by test_buy_transfers_excess)
- L232: `or` -> `and` in _check_user (killed by test_buy)
