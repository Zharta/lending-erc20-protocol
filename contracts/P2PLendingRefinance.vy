# @version 0.4.3

"""
@title P2PLendingErc20
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.

"""

from contracts import P2PLendingBase as base

initializes: base
exports: base.__interface__

# Interfaces

from ethereum.ercs import IERC721
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed


# Structs

event LoanReplaced:
    id: bytes32
    amount: uint256
    apr: uint256
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    soft_liquidation_ltv: uint256
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    soft_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32
    original_loan_id: bytes32
    paid_principal: uint256
    paid_interest: uint256
    paid_protocol_settlement_fee_amount: uint256

event LoanReplacedByLender:
    id: bytes32
    amount: uint256
    apr: uint256
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    soft_liquidation_ltv: uint256
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    soft_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32
    original_loan_id: bytes32
    paid_principal: uint256
    paid_interest: uint256
    paid_protocol_settlement_fee_amount: uint256


# Constants

BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

VERSION: public(constant(String[30])) = "P2PLendingRefinance.20251001"



@deploy
def __init__(
    _payment_token: address,
    _collateral_token: address,
    _oracle_addr: address,
    _oracle_reverse: bool,
    _kyc_validator_addr: address,
    _protocol_upfront_fee: uint256,
    _protocol_settlement_fee: uint256,
    _protocol_wallet: address,
    _max_protocol_upfront_fee: uint256,
    _max_protocol_settlement_fee: uint256,
    _soft_liquidation_fee: uint256,
):

    """
    @notice Initialize the contract with the given parameters.
    @param _payment_token The address of the payment token.
    @param _collateral_token The address of the collateral token.
    @param _oracle_addr The address of the oracle contract for collateral valuation.
    @param _oracle_reverse Whether the oracle returns the collateral price in reverse (i.e., 1 / price).
    @param _protocol_upfront_fee The percentage (bps) of the principal paid to the protocol at origination.
    @param _protocol_settlement_fee The percentage (bps) of the interest paid to the protocol at settlement.
    @param _protocol_wallet The address where the protocol fees are accrued.
    @param _max_protocol_upfront_fee The maximum percentage (bps) of the principal that can be charged as protocol upfront fee.
    @param _max_protocol_settlement_fee The maximum percentage (bps) of the interest that can be charged as protocol settlement fee.
    @param _soft_liquidation_fee The percentage (bps) of the principal that is charged as a liquidation fee when a loan is soft liquidated.

    @dev This requires a P2PLendingRefinance deployment for each base contract.
    @dev TODO: Eval alternative impl so the P2PLendingRefinance could be shared: initialize the base module with empty data, add the relevant data to the methods signatures and appended it to the calldata in the delegatecall from the main contract.
    """

    base.__init__(
    _payment_token,
    _collateral_token,
    _oracle_addr,
    _oracle_reverse,
    _kyc_validator_addr,
    _protocol_upfront_fee,
    _protocol_settlement_fee,
    _protocol_wallet,
    _max_protocol_upfront_fee,
    _max_protocol_settlement_fee,
    _soft_liquidation_fee,
    )



# Config functions

@external
def replace_loan(
    loan: base.Loan,
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:

    """
    @notice Replace an existing loan by accepting a new offer over the same collateral. The current loan is settled and the new loan is created. Must be called by the borrower.
    @dev No collateral transfer is required. The borrower must be the same as the borrower of the current loan.
    @param loan The loan to be replaced.
    @param offer The new signed offer.
    @param principal The principal amount of the new loan, 0 means the outstanding debt
    @param collateral_amount The amount of collateral tokens to be used for the new loan.
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the new loan.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._check_user(loan.borrower), "not borrower"
    assert not base._is_loan_defaulted(loan), "loan defaulted"

    assert base._is_offer_signed_by_lender(offer), "offer not signed by lender"
    base._check_offer_validity(offer)

    self._validate_kyc(lender_kyc, offer.offer.lender)
    assert offer.offer.borrower == empty(address) or offer.offer.borrower == loan.borrower, "borrower not allowed"
    assert offer.offer.min_collateral_amount <= collateral_amount, "low collateral amount"
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"

    interest: uint256 = base._compute_settlement_interest(loan)
    protocol_settlement_fee: uint256 = loan.protocol_settlement_fee * interest // BPS
    outstanding_debt: uint256 = loan.amount + interest
    new_principal: uint256 = outstanding_debt if principal == 0 else principal
    assert offer.offer.principal == 0 or offer.offer.principal == new_principal, "offer principal mismatch"

    convertion_rate: base.UInt256Rational = base._get_oracle_rate()

    max_initial_ltv: uint256 = offer.offer.max_iltv
    if offer.offer.max_iltv == 0:
        max_initial_ltv = base._compute_ltv(offer.offer.min_collateral_amount, new_principal, convertion_rate)

    initial_ltv: uint256 = base._compute_ltv(collateral_amount, new_principal, convertion_rate)
    assert initial_ltv <= max_initial_ltv, "initial ltv gt max iltv"

    if offer.offer.soft_liquidation_ltv > 0:
        assert offer.offer.soft_liquidation_ltv > max_initial_ltv, "liquidation ltv le initial ltv"
        # required for soft liquidation: (1 + f) * iltv < 1
        assert (BPS + base.soft_liquidation_fee) * max_initial_ltv < BPS * BPS, "initial ltv too high"

    offer_id: bytes32 = base._compute_signed_offer_id(offer)
    new_loan: base.Loan = base.Loan(
        id=empty(bytes32),
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        initial_amount=new_principal,
        amount=new_principal,
        apr=offer.offer.apr,
        payment_token=offer.offer.payment_token,
        maturity=block.timestamp + offer.offer.duration,
        start_time=block.timestamp,
        accrual_start_time=block.timestamp,
        borrower=loan.borrower,
        lender=offer.offer.lender,
        collateral_token=base.collateral_token,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.offer.min_collateral_amount,
        origination_fee_amount=offer.offer.origination_fee_bps * new_principal // BPS,
        protocol_upfront_fee_amount=base.protocol_upfront_fee * new_principal // BPS,
        protocol_settlement_fee=base.protocol_settlement_fee,
        soft_liquidation_fee=base.soft_liquidation_fee,
        call_eligibility=offer.offer.call_eligibility,
        call_window=offer.offer.call_window,
        soft_liquidation_ltv=offer.offer.soft_liquidation_ltv,
        oracle_addr=base.oracle_addr,
        initial_ltv=max_initial_ltv,
        call_time=0,
    )
    new_loan.id = base._compute_loan_id(new_loan)
    assert base.loans[new_loan.id] == empty(bytes32), "loan already exists"

    base.loans[loan.id] = empty(bytes32)
    base._reduce_commited_liquidity(loan.offer_tracing_id, loan.amount)

    base._check_and_update_offer_state(offer, new_principal)
    base.loans[new_loan.id] = base._loan_state_hash(new_loan)

    if collateral_amount > loan.collateral_amount:
        base._receive_collateral(loan.borrower, collateral_amount - loan.collateral_amount)
    elif collateral_amount < loan.collateral_amount:
        base._send_collateral(loan.borrower, loan.collateral_amount - collateral_amount)


    borrower_delta: int256 = convert(new_principal, int256) - convert(outstanding_debt + new_loan.origination_fee_amount, int256)
    old_lender_delta: uint256 = outstanding_debt - protocol_settlement_fee
    new_lender_delta: int256 = convert(new_loan.origination_fee_amount, int256) - convert(new_loan.amount + new_loan.protocol_upfront_fee_amount, int256)
    if borrower_delta < 0:
        base._receive_funds(loan.borrower, convert(-borrower_delta, uint256))

    if loan.lender == offer.offer.lender:
        lender_delta: int256 = convert(old_lender_delta, int256) + new_lender_delta
        if lender_delta < 0:
            base._receive_funds(loan.lender, convert(-lender_delta, uint256))
        elif lender_delta > 0:
            base._send_funds(loan.lender, convert(lender_delta, uint256))
    else:
        if new_lender_delta < 0:
            base._receive_funds(new_loan.lender, convert(-new_lender_delta, uint256))
        if old_lender_delta > 0:
            base._send_funds(loan.lender, old_lender_delta)

    if borrower_delta > 0:
        base._send_funds(loan.borrower, convert(borrower_delta, uint256))


    if protocol_settlement_fee + new_loan.protocol_upfront_fee_amount > 0:
        base._send_funds(base.protocol_wallet, protocol_settlement_fee + new_loan.protocol_upfront_fee_amount)

    log LoanReplaced(
        id=new_loan.id,
        amount=new_loan.initial_amount,
        apr=new_loan.apr,
        maturity=new_loan.maturity,
        start_time=new_loan.start_time,
        borrower=new_loan.borrower,
        lender=new_loan.lender,
        collateral_amount=new_loan.collateral_amount,
        min_collateral_amount=new_loan.min_collateral_amount,
        call_eligibility=new_loan.call_eligibility,
        call_window=new_loan.call_window,
        soft_liquidation_ltv=new_loan.soft_liquidation_ltv,
        initial_ltv=new_loan.initial_ltv,
        origination_fee_amount=new_loan.origination_fee_amount,
        protocol_upfront_fee_amount=new_loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=new_loan.protocol_settlement_fee,
        soft_liquidation_fee=new_loan.soft_liquidation_fee,
        offer_id=new_loan.offer_id,
        offer_tracing_id=new_loan.offer_tracing_id,
        original_loan_id=loan.id,
        paid_principal=loan.amount,
        paid_interest=interest,
        paid_protocol_settlement_fee_amount=protocol_settlement_fee
    )

    return new_loan.id


@external
def replace_loan_lender(
    loan: base.Loan,
    offer: base.SignedOffer,
    principal: uint256,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:

    """
    @notice Replace an existing loan by accepting a new offer over the same collateral. The current loan is settled and the new loan is created. Must be called by the borrower.
    @dev No collateral transfer is required. The borrower must be the same as the borrower of the current loan.
    @param loan The loan to be replaced.
    @param offer The new signed offer.
    @param principal The principal amount of the new loan, 0 means the outstanding debt
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the new loan.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._check_user(loan.lender), "not lender"
    assert not base._is_loan_defaulted(loan), "loan defaulted"

    assert base._is_offer_signed_by_lender(offer), "offer not signed by lender"
    base._check_offer_validity(offer)
    self._validate_kyc(lender_kyc, offer.offer.lender)

    assert offer.offer.borrower == empty(address) or offer.offer.borrower == loan.borrower, "borrower not allowed"
    assert offer.offer.min_collateral_amount <= loan.collateral_amount, "low collateral amount"
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"

    interest: uint256 = base._compute_settlement_interest(loan)
    protocol_settlement_fee: uint256 = loan.protocol_settlement_fee * interest // BPS
    outstanding_debt: uint256 = loan.amount + interest
    new_principal: uint256 = outstanding_debt if principal == 0 else principal
    assert offer.offer.principal == 0 or offer.offer.principal == new_principal, "offer principal mismatch"

    convertion_rate: base.UInt256Rational = base._get_oracle_rate()

    max_initial_ltv: uint256 = offer.offer.max_iltv
    if offer.offer.max_iltv == 0:
        max_initial_ltv = base._compute_ltv(offer.offer.min_collateral_amount, new_principal, convertion_rate)

    current_ltv: uint256 = base._compute_ltv(loan.collateral_amount, loan.amount, convertion_rate)
    initial_ltv: uint256 = base._compute_ltv(loan.collateral_amount, new_principal, convertion_rate)
    assert initial_ltv <= max_initial_ltv, "initial ltv gt max iltv"

    if offer.offer.soft_liquidation_ltv > 0:
        assert offer.offer.soft_liquidation_ltv > max_initial_ltv, "liquidation ltv le initial ltv"
        # required for soft liquidation: (1 + f) * iltv < 1
        assert (BPS + base.soft_liquidation_fee) * max_initial_ltv < BPS * BPS, "initial ltv too high"

    offer_id: bytes32 = base._compute_signed_offer_id(offer)
    new_loan: base.Loan = base.Loan(
        id=empty(bytes32),
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        initial_amount=new_principal,
        amount=new_principal,
        apr=offer.offer.apr,
        payment_token=offer.offer.payment_token,
        maturity=block.timestamp + offer.offer.duration,
        start_time=block.timestamp,
        accrual_start_time=block.timestamp,
        borrower=loan.borrower,
        lender=offer.offer.lender,
        collateral_token=base.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=offer.offer.min_collateral_amount,
        origination_fee_amount=offer.offer.origination_fee_bps * new_principal // BPS,
        protocol_upfront_fee_amount=base.protocol_upfront_fee * new_principal // BPS,
        protocol_settlement_fee=base.protocol_settlement_fee,
        soft_liquidation_fee=base.soft_liquidation_fee,
        call_eligibility=offer.offer.call_eligibility,
        call_window=offer.offer.call_window,
        soft_liquidation_ltv=offer.offer.soft_liquidation_ltv,
        oracle_addr=base.oracle_addr,
        initial_ltv=max_initial_ltv,
        call_time=0,
    )
    new_loan.id = base._compute_loan_id(new_loan)
    assert base.loans[new_loan.id] == empty(bytes32), "loan already exists"

    # New loan earlier repayment date must be equal or higher than current loan earlier repayment date
    # Net repayment must be equal or lower during period
    # New Loan LTV must be equal or lower than New Loan Max LTV
    # Loan LLTV <= New Loan LLTV (if applicable)
    # Call window <= New Loan Call windown (if applicable)
    # Call Eligilibity - Actual maturity <= New Call Eligibility
    # Max LTV <= New Loan Max LTV
    # Loan LTV >= New Loan LTV if there is Liquidation

    repayment_time_old_loan: uint256 = self._get_repayment_time(loan)
    repayment_time_new_loan: uint256 = self._get_repayment_time(new_loan)
    assert repayment_time_new_loan >= repayment_time_old_loan, "repayment time lt old loan"
    assert repayment_time_new_loan * new_loan.apr * new_loan.amount <= repayment_time_old_loan * loan.apr * loan.amount, "repayment amount gt old loan"
    if new_loan.soft_liquidation_ltv > 0:
        assert new_loan.soft_liquidation_ltv >= loan.soft_liquidation_ltv, "liquidation ltv lt old loan"
    if loan.call_eligibility > 0 and new_loan.call_eligibility > 0:
        assert new_loan.call_window >= loan.call_window, "call window lt old loan"
    assert new_loan.initial_ltv >= loan.initial_ltv, "max iltv lt old loan"
    if new_loan.soft_liquidation_ltv > 0:
        assert initial_ltv <= current_ltv, "initial ltv gt old loan"

    base.loans[loan.id] = empty(bytes32)
    base._reduce_commited_liquidity(loan.offer_tracing_id, loan.amount)

    base._check_and_update_offer_state(offer, new_principal)
    base.loans[new_loan.id] = base._loan_state_hash(new_loan)


    borrower_delta: int256 = convert(new_principal, int256) - convert(outstanding_debt + new_loan.origination_fee_amount, int256)
    old_lender_delta: int256 = convert(outstanding_debt - protocol_settlement_fee, int256)
    new_lender_delta: int256 = convert(new_loan.origination_fee_amount, int256) - convert(new_loan.amount + new_loan.protocol_upfront_fee_amount, int256)
    if borrower_delta < 0:
        old_lender_delta += borrower_delta
        borrower_delta = 0

    if loan.lender == offer.offer.lender:
        lender_delta: int256 = old_lender_delta + new_lender_delta
        if lender_delta < 0:
            base._receive_funds(loan.lender, convert(-lender_delta, uint256))
        elif lender_delta > 0:
            base._send_funds(loan.lender, convert(lender_delta, uint256))
    else:
        if new_lender_delta < 0:
            base._receive_funds(new_loan.lender, convert(-new_lender_delta, uint256))
        if old_lender_delta < 0:
            base._receive_funds(loan.lender, convert(-old_lender_delta, uint256))
        if old_lender_delta > 0:
            base._send_funds(loan.lender, convert(old_lender_delta, uint256))

    if borrower_delta > 0:
        base._send_funds(loan.borrower, convert(borrower_delta, uint256))


    if protocol_settlement_fee + new_loan.protocol_upfront_fee_amount > 0:
        base._send_funds(base.protocol_wallet, protocol_settlement_fee + new_loan.protocol_upfront_fee_amount)

    log LoanReplacedByLender(
        id=new_loan.id,
        amount=new_loan.initial_amount,
        apr=new_loan.apr,
        maturity=new_loan.maturity,
        start_time=new_loan.start_time,
        borrower=new_loan.borrower,
        lender=new_loan.lender,
        collateral_amount=new_loan.collateral_amount,
        min_collateral_amount=new_loan.min_collateral_amount,
        call_eligibility=new_loan.call_eligibility,
        call_window=new_loan.call_window,
        soft_liquidation_ltv=new_loan.soft_liquidation_ltv,
        initial_ltv=new_loan.initial_ltv,
        origination_fee_amount=new_loan.origination_fee_amount,
        protocol_upfront_fee_amount=new_loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=new_loan.protocol_settlement_fee,
        soft_liquidation_fee=new_loan.soft_liquidation_fee,
        offer_id=new_loan.offer_id,
        offer_tracing_id=new_loan.offer_tracing_id,
        original_loan_id=loan.id,
        paid_principal=loan.amount,
        paid_interest=interest,
        paid_protocol_settlement_fee_amount=protocol_settlement_fee
    )

    return new_loan.id




# Internal functions

@view
@internal
def _get_repayment_time(loan: base.Loan) -> uint256:
    if loan.call_eligibility == 0:
        return loan.maturity
    elif loan.call_time > 0:
        return min(loan.maturity,loan.call_time + loan.call_window)
    else:
        return min(loan.maturity, max(block.timestamp, loan.start_time + loan.call_eligibility) + loan.call_window)

@view
@internal
def _validate_kyc(validation: base.SignedWalletValidation, wallet: address):
    assert (staticcall base.KYCValidator(base.kyc_validator_addr).check_validation(validation) and validation.validation.wallet == wallet), "KYC validation fail"
