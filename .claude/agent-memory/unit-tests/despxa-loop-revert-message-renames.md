---
name: despxa-loop-revert-message-renames
description: feat/despxa-loop consolidated some revert strings (cancel_redeem claimable guard); stale test assertions must match the new shorter messages
metadata:
  type: project
---

The `feat/despxa-loop` branch's "rework cancelation and liquidation" / "consolidate events" commits
SHORTENED some revert strings in `contracts/v1/P2PLendingMultiVaultLoan.vy`. At least one unit test's
`boa.reverts(...)` assertion was left stale.

Confirmed instance:
- `cancel_redeem` claimable-redemption guard now reverts **`"claimable redeem"`** (line ~525), NOT the
  older `"claimable redeem, settle first"`. `test_cancel_redeem_reverts_if_redeem_claimable` in
  `tests/p2p_erc20_multivault/unit/test_leveraged_async.py` asserted the old string and failed on the
  branch until updated. (The sibling MINT guard `"claimable mint, start instead"` at line ~380 was NOT
  renamed and still stands.)

**Why:** revert-message renames on a feature branch are easy to miss because the test still exercises the
right code path — it just asserts a superseded string. boa reports a bare "does not match (...)" rather
than a code error, so it looks like a deep failure.

**How to apply:** when a test on this branch fails a `boa.reverts` match (not a code error), grep the
exact revert string in `contracts/` FIRST — if the string isn't found, it was renamed; update the test
to the current contract message rather than assuming a contract bug.

Related: [[despxa-async-leveraged-tests]].
