from textwrap import dedent

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc):
    usdc.mint(lender, 10**12)


@pytest.fixture(autouse=True)
def borrower_funds(borrower, usdc):
    usdc.mint(borrower, 10**12)


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
def offer_usdc_weth(now, borrower, lender, oracle, lender_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=10,
        call_window=10,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
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
    oracle,
):
    offer = offer_usdc_weth.offer
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=lender_approval, sender=lender)
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
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    print(event)
    print(loan)
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def test_transfer_loan_reverts_if_loan_invalid(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract
):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    for loan in get_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.transfer_loan(loan, new_borrower, new_borrower_kyc, sender=transfer_agent)


def test_transfer_loan_reverts_if_not_transfer_agent(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract
):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    with boa.reverts("not transfer agent"):
        p2p_usdc_weth.transfer_loan(ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, sender=boa.env.generate_address())


def test_transfer_loan_changes_borrower(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract
):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    p2p_usdc_weth.transfer_loan(ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, sender=transfer_agent)
    event = get_last_event(p2p_usdc_weth, "LoanBorrowerTransferred")
    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        borrower=new_borrower,
        id=event.new_loan_id,
    )
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(updated_loan.id)
