# Known issues

These issues were reported to Zharta and are closed. They are not eligible for
a bug bounty reward, and neither is any issue with the same root cause.
Findings in the audit reports in [`audits/`](audits/) are known as well.

| ID | Component | Issue | Resolution | Reported |
|---|---|---|---|---|
| KI-01 | Refinance, `replace_loan_lender` (Vaulted, Securitize) | In a lender-initiated replacement, the borrower is compensated with the greater of the new loan's origination fee and the projected extra interest to the original maturity, not their sum. | By design. | 13 Oct 2026 |
| KI-02 | Securitize partial liquidation | The partial-liquidation formula would underflow if `(BPS + partial_liquidation_fee) * initial_ltv >= BPS * BPS`. | Not a vulnerability. Every loan-creation path rejects such loans, and both values are fixed per loan. | 13 Oct 2026 |
| KI-03 | `P2PLendingSecuritizeLiquidation.transfer_loan` | Transferring a loan with a redemption in progress keeps the redemption state, so the original redemption attestation no longer matches the new vault. | Acknowledged, won't fix. Requires the transfer-agent role; a new attestation for the new vault concludes the redemption, and no funds are at risk. | 13 Oct 2026 |
| KI-04 | `P2PLendingSecuritizeErc20.redeem` | A borrower can redeem with the full collateral as residual, so nothing is sent out. Liquidation and settlement then stay blocked until the redemption is concluded by attestation. | Acknowledged, won't fix. The block is temporary; the attestation signer concludes the redemption. | 13 Oct 2026 |
| KI-05 | MultiVault variant (`P2PLendingMultiVault*`) | Lacks the signature-handling changes applied to the Vaulted and Securitize variants: zero-lender check, standard `isValidSignature`, and signer check order. | Known. MultiVault is not deployed and is out of scope. | 13 Oct 2026 |
| KI-06 | `KYCValidator.set_validator` | The owner changes the validator in a single transaction, with no two-step or timelocked process. | Out of scope: privileged role. | 15 Oct 2026 |
| KI-07 | Vaulted collateral valuation (tokenized equities with `uiMultiplier`) | Collateral is valued as the raw token balance times the oracle price; the token's `uiMultiplier` / `balanceOfUI` is never read, so a stock split could appear to misprice loans. | Not a vulnerability. The price feeds used by these markets quote one raw token, already adjusted by the multiplier, so a split moves the multiplier and the feed together. | 14 Oct 2026 |
