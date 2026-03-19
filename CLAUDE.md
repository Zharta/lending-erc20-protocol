# Zharta P2P ERC20 Lending Protocol

A peer-to-peer lending protocol enabling ERC20 tokens as collateral for loans. Borrowers deposit collateral and receive loans; lenders provide capital and earn interest. All participants require KYC validation.

## Tech Stack

- **Contracts**: Vyper 0.4.3
- **Testing**: pytest + titanoboa (py-evm)
- **Development**: eth-ape framework, Python 3.11+
- **Oracles**: Chainlink AggregatorV3
- **Package Management**: uv

## Project Structure

```
contracts/
  v0/                   # Legacy version
    P2PLendingV0Erc20.vy    # Main entry point
    P2PLendingV0Base.vy     # Shared state and logic
    P2PLendingV0Refinance.vy
    P2PLendingV0Securitize.vy
  v1/                   # Production versions (standard, vaulted, and securitize)
    # Standard contracts (direct collateral)
    P2PLendingErc20.vy      # Main entry point
    P2PLendingBase.vy       # Shared state and logic
    P2PLendingRefinance.vy  # Refinancing facet (delegatecall)
    P2PLendingLiquidation.vy # Liquidation facet (delegatecall)
    # Vaulted contracts (vault-based collateral)
    P2PLendingVaultedErc20.vy    # Main entry point with vault system
    P2PLendingVaultedBase.vy     # Shared state with vault logic
    P2PLendingVaultedRefinance.vy
    P2PLendingVaultedLiquidation.vy
    P2PLendingVault.vy      # Per-borrower collateral vault (CREATE2 proxy)
    P2PLendingVaultProfitr.vy # Profitr securitization vault
    # Securitize contracts (DS Token collateral with redemption)
    P2PLendingSecuritizeErc20.vy    # Main entry point for Securitize DS tokens
    P2PLendingSecuritizeBase.vy     # Shared state with redemption logic
    P2PLendingSecuritizeRefinance.vy # Refinance + maturity extension facet
    P2PLendingSecuritizeLiquidation.vy # Liquidation with redemption handling
    P2PLendingVaultSecuritize.vy    # Vault with SecuritizeSwap integration
    P2PLendingSecuritize.vy  # Single-borrower variant (direct collateral)
  auxiliary/            # Mock contracts for testing
  KYCValidator.vy       # KYC signature validation

tests/
  p2p_erc20_v1/
    unit/               # Unit tests with mocked dependencies
    integration/        # Forked chain tests
  p2p_erc20_vaulted/
    unit/
    integration/
    profitr/            # Securitization integration tests
  conftest.py

scripts/
  deployment.py         # Main deployment script
  _helpers/             # Deployment utilities

configs/
  local/                # Local Anvil config
  dev/                  # Private network config
  int/                  # Sepolia testnet config
  prod/                 # Mainnet config
```

## Essential Commands

```bash
# Setup
make install-dev          # Install dev dependencies + pre-commit hooks

# Testing
make unit-tests           # Run all unit tests (parallel)
make integration-tests    # Run integration tests
make coverage             # Run coverage report
make branch-coverage      # Run branch coverage
make gas                  # Gas profiling

# Development
make compile              # Compile contracts with ape
make console-local        # Interactive console (local)
make deploy-local         # Deploy to local Anvil

# Other environments
make deploy-sepolia       # Deploy to Sepolia
make console-sepolia      # Console for Sepolia
```

## Testing Notes

- First unit test run may fail due to titanoboa cache initialization - run twice
- Unit tests mock external dependencies (ERC20, oracle, KYC validator)
- Integration tests use forked mainnet data
- Test helpers in `tests/p2p_erc20_vaulted/conftest_base.py` provide:
  - `sign_offer()` - EIP-712 offer signing
  - `sign_kyc()` - KYC validation signing
  - `Loan`, `Offer`, `SignedOffer` NamedTuples mirroring Vyper structs

## Key Concepts

- **Loans**: Created from signed offers; tracked via hash in `loans` mapping
- **Offers**: EIP-712 signed off-chain, validated on-chain
- **LTV**: Loan-to-Value ratio for liquidation triggers
- **Callable Loans**: Lenders can call loans after eligibility period
- **Partial Liquidation**: "Heals" loans back to initial LTV when threshold exceeded

## Contract Versioning

- **v0**: Legacy version (contracts/v0/)
- **v1 (Standard)**: Collateral held directly in main contract (P2PLendingErc20)
- **v1 (Vaulted)**: Collateral isolated in per-borrower vaults using CREATE2 minimal proxies (P2PLendingVaultedErc20)
- **v1 (Securitize)**: Designed for Securitize DS Token collateral with redemption workflow (P2PLendingSecuritizeErc20)

All v1 contracts use delegatecall facets for Refinance and Liquidation logic.

### Securitize Contracts Key Features:
- **Multiple vaults per borrower**: Each loan creates a new vault (tracked via `vault_id`)
- **Redemption workflow**: Collateral can be redeemed via Securitize (collateral → payment token)
- **Maturity extensions**: `extend_loan` and `extend_loan_lender` functions
- **No callable loans**: call_eligibility/call_window not supported
- **SecuritizeSwap integration**: Vaults can buy DS tokens from stablecoins via `buy()` function
- **Signed redemption results**: Settlement/liquidation verifies redemption via owner-signed attestations

## Configuration

Deployment configs in `configs/{env}/{chain}/p2p.json` contain:
- Contract addresses
- Token addresses (payment, collateral)
- Oracle configuration
- Fee parameters

## Additional Documentation

When working on specific topics, refer to:

- `.claude/docs/architectural_patterns.md` - Contract architecture, design patterns, and conventions
- `.claude/docs/test_patterns.md` -  Tests creation, validation and fixing
- `README.md` - Full protocol documentation with function signatures and state variables
- `audits/` - Security audit reports and remediations


## Agent Delegation

**IMPORTANT**: Proactively delegate test work to specialized agents — do not write or fix tests yourself.

- **`unit-tests` agent**: Use whenever unit tests need to be written, validated, or fixed. This includes after writing or modifying contract functions, when test failures are reported, or when the user asks about test coverage.
- **`integration-tests` agent**: Use whenever integration tests need to be written, validated, or fixed. This includes after writing or modifying contract functions that affect the loan lifecycle, when integration test failures are reported, or when the user asks for fork-based testing.
- **`mutation-tests` agent**: Use whenever the user asks to find test coverage gaps, run mutation testing, or verify test quality. Systematically mutates contract code and identifies surviving mutations (mutations that don't break tests). Spawns `unit-tests` sub-agents to write tests that kill surviving mutations. Tracks progress in `.claude/plans/mutations_to_fix.md` and avoids repeating work via its agent memory. **Always launch with `isolation: "worktree"`** since it temporarily mutates contract source files during testing. **Always include the current branch name in the prompt** (e.g., "Current branch: feat/my-branch") so the agent can checkout that branch in the worktree instead of working on `main`.

Trigger these agents automatically when the task involves test work — don't wait for the user to ask for them by name.

## Working on new features or fixing bugs

**IMPORTANT**: When working on a new feature or bug fix, create a git branch first. Then work on changes in that branch for the remainder of the session.
