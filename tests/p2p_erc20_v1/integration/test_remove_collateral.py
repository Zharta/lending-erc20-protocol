import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_collateral_from_ltv,
    calc_ltv,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e11))


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
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def offer_usdc_weth(now, borrower, lender, oracle_usdc_eth, lender_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=4000,
        available_liquidity=principal,
        call_eligibility=1,
        call_window=3600,
        liquidation_ltv=6000,
        oracle_addr=oracle_usdc_eth.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    return sign_offer(offer, lender_key, p2p_usdc_weth.address)


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
    weth.approve(p2p_usdc_weth, collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    get_last_event(p2p_usdc_weth, "LoanCreated")

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
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def test_remove_collateral_from_loan(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, usdc, oracle_usdc_eth):
    collateral_amount = ongoing_loan_usdc_weth.collateral_amount
    removed_collateral = 1000
    borrower = ongoing_loan_usdc_weth.borrower
    borrower_balance_before = weth.balanceOf(ongoing_loan_usdc_weth.borrower)

    p2p_usdc_weth.remove_collateral_from_loan(ongoing_loan_usdc_weth, removed_collateral, sender=borrower)
    event = get_last_event(p2p_usdc_weth, "LoanCollateralRemoved")

    updated_loan = replace_namedtuple_field(ongoing_loan_usdc_weth, collateral_amount=collateral_amount - removed_collateral)
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id)

    old_ltv = calc_ltv(ongoing_loan_usdc_weth.amount, collateral_amount, usdc, weth, oracle_usdc_eth, oracle_reverse=True)
    new_ltv = calc_ltv(
        ongoing_loan_usdc_weth.amount, collateral_amount - removed_collateral, usdc, weth, oracle_usdc_eth, oracle_reverse=True
    )
    assert event.id == ongoing_loan_usdc_weth.id
    assert event.borrower == ongoing_loan_usdc_weth.borrower
    assert event.lender == ongoing_loan_usdc_weth.lender
    assert event.collateral_token == ongoing_loan_usdc_weth.collateral_token
    assert event.old_collateral_amount == collateral_amount
    assert event.new_collateral_amount == collateral_amount - removed_collateral
    assert event.old_ltv == old_ltv
    assert event.new_ltv == new_ltv

    assert weth.balanceOf(p2p_usdc_weth) == collateral_amount - removed_collateral
    assert weth.balanceOf(ongoing_loan_usdc_weth.borrower) == borrower_balance_before + removed_collateral
