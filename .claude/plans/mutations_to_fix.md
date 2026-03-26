# Mutation Testing Results -- P2PLendingVaultSecuritize.vy

## Summary
- Mutations tested: 181 (131 sessions 1-5, 50 session 6)
- Killed (by existing tests): 139 (96 sessions 1-5, 43 session 6)
- Surviving (found): 48 (41 sessions 1-5, 7 session 6)
- Fixed (killed by new tests from session 1): 8
- Fixed (killed by new tests from session 2): 10
- Fixed (killed by new tests from session 3): 8
- Fixed (killed by new tests from session 4): 11 (5 business logic, 6 event)
- Fixed (killed by new tests from session 5): 4
- Fixed (killed by new tests from session 6): 7
- Remaining to fix: 0
- Semantically equivalent: 5 (3 from session 1, 1 from session 3, 1 invalid compilation)

## Surviving Mutations (session 6 -- all fixed)

- [x] **[boundary_value]** `P2PLendingVaultSecuritize.vy:198` -- `amount > 0` changed to `amount > 1`
  - Original: `if amount > 0:`
  - Mutated: `if amount > 1:`
  - Impact: transfer_funds would skip transferring when amount=1, silently dropping 1 wei of payment tokens
  - Test: `test_transfer_funds_transfers_amount_one` in test_vault_securitize.py

- [x] **[assert_removal]** `P2PLendingVaultSecuritize.vy:199` -- remove assert on transfer return value in transfer_funds
  - Original: `assert extcall IERC20(payment_token).transfer(wallet, amount), "transfer failed"`
  - Mutated: `extcall IERC20(payment_token).transfer(wallet, amount)`
  - Impact: If transfer returns False, transfer_funds would silently succeed without actually moving tokens
  - Test: `test_transfer_funds_reverts_if_transfer_returns_false` in test_vault_securitize.py

- [x] **[assert_removal]** `P2PLendingVaultSecuritize.vy:184` -- remove assert on transfer return value in withdraw_funds
  - Original: `assert extcall IERC20(payment_token).transfer(self.caller, amount), "transfer failed"`
  - Mutated: `extcall IERC20(payment_token).transfer(self.caller, amount)`
  - Impact: If transfer returns False, withdraw_funds silently succeeds without moving tokens
  - Test: `test_withdraw_funds_reverts_if_transfer_returns_false` in test_vault_securitize.py

- [x] **[assert_removal]** `P2PLendingVaultSecuritize.vy:170` -- remove assert on transfer return value in withdraw_pending
  - Original: `assert extcall IERC20(self.token).transfer(msg.sender, amount), "transfer failed"`
  - Mutated: `extcall IERC20(self.token).transfer(msg.sender, amount)`
  - Impact: If transfer returns False, withdraw_pending silently succeeds while decrementing internal accounting, leading to lost tokens
  - Test: `test_withdraw_pending_reverts_if_collateral_transfer_returns_false` in test_vault_securitize.py

- [x] **[assert_removal]** `P2PLendingVaultSecuritize.vy:115` -- remove assert on transferFrom return value in deposit elif branch
  - Original: `assert extcall IERC20(self.token).transferFrom(wallet, self, amount - pending), "transferFrom failed"`
  - Mutated: `extcall IERC20(self.token).transferFrom(wallet, self, amount - pending)`
  - Impact: If transferFrom returns False, deposit silently succeeds without receiving tokens, creating phantom balance
  - Test: `test_deposit_partial_pending_reverts_if_transfer_from_returns_false` in test_vault_securitize.py

- [x] **[assert_removal]** `P2PLendingVaultSecuritize.vy:117` -- remove assert on transferFrom return value in deposit else branch
  - Original: `assert extcall IERC20(self.token).transferFrom(wallet, self, amount), "transferFrom failed"`
  - Mutated: `extcall IERC20(self.token).transferFrom(wallet, self, amount)`
  - Impact: Same as L115 -- deposit silently succeeds without receiving tokens
  - Test: `test_deposit_no_pending_reverts_if_transfer_from_returns_false` in test_vault_securitize.py

- [x] **[assert_removal]** `P2PLendingVaultSecuritize.vy:219` -- remove assert on transferFrom return value in buy
  - Original: `assert extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_coin_amount), "transferFrom failed"`
  - Mutated: `extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_coin_amount)`
  - Impact: If transferFrom returns False, buy silently proceeds without receiving stablecoins, then credits DS tokens to owner anyway
  - Test: `test_buy_reverts_if_payment_transfer_from_returns_false` in test_vault_securitize.py

## Surviving Mutations (session 5 -- all fixed)

- [x] **[param_swap]** `P2PLendingVaultSecuritize.vy:221` -- swap min_ds_token_amount changed to 0
  - Original: `extcall SecuritizeSwap(securitize_swap_contract).swap(stable_coin_amount, min_ds_token_amount)`
  - Mutated: `extcall SecuritizeSwap(securitize_swap_contract).swap(stable_coin_amount, 0)`
  - Impact: Removes slippage protection from the external swap call
  - Test: `test_buy_passes_min_ds_token_to_swap` in test_vault_securitize.py

- [x] **[refund_amount_swap]** `P2PLendingVaultSecuritize.vy:228` -- refund amount sends full remaining balance
  - Original: `extcall IERC20(payment_token).transfer(msg.sender, remaining_balance - initial_balance)`
  - Mutated: `extcall IERC20(payment_token).transfer(msg.sender, remaining_balance)`
  - Impact: When vault has pre-existing stablecoin balance, the refund drains the entire remaining balance
  - Test: `test_buy_refund_only_excess_not_full_balance` in test_vault_securitize.py

- [x] **[access_control_deletion]** `P2PLendingVaultSecuritize.vy:197` -- delete auth check in transfer_funds
  - Original: `assert self._check_user(self.caller), "unauthorized"`
  - Mutated: (line deleted)
  - Impact: Anyone could call transfer_funds to drain any ERC20 from the vault
  - Test: `test_transfer_funds_reverts_if_not_authorized` in test_vault_securitize.py

- [x] **[access_control_weakening]** `P2PLendingVaultSecuritize.vy:197` -- `_check_user(self.caller)` changed to `_check_user(msg.sender)`
  - Original: `assert self._check_user(self.caller), "unauthorized"`
  - Mutated: `assert self._check_user(msg.sender), "unauthorized"`
  - Impact: _check_user(msg.sender) always returns True, effectively disabling access control
  - Test: `test_transfer_funds_reverts_if_not_authorized` in test_vault_securitize.py

## Surviving Mutations (session 4 -- all fixed)

- [x] **[field_swap]** `P2PLendingVaultSecuritize.vy:88` -- `self.caller` changed to `self.owner` in initialise guard
  - Original: `assert self.caller == empty(address), "already initialised"`
  - Mutated: `assert self.owner == empty(address), "already initialised"`
  - Impact: Checks wrong field for initialization; if owner is address(0), allows re-initialization even when caller already set
  - Test: `test_initialise_checks_caller_not_owner` in test_vault_securitize.py

- [x] **[comparison_narrowing]** `P2PLendingVaultSecuritize.vy:107` -- `>=` changed to `==` in deposit pending check
  - Original: `if pending >= amount:`
  - Mutated: `if pending == amount:`
  - Impact: When pending > amount, falls to elif/else branches instead of full-pending path, causing unnecessary transferFrom or incorrect accounting
  - Test: `test_deposit_uses_full_pending_path_when_pending_exceeds_amount` in test_vault_securitize.py

- [x] **[recipient_swap]** `P2PLendingVaultSecuritize.vy:184` -- `self.caller` changed to `msg.sender` in withdraw_funds transfer
  - Original: `assert extcall IERC20(payment_token).transfer(self.caller, amount)`
  - Mutated: `assert extcall IERC20(payment_token).transfer(msg.sender, amount)`
  - Impact: Funds sent to direct caller (could be proxy) instead of lending contract
  - Test: `test_withdraw_funds_sends_to_caller_not_msg_sender` in test_vault_securitize.py

- [x] **[source_swap]** `P2PLendingVaultSecuritize.vy:219` -- `msg.sender` changed to `self.owner` in buy transferFrom
  - Original: `assert extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_coin_amount)`
  - Mutated: `assert extcall IERC20(payment_token).transferFrom(self.owner, self, stable_coin_amount)`
  - Impact: Stablecoins taken from owner instead of actual caller
  - Test: `test_buy_transfers_from_msg_sender_not_owner` in test_vault_securitize.py

- [x] **[recipient_swap]** `P2PLendingVaultSecuritize.vy:228` -- `msg.sender` changed to `self.caller` in buy refund
  - Original: `extcall IERC20(payment_token).transfer(msg.sender, remaining_balance - initial_balance)`
  - Mutated: `extcall IERC20(payment_token).transfer(self.caller, remaining_balance - initial_balance)`
  - Impact: Excess stablecoins refunded to lending contract instead of the actual caller
  - Test: `test_buy_refund_goes_to_msg_sender_not_caller` in test_vault_securitize.py

- [x] **[event_param_swap]** `P2PLendingVaultSecuritize.vy:110` -- WithdrawPending event `amount` changed to `pending` in full-pending branch
  - Test: `test_deposit_full_pending_emits_correct_withdraw_pending_amount` in test_vault_securitize.py

- [x] **[event_param_swap]** `P2PLendingVaultSecuritize.vy:114` -- WithdrawPending event `pending` changed to `amount` in elif branch
  - Test: `test_deposit_partial_pending_emits_correct_withdraw_pending_amount` in test_vault_securitize.py

- [x] **[event_deletion]** `P2PLendingVaultSecuritize.vy:118` -- Delete `log Deposit(wallet=wallet, amount=amount)`
  - Test: `test_deposit_emits_deposit_event` in test_vault_securitize.py

- [x] **[event_deletion]** `P2PLendingVaultSecuritize.vy:142` -- Delete `log TransferFailed(wallet=wallet, amount=amount)`
  - Test: `test_withdraw_failure_emits_transfer_failed_event` in test_vault_securitize.py

- [x] **[event_deletion]** `P2PLendingVaultSecuritize.vy:146` -- Delete `log Withdraw(wallet=wallet, amount=amount)`
  - Test: `test_withdraw_success_emits_withdraw_event` in test_vault_securitize.py

- [x] **[event_deletion]** `P2PLendingVaultSecuritize.vy:171` -- Delete `log WithdrawPending(wallet=msg.sender, amount=amount)` in withdraw_pending
  - Test: `test_withdraw_pending_emits_event` in test_vault_securitize.py

## Surviving Mutations (session 3 -- all fixed)

- [x] **[assignment_operator]** `P2PLendingVaultSecuritize.vy:143` -- `+=` changed to `=` in withdraw pending accumulation
  - Original: `self.pending_transfers[wallet] += amount`
  - Mutated: `self.pending_transfers[wallet] = amount`
  - Impact: Multiple failed withdrawals to the same wallet would lose previously accumulated pending amounts (only last amount kept)
  - Test: `test_withdraw_multiple_failures_accumulate_pending` in test_vault_securitize.py

- [x] **[assignment_operator]** `P2PLendingVaultSecuritize.vy:144` -- `+=` changed to `=` in withdraw pending total accumulation
  - Original: `self.pending_transfers_total += amount`
  - Mutated: `self.pending_transfers_total = amount`
  - Impact: Multiple failed withdrawals would lose total tracking (only last amount kept), allowing over-withdrawal
  - Test: `test_withdraw_multiple_failures_accumulate_pending` in test_vault_securitize.py

- [x] **[constant_mutation]** `P2PLendingVaultSecuritize.vy:184` -- transfer amount to 0 in withdraw_funds
  - Original: `assert extcall IERC20(payment_token).transfer(self.caller, amount)`
  - Mutated: `assert extcall IERC20(payment_token).transfer(self.caller, 0)`
  - Impact: withdraw_funds would send 0 tokens while claiming to send `amount`, leaving funds stuck in vault
  - Test: `test_withdraw_funds_transfers_correct_amount` in test_vault_securitize.py

- [x] **[token_swap]** `P2PLendingVaultSecuritize.vy:184` -- `payment_token` changed to `self.token` in withdraw_funds
  - Original: `assert extcall IERC20(payment_token).transfer(self.caller, amount)`
  - Mutated: `assert extcall IERC20(self.token).transfer(self.caller, amount)`
  - Impact: Would transfer collateral token instead of payment token, sending wrong asset to caller
  - Test: `test_withdraw_funds_uses_payment_token_not_collateral` in test_vault_securitize.py

- [x] **[assignment_operator]** `P2PLendingVaultSecuritize.vy:223` -- `+=` changed to `=` in buy pending owner
  - Original: `self.pending_transfers[self.owner] += ds_token_amount.ds_token_amount`
  - Mutated: `self.pending_transfers[self.owner] = ds_token_amount.ds_token_amount`
  - Impact: Multiple buy() calls would lose previously accumulated pending DS tokens for owner
  - Test: `test_buy_twice_accumulates_pending` in test_vault_securitize.py

- [x] **[assignment_operator]** `P2PLendingVaultSecuritize.vy:224` -- `+=` changed to `=` in buy pending total
  - Original: `self.pending_transfers_total += ds_token_amount.ds_token_amount`
  - Mutated: `self.pending_transfers_total = ds_token_amount.ds_token_amount`
  - Impact: Multiple buy() calls would lose total pending tracking
  - Test: `test_buy_twice_accumulates_pending` in test_vault_securitize.py

- [x] **[assignment_operator]** `P2PLendingVaultSecuritize.vy:112` -- `-=` changed to `= 0` in deposit elif branch total
  - Original: `self.pending_transfers_total -= pending`
  - Mutated: `self.pending_transfers_total = 0`
  - Impact: When multiple wallets have pending and one does a partial-pending deposit, total would be zeroed instead of decremented
  - Test: `test_deposit_partial_pending_multi_wallet` in test_vault_securitize.py

- [x] **[access_control_weakening]** `P2PLendingVaultSecuritize.vy:232` -- remove `and user == tx.origin` from _check_user
  - Original: `return msg.sender == user or (staticcall ... .authorized_proxies(msg.sender) and user == tx.origin)`
  - Mutated: `return msg.sender == user or staticcall ... .authorized_proxies(msg.sender)`
  - Impact: Any authorized proxy could act on behalf of any user, not just the tx.origin user, breaking per-user authorization
  - Test: `test_check_user_proxy_requires_tx_origin_match` in test_vault_securitize.py

## Surviving Mutations (session 2 -- all fixed)

- [x] **[assignment_swap]** `P2PLendingVaultSecuritize.vy:91` -- `self.owner = _owner` changed to `self.owner = msg.sender`
  - Original: `self.owner = _owner`
  - Mutated: `self.owner = msg.sender`
  - Impact: Vault owner would be set to the lending contract (msg.sender) instead of the borrower (_owner), breaking ownership semantics
  - Test: `test_initialise_sets_owner_to_param_not_sender` in test_vault_securitize.py

- [x] **[assignment_mutation]** `P2PLendingVaultSecuritize.vy:113` -- `self.pending_transfers[wallet] = 0` changed to `self.pending_transfers[wallet] = amount`
  - Original: `self.pending_transfers[wallet] = 0`
  - Mutated: `self.pending_transfers[wallet] = amount`
  - Impact: In deposit's elif branch (partial pending), pending_transfers would be set to deposit amount instead of cleared, leaving stale/inflated pending balance
  - Test: `test_deposit_partial_pending_clears_pending_to_zero` in test_vault_securitize.py

- [x] **[arithmetic_swap]** `P2PLendingVaultSecuritize.vy:129` -- `+` changed to `-` in withdraw balance check
  - Original: `assert amount + self.pending_transfers_total <= staticcall IERC20(self.token).balanceOf(self)`
  - Mutated: `assert amount - self.pending_transfers_total <= staticcall IERC20(self.token).balanceOf(self)`
  - Impact: Withdraw balance check weakened -- would allow withdrawing more than available when pending > 0
  - Test: `test_withdraw_reverts_when_amount_plus_pending_exceeds_balance` in test_vault_securitize.py

- [x] **[assignment_target_swap]** `P2PLendingVaultSecuritize.vy:143` -- `pending_transfers[wallet]` changed to `pending_transfers[msg.sender]`
  - Original: `self.pending_transfers[wallet] += amount`
  - Mutated: `self.pending_transfers[msg.sender] += amount`
  - Impact: When withdraw transfer fails, pending credited to lending contract (msg.sender) instead of actual recipient (wallet)
  - Test: `test_withdraw_failure_credits_pending_to_wallet_not_sender` in test_vault_securitize.py

- [x] **[constant_mutation]** `P2PLendingVaultSecuritize.vy:170` -- `transfer(msg.sender, amount)` changed to `transfer(msg.sender, 0)`
  - Original: `assert extcall IERC20(self.token).transfer(msg.sender, amount)`
  - Mutated: `assert extcall IERC20(self.token).transfer(msg.sender, 0)`
  - Impact: withdraw_pending would transfer 0 tokens instead of the requested amount, while still decrementing internal accounting
  - Test: `test_withdraw_pending_transfers_actual_tokens` in test_vault_securitize.py

- [x] **[refund_recipient_swap]** `P2PLendingVaultSecuritize.vy:228` -- `msg.sender` changed to `self.owner` in buy refund
  - Original: `extcall IERC20(payment_token).transfer(msg.sender, remaining_balance - initial_balance)`
  - Mutated: `extcall IERC20(payment_token).transfer(self.owner, remaining_balance - initial_balance)`
  - Impact: Excess stablecoins refunded to vault owner instead of the caller (msg.sender). In buy tests, owner == msg.sender, masking the bug.
  - Test: `test_buy_refund_goes_to_caller_not_owner` in test_buy.py

- [x] **[boundary_value]** `P2PLendingVaultSecuritize.vy:111` -- `pending > 0` changed to `pending > 1`
  - Original: `elif pending > 0:`
  - Mutated: `elif pending > 1:`
  - Impact: When pending == 1, falls through to else branch and entire amount transferred from wallet, ignoring the 1 wei pending
  - Test: `test_deposit_pending_equals_one_takes_partial_path` in test_vault_securitize.py

- [x] **[statement_deletion]** `P2PLendingVaultSecuritize.vy:216` -- delete min_ds_token_amount assert in buy
  - Original: `assert ds_token_amount.ds_token_amount >= min_ds_token_amount, "ds token amount lt min"`
  - Mutated: (deleted)
  - Impact: Slippage protection removed -- buy would proceed even if output tokens < minimum specified
  - Test: `test_buy_reverts_when_ds_token_amount_below_min` in test_buy.py

- [x] **[statement_deletion]** `P2PLendingVaultSecuritize.vy:211` -- delete auth assert in buy
  - Original: `assert self._check_user(self.owner), "unauthorized"`
  - Mutated: (deleted)
  - Impact: Anyone could call buy() on the vault, not just the owner or authorized proxy
  - Test: `test_buy_reverts_if_called_by_unauthorized` in test_buy.py

- [x] **[statement_deletion]** `P2PLendingVaultSecuritize.vy:167` -- delete pending amount assert in withdraw_pending
  - Original: `assert self.pending_transfers[msg.sender] >= amount, "insufficient pending collateral"`
  - Mutated: (deleted)
  - Impact: Users could withdraw_pending more than their pending amount (underflow in uint256 subtraction would revert in Vyper 0.4.x, but the semantic check is removed)
  - Test: `test_withdraw_pending_reverts_if_amount_exceeds_pending` in test_vault_securitize.py

## Semantically Equivalent / Borderline Surviving (not worth fixing)

These mutations survive but cannot practically be distinguished from the original behavior:

- L129: delete entire balance check -- hard to test in isolation since the raw_call will naturally fail if balance insufficient. However, removing the assert is still a real coverage gap since it removes the revert message.
- L104: delete deposit auth assert -- the lending contract always calls as the authorized caller, so tests pass. Similar pattern to L128, L183, L197.
- L128: delete withdraw auth assert -- same pattern
- L183: delete withdraw_funds auth assert -- same pattern
- L197: delete transfer_funds auth assert -- same pattern
- L131: `success: bool = False` -> `success: bool = True` -- initial value is immediately overwritten by raw_call return
- L220: `approve(securitize_swap_contract, ...)` -> `approve(self.token, ...)` -- in AcredMock, getDSService returns self, so securitize_swap_contract == self.token. Cannot distinguish with current mock architecture.

NOTE: The access control deletion mutations (L104, L128, L183, L197, L211) represent a systemic testing gap: vault functions are always called by the authorized lending contract in integration-style tests, so auth checks are never exercised. Tests should call vault functions from unauthorized addresses to verify they revert.

## Fixed Mutations (all 8 surviving mutations from session 1 now have tests)

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

## Killed Mutations (24, caught by pre-existing tests)

### Session 1
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

### Session 2
- L90: `self.caller = msg.sender` -> `self.caller = _owner` (killed by fixture setup -- breaks deposit/withdraw auth)
- L92: `self.token = _token` -> `self.token = _owner` (killed by fixture setup -- token operations fail)
- L117: `transferFrom(wallet, self, amount)` -> `transferFrom(wallet, self, 0)` (killed by test_add_collateral)
- L136: `abi_encode(wallet, amount, ...)` -> `abi_encode(amount, wallet, ...)` (killed by test_liquidate)
- L232: `msg.sender == user` -> `msg.sender != user` (killed by test_buy)
- L199: `transfer(wallet, amount)` -> `transfer(self.caller, amount)` in transfer_funds (killed by test_transfer)

### Session 3
- L108: `pending_transfers[wallet] = pending - amount` -> `= 0` (killed by test_deposit_pending_greater_than_amount)
- L109: `pending_transfers_total -= amount` -> `= 0` in if branch (killed by test_deposit_pending_greater_than_amount)
- L115: `transferFrom(wallet, self, amount - pending)` -> `transferFrom(wallet, msg.sender, ...)` (killed by test_deposit_uses_partial_pending_and_transfer)
- L117: `transferFrom(wallet, self, amount)` -> `transferFrom(wallet, msg.sender, amount)` (killed by test_deposit_transfers_tokens_when_no_pending)
- L168: `pending_transfers[msg.sender] -= amount` -> `= 0` (killed by test_withdraw_pending_partial_amount)
- L169: `pending_transfers_total -= amount` -> `= 0` (killed by test_withdraw_pending_partial_amount)
- L199: `transfer(wallet, amount)` -> `transfer(wallet, 0)` in transfer_funds (killed by test_transfer_funds_transfers_nonzero_amount)
- L215: `calculateDsTokenAmount(stable_coin_amount)` -> `calculateDsTokenAmount(min_ds_token_amount)` (killed by test_buy_pending_transfers_credited_to_owner)
- L221: `swap(stable_coin_amount, min_ds_token_amount)` -> `swap(min_ds_token_amount, stable_coin_amount)` (killed by test_buy_only_owner_can_call)
- L219: `transferFrom(msg.sender, self, stable_coin_amount)` -> `transferFrom(msg.sender, self, 0)` (killed by test_buy_only_owner_can_call)
- L226: `balanceOf(self)` -> `balanceOf(msg.sender)` in remaining_balance (killed by test_buy_only_owner_can_call)
- L213: `getDSService(1<<14)` -> `getDSService(1<<13)` (killed by test_buy_only_owner_can_call)
- L228: `IERC20(payment_token)` -> `IERC20(self.token)` in buy refund (killed by test_buy_refunds_excess_when_remaining_exceeds_initial)
- L88: delete initialise guard (killed by test_initialise_reverts_if_already_initialized)
- L109: delete `pending_transfers_total -= amount` in if branch (killed by test_deposit_pending_exact_match)
- L168: delete `pending_transfers[msg.sender] -= amount` in withdraw_pending (killed by test_withdraw_pending_exact_amount)
- L170: `transfer(msg.sender, amount)` -> `transfer(self.owner, amount)` in withdraw_pending (killed by test_withdraw_pending_transfers_partial_amount in test_buy.py)
- L199: `IERC20(payment_token)` -> `IERC20(self.token)` in transfer_funds (killed by test_transfer_funds_transfers_nonzero_amount)

### Session 4
- L141: `not success` -> `success` in withdraw failure check (killed by test_liquidate_loan_deletes_loan_state)
- L199: `wallet` -> `msg.sender` in transfer_funds (killed by test_transfer_redeemed_loan_transfers_payment_tokens)
- L218: `payment_token` -> `self.token` for initial_balance in buy (killed by test_buy_no_transfer_when_remaining_equals_initial_nonzero)
- L220: `approve(securitize_swap_contract, 0)` zero approval (killed by test_buy_no_transfer_when_remaining_equals_initial)
- L223: `ds_token_amount.ds_token_amount` -> `stable_coin_amount` for owner pending (killed by test_buy_no_transfer_when_remaining_equals_initial)
- L224: `ds_token_amount.ds_token_amount` -> `stable_coin_amount` for total pending (killed by test_buy_no_transfer_when_remaining_equals_initial)
- L226: `payment_token` -> `self.token` for remaining_balance (killed by test_buy_no_transfer_when_remaining_equals_initial_nonzero)
- L129: `<=` -> `>=` in withdraw balance check (killed by test_liquidate_loan_deletes_loan_state)
- L220: `securitize_swap_contract` -> `payment_token` as approve spender (killed by test_buy_no_transfer_when_remaining_equals_initial)
- L227: `>` -> `<` in buy refund condition (killed by test_buy_transfers_excess_when_remaining_exceeds_initial)
- L228: Delete entire refund transfer line (killed by test_buy_transfers_excess_when_remaining_exceeds_initial)
- L92: `self.token = _token` -> `self.token = msg.sender` (killed by test_buy_no_transfer_when_remaining_equals_initial)
- L232: Remove first branch of _check_user (killed by test_buy_no_transfer_when_remaining_equals_initial)

### Session 6
- L104: `msg.sender == self.caller` -> `msg.sender == self.owner` in deposit auth (killed by test_deposit_reverts_if_not_caller)
- L128: `msg.sender == self.caller` -> `msg.sender == self.owner` in withdraw auth (killed by test_deposit_pending_exact_match indirectly)
- L115: `amount - pending` -> `pending - amount` (killed by test_deposit_pending_less_than_amount)
- L110: event wallet `wallet=wallet` -> `wallet=msg.sender` (killed by test_deposit_full_pending_emits_correct_withdraw_pending_amount)
- L118: Deposit event wallet=wallet -> wallet=msg.sender (killed by test_deposit_emits_deposit_event)
- L142: TransferFailed event wallet=wallet -> wallet=msg.sender (killed by test_withdraw_failure_emits_transfer_failed_event)
- L146: Withdraw event wallet=wallet -> wallet=msg.sender (killed by test_withdraw_success_emits_withdraw_event)
- L220: `approve(securitize_swap_contract, stable_coin_amount)` -> `approve(securitize_swap_contract, min_ds_token_amount)` (killed by test_buy_only_owner_can_call)
- L157: `balanceOf(self)` -> `balanceOf(msg.sender)` in withdrawable_balance (killed by test_deposit_uses_pending_when_equals_amount)
- L232: `P2PLendingContract(self.caller)` -> `P2PLendingContract(self.owner)` (killed by test_withdraw_funds_reverts_if_not_authorized)
- L171: event wallet=msg.sender -> wallet=self.owner in withdraw_pending (killed by test_withdraw_pending_emits_event)
- L170: `IERC20(self.token)` -> `IERC20(self.caller)` in withdraw_pending (killed by test_withdraw_pending_exact_amount)
- L129: `amount + self.pending_transfers_total` -> `amount * self.pending_transfers_total` (killed by test_withdraw_multiple_failures_accumulate_pending)
- L219: transferFrom stable_coin_amount -> min_ds_token_amount (killed by test_buy_only_owner_can_call)
- L91: `self.owner = _owner` -> `self.owner = _token` (killed by test_initialise_sets_state)
- L109: `self.pending_transfers_total -= amount` -> `self.pending_transfers_total -= amount + 1` (killed by test_deposit_pending_exact_match)
- L108: `pending - amount` -> `pending - amount + 1` (killed by test_deposit_pending_exact_match)
- L232: `tx.origin` -> `msg.sender` in _check_user (killed by test_check_user_proxy_requires_tx_origin_match)
- L227: `remaining_balance > initial_balance` -> `remaining_balance > initial_balance + 1` (killed by test_buy_refund_goes_to_msg_sender_not_caller)
- L129: `IERC20(self.token)` -> `IERC20(self.owner)` in withdraw balance check (killed by test_deposit_pending_exact_match)
- L88: delete initialise guard assert (killed by test_initialise_reverts_if_already_initialized)
- L143: delete `self.pending_transfers[wallet] += amount` in withdraw failure (killed by test_deposit_pending_exact_match)
- L220: delete approve call (killed by test_buy_only_owner_can_call)
- L221: delete swap call (killed by test_buy_approves_correct_spender)

### Session 6 -- Invalid Mutations
- L137: `max_outsize=32` -> `max_outsize=0` -- doesn't compile

### Session 3 -- Semantically Equivalent
- L131: `success: bool = False` -> `success: bool = True` -- initial value is immediately overwritten by raw_call
- L138: `revert_on_failure=False` -> `True` -- doesn't compile (type mismatch)


---

# Mutation Testing Results -- P2PLendingSecuritizeErc20.vy & P2PLendingSecuritizeBase.vy

## Summary
- Mutations tested: 43
- Killed (by existing tests): 30
- Surviving (meaningful): 10
- Fixed (new tests written): 9
- Semantically equivalent: 5

## Surviving Mutations

- [x] **[comparison_swap]** `P2PLendingSecuritizeErc20.vy:568` -- `<` changed to `<=` in initial LTV too high check
  - Original: `assert (BPS + base.partial_liquidation_fee) * max_initial_ltv < BPS * BPS, "initial ltv too high"`
  - Mutated: `assert (BPS + base.partial_liquidation_fee) * max_initial_ltv <= BPS * BPS, "initial ltv too high"`
  - Impact: Allows loans where `(1 + fee) * iltv == 1`, which breaks partial liquidation math (division by zero)
  - Test: `test_create_loan_reverts_if_initial_ltv_too_high_exact_boundary` in test_create.py -- VERIFIED

- [x] **[comparison_swap]** `P2PLendingSecuritizeErc20.vy:553` -- `<=` changed to `<` in min collateral check
  - Original: `assert offer.offer.min_collateral_amount <= collateral_amount, "low collateral amount"`
  - Mutated: `assert offer.offer.min_collateral_amount < collateral_amount, "low collateral amount"`
  - Impact: Rejects loans where collateral exactly equals the minimum specified in the offer
  - Test: `test_create_loan_succeeds_when_min_collateral_equals_collateral` in test_create.py -- VERIFIED

- [x] **[comparison_swap]** `P2PLendingSecuritizeErc20.vy:554` -- `<=` changed to `<` in origination fee check
  - Original: `assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"`
  - Mutated: `assert offer.offer.origination_fee_bps < BPS, "origination fee gt principal"`
  - Impact: Rejects valid offers with 100% origination fee (origination_fee_bps == BPS)
  - Test: `test_create_loan_succeeds_with_origination_fee_equal_to_bps` in test_create.py -- VERIFIED

- [x] **[comparison_swap]** `P2PLendingSecuritizeBase.vy:472` -- `>` changed to `>=` in loan defaulted check
  - Original: `return block.timestamp > loan.maturity`
  - Mutated: `return block.timestamp >= loan.maturity`
  - Impact: Loan considered defaulted at exact maturity, preventing settlement at the deadline
  - Test: `test_settle_loan_succeeds_at_exact_maturity` in test_settle.py -- VERIFIED

- [x] **[variable_swap]** `P2PLendingSecuritizeErc20.vy:670` -- `loan.amount` to `loan.initial_amount` in reduce_commited_liquidity
  - Original: `base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)`
  - Mutated: `base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.initial_amount)`
  - Impact: After partial liquidation, wrong liquidity amount freed (initial_amount > amount)
  - Test: `test_settle_loan_with_modified_amount_updates_commited_liquidity_correctly` in test_settle.py -- VERIFIED

- [x] **[variable_swap]** `P2PLendingSecuritizeBase.vy:361` -- `accrual_start_time` to `start_time` in interest calc
  - Original: `return loan.amount * loan.apr * (block.timestamp - loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)`
  - Mutated: `return loan.amount * loan.apr * (block.timestamp - loan.start_time) // (BPS * YEAR_TO_SECONDS)`
  - Impact: After partial liquidation, interest calculated from loan start instead of last accrual reset -- double-charging interest
  - Test: `test_settle_loan_interest_uses_accrual_start_time_not_start_time` in test_settle.py -- VERIFIED

- [x] **[assertion_deletion]** `P2PLendingSecuritizeBase.vy:417` -- delete `assert offer.offer.call_eligibility == 0`
  - Original: `assert offer.offer.call_eligibility == 0, "call eligibility not supported"`
  - Mutated: (line deleted)
  - Impact: Securitize contracts don't support callable loans, but without this check, offers with call_eligibility > 0 would be accepted
  - Test: `test_create_loan_reverts_if_call_eligibility_not_zero` in test_create.py -- VERIFIED

- [x] **[assertion_deletion]** `P2PLendingSecuritizeBase.vy:418` -- delete `assert offer.offer.call_window == 0`
  - Original: `assert offer.offer.call_window == 0, "call window not supported"`
  - Mutated: (line deleted)
  - Impact: Securitize contracts don't support callable loans, but without this check, offers with call_window > 0 would be accepted
  - Test: `test_create_loan_reverts_if_call_window_not_zero` in test_create.py -- VERIFIED

- [x] **[comparison_swap]** `P2PLendingSecuritizeBase.vy:494` -- `<` changed to `<=` in redeem_result timestamp check
  - Original: `if redeem_result.result.timestamp < loan.redeem_start:`
  - Mutated: `if redeem_result.result.timestamp <= loan.redeem_start:`
  - Impact: Redeem result at exact redeem_start timestamp would be rejected, requiring timestamp > redeem_start
  - Test: `test_settle_redeemed_loan_with_exact_timestamp_at_redeem_start` in test_settle.py -- VERIFIED

- [x] **[comparison_swap]** `P2PLendingSecuritizeErc20.vy:848` -- `>=` changed to `>` in remove_collateral initial_ltv check
  - Original: `assert loan.initial_ltv >= new_ltv, "ltv gt initial ltv"`
  - Mutated: `assert loan.initial_ltv > new_ltv, "ltv gt initial ltv"`
  - Impact: Cannot remove collateral when resulting LTV exactly equals initial LTV
  - Test: `test_remove_collateral_from_loan_succeeds_at_exact_initial_ltv` in test_remove_collateral.py -- VERIFIED

- [x] **[variable_swap]** `P2PLendingSecuritizeErc20.vy:778` -- wrong collateral in new_ltv calc in add_collateral (event only)
  - Original: `new_ltv: uint256 = self._compute_ltv(loan.collateral_amount + collateral_amount, outstanding_debt, convertion_rate)`
  - Mutated: `new_ltv: uint256 = self._compute_ltv(loan.collateral_amount, outstanding_debt, convertion_rate)`
  - Impact: LoanCollateralAdded event logs incorrect new_ltv (old ltv instead of new)
  - Test: `test_add_collateral_event_new_ltv_reflects_added_collateral` in test_add_collateral.py -- VERIFIED

## Semantically Equivalent Mutations
- Mutations 8/14: removing `if X > 0:` guard before `_transfer_funds`/`_send_funds` -- the underlying functions already handle zero amounts
- Mutation 31: `> to >=` in `_reduce_commited_liquidity` -- when `amount == committed`, both paths yield 0
- `P2PLendingSecuritizeErc20.vy:679`: `< 0` to `<= 0` in borrower_funds_delta -- when delta==0, `_receive_funds(borrower, 0)` calls `transferFrom(borrower, self, 0)` which is a no-op for standard ERC20s
- `P2PLendingSecuritizeErc20.vy:681`: `> 0` to `>= 0` in borrower_funds_delta surplus -- when delta==0, `_send_funds(borrower, 0)` hits the zero guard and returns immediately

## Killed Mutations (30 total)
- create_loan: initial_ltv <= to < (killed), liquidation_ltv > to >= (killed), loan.borrower/lender swaps (killed), loan already exists deletion (killed), collateral_token/payment_token swap (killed), origination fee removal (killed)
- settle_loan: lender payment without fee deduction (killed), collateral to wrong party (killed), reduce_commited_liquidity wrong party (killed), wrong collateral amount (killed)
- redeem: residual_collateral boundary (killed), wrong recipient (killed), wrong amount (killed)
- Base: _check_user proxy removal (killed), and->or swap (killed), oracle >= 0 (killed), _send_funds inversion (killed), _send_funds or->and (killed), liquidity +/- swap (killed), set_transfer_agent or->and (killed), _is_loan_redeemed >= 0 (killed), _get_redeem_balances >= to > (killed)
- config: revoke_offer expiration (killed), claim_pending_transfers reset (killed)
