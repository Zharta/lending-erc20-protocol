---
name: vault_securitize_session4
description: Mutation testing session 4 for P2PLendingVaultSecuritize.vy - 24 new mutations tested, 11 surviving all fixed with new tests (2026-03-24)
type: project
---

# P2PLendingVaultSecuritize.vy Mutation Testing - Session 4

## Date: 2026-03-24

## Summary
- 24 new mutations tested (continuing from sessions 1-3's 62)
- 13 killed by existing tests
- 11 surviving -- all fixed with 11 new tests in test_vault_securitize.py
- Total across all sessions: 86 mutations tested

## Key Findings

### Proxy-based mutations were the major gap
The most important surviving mutations (L184, L219, L228) all involved swapping `msg.sender` with another address (`self.caller`, `self.owner`). These survived because all existing tests call vault functions directly (where msg.sender == owner or msg.sender == caller), never via proxy contracts.

**Solution**: Created a `VaultProxy` inline contract that calls vault functions. This separates msg.sender (proxy contract) from tx.origin (the user). This pattern is essential for testing `_check_user` proxy authorization paths.

### Initialization guard field swap (L88)
The initialise guard checked `self.caller == empty(address)`, but swapping to `self.owner` survived. Tests always initialized with a non-zero _owner parameter. Fixed by testing initialise with `_owner=empty(address)`.

### Event coverage was absent
None of the existing tests checked for event emission on the vault contract itself. 6 event mutations (deletions + parameter swaps) survived. Fixed with direct event assertion tests using `vault.get_logs()`.

## Tests Created (11)
All added to `tests/p2p_erc20_securitize/unit/test_vault_securitize.py`:
1. test_initialise_checks_caller_not_owner -- kills L88 field swap
2. test_deposit_uses_full_pending_path_when_pending_exceeds_amount -- kills L107 >= to ==
3. test_withdraw_funds_sends_to_caller_not_msg_sender -- kills L184 recipient swap (via proxy)
4. test_buy_transfers_from_msg_sender_not_owner -- kills L219 source swap (via proxy)
5. test_buy_refund_goes_to_msg_sender_not_caller -- kills L228 refund recipient swap (via proxy)
6. test_deposit_emits_deposit_event -- kills L118 event deletion
7. test_withdraw_success_emits_withdraw_event -- kills L146 event deletion
8. test_withdraw_failure_emits_transfer_failed_event -- kills L142 event deletion
9. test_withdraw_pending_emits_event -- kills L171 event deletion
10. test_deposit_full_pending_emits_correct_withdraw_pending_amount -- kills L110 event param swap
11. test_deposit_partial_pending_emits_correct_withdraw_pending_amount -- kills L114 event param swap

## Patterns Learned
- **Proxy testing requires intermediary contracts**: In boa, `sender=X` sets both msg.sender and tx.origin to X. To test proxy paths (msg.sender != tx.origin), use an actual Vyper proxy contract.
- **Event testing with get_logs()**: Use `vault.get_logs()` and filter by `type(e).__name__` to check event emissions.
- **Blacklist trick for failed withdrawals**: WETH9Mock's blacklist feature can force raw_call transfers to fail, useful for creating pending_transfers state.
