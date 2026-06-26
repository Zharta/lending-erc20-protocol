---
name: acredmock-consistent-swap-direction
description: AcredMock swap now uses a CONSISTENT direction — ds=stable*den//num in calc AND liquidity pulled=ds*num//den in swap agree; buy(10)@3/10 refunds 1, not 0
metadata:
  type: project
---

`contracts/auxiliary/AcredMock.vy` `swap`/`calculateDsTokenAmount` are now direction-CONSISTENT (was a
mismatch). Oracle num = rate (answer), den = 10**decimals; num/den = payment per DS token:
- `calculateDsTokenAmount(stable)` / `_ds_token_amount`: `ds = stable * den // num` (credited to
  `pending_transfers`, UNCHANGED).
- `swap(liquidity)`: mints `ds = liquidity * den // num`, then pulls `_liquidityAmount = ds * num // den`
  stablecoin via `transferFrom(msg.sender=vault, self, _liquidityAmount)`. The two now AGREE.
- `set_max_mint_amount(cap)` (0=uncapped) caps `ds` in BOTH calc and swap, so they stay consistent (the
  partial-mint / refund knob for leveraged tests).

**Fallout fixed in the legacy-`P2PLendingVaultSecuritize.buy()` tests** (`test_buy.py` +
`test_vault_securitize.py` in BOTH `tests/p2p_erc20_multivault/unit/` and
`tests/p2p_erc20_securitize/unit/`; the two dir copies are line-identical except the `get_calls` import
and `get_logs(strict=False)`). With oracle 3/10 (num=3, den=10):
- `swap(10)`: `ds = 10*10//3 = 33`, `_liquidityAmount = 33*3//10 = 9` -> consumes 9, **REFUND 1** (was 0
  under the old opposite direction). The old "skips refund for swap(10)" tests were WRONG; renamed to
  `test_buy_refunds_swap_leftover_from_10` etc. and now assert a 1-unit refund.
- `swap(11)`: `ds = 11*10//3 = 36`, `_liquidityAmount = 36*3//10 = 10` -> consumes 10, refund 1 (value
  coincidentally unchanged; docstrings corrected).
- `test_buy_approves_correct_spender`: swap(10) now leaves residual allowance = `10 - 9 = 1` on the swap
  contract (was 0 when it consumed the full 10); re-asserts the nonzero residual on `swap_addr`.
- `pending_transfers` assertions (from `calculateDsTokenAmount = stable*den//num`) are UNCHANGED.
- The 1:1 oracle test (`OracleMock.deploy(1,10)` -> num=10, den=10) still consumes fully (refund 0).

Note: the multivault market leveraged tests use a SEPARATE AcredMock (`acred_lev`, 18-dec, oracle
`deploy(12,1500)`) — the 3/10 `oracle_acred_usdc`/`acred` fixtures are ONLY for the legacy buy/vault
securitize tests. See [[leveraged-loan-real-vault-mint]].
