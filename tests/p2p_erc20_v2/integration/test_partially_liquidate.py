import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    PartialLiquidationResult,
    calc_collateral_from_ltv,
    calc_ltv,
    calc_partial_liquidation,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000
DAY = 86400


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
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=int(0.5e18),
        max_iltv=5000,
        available_liquidity=principal,
        call_eligibility=1 * DAY,
        call_window=1 * DAY,
        liquidation_ltv=6000,
        oracle_addr=oracle_usdc_eth.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\1",
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
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    initial_ltv = calc_ltv(principal, collateral_amount, usdc, weth, oracle_usdc_eth, oracle_reverse=True)

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
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_weth.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=initial_ltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def disabled_test_partial_liquidate(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, oracle_usdc_eth, usdc, now):
    liquidator = boa.env.generate_address("liquidator")
    loan = ongoing_loan_usdc_weth
    oracle_usdc_eth.set_rate(oracle_usdc_eth.rate() // 3, sender=oracle_usdc_eth.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle_usdc_eth)
    assert current_ltv > loan.liquidation_ltv

    principal_written_off, collateral_claimed, liquidation_fee = calc_partial_liquidation(
        loan, usdc, weth, oracle_usdc_eth, now, oracle_reverse=False
    )

    lender_balance_before = weth.balanceOf(loan.lender)
    protocol_balance_before = weth.balanceOf(p2p_usdc_weth.address)
    liquidator_fee_before = weth.balanceOf(loan.borrower)

    p2p_usdc_weth.partially_liquidate_loan(loan, sender=liquidator)
    event = get_last_event(p2p_usdc_weth, "LoanPartiallyLiquidated")

    updated_loan = replace_namedtuple_field(
        loan,
        collateral_amount=loan.collateral_amount - collateral_claimed,
        amount=loan.amount + loan.get_interest(now) - principal_written_off,
        accrual_start_time=now,
    )
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(loan.id)

    assert event.id == loan.id
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.written_off == principal_written_off
    assert event.collateral_claimed == collateral_claimed
    assert event.liquidation_fee == liquidation_fee
    assert event.updated_amount == loan.amount + loan.get_interest(now) - principal_written_off
    assert event.updated_collateral_amount == loan.collateral_amount - collateral_claimed
    assert event.updated_accrual_start_time == now
    assert event.liquidator == liquidator
    assert event.old_ltv == current_ltv
    assert event.new_ltv == calc_ltv(
        event.updated_amount, event.updated_collateral_amount, usdc, weth, oracle_usdc_eth, oracle_reverse=False
    )

    assert weth.balanceOf(p2p_usdc_weth.address) == protocol_balance_before - collateral_claimed
    assert weth.balanceOf(loan.lender) == lender_balance_before + collateral_claimed - liquidation_fee
    assert weth.balanceOf(liquidator) == liquidator_fee_before + liquidation_fee
