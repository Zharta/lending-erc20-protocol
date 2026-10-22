---
name: leveraged-loan-real-vault-mint
description: create_leveraged_loan sync-mint unit tests use the REAL P2PLendingVaultSecuritizeMV + AcredMock (deposit_vault ignored); the sync redeem_and_settle market uses the REAL P2PLendingVaultMidas with a MidasVaultMock redemption_addr
metadata:
  type: project
---

The multivault unit suites put the REAL vault contracts under test (despxa pattern: real vault +
external mock ONLY). `MultiVaultMock` is GONE from these suites — the `multivault_mock_contract_def`
fixture and the cap-flag constants were deleted from
`tests/p2p_erc20_multivault/unit/conftest.py`. Supersedes the old MultiVaultMock/deposit_vault-config
approach.

**Leveraged sync-create (`test_create_leveraged.py`) — REAL `P2PLendingVaultSecuritizeMV` + `AcredMock`:**
- Market fixture `p2p_usdc_acred` (conftest): real SecuritizeMV impl (`securitize_vault_impl`, a plain
  `securitize_mv_vault_contract_def.deploy()`), collateral token = the 18-dec `acred_lev` AcredMock.
- SecuritizeMV `mint_sync` IGNORES `deposit_vault`; it resolves the swap connector FROM the collateral
  token via `SecuritizeDSToken(self.token).getDSService(1<<14)` — so the collateral MUST be an AcredMock
  (its `getDSService(1<<14)` returns self). Tests pass a concrete dummy (the acred address) for
  `deposit_vault`.
- Rate: AcredMock `ds = stable * den // num`, `den = 10**oracle_decimals`, `num = oracle.rate`.
  `oracle_acred_lev = OracleMock.deploy(12, 1500)` (num=1500, den=10**12) maps a 6-dec USDC mint_spend
  to an 18-dec DS collateral: full mint of 1500e6 USDC -> exactly 1e18 DS, consumes all 1500e6 (refund
  0). A plain 0-dec 1:1 oracle is UNUSABLE (leaves collateral at 6-dec scale ~1.5e-9 DS, blows past the
  loan's max LTV). Constants exported from conftest as `ACRED_LEV_ORACLE_DECIMALS`/`ACRED_LEV_ORACLE_RATE`;
  the test file derives `RATE_NUM`/`RATE_DEN` and `minted = mint_spend * RATE_DEN // RATE_NUM`.
- Refunds driven by `acred_lev.set_max_mint_amount(cap)`: minted = cap, spent = `cap * num // den`,
  refunded = `mint_spend - spent`. `set_max_mint_amount` applies CONSISTENTLY in both
  `calculateDsTokenAmount` (credited to pending) and `swap` (stablecoin pulled), so the two agree.
- Funding: NO collateral seeding. The AcredMock `swap` pulls the stablecoin from the vault via
  transferFrom (the vault approves the swap for `stable_coin_amount`) and mints DS to the vault. The
  contract already routes `mint_spend` USDC into the vault (lender net-of-fee + borrower margin), so
  `_fund_leveraged` only mints/approves the lender + borrower USDC — no weth/DS seeding.
- TWO distinct min checks: (1) `min_collateral_out` (7th create arg) -> vault `min_ds_token_amount`,
  AcredMock reverts `"ds token amount lt min"` when swap-calc < it; (2) `offer.min_collateral_amount`
  re-validated in `_validate_and_build_loan` -> `"low collateral amount"` when minted < offer floor.
- `sign_leveraged_offer`/`fund_leveraged`/`expected_leveraged_loan` are LOCAL to `test_create_leveraged.py`
  (single-file, per feedback-helpers-local-when-single-file). `mint_config_def` fixture DELETED.
- `create_leveraged_loan` ABI (7 args, branch feat/despxa-loop 2026-07-15): `(offer, principal,
  collateral_amount, borrower_kyc, lender_kyc, mint_spend, min_collateral_out)`. The old trailing
  `deposit_vault: address` (8th positional) was REMOVED — the sync mint target now comes from the
  market config `mint_addr` (set at deployment), not passed per-call. Midas sync market sets `mint_addr`
  to the Midas DepositVault; SecuritizeMV sync resolves the connector from the collateral token as before.
  Fees snapshotted on the ORIGINAL offer principal (`fee_principal`), D13 reconciliation unchanged
  (see [[feedback-nonzero-fees-in-math-tests]]).

**Leveraged sync-create on the MIDAS market (also in `test_create_leveraged.py`, LOCAL fixtures):**
There is NO conftest Midas *leveraged* market — build it in the test file. `p2p_usdc_weth_sync`
(conftest) is redeem-only (mint_addr empty). Local fixtures `p2p_usdc_weth_midas_lev` +
`midas_deposit_vault` (a `MidasVaultMock.deploy(weth, 0)` wired as `mint_addr`), composed from the
real `securitize_vault_impl_sync` (real P2PLendingVaultMidas) + injected conftest fixtures. Midas
`mint_sync` uses `base.mint_addr` as the DepositVault (unlike SecuritizeMV which resolves the connector
from the collateral token) — so weth collateral works here (no getDSService needed).
- MidasVaultMock `depositInstant` is a PURE test knob: `minted == set_deposit_deliver_amount` (weth,
  measured by vault balance delta), spend `= min(mint_spend, max_deposit_spend or mint_spend)`,
  `refunded = mint_spend - spent`. NO rate math. Pre-fund the mock with weth (`weth.mint(mock, minted,
  sender=owner)`) — it pays the mtoken from its own balance. Set `set_deposit_deliver_amount(minted)`.
- Pick `minted` so LTV<=max_iltv: with principal 1000e6 USDC + main oracle (rate 387780390000, 8-dec)
  + weth 18-dec, `minted=1e18` -> LTV 2578 (<8000). Assert precond with `calc_ltv(principal, minted,
  usdc, weth, oracle)`.
- Same get_logs quirk as async: read `get_last_event` BEFORE `expected_leveraged_loan`/`p2p.loans`
  (see [[boa-get-logs-last-computation]]).

**Sync early guards (Loan.vy `_create_leveraged_loan_sync`):** L793 `origination_fee_bps <= BPS` ->
"origination fee gt principal" (fires before funding; sign offer with bps=10001). L798
`mint_spend >= lender_to_vault` -> "mint_spend lt principal". borrower_margin==0 when
`mint_spend == principal - origination_fee` (the `if borrower_margin > 0` transfer is skipped; borrower
not debited; only mint+approve the lender).

Related: [[multivault-mock-selectable-capabilities]] (redeem_and_settle sync market now real Midas +
MidasVaultMock redemption_addr), [[acredmock-consistent-swap-direction]].
