---
name: committed-liquidity-freed-by-principal
description: liquidate_loan/settle/refinance free commited_liquidity by loan.amount in branches 1&2, but the SHORTFALL branch frees min(lender_funds_delta, loan.amount) (recovered principal); only an AGGREGATED offer unmasks it
metadata:
  type: project
---

Audit finding #6 (feat/despxa-loop, `P2PLendingMultiVaultLiquidation.vy` `liquidate_loan`): branches
1 & 2 free the lender's `commited_liquidity` by **`loan.amount` (principal)** — full-payment (line
~270) and payment+collateral (line ~286). The **shortfall branch (the `else`, line ~304)** was
REFINED after #6: it now frees **`min(lender_funds_delta, loan.amount)`** — the principal actually
RECOVERED, net of protocol fee — NOT `loan.amount`. `lender_funds_delta = in_vault_payment_token +
remaining_collateral_value - protocol_settlement_fee_amount`. Rationale: in a shortfall the lender
does NOT get full principal back; the unrecovered part is a realized loss that must stay committed
permanently (not be re-advertised as reusable offer capacity). So after a shortfall liquidation on
an aggregated offer, `commited_liquidity` drops by only the recovered principal and the loss stays.
For a NON-redeemed loan `in_vault_payment_token == 0`, so recovered == `remaining_collateral_value -
protocol_fee` == `send_to_lender` from `calc_full_liquidation`. NOTE: don't take
`remaining_collateral_value` from `calc_full_liquidation` for the liquidator's exact payment — its
one-expression fee rounding differs from the contract's two-step order; replicate the contract order
(fee in payment first, then to collateral) as `test_liquidate_loan_with_shortfall_lender_receives_partial_payment` does.

**Why loan.amount:** `commited_liquidity[key]` is ONLY ever incremented — by `loan.amount` at
creation (`base._check_and_update_offer_state`, asserts `commited + amount <= available_liquidity`,
revert `"offer fully utilized"`). Every closure path reduces by `loan.amount` (settle, refinance,
Loan-facet cancel/redeem). `_reduce_commited_liquidity` **clamps at 0**.

**Masking / why an AGGREGATED offer is required to expose it:** on a SINGLE-loan offer
(`commited == P`), over-freeing `outstanding_debt` (> P) clamps to 0 — same result as freeing P.
The over-free only shows when `commited > P` at liquidation, i.e. multiple loans share one
`tracing_id` + `available_liquidity`. Build a reusable offer with `borrower=ZERO_ADDRESS` and
`available_liquidity = 2*P`, open TWO loans (commited=2P), then liquidate one:
fixed -> 2P - P = P; buggy -> 2P - (P+interest) = P - interest.

**How to build an aggregated offer / multiple loans from it:**
- `offer.borrower == empty(address)` => NOT revoked after first loan (normal offers with a set
  borrower ARE revoked; see `_check_and_update_offer_state`). `offer.principal` may be a fixed P
  (asserted `== principal`) OR 0 (flexible per-loan principal).
- **loan_id = keccak(borrower, lender, create_time, offer_id)** — NOT vault-dependent. Two loans
  from the same borrower+lender+offer in the SAME block collide -> `"loan already exists"`.
  `boa.env.time_travel(seconds=1)` between creates to get distinct `create_time`.
- Order in `create_loan`: build loan -> assert `loans[id]==empty` ("loan already exists") ->
  `_check_and_update_offer_state` ("offer fully utilized"). So to test the "offer fully utilized"
  revert, the attempt must have a UNIQUE create_time or it hits "loan already exists" first.
- KYC `expiration_time >= block.timestamp`; the autouse `kyc_borrower/kyc_lender` sign at
  `expiration=now`, so after any `time_travel` they expire. Re-sign in-test:
  `kyc_for(wallet, kyc_validator_contract.address, now + 10**6)`.

**Liquidity key** (`commited_liquidity` is public): `keccak256(concat(convert(lender,bytes32),
tracing_id))`. In the multivault suite use `compute_liquidity_key(lender, tracing_id)` from
`conftest_base` (imported as `compute_liquidity_key`); or locally
`keccak(to_bytes(hexstr=lender).rjust(32, b"\x00") + tracing_id)`.

**Branch reachability for a NON-redeemed loan:** vault holds no payment token
(`in_vault_payment_token == 0`), so the full-payment branch (`in_vault_payment_token >=
outstanding_debt`) is UNREACHABLE. Default rate (~3877 USDC/WETH, 1 WETH vs 1000 USDC principal)
=> collateral value >> debt => payment+collateral (surplus) branch: third-party liquidator pays
`outstanding_debt`, receives collateral, borrower gets surplus. Use `liquidator != lender` so the
`_reduce_commited_liquidity` actually runs.

**Regression tests:**
- `test_liquidate.py::test_liquidate_loan_frees_committed_liquidity_by_principal_not_debt_on_aggregated_offer`
  (payment+collateral branch). GREEN: committed 2e9 -> 1e9, delta == P (1e9).
  RED (revert to `outstanding_debt`): committed -> 997_260_274, delta == P+interest (1_002_739_726).
- `test_liquidate.py::test_liquidate_loan_shortfall_frees_only_recovered_principal_retaining_loss_on_aggregated_offer`
  (SHORTFALL branch, the refinement). Aggregated offer `principal=0` (flexible, so the reuse loan can
  be sized to remaining capacity), `available_liquidity=2*P`, `protocol_fees` fixture (non-zero fee).
  Two P loans committed (2e9), loan A defaulted + oracle cratered `//100` -> genuine principal-
  shortfall. Third-party liquidator. GREEN concretes: P=1e9, recovered=8_421_876 (=rcv 8_695_848 -
  fee 273_972), retained_loss=991_578_124; committed 2e9 -> 1_008_421_876 (== P + retained_loss),
  drop == recovered. Then a reuse loan of exactly `remaining_capacity (== recovered)` refills to 2e9,
  and 1 wei more reverts "offer fully utilized". RED (revert to `loan.amount`): committed drops by
  full P -> committed_after == P (1e9), `drop == recovered` assert flips (`1e9 != 8_421_876`).
- `test_async_redeem_settle.py::test_liquidate_async_claims_proceeds_and_clears_loan` ALSO pins the
  refinement (shortfall branch): single-loan REDEEMED async offer, `remaining_collateral_value == 0`,
  proceeds `assets=500e6` claimed into vault, fee 0 -> `lender_funds_delta == assets == recovered`.
  Asserts committed drops by `assets` (500e6) leaving `loan.amount - assets` committed (NOT -> 0).
  RED (revert to `loan.amount`): committed -> 0, `drop == recovered` flips (`1e9 != 500e6`).

Non-zero interest + fees are mandatory (apr=1000, `set_protocol_fee` + origination_fee_bps=100) so
`outstanding_debt != principal`; that difference is exactly what the bug over-freed
(see [[feedback-nonzero-fees-in-math-tests]]).
