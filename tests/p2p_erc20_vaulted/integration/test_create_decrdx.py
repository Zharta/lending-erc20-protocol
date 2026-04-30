"""
Integration tests for P2PLendingVaultedErc20 with deCRDX token (Centrifuge deRWA wrapper).
These tests use the actual deCRDX token on mainnet fork.
Oracle: CentrifugeOracleAdapter wrapping the Centrifuge Spoke for deCRDX price feed.
deCRDX is a freely transferable wrapper around a Centrifuge RWA token.

Token acquisition: deCRDX has no holders at the fork block (total supply = 0). We mint tokens
by removing the transfer hook (via file("hook", zero_address) as Spoke ward) and then calling
mint(borrower, amount) as the Spoke.

"""

import json
import os

import boa
import pytest
from boa.contracts.event_decoder import RawLogEntry
from boa.environment import Env

from ..conftest_base import (
    ZERO_BYTES32,
    EventWrapper,
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
def decrdx(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x9E2679eABFF131b8b1b48fF7566140794E0eEdc4")


@pytest.fixture
def centrifuge_spoke():
    return "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"


@pytest.fixture
def oracle_decrdx_usd(centrifuge_oracle_adapter_contract_def, owner, centrifuge_spoke, decrdx):
    # Deploy CentrifugeOracleAdapter with the deCRDX token address as the asset.
    # The Spoke resolves poolId/scId via shareTokenDetails(deCRDX_address).
    return centrifuge_oracle_adapter_contract_def.deploy(centrifuge_spoke, decrdx.address)


@pytest.fixture
def p2p_usdc_decrdx(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    decrdx,
    oracle_decrdx_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        decrdx,
        oracle_decrdx_usd,
        False,  # oracle_reverse (deCRDX/USD oracle is not reversed)
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
def centrifuge_token_def():
    """ABI for Centrifuge token ward/hook management functions."""

    abi = json.dumps(
        [
            {
                "inputs": [{"name": "user", "type": "address"}],
                "name": "wards",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
                "name": "mint",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
            {
                "inputs": [{"name": "what", "type": "bytes32"}, {"name": "data", "type": "address"}],
                "name": "file",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "hook",
                "outputs": [{"name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]
    )
    return boa.loads_abi(abi)


@pytest.fixture
def de_borrower(decrdx, centrifuge_token_def, centrifuge_spoke):
    """Mint deCRDX tokens for a fresh borrower address.
    Since deCRDX has zero total supply, we mint by:
    1. Removing the transfer hook (via Spoke ward calling file("hook", zero_address))
    2. Minting tokens as the Spoke ward
    No whitelisting needed — deCRDX is freely transferable.
    deCRDX has 18 decimals."""
    borrower = boa.env.generate_address("borrwer")
    boa.env.set_balance(centrifuge_spoke, 10**21)

    # Access deCRDX via Centrifuge token ABI for ward/hook management
    decrdx_cf = centrifuge_token_def.at(decrdx.address)

    # Remove the transfer hook to allow minting
    hook_key = b"hook" + b"\x00" * 28  # bytes32 padded
    decrdx_cf.file(hook_key, "0x0000000000000000000000000000000000000000", sender=centrifuge_spoke)

    # Mint tokens as the Spoke (authorized ward)
    mint_amount = 10000 * int(1e18)
    decrdx_cf.mint(borrower, mint_amount, sender=centrifuge_spoke)

    return borrower


def test_oracle_data(oracle_decrdx_usd, p2p_usdc_decrdx):
    answer = oracle_decrdx_usd.latestRoundData()[1]

    assert oracle_decrdx_usd.address == p2p_usdc_decrdx.oracle_addr()
    assert oracle_decrdx_usd.decimals() == 18

    # deCRDX price from Centrifuge Spoke: ~$0.9949 per token at the fork block (24920000).
    # Must change if fork block changes.
    min_price = 994 * 10**15
    max_price = 995 * 10**15
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_decrdx,
    de_borrower,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    decrdx,
    usdc,
    oracle_decrdx_usd,
):
    borrower = de_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has deCRDX (de_borrower minted tokens)
    boa.env.set_balance(borrower, 10**21)

    # deCRDX has 18 decimals, oracle price ~$0.9949 (18 decimals from adapter)
    # 200 deCRDX ~ $199 collateral. 100 USDC principal => LTV ~50.2%, well within 95% max
    collateral_amount = 200 * int(1e18)  # 200 deCRDX (18 decimals)
    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_decrdx.payment_token(),
        collateral_token=p2p_usdc_decrdx.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_decrdx.address)

    # Approve collateral
    decrdx.approve(p2p_usdc_decrdx.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_decrdx.address, principal, sender=lender)

    borrower_collateral_balance_before = decrdx.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Precondition: borrower has enough collateral
    assert borrower_collateral_balance_before >= collateral_amount, "borrower must have enough deCRDX"

    # Create loan
    loan_id = p2p_usdc_decrdx.create_loan(
        signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_decrdx, "LoanCreated")

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
        protocol_upfront_fee_amount=p2p_usdc_decrdx.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_decrdx.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_decrdx.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_decrdx.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_decrdx.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_decrdx.loans(loan_id), "Loan hash should match"

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
    assert event.oracle_addr == p2p_usdc_decrdx.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_decrdx.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_decrdx.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_decrdx.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    vault_addr = p2p_usdc_decrdx.wallet_to_vault(borrower)

    # Balance assertions
    assert decrdx.balanceOf(vault_addr) == collateral_amount
    assert decrdx.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_decrdx.commited_liquidity(liquidity_key) == principal
