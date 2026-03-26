---
name: vault_securitize_session6
description: Mutation testing session 6 for P2PLendingVaultSecuritize.vy - 50 new mutations tested, 7 surviving all fixed with 7 new tests (2026-03-25)
type: project
---

# P2PLendingVaultSecuritize.vy Mutation Testing - Session 6

## Date: 2026-03-25

## Summary
- 50 new mutations tested (continuing from sessions 1-5's 131)
- 43 killed by existing tests
- 7 surviving -- all fixed with 7 new tests in test_vault_securitize.py
- Total across all sessions: 181 mutations tested

## Key Findings

### Systematic assert-removal gap (CRITICAL)
All 6 assert-on-return-value checks for ERC20 transfer/transferFrom survived removal. The root cause: all test mocks (WETH9Mock, AcredMock, USDC) always return True from transfer() and transferFrom(). No test used a token that returns False to verify the contract properly checks the return value.

Functions affected:
- transfer_funds L199: `assert extcall ... .transfer(wallet, amount)`
- withdraw_funds L184: `assert extcall ... .transfer(self.caller, amount)`
- withdraw_pending L170: `assert extcall ... .transfer(msg.sender, amount)`
- deposit elif L115: `assert extcall ... .transferFrom(wallet, self, amount - pending)`
- deposit else L117: `assert extcall ... .transferFrom(wallet, self, amount)`
- buy L219: `assert extcall ... .transferFrom(msg.sender, self, stable_coin_amount)`

### Boundary off-by-one in transfer_funds
Changing `amount > 0` to `amount > 1` survived because all existing tests used amounts >= 100. No test ever called transfer_funds with amount=1.

## Tests Created (7)
All added to `tests/p2p_erc20_securitize/unit/test_vault_securitize.py`:
1. test_transfer_funds_transfers_amount_one -- kills L198 boundary mutation
2. test_transfer_funds_reverts_if_transfer_returns_false -- kills L199 assert removal (uses failing_transfer_erc20)
3. test_withdraw_funds_reverts_if_transfer_returns_false -- kills L184 assert removal (uses inline false-transfer mock)
4. test_withdraw_pending_reverts_if_collateral_transfer_returns_false -- kills L170 assert removal (uses failing_transfer_erc20)
5. test_deposit_partial_pending_reverts_if_transfer_from_returns_false -- kills L115 assert removal (uses false_transfer_from_erc20 fixture)
6. test_deposit_no_pending_reverts_if_transfer_from_returns_false -- kills L117 assert removal (uses false_transfer_from_erc20 fixture)
7. test_buy_reverts_if_payment_transfer_from_returns_false -- kills L219 assert removal (uses inline false-transferFrom mock)

## New Fixtures Created
- `false_transfer_from_erc20` -- ERC20 where transferFrom() always returns False, transfer() returns True. Has balanceOf support. Used for deposit assert-removal tests.

## Killed Mutations (43 new, by existing tests)
Key killed mutations:
- L104: `msg.sender == self.caller` -> `msg.sender == self.owner` (killed by test_deposit_reverts_if_not_caller)
- L128: `msg.sender == self.caller` -> `msg.sender == self.owner` (killed indirectly)
- L115: `amount - pending` -> `pending - amount` (killed by test_deposit_pending_less_than_amount)
- L110, L114, L118, L142, L146, L171: event wallet param swaps (killed by event assertion tests)
- L220: approve amount: `stable_coin_amount` -> `min_ds_token_amount` (killed by test_buy_only_owner_can_call)
- L157: `balanceOf(self)` -> `balanceOf(msg.sender)` (killed by test_deposit_uses_pending_when_equals_amount)
- L232: `P2PLendingContract(self.caller)` -> `P2PLendingContract(self.owner)` (killed by test_withdraw_funds_reverts_if_not_authorized)
- L232: `tx.origin` -> `msg.sender` (killed by test_check_user_proxy_requires_tx_origin_match)
- L129: `amount + pending` -> `amount * pending` (killed by test_withdraw_multiple_failures_accumulate_pending)
- L129: `IERC20(self.token)` -> `IERC20(self.owner)` (killed by test_deposit_pending_exact_match)
- L88: delete initialise guard (killed by test_initialise_reverts_if_already_initialized)
- L108, L109: off-by-one mutations (killed by test_deposit_pending_exact_match)
- L143: delete pending_transfers[wallet] += amount (killed by test_deposit_pending_exact_match)
- L220: delete approve call (killed by test_buy_only_owner_can_call)
- L221: delete swap call (killed by test_buy_approves_correct_spender)
- Plus more event, recipient, source, and amount swap mutations

## Invalid Mutations (1)
- L137: `max_outsize=32` -> `max_outsize=0` -- doesn't compile

## Patterns Found
- **Return value assertion gap**: When all test mocks return True, removing `assert` on extcall return values is invisible. Need dedicated false-returning mocks.
- **Boundary testing at 1**: Tests using large amounts (100+) miss off-by-one boundaries. Always test with amount=1 for functions that guard against amount=0.
- **Contract is now very thoroughly covered**: After 181 mutations across 6 sessions, with all surviving mutations fixed, the P2PLendingVaultSecuritize.vy contract has comprehensive unit test coverage. The only known semantic equivalence is L220 (approve self.token vs securitize_swap_contract) due to AcredMock's getDSService returning self.
