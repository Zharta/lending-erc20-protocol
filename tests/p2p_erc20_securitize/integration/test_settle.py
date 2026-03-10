import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    SignedRedeemResult,
    compute_liquidity_key,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
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
def protocol_fees(p2p_usdc_acred):
    settlement_fee = 1000
    upfront_fee = 11
    p2p_usdc_acred.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_acred.owner())
    p2p_usdc_acred.change_protocol_wallet(p2p_usdc_acred.owner(), sender=p2p_usdc_acred.owner())
    return settlement_fee


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def offer_usdc_acred(now, borrower, lender, oracle_acred_usd, lender_key, usdc, acred, p2p_usdc_acred):
    principal = 100 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=acred.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle_acred_usd.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    return sign_offer(offer, lender_key, p2p_usdc_acred.address)


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

    # Get the vault_id before loan creation
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


def test_settle_loan_non_redeemed(p2p_usdc_acred, ongoing_loan_usdc_acred, usdc, acred, now):
    """For Securitize non-redeemed loans, collateral stays in vault after settlement."""
    loan = ongoing_loan_usdc_acred
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 365 * 10000)
    amount_to_settle = loan.amount + interest
    protocol_fee_amount = interest * loan.protocol_settlement_fee // 10000
    amount_to_receive = loan.amount + interest - protocol_fee_amount
    initial_lender_balance = usdc.balanceOf(loan.lender)
    liquidity_key = compute_liquidity_key(loan.lender, ongoing_loan_usdc_acred.offer_tracing_id)

    usdc.approve(p2p_usdc_acred.address, amount_to_settle, sender=loan.borrower)

    initial_borrower_balance = usdc.balanceOf(ongoing_loan_usdc_acred.borrower)
    offer_liquidity_before = p2p_usdc_acred.commited_liquidity(liquidity_key)
    borrower_balance_before = acred.balanceOf(loan.borrower)
    vault_addr = p2p_usdc_acred.vault_id_to_vault(loan.borrower, loan.vault_id)
    vault_balance_before = acred.balanceOf(vault_addr)
    initial_protocol_wallet_balance = usdc.balanceOf(p2p_usdc_acred.protocol_wallet())

    p2p_usdc_acred.settle_loan(loan, SignedRedeemResult(), sender=loan.borrower)
    event = get_last_event(p2p_usdc_acred, "LoanPaid")

    assert p2p_usdc_acred.loans(loan.id) == ZERO_BYTES32

    assert event.id == loan.id
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.payment_token == loan.payment_token
    assert event.paid_principal == loan.amount
    assert event.paid_interest == interest
    assert event.origination_fee_amount == loan.origination_fee_amount
    assert event.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert event.protocol_settlement_fee_amount == protocol_fee_amount
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == offer_liquidity_before - loan.amount

    assert usdc.balanceOf(p2p_usdc_acred.address) == 0
    assert usdc.balanceOf(ongoing_loan_usdc_acred.borrower) == initial_borrower_balance - amount_to_settle
    assert usdc.balanceOf(loan.lender) == initial_lender_balance + amount_to_receive
    assert usdc.balanceOf(p2p_usdc_acred.protocol_wallet()) == initial_protocol_wallet_balance + protocol_fee_amount

    # Securitize: for non-redeemed loans, collateral stays in vault
    assert acred.balanceOf(vault_addr) == vault_balance_before
    assert acred.balanceOf(loan.borrower) == borrower_balance_before
