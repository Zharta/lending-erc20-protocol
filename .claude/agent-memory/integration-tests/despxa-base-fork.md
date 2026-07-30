---
name: despxa-base-fork
description: Real deSPXA (Base) Centrifuge V3 ERC-7540 addresses + Base-vs-Ethereum cancel-async difference for the test_loop_despxa.py suite; BASE_FORK_BLOCK + eth->base RPC derivation
metadata:
  type: project
---

How the deSPXA-on-Base integration suite (`tests/p2p_erc20_multivault/integration/test_loop_despxa.py`)
tests the SAME `P2PLendingVaultDespxa` impl as the deJAAA suite, but against the real deSPXA token on a
BASE mainnet fork. Sibling of `[[despxa-centrifuge-fork]]` (deJAAA/Ethereum); read that first for the core
fulfilment recipe — this note only records the Base-specific deltas.

**Base Centrifuge V3 is the SAME deployment vintage as Ethereum.** The manager / spoke / hook / root /
balanceSheet all share the IDENTICAL addresses across chains (Centrifuge deploys deterministically). So the
`centrifuge_whitelist` / `centrifuge_fulfill_deposit` / `centrifuge_fulfill_redeem` module functions in
`integration/conftest.py` are reused verbatim — they take spoke/root/pool_id/scid/asset_id as EXPLICIT ARGS
(refactored away from hardcoded deJAAA constants during the deJAAA->dejaaa rename), the deSPXA suite just
passes its own DESPXA_* constants.

**Base addresses (mainnet fork, discovered on-fork; recorded in conftest.py `DESPXA_*` constants):**
- deSPXA share token (collateral, **18 dec**): `0x9c5C365e764829876243d0b289733B9D2b729685`
- AsyncVault (deSPXA/USDC, ERC-7575): `0x2dA40F061536c2f3a8f95f23a5f4c133d07D393a` — discover via
  `share.vault(usdc)`. NOTE `vault.manager()` REVERTS on this vault; use `vault.asyncManager()` /
  `vault.baseManager()` / `vault.asyncRedeemManager()` (all == the manager below).
- Manager (AsyncRequestManager): `0xF48256AbDDf96EcDDc4B3DbD23E8C1921f9761Ae` (same as Ethereum)
- Spoke: `0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB` (same as Ethereum) — impersonate to fulfil
- Root: `0x7Ed48C31f2fdC40d37407cBaBf0870B2b688368f` (same as Ethereum) — impersonate to whitelist
- Hook (CentrifugeFullRestrictions): `0x2a9B9C14851Baf7AD19f26607C9171CA1E7a1A61` (same as Ethereum);
  `share.hook()` returns it live.
- balanceSheet: `0x12a110cE5f0FC871cC72Bc7ECaF35cf39DD0f43e` (same as Ethereum)
- USDC (**6 dec**): `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- USDC whale (honest transfer, ~32M on-fork): `0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB` (Aave aBasUSDC
  pool). The Circle bridge `0xcDAC0d6c...885C43` (~4M) is a CONTRACT that blocks transfers — don't use it.
- poolId (uint64) = `281474976710668`; scId (bytes16) = `0x000100000000000c0000000000000001`
- assetId (uint128) for USDC = `spoke.assetToId(usdc,0)` = `10384593717069655257060992658440193`
- Price: `spoke.pricePoolPerShare(poolId,scId,True)` ~= **757.49 USDC/deSPXA** (D18). Marker maxAge is
  uint64 MAX (never stale), so it survives the time-travel flows. deSPXA is EXPENSIVE:
  `convertToShares(1e6 usdc)` ~= 1.32e15 shares.

**deSPXA / USDC Base decimals = 18 / 6 — IDENTICAL to deJAAA.** So the `_size_leverage` sizing math and the
force-unwind share-split math are shared verbatim; the ONLY numeric difference from deJAAA is the price
(~757 vs ~1.04 USDC/share), and every amount is derived live from the oracle + convertToShares.

**Oracle: DEPLOY a FRESH CentrifugeOracleAdapter on the Base fork.** No Base p2p config / oracle exists
(configs/ has only ethereum/sepolia/zethereum). `contracts/CentrifugeOracleAdapter.vy.deploy(DESPXA_SPOKE,
DESPXA)` prices deSPXA on-fork at ~757.49 USDC (D18, decimals()==18) — a REAL adapter, NOT a mock. The
`despxa_oracle` fixture deploys it under the Base env; the market wires `despxa_oracle.address`.

**THE KEY BASE-vs-ETHEREUM DIFFERENCE: cancel is ASYNCHRONOUS on Base (synchronous on Ethereum).** On the
Base manager, `cancelDepositRequest` / `cancelRedeemRequest` only SUBMIT the cancel: right after,
`pendingCancelDeposit==True` but `pendingDepositRequest` is STILL the full amount and
`claimableCancelDeposit==0`. The reclaimed payment/shares become claimable ONLY after the issuer relays a
fulfilment. So the contract's async-cancel state machine (`request_pending -> cancel_pending ->
cancel_claimable`, in `P2PLendingMultiVaultLoan.cancel_pending_loan` / `cancel_redeem`) needs a real issuer
step BETWEEN the two `cancel_*` calls on Base (whereas deJAAA needs only two back-to-back calls). Two new
chain-neutral helpers in conftest.py drive it (no-op on Ethereum, load-bearing on Base):
- `centrifuge_fulfill_cancel_deposit(manager, pool_id, scid, asset_id, controller, assets, spoke)` —
  FulfilledDepositRequest (type 4) with `fulfilledAssets=0, fulfilledShares=0, cancelledAssets=assets`.
- `centrifuge_fulfill_cancel_redeem(manager, pool_id, scid, asset_id, controller, shares, spoke)` —
  FulfilledRedeemRequest (type 5) with `fulfilledAssets=0, fulfilledShares=0, cancelledShares=shares`.
After each, `claimableCancelDeposit/RedeemRequest == the full amount`. This is a real Centrifuge deployment
difference, NOT a contract bug — the contract handles both correctly.

**BASE_FORK_BLOCK = 48500000** (`tests/fork_helpers.py`, next to ETH_FORK_BLOCK — one block per chain, same
rule; profitr/Fuji is the precedent for a second chain). Recent Base block where the vault prices and the
spoke is live. RPC derivation: `os.environ["BOA_FORK_RPC_URL"].replace("eth-mainnet","base-mainnet")`
(alchemy URL). If the `base-mainnet` substring is absent after the replace, the module skips
(`base_boa_env` fixture does `pytest.skip`).

**Base env needs its OWN everything.** A Base fork is a different env than the dir's Ethereum `boa_env`, so
the Base suite has its own `base_boa_env` (@BASE_FORK_BLOCK, base RPC) + Base-scoped facets
(`base_mv_loan/refinance/liquidation`), kyc (`base_kyc_validator_contract`), vault impl
(`despxa_vault_impl_base`), oracle adapter, usdc, accounts, owner/borrower/lender/keeper, and market
(`p2p_usdc_despxa`). A market wired to the ETHEREUM-env facets would delegatecall into empty code on Base and
silently no-op (returns zero loan id) — same trap as the old cross-env facet bug. The env-agnostic contract
DEFS (session `p2p_lending_multivault_*_contract_def`, `despxa_vault_impl`, KYC def) are reused; only the
deployments differ. Market/facet/kyc deploy logic is factored into the shared `deploy_centrifuge_market(...)`
module helper so `p2p_usdc_dejaaa` and `p2p_usdc_despxa` don't copy-paste.

**Rename map applied to the deJAAA suite (Part 1 of this task):** fixtures `despxa_dejaaa->dejaaa_token`,
`despxa_oracle->dejaaa_oracle`, `despxa_async_vault->dejaaa_async_vault`, `despxa_manager->dejaaa_manager`,
`despxa_hook->dejaaa_hook`, `despxa_asset_id->dejaaa_asset_id`, `despxa_keeper->dejaaa_keeper`; module fns
`despxa_whitelist->centrifuge_whitelist(hook,token,addr,root)`, `despxa_fulfill_deposit->
centrifuge_fulfill_deposit(manager,pool_id,scid,asset_id,controller,assets,shares,spoke)`,
`despxa_fulfill_redeem->centrifuge_fulfill_redeem(...,shares,assets,spoke)`; consts `DESPXA_*->DEJAAA_*`
(vault/manager/spoke/root/oracle/usdc/pool_id/scid). KEPT: `despxa_vault_impl` (it IS the shared
P2PLendingVaultDespxa impl), `p2p_usdc_dejaaa`, and the chain-neutral `_RC_*` tags / `_D18_ONE` /
`_left_investor`.

**All 5 flows PASS on Base** (create/start/settle happy path; cancel pending unfilled; force-unwind D28 on
under-min fill; async redeem blocks settle; cancel_redeem reversal). No flow was blocked. Same all-effects
standard as deJAAA (state hash + full events + balances + liquidity, no weakened assertions). The boa async-
create event-unobservability limitation is identical (create validated via loan-HASH, every other op's event
asserted in full). Full integration dir: 24/24 green (5 deJAAA + 5 deSPXA + 14 non-despxa — the non-despxa
V2/Midas gap from `[[shared-fork-block-and-log-stuff]]` has since been fixed on this branch and is now green).
