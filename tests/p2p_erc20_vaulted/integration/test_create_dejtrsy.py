"""
Integration tests for P2PLendingVaultedErc20 with deJTRSY token (Centrifuge deRWA wrapper).
These tests use the actual deJTRSY token on mainnet fork.
Oracle: CentrifugeOracleAdapter wrapping the Centrifuge Spoke for deJTRSY price feed.
deJTRSY is a freely transferable wrapper around the restricted JTRSY token.
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

# deJTRSY is a freely transferable wrapper — no transfer restrictions / whitelisting needed.
# The Centrifuge Spoke resolves the price via shareTokenDetails(deJTRSY_address) directly.
DEJTRSY_ADDRESS = "0xA6233014B9b7aaa74f38fa1977ffC7A89642dC72"
DEJTRSY_HOLDER = "0xB9d62d9DD99635370C2eAc9fBFDD8163956afe0c"
CENTRIFUGE_SPOKE = "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"


@pytest.fixture
def dejtrsy(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at(DEJTRSY_ADDRESS)


@pytest.fixture
def centrifuge_spoke():
    return CENTRIFUGE_SPOKE


@pytest.fixture
def oracle_dejtrsy_usd(centrifuge_oracle_adapter_contract_def, owner, centrifuge_spoke):
    # Deploy CentrifugeOracleAdapter with the deJTRSY token address as the asset.
    # The Spoke resolves poolId/scId via shareTokenDetails(deJTRSY_address).
    return centrifuge_oracle_adapter_contract_def.deploy(centrifuge_spoke, DEJTRSY_ADDRESS)


@pytest.fixture
def p2p_usdc_dejtrsy(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    dejtrsy,
    oracle_dejtrsy_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        dejtrsy,
        oracle_dejtrsy_usd,
        False,  # oracle_reverse (deJTRSY/USD oracle is not reversed)
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
def de_borrower(dejtrsy):
    """Transfer deJTRSY tokens from a known holder to a fresh borrower address.
    No whitelisting needed — deJTRSY is freely transferable.
    deJTRSY has 18 decimals."""
    borrower = boa.env.generate_address("borrwer")
    dejtrsy.transfer(borrower, 10000 * int(1e18), sender=DEJTRSY_HOLDER)
    return borrower


def test_oracle_data(oracle_dejtrsy_usd, p2p_usdc_dejtrsy):
    answer = oracle_dejtrsy_usd.latestRoundData()[1]

    assert oracle_dejtrsy_usd.address == p2p_usdc_dejtrsy.oracle_addr()
    assert oracle_dejtrsy_usd.decimals() == 18

    # deJTRSY ~$1.02761 per token at fork block 25300898. Must change if fork block changes.
    min_price = 1027 * 10**15
    max_price = 1028 * 10**15
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_dejtrsy,
    de_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    dejtrsy,
    usdc,
    oracle_dejtrsy_usd,
):
    borrower = de_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has deJTRSY (de_borrower transferred tokens)
    boa.env.set_balance(borrower, 10**21)

    collateral_amount = 200 * int(1e18)  # 200 deJTRSY (18 decimals)
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_dejtrsy.payment_token(),
        collateral_token=p2p_usdc_dejtrsy.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_dejtrsy.address)

    # Approve collateral
    dejtrsy.approve(p2p_usdc_dejtrsy.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_dejtrsy.address, principal, sender=lender)

    borrower_collateral_balance_before = dejtrsy.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Precondition: borrower has enough collateral
    assert borrower_collateral_balance_before >= collateral_amount, "borrower must have enough deJTRSY"

    # Create loan
    loan_id = p2p_usdc_dejtrsy.create_loan(
        signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_dejtrsy, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_dejtrsy.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_dejtrsy.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_dejtrsy.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_dejtrsy.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_dejtrsy.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_dejtrsy.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_dejtrsy.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_dejtrsy.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_dejtrsy.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_dejtrsy.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_dejtrsy.wallet_to_vault(borrower)

    # Balance assertions
    assert dejtrsy.balanceOf(vault_addr) == collateral_amount
    assert dejtrsy.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_dejtrsy.commited_liquidity(liquidity_key) == principal
