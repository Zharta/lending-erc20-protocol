---
name: cancel-pending-force-unwind-share-split
description: Testing cancel_pending_loan's fulfilled-but-not-startable force-unwind branch (share-denominated split) in the despxa async suite
metadata:
  type: project
---

`cancel_pending_loan(loan, mint_result, sender=...)` (2nd arg is `SignedMintResult`, unused on async path — pass `EMPTY_MINT_RESULT`). It has TWO settling waterfalls:

- **cancel_claimable branch** (payment-token): reclaimed USDC split; legs paid in payment token. Reached by request cancel -> `process_cancel_deposit`.
- **request_claimable branch** (D28 force-unwind, share-denominated): a FULLY-fulfilled deposit that is NOT startable (fill < `min_collateral_amount`, OR loan defaulted). Claims the shares, splits them oracle-valued, legs paid in COLLATERAL (weth). Reached by `fulfill_deposit` + fund the AsyncVaultMock with weth so the claim can pay.

**Why:** a STARTABLE fulfilled deposit (fill >= min, not defaulted) reverts "claimable mint, start instead"; only the non-startable complement force-unwinds.

**How to apply (force-unwind test setup):**
- Two triggers, exercise both: past-maturity (time_travel past window, which is 86400s > 100s maturity, so it defaults too) with full fill; and below-min fill (offer `min_collateral_amount` > the fulfilled shares).
- Create-time `collateral_amount` (the 3rd arg / estimate) must itself satisfy the offer's min at create — pass an estimate >= offer min, then `fulfill_deposit` the smaller ACTUAL share amount to get below-min at start.
- Oracle (conftest `oracle`): rate_num=387780390000, rate_den=1e8, usdc=1e6, weth=1e18. `value = shares*rate_num*1e6//(rate_den*1e18)`; shares=inverse. 1e18 weth ~= 3877 USDC (covered vs ~1000 debt); 1000 wei ~= 0 (shortfall).
- Covered: lender gets `value_to_shares(debt - protocol_fee_value)`, borrower gets `minted - fee - protocol - lender` (dust). Shortfall (`value_after_fee < debt`): lender gets ALL remaining shares, borrower 0.
- `debt = (loan.amount - origination_fee_amount) + get_capped_interest(now)`.
- Keeper needs post-window (`max_pending_window`); borrower can self-cancel anytime (gets fee + surplus, net-neutral).

**Event gotcha:** `PendingLoanLiquidated` is share-denominated and emitted from the Loan facet via `log main.…`. Read it with `get_last_event` BEFORE any later same-contract view (`p2p.loans`, `p2p.commited_liquidity`) — a same-contract view resets boa's log buffer (see [[boa-get-logs-last-computation]]). `weth.balanceOf` is a different contract, safe to call first.
