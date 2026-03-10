import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    calc_ltv,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
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
    principal = 50 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=acred.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=4000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=6000,
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
    get_last_event(p2p_usdc_acred, "LoanCreated")

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


def test_add_collateral_to_loan(p2p_usdc_acred, ongoing_loan_usdc_acred, acred, usdc, oracle_acred_usd):
    collateral_amount = ongoing_loan_usdc_acred.collateral_amount
    additional_collateral = 1000
    borrower = ongoing_loan_usdc_acred.borrower
    vault_id = ongoing_loan_usdc_acred.vault_id

    # Securitize: approve the specific vault for this loan
    vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, vault_id)
    acred.approve(vault_addr, additional_collateral, sender=borrower)
    borrower_balance_before = acred.balanceOf(ongoing_loan_usdc_acred.borrower)

    p2p_usdc_acred.add_collateral_to_loan(ongoing_loan_usdc_acred, additional_collateral, sender=borrower)
    event = get_last_event(p2p_usdc_acred, "LoanCollateralAdded")

    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_acred, collateral_amount=collateral_amount + additional_collateral
    )
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_acred.loans(ongoing_loan_usdc_acred.id)

    old_ltv = calc_ltv(
        ongoing_loan_usdc_acred.amount,
        collateral_amount,
        usdc,
        acred,
        oracle_acred_usd,
        oracle_reverse=False,
    )
    new_ltv = calc_ltv(
        ongoing_loan_usdc_acred.amount,
        collateral_amount + additional_collateral,
        usdc,
        acred,
        oracle_acred_usd,
        oracle_reverse=False,
    )
    assert event.id == ongoing_loan_usdc_acred.id
    assert event.borrower == ongoing_loan_usdc_acred.borrower
    assert event.lender == ongoing_loan_usdc_acred.lender
    assert event.collateral_token == ongoing_loan_usdc_acred.collateral_token
    assert event.old_collateral_amount == collateral_amount
    assert event.new_collateral_amount == collateral_amount + additional_collateral
    assert event.old_ltv == old_ltv
    assert event.new_ltv == new_ltv

    # Securitize: use vault_id_to_vault for the correct vault
    assert acred.balanceOf(vault_addr) == collateral_amount + additional_collateral
    assert acred.balanceOf(borrower) == borrower_balance_before - additional_collateral
