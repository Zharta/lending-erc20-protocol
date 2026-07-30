---
name: feedback-no-mock-protocol-contracts
description: Never mock protocol contracts in unit tests — use the real contract and mock only its external dependencies
metadata:
  type: feedback
---

Never mock PROTOCOL contracts in unit tests. Deploy the REAL contract under test and mock only its
EXTERNAL dependencies (ERC20 tokens, Chainlink oracle, KYC validator, Midas deposit/redemption vaults,
Securitize/Acred swap connectors).

**Why:** A mock standing in for our own vault implementation (e.g. `MultiVaultMock` replacing
`P2PLendingVaultSecuritizeMV` / `P2PLendingVaultMidas`) can drift from the real vault's behavior — the
mock passes while the real contract has a bug. The despxa suite already follows the right pattern:
real `P2PLendingVaultDespxa` + `AsyncVaultMock` (external ERC-7540 async vault mocked).

**How to apply:** When wiring market fixtures, deploy the real vault impl (`P2PLendingVaultSecuritizeMV`,
`P2PLendingVaultMidas`, `P2PLendingVaultDespxa`) and give it mocked external deps:
- Midas vault (`redemption_addr`) → `MidasVaultMock` (deposit + redeem surface, external Midas vaults).
- Securitize/Acred swap connector → `AcredMock` (external DS-token swap).
- Async ERC-7540 vault → `AsyncVaultMock`.
`MultiVaultMock` may ONLY survive where a test genuinely needs a capability combination or dispatch
behavior no real vault has (e.g. unsupported-combo dispatch-revert tests) — leave a comment justifying
each surviving usage.

Related: [[multivault-mock-selectable-capabilities]] (now largely superseded — real vaults preferred),
[[leveraged-loan-mint-mock]] (mint now via real SecuritizeMV + AcredMock, not deposit_vault config).
