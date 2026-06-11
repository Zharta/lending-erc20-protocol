from textwrap import dedent

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    SignedOffer,
    calc_ltv,
    compute_liquidity_key,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_events,
    get_last_event,
    manipulate_signature,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
)

BPS = 10000


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc):
    usdc.mint(lender, 10**12)


@pytest.fixture
def lender_sc_wallet(sc_wallet_contract_def, lender):
    return sc_wallet_contract_def.deploy(lender)


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_lender2(lender2, kyc_for, kyc_validator_contract):
    return kyc_for(lender2, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def kyc_lender_sc_wallet(lender_sc_wallet, kyc_for, kyc_validator_contract):
    return kyc_for(lender_sc_wallet.address, kyc_validator_contract.address)


@pytest.fixture
def registrar_connector_weth(registrar_connector_def, vault_registrar_weth, p2p_usdc_weth, owner):
    return registrar_connector_def.deploy(vault_registrar_weth.address)


def test_create_loan_reverts_if_offer_not_signed_by_lender(
    p2p_usdc_weth,
    borrower,
    now,
    lender,
    lender_key,
    p2p_lending_erc20_proxy_contract_def,
    kyc_borrower,
    kyc_lender,
    usdc,
    weth,
    oracle,
    borrower_key,
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, borrower_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_expired(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("offer expired"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_revoked(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("offer revoked"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_wrong_payment_token(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        payment_token=weth.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    with boa.reverts("invalid payment token"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_wrong_collateral_token(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=usdc.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)

    with boa.reverts("invalid collateral token"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_wrong_oracle(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle, oracle_contract_def
):
    wrong_oracle = oracle_contract_def.deploy(8, 100000000)
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=wrong_oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    with boa.reverts("invalid oracle address"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_principal_gt_offer(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal + 1, sender=lender)

    with boa.reverts("offer principal mismatch"):
        p2p_usdc_weth.create_loan(signed_offer, principal + 1, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_principal_gt_available_liquidity(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    available_liquidity = principal - 1
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=available_liquidity,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("offer fully utilized"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_borrower_mismatch(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle, lender2
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=lender2,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("borrower not allowed"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_collateral_lt_min(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    min_collateral = int(2e18)
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=min_collateral,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = min_collateral - 1
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("low collateral amount"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_iltv_gt_max(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    max_iltv = 100
    offer = Offer(
        principal=principal,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=0,
        max_iltv=max_iltv,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("initial ltv gt max iltv"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_call_eligibility_nonzero(
    p2p_usdc_weth, now, borrower, lender, oracle, lender_key, usdc, weth, kyc_borrower, kyc_lender
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=10,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("call eligibility not supported"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_call_window_nonzero(
    p2p_usdc_weth, now, borrower, lender, oracle, lender_key, usdc, weth, kyc_borrower, kyc_lender
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=10,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    with boa.reverts("call window not supported"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan(p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    loan = SecuritizeLoan(
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
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_weth.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=0,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)


def test_create_loan_logs_event(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    event = get_last_event(p2p_usdc_weth, "LoanCreated")
    assert event.id == loan_id
    assert event.amount == principal
    assert event.apr == offer.apr
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_token == weth.address
    assert event.collateral_amount == collateral_amount
    assert event.initial_ltv == offer.max_iltv
    assert event.oracle_rate_num > 0
    assert event.oracle_rate_den > 0
    assert event.vault_id == 0


def test_create_loan_transfers_collateral_to_vault(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, 0)
    assert weth.balanceOf(vault_addr) == collateral_amount


def test_create_loan_transfers_principal_to_borrower(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee


def test_create_loan_updates_committed_liquidity(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    liquidity_key = compute_liquidity_key(lender, offer.tracing_id)
    assert p2p_usdc_weth.commited_liquidity(liquidity_key) == 0

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert p2p_usdc_weth.commited_liquidity(liquidity_key) == principal


def test_create_loan_reverts_if_oracle_answer_zero(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    oracle.set_rate(0, sender=oracle.owner())

    with boa.reverts("invalid oracle rate"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
