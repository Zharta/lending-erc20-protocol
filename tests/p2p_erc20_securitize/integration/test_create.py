import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    calc_ltv,
    compute_liquidity_key,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    sign_offer,
)

BPS = 10000


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


def test_create_loan(
    p2p_usdc_acred, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, acred, usdc, oracle_acred_usd
):
    principal = 1000 * int(1e9)
    collateral_amount = 95 * int(1e6)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_acred.payment_token(),
        collateral_token=p2p_usdc_acred.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acred.address)

    # Get the vault_id before loan creation (this will be the vault_id used)
    vault_id = p2p_usdc_acred.vault_count(borrower)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    borrower_collateral_balance_before = acred.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    loan_id = p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_acred, "LoanCreated")
    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, acred, oracle_acred_usd, oracle_reverse=False)

    loan = SecuritizeLoan(
        id=loan_id,
        offer_id=compute_signed_offer_id(signed_offer),
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
        protocol_upfront_fee_amount=p2p_usdc_acred.protocol_upfront_fee(),
        protocol_settlement_fee=p2p_usdc_acred.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acred.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_acred.oracle_addr(),
        initial_ltv=initial_ltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)

    # event assertions
    assert event.id == loan_id
    assert event.amount == principal
    assert event.apr == offer.apr
    assert event.payment_token == offer.payment_token
    assert event.maturity == now + offer.duration
    assert event.start_time == now
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_token == offer.collateral_token
    assert event.collateral_amount == collateral_amount
    assert event.call_eligibility == offer.call_eligibility
    assert event.call_window == offer.call_window
    assert event.liquidation_ltv == offer.liquidation_ltv
    assert event.oracle_addr == p2p_usdc_acred.oracle_addr()
    assert event.initial_ltv == initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_acred.protocol_upfront_fee()
    assert event.protocol_settlement_fee == p2p_usdc_acred.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_acred.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    # Securitize: use vault_id_to_vault to get the correct vault address
    assert acred.balanceOf(p2p_usdc_acred.vault_id_to_vault(borrower, vault_id)) == collateral_amount
    assert acred.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal


def test_create_loan_registers_vault_with_registrar(
    p2p_usdc_acred,
    borrower,
    now,
    lender,
    lender_key,
    kyc_borrower,
    kyc_lender,
    acred,
    usdc,
    oracle_acred_usd,
    vault_registrar,
):
    vault_id = p2p_usdc_acred.vault_count(borrower)

    principal = 1000 * int(1e9)
    collateral_amount = 95 * int(1e6)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_acred.payment_token(),
        collateral_token=p2p_usdc_acred.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acred.address)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, vault_id)
    assert vault_registrar.isRegistered(vault_addr, borrower) is True
