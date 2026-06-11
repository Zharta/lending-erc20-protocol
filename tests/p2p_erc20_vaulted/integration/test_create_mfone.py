"""
Integration tests for P2PLendingVaultedErc20 with mF-ONE token (Midas Fasanara ONE).
These tests use the actual mF-ONE token and Chainlink oracle on mainnet fork.
mF-ONE uses blacklist-based access control (no whitelist/greenlist for transfers).
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    sign_offer,
)

BPS = 10000


@pytest.fixture
def mfone(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x238a700eD6165261Cf8b2e544ba797BC11e466Ba")


@pytest.fixture
def oracle_mfone_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C")


@pytest.fixture
def p2p_usdc_mfone(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    mfone,
    oracle_mfone_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        mfone,
        oracle_mfone_usd,
        False,  # oracle_reverse (mF-ONE/USD oracle is not reversed)
        kyc_validator_contract,
        0,  # protocol_upfront_fee
        0,  # protocol_settlement_fee
        owner,  # protocol_wallet
        10000,  # max_protocol_upfront_fee
        10000,  # max_protocol_settlement_fee
        0,  # partial_liquidation_fee
        0,  # full_liquidation_fee
        p2p_refinance.address,  # refinance_addr
        p2p_liquidation.address,  # liquidation_addr
        vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        boa.eval("empty(address)"),  # vault_registrar_addr
    )


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture
def sec_borrower(mfone, p2p_usdc_mfone, now):
    holder = "0x9Db5B0B081E2202fb588cbD541B01b77f45Cfe2d"
    borrower = boa.env.generate_address("borrwer")
    mfone.transfer(borrower, 500 * int(1e18), sender=holder)
    return borrower


def test_oracle_data(oracle_mfone_usd, p2p_usdc_mfone):
    answer = oracle_mfone_usd.latestRoundData()[1]

    assert oracle_mfone_usd.address == p2p_usdc_mfone.oracle_addr()
    assert oracle_mfone_usd.decimals() == 8

    # mF-ONE trades at ~$1.077 per token at the fork block. Must change if fork block changes.
    min_price = 107 * 10**6
    max_price = 108 * 10**6
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_mfone,
    sec_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    mfone,
    usdc,
    oracle_mfone_usd,
):
    borrower = sec_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    boa.env.set_balance(borrower, 10**21)

    # mF-ONE is ~$1.077/token (18 decimals), USDC is 6 decimals
    # 200 mF-ONE ≈ $215 collateral, 100 USDC principal => LTV ~46%, well within 95% max
    collateral_amount = 200 * int(1e18)  # 200 mF-ONE
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_mfone.payment_token(),
        collateral_token=p2p_usdc_mfone.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_mfone.address)

    # Approve collateral
    vault_addr = p2p_usdc_mfone.wallet_to_vault(borrower)
    mfone.approve(vault_addr, collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)

    borrower_collateral_balance_before = mfone.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Create loan
    loan_id = p2p_usdc_mfone.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_mfone, "LoanCreated")

    # Verify loan was created with proper hash
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
        protocol_upfront_fee_amount=p2p_usdc_mfone.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_mfone.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_mfone.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_mfone.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_mfone.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_mfone.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_mfone.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_mfone.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_mfone.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    # Balance assertions
    assert mfone.balanceOf(vault_addr) == collateral_amount
    assert mfone.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal
