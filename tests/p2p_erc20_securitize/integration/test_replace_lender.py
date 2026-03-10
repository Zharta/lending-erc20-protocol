import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    compute_liquidity_key,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
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
def protocol_fees(p2p_usdc_acred):
    settlement_fee = 1000
    upfront_fee = 11
    p2p_usdc_acred.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_acred.owner())
    p2p_usdc_acred.change_protocol_wallet(p2p_usdc_acred.owner(), sender=p2p_usdc_acred.owner())
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
def offer_usdc_acred(now, borrower, lender, oracle_acred_usd, lender_key, usdc, acred, p2p_usdc_acred):
    principal = 100 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=acred.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=9000,
        oracle_addr=oracle_acred_usd.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\1",
    )
    return sign_offer(offer, lender_key, p2p_usdc_acred.address)


@pytest.fixture
def offer_usdc_acred2(now, borrower, lender2, oracle_acred_usd, lender2_key, usdc, acred, p2p_usdc_acred):
    principal = 100 * 10**6
    offer = Offer(
        principal=principal,
        apr=500,
        payment_token=usdc.address,
        collateral_token=acred.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle_acred_usd.address,
        expiration=now + 30 * DAY,
        lender=lender2,
        borrower=borrower,
        tracing_id=32 * b"\2",
    )
    return sign_offer(offer, lender2_key, p2p_usdc_acred.address)


@pytest.fixture
def ongoing_loan_usdc_acred(
    p2p_usdc_acred,
    offer_usdc_acred,
    usdc,
    acred,
    borrower,
    lender,
    lender_key,
    now,
    protocol_fees,
    kyc_borrower,
    kyc_lender,
    oracle_acred_usd,
):
    offer = offer_usdc_acred.offer
    principal = offer.principal
    collateral_amount = 20 * int(1e6)
    lender_approval = principal + (p2p_usdc_acred.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    # Get vault_id before loan creation
    vault_id = p2p_usdc_acred.vault_count(borrower)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_acred.create_loan(
        offer_usdc_acred, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )

    loan = SecuritizeLoan(
        id=loan_id,
        offer_id=compute_signed_offer_id(offer_usdc_acred),
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
        protocol_upfront_fee_amount=p2p_usdc_acred.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_acred.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acred.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)
    return loan


def _max_interest_delta(loan: SecuritizeLoan, offer: Offer, new_principal: int, refinance_timestamp: int):
    assert refinance_timestamp >= loan.start_time
    assert refinance_timestamp <= loan.maturity

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
    borrower_compensation = max(max_interest_delta, origination_fee_amount - new_principal + outstanding_debt)

    delta_borrower = new_principal - outstanding_debt - origination_fee_amount + borrower_compensation
    delta_lender = outstanding_debt - protocol_settlement_fee - borrower_compensation
    delta_new_lender = origination_fee_amount - new_principal - protocol_fee_amount
    delta_protocol = protocol_settlement_fee + protocol_fee_amount

    return delta_borrower, delta_lender, delta_new_lender, delta_protocol


def test_replace_loan_lender(
    p2p_usdc_acred, ongoing_loan_usdc_acred, usdc, acred, now, offer_usdc_acred2, kyc_lender2, lender2, oracle_acred_usd
):
    loan = ongoing_loan_usdc_acred
    offer = offer_usdc_acred2.offer
    replace_timestamp = now + 1 * DAY
    delta_borrower, delta_lender, delta_new_lender, protocol_delta = _calc_deltas(
        loan, offer, offer.principal, replace_timestamp, p2p_usdc_acred
    )

    # Securitize: get the vault address for this loan
    vault_addr = p2p_usdc_acred.vault_id_to_vault(loan.borrower, loan.vault_id)

    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_acred.address, -delta_new_lender, sender=lender2)

    liquidity1_key = compute_liquidity_key(ongoing_loan_usdc_acred.lender, ongoing_loan_usdc_acred.offer_tracing_id)
    liquidity2_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    offer1_liquidity_before = p2p_usdc_acred.commited_liquidity(liquidity1_key)
    offer2_liquidity_before = p2p_usdc_acred.commited_liquidity(liquidity2_key)
    initial_borrower_collateral = acred.balanceOf(loan.borrower)
    initial_vault_collateral = acred.balanceOf(vault_addr)
    initial_borrower_balance = usdc.balanceOf(loan.borrower)
    initial_lender_balance = usdc.balanceOf(loan.lender)
    initial_new_lender_balance = usdc.balanceOf(lender2)
    initial_protocol_wallet_balance = usdc.balanceOf(p2p_usdc_acred.protocol_wallet())

    boa.env.time_travel(seconds=replace_timestamp - now)
    new_loan_id = p2p_usdc_acred.replace_loan_lender(loan, offer_usdc_acred2, offer.principal, kyc_lender2, sender=loan.lender)  # noqa: F841

    assert p2p_usdc_acred.loans(loan.id) == ZERO_BYTES32
    assert usdc.balanceOf(p2p_usdc_acred.address) == 0

    assert p2p_usdc_acred.commited_liquidity(liquidity1_key) == offer1_liquidity_before - loan.amount
    assert p2p_usdc_acred.commited_liquidity(liquidity2_key) == offer2_liquidity_before + offer.principal

    # Securitize: collateral stays in the same vault
    assert acred.balanceOf(vault_addr) == initial_vault_collateral
    assert acred.balanceOf(loan.borrower) == initial_borrower_collateral

    assert usdc.balanceOf(loan.borrower) == initial_borrower_balance + delta_borrower
    assert usdc.balanceOf(loan.lender) == initial_lender_balance + delta_lender
    assert usdc.balanceOf(lender2) == initial_new_lender_balance + delta_new_lender

    assert protocol_delta > 0
    assert usdc.balanceOf(p2p_usdc_acred.protocol_wallet()) == initial_protocol_wallet_balance + protocol_delta
