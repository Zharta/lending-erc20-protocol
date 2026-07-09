"""
Integration tests for P2PLendingVaultedErc20 with deJAAA token (Centrifuge deRWA wrapper).
These tests use the actual deJAAA token on mainnet fork.
Oracle: CentrifugeOracleAdapter wrapping the Centrifuge Spoke for deJAAA price feed.
deJAAA is a freely transferable wrapper around the restricted JAAA token.
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

# deJAAA is a freely transferable wrapper — no transfer restrictions / whitelisting needed.
# The Centrifuge Spoke resolves the price via shareTokenDetails(deJAAA_address) directly.
DEJAAA_ADDRESS = "0xAAA0008C8CF3A7Dca931adaF04336A5D808C82Cc"
DEJAAA_HOLDER = "0x490b0d0eF365cB949B9E9f5656b9301048d2b474"
CENTRIFUGE_SPOKE = "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"


@pytest.fixture
def dejaaa(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at(DEJAAA_ADDRESS)


@pytest.fixture
def centrifuge_spoke():
    return CENTRIFUGE_SPOKE


@pytest.fixture
def oracle_dejaaa_usd(centrifuge_oracle_adapter_contract_def, owner, centrifuge_spoke):
    # Deploy CentrifugeOracleAdapter with the deJAAA token address as the asset.
    # The Spoke resolves poolId/scId via shareTokenDetails(deJAAA_address).
    return centrifuge_oracle_adapter_contract_def.deploy(centrifuge_spoke, DEJAAA_ADDRESS)


@pytest.fixture
def p2p_usdc_dejaaa(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    dejaaa,
    oracle_dejaaa_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        dejaaa,
        oracle_dejaaa_usd,
        False,  # oracle_reverse (deJAAA/USD oracle is not reversed)
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
def de_borrower(dejaaa):
    """Transfer deJAAA tokens from a known holder to a fresh borrower address.
    No whitelisting needed — deJAAA is freely transferable.
    deJAAA has 18 decimals."""
    borrower = boa.env.generate_address("borrower")
    dejaaa.transfer(borrower, 10000 * int(1e18), sender=DEJAAA_HOLDER)
    return borrower


def test_oracle_data(oracle_dejaaa_usd, p2p_usdc_dejaaa):
    answer = oracle_dejaaa_usd.latestRoundData()[1]

    assert oracle_dejaaa_usd.address == p2p_usdc_dejaaa.oracle_addr()
    assert oracle_dejaaa_usd.decimals() == 18

    # deJAAA ~$1.03607 per token at fork block 25300898. Must change if fork block changes.
    min_price = 1036 * 10**15
    max_price = 1037 * 10**15
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_dejaaa,
    de_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    dejaaa,
    usdc,
    oracle_dejaaa_usd,
):
    borrower = de_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has deJAAA (de_borrower transferred tokens)
    boa.env.set_balance(borrower, 10**21)

    collateral_amount = 200 * int(1e18)  # 200 deJAAA (18 decimals)
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_dejaaa.payment_token(),
        collateral_token=p2p_usdc_dejaaa.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_dejaaa.address)

    # Approve collateral
    dejaaa.approve(p2p_usdc_dejaaa.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_dejaaa.address, principal, sender=lender)

    borrower_collateral_balance_before = dejaaa.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Precondition: borrower has enough collateral
    assert borrower_collateral_balance_before >= collateral_amount, "borrower must have enough deJAAA"

    # Create loan
    loan_id = p2p_usdc_dejaaa.create_loan(
        signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_dejaaa, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_dejaaa.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_dejaaa.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_dejaaa.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_dejaaa.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_dejaaa.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_dejaaa.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_dejaaa.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_dejaaa.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_dejaaa.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_dejaaa.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_dejaaa.wallet_to_vault(borrower)

    # Balance assertions
    assert dejaaa.balanceOf(vault_addr) == collateral_amount
    assert dejaaa.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_dejaaa.commited_liquidity(liquidity_key) == principal
