---
name: feedback-concrete-tests
description: Tests must stay concrete and readable — never hide the call-under-test behind a factory/closure, a SimpleNamespace grab-bag, OR a deep multi-level fixture chain with hidden _replace mutations and default kwargs
metadata:
  type: feedback
---

Tests must not be obfuscated. Fixtures and aux functions are fine for stage-setting, but the substance of the test must be visible in the test body.

**Why:** When a test is 3 lines because everything (the contract call, its args, the sender, the concrete amounts) is buried 3 levels deep in conftest, the reader can't verify the assertion math without opening other files. The user explicitly rejected the `leveraged_setup` factory pattern that returned a `SimpleNamespace` grab-bag `s` with a `s.create(**overrides)` closure wrapping `p2p.create_leveraged_loan(...)` — the function under test, its arguments, and the sender were all invisible.

**How to apply (codified in `.claude/docs/test_patterns.md` section 1, "Keep tests concrete — fixtures set the stage, tests do the acting"):**
- The call under test appears in the test body — call the contract fn directly (`p2p.create_leveraged_loan(signed_offer, principal, ...)`), never behind a closure/factory wrapper.
- Values assertions depend on (principal, fees, refunds, collateral, timestamps) are concrete literals or trivially-derived locals IN the test body.
- No `SimpleNamespace`/dict grab-bags returned from fixtures. Return real objects (a contract, a signed offer, a `Loan` NamedTuple).
- One level of indirection max: reading the test + the fixture signatures should fully explain the scenario. Inline setup even if it costs ~10 more lines per test; some duplication across tests is fine, unreadable tests are not.

**The bar is stricter than "no closure around the call-under-test."** Deep fixture CHAINS are also obfuscation, even when each level returns a real `Loan` NamedTuple (not a grab-bag) and calls a contract fn that is NOT the function-under-test. The user overruled an earlier "legitimate exception" that had blessed `make_pending_async_loan`: a 3-4 level chain (`redeeming_async_loan` -> `started_async_loan` -> `make_started_async_loan` -> `make_pending_async_loan`) where each level hid a contract call (`create_leveraged_loan` / `fulfill_deposit` / `start_loan` / `redeem`), a `_replace` mutation, and default kwargs (principal 1000 USDC, mint_spend 1500, shares 10**18). Verdict: "make_pending_async_loan still hiding too much stuff." A test consuming `redeeming_async_loan` couldn't tell what state the loan was in or which calls produced it without tracing 4 conftest layers.

**What a stage-setting fixture that reaches a downstream state MUST do (as refactored in `test_leveraged_async.py` / `test_async_redeem_settle.py`):**
- Live in the TEST FILE, not conftest (the reader sees it right next to the tests).
- Be ONE flat level — self-contained, NOT stacked on another stage fixture. If `started`/`redeeming` need the create sequence, repeat it inline; do not chain onto `pending`. Repetition is acceptable; a chain is not.
- Show the lifecycle calls in sequence with concrete literal amounts (`create_leveraged_loan(...)` -> `fulfill_deposit(vault, 1500*10**6, 10**18)` -> `start_loan(...)` -> `redeem(...)`), the `_replace` transitions visible in the fixture body.
- Only genuinely repetitive struct-building may hide behind a helper, and its inputs must be explicit args (e.g. `expected_pending_despxa_loan(p2p, signed_offer, loan_id, ..., principal=..., collateral=...)`, analogous to `expected_leveraged_loan`). A 30-field Loan builder is legitimate helper work; a `create()` closure is not.
- When a test needs custom fees/window snapshotted at creation, or asserts the create event (get_logs quirk — see [[boa-get-logs-last-computation]]), do the create INLINE in the test body rather than via a fixture.
