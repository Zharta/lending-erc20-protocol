---
name: multivault-real-vault-markets
description: Multivault unit market fixtures now deploy the REAL vault impls (SecuritizeMV default / Midas sync), NOT MultiVaultMock — which was removed from the unit suites
metadata:
  type: project
---

The multivault unit suites test the REAL vault contracts with external deps mocked (despxa pattern).
`contracts/auxiliary/MultiVaultMock.vy` is NO LONGER used by
`tests/p2p_erc20_multivault/unit/` — the `multivault_mock_contract_def` fixture and the cap-flag
constants (`REDEEM_SYNC=1<<0` ... `MINT_SYNC=1<<4` etc., `DESPXA_CAPABILITIES`, the conftest
`EMPTY_MINT_RESULT`) were DELETED from `tests/p2p_erc20_multivault/unit/conftest.py`. (The `.vy` mock
file still exists in the repo; it just has no unit-suite consumers.)

**The two vault modes are now REAL impls (capabilities are the impl's own constant, read once by the
p2p at init):**
- `securitize_vault_impl` = REAL `P2PLendingVaultSecuritizeMV` (`securitize_mv_vault_contract_def.deploy()`),
  caps `MINT_SYNC | REDEEM_MANUAL`. The DEFAULT (`p2p_usdc_weth`, weth collateral). REDEEM_MANUAL so the
  redeemed-state tests (settle/liquidate/partially_liquidate/transfer/replace) reach "redeemed, awaiting
  settle" through `redeem()` (the p2p redeem() guard rejects REDEEM_SYNC). SecuritizeMV `redeem_manual`
  just `transfer`s the collateral token to the redemption vault (no payment produced), so redeemed-state
  tests still mint the "redeemed" payment into the vault before `settle_loan`. Leveraged mint tests do NOT
  use `p2p_usdc_weth` (weth can't resolve getDSService) — they use `p2p_usdc_acred` (see
  [[leveraged-loan-real-vault-mint]]).
- `securitize_vault_impl_sync` = REAL `P2PLendingVaultMidas` (`midas_vault_impl_contract_def.deploy()`),
  caps `MINT_SYNC | REDEEM_SYNC`; `p2p_usdc_weth_sync` wires it. Used by `test_redeem_and_settle.py` and
  the `redeem()`-rejects-sync test in `test_redeem.py`.

**redeem_and_settle sync market wiring (`test_redeem_and_settle.py`):** `p2p_usdc_weth_sync`'s
`redemption_addr` is a `MidasVaultMock` (fixture `midas_redemption_vault`, deployed `(weth, 0)`), NOT an
EOA — the real Midas `redeem_sync` staticcalls fee getters (`waivedFeeRestriction`/`instantFee`/
`tokensConfig`) and calls `redeemInstant` on it. `redeemInstant` PULLS the redeemed collateral (weth)
from the vault into the mock and PAYS OUT `set_deliver_amount` usdc to the vault; the settle logic then
`withdraw_funds` that usdc. So the redeemed proceeds the settle uses == the mock's delivered usdc (a test
knob), NOT `collateral - residual`. The delivered usdc must clear the vault slippage floor
`min_receive = collateral_redeemed_base18 * oracle_num // oracle_den` (weth 18-dec -> base18 == native;
`set_waived(True)` zeroes the fee). Tests: `set_waived(True)` + `set_deliver_amount(usdc)` + pre-fund the
mock with usdc; helper `_configure_redemption` asserts the floor as a precondition. Surplus scenarios
redeem a big collateral chunk (floor already > debt); shortfall keeps a large residual (small
collateral_redeemed -> floor < debt, deliver below debt). The
`test_redeem_and_settle_redeems_collateral_to_redemption_vault` assertion target is now the MidasVaultMock
address (collateral pulled there), not an EOA redemption wallet.

**Unchanged:** `_is_loan_started` = `start_time >= create_time` (pending loan = start_time 0); seed
unreachable states by writing the hash directly
`p2p.eval(f"base.loans[{'0x'+loan.id.hex()}] = {'0x'+compute_loan_hash(mutated).hex()}")`.

Related: [[leveraged-loan-real-vault-mint]], [[acredmock-consistent-swap-direction]].
