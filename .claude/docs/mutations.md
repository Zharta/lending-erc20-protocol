# Vyper Mutation Testing Permutations

A catalog of valid code mutations for Vyper smart contracts, useful for identifying missing test coverage. Each permutation describes a small, syntactically valid change that should cause at least one test to fail if the mutated code path is properly covered.

Reference: [Vyper Language Documentation](https://docs.vyperlang.org/en/stable/)

---

## Table of Contents

1. [Comparison Operator Mutations](#1-comparison-operator-mutations)
2. [Arithmetic Operator Mutations](#2-arithmetic-operator-mutations)
3. [Boolean Logic Mutations](#3-boolean-logic-mutations)
4. [Constant and Literal Mutations](#4-constant-and-literal-mutations)
5. [Boundary Value Mutations](#5-boundary-value-mutations)
6. [Assignment Mutations](#6-assignment-mutations)
7. [Control Flow Mutations](#7-control-flow-mutations)
8. [Function Parameter Swap Mutations](#8-function-parameter-swap-mutations)
9. [Assert and Revert Mutations](#9-assert-and-revert-mutations)
10. [Built-in Function Mutations](#10-built-in-function-mutations)
11. [External Call Mutations](#11-external-call-mutations)
12. [Type Conversion Mutations](#12-type-conversion-mutations)
13. [Event Logging Mutations](#13-event-logging-mutations)
14. [Access Control Mutations](#14-access-control-mutations)
15. [State Variable Mutations](#15-state-variable-mutations)
16. [Ternary Expression Mutations](#16-ternary-expression-mutations)
17. [Empty/Default Value Mutations](#17-emptydefault-value-mutations)
18. [Hash and Cryptographic Mutations](#18-hash-and-cryptographic-mutations)
19. [Loop Mutations](#19-loop-mutations)
20. [Return Value Mutations](#20-return-value-mutations)
21. [Statement Deletion Mutations](#21-statement-deletion-mutations)
22. [Statement Reordering Mutations](#22-statement-reordering-mutations)

---

## 1. Comparison Operator Mutations

Replace each comparison operator with every other valid comparison operator.

| Original | Mutations |
|----------|-----------|
| `<`  | `<=`, `>`, `>=`, `==`, `!=` |
| `<=` | `<`, `>`, `>=`, `==`, `!=` |
| `>`  | `>=`, `<`, `<=`, `==`, `!=` |
| `>=` | `>`, `<`, `<=`, `==`, `!=` |
| `==` | `!=`, `<`, `<=`, `>`, `>=` |
| `!=` | `==`, `<`, `<=`, `>`, `>=` |

**Examples:**

```vyper
# Original
assert block.timestamp >= loan.start_time + loan.call_eligibility

# Mutant: >= → >
assert block.timestamp > loan.start_time + loan.call_eligibility

# Mutant: >= → <=
assert block.timestamp <= loan.start_time + loan.call_eligibility
```

```vyper
# Original
assert offer.offer.expiration > block.timestamp

# Mutant: > → >=
assert offer.offer.expiration >= block.timestamp

# Mutant: > → <
assert offer.offer.expiration < block.timestamp
```

```vyper
# Original
assert base.loans[loan.id] == empty(bytes32)

# Mutant: == → !=
assert base.loans[loan.id] != empty(bytes32)
```

**Key insight:** The most critical mutation is between strict and non-strict comparisons (`>` vs `>=`, `<` vs `<=`), as these test boundary conditions.

---

## 2. Arithmetic Operator Mutations

Replace each arithmetic operator with every other valid operator of compatible return type.

| Original | Mutations |
|----------|-----------|
| `+` | `-`, `*`, `//`, `%` |
| `-` | `+`, `*`, `//`, `%` |
| `*` | `+`, `-`, `//`, `%` |
| `//` | `*`, `+`, `-`, `%` |
| `%` | `+`, `-`, `*`, `//` |
| `**` | `*`, `+` |

**Examples:**

```vyper
# Original: interest accrual formula
interest: uint256 = loan.amount * loan.apr * (block.timestamp - loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)

# Mutant: first * → +
interest: uint256 = (loan.amount + loan.apr) * (block.timestamp - loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)

# Mutant: // → *
interest: uint256 = loan.amount * loan.apr * (block.timestamp - loan.accrual_start_time) * (BPS * YEAR_TO_SECONDS)

# Mutant: - → +
interest: uint256 = loan.amount * loan.apr * (block.timestamp + loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)
```

```vyper
# Original: fee calculation
origination_fee_amount = offer.offer.origination_fee_bps * principal // BPS

# Mutant: * → +
origination_fee_amount = offer.offer.origination_fee_bps + principal // BPS

# Mutant: // → *
origination_fee_amount = offer.offer.origination_fee_bps * principal * BPS
```

```vyper
# Original: decimal exponentiation
collateral_token_decimals = 10 ** convert(staticcall IERC20Detailed(_collateral_token).decimals(), uint256)

# Mutant: ** → *
collateral_token_decimals = 10 * convert(staticcall IERC20Detailed(_collateral_token).decimals(), uint256)
```

---

## 3. Boolean Logic Mutations

### 3a. Logical Operator Replacement

| Original | Mutations |
|----------|-----------|
| `and` | `or` |
| `or` | `and` |
| `not x` | `x` (remove negation) |
| `x` | `not x` (add negation) |

**Examples:**

```vyper
# Original
assert offer.offer.call_window != 0 or offer.offer.call_eligibility == 0

# Mutant: or → and
assert offer.offer.call_window != 0 and offer.offer.call_eligibility == 0
```

```vyper
# Original
assert not self.revoked_offers[offer_id]

# Mutant: remove not
assert self.revoked_offers[offer_id]
```

```vyper
# Original
assert msg.sender == base.owner or msg.sender == base.transfer_agent

# Mutant: or → and
assert msg.sender == base.owner and msg.sender == base.transfer_agent
```

### 3b. Condition Replacement

| Original | Mutations |
|----------|-----------|
| `condition` | `True` |
| `condition` | `False` |

```vyper
# Original
if loan.call_time > 0 and block.timestamp > loan.call_time + loan.call_window:

# Mutant: replace entire condition with True
if True:

# Mutant: replace entire condition with False
if False:
```

### 3c. Sub-expression Negation

In compound boolean expressions, negate individual sub-expressions.

```vyper
# Original
assert (offer.offer.borrower == empty(address) or offer.offer.borrower == borrower)

# Mutant: negate first sub-expression
assert (offer.offer.borrower != empty(address) or offer.offer.borrower == borrower)

# Mutant: negate second sub-expression
assert (offer.offer.borrower == empty(address) or offer.offer.borrower != borrower)
```

---

## 4. Constant and Literal Mutations

### 4a. Numeric Literal Mutations

| Original | Mutations |
|----------|-----------|
| `0` | `1`, `max_value(uint256)` |
| `1` | `0`, `2` |
| `N` (any positive integer) | `N + 1`, `N - 1`, `0`, `1` |
| `BPS` (10000) | `BPS - 1`, `BPS + 1`, `0`, `1` |

**Examples:**

```vyper
# Original
assert offer.offer.duration > 0

# Mutant: 0 → 1
assert offer.offer.duration > 1
```

```vyper
# Original
call_time: uint256 = 0

# Mutant: 0 → 1
call_time: uint256 = 1
```

### 4b. Named Constant Replacement

Replace named constants with related constants of the same type.

```vyper
# Original
interest = loan.amount * loan.apr * delta // (BPS * YEAR_TO_SECONDS)

# Mutant: BPS → BPS + 1
interest = loan.amount * loan.apr * delta // ((BPS + 1) * YEAR_TO_SECONDS)
```

---

## 5. Boundary Value Mutations

### 5a. Off-by-One in Comparisons

| Original | Mutations |
|----------|-----------|
| `x > 0` | `x > 1`, `x >= 0` |
| `x >= threshold` | `x > threshold`, `x >= threshold + 1`, `x >= threshold - 1` |
| `x <= limit` | `x < limit`, `x <= limit + 1`, `x <= limit - 1` |
| `x < max` | `x <= max`, `x < max - 1` |

**Examples:**

```vyper
# Original
assert answer > 0, "invalid oracle rate"

# Mutant: > 0 → >= 0
assert answer >= 0, "invalid oracle rate"

# Mutant: > 0 → > 1
assert answer > 1, "invalid oracle rate"
```

```vyper
# Original
assert new_partial_liquidation_fee <= BPS

# Mutant: <= BPS → < BPS
assert new_partial_liquidation_fee < BPS

# Mutant: <= BPS → <= BPS - 1
assert new_partial_liquidation_fee <= BPS - 1
```

### 5b. Inclusive/Exclusive Boundary Swap

```vyper
# Original
commited_liquidity + amount <= offer.offer.available_liquidity

# Mutant: <= → <
commited_liquidity + amount < offer.offer.available_liquidity
```

---

## 6. Assignment Mutations

### 6a. Operator Replacement in Compound Assignments

| Original | Mutations |
|----------|-----------|
| `x += y` (or `x = x + y`) | `x -= y`, `x = x * y`, `x = y` |
| `x -= y` (or `x = x - y`) | `x += y`, `x = x * y`, `x = y` |

**Examples:**

```vyper
# Original
self.pending_transfers[_to] += _amount

# Mutant: += → -=
self.pending_transfers[_to] -= _amount

# Mutant: += → = (direct assignment, losing accumulated value)
self.pending_transfers[_to] = _amount
```

```vyper
# Original
self.vault_count[wallet] += 1

# Mutant: += 1 → += 2
self.vault_count[wallet] += 2

# Mutant: += → -=
self.vault_count[wallet] -= 1
```

### 6b. Assignment Value Mutations

| Original | Mutations |
|----------|-----------|
| `x = value` | `x = 0`, `x = empty(type)` |
| `x = empty(bytes32)` | skip the assignment entirely |
| `x = True` | `x = False` |
| `x = False` | `x = True` |

**Examples:**

```vyper
# Original
self.revoked_offers[offer_id] = True

# Mutant: True → False
self.revoked_offers[offer_id] = False
```

```vyper
# Original
base.loans[loan.id] = empty(bytes32)

# Mutant: remove the line (loan not cleared)
# (line deleted)
```

---

## 7. Control Flow Mutations

### 7a. If/Else Branch Swap

Swap the bodies of if and else blocks.

```vyper
# Original
if collateral_amount > loan.collateral_amount:
    base._receive_collateral(loan.borrower, collateral_amount - loan.collateral_amount, collateral_token)
elif collateral_amount < loan.collateral_amount:
    base._send_collateral(loan.borrower, loan.collateral_amount - collateral_amount, collateral_token)

# Mutant: swap if/elif bodies
if collateral_amount > loan.collateral_amount:
    base._send_collateral(loan.borrower, loan.collateral_amount - collateral_amount, collateral_token)
elif collateral_amount < loan.collateral_amount:
    base._receive_collateral(loan.borrower, collateral_amount - loan.collateral_amount, collateral_token)
```

### 7b. Condition Inversion

Negate the condition in if-statements.

```vyper
# Original
if offer.offer.max_iltv == 0:
    max_initial_ltv = self._compute_ltv(...)

# Mutant: invert condition
if offer.offer.max_iltv != 0:
    max_initial_ltv = self._compute_ltv(...)
```

### 7c. Branch Removal

Remove an entire if/elif/else branch.

```vyper
# Original
if loan.call_eligibility == 0:
    return loan.maturity
elif loan.call_time > 0:
    return min(loan.maturity, loan.call_time + loan.call_window)
else:
    return min(loan.maturity, max(block.timestamp, loan.start_time + loan.call_eligibility) + loan.call_window)

# Mutant: remove elif branch (fall through to else)
if loan.call_eligibility == 0:
    return loan.maturity
else:
    return min(loan.maturity, max(block.timestamp, loan.start_time + loan.call_eligibility) + loan.call_window)
```

### 7d. Early Return Insertion/Removal

```vyper
# Original: function continues after a check
assert base._is_loan_valid(loan), "invalid loan"
assert not base._is_loan_defaulted(loan), "loan defaulted"
# ... rest of function

# Mutant: insert early return after first assert
assert base._is_loan_valid(loan), "invalid loan"
return  # early exit skips remaining logic
```

---

## 8. Function Parameter Swap Mutations

Swap parameters of the same type in function calls. This is one of the most powerful mutation categories because it catches cases where argument order matters but tests pass coincidentally.

### 8a. Same-Type Argument Swap

```vyper
# Original: transfer from borrower to lender
extcall IERC20(payment_token).transferFrom(loan.borrower, loan.lender, amount)

# Mutant: swap borrower/lender (both address type)
extcall IERC20(payment_token).transferFrom(loan.lender, loan.borrower, amount)
```

```vyper
# Original
base._send_payment(loan.lender, lender_amount, loan.payment_token)
base._send_payment(base.protocol_wallet, protocol_fee, loan.payment_token)

# Mutant: swap payment recipients
base._send_payment(base.protocol_wallet, lender_amount, loan.payment_token)
base._send_payment(loan.lender, protocol_fee, loan.payment_token)
```

```vyper
# Original: receive collateral from one party, send to another
base._receive_collateral(loan.borrower, collateral_delta, collateral_token)
base._send_collateral(loan.lender, collateral_delta, collateral_token)

# Mutant: swap the address arguments
base._receive_collateral(loan.lender, collateral_delta, collateral_token)
base._send_collateral(loan.borrower, collateral_delta, collateral_token)
```

### 8b. Amount Argument Swap

```vyper
# Original
base._send_payment(loan.lender, lender_amount, payment_token)
base._send_payment(base.protocol_wallet, protocol_fee, payment_token)

# Mutant: swap amounts between calls
base._send_payment(loan.lender, protocol_fee, payment_token)
base._send_payment(base.protocol_wallet, lender_amount, payment_token)
```

```vyper
# Original: LTV computation with numerator/denominator
collateral_claimed = principal_written_off * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)

# Mutant: swap numerator and denominator
collateral_claimed = principal_written_off * convertion_rate.numerator * collateral_token_decimals // (convertion_rate.denominator * payment_token_decimals)
```

```vyper
# Original: swap payment_token_decimals and collateral_token_decimals
collateral_claimed = principal_written_off * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)

# Mutant: swap decimal scaling factors
collateral_claimed = principal_written_off * convertion_rate.denominator * payment_token_decimals // (convertion_rate.numerator * collateral_token_decimals)
```

### 8c. Token Address Swap

```vyper
# Original
base._receive_payment(loan.borrower, amount, payment_token)
base._receive_collateral(loan.borrower, collateral, collateral_token)

# Mutant: swap token addresses (payment_token ↔ collateral_token)
base._receive_payment(loan.borrower, amount, collateral_token)
base._receive_collateral(loan.borrower, collateral, payment_token)
```

### 8d. Hash Input Field Swap

```vyper
# Original: loan ID computation
return keccak256(concat(
    convert(loan.borrower, bytes32),
    convert(loan.lender, bytes32),
    convert(loan.start_time, bytes32),
    loan.offer_id,
))

# Mutant: swap borrower and lender in hash
return keccak256(concat(
    convert(loan.lender, bytes32),
    convert(loan.borrower, bytes32),
    convert(loan.start_time, bytes32),
    loan.offer_id,
))
```

### 8e. Signature Parameter Swap

```vyper
# Original
signer = ecrecover(message_hash, signed_offer.signature.v, signed_offer.signature.r, signed_offer.signature.s)

# Mutant: swap r and s
signer = ecrecover(message_hash, signed_offer.signature.v, signed_offer.signature.s, signed_offer.signature.r)
```

### 8f. KYC Validation Parameter Swap

```vyper
# Original
staticcall base.KYCValidator(kyc_validator_addr).check_validations_pair(borrower_kyc, lender_kyc)

# Mutant: swap borrower_kyc and lender_kyc
staticcall base.KYCValidator(kyc_validator_addr).check_validations_pair(lender_kyc, borrower_kyc)
```

### 8g. Min/Max Argument Swap

```vyper
# Original
return min(loan.maturity, loan.call_time + loan.call_window)

# Mutant: swap min arguments (semantically different if one is always smaller)
return min(loan.call_time + loan.call_window, loan.maturity)
# Note: min(a,b) == min(b,a), so this only matters if the function has side effects
# More useful: min → max
return max(loan.maturity, loan.call_time + loan.call_window)
```

---

## 9. Assert and Revert Mutations

### 9a. Assert Removal

Remove individual assert statements entirely.

```vyper
# Original
assert base._is_loan_valid(loan), "invalid loan"
assert not base._is_loan_defaulted(loan), "loan defaulted"
assert base._check_user(loan.borrower), "not borrower"

# Mutant: remove one assert
assert base._is_loan_valid(loan), "invalid loan"
# (assert removed)
assert base._check_user(loan.borrower), "not borrower"
```

### 9b. Assert Condition Inversion

```vyper
# Original
assert current_ltv >= loan.liquidation_ltv, "ltv lt liquidation ltv"

# Mutant: invert condition
assert current_ltv < loan.liquidation_ltv, "ltv lt liquidation ltv"
```

### 9c. Assert to Pass

Replace assert with pass.

```vyper
# Original
assert msg.sender == base.owner

# Mutant
pass  # anyone can call this
```

### 9d. Raise Removal

Remove raise statements in error paths.

```vyper
# Original
if some_error_condition:
    raise "error message"

# Mutant: remove raise (function continues in error state)
if some_error_condition:
    pass
```

---

## 10. Built-in Function Mutations

### 10a. Min/Max Swap

| Original | Mutation |
|----------|----------|
| `min(a, b)` | `max(a, b)` |
| `max(a, b)` | `min(a, b)` |

```vyper
# Original
return min(loan.maturity, loan.call_time + loan.call_window)

# Mutant
return max(loan.maturity, loan.call_time + loan.call_window)
```

### 10b. Abs Removal

| Original | Mutation |
|----------|----------|
| `abs(x)` | `x` |
| `abs(x)` | `-x` |

### 10c. Floor/Ceil Swap

| Original | Mutation |
|----------|----------|
| `floor(x)` | `ceil(x)` |
| `ceil(x)` | `floor(x)` |

### 10d. Unsafe Math Swap

| Original | Mutation |
|----------|----------|
| `unsafe_add(a, b)` | `a + b` (safe add) |
| `unsafe_sub(a, b)` | `a - b` (safe sub) |
| `unsafe_mul(a, b)` | `a * b` (safe mul) |
| `unsafe_div(a, b)` | `a // b` (safe div) |
| `a + b` | `unsafe_add(a, b)` |

### 10e. Len Mutation

| Original | Mutation |
|----------|----------|
| `len(x)` | `0` |
| `len(x)` | `1` |
| `len(x) > 0` | `True` |

### 10f. Convert Target Type Mutation

```vyper
# Original
convert(answer, uint256)

# Mutant: change target type
convert(answer, int256)
```

### 10g. Slice Boundary Mutations

| Original | Mutation |
|----------|----------|
| `slice(b, start, length)` | `slice(b, start + 1, length)` |
| `slice(b, start, length)` | `slice(b, start, length - 1)` |
| `slice(b, start, length)` | `slice(b, start, length + 1)` |

### 10h. Empty Type Mutation

```vyper
# Original
x = empty(bytes32)

# Mutant: different empty type (if context allows)
x = empty(address)  # only if types are compatible
```

---

## 11. External Call Mutations

### 11a. Call Type Swap

| Original | Mutation |
|----------|-----------|
| `extcall` | `staticcall` (removes state modification) |
| `staticcall` | `extcall` |
| `is_delegate_call=True` | `is_delegate_call=False` |
| `is_static_call=True` | `is_static_call=False` |

### 11b. Revert-on-Failure Flag

```vyper
# Original
success, response = raw_call(target, data, max_outsize=32, revert_on_failure=False)

# Mutant: change to revert on failure
response = raw_call(target, data, max_outsize=32, revert_on_failure=True)
```

### 11c. Transfer Direction Swap

```vyper
# Original
extcall IERC20(token).transferFrom(sender, receiver, amount)

# Mutant: swap sender/receiver
extcall IERC20(token).transferFrom(receiver, sender, amount)
```

### 11d. Transfer vs TransferFrom

```vyper
# Original: transferFrom (pull pattern)
extcall IERC20(token).transferFrom(_from, self, amount)

# Mutant: transfer (push pattern, changes semantics)
extcall IERC20(token).transfer(_from, amount)
```

### 11e. Return Value Ignore

```vyper
# Original
assert extcall IERC20(token).transfer(to, amount), "transfer failed"

# Mutant: ignore return value
extcall IERC20(token).transfer(to, amount)
```

### 11f. Self vs Msg.sender as Target

```vyper
# Original
extcall IERC20(token).transferFrom(user, self, amount)

# Mutant: self → msg.sender
extcall IERC20(token).transferFrom(user, msg.sender, amount)
```

---

## 12. Type Conversion Mutations

### 12a. Signed/Unsigned Swap

```vyper
# Original
convert(value, uint256)

# Mutant
convert(value, int256)
```

### 12b. Narrowing/Widening Type

```vyper
# Original
convert(value, uint256)

# Mutant
convert(value, uint128)
```

### 12c. Negation Before Convert

```vyper
# Original
convert(-borrower_delta, uint256)

# Mutant: remove negation
convert(borrower_delta, uint256)
```

### 12d. Convert Removal

```vyper
# Original
10 ** convert(staticcall IERC20Detailed(token).decimals(), uint256)

# Mutant: use raw value without conversion
10 ** staticcall IERC20Detailed(token).decimals()
```

---

## 13. Event Logging Mutations

### 13a. Event Removal

Remove `log` statements entirely.

```vyper
# Original
log LoanCreated(id=loan.id, amount=loan.amount, ...)

# Mutant: line removed
```

### 13b. Event Argument Swap

Swap arguments of the same type in event emissions.

```vyper
# Original
log LoanPaid(id=loan.id, borrower=loan.borrower, lender=loan.lender, ...)

# Mutant: swap borrower and lender
log LoanPaid(id=loan.id, borrower=loan.lender, lender=loan.borrower, ...)
```

### 13c. Event Argument Value Mutation

```vyper
# Original
log LoanPaid(paid_principal=loan.amount, paid_interest=interest, ...)

# Mutant: swap principal and interest
log LoanPaid(paid_principal=interest, paid_interest=loan.amount, ...)
```

### 13d. Wrong Event Type

```vyper
# Original
log LoanPaid(...)

# Mutant: emit different event
log LoanCreated(...)
```

---

## 14. Access Control Mutations

### 14a. Sender Check Replacement

| Original | Mutation |
|----------|----------|
| `msg.sender` | `tx.origin` |
| `tx.origin` | `msg.sender` |
| `msg.sender == owner` | `True` |
| `msg.sender == owner` | `msg.sender != owner` |

```vyper
# Original
assert msg.sender == base.owner

# Mutant: use tx.origin
assert tx.origin == base.owner

# Mutant: remove check
pass
```

### 14b. Role Swap

```vyper
# Original
assert base._check_user(loan.borrower), "not borrower"

# Mutant: check wrong role
assert base._check_user(loan.lender), "not borrower"
```

### 14c. Authorized Proxy Logic

```vyper
# Original
liquidator: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

# Mutant: invert proxy check
liquidator: address = msg.sender if base.authorized_proxies[msg.sender] else tx.origin

# Mutant: always use msg.sender
liquidator: address = msg.sender

# Mutant: always use tx.origin
liquidator: address = tx.origin
```

### 14d. OR to AND in Multi-Role Checks

```vyper
# Original
assert msg.sender == base.owner or msg.sender == base.transfer_agent

# Mutant: or → and (impossible to satisfy both)
assert msg.sender == base.owner and msg.sender == base.transfer_agent
```

---

## 15. State Variable Mutations

### 15a. Skip State Update

Remove a state-changing line entirely.

```vyper
# Original
base.loans[loan.id] = base._loan_state_hash(loan)

# Mutant: line removed (loan state not persisted)
```

### 15b. Wrong State Cleared

```vyper
# Original: clear loan on settlement
base.loans[loan.id] = empty(bytes32)

# Mutant: don't clear (stale state remains)
# (line removed)
```

### 15c. Update Wrong Variable

```vyper
# Original
base.partial_liquidation_fee = new_partial_liquidation_fee

# Mutant: update wrong fee
base.full_liquidation_fee = new_partial_liquidation_fee
```

### 15d. Accumulator Direction

```vyper
# Original
self.commited_liquidity[key] = commited_liquidity + amount

# Mutant: subtract instead of add
self.commited_liquidity[key] = commited_liquidity - amount
```

### 15e. Conditional Assignment Mutation

```vyper
# Original
self.commited_liquidity[key] = 0 if amount > commited_liquidity else commited_liquidity - amount

# Mutant: remove the zero-floor
self.commited_liquidity[key] = commited_liquidity - amount
```

---

## 16. Ternary Expression Mutations

### 16a. Swap True/False Branches

```vyper
# Original
new_principal = outstanding_debt if principal == 0 else principal

# Mutant: swap branches
new_principal = principal if principal == 0 else outstanding_debt
```

### 16b. Always Take One Branch

```vyper
# Original
liquidator = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

# Mutant: always first branch
liquidator = msg.sender

# Mutant: always second branch
liquidator = tx.origin
```

### 16c. Invert Condition

```vyper
# Original
current_ltv = self._compute_ltv(...) if in_vault_collateral > 0 else 0

# Mutant: invert condition
current_ltv = self._compute_ltv(...) if in_vault_collateral == 0 else 0
```

---

## 17. Empty/Default Value Mutations

### 17a. Empty Check Inversion

```vyper
# Original
assert offer.offer.borrower != empty(address)

# Mutant: != → ==
assert offer.offer.borrower == empty(address)
```

### 17b. Empty vs Non-Empty Assignment

```vyper
# Original
base.proposed_owner = empty(address)

# Mutant: don't clear
# (line removed)
```

### 17c. Zero vs Non-Zero Initialization

```vyper
# Original
redeem_start: uint256 = 0

# Mutant
redeem_start: uint256 = block.timestamp
```

### 17d. Empty Address in Conditional

```vyper
# Original
if offer.offer.borrower == empty(address) or offer.offer.borrower == borrower:

# Mutant: remove empty(address) check
if offer.offer.borrower == borrower:
```

---

## 18. Hash and Cryptographic Mutations

### 18a. Hash Input Removal

Remove one field from a hash computation.

```vyper
# Original
keccak256(concat(
    convert(loan.borrower, bytes32),
    convert(loan.lender, bytes32),
    convert(loan.start_time, bytes32),
    loan.offer_id,
))

# Mutant: remove one field
keccak256(concat(
    convert(loan.borrower, bytes32),
    convert(loan.start_time, bytes32),
    loan.offer_id,
))
```

### 18b. Hash Algorithm Swap

| Original | Mutation |
|----------|----------|
| `keccak256(x)` | `sha256(x)` |
| `sha256(x)` | `keccak256(x)` |

### 18c. Signature Validation Skip

```vyper
# Original
assert base._is_offer_signed_by_lender(offer, domain_separator)

# Mutant: remove signature check
pass
```

### 18d. Malleability Check Removal

```vyper
# Original
assert signed_offer.signature.s <= MALLEABILITY_THRESHOLD

# Mutant: remove check
pass
```

### 18e. Domain Separator Mutation

```vyper
# Original
offer_sig_domain_separator = keccak256(abi_encode(
    DOMAIN_TYPE_HASH,
    name_hash,
    version_hash,
    chain.id,
    self,
))

# Mutant: swap self → msg.sender
offer_sig_domain_separator = keccak256(abi_encode(
    DOMAIN_TYPE_HASH,
    name_hash,
    version_hash,
    chain.id,
    msg.sender,
))
```

---

## 19. Loop Mutations

### 19a. Range Bound Mutations

```vyper
# Original
for i: uint256 in range(10):
    ...

# Mutant: change upper bound
for i: uint256 in range(9):
    ...

# Mutant: off-by-one
for i: uint256 in range(11):
    ...
```

### 19b. Break/Continue Swap

| Original | Mutation |
|----------|----------|
| `break` | `continue` |
| `continue` | `break` |
| `break` | `pass` (remove break) |
| `continue` | `pass` (remove continue) |

### 19c. Loop Body Skip

```vyper
# Original
for i: uint256 in range(len(items), bound=MAX):
    process(items[i])

# Mutant: skip processing
for i: uint256 in range(len(items), bound=MAX):
    pass
```

### 19d. DynArray Append/Pop Swap

```vyper
# Original
my_array.append(value)

# Mutant
my_array.pop()
```

---

## 20. Return Value Mutations

### 20a. Return Value Replacement

| Original | Mutation |
|----------|----------|
| `return value` | `return 0` |
| `return value` | `return empty(type)` |
| `return True` | `return False` |
| `return False` | `return True` |

```vyper
# Original
return loan.maturity

# Mutant: return 0
return 0

# Mutant: return different field
return loan.start_time
```

### 20b. Return Field Swap

```vyper
# Original
return ConvertionRate(numerator=price, denominator=oracle_decimals)

# Mutant: swap numerator/denominator
return ConvertionRate(numerator=oracle_decimals, denominator=price)
```

### 20c. Early Return vs Continue

```vyper
# Original
if condition:
    return value_a
return value_b

# Mutant: always return second value
return value_b
```

---

## 21. Statement Deletion Mutations

Drop a single statement from a function body. If no test fails, the statement is either dead code or test coverage is missing. This is one of the most powerful mutation categories — every executable statement should be "protected" by at least one test.

### 21a. Assert/Require Deletion

Drop individual validation statements. Each removed assert represents a bypassed security check.

```vyper
# Original: create_loan validations
assert base._is_offer_signed_by_lender(offer, offer_sig_domain_separator), "offer not signed by lender"   # line A
self._check_offer_validity(offer)                                                                          # line B
assert staticcall base.KYCValidator(kyc_validator_addr).check_validations_pair(borrower_kyc, lender_kyc)   # line C
assert lender_kyc.validation.wallet == offer.offer.lender, "KYC validation fail"                           # line D
assert borrower_kyc.validation.wallet == borrower, "KYC validation fail"                                   # line E
assert offer.offer.borrower == empty(address) or offer.offer.borrower == borrower, "borrower not allowed"  # line F

# Mutants: drop each line individually → 6 mutants
# Drop A: unsigned offers accepted
# Drop B: expired/revoked offers accepted
# Drop C: un-KYC'd participants can transact
# Drop D: lender KYC wallet mismatch accepted
# Drop E: borrower KYC wallet mismatch accepted
# Drop F: wrong borrower can use any offer
```

### 21b. State Update Deletion

Drop a state-modifying statement. Detects whether tests verify storage changes.

```vyper
# Original: settle_loan
base.loans[loan.id] = empty(bytes32)                                              # line A: clear loan
base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)  # line B: free liquidity

# Mutant: drop line A → loan not cleared, can be settled/liquidated again
# Mutant: drop line B → lender's committed liquidity never freed, can't reuse it
```

```vyper
# Original: create_loan
base._check_and_update_offer_state(offer, principal)       # line A: track offer usage
base.loans[loan.id] = base._loan_state_hash(loan)          # line B: register loan

# Mutant: drop line A → offer utilization not tracked, can exceed available_liquidity
# Mutant: drop line B → loan exists but not in storage, settle/liquidate will fail
```

```vyper
# Original: revoke_offer
self.revoked_offers[offer_id] = True

# Mutant: drop the line → offer revocation has no effect, revoked offers can still be used
```

### 21c. External Call Deletion

Drop an external call (token transfer, vault interaction). Detects whether tests verify fund movements.

```vyper
# Original: settle_loan
self._receive_funds(loan.borrower, loan.amount + interest)                     # line A: pull payment from borrower
self._send_funds(loan.lender, loan.amount + interest - protocol_settlement_fee) # line B: pay lender
if protocol_settlement_fee > 0:
    self._send_funds(base.protocol_wallet, protocol_settlement_fee)             # line C: pay protocol

self._send_collateral(loan.borrower, loan.collateral_amount)                    # line D: return collateral

# Mutant: drop A → borrower doesn't pay, loan settles for free
# Mutant: drop B → lender never receives payment
# Mutant: drop C → protocol fee not collected
# Mutant: drop D → borrower's collateral never returned
```

```vyper
# Original: create_loan
self._receive_collateral(loan.borrower, loan.collateral_amount)                            # line A
self._transfer_funds(loan.lender, loan.borrower, loan.amount - loan.origination_fee_amount) # line B
if loan.protocol_upfront_fee_amount > 0:
    self._transfer_funds(loan.lender, base.protocol_wallet, loan.protocol_upfront_fee_amount) # line C

# Mutant: drop A → loan created without collateral posted
# Mutant: drop B → borrower never receives loan principal
# Mutant: drop C → protocol upfront fee not collected
```

### 21d. Event Log Deletion

Drop a `log` statement. Detects whether tests verify event emissions.

```vyper
# Original
log LoanCreated(id=loan.id, amount=loan.amount, ...)
log LoanPaid(id=loan.id, borrower=loan.borrower, ...)
log OfferRevoked(offer_id=offer_id, lender=offer.offer.lender)
log PartialLiquidationFeeSet(old_fee=base.partial_liquidation_fee, new_fee=new_partial_liquidation_fee)

# Mutant: drop each log → off-chain indexers and monitors miss the event
```

### 21e. Conditional Branch Body Deletion

Drop the body inside an if/elif/else branch (replace with `pass`).

```vyper
# Original
if collateral_amount > loan.collateral_amount:
    base._receive_collateral(loan.borrower, collateral_amount - loan.collateral_amount, collateral_token)
elif collateral_amount < loan.collateral_amount:
    base._send_collateral(loan.borrower, loan.collateral_amount - collateral_amount, collateral_token)

# Mutant: drop if-body → extra collateral not collected during refinance
# Mutant: drop elif-body → excess collateral not returned during refinance
```

```vyper
# Original
if protocol_settlement_fee > 0:
    self._send_funds(base.protocol_wallet, protocol_settlement_fee)

# Mutant: drop if-body → protocol fee never sent even when > 0
```

### 21f. Committed Liquidity Update Deletion

Drop liquidity tracking calls.

```vyper
# Original
base._check_and_update_offer_state(offer, principal)
# or
base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)

# Mutant: drop either → liquidity accounting becomes incorrect,
#         lender can over-commit or liquidity remains locked forever
```

### 21g. Vault Operation Deletion

Drop vault-specific operations in securitize contracts.

```vyper
# Original
base.vault_count[wallet] += 1
_vault: address = base._get_or_create_vault(wallet, vault_id, vault_impl_addr)
extcall _vault.withdraw_funds(payment_token, amount)

# Mutant: drop vault_count increment → vault IDs collide
# Mutant: drop vault creation → operations fail on non-existent vault
# Mutant: drop withdraw_funds → funds remain stuck in vault
```

---

## 22. Statement Reordering Mutations

Swap the order of two adjacent (or nearby) statements within a function. Order-dependent sequences are common in smart contracts due to reentrancy concerns, data dependencies, and the checks-effects-interactions pattern.

### 22a. Checks-Effects-Interactions (CEI) Violations

The most critical reordering: move state updates after external calls, or external calls before state updates.

```vyper
# Original: settle_loan (correct CEI order)
base.loans[loan.id] = empty(bytes32)                          # EFFECT: clear state
base._reduce_commited_liquidity(loan.lender, ...)             # EFFECT: update accounting
self._receive_funds(loan.borrower, loan.amount + interest)     # INTERACTION: pull funds
self._send_funds(loan.lender, ...)                             # INTERACTION: push funds

# Mutant: swap effects and interactions (CEI violation)
self._receive_funds(loan.borrower, loan.amount + interest)     # INTERACTION first!
self._send_funds(loan.lender, ...)                             # INTERACTION
base.loans[loan.id] = empty(bytes32)                          # EFFECT after interactions
base._reduce_commited_liquidity(loan.lender, ...)             # EFFECT after interactions
# → reentrancy through token callback could settle/liquidate the same loan again
```

```vyper
# Original: create_loan
base.loans[loan.id] = base._loan_state_hash(loan)             # EFFECT: register loan
self._receive_collateral(loan.borrower, loan.collateral_amount) # INTERACTION: pull collateral
self._transfer_funds(loan.lender, loan.borrower, ...)           # INTERACTION: transfer funds

# Mutant: interactions before effects
self._receive_collateral(loan.borrower, loan.collateral_amount)
self._transfer_funds(loan.lender, loan.borrower, ...)
base.loans[loan.id] = base._loan_state_hash(loan)
# → reentrancy during transfer could call settle_loan before loan is registered
```

### 22b. Paired State Deletion + Creation Reorder

When replacing a loan (refinance), the old loan must be deleted before or atomically with creating the new one.

```vyper
# Original: replace_loan
base.loans[loan.id] = empty(bytes32)                            # A: delete old loan
base._reduce_commited_liquidity(loan.lender, ...)               # B: free old liquidity
base._check_and_update_offer_state(offer, new_principal)         # C: commit new liquidity
base.loans[new_loan.id] = base._loan_state_hash(new_loan)       # D: create new loan

# Mutant: swap A and D → both loans exist simultaneously in storage
base.loans[new_loan.id] = base._loan_state_hash(new_loan)       # D first
base._reduce_commited_liquidity(loan.lender, ...)
base._check_and_update_offer_state(offer, new_principal)
base.loans[loan.id] = empty(bytes32)                            # A last
# → if loan.id != new_loan.id, both loans are valid during B and C
```

### 22c. Validation Before vs After State Mutation

Move a validation check after the state it's supposed to guard.

```vyper
# Original: create_loan
assert base.loans[loan.id] == empty(bytes32), "loan already exists"   # CHECK
base._check_and_update_offer_state(offer, principal)                   # EFFECT
base.loans[loan.id] = base._loan_state_hash(loan)                     # EFFECT

# Mutant: check after state change (always passes since we just set it)
base._check_and_update_offer_state(offer, principal)
base.loans[loan.id] = base._loan_state_hash(loan)
assert base.loans[loan.id] == empty(bytes32), "loan already exists"   # always fails now!
# → or simply: check moved after mutation makes it meaningless
```

```vyper
# Original: liquidate check sequence
assert base._is_loan_valid(loan), "invalid loan"
assert not base._is_loan_defaulted(loan), "loan defaulted"
assert current_ltv >= loan.liquidation_ltv, "ltv lt liquidation ltv"

# Mutant: swap validation order
assert current_ltv >= loan.liquidation_ltv, "ltv lt liquidation ltv"
assert not base._is_loan_defaulted(loan), "loan defaulted"
assert base._is_loan_valid(loan), "invalid loan"
# → functionally equivalent in this case, but gas-inefficient;
#   more meaningful when a later check depends on an earlier one
```

### 22d. Vault Withdrawal Before vs After Calculation

Swap the order of vault fund withdrawal and the calculations that depend on it.

```vyper
# Original: securitize liquidate_loan
extcall _vault.withdraw_funds(payment_token, in_vault_payment_token + liquidation_fee)  # A: withdraw
# ... calculations using in_vault_payment_token ...                                       # B: compute
if in_vault_payment_token >= outstanding_debt:                                            # C: branch
    lender_funds_delta = outstanding_debt - protocol_settlement_fee_amount

# Mutant: compute before withdraw (stale vault state)
# If calculations depend on vault balance queries rather than pre-computed values,
# moving A after B would use pre-withdrawal balances
```

### 22e. Token Transfer Order Swap

Swap the order of two independent transfers, changing who gets paid first.

```vyper
# Original: liquidate_loan (lender-is-not-liquidator path)
base._receive_funds(liquidator, principal_written_off, payment_token)    # A: pull from liquidator
base._send_funds(loan.lender, principal_written_off, payment_token)      # B: pay lender

# Mutant: swap A and B
base._send_funds(loan.lender, principal_written_off, payment_token)      # B first: pay lender
base._receive_funds(liquidator, principal_written_off, payment_token)    # A second: pull from liquidator
# → if contract doesn't have enough balance, B fails before A provides the funds
```

```vyper
# Original: settle_loan
self._receive_funds(loan.borrower, loan.amount + interest)           # A: collect payment
self._send_funds(loan.lender, loan.amount + interest - fee)          # B: pay lender

# Mutant: swap A and B
self._send_funds(loan.lender, loan.amount + interest - fee)          # B: pay lender first
self._receive_funds(loan.borrower, loan.amount + interest)           # A: collect payment after
# → contract may not have sufficient balance for B if it relies on A's incoming funds
```

### 22f. Collateral vs Payment Transfer Order

Swap collateral and payment token operations, changing the economic sequence.

```vyper
# Original: create_loan
self._receive_collateral(loan.borrower, loan.collateral_amount)                          # A: take collateral
self._transfer_funds(loan.lender, loan.borrower, loan.amount - origination_fee_amount)   # B: send principal

# Mutant: swap A and B
self._transfer_funds(loan.lender, loan.borrower, loan.amount - origination_fee_amount)   # B: send principal first
self._receive_collateral(loan.borrower, loan.collateral_amount)                          # A: take collateral after
# → borrower receives funds before posting collateral; if B triggers a callback,
#   borrower could abort before A executes
```

### 22g. Event Before vs After State Change

Swap event emission with the state update it documents.

```vyper
# Original: set_partial_liquidation_fee
log PartialLiquidationFeeSet(old_fee=base.partial_liquidation_fee, new_fee=new_partial_liquidation_fee)
base.partial_liquidation_fee = new_partial_liquidation_fee

# Mutant: swap order
base.partial_liquidation_fee = new_partial_liquidation_fee
log PartialLiquidationFeeSet(old_fee=base.partial_liquidation_fee, new_fee=new_partial_liquidation_fee)
# → old_fee now shows the NEW value (since state was already updated), event data is wrong
```

```vyper
# Original: extend_loan
base.loans[loan.id] = base._loan_state_hash(new_loan)
log LoanMaturityExtended(original_maturity=loan.maturity, new_maturity=new_loan.maturity, ...)

# Mutant: log before state update
log LoanMaturityExtended(original_maturity=loan.maturity, new_maturity=new_loan.maturity, ...)
base.loans[loan.id] = base._loan_state_hash(new_loan)
# → event emitted but if subsequent code reverts, event is also reverted (no difference);
#   however, reentrancy through log side-effects could observe stale state
```

### 22h. Offer State Update vs Loan Registration

Swap offer utilization tracking with loan creation.

```vyper
# Original
base._check_and_update_offer_state(offer, principal)           # A: track offer usage
base.loans[loan.id] = base._loan_state_hash(loan)              # B: register loan

# Mutant: swap A and B
base.loans[loan.id] = base._loan_state_hash(loan)              # B: register loan first
base._check_and_update_offer_state(offer, principal)           # A: track offer usage after
# → if _check_and_update_offer_state reverts (offer fully utilized),
#   the loan is already in storage but offer state is inconsistent
#   (Vyper reverts the entire tx, so this is safe in practice, but
#   swapping reveals whether tests exercise offer capacity limits)
```

### 22i. Committed Liquidity: Reduce vs Transfer

Swap liquidity accounting with the actual fund movement.

```vyper
# Original: partial_liquidate
base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, principal_written_off)  # A
base._send_funds(loan.lender, principal_written_off, payment_token)                          # B

# Mutant: swap A and B
base._send_funds(loan.lender, principal_written_off, payment_token)                          # B first
base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, principal_written_off)  # A after
# → reentrancy during B could observe stale committed liquidity
```

### Reordering Prioritization

When testing for missing coverage via statement reordering, prioritize:

1. **State clear/set ↔ external call** — reentrancy vulnerabilities (highest impact)
2. **Receive funds ↔ send funds** — balance dependency violations
3. **Collateral ↔ payment operations** — economic ordering attacks
4. **Old state delete ↔ new state create** — double-existence windows
5. **Event ↔ state update** — incorrect event data
6. **Validation ↔ state mutation** — check bypass

---

## Prioritization Guide

When checking for missing tests, prioritize mutations in this order:

1. **Statement deletion — state updates** (dropped loan clear, dropped liquidity tracking) - reentrancy, double-spend
2. **Statement reordering — CEI violations** (state update after external call) - reentrancy
3. **Financial calculations** (arithmetic mutations in fee/interest/LTV formulas) - highest value impact
4. **Access control** (sender checks, role verification) - security critical
5. **Statement deletion — external calls** (dropped transfers) - funds at risk
6. **Parameter swaps** (especially address and amount swaps in transfers) - funds at risk
7. **Statement reordering — transfer order** (receive ↔ send, collateral ↔ payment) - balance dependency
8. **Boundary conditions** (off-by-one, strict vs non-strict comparisons) - common bug class
9. **Statement deletion — assertions** (dropped validation checks) - validation bypass
10. **Boolean logic** (and/or swaps, negation changes) - validation bypass
11. **State updates** (wrong variable updated, wrong direction) - protocol integrity
12. **External call mutations** (transfer direction, return value handling) - integration bugs
13. **Statement reordering — event vs state** (event emitted with stale/wrong data) - observability
14. **Event logging** (argument swaps, missing events) - observability
15. **Return values** (wrong return, field swaps) - downstream impact
16. **Control flow** (branch swaps, condition inversions) - logic errors
