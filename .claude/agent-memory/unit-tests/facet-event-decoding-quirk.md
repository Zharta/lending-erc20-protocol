---
name: facet-event-decoding-quirk
description: When a function/event moves to a delegatecall facet, boa can no longer decode that event unless conftest's log_stuff() emits it
metadata:
  type: project
---

In `tests/p2p_erc20_multivault/unit/conftest.py`, the main contract fixture
(`p2p_lending_multivault_erc20_contract_def`) appends a `log_stuff()` function that
emits every event the main contract declares but does NOT itself emit in its own
bytecode (events actually emitted live in the delegatecall facets:
Refinance / Liquidation / Loan).

**Why:** boa only registers an event in a contract's ABI (for log decoding) if that
event appears in the contract's own bytecode. Events emitted only via `log main.X(...)`
from a facet during delegatecall are attributed to the main contract address but cannot
be decoded — `get_last_event(p2p_usdc_weth, "X")` then returns an empty list and raises
`IndexError: list index out of range` in `get_last_event` (conftest_base.py).

**How to apply:** Whenever a function (and its event) is extracted from the main
contract into a delegatecall facet, ADD that event to `log_stuff()` in conftest.
Example: when `create_loan` moved to `P2PLendingMultiVaultLoan.vy`, `LoanCreated`
stopped being emitted from main, breaking ~146 tests across test_create / test_add_collateral
/ test_remove_collateral / test_transfer. Fix was adding a `log LoanCreated(...)` call to
`log_stuff()`. This is a conftest wiring fix, never a test-expectation change.

Also: the constructor gained `_loan_addr` (positionally AFTER `_liquidation_addr`,
BEFORE `_vault_impl_addr`). Any test that deploys the contract directly (not via the
`p2p_usdc_weth` fixture) must pass the loan facet address there too — e.g.
test_settle.py::test_settle_loan_creates_pending_transfer_on_erc20_transfer_fail.
