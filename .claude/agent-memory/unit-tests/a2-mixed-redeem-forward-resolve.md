---
name: a2-mixed-redeem-forward-resolve
description: Audit A2 — settle/liquidate forward-resolve a MIXED async redeem (request_claimable>0 AND cancel_claimable>0); cancel_redeem stays blocked; how to reach the mixed redeem terminal state in tests
metadata:
  type: project
---

Audit fix A2 (feat/despxa-loop, `P2PLendingMultiVaultBase.vy::_resolve_redeem_balances`, async
REDEEM_ASYNC branch ~line 615-632): an async ERC-7540 redeem can be PARTIALLY FULFILLED and PARTIALLY
CANCELLED at once — `request_claimable>0` (fulfilled slice -> payment) AND `cancel_claimable>0`
(cancelled remainder -> reclaimed collateral shares), both pendings 0. The OLD async branch asserted
`... and status.cancel_claimable == 0, "redeem not settled"`, so this mixed state FROZE the loan:
`cancel_redeem` reverts `"claimable redeem"` (it asserts `request_claimable == 0`) and settle/liquidate
reverted `"redeem not settled"` — no forward or reverse resolution.

**The fix makes settle_loan (Erc20) + liquidate_loan (Liquidation facet) the UNIVERSAL FORWARD RESOLVER.**
Async branch now asserts only `request_pending == 0 and cancel_pending == 0`, then claims BOTH legs:
`reclaimed = claim_redeem(addr, False, True)` when `cancel_claimable>0`; `claimed = claim_redeem(addr,
True, False)` when `request_claimable>0`. Returns `(claimed_payment, redeem_residual_collateral +
reclaimed)` when fulfilled, else `(balanceOf(payment), residual + reclaimed)`. `cancel_redeem` is
UNCHANGED (still `assert request_claimable == 0`) — a partially-fulfilled redeem cannot be cleanly
REVERSED, so the borrower must settle FORWARD. That boundary is INTENTIONAL, test it (`with
boa.reverts("claimable redeem")` in the mixed state).

**NO MOCK CHANGE NEEDED for A2.** `CentrifugeAsyncVaultMock.fulfill_redeem` already supports PARTIAL
settlement (asserts `redeem_pending >= shares`, decrements) — mirrors the A1 `fulfill_deposit` work. The
mock's docstring (already `M` on the branch from A1) documents the mixed terminal state for both legs.

**Reaching the MIXED REDEEM terminal state (mock hooks = off-chain issuer):** helper
`_drive_to_mixed_redeem(mock, usdc, vault_addr, fulfilled_shares, assets)` in
`tests/p2p_erc20_multivault/unit/test_async_redeem_settle.py`:
1. loan already `redeem(residual)` -> `requestRedeem(collateral - residual)`, `redeem_pending` set.
2. `usdc.mint(mock, assets)` then `mock.fulfill_redeem(vault_addr, fulfilled_shares, assets)` — PARTIAL
   fulfil: pending -= fulfilled_shares, claimable += fulfilled_shares, redeem_assets += assets.
3. `mock.cancelRedeemRequest(0, vault_addr)` — CRITICAL: call the mock's ERC-7887 surface DIRECTLY (it's
   permissionless, controller=vault_addr). You CANNOT drive this via the contract's `cancel_redeem`
   because that reverts `"claimable redeem"` once `request_claimable>0`. The direct call stands in for
   the issuer. Moves remaining pending into the cancel pipeline.
4. `mock.process_cancel_redeem(vault_addr)` -> `redeem_cancel_claimable := remainder`.
Result: `redeem_claimable == fulfilled_shares` (payment=assets), `redeem_cancel_claimable == remainder`,
both pendings 0, `redeem_cancel_pending == False`.

**Estate on settle (mixed):** `in_vault_payment_token` = fulfilled slice's assets (claimed); `in_vault_collateral`
= `redeem_residual_collateral + reclaimed` (residual weth in vault + reclaimed cancelled shares, both
physically present). Core test uses residual=0.2 weth, fulfil 0.5 weth@1200e6, cancel 0.3 weth -> event
`in_vault_collateral == 0.5 weth`; surplus payment + 0.5 weth collateral to borrower, lender debt-net-fee.

**Estate on liquidate (mixed):** reclaimed shares land in the vault and get VALUED via oracle in the
liquidation math (remaining_collateral_value). Keep it clean by making the payment leg alone cover the
debt (`in_vault_payment_token >= outstanding_debt` branch): lender gets outstanding_debt, borrower gets
surplus payment + `borrower_collateral_delta == in_vault_collateral` (= reclaimed shares), liquidator 0
(fee 0). committed drops by full `loan.amount` (covered branch).

**RED verification (tests 1 & 2, both revert `"redeem not settled"`):** temporarily edit
`_resolve_redeem_balances` — re-add `and status.cancel_claimable == 0` to the assert AND delete the
`if status.cancel_claimable > 0: reclaimed = claim_redeem(...False,True)` block. `rm -rf .cache/titanoboa`
so boa recompiles. settle test reverts at Base.vy:622 directly; liquidate test reverts INSIDE the
delegatecall (`liquidate_loan` raw_call -> `_resolve_redeem_balances` line 622). Restore the fix,
`rm -rf .cache/titanoboa`, rerun. The A2 fix is UNCOMMITTED working-tree state on the branch (the file is
`M` vs HEAD which still has the old assert), so `git diff contracts/v1/P2PLendingMultiVaultBase.vy` after
restore should show exactly the A2 forward-resolve diff, not empty.

Tests added (all in `test_async_redeem_settle.py`, alongside the A1 tests):
`test_settle_async_mixed_state_forward_resolves_and_clears_loan` (core, RED pre-fix),
`test_liquidate_async_mixed_state_forward_resolves_and_clears_loan` (RED pre-fix),
`test_cancel_redeem_still_blocked_in_mixed_state` (intended boundary),
`test_settle_async_cancel_only_returns_residual_plus_reclaimed` (else-branch regression).
Tests 4 (pure fulfilled) / 5 (clean reverse via cancel_redeem) / 6 (already-claimed transferred-loan
else branch) were ALREADY covered: `test_settle_async_surplus_pays_all_parties_and_clears_loan`,
`test_cancel_redeem_reverses_redemption_when_cancel_claimable` (test_leveraged_async.py),
`test_transfer_loan_async_...` (~line 2280 test_leveraged_async.py) respectively — do NOT duplicate.

Full multivault unit suite after: 521 passed, 1 skipped (pre-existing skip). Concrete estate numbers for
the core settle test: principal 1000e6@10% 5% settlement fee, t=50 interest 136986 wei, protocol_fee 6849,
payment claimed 1200e6, reclaimed 0.3 weth, residual 0.2 weth -> lender +1000129137, protocol +6849,
borrower +199863014 usdc surplus + 0.5 weth.

Related: [[cancel-pending-a1-mixed-terminal]] (A1 mixed DEPOSIT, symmetric), [[despxa-async-leveraged-tests]]
(A1 redeem->settle, the sibling `test_async_redeem_settle.py` file), [[despxa-loop-revert-message-renames]]
("claimable redeem" is the current cancel_redeem guard string).
