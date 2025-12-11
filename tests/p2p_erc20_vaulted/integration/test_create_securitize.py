import os
from textwrap import dedent

import boa
import pytest
from boa.environment import Env

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
    sign_kyc,
    sign_offer,
)

BPS = 10000

SEC_REG_ACCREDITED = 2
SEC_REG_APPROVED = 1


@pytest.fixture
def acred(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x17418038ecF73BA4026c4f428547BF099706F27B")


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender, kyc_validator_contract.address, expiration=now + 86400)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def oracle_acred_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0xD6BcbbC87bFb6c8964dDc73DC3EaE6d08865d51C")


@pytest.fixture
def securitize_vault_contract_def():
    return boa.load_partial("contracts/v2/P2PLendingV2VaultSecuritize.vy")


@pytest.fixture
def securitize_vault_impl(securitize_vault_contract_def):
    return securitize_vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_acred(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    usdc,
    acred,
    oracle_acred_usd,
    kyc_validator_contract,
    owner,
    securitize_vault_impl,
    transfer_agent,
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
        0,
        0,
        p2p_refinance.address,
        p2p_liquidation.address,
        securitize_vault_impl.address,
        transfer_agent,
    )


@pytest.fixture
def securitize_owner():
    return "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"


@pytest.fixture
def securitize_registry(p2p_usdc_acred, securitize_owner, now):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json")
    return contract_def.at("0x3A8E9CD2E17E1F2904b7f745Da29C9cA765Cc319")


@pytest.fixture
def securitize_swap(p2p_usdc_acred, securitize_registry, securitize_owner, now):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeSwapService_abi.json")
    # return contract_def.at(securitize_registry.getDSService(1 << 14))
    return contract_def.at("0x4A107BAEc38840E744d397f6a7E90ffc36beE141")


@pytest.fixture
def balancer(boa_env):
    return boa.load_abi("contracts/auxiliary/BalancerFlashLoanProvider.json", name="Balancer").at(
        "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
    )


@pytest.fixture
def securitize_proxy(securitize_proxy_contract_def, p2p_usdc_acred, balancer, securitize_registry, securitize_owner, now):
    proxy = securitize_proxy_contract_def.deploy(p2p_usdc_acred.address, balancer.address)
    p2p_usdc_acred.set_proxy_authorization(proxy, True)
    return proxy


@pytest.fixture(autouse=True)
def sec_borrower(securitize_registry, p2p_usdc_acred, securitize_owner, now):
    wallet = "0x81aF1E160c290E8Fff6381CCF67981f012Cf1009"
    securitize_registry.updateInvestor(
        "sec_borrower_vault",
        "",
        "PT",
        [p2p_usdc_acred.wallet_to_vault(wallet)],
        [SEC_REG_ACCREDITED],
        [SEC_REG_APPROVED],
        [now + 86400 * 365],
        sender=securitize_owner,
    )
    return wallet


def test_create_loan(
    p2p_usdc_acred,
    sec_borrower,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    acred,
    oracle_acred_usd,
    securitize_registry,
):
    borrower = sec_borrower
    principal = 1000 * int(1e9)
    collateral_amount = 95 * int(1e6)
    now = boa.eval("block.timestamp")
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
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    borrower_collateral_balance_before = acred.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)

    now = boa.eval("block.timestamp")
    boa.vm.py_evm.register_raw_precompile(
        "0x0000000000000000000000000000000000011111", lambda computation: print("0x" + computation.msg.data.hex())
    )

    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    loan_id = p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_acred, "LoanCreated")
    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, acred, oracle_acred_usd, oracle_reverse=False)

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
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
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
    assert event.liquidation_ltv == offer.liquidation_ltv
    assert event.oracle_addr == p2p_usdc_acred.oracle_addr()
    assert event.initial_ltv == initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_acred.protocol_upfront_fee()
    assert event.protocol_settlement_fee == p2p_usdc_acred.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_acred.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    assert acred.balanceOf(p2p_usdc_acred.wallet_to_vault(borrower)) == collateral_amount
    assert acred.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal


def test_loop(
    p2p_usdc_acred,
    sec_borrower,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    acred,
    oracle_acred_usd,
    securitize_registry,
    securitize_swap,
    securitize_proxy,
):
    principals = [70000000000, 49000000000, 34300000000, 24000000000, 17000000000]
    collateral_amounts = [94000000, 66000000, 46000000, 32000000, 23000000]

    initial_borrower_collateral = collateral_amounts[0]
    collateral_amount = sum(collateral_amounts)
    collateral_to_buy = collateral_amount - initial_borrower_collateral
    collateral_to_buy_value = securitize_swap.calculateStableCoinAmount(collateral_to_buy)
    principal = sum(principals)

    borrower = sec_borrower
    # principal = 1000 * int(1e9)
    # collateral_amount = 95 * int(1e6)
    now = boa.eval("block.timestamp")
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
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    # usdc.approve(securitize_swap.address, collateral_to_buy_value, sender=borrower)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)
    usdc.approve(securitize_proxy.address, collateral_to_buy_value, sender=borrower)

    borrower_collateral_balance_before = acred.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)

    now = boa.eval("block.timestamp")

    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    securitize_proxy.create_loan(
        signed_offer,
        principal,
        collateral_amount,
        kyc_borrower,
        kyc_lender,
        collateral_to_buy,
        collateral_to_buy_value,
        sender=borrower,
    )

    assert acred.balanceOf(p2p_usdc_acred.wallet_to_vault(borrower)) == collateral_amount
    assert acred.balanceOf(borrower) == borrower_collateral_balance_before + collateral_to_buy - collateral_amount

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - collateral_to_buy_value - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal
