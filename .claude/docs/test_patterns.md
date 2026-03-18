# Test Patterns

Rules and expectations for writing tests in this project. Focus is on what makes a test correct and meaningful, not on describing existing fixtures (read the conftest files for that).

## 1. Unit Tests

Unit tests cover **all code paths** for every contract function. External contracts (ERC20, oracle, KYC validator) are mocked.

### Split by effect and precondition

Each test targets **one specific effect** or **one revert condition**. Name tests as `test_{function}_{effect}` or `test_{function}_reverts_if_{condition}`:

```
test_settle_loan_removes_loan                             # state change: loan deleted
test_settle_loan_logs_event                               # event emission
test_settle_loan_pays_lender                              # balance: lender receives funds
test_settle_loan_pays_protocol_fees                       # balance: protocol wallet receives fees
test_settle_loan_transfers_collateral_to_borrower         # balance: collateral returned
test_settle_loan_updates_commited_liquidity               # state change: liquidity tracking
test_settle_loan_reverts_if_loan_invalid                  # revert: bad loan hash
test_settle_loan_reverts_if_loan_defaulted                # revert: past maturity
test_settle_loan_reverts_if_loan_called                   # revert: called + window expired
test_settle_loan_reverts_if_loan_already_settled          # revert: double settle
test_settle_loan_reverts_if_funds_not_approved            # revert: insufficient approval
```

This means a single contract function may have 10+ unit tests. That's expected — each test is small, focused, and independently verifiable.

### Revert tests cover every code path

For **loan validation reverts**, use `get_loan_mutations()` to test every possible single-field corruption:

```python
def test_settle_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    for loan in get_loan_mutations(ongoing_loan_usdc_weth):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.settle_loan(loan, sender=ongoing_loan_usdc_weth.borrower)
```

For **condition-specific reverts**, one test per condition with the specific error message:

```python
with boa.reverts("loan defaulted"):      # always use the exact revert string
with boa.reverts("offer expired"):
with boa.reverts():                       # bare only for ERC20 failures with no custom message
```

## 2. Integration Tests

Integration tests run on a **mainnet fork** with real contracts (real USDC, real WETH, real Chainlink oracles). Only **core functionalities** are tested — no admin/config tests like `test_change_protocol_wallet`.

### Split by function and precondition, check all effects in one test

Since fork setup is expensive, integration tests check **all effects in a single test**. Split only when preconditions differ meaningfully:

```
test_create_loan                          # checks state, event, balances all at once
test_replace_loan_lender_same_lender      # precondition: same lender refinance
test_replace_loan_lender_different_lender # precondition: different lender refinance
```

A single integration test should verify:
- Loan state (hash matches expected Loan)
- Event fields (all of them)
- Token balances (all parties: borrower, lender, protocol, liquidator, vault)
- Committed liquidity changes

```python
def test_create_loan(p2p_usdc_weth, ...):
    # capture before-state
    borrower_balance_before = usdc.balanceOf(borrower)
    lender_balance_before = usdc.balanceOf(lender)
    origination_fee = offer.origination_fee_bps * principal // BPS

    # execute
    loan_id = p2p_usdc_weth.create_loan(...)

    # ALL effects verified in one test:
    # 1. state
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    # 2. event
    event = get_last_event(p2p_usdc_weth, "LoanCreated")
    assert event.id == loan_id
    assert event.amount == principal
    # ... all event fields
    # 3. balances
    assert weth.balanceOf(p2p_usdc_weth.wallet_to_vault(borrower)) == collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee
    # 4. liquidity
    assert p2p_usdc_weth.commited_liquidity(liquidity_key) == principal
```

## 3. Assertion Quality

### Assert preconditions

Before testing an effect, assert that the test setup actually creates the right conditions. This catches broken fixtures and ensures the test is meaningful:

```python
def test_liquidate_loan_not_defaulted_works_if_partial_liquidation_not_possible(...):
    oracle.set_rate(int(oracle.rate() / 5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.liquidation_ltv  # precondition: LTV exceeds threshold
    # ... now test the actual behavior
```

```python
def test_liquidate_loan_with_surplus_transfers_collateral_in_excess_to_borrower(...):
    oracle.set_rate(oracle.rate() * 2, sender=oracle.owner())
    liquidation = calc_full_liquidation(loan, usdc, weth, oracle)
    assert liquidation.remaining_collateral_value >= liquidation.outstanding_debt  # precondition: surplus
    assert liquidation.send_to_borrower > 0  # precondition: borrower gets something back
    # ... now test
```

Without these, a silent fixture change could make the test pass vacuously.

### Exact expected values, never weak assertions

Compute the exact expected value independently (using `conftest_base.py` helpers) and assert equality:

```python
# GOOD: exact expected value computed independently
interest = loan.get_interest(now)
protocol_fee = interest * loan.protocol_settlement_fee // BPS
expected_lender_amount = loan.amount + interest - protocol_fee
assert usdc.balanceOf(loan.lender) == lender_balance_before + expected_lender_amount

# BAD: weak assertion that hides bugs
assert usdc.balanceOf(loan.lender) >= lender_balance_before
```

Never use a contract's own return value as the expected value (circular validation):

```python
# BAD: circular — only proves view and mutation agree, not that either is correct
result = contract.simulate_partial_liquidation(loan)
contract.partially_liquidate_loan(loan, sender=liquidator)
assert some_state == result.some_field

# GOOD: independent calculation
principal_written_off, collateral_claimed, liquidation_fee = calc_partial_liquidation(loan, usdc, weth, oracle, now)
contract.partially_liquidate_loan(loan, sender=liquidator)
updated_loan = replace_namedtuple_field(loan,
    amount=loan.amount + loan.get_interest(now) - principal_written_off,
    collateral_amount=loan.collateral_amount - collateral_claimed - liquidation_fee,
    accrual_start_time=now,
)
assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(loan.id)
```

### Verify all state changes, not just "no revert"

A test that just calls a function without assertions proves nothing. Every happy-path test must assert specific outcomes — at minimum one of: state change, event emission, balance change.

After loan deletion (settle, liquidate), always verify cleanup:
```python
assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
assert weth.balanceOf(p2p_usdc_weth.wallet_to_vault(borrower)) == 0
```

## 4. Flag Test Blindspots

When writing a test, if you cannot assert an exact expected value — either because the calculation is unclear, the docs are ambiguous, or there's conflicting information — **do not write a weak assertion or skip it**. Instead, flag it explicitly:

```python
def test_settle_loan_pays_lender(...):
    # ... setup and execute ...

    # If the formula for settlement amount is unclear from docs:
    assert False, "post condition missing: exact lender payment amount unknown — README says X but contract code suggests Y"

    # Or if a specific effect can't be verified:
    # TODO: verify protocol fee is correctly split between protocol_wallet and lender
    assert False, "post condition missing: unable to determine protocol fee split from available docs"
```

This applies to:
- **Missing info**: The README/docs don't specify what the expected behavior is for a particular edge case.
- **Conflicting info**: The README says one thing but the contract code appears to do another.
- **Untestable effects**: An effect exists but there's no way to observe it from the test (e.g., internal storage not exposed via a getter).

A failing `assert False` with a clear comment is **far more valuable** than a passing test that doesn't actually verify correctness. It makes blindspots visible and actionable.
Again, we **never want weak assertions or skipping tests**. If it can't be fixed right away, flag it as blindspots, at least we know we have to fix it.

## 5. Formula Reference

All formulas are implemented independently in `conftest_base.py`. Tests MUST use these (or reimplement the same math) to compute expected values — never hardcode derived values.

### Interest
```
interest = apr * amount * (timestamp - accrual_start_time) // (365 * 24 * 3600 * BPS)
```

### LTV
```
ltv = principal * BPS * oracle_decimals * collateral_token_decimals // (collateral_amount * oracle_rate * payment_token_decimals)
```
When `oracle_reverse=True`, swap `oracle_rate` and `oracle_decimals`.

### Fees
```
origination_fee_amount = origination_fee_bps * principal // BPS
protocol_upfront_fee_amount = protocol_upfront_fee_bps * principal // BPS
protocol_settlement_fee_amount = protocol_settlement_fee_bps * interest // BPS
```

### Partial liquidation
```
outstanding_debt = amount + interest
collateral_value = collateral_amount * rate_num * payment_decimals // (rate_den * collateral_decimals)
principal_written_off = (outstanding_debt * BPS - collateral_value * initial_ltv) * BPS // (BPS * BPS - (BPS + partial_liquidation_fee) * initial_ltv)
collateral_claimed = principal_written_off * rate_den * collateral_decimals // (rate_num * payment_decimals)
liquidation_fee = collateral_claimed * partial_liquidation_fee // BPS
```

### Full liquidation
```
outstanding_debt = amount + interest
liquidation_fee = min(collateral_amount, outstanding_debt * full_liquidation_fee * rate_den * collateral_decimals // (rate_num * payment_decimals * BPS))
remaining_collateral = collateral_amount - liquidation_fee
remaining_collateral_value = remaining_collateral * rate_num * payment_decimals // (rate_den * collateral_decimals)
shortfall = max(0, outstanding_debt - remaining_collateral_value)
protocol_settlement_fee_amount = min(protocol_settlement_fee * interest // BPS, remaining_collateral_value)
receive_from_liquidator = min(remaining_collateral_value, outstanding_debt)
send_to_lender = receive_from_liquidator - protocol_settlement_fee_amount
collateral_for_debt = outstanding_debt * rate_den * collateral_decimals // (rate_num * payment_decimals)
send_to_liquidator = min(collateral_amount, collateral_for_debt + liquidation_fee)
send_to_borrower = collateral_amount - send_to_liquidator
```
