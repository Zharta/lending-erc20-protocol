from textwrap import dedent

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    SignedOffer,
    calc_ltv,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000
DAY = 86400
MAX_UINT256 = 2**256 - 1


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e11))


@pytest.fixture(autouse=True)
def lender2_funds(lender2, usdc, owner):
    usdc.transfer(lender2, int(1e11))


@pytest.fixture(autouse=True)
def borrower_funds(borrower, usdc):
    usdc.transfer(borrower, int(1e11))


@pytest.fixture
def protocol_fees(p2p_usdc_weth):
    settlement_fee = 1000
    upfront_fee = 11
    p2p_usdc_weth.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_weth.owner())
    p2p_usdc_weth.change_protocol_wallet(p2p_usdc_weth.owner(), sender=p2p_usdc_weth.owner())
    return settlement_fee


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender, kyc_validator_contract.address, expiration=now + 365 * DAY)


@pytest.fixture(autouse=True)
def kyc_lender2(lender2, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender2, kyc_validator_contract.address, expiration=now + 365 * DAY)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract, now):
    return kyc_for(borrower, kyc_validator_contract.address, expiration=now + 365 * DAY)


@pytest.fixture
def offer_usdc_weth(now, borrower, lender, oracle_usdc_eth, lender_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=1 * DAY,
        call_window=1 * DAY,
        soft_liquidation_ltv=9000,
        oracle_addr=oracle_usdc_eth.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\1",
    )
    return sign_offer(offer, lender_key, p2p_usdc_weth.address)


@pytest.fixture
def offer_usdc_weth2(now, borrower, lender2, oracle_usdc_eth, lender2_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=500,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle_usdc_eth.address,
        expiration=now + 30 * DAY,
        lender=lender2,
        borrower=borrower,
        tracing_id=32 * b"\2",
    )
    return sign_offer(offer, lender2_key, p2p_usdc_weth.address)


@pytest.fixture
def ongoing_loan_usdc_weth(
    p2p_usdc_weth,
    offer_usdc_weth,
    usdc,
    weth,
    borrower,
    lender,
    lender_key,
    now,
    protocol_fees,
    kyc_borrower,
    kyc_lender,
    oracle_usdc_eth,
):
    offer = offer_usdc_weth.offer
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.address, collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_weth, "LoanCreated")

    loan = Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(offer_usdc_weth),
        offer_tracing_id=offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.apr,
        payment_token=offer.payment_token,
        collateral_token=offer.collateral_token,
        maturity=now + offer.duration,
        start_time=now,
        accrual_start_time=now,
        borrower=borrower,
        lender=lender,
        collateral_amount=collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        soft_liquidation_fee=p2p_usdc_weth.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    print(event)
    print(loan)
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def _max_interest_delta(loan: Loan, offer: Offer, new_principal: int, refinance_timestamp: int):
    assert refinance_timestamp >= loan.start_time
    assert refinance_timestamp <= loan.maturity
    print(f"_max_interest_delta: {loan=}, {offer=}, {refinance_timestamp=}")

    loan_interest_delta_at_maturity = loan.amount * loan.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)
    offer_interest_at_loan_maturity = new_principal * offer.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)

    return max(0, offer_interest_at_loan_maturity - loan_interest_delta_at_maturity)


def _max_interest_delta(loan: Loan, offer: Offer, new_principal: int, refinance_timestamp: int):
    assert refinance_timestamp >= loan.start_time
    assert refinance_timestamp <= loan.maturity
    print(f"_max_interest_delta: {loan=}, {offer=}, {refinance_timestamp=}")
    print(
        f"_max_interest_delta: {loan.amount=} {loan.apr=} {new_principal=}, {offer.apr=} {loan.maturity=}, {refinance_timestamp=}"  # noqa: E501
    )  # noqa: E501

    loan_interest_delta_at_maturity = loan.amount * loan.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)
    offer_interest_at_loan_maturity = new_principal * offer.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)

    return max(0, offer_interest_at_loan_maturity - loan_interest_delta_at_maturity)


def _calc_deltas(loan, offer, principal, timestamp, contract) -> (int, int, int, int):
    interest = loan.amount * loan.apr * (timestamp - loan.accrual_start_time) // (365 * DAY * BPS)
    protocol_settlement_fee = interest * loan.protocol_settlement_fee // BPS
    outstanding_debt = loan.amount + interest
    new_principal = outstanding_debt if principal == 0 else principal
    origination_fee_amount = offer.origination_fee_bps * new_principal // BPS
    protocol_fee_amount = contract.protocol_upfront_fee() * new_principal // BPS

    max_interest_delta = _max_interest_delta(loan, offer, new_principal, timestamp)
    borrower_compensation = max(0, max_interest_delta + new_principal - outstanding_debt - origination_fee_amount)
    borrower_compensation = max(max_interest_delta, origination_fee_amount - new_principal + outstanding_debt)

    delta_borrower = new_principal - outstanding_debt - origination_fee_amount + borrower_compensation
    delta_lender = outstanding_debt - protocol_settlement_fee - borrower_compensation
    delta_new_lender = origination_fee_amount - new_principal - protocol_fee_amount
    delta_protocol = protocol_settlement_fee + protocol_fee_amount

    print(
        f"_calc_deltas {max_interest_delta=}, {borrower_compensation=} {delta_borrower=}, {delta_lender=}, {delta_new_lender=}, {delta_protocol=}"  # noqa: E501
    )  # noqa: E501
    return delta_borrower, delta_lender, delta_new_lender, delta_protocol


def test_replace_loan(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now, offer_usdc_weth2, kyc_lender2, lender2, oracle_usdc_eth
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    replace_timestamp = now + 1 * DAY
    delta_borrower, delta_lender, delta_new_lender, protocol_delta = _calc_deltas(
        loan, offer, offer.principal, replace_timestamp, p2p_usdc_weth
    )

    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    offer1_liquidity_before = p2p_usdc_weth.commited_liquidity(ongoing_loan_usdc_weth.offer_tracing_id)
    offer2_liquidity_before = p2p_usdc_weth.commited_liquidity(offer.tracing_id)
    initial_borrower_collateral = weth.balanceOf(loan.borrower)
    initial_protocol_collateral = weth.balanceOf(p2p_usdc_weth.address)
    initial_borrower_balance = usdc.balanceOf(loan.borrower)
    initial_lender_balance = usdc.balanceOf(loan.lender)
    initial_new_lender_balance = usdc.balanceOf(lender2)
    initial_protocol_wallet_balance = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    boa.env.time_travel(seconds=replace_timestamp - now)
    new_loan_id = p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, offer.principal, kyc_lender2, sender=loan.lender)  # noqa: F841
    # TODO: re-enable event checks once event parsing is fixed
    # event = get_last_event(p2p_usdc_weth, "LoanReplaced")

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert usdc.balanceOf(p2p_usdc_weth.address) == 0

    # assert event.id == new_loan_id
    # assert event.amount == offer.principal
    # assert event.apr == offer.apr
    # assert event.maturity == replace_timestamp + offer.duration
    # assert event.start_time == replace_timestamp
    # assert event.borrower == loan.borrower
    # assert event.lender == lender2
    # assert event.collateral_amount == new_collateral_amount
    # assert event.min_collateral_amount == offer.min_collateral_amount
    # assert event.call_eligibility == offer.call_eligibility
    # assert event.call_window == offer.call_window
    # assert event.soft_liquidation_ltv == offer.soft_liquidation_ltv
    # assert event.initial_ltv == offer.max_iltv
    # assert event.origination_fee_amount == offer.origination_fee_bps * offer.principal // BPS
    # assert event.protocol_upfront_fee_amount == p2p_usdc_weth.protocol_upfront_fee() * offer.principal // BPS
    # assert event.protocol_settlement_fee == p2p_usdc_weth.protocol_settlement_fee()
    # assert event.soft_liquidation_fee == p2p_usdc_weth.soft_liquidation_fee()
    # assert event.offer_id == compute_signed_offer_id(offer_usdc_weth2)
    # assert event.offer_tracing_id == offer.tracing_id
    # assert event.original_loan_id == loan.id
    # assert event.paid_principal == loan.amount
    # interest = loan.amount * loan.apr * (replace_timestamp - loan.accrual_start_time) // (365 * 86400 * 10000)
    # assert event.paid_interest == interest
    # assert event.paid_protocol_settlement_fee_amount == interest * loan.protocol_settlement_fee // 10000

    assert p2p_usdc_weth.commited_liquidity(ongoing_loan_usdc_weth.offer_tracing_id) == offer1_liquidity_before - loan.amount
    assert p2p_usdc_weth.commited_liquidity(offer.tracing_id) == offer2_liquidity_before + offer.principal

    assert weth.balanceOf(p2p_usdc_weth.address) == initial_protocol_collateral
    assert weth.balanceOf(loan.borrower) == initial_borrower_collateral

    assert usdc.balanceOf(loan.borrower) == initial_borrower_balance + delta_borrower
    assert usdc.balanceOf(loan.lender) == initial_lender_balance + delta_lender
    assert usdc.balanceOf(lender2) == initial_new_lender_balance + delta_new_lender

    assert protocol_delta > 0
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == initial_protocol_wallet_balance + protocol_delta
