---
name: dejtrsy-eth-fork
description: Real deJTRSY (Ethereum) Centrifuge V3 AsyncVault addresses + discovery values for test_loop_dejtrsy.py; a third fully-async pool mirroring test_loop_dejaaa.py verbatim
metadata:
  type: project
---

`tests/p2p_erc20_multivault/integration/test_loop_dejtrsy.py` — third real-pool sibling of
`[[despxa-centrifuge-fork]]` (deJAAA/Eth) and `[[despxa-base-fork]]` (deSPXA/Base). Same
`P2PLendingVaultCentrifugeAsync` impl, same 5 flows, same chain-neutral `centrifuge_*` conftest
helpers, same all-effects standard. Runs on the shared `ETH_FORK_BLOCK = 25400000`.

**deJTRSY addresses (Ethereum mainnet, discovered on-fork @25400000):**
- deJTRSY share token (collateral, **18 dec**): `0xA6233014B9b7aaa74f38fa1977ffC7A89642dC72`
- AsyncVault (deJTRSY/USDC, via `share.vault(usdc)`): `0x18Ab9fC0B2e4Fef9e0e03c8EC63BA287a3238257`.
  `vault.manager()` does NOT revert here (unlike the deSPXA Base vault) and == the shared manager.
- AsyncRequestManager: `0xF48256AbDDf96EcDDc4B3DbD23E8C1921f9761Ae` (SAME as deJAAA/deSPXA)
- Spoke: `0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB`; Root: `0x7Ed48C31f2fdC40d37407cBaBf0870B2b688368f`
  (both SAME as deJAAA — impersonate spoke to fulfil, root to whitelist)
- **Hook (live via `share.hook()`): `0xD51D8450DCAdfF570424194251E3b165594Aa2a0`** — DIFFERENT from
  deJAAA's `0x2a9B9C1485...`. Read live (never hardcode). Whitelisting still works via the same
  `centrifuge_whitelist(hook, token, vault, root)` (updateMember impersonating root).
- Oracle (CentrifugeOracleAdapter deJTRSY/USD, oracle_reverse=false): `0xB3fa00f2F9DD20E5503bB1EBe398074eAbf418d9`
  — **18 decimals**, answer `1028903789003160000` (~1.0289 USDC/deJTRSY) @25400000 (matches the
  vaulted create sanity range). Bound via `oracle_contract_def.at(...)` like deJAAA (a REAL adapter, no
  deploy — unlike deSPXA/Base which needs a fresh adapter).
- USDC (6 dec): `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`; whale `0x99C9fc46...`.
- **poolId = 281474976710660**; **scId = 0x00010000000000040000000000000001** (read `vault.poolId()`/
  `vault.scId()`; both differ from deJAAA's `...710659` / `...0003...`).
- assetId (USDC) = `spoke.assetToId(usdc,0)` = `5192296858534827628530496329220097` (SAME as deJAAA —
  USDC on the same chain).
- Price: `convertToShares(1e6 usdc)` ≈ 0.9719e18 deJTRSY.

**Vault bytecode is NOT byte-identical to deJAAA's** (task claimed it was) but is the SAME runtime with
different embedded immutables: same length (12099), only 114 differing bytes, and the diff region literally
shows the scId `...0004...` vs deJAAA's `...0003...`. So it's the same fully-async AsyncVault impl — the
`centrifuge_*` recipe applies verbatim.

**Cancel is SYNCHRONOUS (Ethereum), like deJAAA — no issuer cancel-fulfil step** between the two
`cancel_pending_loan` / `cancel_redeem` calls (flows 2 and 5). Only Base/deSPXA needs the async
cancel-fulfil.

**No deJTRSY-specific surprises.** All 5 flows passed on the FIRST run, no whitelisting/price/heartbeat
quirks. Full multivault integration dir is now 29/29 (5 deJAAA + 5 deJTRSY + 5 deSPXA + 14 non-despxa).
The file is a near-verbatim copy of test_loop_dejaaa.py with `dejaaa`->`dejtrsy` / `DEJAAA_*`->`DEJTRSY_*`.
