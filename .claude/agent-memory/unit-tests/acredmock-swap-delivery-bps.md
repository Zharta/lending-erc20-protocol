---
name: acredmock-swap-delivery-bps
description: AcredMock swap_delivery_bps knob makes swap() under-deliver vs the calculateDsTokenAmount view — the divergence that exercises SecuritizeMV.mint_sync's measured-delta fix (audit finding #1)
metadata:
  type: project
---

`contracts/auxiliary/AcredMock.vy` has a `swap_delivery_bps: public(uint256)` knob (default 10000 =
100%, set in `__init__`; setter `set_swap_delivery_bps(bps)`). `swap()` computes `full =
_ds_token_amount(liquidityAmount)` (what `calculateDsTokenAmount`/the VIEW still returns, UNCHANGED),
then `delivered = full * swap_delivery_bps // 10000`; it enforces `delivered >= minOutAmount`
(`"insufficient output amount"`), pulls `delivered * num // den` stablecoin, and mints `delivered`.
Default 10000 keeps view == delivered so ALL existing AcredMock-based tests (`test_vault_securitize.py`
+ `test_buy.py` in BOTH `tests/p2p_erc20_multivault/unit` and `tests/p2p_erc20_securitize/unit`) are
byte-unaffected. `set_max_mint_amount` (the cap) and `swap_delivery_bps` are independent and compose.

**Why it exists — audit finding #1 (branch feat/despxa-loop):** `P2PLendingVaultSecuritizeMV.mint_sync`
used to credit `pending_transfers` + return the pre-swap `calculateDsTokenAmount().ds_token_amount` VIEW
estimate as `minted`. If the real `swap()` delivered fewer DS than the view, `loan.collateral_amount`
was set ABOVE the DS the vault actually held, and every later `withdraw`/`redeem_manual` (asserts
`amount + pending_transfers_total <= balanceOf`) reverted `"insufficient balance"` — freezing collateral.
The fix (mirrors `P2PLendingVaultMidas.mint_sync`) snapshots `initial_ds_balance` before swap and
credits/returns the MEASURED delta `ds_received = balanceOf - initial_ds_balance`. Before this knob the
mock could NEVER express the divergence (both view and swap used `_ds_token_amount`), so the bug was
untestable.

**Regression tests (both pass with fix, both RED when the two `ds_received` lines are reverted to
`ds_token_amount.ds_token_amount`):**
- `tests/p2p_erc20_multivault/unit/test_vault_securitize_mv.py::test_mint_sync_credits_measured_delta_when_swap_under_delivers`
  — direct `mint_sync` call at `swap_delivery_bps=9900`; asserts `minted == delivered` (0.99e18) NOT
  `full` (1e18), and credited (`pending_transfers[owner]`) == held (`balanceOf`). RED: `minted == full`.
- `tests/p2p_erc20_multivault/unit/test_create_leveraged.py::test_under_delivering_swap_stores_measured_collateral_and_settles`
  — end-to-end: `create_leveraged_loan` on `p2p_usdc_acred` with the acred at 9900 bps, then
  `settle_loan` succeeds and returns `delivered` DS to the borrower. RED: loan stores `collateral_amount
  == full` (hash mutates) AND `settle_loan`'s `_send_collateral` -> vault `withdraw(full)` reverts
  `"insufficient balance"` (verified via a temporary RED-PROBE that stored `full` and asserted the revert).

**How to verify a mint_sync-measured-delta fix in future:** set the acred to under-deliver, and check the
STORED loan collateral / returned `minted` equals the delivered amount, not the view. To surface the
settle-side `"insufficient balance"` manifestation, you must store the buggy `full` collateral in the
loan the test hands to `settle_loan` (the loan-hash assert otherwise catches the bug first).

Related: [[mv-vault-mint-sync-caller-only]], [[acredmock-consistent-swap-direction]],
[[leveraged-loan-mint-mock]].
