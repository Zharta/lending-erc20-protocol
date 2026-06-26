---
name: despxa-async-leveraged-tests
description: How the async (despxa/Centrifuge ERC-7540) leveraged-loan lifecycle is unit-tested — fixtures, AsyncVaultMock funding, D24 dual mint/redemption addr, nonzero max_pending_window
metadata:
  type: project
---

Async despxa leveraged-loan unit tests live in
`tests/p2p_erc20_multivault/unit/test_leveraged_async.py`; fixtures in the same dir's `conftest.py`.
Contract under test: `P2PLendingVaultDespxa` (caps == 938 = MINT_ASYNC|MINT_STATUS|MINT_CANCEL|
REDEEM_ASYNC|REDEEM_STATUS|REDEEM_CANCEL), driven through `P2PLendingMultiVaultLoan`'s
`_create_leveraged_loan_async` / `start_loan` / `cancel_pending_loan` / `cancel_redeem`.

**Fixtures (conftest.py):**
- `despxa_vault_impl` — `P2PLendingVaultDespxa.deploy()` (no ctor args; caps is a compile-time
  constant, NOT deploy-selectable like MultiVaultMock).
- `async_vault_mock` — `AsyncVaultMock.deploy(usdc, weth)`: asset=usdc (payment), share=weth
  (collateral). It pays share out on deposit-claim and asset on redeem-claim from its OWN balance.
- `p2p_usdc_weth_despxa` — vault_impl = despxa; per D24 BOTH `mint_addr` AND `redemption_addr` =
  `async_vault_mock` (same Centrifuge vault). Calls `set_max_pending_window(50, sender=owner)` —
  MUST be nonzero, else the `block.timestamp >= create_time + max_pending_window` guard in
  cancel_pending_loan is always true and the "not borrower" revert can't be exercised. **Window is 50
  and async offers use duration=100 (`_async_offer`), by design: window < duration decouples "past
  window" (t=51, permissionless keeper allowed but loan STILL PENDING, not defaulted) from "past
  maturity" (t=101, defaulted).** Interest at t=51 (~161 wei for 1000e6@10%) is uncapped-equivalent
  (`get_capped_interest == get_interest` since 51<100); past maturity it caps at ~317. This was 86400
  pre-feat/despxa-loop, which made "past window" ALWAYS imply "past maturity" and conflated the two.
  Consequence for force-unwind tests: the DEFAULTED trigger must time_travel explicitly past maturity
  (`loan.maturity - loan.create_time + 1`), NOT past window; the below-min trigger works at t=51 while
  not-defaulted (a keeper-driven below-min unwind is now reachable — was untestable before). D30:
  `_create_leveraged_loan_async` asserts `offer.duration > max_pending_window` (revert
  `"duration le pending window"`); window 0 passes trivially. Window is read at create and snapshotted
  onto the loan (`loan.max_pending_window`).

**Mock funding rules:** before `start_loan`, `fulfill_deposit(vault, mint_spend, shares)` THEN
`weth.mint(async_vault_mock, shares, sender=owner)` (mock pays shares on deposit()). Redeem-cancel
returns exactly the collateral pulled in on requestRedeem, so no extra funding for cancel_redeem.
`deposit_vault` arg to create_leveraged_loan is IGNORED on the async path (uses market `mint_addr`) —
pass `ZERO_ADDRESS`.

**State-machine driving:** the mock's test hooks are the off-chain issuer. Three cancel branches are
reached by: request pending (nothing extra) → `cancelDepositRequest` via cancel_mint;
`process_cancel_deposit(vault)` → cancel_claimable branch (settles/reverses). Redeem side mirrors with
`fulfill_redeem` / `process_cancel_redeem`.

**Pending vs started Loan:** pending loan has `start_time == 0` (`_is_loan_started` is
`start_time >= create_time`, and create_time>0). start_loan sets start_time=block.timestamp and
collateral_amount=actual minted shares; it is permissionless (D20) and does NOT LTV-gate.

**start_loan `additional_collateral` (borrower topup) — MIN-GATE COUNTS THE TOPUP (feat/despxa-loop):**
The min-collateral startability gate is `minted + additional_collateral >= loan.min_collateral_amount`
(NOT `minted` alone — an earlier version had `minted >=` and I initially wrote a
`test_start_loan_topup_does_not_bypass_min_gate` asserting the topup was ignored; that test was FLIPPED).
So a below-min fill CAN be started by the BORROWER supplying enough topup; a keeper start
(`additional_collateral == 0`) on a below-min fill STILL reverts `"low collateral amount"`. Topup is
borrower-only (`additional_collateral == 0 or _check_user(borrower)`, revert `"not borrower"`), pulled from
the borrower's wallet via `_receive_collateral` (nets the claimed mint credit first, then transferFrom's
the topup remainder). `cancel_pending_loan`'s force-unwind guard is UNCHANGED (on `minted` alone), so a
below-min fill is EITHER cancellable OR started-with-enough-topup. Tests in test_leveraged_async.py:
`test_start_loan_topup_can_satisfy_min_gate` (below-min fill 0.9 + 0.2 topup by borrower -> live, collateral
1.1), `test_start_loan_reverts_if_minted_plus_topup_below_min` (0.9 + 0.05 -> still `"low collateral amount"`),
`test_start_loan_reverts_if_minted_below_min_collateral` (keeper, 0 topup, below-min -> reverts).
When `additional_collateral > 0`, start_loan emits `LoanCollateralAdded(id, borrower, lender,
collateral_token, old_collateral_amount==minted, new_collateral_amount==minted+additional, old_ltv, new_ltv)`
mirroring add_collateral_to_loan. LTVs use `outstanding_debt = loan.amount + _compute_settlement_interest`
(= `apr*amount*(block.timestamp - accrual_start_time)//(BPS*YEAR)`, UNCAPPED from accrual_start_time ==
`loan.get_interest(ts)`; at start with no time-travel ts==create_time so interest is 0). Compute expected
LTVs independently with conftest_base `calc_ltv(outstanding_debt, collateral, usdc, weth, oracle)` (reads
oracle — a different contract, safe after the emitting tx; read the event via get_last_event BEFORE any p2p
view call — see [[boa-get-logs-last-computation]]). `LoanCollateralAdded` is auto-decoded: `log_stuff` is now
GENERATED by `tests/conftest_base.py::build_erc20_contract_def_with_log_stuff` from the facets' `used_events`,
so any facet-emitted event decodes without a manual conftest edit (supersedes the hand-list in
[[facet-event-decoding-quirk]]). Test file naming is `centrifuge` now (fixtures `p2p_usdc_weth_centrifuge`,
`sign_centrifuge_offer`, `centrifuge_async_vault_mock`, `expected_pending_centrifuge_loan`), not `despxa`.

**cancel_pending_loan SETTLE branch is LIQUIDATION-style (audit A4 + M4), NOT settlement-style.**
The borrower NEVER adds funds (pre-fix it did a transferFrom for the interest-over-margin shortfall,
which broke permissionless cancel for an unfunded/absent borrower = A4). Distributes `available`
(== reclaimed payment == mint_spend) with:
`interest = base._compute_capped_interest` = `amount*apr*(min(now,maturity)−accrual_start)/(BPS*YEAR)`
— accrued from create_time (D1) but CAPPED at maturity (M4, no unbounded interest past term; the
Python `Loan.get_interest` is UNCAPPED, so tests need a local `_capped_interest`);
`lender_deployed = amount − origination_fee_amount`; `debt = lender_deployed + interest`;
`liquidation_fee = min(debt*full_liquidation_fee//BPS, available)` → CALLER (keeper incentive;
liquidator=msg.sender unless authorized_proxy then tx.origin); `available_after_fee = available −
liquidation_fee`; `protocol_fee = min(protocol_settlement_fee*interest//BPS, available_after_fee)` →
protocol_wallet. COVERED (available_after_fee>=debt): lender=debt−protocol_fee, borrower=surplus.
SHORTFALL: lender=available_after_fee−protocol_fee, borrower=0 (lender absorbs the loss). Conserves:
`liquidation_fee + lender + protocol_fee + borrower == available`.
Test helpers in `test_leveraged_async.py`: `_capped_interest`, `_cancel_distribution(loan, available,
now)` (independent reproduction of the split), `_drive_to_cancel_claimable(...)` (phase1 request +
`process_cancel_deposit`). Fees default 0 in the despxa fixture — set via `set_full_liquidation_fee`
and `set_protocol_fee(0, settlement)` BEFORE `_create_pending_loan` so `_read_fee_params` snapshots
them onto the loan hash. Third-party keeper must warp past `max_pending_window` before EVERY call
(phase1 included). protocol_wallet==owner in the fixture. available==mint_spend (mock returns all usdc
on cancel-claim; `usdc.balanceOf(mock)==mint_spend` right before the settle tx, 0 after).

Standalone-vault direct tests (`standalone_despxa_vault` fixture): deploy impl + `initialise(owner,
weth)` so caller == the EOA; drive mint_status/redeem_status via the mock and assert the AsyncStatus
4-tuple; auth reverts are `"unauthorized"` (msg.sender != caller).

**Async redeem -> settle/liquidate (audit A1 fix), `test_async_redeem_settle.py`:** the base helper
`_resolve_redeem_balances(loan, vault, payment_token, redeem_result)` (called by `settle_loan` and the
liquidation facet's `liquidate_loan` for a redeemed loan) dispatches on `vault.capabilities()`. For a
REDEEM_ASYNC despxa vault it ignores the `redeem_result` arg entirely (pass `SignedRedeemResult()`),
asserts the redemption is fully fulfilled (`request_pending==0 and request_claimable>0 and
cancel_pending==0 and cancel_claimable==0`, else revert **"redeem not settled"**) and CLAIMS the
proceeds on-chain via `claim_redeem`, returning `(claimed_assets, redeem_residual_collateral)`.
- Fulfill+fund: `usdc.mint(mock, assets)` THEN `mock.fulfill_redeem(vault_addr, shares, assets)` before
  settle (mock pays `asset`/usdc on the redeem claim from its own balance).
- Mock funding gotcha: the mock KEEPS the original deposit's usdc (deposit claim pays out weth, retains
  the stablecoin), so after settle `usdc.balanceOf(mock)` == pre-settle − assets, NOT 0. Assert the
  delta / `mock.redeem_claimable(vault)==0`, not an absolute 0.
- Redeem with residual>0: `redeem(loan, residual)` pulls only `collateral−residual` shares into the
  mock (`redeem_pending==collateral−residual`); the residual weth stays in the vault and is returned to
  the borrower on settle.
- Settle economics (despxa fixture: settlement fee 0 by default — use `set_protocol_fee(0, fee, owner)`
  before create to exercise the protocol-fee leg): `in_vault_payment_token=assets`; borrower refunded
  `assets−(amount+interest)` if surplus, tops up the shortfall (needs usdc+allowance) if negative.
- Liquidation quirk (pre-existing, NOT part of A1): in the SHORTFALL branch committed liquidity is
  released by `remaining_collateral_value` only (not by the payment proceeds), so with residual==0 and
  no collateral value the committed amount is left UNTOUCHED after a shortfall liquidation.

**D31 create-event shape (feat/despxa-loop):** `PendingLoanCreated` is DELETED. The async
create branch now emits the SAME pair as sync: full `LoanCreated` (with `start_time == 0` marking
pending, `collateral_amount` = caller's expected amount) + `LeveragedLoanCreated`.
`LeveragedLoanCreated` gained a trailing `mint_deadline: uint256`: async = `block.timestamp +
loan.max_pending_window` if window>0 else 0 (fixture window 50s -> `create_ts + 50`); sync always 0.
Async LeveragedLoanCreated: `principal`=full, `collateral_amount`=expected, `acquired_collateral=0`,
`pending=True`. Event tests (`test_create_async_logs_loan_created_event` /
`test_create_async_logs_leveraged_event` / `test_create_async_window_zero_logs_zero_mint_deadline`)
create INLINE and snapshot p2p fee getters BEFORE the create tx; oracle rate fields asserted via
`oracle.latestRoundData().answer` / `10**oracle.decimals()` (other-contract reads are get_logs-safe).

Related: [[boa-get-logs-last-computation]] (event tests read getters before the tx),
[[multivault-mock-selectable-capabilities]], [[leveraged-loan-mint-mock]] (sync counterpart).
