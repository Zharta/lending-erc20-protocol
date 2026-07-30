---
name: boa-get-logs-last-computation
description: get_last_event/get_logs read the contract's LAST computation, so a p2p view call after a tx returns the view's empty logs — read getters BEFORE the tx
metadata:
  type: feedback
---

`get_last_event(contract, ...)` (conftest_base) calls `contract.get_logs()`, which returns logs from
the contract's most recent computation. A view/getter call on that same contract counts as a
computation.

**Why it bites:** a test helper that, after the event-emitting tx, calls `p2p.protocol_upfront_fee()`
/ `p2p.max_pending_window()` etc. to build the expected Loan will reset `p2p`'s last computation to
that empty view call, so `get_last_event(p2p, "SomeEvent")` finds nothing and raises
`IndexError: list index out of range`. Storage-based assertions (`p2p.loans(id)` compared to a
Python-computed hash) still pass, which makes the failure look event-specific.

**How to apply:** in tests that assert events, make the event-emitting tx the LAST call on that
contract. Snapshot any p2p getters you need BEFORE the tx (see `_read_fee_params` in
`test_leveraged_async.py`). `boa.eval(...)`, `compute_loan_hash`, `compute_signed_offer_id` are safe
after the tx — they run in an anonymous boa context and do NOT touch the contract's `_computation`.
Calls to OTHER contracts (usdc/weth/mock) are also safe; only a view call on the same contract you
call `get_logs` on resets it.

Related: [[facet-event-decoding-quirk]] (a different, ABI-level reason facet events fail to decode).
