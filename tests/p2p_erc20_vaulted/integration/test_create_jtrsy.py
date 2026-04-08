"""
Integration tests for P2PLendingVaultedErc20 with JTRSY token.
These tests use the actual JTRSY token on mainnet fork.
Oracle: CentrifugeOracleAdapter wrapping the Centrifuge Spoke for JTRSY price feed.
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
def jtrsy(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x8c213ee79581Ff4984583C6a801e5263418C4b86")


@pytest.fixture
def centrifuge_spoke():
    return "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"


@pytest.fixture
def oracle_jtrsy_usd(centrifuge_oracle_adapter_contract_def, jtrsy, owner, centrifuge_spoke):
    return centrifuge_oracle_adapter_contract_def.deploy(centrifuge_spoke, jtrsy.address)


@pytest.fixture
def centrifuge_full_restrictions():
    contract_def = boa.load_abi("contracts/auxiliary/CentrifugeFullRestrictions_abi.json")
    return contract_def.at("0x8E680873b4C77e6088b4Ba0aBD59d100c3D224a4")


@pytest.fixture
def p2p_usdc_jtrsy(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    jtrsy,
    oracle_jtrsy_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        jtrsy,
        oracle_jtrsy_usd,
        False,  # oracle_reverse (JTRSY/USD oracle is not reversed)
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
def sec_borrower(jtrsy, p2p_usdc_jtrsy, centrifuge_full_restrictions, now, centrifuge_spoke):
    holder = "0x491EDFB0B8b608044e227225C715981a30F3A44E"
    borrower = boa.env.generate_address("borrwer")

    # Whitelist borrower in Centrifuge FullRestrictions before transferring
    centrifuge_full_restrictions.updateMember(jtrsy.address, borrower, 2**64 - 1, sender=centrifuge_spoke)
    jtrsy.transfer(borrower, 10000 * int(1e6), sender=holder)

    # Also whitelist the vault that will hold collateral
    vault_addr = p2p_usdc_jtrsy.wallet_to_vault(borrower)
    centrifuge_full_restrictions.updateMember(jtrsy.address, vault_addr, 2**64 - 1, sender=centrifuge_spoke)

    return borrower


def test_create_loan(
    p2p_usdc_jtrsy,
    sec_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    jtrsy,
    usdc,
    oracle_jtrsy_usd,
):
    borrower = sec_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has JTRSY (sec_borrower transferred tokens)
    boa.env.set_balance(borrower, 10**21)

    collateral_amount = 200 * int(1e6)  # 200 JTRSY
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_jtrsy.payment_token(),
        collateral_token=p2p_usdc_jtrsy.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_jtrsy.address)

    # Approve collateral
    jtrsy.approve(p2p_usdc_jtrsy.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_jtrsy.address, principal, sender=lender)

    borrower_collateral_balance_before = jtrsy.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Create loan
    loan_id = p2p_usdc_jtrsy.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_jtrsy, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_jtrsy.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_jtrsy.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_jtrsy.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_jtrsy.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_jtrsy.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_jtrsy.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_jtrsy.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_jtrsy.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_jtrsy.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_jtrsy.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_jtrsy.wallet_to_vault(borrower)

    # Balance assertions
    assert jtrsy.balanceOf(vault_addr) == collateral_amount
    assert jtrsy.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_jtrsy.commited_liquidity(liquidity_key) == principal
