---
name: feedback-helpers-local-when-single-file
description: Keep test helpers/fixtures local to the test file when only one file uses them; conftest is for genuinely shared ones
metadata:
  type: feedback
---

Keep a helper or fixture in the test file that uses it when only that one file uses it. `conftest.py`
is for genuinely shared helpers (used by 2+ files).

**Why:** Single-use helpers in conftest add indirection and make a reader open another file to
understand one test. Reinforces [[feedback-concrete-tests]] (one level of indirection max).

**How to apply:** Before adding a helper to conftest, check how many test files call it. Example
(feat/despxa-loop): `expected_leveraged_loan` was used only by `test_create_leveraged.py`, so it lives
there as a module-level function; `expected_pending_despxa_loan` is shared by
`test_leveraged_async.py` + `test_async_redeem_settle.py`, so it stays in `conftest.py`.
