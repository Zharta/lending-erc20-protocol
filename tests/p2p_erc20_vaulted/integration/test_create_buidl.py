"""
Integration tests for P2PLendingVaultedErc20 with BUIDL token and real VaultRegistrar.
These tests use the actual BUIDL token and VaultRegistrar on mainnet fork.
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
def buidl(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x7712c34205737192402172409a8F7CcEF8aA2AEc")


@pytest.fixture
def oracle_buidl_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0xb9BD795BB71012c0F3cd1D9c9A4c686F2d3524A4")


@pytest.fixture
def securitize_registry(buidl):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json")
    return contract_def.at("0x0Dac900f26DE70336f2320F7CcEDeE70fF6A1a5B")


@pytest.fixture
def p2p_usdc_buidl(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    buidl,
    oracle_buidl_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
    securitize_registry,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        buidl,
        oracle_buidl_usd,
        False,  # oracle_reverse (BUIDL/USD oracle is not reversed)
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
def sec_borrower(buidl, p2p_usdc_buidl, securitize_registry):
    holder = "0xEd71aa0dA4fdBA512FfA398fcFf9db8C49A5Cf72"
    borrower = boa.env.generate_address("borrwer")
    sec_owner = "0xe01605f6b6dC593b7d2917F4a0940db2A625b09e"
    att_accredited = 2
    securitize_registry.updateInvestor(
        "borrower",
        "",
        "US",
        [borrower, p2p_usdc_buidl.wallet_to_vault(borrower)],
        [att_accredited],
        [1],
        [2**255],
        sender=sec_owner,
    )
    buidl.transfer(borrower, 10000 * int(1e6), sender=holder)
    return borrower


def test_oracle_data(oracle_buidl_usd, p2p_usdc_buidl):
    answer = oracle_buidl_usd.latestRoundData()[1]

    assert oracle_buidl_usd.address == p2p_usdc_buidl.oracle_addr()
    assert oracle_buidl_usd.decimals() == 8

    # BUIDL trades at $1.00 per token at the fork block. Must change if fork block changes.
    min_price = 1 * 10**8
    max_price = 101 * 10**6
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_buidl,
    sec_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    buidl,
    usdc,
    oracle_buidl_usd,
):
    borrower = sec_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has BUIDL (sec_borrower is a known holder)
    boa.env.set_balance(borrower, 10**21)

    # Get the borrower's BUIDL balance to determine how much we can use
    borrower_buidl_balance = buidl.balanceOf(borrower)
    # Use 10% of borrower's balance or a minimum of 1e15
    collateral_amount = min(borrower_buidl_balance // 10, int(1e17))
    if collateral_amount == 0:
        collateral_amount = int(1e15)  # Minimum amount for test

    # Adjust principal to maintain LTV within limits
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_buidl.payment_token(),
        collateral_token=p2p_usdc_buidl.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_buidl.address)

    # Approve collateral
    acred_vault = p2p_usdc_buidl.wallet_to_vault(borrower)
    buidl.approve(acred_vault, collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_buidl.address, principal, sender=lender)

    borrower_collateral_balance_before = buidl.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Create loan
    loan_id = p2p_usdc_buidl.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_buidl, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_buidl.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_buidl.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_buidl.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_buidl.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_buidl.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_buidl.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_buidl.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_buidl.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_buidl.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_buidl.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_buidl.wallet_to_vault(borrower)

    # Balance assertions
    assert buidl.balanceOf(vault_addr) == collateral_amount
    assert buidl.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_buidl.commited_liquidity(liquidity_key) == principal
