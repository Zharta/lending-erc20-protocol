# @version 0.4.3

"""
@title P2PLendingSecuritizeLiquidation
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.

"""

from contracts.v1 import P2PLendingSecuritizeBase as base

initializes: base
exports: base.__interface__

# Interfaces

from ethereum.ercs import IERC721
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingVaultSecuritize as vault
from contracts.v1 import P2PLendingSecuritizeErc20 as main




# Constants

BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

VERSION: public(constant(String[30])) = "P2PLendingLiquidation.20260113"



@deploy
def __init__():
    base.__init__()



@external
def partially_liquidate_loan(
    loan: base.Loan,

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
    @notice Partialy liquidates a loan if the LTV exceeds the liquidation_ltv, resulting in a write-off of part of the debt and transfer of part of the collateral to the lender. The loan remains active. Can be called by anyone.
    @param loan The loan to be soft liquidated.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert not base._is_loan_redeemed(loan), "loan redeemed"
    liquidator: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

    current_interest: uint256 = base._compute_settlement_interest(loan)
    convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)
    current_ltv: uint256 = base._compute_ltv(loan.collateral_amount, loan.amount + current_interest, convertion_rate, payment_token_decimals, collateral_token_decimals)

    assert loan.liquidation_ltv > 0, "soft liquidation disabled"
    assert current_ltv >= loan.liquidation_ltv, "ltv lt liquidation ltv"

    principal_written_off: uint256 = 0
    collateral_claimed: uint256 = 0
    liquidation_fee: uint256 = 0
    principal_written_off, collateral_claimed, liquidation_fee = base._compute_partial_liquidation(
        loan.collateral_amount,
        loan.amount + current_interest,
        loan.initial_ltv,
        loan.partial_liquidation_fee,
        convertion_rate,
        payment_token_decimals,
        collateral_token_decimals
    )

    assert principal_written_off < loan.amount + current_interest, "written off ge debt"

    updated_loan: base.Loan = base.Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount + current_interest - principal_written_off,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=block.timestamp,  # reset accrual start time
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount - collateral_claimed - liquidation_fee,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv= loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time,
        vault_id=loan.vault_id,
        redeem_start=loan.redeem_start,
        redeem_residual_collateral=loan.redeem_residual_collateral,
    )

    base.loans[loan.id] = base._loan_state_hash(updated_loan)

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    base._send_collateral(liquidator, collateral_claimed + liquidation_fee, _vault)
    if liquidator != loan.lender:
        base._receive_funds(liquidator, principal_written_off, payment_token)
        base._send_funds(loan.lender, principal_written_off, payment_token)
        base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, principal_written_off)

    log main.LoanPartiallyLiquidated(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        written_off=principal_written_off,
        collateral_claimed=collateral_claimed,
        liquidation_fee=liquidation_fee,
        updated_amount=updated_loan.amount,
        updated_collateral_amount=updated_loan.collateral_amount,
        updated_accrual_start_time=updated_loan.accrual_start_time,
        liquidator=liquidator,
        old_ltv=current_ltv,
        new_ltv=base._compute_ltv(updated_loan.collateral_amount, updated_loan.amount, convertion_rate, payment_token_decimals, collateral_token_decimals)
    )


@external
def liquidate_loan(
    loan: base.Loan,
    redeem_result: base.SignedRedeemResult,

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
    @notice Fully liquidates a defaulted loan. It also allows the full liquidation of active loans that are enabled for partial liquidations but can't be restored to a healthy ltv. The function can be called by anyone.
    @param loan The loan to be liquidated.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    # assert base._is_loan_defaulted(loan), "loan not defaulted"
    liquidator: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin
    current_interest: uint256 = 0
    in_vault_collateral: uint256 = loan.collateral_amount
    in_vault_payment_token: uint256 = 0

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    is_loan_redeemed: bool = base._is_loan_redeemed(loan)
    if is_loan_redeemed:
        assert base._is_loan_redeem_concluded(loan, _vault, redeem_result), "redeem not concluded"
        in_vault_payment_token, in_vault_collateral = base._get_redeem_balances(loan, _vault, payment_token, redeem_result.result)

    if not base._is_loan_defaulted(loan):
        assert loan.liquidation_ltv > 0, "not defaulted, partial disabled"
        current_interest = base._compute_settlement_interest(loan)
        convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)

        if is_loan_redeemed:
            current_ltv: uint256 = base._compute_ltv(
                in_vault_collateral,
                loan.amount + current_interest - in_vault_payment_token if in_vault_payment_token < loan.amount + current_interest else 0,
                convertion_rate,
                payment_token_decimals,
                collateral_token_decimals
            ) if in_vault_collateral > 0 else 0
            if current_ltv > 0:
                assert current_ltv >= loan.liquidation_ltv, "not defaulted, ltv lt partial"
            else:
                assert loan.amount + current_interest > in_vault_payment_token, "not defaulted, no debt"
        else:
            current_ltv: uint256 = base._compute_ltv(loan.collateral_amount, loan.amount + current_interest, convertion_rate, payment_token_decimals, collateral_token_decimals)
            assert current_ltv >= loan.liquidation_ltv, "not defaulted, ltv lt partial"
            principal_written_off: uint256 = 0
            collateral_claimed: uint256 = 0
            liquidation_fee: uint256 = 0
            principal_written_off, collateral_claimed, liquidation_fee = base._compute_partial_liquidation(
                loan.collateral_amount,
                loan.amount + current_interest,
                loan.initial_ltv,
                loan.partial_liquidation_fee,
                convertion_rate,
                payment_token_decimals,
                collateral_token_decimals
            )

            assert principal_written_off >= loan.amount + current_interest, "not defaulted, partial possible"

    else:
        current_interest = self._compute_liquidation_interest(loan)


    outstanding_debt: uint256 = loan.amount + current_interest
    rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)

    liquidation_fee: uint256 = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral: uint256 = 0

    if liquidation_fee <= in_vault_payment_token:
        in_vault_payment_token -= liquidation_fee
    else:
        liquidation_fee_collateral = min(in_vault_collateral, (liquidation_fee - in_vault_payment_token) * rate.denominator * collateral_token_decimals // (rate.numerator * payment_token_decimals))
        liquidation_fee = in_vault_payment_token
        in_vault_payment_token = 0

    # After this block the liquidation fee is fully set:
    # - if the loan is unredeemed, liquidation_fee == 0, liquidation_fee_collateral contains all the fee, in_vault_payment_token == 0
    # - if the loan is redeemed and in_vault_payment_token covers the liquidation fee, liquidation_fee_collateral == 0, liquidation_fee contains all the fee and  in_vault_payment_token is reduced by the fee
    # - otherwise, the fee is split between payment token and collateral token, with in_vault_payment_token == 0
    # For all cases, the liquidation_fee is payable with the tokens in the vault and the liquidation_fee_collateral is payable with the collateral in the vault

    collateral_for_debt: uint256 = (outstanding_debt - in_vault_payment_token) * rate.denominator * collateral_token_decimals // (rate.numerator * payment_token_decimals) if in_vault_payment_token < outstanding_debt else 0
    remaining_collateral: uint256 = in_vault_collateral - liquidation_fee_collateral
    remaining_collateral_value: uint256 = remaining_collateral * rate.numerator * payment_token_decimals // (rate.denominator * collateral_token_decimals)
    protocol_settlement_fee_amount: uint256 = min(loan.protocol_settlement_fee * current_interest // BPS, in_vault_payment_token + remaining_collateral_value)
    shortfall: uint256 = outstanding_debt - remaining_collateral_value if remaining_collateral_value < outstanding_debt else 0
    extcall _vault.withdraw_funds(payment_token, in_vault_payment_token + liquidation_fee)


    # payment_token: outstanding_debt (incl protocol_settlement_fee_amount) + liquidation_fee
    # collateral_token: collateral_for_debt + liquidation_fee_collateral

    liquidator_funds_delta: int256 = 0
    lender_funds_delta: uint256 = 0
    borrower_funds_delta: uint256 = 0
    liquidator_collateral_delta: uint256 = 0
    borrower_collateral_delta: uint256 = 0

    if in_vault_payment_token >= outstanding_debt:

        # scenario: payment tokens fully cover the debt
        # pre: liquidation_fee_collateral == 0 (fee was fully covered by payment tokens)
        # pre: collateral_for_debt == 0 (no collateral needed for debt)
        # pre: in_vault_payment_token >= outstanding_debt

        lender_funds_delta = outstanding_debt - protocol_settlement_fee_amount
        liquidator_funds_delta = convert(liquidation_fee, int256)
        borrower_funds_delta = in_vault_payment_token - outstanding_debt
        # liquidator_collateral_delta = 0
        borrower_collateral_delta = in_vault_collateral

        base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, outstanding_debt)

    elif in_vault_payment_token + remaining_collateral_value >= outstanding_debt:

        # scenario: payment tokens + collateral value cover the debt
        # pre: in_vault_payment_token < outstanding_debt
        # pre: in_vault_payment_token + remaining_collateral_value >= outstanding_debt
        # pre: protocol_settlement_fee_amount <= current_interest < outstanding_debt

        lender_funds_delta = outstanding_debt - protocol_settlement_fee_amount
        liquidator_funds_delta = convert(liquidation_fee + in_vault_payment_token, int256) - convert(outstanding_debt, int256)
        # borrower_funds_delta = 0
        liquidator_collateral_delta = min(collateral_for_debt, remaining_collateral) + liquidation_fee_collateral
        borrower_collateral_delta = in_vault_collateral - liquidator_collateral_delta if in_vault_collateral > liquidator_collateral_delta else 0

        if liquidator != loan.lender:
            base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, outstanding_debt)

    else:

        # scenario: shortfall — vault doesn't have enough to cover the debt
        # pre: in_vault_payment_token + remaining_collateral_value < outstanding_debt
        # pre: protocol_settlement_fee_amount <= remaining_collateral_value (from min())

        lender_funds_delta = in_vault_payment_token + remaining_collateral_value - protocol_settlement_fee_amount
        liquidator_funds_delta = convert(liquidation_fee, int256) - convert(remaining_collateral_value, int256)
        # borrower_funds_delta = 0
        liquidator_collateral_delta = in_vault_collateral
        # borrower_collateral_delta = 0

        if liquidator != loan.lender:
            base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, remaining_collateral_value)


    if liquidator != loan.lender:
        if liquidator_funds_delta < 0:
            base._receive_funds(liquidator, convert(-liquidator_funds_delta, uint256), payment_token)
    else:
        if liquidator_funds_delta + convert(lender_funds_delta, int256) < 0:
            base._receive_funds(liquidator, convert(-liquidator_funds_delta - convert(lender_funds_delta, int256), uint256), payment_token)

    if liquidator != loan.lender:
        base._send_funds(loan.lender, lender_funds_delta, payment_token)
        if liquidator_funds_delta > 0:
            base._send_funds(liquidator, convert(liquidator_funds_delta, uint256), payment_token)
    else:
        if liquidator_funds_delta + convert(lender_funds_delta, int256) > 0:
            base._send_funds(liquidator, convert(liquidator_funds_delta + convert(lender_funds_delta, int256), uint256), payment_token)

    base._send_funds(base.protocol_wallet, protocol_settlement_fee_amount, payment_token)
    base._send_funds(loan.borrower, borrower_funds_delta, payment_token)
    base._send_collateral(liquidator, liquidator_collateral_delta, _vault)
    base._send_collateral(loan.borrower, borrower_collateral_delta, _vault)

    base.loans[loan.id] = empty(bytes32)

    log main.LoanLiquidated(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        liquidator=liquidator,
        outstanding_debt=outstanding_debt,
        collateral_for_debt=collateral_for_debt,
        remaining_collateral=remaining_collateral,
        remaining_collateral_value=remaining_collateral_value,
        shortfall=shortfall,
        liquidation_fee=liquidation_fee_collateral,
        protocol_settlement_fee_amount=protocol_settlement_fee_amount
    )


@view
@external
def simulate_partial_liquidation(
    loan: base.Loan,
    oracle_addr: address,
    oracle_reverse: bool,
    payment_token_decimals: uint256,
    collateral_token_decimals: uint256,
) -> base.PartialLiquidationResult:

    assert base._is_loan_valid(loan), "invalid loan"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert not base._is_loan_redeemed(loan), "loan redeemed"

    current_interest: uint256 = base._compute_settlement_interest(loan)
    convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)
    current_ltv: uint256 = base._compute_ltv(loan.collateral_amount, loan.amount + current_interest, convertion_rate, payment_token_decimals, collateral_token_decimals)

    assert current_ltv >= loan.liquidation_ltv, "ltv lt liquidation ltv"

    debt_written_off: uint256 = 0
    collateral_claimed: uint256 = 0
    liquidation_fee: uint256 = 0
    debt_written_off, collateral_claimed, liquidation_fee = base._compute_partial_liquidation(
        loan.collateral_amount,
        loan.amount + current_interest,
        loan.initial_ltv,
        loan.partial_liquidation_fee,
        convertion_rate,
        payment_token_decimals,
        collateral_token_decimals,
    )


    assert debt_written_off < loan.amount + current_interest, "written off ge debt"

    return base.PartialLiquidationResult(
        collateral_claimed=collateral_claimed,
        liquidation_fee=liquidation_fee,
        debt_written_off=debt_written_off,
        updated_ltv=base._compute_ltv(loan.collateral_amount - collateral_claimed - liquidation_fee, loan.amount + current_interest - debt_written_off, convertion_rate, payment_token_decimals, collateral_token_decimals)
    )



@external
def transfer_loan(
    loan: base.Loan,
    new_borrower: address,
    new_borrower_kyc: base.SignedWalletValidation,
    redeem_result: base.SignedRedeemResult,

    payment_token: address,
    collateral_token: address,
    oracle_addr: address,
    oracle_reverse: bool,
    kyc_validator_addr: address,
    collateral_token_decimals: uint256,
    payment_token_decimals: uint256,
    offer_sig_domain_separator: bytes32,
    vault_impl_addr: address,
    vault_registrar: address,
):

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._check_user(base.transfer_agent), "not transfer agent"
    assert new_borrower != loan.borrower, "new borrower same as current"

    is_loan_redeemed: bool = base._is_loan_redeemed(loan)
    current_vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)

    if is_loan_redeemed:
        assert base._is_loan_redeem_concluded(loan, current_vault, redeem_result), "redeem not concluded"

    assert staticcall base.KYCValidator(kyc_validator_addr).check_validation(new_borrower_kyc), "KYC validation fail"
    assert new_borrower_kyc.validation.wallet == new_borrower, "KYC validation fail"

    updated_loan: base.Loan = base.Loan(
        id=empty(bytes32),
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=new_borrower,
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
        liquidation_ltv= loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time,
        vault_id=base.vault_count[new_borrower],
        redeem_start=loan.redeem_start,
        redeem_residual_collateral=loan.redeem_residual_collateral,
    )
    updated_loan.id = base._compute_loan_id(updated_loan)
    base.loans[updated_loan.id] = base._loan_state_hash(updated_loan)
    base.loans[loan.id] = empty(bytes32)

    new_vault: vault.Vault = base._create_new_vault(new_borrower, vault_impl_addr, collateral_token, vault_registrar)
    base._send_collateral(
        new_vault.address,
        staticcall current_vault.withdrawable_balance(),
        current_vault
    )
    extcall current_vault.transfer_funds(
        loan.payment_token,
        staticcall IERC20(loan.payment_token).balanceOf(current_vault.address),
        new_vault.address
    )

    log main.LoanBorrowerTransferred(
        loan_id=loan.id,
        new_loan_id=updated_loan.id,
        old_borrower=loan.borrower,
        new_borrower=new_borrower,
        lender=loan.lender,
        vault_id=updated_loan.vault_id
    )

# Internal functions


@view
@internal
def _get_repayment_time(loan: base.Loan) -> uint256:
    return loan.maturity

@view
@internal
def _validate_kyc(validation: base.SignedWalletValidation, wallet: address, kyc_validator_addr: address):
    assert (staticcall base.KYCValidator(kyc_validator_addr).check_validation(validation) and validation.validation.wallet == wallet), "KYC validation fail"

@view
@internal
def _compute_liquidation_interest(loan: base.Loan) -> uint256:
    return loan.amount * loan.apr * (loan.maturity - loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)
