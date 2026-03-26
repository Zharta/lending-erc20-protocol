---
name: securitize_erc20_base_session1
description: Mutation testing of P2PLendingSecuritizeErc20.vy and P2PLendingSecuritizeBase.vy -- 43 mutations tested, 30 killed by existing tests, 11 surviving fixed with new tests, 5 semantically equivalent
type: project
---

## Session: 2026-03-26

### Contracts Tested
- `contracts/v1/P2PLendingSecuritizeErc20.vy` -- main entry point for Securitize lending
- `contracts/v1/P2PLendingSecuritizeBase.vy` -- shared state and internal logic

### Functions Tested
- `create_loan` (lines 520-644): validation checks, offer parsing, LTV computation
- `settle_loan` (lines 648-710): settlement flow, interest calc, committed liquidity, borrower funds delta
- `redeem` (lines 714-750): redemption flow, collateral transfer
- `add_collateral_to_loan` (lines 768-810): collateral addition, LTV event
- `remove_collateral_from_loan` (lines 823-880): collateral removal, LTV boundary
- `_compute_settlement_interest` (Base line 361): interest calculation
- `_is_loan_defaulted` (Base line 472): maturity check
- `_check_offer_validity` (Base lines 413-418): offer validation including call eligibility/window
- `_is_loan_redeem_concluded` (Base line 494): redeem timestamp validation
- `_reduce_commited_liquidity`, `_get_oracle_rate`, `_send_funds`, `_get_redeem_balances`, `_check_user`, `_is_loan_redeemed`

### Results Summary
- Total mutations tested: 43
- Killed by existing tests: 30
- Surviving (meaningful): 11 (all fixed with new tests)
- Semantically equivalent: 5

### New Tests Written (11 tests across 4 files)

**test_create.py** (5 tests):
- `test_create_loan_succeeds_when_min_collateral_equals_collateral` -- kills <= to < on line 553
- `test_create_loan_succeeds_with_origination_fee_equal_to_bps` -- kills <= to < on line 554
- `test_create_loan_reverts_if_initial_ltv_too_high_exact_boundary` -- kills < to <= on line 568
- `test_create_loan_reverts_if_call_eligibility_not_zero` -- kills assertion deletion Base line 417
- `test_create_loan_reverts_if_call_window_not_zero` -- kills assertion deletion Base line 418

**test_settle.py** (4 tests):
- `test_settle_loan_succeeds_at_exact_maturity` -- kills > to >= on Base line 472
- `test_settle_redeemed_loan_with_exact_timestamp_at_redeem_start` -- kills < to <= on Base line 494
- `test_settle_loan_with_modified_amount_updates_commited_liquidity_correctly` -- kills loan.amount to loan.initial_amount on line 670
- `test_settle_loan_interest_uses_accrual_start_time_not_start_time` -- kills accrual_start_time to start_time on Base line 361

**test_remove_collateral.py** (1 test):
- `test_remove_collateral_from_loan_succeeds_at_exact_initial_ltv` -- kills >= to > on line 848

**test_add_collateral.py** (1 test):
- `test_add_collateral_event_new_ltv_reflects_added_collateral` -- kills variable swap on line 778

### Key Technique: Modifying Loan State for Post-Partial-Liquidation Testing
For mutations involving `loan.amount` vs `loan.initial_amount` and `accrual_start_time` vs `start_time`, the tests:
1. Create a loan via the normal flow
2. Use `replace_namedtuple_field()` to modify loan fields
3. Compute the new hash with `compute_securitize_loan_hash(modified_loan)`
4. Directly set the hash in storage: `p2p_usdc_weth.eval(f"base.loans[{loan_id_hex}] = {hash_hex}")`
Note: bytes32 values must be hex-encoded (e.g., `"0x" + modified_loan.id.hex()`) for Vyper eval.

### Semantically Equivalent Mutations
- Line 679: `< 0` to `<= 0` in borrower_funds_delta -- zero-amount transferFrom is no-op for standard ERC20s
- Line 681: `> 0` to `>= 0` in borrower_funds_delta -- _send_funds has zero guard
- Mutations 8/14 (from VaultSecuritize): removing zero guards before transfers
- Mutation 31: `> to >=` in _reduce_commited_liquidity boundary

### Remaining Contracts Not Yet Tested
- `P2PLendingSecuritizeLiquidation.vy` -- liquidation facet
- `P2PLendingSecuritizeRefinance.vy` -- refinance + maturity extension facet
- `P2PLendingErc20.vy` / `P2PLendingBase.vy` -- standard (non-securitize) contracts
- `P2PLendingVaultedErc20.vy` / `P2PLendingVaultedBase.vy` -- vaulted contracts
- `P2PLendingLiquidation.vy` / `P2PLendingRefinance.vy` -- standard facets
- `P2PLendingVaultedLiquidation.vy` / `P2PLendingVaultedRefinance.vy` -- vaulted facets
