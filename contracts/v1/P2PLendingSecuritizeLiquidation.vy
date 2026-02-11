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

    is_loan_redeemed: bool = base._is_loan_redeemed(loan)

    if not base._is_loan_defaulted(loan):

        current_interest = base._compute_settlement_interest(loan)
        convertion_rate: base.UInt256Rational = base._get_oracle_rate(oracle_addr, oracle_reverse)
        current_ltv: uint256 = base._compute_ltv(loan.collateral_amount, loan.amount + current_interest, convertion_rate, payment_token_decimals, collateral_token_decimals)

        assert loan.liquidation_ltv > 0, "not defaulted, partial disabled"
        assert current_ltv >= loan.liquidation_ltv, "not defaulted, ltv lt partial"

        if not is_loan_redeemed:
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

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    if is_loan_redeemed:
        assert base._is_loan_redeem_concluded(loan, _vault, redeem_result), "redeem not concluded"
        in_vault_payment_token, in_vault_collateral = base._get_redeem_balances(loan, _vault, payment_token, redeem_result.result)

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

    collateral_for_debt: uint256 = (outstanding_debt - in_vault_payment_token) * rate.denominator * collateral_token_decimals // (rate.numerator * payment_token_decimals) if in_vault_payment_token < outstanding_debt else 0
    remaining_collateral: uint256 = in_vault_collateral - liquidation_fee_collateral
    remaining_collateral_value: uint256 = remaining_collateral * rate.numerator * payment_token_decimals // (rate.denominator * collateral_token_decimals)
    protocol_settlement_fee_amount: uint256 = min(loan.protocol_settlement_fee * current_interest // BPS, remaining_collateral_value)
    shortfall: uint256 = outstanding_debt - remaining_collateral_value if remaining_collateral_value < outstanding_debt else 0
    extcall _vault.withdraw_funds(payment_token, in_vault_payment_token + liquidation_fee)


    # payment_token: outstanding_debt (incl protocol_settlement_fee_amount) + liquidation_fee
    # collateral_token: collateral_for_debt + liquidation_fee_collateral

    if in_vault_payment_token >= outstanding_debt:
        # liquidation_fee_collateral == 0
        base._send_funds(loan.lender, outstanding_debt - protocol_settlement_fee_amount, payment_token)
        base._send_funds(base.protocol_wallet, protocol_settlement_fee_amount, payment_token)
        base._send_funds(liquidator, liquidation_fee, payment_token)
        base._send_funds(loan.borrower, in_vault_payment_token - outstanding_debt, payment_token)

        base._send_collateral(liquidator, collateral_for_debt, _vault)
        if remaining_collateral > collateral_for_debt:
            base._send_collateral(loan.borrower, remaining_collateral - collateral_for_debt, _vault)

        base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, outstanding_debt)

    elif in_vault_payment_token + remaining_collateral_value >= outstanding_debt:
    # if remaining_collateral_value >= outstanding_debt:
        if liquidator != loan.lender:
            base._receive_funds(liquidator, outstanding_debt - in_vault_payment_token - liquidation_fee, payment_token)
            base._send_funds(loan.lender, outstanding_debt - protocol_settlement_fee_amount, payment_token)
            base._send_funds(base.protocol_wallet, protocol_settlement_fee_amount, payment_token)
            base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, outstanding_debt)
        else:
            base._transfer_funds(liquidator, base.protocol_wallet, protocol_settlement_fee_amount, payment_token)
            base._send_funds(liquidator, liquidation_fee, payment_token)

        base._send_collateral(liquidator, collateral_for_debt + liquidation_fee_collateral, _vault)
        if remaining_collateral > collateral_for_debt + liquidation_fee_collateral:
            base._send_collateral(loan.borrower, remaining_collateral - collateral_for_debt - liquidation_fee_collateral, _vault)

    else:
        if liquidator != loan.lender:
            base._receive_funds(liquidator, remaining_collateral_value - in_vault_payment_token - liquidation_fee, payment_token)
            base._send_funds(loan.lender, remaining_collateral_value - protocol_settlement_fee_amount, payment_token)
            base._send_funds(base.protocol_wallet, protocol_settlement_fee_amount, payment_token)
            base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, remaining_collateral_value)
        else:
            base._transfer_funds(liquidator, base.protocol_wallet, protocol_settlement_fee_amount, payment_token)

        base._send_funds(liquidator, liquidation_fee, payment_token)
        base._send_collateral(liquidator, remaining_collateral, _vault)

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
