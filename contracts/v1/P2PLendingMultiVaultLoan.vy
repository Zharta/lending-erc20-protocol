# @version 0.4.3

"""
@title P2PLendingMultiVaultLoan
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.

"""

from contracts.v1 import P2PLendingMultiVaultBase as base

initializes: base
exports: base.__interface__

# Interfaces

from ethereum.ercs import IERC721
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingMultiVaultErc20 as main


# Constants

BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

VERSION: public(constant(String[25])) = "P2PLendingMVLoan.20260612"



@deploy
def __init__():
    base.__init__()



# Core functions

@external
def create_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bytes32:

    """
    @notice Create a loan.
    @param offer The signed offer.
    @param principal The principal amount of the loan.
    @param collateral_amount The amount of collateral tokens to be used for the loan.
    @param borrower_kyc The signed KYC validation for the borrower.
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the created loan.
    """


    borrower: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

    convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)
    loan: base.Loan = self._validate_and_build_loan(
        offer,
        principal,
        principal,
        collateral_amount,
        borrower,
        block.timestamp,
        base.vault_count[borrower],
        convertion_rate,
        borrower_kyc,
        lender_kyc,
        payment_token,
        collateral_token,
        oracle_addr,
        kyc_validator_addr,
        collateral_token_decimals,
        payment_token_decimals,
        offer_sig_domain_separator,
    )

    assert base.loans[loan.id] == empty(bytes32), "loan already exists"
    base._check_and_update_offer_state(offer, principal)
    base.loans[loan.id] = base._loan_state_hash(loan)

    _vault: base.Vault = base._create_new_vault(loan.borrower, vault_impl_addr, collateral_token, base.vault_registrar)
    base._receive_collateral(loan.borrower, loan.collateral_amount, _vault)
    base._transfer_funds(loan.lender, loan.borrower, loan.amount - loan.origination_fee_amount, payment_token)

    if loan.protocol_upfront_fee_amount > 0:
        base._transfer_funds(loan.lender, base.protocol_wallet, loan.protocol_upfront_fee_amount, payment_token)

    log main.LoanCreated(
        id=loan.id,
        amount=loan.initial_amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        create_time=loan.create_time,
        start_time=loan.start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv=loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv=loan.initial_ltv,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        offer_id=loan.offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        oracle_rate_num=convertion_rate.numerator,
        oracle_rate_den=convertion_rate.denominator,
        vault_id=loan.vault_id,
        vault_addr=_vault.address,
    )
    return loan.id


@external
def create_leveraged_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation,
    mint_spend: uint256,
    min_collateral_out: uint256,
    vault_capabilities: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bytes32:

    """
    @notice Create a leveraged loan by minting collateral with the loan principal plus borrower margin.
    @param offer The signed offer.
    @param principal The principal amount of the loan.
    @param collateral_amount The expected total collateral amount backing the loan after minting.
    @param borrower_kyc The signed KYC validation for the borrower.
    @param lender_kyc The signed KYC validation for the lender.
    @param mint_spend The total payment token amount routed to the collateral mint.
    @param min_collateral_out The minimum collateral amount to receive from the mint.
    @param vault_capabilities The capability bitmask of the vault implementation (injected by the main stub).
    @return The ID of the created loan.
    """

    if (vault_capabilities & base.MINT_SYNC) != 0:
        return self._create_leveraged_loan_sync(
            offer,
            principal,
            collateral_amount,
            borrower_kyc,
            lender_kyc,
            mint_spend,
            min_collateral_out,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            vault_impl_addr,
        )
    elif (vault_capabilities & base.MINT_ASYNC) != 0:
        return self._create_leveraged_loan_async(
            offer,
            principal,
            collateral_amount,
            borrower_kyc,
            lender_kyc,
            mint_spend,
            min_collateral_out,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            vault_impl_addr,
        )
    else:
        # MINT_MANUAL is deferred until a manual-mint vault exists
        raise "mint mode not supported"


@external
def start_loan(
    loan: base.Loan,
    mint_result: base.SignedMintResult,
    additional_collateral: uint256,
    vault_capabilities: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bytes32:

    """
    @notice Start a pending loan once the collateral mint is settled.
    @dev Permissionless: anyone can activate a pending loan, so a keeper/lender can start (and later liquidate) it even if the borrower walks away.
         No offer re-validation and no LTV gating, an unhealthy loan is handled by the normal liquidation. The borrower can add collateral to restore loan health.
         A loan is startable if is not past maturity and the total collateral satisfies the offer's min_collateral_amount.
         If a loan is not startable, must be force-unwound via cancel_pending_loan.
         For an async (ERC-7540) vault the mint must be FULLY fulfilled  with no in-flight/claimable cancellation.
    @param loan The pending loan to start.
    @param mint_result The owner-signed mint result attestation (used by the deferred MINT_MANUAL path).
    @param additional_collateral Possible extra collateral to add to the loan. Only valid if called by the borrower.
    @param vault_capabilities The capability bitmask of the vault implementation (injected by the main stub).
    @return The ID of the started loan.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert not base._is_loan_started(loan), "loan started"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert additional_collateral == 0 or base._check_user(loan.borrower), "not borrower"

    _vault: base.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)

    minted: uint256 = 0
    if (vault_capabilities & base.MINT_ASYNC) != 0:
        # Async (ERC-7540): require the deposit FULLY fulfilled with no pending/claimable cancel
        status: base.AsyncStatus = staticcall _vault.mint_status(base.mint_addr)
        assert status.request_claimable > 0 and status.request_pending == 0 and status.cancel_pending == 0 and status.cancel_claimable == 0, "mint not settled"
        minted = extcall _vault.claim_mint(base.mint_addr, True, False)
        assert minted + additional_collateral >= loan.min_collateral_amount, "low collateral amount"
    else:
        # MINT_MANUAL is deferred until a manual-mint vault exists
        raise "mint mode not supported"

    total_collateral: uint256 = minted + additional_collateral

    updated_loan: base.Loan = base.Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        create_time=loan.create_time,
        start_time=block.timestamp,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=total_collateral,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv=loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv=loan.initial_ltv,
        call_time=loan.call_time,
        vault_id=loan.vault_id,
        redeem_start=loan.redeem_start,
        redeem_residual_collateral=loan.redeem_residual_collateral,
        max_pending_window=loan.max_pending_window,
    )
    base.loans[loan.id] = base._loan_state_hash(updated_loan)

    base._receive_collateral(loan.borrower, total_collateral, _vault)

    if additional_collateral > 0:
        # Mirror add_collateral_to_loan's event so indexers see the borrower topup applied at activation.
        convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)
        outstanding_debt: uint256 = loan.amount + base._compute_settlement_interest(loan)
        log main.LoanCollateralAdded(
            id=loan.id,
            borrower=loan.borrower,
            lender=loan.lender,
            collateral_token=loan.collateral_token,
            old_collateral_amount=minted,
            new_collateral_amount=total_collateral,
            old_ltv=base._compute_ltv(minted, outstanding_debt, convertion_rate, payment_token_decimals, collateral_token_decimals),
            new_ltv=base._compute_ltv(total_collateral, outstanding_debt, convertion_rate, payment_token_decimals, collateral_token_decimals),
        )

    log main.LoanStarted(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        start_time=block.timestamp,
        maturity=loan.maturity,
        collateral_amount=total_collateral,
        caller=msg.sender,
    )
    return loan.id


@external
def cancel_pending_loan(
    loan: base.Loan,
    mint_result: base.SignedMintResult,
    vault_capabilities: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bool:

    """
    @notice Cancel a pending (async) leveraged loan, unwinding the in-flight ERC-7540 deposit.
    @dev Two-phase async state machine over the vault `mint_status()`.
         Returns whether the cancellation completed (True) or must be retried after the request
         resolves (False). Only applies to `MINT_ASYNC` pending loans. The branches are:
           - deposit claimable:
                if the loan is startable, cancelation is disallowed (revert); the caller must start_loan instead.
                if it is NOT startable, the fill cannot be cancelled at the ERC-7540 level, so force unwind: claim the minted
                shares and split them as in liquidation. Returns True.
           - cancel claimable: claim the reclaimed payment to the vault and unwind the loan
           - request pending: request the cancellation (cancelDepositRequest), return False.
           - cancel pending: cancellation submitted, still processing, return False.
    @param loan The pending loan to cancel.
    @param mint_result The owner-signed mint result attestation (for MINT_MANUAL cancellation path; unused on the async path).
    @param vault_capabilities The capability bitmask of the vault implementation (injected by the main stub).
    @return True if the cancellation completed and the loan was settled, False if it must be retried.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert not base._is_loan_started(loan), "loan started"
    # Borrower may cancel anytime; anyone may cancel after the pending window elapses
    # zero max_pending_window means permissionless cancel is DISABLED
    assert msg.sender == loan.borrower or (loan.max_pending_window > 0 and block.timestamp >= loan.create_time + loan.max_pending_window), "not borrower"
    assert (vault_capabilities & (base.MINT_ASYNC | base.MINT_CANCEL)) == (base.MINT_ASYNC | base.MINT_CANCEL), "cancel not supported"

    _vault: base.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)

    status: base.AsyncStatus = staticcall _vault.mint_status(base.mint_addr)

    if status.request_claimable > 0:
        # The deposit is fulfilled, cancelation is possible only if the loan is NOT startable.
        assert status.request_pending == 0, "deposit still pending"
        assert status.cancel_pending == 0 and status.cancel_claimable == 0, "cancel in flight"

        minted: uint256 = extcall _vault.claim_mint(base.mint_addr, True, False)
        assert minted < loan.min_collateral_amount or base._is_loan_defaulted(loan), "claimable mint, start instead"
        base._receive_collateral(loan.borrower, minted, _vault)

        # order: caller fee > protocol fee > lender recovery > borrower
        convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)
        interest: uint256 = base._compute_capped_interest(loan)
        lender_deployed: uint256 = loan.amount - loan.origination_fee_amount
        debt: uint256 = lender_deployed + interest

        minted_value: uint256 = minted * convertion_rate.numerator * payment_token_decimals // (convertion_rate.denominator * collateral_token_decimals)
        liquidation_fee_value: uint256 = min(debt * loan.full_liquidation_fee // BPS, minted_value)
        value_after_fee: uint256 = minted_value - liquidation_fee_value
        protocol_fee_value: uint256 = min(loan.protocol_settlement_fee * interest // BPS, value_after_fee)

        liquidation_fee_shares: uint256 = liquidation_fee_value * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)
        protocol_fee_shares: uint256 = protocol_fee_value * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)
        lender_shares: uint256 = 0
        borrower_shares: uint256 = 0
        if value_after_fee >= debt:
            lender_shares = (debt - protocol_fee_value) * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)
            borrower_shares = minted - liquidation_fee_shares - protocol_fee_shares - lender_shares
        else:
            lender_shares = minted - liquidation_fee_shares - protocol_fee_shares

        base.loans[loan.id] = empty(bytes32)
        base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)

        canceller: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin
        base._send_collateral(canceller, liquidation_fee_shares, _vault)
        base._send_collateral(loan.lender, lender_shares, _vault)
        base._send_collateral(base.protocol_wallet, protocol_fee_shares, _vault)
        base._send_collateral(loan.borrower, borrower_shares, _vault)

        log main.PendingLoanLiquidated(
            id=loan.id,
            borrower=loan.borrower,
            lender=loan.lender,
            collateral_claimed=minted,
            lender_amount=lender_shares,
            liquidation_fee=liquidation_fee_shares,
            protocol_fee=protocol_fee_shares,
            borrower_amount=borrower_shares,
            caller=canceller,
        )
        return True

    if status.cancel_claimable > 0:
        # The cancellation settled: claim the reclaimed payment back into the vault, then settle.
        assert status.request_pending == 0, "deposit still pending"
        extcall _vault.claim_mint(base.mint_addr, False, True)

        # a pending loan has NO minted collateral, so the reclaimed payment is the only asset
        available: uint256 = staticcall IERC20(payment_token).balanceOf(_vault.address)

        interest: uint256 = base._compute_capped_interest(loan)
        lender_deployed: uint256 = loan.amount - loan.origination_fee_amount
        debt: uint256 = lender_deployed + interest
        liquidation_fee: uint256 = min(debt * loan.full_liquidation_fee // BPS, available)
        available_after_fee: uint256 = available - liquidation_fee
        protocol_settlement_fee: uint256 = min(loan.protocol_settlement_fee * interest // BPS, available_after_fee)

        lender_amount: uint256 = 0
        borrower_amount: uint256 = 0
        if available_after_fee >= debt:
            lender_amount = debt - protocol_settlement_fee
            borrower_amount = available_after_fee - debt
        else:
            lender_amount = available_after_fee - protocol_settlement_fee

        base.loans[loan.id] = empty(bytes32)
        base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)

        # fee + lender + protocol + borrower == available
        extcall _vault.withdraw_funds(payment_token, available)

        liquidator: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin
        if liquidation_fee > 0:
            base._send_funds(liquidator, liquidation_fee, payment_token)
        base._send_funds(loan.lender, lender_amount, payment_token)
        if protocol_settlement_fee > 0:
            base._send_funds(base.protocol_wallet, protocol_settlement_fee, payment_token)
        if borrower_amount > 0:
            base._send_funds(loan.borrower, borrower_amount, payment_token)

        log main.PendingLoanCancelled(
            id=loan.id,
            borrower=loan.borrower,
            lender=loan.lender,
            payment_refunded=available,
            caller=liquidator,
        )
        return True
    elif status.request_pending > 0:
        # the deposit is still in-flight, request its cancellation, retry once it settles.
        extcall _vault.cancel_mint(base.mint_addr)
        return False
    elif status.cancel_pending > 0:
        # the cancellation was submitted but has not yet resolved, retry later.
        return False
    else:
        # all four counters zero is invalid for a pending async loan.
        raise "no pending mint"


@external
def cancel_redeem(
    loan: base.Loan,
    vault_capabilities: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bool:

    """
    @notice Cancel an ongoing collateral redemption for an active loan, reversing the in-flight
            ERC-7540 redeem request.
    @dev Borrower-only. Returns whether the cancellation completed (True) or must be retried after the request resolves (False).
         Only applies to vaults that support both REDEEM_ASYNC and REDEEM_CANCEL.
         Precondition: the redemption must NOT be claimable, if it is, the borrower must settle instead.
         The phases are:
           - cancel claimable: claim the reclaimed collateral back into the vault and reverse the redemption; return True.
           - request pending: request the cancellation (cancelRedeemRequest), return False.
           - cancel pending: cancellation submitted, still processing, return False.
    @param loan The active loan whose redemption is to be cancelled.
    @param vault_capabilities The capability bitmask of the vault implementation.
    @return True if the cancellation completed and the redemption was reversed, False if it must be retried.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._is_loan_started(loan), "loan not started"
    assert loan.redeem_start > 0, "not redeeming"
    assert msg.sender == loan.borrower, "not borrower"
    assert (vault_capabilities & (base.REDEEM_ASYNC | base.REDEEM_CANCEL)) == (base.REDEEM_ASYNC | base.REDEEM_CANCEL), "redeem cancel not supported"

    _vault: base.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)

    status: base.AsyncStatus = staticcall _vault.redeem_status(base.redemption_addr)

    assert status.request_claimable == 0, "claimable redeem"

    if status.cancel_claimable > 0:
        # cancellation settled: reclaim the collateral shares back into the vault, then reverse the redemption.
        assert status.request_pending == 0, "redeem still pending"
        extcall _vault.claim_redeem(base.redemption_addr, False, True)

        updated_loan: base.Loan = base.Loan(
            id=loan.id,
            offer_id=loan.offer_id,
            offer_tracing_id=loan.offer_tracing_id,
            initial_amount=loan.initial_amount,
            amount=loan.amount,
            apr=loan.apr,
            payment_token=loan.payment_token,
            maturity=loan.maturity,
            create_time=loan.create_time,
            start_time=loan.start_time,
            accrual_start_time=loan.accrual_start_time,
            borrower=loan.borrower,
            lender=loan.lender,
            collateral_token=loan.collateral_token,
            collateral_amount=loan.collateral_amount,
            min_collateral_amount=loan.min_collateral_amount,
            origination_fee_amount=loan.origination_fee_amount,
            protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
            protocol_settlement_fee=loan.protocol_settlement_fee,
            partial_liquidation_fee=loan.partial_liquidation_fee,
            full_liquidation_fee=loan.full_liquidation_fee,
            call_eligibility=loan.call_eligibility,
            call_window=loan.call_window,
            liquidation_ltv=loan.liquidation_ltv,
            oracle_addr=loan.oracle_addr,
            initial_ltv=loan.initial_ltv,
            call_time=loan.call_time,
            vault_id=loan.vault_id,
            redeem_start=0,
            redeem_residual_collateral=0,
            max_pending_window=loan.max_pending_window,
        )
        base.loans[loan.id] = base._loan_state_hash(updated_loan)

        log main.RedeemCancelled(
            loan_id=loan.id,
            borrower=loan.borrower,
            lender=loan.lender,
            vault_id=loan.vault_id,
        )
        return True
    elif status.request_pending > 0:
        # redemption is still in-flight, request its cancellation. Retry once it settles.
        extcall _vault.cancel_redeem(base.redemption_addr)
        return False
    elif status.cancel_pending > 0:
        # cancellation was submitted but has not yet resolved, retry later.
        return False
    else:
        # All four counters zero is invalid for a loan in redemption.
        raise "no pending redeem"


@external
def redeem_and_settle(
    loan: base.Loan,
    residual_collateral: uint256,
    vault_capabilities: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
):

    """
    @notice Atomically redeem the loan's collateral to payment token (sync) and settle the loan in
            one transaction.
    @dev REDEEM_SYNC only. The collateral to payment conversion completes on-chain and instantly.
    @param loan The loan to redeem-and-settle.
    @param residual_collateral The amount of collateral to keep (not redeem); returned to the borrower.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._is_loan_started(loan), "loan not started"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert not base._is_loan_redeemed(loan), "loan already redeemed"
    assert base._check_user(loan.borrower), "not borrower"
    assert (vault_capabilities & base.REDEEM_SYNC) != 0, "sync redeem not supported"
    assert base.redemption_addr != empty(address), "redemption addr not set"
    assert residual_collateral <= loan.collateral_amount, "residual collateral gt total"

    _vault: base.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)

    redeemed: uint256 = 0
    refunded: uint256 = 0
    (redeemed, refunded) = extcall _vault.redeem_sync(
        base.redemption_addr,
        payment_token,
        loan.collateral_amount - residual_collateral,
        convertion_rate.numerator,
        convertion_rate.denominator,
    )

    in_vault_payment_token: uint256 = redeemed
    in_vault_collateral: uint256 = residual_collateral

    interest: uint256 = base._compute_settlement_interest(loan)
    protocol_settlement_fee: uint256 = loan.protocol_settlement_fee * interest // BPS

    base.loans[loan.id] = empty(bytes32)
    base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)

    if in_vault_payment_token > 0:
        extcall _vault.withdraw_funds(payment_token, in_vault_payment_token)

    # in_vault_payment_token - (loan.amount + interest) == borrower_funds_delta
    borrower_funds_delta: int256 = convert(in_vault_payment_token, int256) - convert(loan.amount + interest, int256)
    if borrower_funds_delta < 0:
        base._receive_funds(loan.borrower, convert(-borrower_funds_delta, uint256), payment_token)
    elif borrower_funds_delta > 0:
        base._send_funds(loan.borrower, convert(borrower_funds_delta, uint256), payment_token)

    base._send_funds(loan.lender, loan.amount + interest - protocol_settlement_fee, payment_token)
    if protocol_settlement_fee > 0:
        base._send_funds(base.protocol_wallet, protocol_settlement_fee, payment_token)

    base._send_collateral(loan.borrower, in_vault_collateral, _vault)

    log main.LoanPaid(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        payment_token=loan.payment_token,
        paid_principal=loan.amount,
        paid_interest=interest,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee_amount=protocol_settlement_fee,
        in_vault_payment_token=in_vault_payment_token,
        in_vault_collateral=in_vault_collateral,
    )



@internal
def _validate_and_build_loan(
    offer: base.SignedOffer,
    principal: uint256,
    fee_principal: uint256,
    collateral_amount: uint256,
    borrower: address,
    start_time: uint256,
    vault_id: uint256,
    convertion_rate: base.UInt256Rational,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation,
    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
) -> base.Loan:

    assert base._is_offer_signed_by_lender(offer, offer_sig_domain_separator), "offer not signed by lender"
    base._check_offer_validity(offer, payment_token, collateral_token, oracle_addr)

    assert staticcall base.KYCValidator(kyc_validator_addr).check_validations_pair(borrower_kyc, lender_kyc), "KYC validation fail"
    assert lender_kyc.validation.wallet == offer.offer.lender, "KYC validation fail"
    assert borrower_kyc.validation.wallet == borrower, "KYC validation fail"
    assert offer.offer.borrower == empty(address) or offer.offer.borrower == borrower, "borrower not allowed"
    assert offer.offer.principal == 0 or offer.offer.principal == principal, "offer principal mismatch"
    assert offer.offer.min_collateral_amount <= collateral_amount, "low collateral amount"
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"

    max_initial_ltv: uint256 = offer.offer.max_iltv
    if offer.offer.max_iltv == 0:
        max_initial_ltv = base._compute_ltv(offer.offer.min_collateral_amount, principal, convertion_rate, payment_token_decimals, collateral_token_decimals)

    initial_ltv: uint256 = base._compute_ltv(collateral_amount, principal, convertion_rate, payment_token_decimals, collateral_token_decimals)
    assert initial_ltv <= max_initial_ltv, "initial ltv gt max iltv"

    if offer.offer.liquidation_ltv > 0:
        assert offer.offer.liquidation_ltv > max_initial_ltv, "liquidation ltv le initial ltv"
        # required for soft liquidation: (1 + f) * iltv < 1
        assert (BPS + base.partial_liquidation_fee) * max_initial_ltv < BPS * BPS, "initial ltv too high"

    offer_id: bytes32 = base._compute_signed_offer_id(offer)
    loan: base.Loan = base.Loan(
        id=empty(bytes32),
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.offer.apr,
        payment_token=offer.offer.payment_token,
        maturity=block.timestamp + offer.offer.duration,
        create_time=block.timestamp,
        start_time=start_time,
        accrual_start_time=block.timestamp,
        borrower=borrower,
        lender=offer.offer.lender,
        collateral_token=collateral_token,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.offer.min_collateral_amount,
        origination_fee_amount=offer.offer.origination_fee_bps * fee_principal // BPS,
        protocol_upfront_fee_amount=base.protocol_upfront_fee * fee_principal // BPS,
        protocol_settlement_fee=base.protocol_settlement_fee,
        partial_liquidation_fee=base.partial_liquidation_fee,
        full_liquidation_fee=base.full_liquidation_fee,
        call_eligibility=offer.offer.call_eligibility,
        call_window=offer.offer.call_window,
        liquidation_ltv=offer.offer.liquidation_ltv,
        oracle_addr=oracle_addr,
        initial_ltv=max_initial_ltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=base.max_pending_window,
    )
    loan.id = base._compute_loan_id(loan)

    return loan


@internal
def _create_leveraged_loan_sync(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation,
    mint_spend: uint256,
    min_collateral_out: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bytes32:

    borrower: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

    convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)

    # Fees are charged on the ORIGINAL principal at creation and are not refunded
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"
    origination_fee: uint256 = offer.offer.origination_fee_bps * principal // BPS
    protocol_upfront: uint256 = base.protocol_upfront_fee * principal // BPS

    lender_to_vault: uint256 = principal - origination_fee
    assert mint_spend >= lender_to_vault, "mint_spend lt principal"
    borrower_margin: uint256 = mint_spend - lender_to_vault

    vault_id: uint256 = base.vault_count[borrower]
    _vault: base.Vault = base._create_new_vault(borrower, vault_impl_addr, collateral_token, base.vault_registrar)

    base._transfer_funds(offer.offer.lender, _vault.address, lender_to_vault, payment_token)
    if borrower_margin > 0:
        base._transfer_funds(borrower, _vault.address, borrower_margin, payment_token)
    if protocol_upfront > 0:
        base._transfer_funds(offer.offer.lender, base.protocol_wallet, protocol_upfront, payment_token)

    minted: uint256 = 0
    refunded: uint256 = 0
    (minted, refunded) = extcall _vault.mint_sync(payment_token, base.mint_addr, min_collateral_out, mint_spend)

    new_principal: uint256 = principal
    if offer.offer.principal == 0:
        # FLEXIBLE principal: reduce the principal by what was refunded to the lender.
        lender_refund: uint256 = min(refunded, principal)
        new_principal = principal - lender_refund
        borrower_refund: uint256 = refunded - lender_refund
        if lender_refund > 0:
            extcall _vault.transfer_funds(payment_token, lender_refund, offer.offer.lender)
        if borrower_refund > 0:
            extcall _vault.transfer_funds(payment_token, borrower_refund, borrower)
    else:
        # FIXED principal: principal is binding, return any leftover to the borrower.
        if refunded > 0:
            extcall _vault.transfer_funds(payment_token, refunded, borrower)

    assert new_principal > 0, "zero principal"

    loan: base.Loan = self._validate_and_build_loan(
        offer,
        new_principal,
        principal,
        minted,
        borrower,
        block.timestamp,
        vault_id,
        convertion_rate,
        borrower_kyc,
        lender_kyc,
        payment_token,
        collateral_token,
        oracle_addr,
        kyc_validator_addr,
        collateral_token_decimals,
        payment_token_decimals,
        offer_sig_domain_separator,
    )

    assert base.loans[loan.id] == empty(bytes32), "loan already exists"
    base._check_and_update_offer_state(offer, new_principal)
    base.loans[loan.id] = base._loan_state_hash(loan)
    base._receive_collateral(borrower, minted, _vault)

    log main.LoanCreated(
        id=loan.id,
        amount=loan.initial_amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        create_time=loan.create_time,
        start_time=loan.start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv=loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv=loan.initial_ltv,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        offer_id=loan.offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        oracle_rate_num=convertion_rate.numerator,
        oracle_rate_den=convertion_rate.denominator,
        vault_id=loan.vault_id,
        vault_addr=_vault.address,
    )
    log main.LeveragedLoanCreated(
        id=loan.id,
        principal=new_principal,
        collateral_amount=minted,
        acquired_collateral=minted,
        payment_spent=mint_spend,
        borrower_margin=borrower_margin,
        pending=False,
        mint_deadline=0,
    )
    return loan.id


@internal
def _create_leveraged_loan_async(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation,
    mint_spend: uint256,
    min_collateral_out: uint256,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
) -> bytes32:

    borrower: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

    convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)

    # zero window (disabled) passes trivially.
    assert offer.offer.duration > base.max_pending_window, "duration le pending window"

    # Fees are charged on the ORIGINAL principal at creation and are not refunded
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"
    origination_fee: uint256 = offer.offer.origination_fee_bps * principal // BPS
    protocol_upfront: uint256 = base.protocol_upfront_fee * principal // BPS

    lender_to_vault: uint256 = principal - origination_fee
    assert mint_spend >= lender_to_vault, "mint_spend lt principal"
    borrower_margin: uint256 = mint_spend - lender_to_vault

    vault_id: uint256 = base.vault_count[borrower]
    _vault: base.Vault = base._create_new_vault(borrower, vault_impl_addr, collateral_token, base.vault_registrar)

    base._transfer_funds(offer.offer.lender, _vault.address, lender_to_vault, payment_token)
    if borrower_margin > 0:
        base._transfer_funds(borrower, _vault.address, borrower_margin, payment_token)
    if protocol_upfront > 0:
        base._transfer_funds(offer.offer.lender, base.protocol_wallet, protocol_upfront, payment_token)

    # Build the PENDING loan against the caller's EXPECTED collateral_amount, reconciliation happens in start_loan.
    loan: base.Loan = self._validate_and_build_loan(
        offer,
        principal,
        principal,
        collateral_amount,
        borrower,
        0,
        vault_id,
        convertion_rate,
        borrower_kyc,
        lender_kyc,
        payment_token,
        collateral_token,
        oracle_addr,
        kyc_validator_addr,
        collateral_token_decimals,
        payment_token_decimals,
        offer_sig_domain_separator,
    )

    assert base.loans[loan.id] == empty(bytes32), "loan already exists"
    base._check_and_update_offer_state(offer, principal)
    base.loans[loan.id] = base._loan_state_hash(loan)

    extcall _vault.mint_async(payment_token, base.mint_addr, min_collateral_out, mint_spend)

    log main.LoanCreated(
        id=loan.id,
        amount=loan.initial_amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        create_time=loan.create_time,
        start_time=loan.start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv=loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv=loan.initial_ltv,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        offer_id=loan.offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        oracle_rate_num=convertion_rate.numerator,
        oracle_rate_den=convertion_rate.denominator,
        vault_id=loan.vault_id,
        vault_addr=_vault.address,
    )
    log main.LeveragedLoanCreated(
        id=loan.id,
        principal=principal,
        collateral_amount=collateral_amount,
        acquired_collateral=0,
        payment_spent=mint_spend,
        borrower_margin=borrower_margin,
        pending=True,
        mint_deadline=block.timestamp + loan.max_pending_window if loan.max_pending_window > 0 else 0,
    )
    return loan.id
