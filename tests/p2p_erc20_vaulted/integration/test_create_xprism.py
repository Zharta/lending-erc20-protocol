"""
Integration tests for P2PLendingVaultedErc20 with xPRISM token.
These tests use the actual xPRISM token on mainnet fork.
Oracle: xPrismOracleAdapter deriving xPRISM/USDC price via ERC-4626 vault rates and Chainlink feeds.
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
def xprism(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x12E04c932D682a2999b4582F7c9B86171B73220D")


@pytest.fixture(scope="session")
def xprism_oracle_adapter_contract_def():
    return boa.load_partial("contracts/xPrismOracleAdapter.vy")


@pytest.fixture
def oracle_xprism_usd(xprism_oracle_adapter_contract_def, owner):
    return xprism_oracle_adapter_contract_def.deploy(
        "0x12E04c932D682a2999b4582F7c9B86171B73220D",  # xPRISM
        "0xad55aebc9b8c03fc43cd9f62260391c13c23e7c0",  # cUSDO
        "0x5b79480BbF13930B777B2Cb9Ca8d664B7AA3aa6a",  # cUSDO/USD Chainlink
        "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",  # USDC/USD Chainlink
    )


@pytest.fixture
def p2p_usdc_xprism(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    xprism,
    oracle_xprism_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        xprism,
        oracle_xprism_usd,
        False,  # oracle_reverse (xPRISM/USD oracle is not reversed)
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
def sec_borrower(xprism, p2p_usdc_xprism, now):
    holder = "0xD15D29BFc6dBBefCCB7e239F1db0d3a6Ca7550e5"
    borrower = boa.env.generate_address("borrwer")
    xprism.transfer(borrower, 800 * int(1e18), sender=holder)
    return borrower


# The xPRISM oracle adapter derives its price from the cUSDO/USD chainlink feed 0x5b79480BbF13930B777B2Cb9Ca8d664B7AA3aa6a.
# That proxy's underlying aggregator was unset on-chain: https://etherscan.io/tx/0x2dd19353d20ee8b4db11bbca2192b8b7a81f46d10f4a92b891cc53dd931bd589/advanced
@pytest.mark.skip("xPRISM oracle adapter cannot produce a price at fork block 25300898")
def test_oracle_data(oracle_xprism_usd, p2p_usdc_xprism):
    answer = oracle_xprism_usd.latestRoundData()[1]

    assert oracle_xprism_usd.address == p2p_usdc_xprism.oracle_addr()
    assert oracle_xprism_usd.decimals() == 8

    # Must change if fork block changes.
    min_price = 100 * 10**6
    max_price = 101 * 10**6
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


# The xPRISM oracle adapter derives its price from the cUSDO/USD chainlink feed 0x5b79480BbF13930B777B2Cb9Ca8d664B7AA3aa6a.
# That proxy's underlying aggregator was unset on-chain: https://etherscan.io/tx/0x2dd19353d20ee8b4db11bbca2192b8b7a81f46d10f4a92b891cc53dd931bd589/advanced
@pytest.mark.skip("xPRISM oracle adapter cannot produce a price at fork block 25300898")
def test_create_loan(
    p2p_usdc_xprism,
    sec_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    xprism,
    usdc,
    oracle_xprism_usd,
):
    borrower = sec_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    boa.env.set_balance(borrower, 10**21)

    # xPRISM is ~$1/token (18 decimals), need enough collateral for LTV <= 95%
    # 200 xPRISM ≈ $200, well above the ~$105 needed for 100 USDC at 95% LTV
    collateral_amount = 200 * int(1e18)  # 200 xPRISM
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_xprism.payment_token(),
        collateral_token=p2p_usdc_xprism.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_xprism.address)

    # Approve collateral
    xprism.approve(p2p_usdc_xprism.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_xprism.address, principal, sender=lender)

    borrower_collateral_balance_before = xprism.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Create loan
    loan_id = p2p_usdc_xprism.create_loan(
        signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_xprism, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_xprism.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_xprism.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_xprism.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_xprism.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_xprism.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_xprism.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_xprism.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_xprism.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_xprism.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_xprism.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_xprism.wallet_to_vault(borrower)

    # Balance assertions
    assert xprism.balanceOf(vault_addr) == collateral_amount
    assert xprism.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_xprism.commited_liquidity(liquidity_key) == principal
