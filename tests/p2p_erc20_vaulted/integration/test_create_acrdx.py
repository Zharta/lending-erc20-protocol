"""
Integration tests for P2PLendingVaultedErc20 with ACRDX token and real VaultRegistrar.
These tests use the actual ACRDX token and VaultRegistrar on mainnet fork.
Oracle: CentrifugeOracleAdapter wrapping the Centrifuge Spoke for ACRDX price feed.
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
def acrdx(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x9477724bb54ad5417de8baff29e59df3fb4da74f")


@pytest.fixture
def centrifuge_spoke():
    return "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"


@pytest.fixture
def oracle_acrdx_usd(centrifuge_oracle_adapter_contract_def, acrdx, owner, centrifuge_spoke):
    return centrifuge_oracle_adapter_contract_def.deploy(centrifuge_spoke, acrdx.address)


@pytest.fixture
def centrifuge_full_restrictions():
    contract_def = boa.load_abi("contracts/auxiliary/CentrifugeFullRestrictions_abi.json")
    return contract_def.at("0x8E680873b4C77e6088b4Ba0aBD59d100c3D224a4")


@pytest.fixture
def p2p_usdc_acrdx(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    acrdx,
    oracle_acrdx_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        acrdx,
        oracle_acrdx_usd,
        False,  # oracle_reverse (ACRDX/USD oracle is not reversed)
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
def sec_borrower(acrdx, p2p_usdc_acrdx, centrifuge_full_restrictions, now, centrifuge_spoke):
    holder = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
    borrower = boa.env.generate_address("borrwer")

    # Whitelist borrower in Centrifuge FullRestrictions before transferring
    centrifuge_full_restrictions.updateMember(acrdx.address, borrower, 2**64 - 1, sender=centrifuge_spoke)
    acrdx.transfer(borrower, 10000 * int(1e18), sender=holder)

    # Also whitelist the vault that will hold collateral
    vault_addr = p2p_usdc_acrdx.wallet_to_vault(borrower)
    centrifuge_full_restrictions.updateMember(acrdx.address, vault_addr, 2**64 - 1, sender=centrifuge_spoke)

    return borrower


def test_oracle_data(oracle_acrdx_usd, p2p_usdc_acrdx):
    answer = oracle_acrdx_usd.latestRoundData()[1]

    assert oracle_acrdx_usd.address == p2p_usdc_acrdx.oracle_addr()
    assert oracle_acrdx_usd.decimals() == 18

    # ACRDX trades at ~$1.0204 per token at the fork block. Must change if fork block changes.
    min_price = 1020 * 10**15
    max_price = 1021 * 10**15
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_acrdx,
    sec_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    acrdx,
    usdc,
    oracle_acrdx_usd,
):
    borrower = sec_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has ACRDX (sec_borrower is a known holder)
    boa.env.set_balance(borrower, 10**21)

    # ACRDX is ~$1.02/token (18 decimals), need enough collateral for LTV <= 95%
    # 200 ACRDX ≈ $204, well above the ~$105 needed for 100 USDC at 95% LTV
    collateral_amount = 200 * int(1e18)  # 200 ACRDX
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_acrdx.payment_token(),
        collateral_token=p2p_usdc_acrdx.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acrdx.address)

    # Approve collateral
    acrdx.approve(p2p_usdc_acrdx.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acrdx.address, principal, sender=lender)

    borrower_collateral_balance_before = acrdx.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Create loan
    loan_id = p2p_usdc_acrdx.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_acrdx, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_acrdx.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_acrdx.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acrdx.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acrdx.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_acrdx.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_acrdx.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_acrdx.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_acrdx.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_acrdx.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_acrdx.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_acrdx.wallet_to_vault(borrower)

    # Balance assertions
    assert acrdx.balanceOf(vault_addr) == collateral_amount
    assert acrdx.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acrdx.commited_liquidity(liquidity_key) == principal
