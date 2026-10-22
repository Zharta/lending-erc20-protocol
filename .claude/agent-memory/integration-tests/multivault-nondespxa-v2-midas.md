---
name: multivault-nondespxa-v2-midas
description: How the non-despxa multivault integration group (ACRED V2-registrar borrower signature, current Midas admin, ACRED oracle heartbeat) was made green at ETH_FORK_BLOCK 25400000
metadata:
  type: project
---

Resolution of the two known-red gaps in `tests/p2p_erc20_multivault/integration/` (non-despxa group) at
the shared `ETH_FORK_BLOCK = 25400000` (see [[shared-fork-block-and-log-stuff]]). All 19 multivault
integration tests (incl. 5 despxa, untouched) + securitize integration 13/13 are green after this.

**1. ACRED tests need a KEY-CONTROLLED borrower + V2 investor signature.**
The V2 registrar connector's `registerVault` (invoked whenever the lending contract creates a per-loan
vault) requires the investor to have stored an EIP-712 authorization via
`registrar_connector.set_investor_signature(deadline, (v,r,s), sender=investor)`; an empty sig reverts
`0x5335c859`. The old multivault borrower fixture was a hardcoded keyless address (`0x81aF...1009`) so it
could not sign. Fix (mirrors the securitize integration suite exactly):
- `integration/conftest.py`: borrower is now `Account.create()` (`borrower_account`/`borrower_key`
  session fixtures + `borrower` fixture). The autouse `borrower_acred_funds` now REGISTERS it as a
  Securitize investor (`securitize_registry.registerInvestor/setCountry/addWallet`, id
  `"zharta_test_investor"`) before issuing ACRED — a fresh account isn't pre-registered on-chain.
- Added `sign_register_vault(account, connector_addr, vault_registrar, deadline)` to the multivault
  `conftest_base.py` (copied verbatim from the securitize `conftest_base.py`; EIP-712 domain
  name="VaultRegistrar" version="1", RegisterVault{investor,operator,token,nonce,deadline}). The sig is
  bound to the investor's CURRENT operator nonce, so ONE stored sig authorizes exactly ONE vault
  registration.
- Added a `set_investor_sig(investor_account, deadline)` callable fixture to `integration/conftest.py`
  (depends on `registrar_connector`+`vault_registrar`) that signs + calls set_investor_signature.
- Every ACRED test/`ongoing_loan_usdc_acred` fixture that calls `create_loan`/`create_leveraged_loan`
  now calls `set_investor_sig(borrower_account, now + 3600)` before the create. Replace/replace_lender
  REUSE `loan.vault_id` (no new registration) so only the initial create needs a sig. `test_transfer`
  registers a NEW vault for the transferred-to borrower -> that `new_borrower` must ALSO be a
  key-controlled `Account.create()`, get `_register_investor(...)`, and `set_investor_sig(new_borrower_account, ...)`.
- mfone + despxa markets don't use the registrar, so their tests are unaffected (they don't pull
  `set_investor_sig`).

**2. Current Midas DEFAULT_ADMIN_ROLE holder @25400000 = `0xd4195CF4df289a4748C1A7B6dDBE770e27bA1227`.**
The old `MIDAS_DEFAULT_ADMIN = 0x875c06a2...` LOST DEFAULT_ADMIN_ROLE on the MidasAccessControl
(`0x0312A9D1Ff2372DDEdCBB21e4B6389aFc919aC4B`) sometime before this block, so its `grantRole` reverted.
Updated the hardcoded `MIDAS_DEFAULT_ADMIN` in `test_loop_mfone.py`. How I re-derived it (repeat on the
next block bump): fork, then enumerate `RoleGranted(DEFAULT_ADMIN_ROLE)` logs and keep the ones that
still `hasRole`:
```python
rpc = boa.env.evm.vm.state._account_db._rpc          # the CachingRPC handle (fork_rpc is a SETTER, unusable)
DEFAULT_ADMIN_ROLE = ac.DEFAULT_ADMIN_ROLE()          # 0x00..00
logs = rpc.fetch("eth_getLogs", [{"fromBlock":"0x0","toBlock":hex(BLOCK),"address":AC,
    "topics":["0x"+keccak(b"RoleGranted(bytes32,address,address)").hex(), "0x"+DEFAULT_ADMIN_ROLE.hex()]}])
holders = [ "0x"+lg["topics"][2][-40:] for lg in logs if ac.hasRole(DEFAULT_ADMIN_ROLE, "0x"+lg["topics"][2][-40:]) ]
```
Two current holders at 25400000: `0xd4195CF4df289a4748C1A7B6dDBE770e27bA1227` (used) and
`0xB60842E9DaBCd1C52e354ac30E82a97661cB7E89`. Verified the chosen one drives the full greenlist chain
(grant GREENLIST_OPERATOR_ROLE to itself, then GREENLISTED_ROLE to the vault). `MIDAS_DV_ADMIN`
(`0x2acb4bdc...`, used for `setMinMTokenAmountForFirstDeposit`) was unchanged. Nothing else drifted for
mfone (fees/whitelist fine); the admin swap alone made all 3 mfone tests green.

**3. Real ACRED Chainlink oracle (`0xD6BcbbC87bFb6c8964dDc73DC3EaE6d08865d51C`) has a ~24h heartbeat and
REVERTS on `latestRoundData()` after time-travel past it.** The proxy delegates to underlying aggregator
`0xe2072fB13FF92D04E44cc55574816dBA3E539e1d` (an "ACRED_FUNDAMENTAL" feed) which reverts `0x245a7bfc`
when stale. At the fork block the feed answer is ALREADY ~9.3h old (updatedAt=1782421811, now=1782455147,
age 33336s), and it tolerates total age up to ~105336s (~29h) — fails by ~112536s. The replace/
replace_lender tests time-travelled `1 * DAY` (86400s) to accrue interest -> total age ~119736s ->
`_get_oracle_rate` reverts inside `replace_loan`/`replace_loan_lender`. Fix WITHOUT weakening: reduce the
travel to `now + 12 * 3600` (12h -> total age ~76536s, well inside the heartbeat). All the interest math
is parameterised off `replace_timestamp - now`/`- accrual_start_time`, so a smaller window auto-scales and
still yields non-zero interest (principal 100e6 @ apr1000 over 12h = 13698). Only replace + replace_lender
time-travel; settle/add/remove/loop don't. NOTE: the securitize integration suite sidesteps this entirely
by using a deployed OracleMock for ACRED — the MULTIVAULT ACRED market uses the REAL chainlink feed on
purpose (true fork integration), so the heartbeat window is a real constraint to respect, not mock away.
Current answer at block: 110077745000 (~$1100.78, 8 dec) — matches the vaulted create sanity range.
