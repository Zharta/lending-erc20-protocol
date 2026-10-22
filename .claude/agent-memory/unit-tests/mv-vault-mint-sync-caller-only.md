---
name: mv-vault-mint-sync-caller-only
description: MV vault mint_sync (SecuritizeMV + Midas) is caller-only — tests must drive it via a caller distinct from owner, never as owner; _check_user is gone from both MV vaults
metadata:
  type: project
---

Both MultiVault vaults — `contracts/v1/P2PLendingVaultSecuritizeMV.vy` and
`contracts/v1/P2PLendingVaultMidas.vy` — guard `mint_sync` (and `redeem_sync`) with a strict
`assert msg.sender == self.caller, "unauthorized"` as the FIRST line. Only the lending contract (the
initialiser, `self.caller`) may call. The old `_check_user(self.owner) or msg.sender == self.caller`
guard, the `_check_user` internal, and its `P2PLendingContract` interface were DELETED from both.

**Why:** under the D2 funding model the vault spends its OWN pre-funded balance, so an owner-callable
`mint_sync` let the borrower convert vault payment token (e.g. SecuritizeMV redemption proceeds awaiting
the manual-redeem settle) into DS/mtoken credited to `pending_transfers[owner]` and drain it via
`withdraw_pending` — a real theft vector on SecuritizeMV during the settle window. Midas settles
atomically (REDEEM_SYNC) so no cross-tx window, but the owner path was removed for consistency.

**How to apply (test plumbing):**
- Initialise MV vaults from a distinct `caller_addr` (`boa.env.generate_address("lending_contract")`),
  NOT from `owner`. If caller == owner, an owner-sender mint_sync passes by COINCIDENCE and the
  caller-only guard is never actually exercised — this is the trap the pre-fix `test_vault_midas.py`
  happy-path tests fell into (`midas_vault` was `initialise(..., sender=owner)`, so `sender=owner`
  mint_sync satisfied the guard). Keep caller and owner separate; drive mint_sync/redeem_sync with
  `sender=caller_addr`. `pending_transfers`/mint credit still lands on `owner`, so credit assertions
  stay on `owner`.
- Negative auth test: assert BOTH a random EOA AND the owner/borrower revert `"unauthorized"` (owner is
  the closed theft vector). Do NOT reference `_check_user` / `min_vault_manager` / authorized-proxy
  semantics for mint_sync — that path is gone; a `min_vault_manager` contract-caller is no longer needed
  for these (it was only there so `_check_user`'s staticcall to `caller.authorized_proxies` resolved).

**Test locations:** Midas mint_sync/redeem_sync unit tests live in
`tests/p2p_erc20_multivault/unit/test_vault_midas.py`. SecuritizeMV theft-vector regression lives in
`tests/p2p_erc20_multivault/unit/test_vault_securitize_mv.py` (NEW focused file — the MV vault had no
dedicated unit test before; `test_vault_securitize.py` tests the LEGACY `P2PLendingVaultSecuritize.vy`
with `buy()`/`_check_user`/proxies, which is UNCHANGED). The MV vault `mint_sync` resolves its swap from
`getDSService(1<<14)` on the collateral token, so the collateral must be an AcredMock; oracle
`deploy(12, 1500)` (num=1500, den=10**12) maps 1500e6 USDC -> exactly 1e18 DS. See
[[leveraged-loan-mint-mock]], [[acredmock-consistent-swap-direction]].
