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
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_events,
    get_last_event,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000


@pytest.fixture
def acred(owner, accounts, erc20_contract_def):
    erc20 = erc20_contract_def.at("0x17418038ecF73BA4026c4f428547BF099706F27B")
    holder = "0xa0759A0DFdE5395a1892aEd90eB5665698CFaa05"
    with boa.env.prank(holder):
        for account in accounts:
            erc20.transfer(account, 10**9, sender=holder)
    erc20.transfer(owner, 10**9, sender=holder)
    return erc20


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def sec_borrower(borrower, kyc_for, kyc_validator_contract):
    return "0x81aF1E160c290E8Fff6381CCF67981f012Cf1009"


@pytest.fixture
def oracle_acred_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0xD6BcbbC87bFb6c8964dDc73DC3EaE6d08865d51C")


@pytest.fixture
def p2p_usdc_acred(
    p2p_lending_erc20_contract_def, p2p_refinance, usdc, acred, oracle_acred_usd, kyc_validator_contract, sec_borrower, owner
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        acred,
        oracle_acred_usd,
        False,
        kyc_validator_contract,
        0,
        0,
        owner,
        10000,
        10000,
        p2p_refinance.address,
        sec_borrower,
    )


def test_create_loan(
    p2p_usdc_acred, sec_borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc, oracle_usdc_eth
):
    borrower = sec_borrower
    principal = 1000 * int(1e9)
    collateral_amount = int(1e9)
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

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_acred.address, collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    borrower_collateral_balance_before = weth.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    loan_id = p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_acred, "LoanCreated")
    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, weth, oracle_usdc_eth, oracle_reverse=True)

    loan = Loan(
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
        soft_liquidation_fee=p2p_usdc_acred.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=p2p_usdc_acred.oracle_addr(),
        initial_ltv=initial_ltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)

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
    assert event.soft_liquidation_ltv == offer.soft_liquidation_ltv
    assert event.oracle_addr == p2p_usdc_acred.oracle_addr()
    assert event.initial_ltv == initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_acred.protocol_upfront_fee()
    assert event.protocol_settlement_fee == p2p_usdc_acred.protocol_settlement_fee()
    assert event.soft_liquidation_fee == p2p_usdc_acred.soft_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    assert weth.balanceOf(p2p_usdc_acred.address) == collateral_amount
    assert weth.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal
