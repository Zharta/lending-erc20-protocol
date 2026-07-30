---
name: preexisting-cancel-redeem-claimable-failure
description: test_cancel_redeem_reverts_if_redeem_claimable fails on feat/despxa-loop, unrelated to additional_collateral work
metadata:
  type: project
---

`tests/p2p_erc20_multivault/unit/test_leveraged_async.py::test_cancel_redeem_reverts_if_redeem_claimable`
fails on branch `feat/despxa-loop` (as of 2026-07-15).

**Why:** Pre-existing failure independent of the `start_loan(additional_collateral)` change. The test
expects `cancel_redeem` to revert `"claimable redeem, settle first"` after a fully-fulfilled redeem, but
the actual revert is `<compiler: external call failed>` (a different, deeper external-call failure).
Reproduced against the staged baseline (only the fixture `start_loan(..., 0, ...)` arg fix applied, none
of the new topup tests) — still failed identically. So it is NOT caused by test edits to this file.

**How to apply:** When you get a green run except for this one test on this branch, it is a known
pre-existing issue in the `cancel_redeem` / async-redeem-fulfill path (likely the mock or contract), not
a regression from your change. Do not "fix" it by weakening the assertion. Full unit suite otherwise:
494 passed, 1 skipped, this 1 failed. Integration suite fully green (29 passed).
