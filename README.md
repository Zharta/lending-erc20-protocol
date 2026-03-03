# Zharta P2P ERC20 Lending Protocol

## Introduction

This protocol implements a peer-to-peer lending system for ERC20 tokens, available in two main versions: non-vaulted and vaulted. Both allow ERC20 token owners to use their assets as collateral to borrow cryptocurrency, while lenders can provide loans and earn interest. The protocol is designed to be trustless, efficient, and flexible, with support for various ERC20 tokens as collateral. It also includes features for dynamic collateral management, partial liquidations, and loan refinancing. The vaulted version introduces a robust vault system for enhanced compliance and isolated collateral management.

## Overview

The protocol is implemented in Vyper 0.4.3. It exists in three primary versions:

*   **Non-vaulted**: The initial version, where collateral is held directly by the main lending contract. The main component is the `P2PLendingErc20` contract, which supports peer-to-peer lending backed by ERC20 collateral. It utilizes `P2PLendingBase` for shared state and common logic, `P2PLendingRefinance` as a facet for complex refinancing operations, `P2PLendingLiquidation` as a facet for liquidation operations, and interacts with a `KYCValidator` contract for compliance checks.
*   **Vaulted**: An updated version featuring a dedicated vault system for managing collateral. This enhancement provides better isolation of borrower collateral, which is crucial for compliance requirements and enhanced security. The main entry point for the vaulted version is `P2PLendingVaultedErc20`, which leverages `P2PLendingVaultedBase` for core logic, `P2PLendingVaultedRefinance` and `P2PLendingVaultedLiquidation` as facets, and integrates with `KYCValidator` and a new `P2PLendingVault` contract for collateral handling.
*   **Securitize**: A specialized version designed for Securitize DS Token collateral. This version supports the unique requirements of security tokens, including a redemption workflow where collateral can be converted back to payment tokens via Securitize. The main entry point is `P2PLendingSecuritizeErc20`, using `P2PLendingSecuritizeBase` for core logic, `P2PLendingSecuritizeRefinance` and `P2PLendingSecuritizeLiquidation` as facets, and `P2PLendingVaultSecuritize` for vault management with SecuritizeSwap integration.

The lending of an NFT in the context of this protocol means that:
1.  A lender provides a loan offer with specific terms
2.  A borrower creates a loan using their NFT as collateral
3.  The loan is created when the borrower accepts an offer
4.  The borrower repays the loan within the specified term
5.  If the borrower defaults, the lender or a liquidator can trigger a full liquidation to claim the ERC20 collateral.
6.  The loan can be partially liquidated if the Loan-to-Value (LTV) ratio exceeds a certain threshold.
7.  The lender can "call" a loan, initiating a repayment window before maturity.
8.  Borrowers can add or remove collateral from an ongoing loan.
9.  A loan may be replaced by the borrower while still ongoing, by accepting a new offer (refinancing).
10. A loan may be replaced by the lender while still ongoing, within some defined conditions (lender-initiated refinancing).

## Core Contracts

The protocol consists of the following core contracts:

### Non-Vaulted Core Contracts
- `P2PLendingErc20.vy`: The main entry point for users to interact with the lending protocol.
- `P2PLendingBase.vy`: An abstract base contract that holds the core state variables and implements common internal logic shared across lending contracts.
- `P2PLendingRefinance.vy`: A facet contract (called via `delegatecall`) that handles the complex logic for loan refinancing, for both borrower- and lender-initiated replacements.
- `P2PLendingLiquidation.vy`: A facet contract (called via `delegatecall`) that handles the logic for partial and full loan liquidations.
- `KYCValidator.vy`: A contract responsible for validating signed KYC (Know Your Customer) attestations for borrowers and lenders.

### Vaulted Core Contracts
- `P2PLendingVaultedErc20.vy`: The main entry point for users to interact with the vaulted lending protocol, incorporating the vault system.
- `P2PLendingVaultedBase.vy`: An abstract base contract for the vaulted version that holds core state variables and implements common internal logic, including vault interactions.
- `P2PLendingVaultedRefinance.vy`: A facet contract for the vaulted version (called via `delegatecall`) handling loan refinancing logic.
- `P2PLendingVaultedLiquidation.vy`: A facet contract for the vaulted version (called via `delegatecall`) handling loan liquidation logic.
- `P2PLendingVault.vy`: A minimal proxy factory and implementation for individual borrower collateral vaults, deployed via CREATE2. Each vault holds the collateral for a borrower's loans and provides isolated management.
- `KYCValidator.vy`: (Same as non-vaulted) A contract responsible for validating signed KYC (Know Your Customer) attestations for borrowers and lenders.

### Securitize Core Contracts
- `P2PLendingSecuritizeErc20.vy`: The main entry point for Securitize DS Token lending, with redemption workflow support.
- `P2PLendingSecuritizeBase.vy`: An abstract base contract for the Securitize version that holds core state variables, implements redemption verification, and manages multiple vaults per borrower.
- `P2PLendingSecuritizeRefinance.vy`: A facet contract (called via `delegatecall`) handling loan refinancing and maturity extension logic.
- `P2PLendingSecuritizeLiquidation.vy`: A facet contract (called via `delegatecall`) handling loan liquidation with redemption-aware settlement.
- `P2PLendingVaultSecuritize.vy`: A vault implementation with SecuritizeSwap integration, enabling the purchase of DS tokens from stablecoins.
- `KYCValidator.vy`: (Same as other versions) A contract responsible for validating signed KYC attestations.

### Auxiliary Contracts
- `SecuritizeRegistrarV1Connector.vy`: A bridge contract that connects P2P lending vaults to the Securitize Vault Registrar. The P2P lending contracts (both vaulted and securitize) call the connector's `register_vault(vault, investor_wallet)` function automatically during vault creation. The contract maintains an allowlist of authorized P2P lending contracts and can only be managed by the owner.

## General considerations

The current status of the protocol follows certain assumptions:

1.  Support for any ERC20 token as collateral, specified at deployment (held directly by the main contract in the non-vaulted version, and within a dedicated vault for each borrower in the vaulted version).
2.  Use of an ERC20 token (e.g., USDC) as a payment token, defined at deployment time for each instance of `P2PLendingErc20` or `P2PLendingVaultedErc20`.
3.  Integration with an oracle (Chainlink AggregatorV3) for collateral valuation.
4.  All participants (borrower and lender) must have valid KYC attestations signed by a whitelisted KYC validator.
5.  Loan terms are part of the lender offers, which are signed and kept off-chain.
6.  Offers have an expiration timestamp and can be revoked on-chain.
7.  Loans can be callable by the lender after a specified `call_eligibility` period, starting a `call_window` for repayment before default.
8.  Loans can be partially liquidated if the LTV exceeds a `partial_liquidation_ltv` threshold.
9.  Dynamic collateral management (add/remove ERC20 collateral) is supported, managed directly by the main contract in the non-vaulted version, and through the borrower's dedicated vault in the vaulted version.
10. Additional fees are supported both for the protocol (upfront and settlement) and for the lender (origination).
11. The vaulted version uses a vault system (`P2PLendingVault`) to hold collateral. Each borrower has a unique vault, deployed via CREATE2, enhancing collateral isolation and compliance.
12. The Securitize version creates a new vault for each loan, supports collateral redemption via Securitize, and allows maturity extensions. Callable loans are not supported.

## Security

Below are the smart contract audits performed for the protocol so far.

| **Auditor** | **Version** | **Status** | **PDF** |
| :----------: | :---------: | :--------: | ------- |
| Hexens | v0 | Done | [hexens-zharta-oct-25-final.pdf](https://github.com/Zharta/lending-erc20-protocol/blob/main/audits/hexens-zharta-oct-25-final.pdf) |
| Hexens | v1 | Done | [hexens-zharta-dec-25-final.pdf](https://github.com/Zharta/lending-erc20-protocol/blob/main/audits/hexens-zharta-dec-25-final.pdf) |


## Architecture

### Non-Vaulted Architecture

The `P2PLendingErc20.vy` contract is the main entry point for users, inheriting most of its state and common logic from `P2PLendingBase.vy`. The `P2PLendingRefinance.vy` contract handles the complex refinancing flows, being called via a `delegatecall` from `P2PLendingErc20.vy` to share the same storage. Similarly, `P2PLendingLiquidation.vy` handles liquidation logic via `delegatecall`. The `KYCValidator.vy` contract is an external dependency used for compliance checks.

Users and other protocols should primarily interact with the `P2PLendingErc20.vy` contract. This contract is responsible for:
*   Creating loans based on signed offers and ERC20 collateral, including KYC validation (collateral held directly by the contract).
*   Settling loans and distributing funds (returning collateral directly).
*   Handling defaulted loans by allowing lenders to claim collateral (collateral transferred directly to lender).
*   Performing partial liquidations based on LTV thresholds (collateral transferred directly to liquidator/lender).
*   Initiating loan calls by lenders.
*   Allowing borrowers to add or remove collateral from existing loans (collateral deposited/withdrawn directly).
*   Facilitating loan refinancing for both borrowers and lenders via the `P2PLendingRefinance` facet.
*   Managing protocol fees and authorized proxies.
*   Revoking unused offers.

### Vaulted Architecture

The `P2PLendingVaultedErc20.vy` contract serves as the main entry point for the vaulted version. It uses `P2PLendingVaultedBase.vy` for common logic and state, which has been updated to interact with the `P2PLendingVault` system. Each borrower has a unique, minimal proxy vault deployed via CREATE2 (`P2PLendingVault`), which securely holds their collateral. Refinancing and liquidation logic are handled by `P2PLendingVaultedRefinance.vy` and `P2PLendingVaultedLiquidation.vy` facets, respectively, which also interact with the vaults. The `KYCValidator.vy` remains an external dependency.

Users and other protocols should primarily interact with the `P2PLendingVaultedErc20.vy` contract. This contract is responsible for:
*   Creating loans based on signed offers and ERC20 collateral, including KYC validation (collateral deposited into the borrower's dedicated vault).
*   Settling loans and distributing funds (collateral withdrawn from the vault and returned to the borrower).
*   Handling defaulted loans by allowing lenders to claim collateral (collateral transferred from the borrower's vault to the lender).
*   Performing partial liquidations based on LTV thresholds (collateral transferred from the borrower's vault to the liquidator/lender).
*   Initiating loan calls by lenders.
*   Allowing borrowers to add or remove collateral from existing loans (collateral deposited into/widhrawn from the borrower's vault).
*   Facilitating loan refinancing for both borrowers and lenders via the `P2PLendingVaultedRefinance` facet.
*   Managing protocol fees and authorized proxies.
*   Revoking unused offers.
*   Supporting loan transfers to new borrowers, including transferring collateral ownership in their respective vaults.

### Securitize Architecture

The `P2PLendingSecuritizeErc20.vy` contract serves as the main entry point for Securitize DS Token lending. It builds upon the vaulted architecture but adds specific features for security tokens:

*   **Multiple Vaults per Borrower**: Unlike the standard vaulted version where each borrower has a single vault, the Securitize version creates a new vault for each loan (`vault_id`). This allows for better tracking and isolation of collateral per loan, as well as to track redeption results back to the redeemed loan.
*   **Redemption Workflow**: Borrowers can initiate a `redeem` process to convert their DS Token collateral back to payment tokens via the Securitize platform. The `redeem_start` timestamp and `redeem_residual_collateral` track this process.
*   **Maturity Extensions**: Unlike other versions, the Securitize contracts support extending loan maturity via `extend_loan` (borrower-initiated with lender's signed offer) and `extend_loan_lender` (lender-initiated, no borrower action needed).
*   **No Callable Loans**: The `call_eligibility` and `call_window` features are disabled for Securitize loans.
*   **SecuritizeSwap Integration**: The `P2PLendingVaultSecuritize` vault includes a `buy()` function that allows purchasing DS tokens from stablecoins via the SecuritizeSwap contract.
*   **Redemption-Aware Settlement/Liquidation**: When settling or liquidating a redeemed loan, the contract verifies the redemption result (signed by the protocol owner) and handles the mixed collateral/payment token balances appropriately.

Users interact with `P2PLendingSecuritizeErc20.vy` for:
*   Creating loans with DS Token collateral (each loan gets a new vault).
*   Initiating redemption of collateral via `redeem()`.
*   Settling loans (with or without redemption).
*   Extending loan maturity.
*   Adding or removing collateral (only before redemption starts).
*   Loan refinancing for both borrowers and lenders.
*   Managing protocol configuration.

### Offers

Loans are created based on the borrower acceptance of offers from lenders, which specify the loan terms. The general features of an offer are:

1.  **Offer Structure**: An offer is defined by the `Offer` structure (from `P2PLendingBase`/`P2PLendingVaultedBase`), which includes:
    - `principal`: Principal amount of the loan (optional, can be 0 for borrower-defined).
    - `apr`: Annual Percentage Rate.
    - `payment_token`: Address of the payment ERC20 token.
    - `collateral_token`: Address of the collateral ERC20 token.
    - `duration`: Duration of the loan in seconds.
    - `origination_fee_bps`: Origination fee percentage (in basis points) paid to the lender.
    - `min_collateral_amount`: Minimum amount of collateral required (optional).
    - `max_iltv`: Maximum Initial Loan-to-Value (optional, used if `min_collateral_amount` isn't specified).
    - `available_liquidity`: The total principal amount the lender has allocated to this offer.
    - `call_eligibility`: Time in seconds after loan start when the lender can call the loan (0 if not callable).
    - `call_window`: Time in seconds after a loan is called for the borrower to repay before default (0 if not callable).
    - `partial_liquidation_ltv`: LTV threshold (in basis points) for partial liquidation (0 if not applicable).
    - `oracle_addr`: Address of the oracle contract for collateral valuation.
    - `expiration`: Expiration timestamp of the offer.
    - `lender`: Address of the lender.
    - `borrower`: Specific borrower address for the offer (empty address for general offers).
    - `tracing_id`: A unique identifier for tracking offers, enabling multiple loans from one offer.

2.  **Signed Offers**: Lenders create and sign offers off-chain. These signed offers (`SignedOffer`) combine the `Offer` structure with an EIP-712 signature.

3.  **Offer Validation**: When a borrower wants to create a loan using an offer, the protocol verifies the offer's signature, checks if it's still valid (not expired), if the `payment_token` and `collateral_token` match the contract's configuration, and if the `oracle_addr` is valid.

4.  **Offer Utilization**: Offers track `available_liquidity` and `commited_liquidity` (per `tracing_id`). **It is important to note that both `available_liquidity` and `commited_liquidity` strictly track the *principal* amount of the loan, not including any protocol or origination fees.** When an offer is used to create a loan, the loan's principal is deducted from the offer's `available_liquidity` (via `commited_liquidity`), preventing overuse beyond the specified limit.

5.  **Offer Revocation**: Lenders can revoke their offers before they expire or are fully utilized. This is a one-time revocation per offer ID.

As offers are kept off-chain, to prevent abusive usage, several on-chain validations are in place:
*   Each offer has an `expiration` timestamp, after which it cannot be used.
*   Offers can be revoked before expiration by calling `revoke_offer` in `P2PLendingErc20` or `P2PLendingVaultedErc20`.
*   Each offer has `available_liquidity` to define the maximum total principal that can be lent through it.

### Loans

1.  **Loan Creation (`create_loan`)**:
    The process involves verifying the offer's signature and validity, along with KYC validation for both borrower and lender. The principal amount is then transferred from the lender to the borrower, along with adjustments for upfront fees. Upfront fees are distributed, and a loan record is created (`base.Loan` struct). Initial LTV is checked against `max_iltv`.
    **For a loan to be successfully created, the lender must approve/hold funds for the total amount to be transferred from their wallet, which is calculated as `principal + protocol_upfront_fee_amount - origination_fee_amount`. If the lender's wallet does not hold sufficient funds or has not provided adequate allowance to the protocol for this calculated amount, the `create_loan` transaction will revert.**
    *   For the **non-vaulted** version, the ERC20 collateral is transferred directly to the main `P2PLendingErc20` contract.
    *   For the **vaulted** version, the ERC20 collateral is transferred to a dedicated `P2PLendingVault` for the borrower. If a vault doesn't exist for the borrower, it's created via CREATE2.

2.  **Loan Settlement (`settle_loan`)**:
    To settle a loan, the contract calculates the total repayment amount (principal + accrued interest + protocol settlement fee). The borrower transfers this amount to the contract, which then distributes the funds to the lender and the protocol wallet.
    *   For the **non-vaulted** version, the ERC20 collateral is transferred directly back to the borrower from the `P2PLendingErc20` contract.
    *   For the **vaulted** version, the ERC20 collateral is transferred from the borrower's `P2PLendingVault` back to the borrower.

3.  **Defaulted Loan Collateral Claim (`liquidate_loan`)**:
    If a loan defaults (either by reaching `maturity` or failing to repay within `call_window` after a `call_loan`), the lender or any address (liquidator) can trigger a full liquidation via `liquidate_loan` (handled by the `P2PLendingLiquidation` or `P2PLendingVaultedLiquidation` facet). The collateral is transferred to the lender (or liquidator for a fee) without any fund transfers.
    *   For the **non-vaulted** version, collateral is transferred directly from the `P2PLendingErc20` contract.
    *   For the **vaulted** version, collateral is transferred from the borrower's `P2PLendingVault`.
    *   **Important**: A full liquidation can also be triggered on a **non-defaulted loan** if its LTV exceeds the `partial_liquidation_ltv` threshold (meaning partial liquidation is enabled and triggered) AND the loan is so severely undercollateralized that even a partial liquidation (aimed at restoring the `initial_ltv`) would result in the **entire outstanding debt being written off**. In such cases, the system proceeds with a full liquidation.

4.  **Partial Liquidation (`partially_liquidate_loan`)**:
    If the current Loan-to-Value (LTV) ratio of an active loan exceeds the `partial_liquidation_ltv` threshold defined in the offer, any address can trigger a partial liquidation via `partially_liquidate_loan` (handled by the `P2PLendingLiquidation` or `P2PLendingVaultedLiquidation` facet). In this process:
    *   A portion of the outstanding debt is "written off" (reduced).
    *   The goal is to bring the LTV back to the `initial_ltv` ratio, thereby "healing" the loan. This is only possible if the calculated debt write-off amount is *less than* the total outstanding debt. If a partial liquidation would write off the entire debt, the loan would instead be fully liquidated.
    *   The `liquidator` receives an amount of collateral equal to the `collateral_claimed` and the `partial_liquidation_fee` (both in collateral tokens).
    *   If the `liquidator` is not the `lender`, the `liquidator` also transfers the `principal_written_off` amount (in payment tokens) to the `lender`, effectively buying out the written-off portion of the debt. The lender's `commited_liquidity` for the offer is reduced by this `principal_written_off`.
    *   The loan's `accrual_start_time` is reset to the current `block.timestamp`.
    *   For the **non-vaulted** version, collateral is claimed directly from the `P2PLendingErc20` contract.
    *   For the **vaulted** version, collateral is claimed from the borrower's `P2PLendingVault`.

5.  **Call Loan (`call_loan`)**:
    Lenders can initiate a loan call if the `call_eligibility` period has passed and the loan is not yet called or defaulted. This sets a `call_time` timestamp, and the borrower then has `call_window` seconds to repay the loan before it automatically defaults.

6.  **Add Collateral (`add_collateral_to_loan`)**:
    Borrowers can add more ERC20 collateral to an ongoing loan at any time, which reduces the loan's LTV.
    *   For the **non-vaulted** version, collateral is deposited directly to the `P2PLendingErc20` contract.
    *   For the **vaulted** version, collateral is deposited into the borrower's `P2PLendingVault`.

7.  **Remove Collateral (`remove_collateral_from_loan`)**:
    Borrowers can remove collateral from an ongoing loan as long as the remaining collateral is at least `min_collateral_amount` and the LTV does not exceed the `initial_ltv` (to prevent immediately increasing risk beyond the initial agreement).
    *   For the **non-vaulted** version, collateral is withdrawn directly from the `P2PLendingErc20` contract.
    *   For the **vaulted** version, collateral is withdrawn from the borrower's `P2PLendingVault`.

8.  **Loan Replacement by Borrower (`replace_loan`)**:
    A borrower can refinance an existing loan by accepting a new offer (which might be from the same or a different lender). The function, handled by the `P2PLendingRefinance` (non-vaulted) or `P2PLendingVaultedRefinance` (vaulted) facet, effectively settles the old loan and creates a new one using the same collateral. Liquidity adjustments are made for both borrower and lender, and any difference in collateral amount is transferred. KYC for the new lender is required. For the **vaulted** version, collateral remains within the borrower's vault, with only internal adjustments if the amount changes.

9.  **Loan Replacement by Lender (`replace_loan_lender`)**:
    A lender can initiate a replacement of an existing loan, effectively selling it to a new lender or refinancing it themselves. This is handled by the `P2PLendingRefinance` (non-vaulted) or `P2PLendingVaultedRefinance` (vaulted) facet. The borrower's terms are protected, ensuring:
    *   No additional liquidity is required from the borrower.
    *   The borrower's repayment obligations (principal, interest, call eligibility, LTV thresholds) under the new conditions are not worse than the original loan's conditions up until the original loan's maturity.
    *   Any necessary compensation is calculated and handled by the protocol.

10. **Loan Borrower Transfer (`transfer_loan`) (vaulted only)**:
    In the **vaulted** version, the `transfer_loan` function allows a privileged `transfer_agent` to change the borrower of an existing loan. This is designed to support special cases (e.g., death, lost keys, or legal transfers). When a loan is transferred, the collateral is also moved from the old borrower's `P2PLendingVault` to the new borrower's `P2PLendingVault` (creating it if necessary).

### Fees

The protocol supports several types of fees:

*   **Protocol Upfront Fee**: A percentage (in basis points) of the principal, paid to the `protocol_wallet` when the loan is created. Configurable by the owner.
*   **Protocol Settlement Fee**: A percentage (in basis points) of the interest, paid to the `protocol_wallet` during loan settlement. Configurable by the owner.
*   **Origination Fee**: An upfront fee (in basis points of the principal) paid to the lender when a loan is created. It is part of the loan terms defined in the `Offer` structure.
*   **Partial Liquidation Fee**: A percentage (in basis points) of the claimed collateral value, paid to the liquidator during a partial liquidation. Configurable by the owner.
*   **Full Liquidation Fee**: A percentage (in basis points) of the claimed collateral value, paid to the liquidator during a full liquidation. Configurable by the owner.

All upfront fees are paid during loan creation, while settlement fees are paid as a fraction of the interest amount during loan settlement.

### Roles

The protocol defines the following key roles:
*   `Owner`: The privileged address that can update protocol-wide parameters (e.g., protocol fees, partial/full liquidation fees), manage authorized proxies, and propose/claim ownership.
*   `Borrower`: The recipient of the loan, identified by `loan.borrower`. Can settle loans, add/remove collateral, and initiate loan replacements.
*   `Lender`: The provider of the loan, identified by `loan.lender`. Can initiate loan replacements and claim collateral for defaulted loans, and call loans.
*   `Liquidator`: Any address that can trigger a `partially_liquidate_loan` or `liquidate_loan` if the LTV conditions are met. Receives the `partial_liquidation_fee` or `full_liquidation_fee` for performing this action.
*   `KYC Validator`: An external address registered in the `KYCValidator` contract that signs wallet attestations, ensuring compliance.
*   `Transfer Agent`: A privileged address (vaulted only) that can transfer a loan's ownership to a new borrower, primarily for compliance and recovery scenarios.

## Development

### Contract Implementations

The protocol includes two versions, non-vaulted and vaulted. The non-vaulted version (`P2PLendingErc20`) handles collateral directly within the main contract. The vaulted version (`P2PLendingVaultedErc20`) introduces a dedicated vault system (`P2PLendingVault`) for each borrower to manage collateral, enhancing security and compliance.

#### P2PLendingErc20 Contract (Non-Vaulted) (`P2PLendingErc20.vy`)

The `P2PLendingErc20` contract serves as the main entry point for the non-vaulted protocol, handling the core logic for loan origination, management, and settlement using ERC20 tokens as collateral. It inherits common state and functions from `P2PLendingBase`.

##### State variables (specific to `P2PLendingErc20`)

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `payment_token` | `immutable(address)` | No | Address of the payment ERC20 token contract |
| `collateral_token` | `immutable(address)` | No | Address of the collateral ERC20 token contract |
| `oracle_addr` | `immutable(address)` | No | Address of the Chainlink AggregatorV3 oracle contract for collateral valuation |
| `oracle_reverse` | `immutable(bool)` | No | Flag indicating if the oracle returns 1/price |
| `kyc_validator_addr` | `immutable(address)` | No | Address of the `KYCValidator` contract |
| `max_protocol_upfront_fee` | `immutable(uint256)` | No | Maximum allowed upfront protocol fee (in BPS) |
| `max_protocol_settlement_fee` | `immutable(uint256)` | No | Maximum allowed settlement protocol fee (in BPS) |
| `payment_token_decimals` | `immutable(uint256)` | No | Decimal precision of the payment token |
| `collateral_token_decimals` | `immutable(uint256)` | No | Decimal precision of the collateral token |
| `offer_sig_domain_separator` | `immutable(bytes32)` | No | EIP-712 domain separator for offer signatures |
| `refinance_addr` | `public(immutable(address))` | No | Address of the `P2PLendingRefinance` facet contract |
| `liquidation_addr` | `public(immutable(address))` | No | Address of the `P2PLendingLiquidation` facet contract |

##### State variables (inherited from `P2PLendingBase`)

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `owner` | `public(address)` | Yes | Address of the contract owner |
| `proposed_owner` | `public(address)` | Yes | Address of the proposed new owner |
| `transfer_agent` | `public(address)` | Yes | Address of the transfer agent |
| `loans` | `public(HashMap[bytes32, bytes32])` | Yes | Mapping of loan IDs to loan state hashes |
| `protocol_wallet` | `public(address)` | Yes | Address where protocol fees are accrued |
| `protocol_upfront_fee` | `public(uint256)` | Yes | Current upfront fee for the protocol (in BPS) |
| `partial_liquidation_fee` | `public(uint256)` | Yes | Fee charged during partial liquidation (in BPS of collateral claimed) |
| `full_liquidation_fee` | `public(uint256)` | Yes | Fee charged during full liquidation (in BPS of collateral claimed) |
| `protocol_settlement_fee` | `public(uint256)` | Yes | Current settlement fee for the protocol (in BPS of interest) |
| `commited_liquidity` | `public(HashMap[bytes32, uint256])` | Yes | Mapping of offer `tracing_id` to committed principal |
| `revoked_offers` | `public(HashMap[bytes32, bool])` | Yes | Mapping of offer IDs to their revocation status |
| `authorized_proxies` | `public(HashMap[address, bool])` | Yes | Mapping of authorized proxy addresses |
| `pending_transfers` | `public(HashMap[address, uint256])` | Yes | Funds that failed ERC20 `transfer` and can be claimed later |
| `pending_collateral` | `public(HashMap[address, uint256])` | Yes | Collateral that failed ERC20 `transfer` and can be claimed later |

##### Externalized State

To reduce gas costs, certain state information, particularly for `Loan` and `Offer` structures, is externalized rather than stored fully on-chain:

*   **For Loans**: The `loans` mapping stores `keccak256` hashes of `base.Loan` structs instead of the full data. When interacting with a loan (e.g., in `settle_loan`), the full `base.Loan` struct is passed as an argument, and its hash is validated against the stored hash. State changes are reflected by updating the stored hash and emitting events.
*   **For Offers**: Full `base.Offer` data is not stored on-chain. Instead, `commited_liquidity` tracks usage per `tracing_id`, and `revoked_offers` tracks revocation status per `offer_id`. When creating a loan, the full `base.SignedOffer` data is passed, and its validity is checked using these mappings and its signature.

##### Structs (defined in `P2PLendingBase.vy` or `P2PLendingVaultedBase.vy`)

| **Struct** | **Variable** | **Type** | **Description** |
| --- | --- | --- | --- |
| `WalletValidation` | `wallet` | `address` | Wallet address being validated |
| | `expiration_time` | `uint256` | Timestamp until which the validation is valid |
| `Signature` | `v` | `uint256` | EIP-712 signature component |
| | `r` | `uint256` | EIP-712 signature component |
| | `s` | `uint256` | EIP-712 signature component |
| `SignedWalletValidation` | `validation` | `WalletValidation` | Signed attestation of a wallet's KYC status |
| | `signature` | `Signature` | Signature of the validation |
| `Offer` | `principal` | `uint256` | Loan principal amount (0 for borrower-defined) |
| | `apr` | `uint256` | Annual Percentage Rate (in BPS) |
| | `payment_token` | `address` | Address of the payment token |
| | `collateral_token` | `address` | Address of the collateral token |
| | `duration` | `uint256` | Loan duration in seconds |
| | `origination_fee_bps` | `uint256` | Origination fee percentage (in BPS) for the lender |
| | `min_collateral_amount` | `uint256` | Minimum collateral amount required |
| | `max_iltv` | `uint256` | Maximum initial LTV allowed (in BPS) |
| | `available_liquidity` | `uint256` | Total principal amount available for this offer |
| | `call_eligibility` | `uint256` | Time in seconds after loan start when the loan becomes callable (0 if not callable) |
| | `call_window` | `uint256` | Time in seconds after a loan is called for repayment before default |
| | `liquidation_ltv` | `uint256` | LTV threshold (in BPS) for partial liquidation |
| | `oracle_addr` | `address` | Address of the oracle for collateral valuation |
| | `expiration` | `uint256` | Offer expiration timestamp |
| | `lender` | `address` | Lender's address |
| | `borrower` | `address` | Specific borrower for the offer (0x0 for general offers) |
| | `tracing_id` | `bytes32` | Unique identifier for tracking offer usage |
| `SignedOffer` | `offer` | `Offer` | The offer details |
| | `signature` | `Signature` | EIP-712 signature of the offer |
| `Loan` | `id` | `bytes32` | Unique identifier of the loan |
| | `offer_id` | `bytes32` | ID of the offer that created the loan |
| | `offer_tracing_id` | `bytes32` | Tracing ID from the offer |
| | `initial_amount` | `uint256` | Initial principal amount of the loan |
| | `amount` | `uint256` | Current outstanding principal amount |
| | `apr` | `uint256` | Annual Percentage Rate (in BPS) |
| | `payment_token` | `address` | Address of the payment token |
| | `maturity` | `uint256` | Maturity timestamp of the loan |
| | `start_time` | `uint256` | Start timestamp of the loan |
| | `accrual_start_time` | `uint256` | Timestamp from which interest accrual is calculated (reset after partial liquidation) |
| | `borrower` | `address` | Borrower's address |
| | `lender` | `address` | Lender's address |
| | `collateral_token` | `address` | Address of the collateral token |
| | `collateral_amount` | `uint256` | Current amount of collateral tokens held by the contract |
| | `min_collateral_amount` | `uint256` | Minimum collateral amount required |
| | `origination_fee_amount` | `uint256` | Total origination fee for the lender |
| | `protocol_upfront_fee_amount` | `uint256` | Upfront protocol fee amount |
| | `protocol_settlement_fee` | `uint256` | Protocol settlement fee percentage (in BPS) |
| | `partial_liquidation_fee` | `uint256` | Partial liquidation fee percentage (in BPS) |
| | `full_liquidation_fee` | `uint256` | Full liquidation fee percentage (in BPS) |
| | `call_eligibility` | `uint256` | Time in seconds after loan start when the loan becomes callable |
| | `call_window` | `uint256` | Time in seconds after a loan is called for repayment before default |
| | `liquidation_ltv` | `uint256` | LTV threshold (in BPS) for partial liquidation |
| | `oracle_addr` | `address` | Address of the oracle for collateral valuation |
| | `initial_ltv` | `uint256` | Initial LTV of the loan (in BPS). This is the target LTV for partial liquidations. |
| | `call_time` | `uint256` | Timestamp when the loan was called (0 if not called) |
| `vault_id` | `uint256` | (Securitize only) Vault identifier for this loan |
| `redeem_start` | `uint256` | (Securitize only) Timestamp when redemption started (0 if not redeemed) |
| `redeem_residual_collateral` | `uint256` | (Securitize only) Collateral amount kept in vault during redemption |
| `UInt256Rational` | `numerator` | `uint256` | Numerator of a rational number |
| | `denominator` | `uint256` | Denominator of a rational number |
| `PartialLiquidationResult` | `collateral_claimed` | `uint256` | Amount of collateral claimed in a partial liquidation simulation |
| | `liquidation_fee` | `uint256` | Liquidation fee in a partial liquidation simulation |
| | `debt_written_off` | `uint256` | Amount of debt written off in a partial liquidation simulation |
| | `updated_ltv` | `uint256` | Calculated LTV after a partial liquidation simulation |

##### Relevant External Functions (`P2PLendingErc20.vy`)

| **Function** | **Roles Allowed** | **Modifier** | **Description** |
| --- | :-: | --- | --- |
| `create_loan` | Any (caller is borrower) | Nonpayable | Creates a new loan based on a signed offer and ERC20 collateral |
| `settle_loan` | Borrower | Payable | Settles an existing loan |
| `partially_liquidate_loan` | Any (Liquidator) | Nonpayable | Performs a partial liquidation on a loan if LTV conditions are met |
| `liquidate_loan` | Any (Liquidator) | Nonpayable | Performs a full liquidation on a defaulted loan |
| `call_loan` | Lender | Nonpayable | Calls an eligible loan, starting the repayment window |
| `add_collateral_to_loan` | Borrower | Nonpayable | Adds ERC20 collateral to an existing loan |
| `remove_collateral_from_loan` | Borrower | Nonpayable | Removes ERC20 collateral from an existing loan, subject to LTV checks |
| `revoke_offer` | Lender | Nonpayable | Revokes a signed offer |
| `claim_pending_transfers` | Any (receiver) | Nonpayable | Claims any ERC20 tokens that failed a direct `transfer` call (payment token) |
| `claim_pending_collateral` | Any (receiver) | Nonpayable | Claims any ERC20 tokens that failed a direct `transfer` call (collateral token) |
| `replace_loan` | Borrower | Payable | Replaces an existing loan with a new one (borrower-initiated refinance) |
| `replace_loan_lender` | Lender | Payable | Replaces a loan by the lender (lender-initiated refinance) |
| `set_partial_liquidation_fee` | Owner | Nonpayable | Sets the partial liquidation fee |
| `set_full_liquidation_fee` | Owner | Nonpayable | Sets the full liquidation fee |
| `set_protocol_fee` | Owner | Nonpayable | Sets the protocol upfront and settlement fees |
| `change_protocol_wallet` | Owner | Nonpayable | Changes the protocol wallet address |
| `set_proxy_authorization` | Owner | Nonpayable | Sets authorization for a proxy address |
| `propose_owner` | Owner | Nonpayable | Proposes a new owner for the contract |
| `claim_ownership` | Proposed Owner | Nonpayable | Claims ownership of the contract |
| `set_transfer_agent` | Owner/Transfer Agent | Nonpayable | Sets the transfer agent address |
| `current_ltv` | Any | View | Gets the current LTV of a loan |
| `is_loan_defaulted` | Any | View | Checks if a loan is defaulted |
| `simulate_partial_liquidation` | Any | View | Simulates the outcome of a partial liquidation |

#### P2PLendingVaultedErc20 Contract (Vaulted) (`P2PLendingVaultedErc20.vy`)

The `P2PLendingVaultedErc20` contract serves as the main entry point for the vaulted protocol. It extends the core logic of the non-vaulted version by integrating a dedicated vault system for collateral management. It inherits common state and functions from `P2PLendingVaultedBase` and includes a new `_vault_impl_addr` parameter in its constructor. Collateral interactions are now handled through calls to the borrower's `P2PLendingVault`.

##### State variables (specific to `P2PLendingVaultedErc20`)

(Adds `vault_impl_addr`, otherwise similar to non-vaulted `P2PLendingErc20.vy`)

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `payment_token` | `immutable(address)` | No | Address of the payment ERC20 token contract |
| `collateral_token` | `immutable(address)` | No | Address of the collateral ERC20 token contract |
| `oracle_addr` | `immutable(address)` | No | Address of the Chainlink AggregatorV3 oracle contract for collateral valuation |
| `oracle_reverse` | `immutable(bool)` | No | Flag indicating if the oracle returns 1/price |
| `kyc_validator_addr` | `immutable(address)` | No | Address of the `KYCValidator` contract |
| `max_protocol_upfront_fee` | `immutable(uint256)` | No | Maximum allowed upfront protocol fee (in BPS) |
| `max_protocol_settlement_fee` | `immutable(uint256)` | No | Maximum allowed settlement protocol fee (in BPS) |
| `payment_token_decimals` | `immutable(uint256)` | No | Decimal precision of the payment token |
| `collateral_token_decimals` | `immutable(uint256)` | No | Decimal precision of the collateral token |
| `offer_sig_domain_separator` | `immutable(bytes32)` | No | EIP-712 domain separator for offer signatures |
| `refinance_addr` | `public(immutable(address))` | No | Address of the `P2PLendingVaultedRefinance` facet contract |
| `liquidation_addr` | `public(immutable(address))` | No | Address of the `P2PLendingVaultedLiquidation` facet contract |
| `vault_impl_addr` | `public(immutable(address))` | No | Address of the `P2PLendingVault` implementation contract |

##### State variables (inherited from `P2PLendingVaultedBase`)

(Similar to non-vaulted `P2PLendingBase`, but its internal collateral functions (`_send_collateral`, `_receive_collateral`) now interact with vaults. Adds `vault_registrar` state variable for automatic vault registration with the Securitize Vault Registrar during vault creation.)

##### Relevant External Functions (`P2PLendingVaultedErc20.vy`)

(Similar to non-vaulted `P2PLendingErc20.vy`, with additional `transfer_loan` and `wallet_to_vault` functions, and all collateral interactions updated to use vaults.)

| **Function** | **Roles Allowed** | **Modifier** | **Description** |
| --- | :-: | --- | --- |
| `create_loan` | Any (caller is borrower) | Nonpayable | Creates a new loan (collateral deposited to borrower's vault) |
| `settle_loan` | Borrower | Payable | Settles an existing loan (collateral withdrawn from vault) |
| `partially_liquidate_loan` | Any (Liquidator) | Nonpayable | Performs a partial liquidation on a loan (collateral claimed from vault) |
| `liquidate_loan` | Any (Liquidator) | Nonpayable | Performs a full liquidation on a defaulted loan (collateral claimed from vault) |
| `call_loan` | Lender | Nonpayable | Calls an eligible loan, starting the repayment window |
| `add_collateral_to_loan` | Borrower | Nonpayable | Adds ERC20 collateral to an existing loan (deposited to vault) |
| `remove_collateral_from_loan` | Borrower | Nonpayable | Removes ERC20 collateral from an existing loan (withdrawn from vault) |
| `revoke_offer` | Lender | Nonpayable | Revokes a signed offer |
| `claim_pending_transfers` | Any (receiver) | Nonpayable | Claims any ERC20 tokens that failed a direct `transfer` call (payment token) |
| `replace_loan` | Borrower | Payable | Replaces an existing loan with a new one (borrower-initiated refinance) |
| `replace_loan_lender` | Lender | Payable | Replaces a loan by the lender (lender-initiated refinance) |
| `transfer_loan` | Transfer Agent | Nonpayable | Transfers a loan's ownership and its collateral to a new borrower (vaulted only) |
| `set_partial_liquidation_fee` | Owner | Nonpayable | Sets the partial liquidation fee |
| `set_full_liquidation_fee` | Owner | Nonpayable | Sets the full liquidation fee |
| `set_protocol_fee` | Owner | Nonpayable | Sets the protocol upfront and settlement fees |
| `change_protocol_wallet` | Owner | Nonpayable | Changes the protocol wallet address |
| `set_proxy_authorization` | Owner | Nonpayable | Sets authorization for a proxy address |
| `propose_owner` | Owner | Nonpayable | Proposes a new owner for the contract |
| `claim_ownership` | Proposed Owner | Nonpayable | Claims ownership of the contract |
| `set_transfer_agent` | Owner/Transfer Agent | Nonpayable | Sets the transfer agent address |
| `change_vault_registrar` | Owner | Nonpayable | Changes the vault registrar connector address |
| `current_ltv` | Any | View | Gets the current LTV of a loan |
| `is_loan_defaulted` | Any | View | Checks if a loan is defaulted |
| `simulate_partial_liquidation` | Any | View | Simulates the outcome of a partial liquidation |
| `wallet_to_vault` | Any | View | Gets the deterministic vault address for a given wallet |

#### P2PLendingSecuritizeErc20 Contract (Securitize) (`P2PLendingSecuritizeErc20.vy`)

The `P2PLendingSecuritizeErc20` contract extends the vaulted architecture for Securitize DS Token collateral, adding redemption workflow and maturity extension support.

##### State variables (specific to `P2PLendingSecuritizeErc20`)

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `payment_token` | `immutable(address)` | No | Address of the payment ERC20 token contract |
| `collateral_token` | `immutable(address)` | No | Address of the Securitize DS Token contract |
| `oracle_addr` | `immutable(address)` | No | Address of the Chainlink AggregatorV3 oracle contract |
| `oracle_reverse` | `immutable(bool)` | No | Flag indicating if the oracle returns 1/price |
| `kyc_validator_addr` | `immutable(address)` | No | Address of the `KYCValidator` contract |
| `refinance_addr` | `public(immutable(address))` | No | Address of the `P2PLendingSecuritizeRefinance` facet |
| `liquidation_addr` | `public(immutable(address))` | No | Address of the `P2PLendingSecuritizeLiquidation` facet |
| `vault_impl_addr` | `public(immutable(address))` | No | Address of the `P2PLendingVaultSecuritize` implementation |

##### State variables (inherited from `P2PLendingSecuritizeBase`)

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `vault_count` | `public(HashMap[address, uint256])` | Yes | Number of vaults created per borrower |
| `securitize_redemption_wallet` | `public(address)` | Yes | Wallet address for Securitize redemptions |
| `vault_registrar` | `public(address)` | Yes | Address of the vault registrar connector |

##### Relevant External Functions (`P2PLendingSecuritizeErc20.vy`)

| **Function** | **Roles Allowed** | **Modifier** | **Description** |
| --- | :-: | --- | --- |
| `create_loan` | Any (caller is borrower) | Nonpayable | Creates a new loan with a new vault for the collateral |
| `settle_loan` | Borrower | Nonpayable | Settles a loan (handles redeemed collateral if applicable) |
| `partially_liquidate_loan` | Any (Liquidator) | Nonpayable | Performs a partial liquidation (not allowed on redeemed loans) |
| `liquidate_loan` | Any (Liquidator) | Nonpayable | Performs a full liquidation (handles redeemed collateral) |
| `add_collateral_to_loan` | Borrower | Nonpayable | Adds collateral (not allowed after redemption starts) |
| `remove_collateral_from_loan` | Borrower | Nonpayable | Removes collateral (not allowed after redemption starts) |
| `redeem` | Borrower | Nonpayable | Initiates redemption of collateral via Securitize |
| `extend_loan` | Borrower | Nonpayable | Extends loan maturity with lender's signed offer |
| `extend_loan_lender` | Lender | Nonpayable | Extends loan maturity (lender-initiated) |
| `replace_loan` | Borrower | Nonpayable | Replaces a loan (not allowed on redeemed loans) |
| `replace_loan_lender` | Lender | Nonpayable | Replaces a loan as lender (not allowed on redeemed loans) |
| `set_securitize_redemption_wallet` | Owner | Nonpayable | Sets the redemption wallet address |
| `change_vault_registrar` | Owner | Nonpayable | Changes the vault registrar connector address |
| `wallet_to_vault` | Any | View | Gets the latest vault address for a wallet |
| `vault_id_to_vault` | Any | View | Gets a specific vault address by ID |
| `is_loan_redeemed` | Any | View | Checks if a loan has started redemption |

#### P2PLendingBase (Non-Vaulted) / P2PLendingVaultedBase (Vaulted) Contracts

`P2PLendingBase.vy` provides common state and logic for the non-vaulted version. `P2PLendingVaultedBase.vy` extends this by modifying the internal collateral handling functions (`_send_collateral`, `_receive_collateral`) to interact with the new `P2PLendingVault` system. It also introduces functions like `_get_vault`, `_create_vault_if_needed`, and `_wallet_to_vault` to manage the lifecycle and address computation for borrower-specific vaults.

#### P2PLendingRefinance (Non-Vaulted) / P2PLendingVaultedRefinance (Vaulted) Contracts

These contracts act as facets for refinancing logic. `P2PLendingRefinance.vy` (non-vaulted) operates on the main `P2PLendingErc20`'s storage, handling collateral directly. `P2PLendingVaultedRefinance.vy` (vaulted) takes `vault_impl_addr` as an additional parameter in its delegatecall context and internally uses the `P2PLendingVaultedBase`'s vault-aware collateral functions.

#### P2PLendingLiquidation (Non-Vaulted) / P2PLendingVaultedLiquidation (Vaulted) Contracts

These contracts act as facets for liquidation logic. `P2PLendingLiquidation.vy` (non-vaulted) operates on the main `P2PLendingErc20`'s storage, handling collateral directly. `P2PLendingVaultedLiquidation.vy` (vaulted) takes `vault_impl_addr` as an additional parameter in its delegatecall context and internally uses the `P2PLendingVaultedBase`'s vault-aware collateral functions.

#### P2PLendingVault Contract (`P2PLendingVault.vy`)

This contract implements the logic for individual collateral vaults in the vaulted version. It is designed to be deployed as a minimal proxy via CREATE2 for each borrower, ensuring isolated collateral management.

##### State variables

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `owner` | `public(address)` | Yes | The wallet address of the borrower owning this vault |
| `caller` | `public(address)` | Yes | The address of the `P2PLendingVaultedErc20` contract (or other authorized caller) |
| `token` | `public(address)` | Yes | The address of the ERC20 collateral token this vault holds |
| `pending_transfers` | `public(HashMap[address, uint256])` | Yes | Map for pending withdrawals if a transfer failed (for `withdraw_pending`) |
| `pending_transfers_total` | `public(uint256)` | Yes | Total pending withdrawals in the vault |

##### Relevant External Functions (`P2PLendingVault.vy`)

| **Function** | **Roles Allowed** | **Modifier** | **Description** |
| --- | :-: | --- | --- |
| `initialise` | Deployer (once) | Nonpayable | Initializes the vault with an owner and token (called by `P2PLendingVaultedErc20` upon creation) |
| `deposit` | Caller (e.g., `P2PLendingVaultedErc20`) | Nonpayable | Deposits tokens into the vault (transfers from borrower) |
| `withdraw` | Caller (e.g., `P2PLendingVaultedErc20`) | Nonpayable | Withdraws tokens from the vault (transfers to recipient) |
| `withdraw_pending` | Any (sender) | Nonpayable | Allows a recipient to claim tokens if a previous `withdraw` failed |

#### KYCValidator Contract (`KYCValidator.vy`)

The `KYCValidator` contract is an external dependency that ensures regulatory compliance by verifying KYC attestations. It holds a trusted `validator` address that is authorized to sign `WalletValidation` messages.

##### State variables

| **Variable** | **Type** | **Mutable** | **Description** |
| --- | --- | :-: | --- |
| `owner` | `public(address)` | Yes | Address of the contract owner |
| `proposed_owner` | `public(address)` | Yes | Address of the proposed new owner |
| `validator` | `public(address)` | Yes | Address of the trusted KYC validator |
| `validation_sig_domain_separator` | `immutable(bytes32)` | No | EIP-712 domain separator for validation signatures |

##### Relevant External Functions (`KYCValidator.vy`)

| **Function** | **Roles Allowed** | **Modifier** | **Description** |
| --- | :-: | --- | --- |
| `check_validation` | Any | View | Checks if a single `SignedWalletValidation` is valid (signed by `validator` and not expired). |
| `check_validations_pair` | Any | View | Checks if two `SignedWalletValidation` structs are both valid. |
| `propose_owner` | Owner | Nonpayable | Proposes a new owner for the contract. |
| `claim_ownership` | Proposed Owner | Nonpayable | Claims ownership of the contract. |
| `set_validator` | Owner | Nonpayable | Sets the address of the trusted KYC validator. |

##### Proxy Support

The `P2PLendingErc20` (non-vaulted) and `P2PLendingVaultedErc20` (vaulted) contracts include support for authorized proxies, allowing for more flexible interaction with the protocol. This feature is particularly useful for integrations with other protocols or for implementing advanced user interfaces.

Key aspects of proxy support include:
1.  **Authorized Proxies**: The contract maintains a mapping of `authorized_proxies: public(HashMap[address, bool])`. The contract owner can set or revoke proxy authorization using `set_proxy_authorization`.
2.  **User Checks**: An internal function `_check_user` verifies if the `msg.sender` is the expected user or an `authorized_proxies[msg.sender]` acting on behalf of `tx.origin`. This is used for user-specific actions (e.g., settling loans, revoking offers).
3.  **Proxy Usage**: When an authorized proxy calls a function, `tx.origin` is used to identify the actual user, allowing proxies to perform actions on behalf of users while maintaining access control.
4.  **Security Considerations**: Only the contract owner can authorize or deauthorize proxies. `tx.origin` is only considered when the `msg.sender` is an authorized proxy; otherwise, `msg.sender` is used for authentication.

### Testing

Both non-vaulted and vaulted versions of the protocol have comprehensive test suites. There are two types of tests implemented, running on py-evm using titanoboa:
1.  Unit tests focus on individual functions for each contract, mocking external dependencies (e.g., ERC20 tokens, oracle, KYC validator, and `P2PLendingVault` for the vaulted version).
2.  Integration tests run on a forked chain, testing the integration between the contracts in the protocol and real implementations of the external dependencies

For deployments in private and test networks, mock implementations of external dependencies are used. These mocks are **NOT part of the core protocol** but facilitate local development and testing. Key mock contracts include:
*   `MockERC20.vy`: For payment and collateral ERC20 tokens.
*   `MockAggregatorV3.vy`: For the Chainlink Price Feed oracle.
*   `MockKYCValidator.vy`: For the KYC validation contract.
*   `MockVault.vy`: For the `P2PLendingVault` in vaulted version testing.
*   `VaultRegistrarMock.vy`: A mock implementation of the Securitize Vault Registrar interface. Provides `registerVault` and `isRegistered` functions.

### Run the project

Run the following command to set everything up:
```
make install-dev
```

To run the tests (ensure `make install-dev` is run first):
*   **Unit tests**:
    *   **Important note**: when running the unit tests for the first time, **run the command twice**! The first time might encounter errors due to uninitialized titanoboa cache.
```
make unit-tests
```
```
make coverage
```
```
make branch-coverage
```
```
make gas
```

### Deployment

#### Deploy the protocol to a local environment

In order to run the protocol locally:
1.  Install [Foundry](https://book.getfoundry.sh/getting-started/installation)
2.  In a terminal, run `make install-dev`
3.  In another terminal, run `anvil`
4.  In the line 39 of `scripts/deployment.py`, ensure the statement for deployment is `dm.deploy(changes, dryrun=False)`. (Set `dryrun=True` to simulate deployment without actual transactions).
5.  In the first terminal, run `make deploy-local`. This will deploy the latest version of the protocol (vaulted by default).
6.  To interact with the deployed contracts manually, run `make console-local` and use the console.

After step 5, the config file `configs/local/p2p.json` will be populated with all deployed contract addresses and other relevant information. To redeploy, you can copy the contents of `configs/local/p2p.json.template` to `configs/local/p2p.json` and run `make deploy-local` again.

#### Deploy the protocol to existing networks

For each environment (e.g., DEV, INT, PROD), a Makefile rule is available to deploy the contracts. For example, for the DEV environment:
```
make deploy-dev
```

The protocol relies on external contracts (ERC20 tokens, oracle, KYC validator). Mock implementations are used in development environments.

| **Component** | **DEV** | **INT** | **PROD** |
| -------------------- | ----------------------------- | ---------------------------------------- | ------------------------------------------------------------------------- |
| **Network** | Private network (Anvil) | Sepolia | Mainnet |
| **Payment Token** | MockERC20 | MockERC20 | USDC (`0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`) |
| **Collateral Token** | MockERC20 | MockERC20 | WETH (`0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2`) or other ERC20 |
| **Oracle Contract** | MockAggregatorV3 | Chainlink AggregatorV3 (e.g., `ETH/USD`) | Chainlink AggregatorV3 (e.g., `ETH/USD`) |
| **KYC Validator** | MockKYCValidator | KYCValidator instance | KYCValidator instance |

The `P2PLendingErc20` (non-vaulted) / `P2PLendingVaultedErc20` (vaulted), their respective Base contracts, Refinance, and Liquidation facets are deployed in each environment. The main entry point `P2PLendingErc20` or `P2PLendingVaultedErc20` is deployed with the following parameters:

| **Parameter** | **Type** | **Description** |
| --- | --- | --- |
| `_payment_token` | `address` | Address of the payment ERC20 token contract. |
| `_collateral_token` | `address` | Address of the collateral ERC20 token contract. |
| `_oracle_addr` | `address` | Address of the oracle contract for collateral valuation. |
| `_oracle_reverse` | `bool` | Whether the oracle returns the collateral price in reverse (i.e., 1 / price). |
| `_kyc_validator_addr` | `address` | Address of the `KYCValidator` contract. |
| `_protocol_upfront_fee` | `uint256` | The percentage (bps) of the principal paid to the protocol at origination. |
| `_protocol_settlement_fee` | `uint256` | The percentage (bps) of the interest paid to the protocol at settlement. |
| `_protocol_wallet` | `address` | Address where the protocol fees are accrued. |
| `_max_protocol_upfront_fee` | `uint256` | The maximum percentage (bps) that can be charged as protocol upfront fee. |
| `_max_protocol_settlement_fee` | `uint256` | The maximum percentage (bps) that can be charged as protocol settlement fee. |
| `_partial_liquidation_fee` | `uint256` | The percentage (bps) charged as a liquidation fee during partial liquidation. |
| `_full_liquidation_fee` | `uint256` | The percentage (bps) charged as a liquidation fee during full liquidation. |
| `_refinance_addr` | `address` | The address of the `P2PLendingRefinance` / `P2PLendingVaultedRefinance` facet contract. |
| `_liquidation_addr` | `address` | The address of the `P2PLendingLiquidation` / `P2PLendingVaultedLiquidation` facet contract. |
| `_vault_impl_addr` | `address` | The address of the `P2PLendingVault` implementation contract (for vaulted only). |
| `_transfer_agent` | `address` | The wallet address for the transfer agent role (for vaulted only). |

## Key Features

### Dynamic Collateral Management

The protocol allows borrowers to actively manage their collateral positions:

-   **Add Collateral**: Borrowers can add more collateral tokens to reduce their LTV ratio and improve loan health.
-   **Remove Collateral**: Borrowers can remove excess collateral as long as the remaining collateral maintains the minimum required amount and doesn't exceed the initial LTV threshold.

### Partial Liquidation System

Unlike traditional hard liquidations, the protocol implements a partial liquidation mechanism:

-   **Trigger**: When LTV exceeds the `partial_liquidation_ltv` threshold.
-   **Process**: A portion of debt is written off and corresponding collateral is claimed.
-   **Goal**: Bring the LTV back to the initial level, effectively "healing" the loan.
-   **Incentive**: Liquidators receive a fee for performing this service.

### Loan Call Feature

Lenders have the ability to "call" loans under specific conditions:

-   **Eligibility**: Only after the `call_eligibility` period has passed.
-   **Window**: Borrowers get a `call_window` period to repay before default.
-   **Protection**: Prevents lenders from arbitrarily calling loans early.

### Refinancing Capabilities

Both borrowers and lenders can initiate loan refinancing:

-   **Borrower-Initiated**: Accept better offers from other lenders.
-   **Lender-Initiated**: Sell loan positions or refinance terms.
-   **Borrower Protection**: Ensures new terms are not worse than original terms.

### KYC Integration

All participants must pass KYC validation:

-   **Signed Attestations**: Off-chain KYC validation with on-chain verification.
-   **Expiration**: Validations have time limits for security.
-   **Compliance**: Ensures regulatory requirements are met.

### Vault Collateral System (vaulted only)

-   Introduces isolated vaults for each borrower's collateral, enhancing security and meeting compliance requirements by separating collateral from the main lending contract.
-   Vaults are deployed as minimal proxies via CREATE2, ensuring gas efficiency and deterministic addresses.

### Securitize DS Token Support (securitize only)

-   **Multiple Vaults per Borrower**: Each loan creates a new vault, enabling per-loan collateral isolation.
-   **Redemption Workflow**: Borrowers can redeem DS Token collateral back to payment tokens via Securitize.
-   **Maturity Extensions**: Loans can be extended without full refinancing, either by borrower (with lender's signed offer) or by lender directly.
-   **SecuritizeSwap Integration**: Vaults can purchase DS tokens from stablecoins directly.

## Security Considerations

### Oracle Security

-   Uses Chainlink AggregatorV3 for reliable price feeds.
-   Supports reverse oracle pricing for different token pairs.
-   Regular price updates ensure accurate LTV calculations.

### Access Control

-   Owner-controlled protocol parameter updates.
-   Proxy authorization for integration flexibility.
-   Role-based access for loan operations.
-   The Transfer Agent role (vaulted only) provides a mechanism for compliance-driven loan transfers.

### Economic Security

-   Maximum fee limits prevent excessive protocol fees.
-   LTV thresholds protect against under-collateralization.
-   Partial liquidation prevents complete loan defaults.

### Vault Security (vaulted)

-   Collateral is held in individual vaults, reducing single points of failure and simplifying compliance audits.
-   Vaults are minimal proxies, reducing attack surface and deployment costs.
-   Strict access control ensures only the main lending contract can manage collateral in a vault.

## Integration Guide

### For Borrowers

1.  Obtain KYC validation from approved validator.
2.  Browse available loan offers.
3.  Accept suitable offer with collateral transfer.
    *   For the **non-vaulted** version, transfer collateral directly to the main lending contract.
    *   For the **vaulted** version, deposit collateral into your dedicated vault.
4.  Manage collateral position during loan term.
    *   For the **non-vaulted** version, interact directly with the main lending contract.
    *   For the **vaulted** version, all collateral operations go through your vault via the main lending contract.
5.  Repay loan or refinance as needed.

### For Lenders

1.  Obtain KYC validation from approved validator.
2.  Create signed loan offers with desired terms.
3.  Monitor loan positions and LTV ratios.
4.  Call loans or initiate refinancing when appropriate.
5.  Claim collateral in case of defaults.

### For Developers

The protocol supports integration through:
-   Direct contract interactions with `P2PLendingErc20` (non-vaulted) or `P2PLendingVaultedErc20` (vaulted).
-   Authorized proxy contracts.
-   Event monitoring for loan state changes.
-   View functions for loan analytics.
-   For the vaulted version, direct interaction with individual `P2PLendingVault` contracts is generally not required for borrowers, as the main lending contract manages vault operations. However, developers integrating deeply might need to understand the vault creation and management patterns.

## Key Innovations

1.  **Partial Liquidation**: Protects against market volatility without full liquidation.
2.  **Callable Loans**: Provides flexibility for lenders while protecting borrowers.
3.  **Dynamic Collateral Management**: Allows borrowers to adjust collateral levels.
4.  **KYC Integration**: Ensures regulatory compliance through signed validations.
5.  **Gas Optimization**: Externalized state design reduces transaction costs.
6.  **Refinancing Support**: Both borrowers and lenders can replace existing loans.
7.  **Vault Collateral System (vaulted)**: Individualized, minimal proxy vaults for each borrower's collateral, improving security, compliance, and asset segregation.
8.  **Securitize Integration (securitize)**: Native support for security tokens with redemption workflow, maturity extensions, and SecuritizeSwap integration for DS token purchases.

The protocol represents a significant advancement in DeFi lending by providing sophisticated risk management tools while maintaining user-friendly operations.

## Future Enhancements

Potential future developments include:
-   Support for multiple collateral types.
-   Cross-chain functionality.
-   Advanced risk management features.
-   Governance mechanisms for protocol upgrades.
-   Insurance integration options.

## Support

For technical support, integration questions, or security concerns, please refer to the official documentation or contact the development team through official channels.

---

*Note: This protocol is under active development. Always verify contract addresses and conduct thorough testing before production use.*
```
