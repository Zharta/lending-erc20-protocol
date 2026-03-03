from textwrap import dedent

import boa
import pytest

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


def test_create_loan_reverts_if_offer_not_signed_by_lender(
    p2p_usdc_weth,
    borrower,
    now,
    lender,
    borrower_key,
    usdc,
    weth,
    kyc_borrower,
    kyc_lender,
):
    offer = Offer(
        principal=1000,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        min_collateral_amount=1,
        duration=100,
        origination_fee_bps=0,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, borrower_key, p2p_usdc_weth.address)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.create_loan(signed_offer, 1000, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_has_invalid_signature(
    p2p_usdc_weth,
    borrower,
    now,
    lender,
    lender_key,
    usdc,
    weth,
    kyc_borrower,
    kyc_lender,
    oracle,
):
    offer = Offer(
        principal=1000,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=0,
        min_collateral_amount=1,
        max_iltv=10000,
        available_liquidity=1000,
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

    invalid_offers = [
        replace_namedtuple_field(offer, principal=offer.principal + 1),
        replace_namedtuple_field(offer, apr=offer.apr + 1),
        replace_namedtuple_field(offer, payment_token=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, collateral_token=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, duration=offer.duration + 1),
        replace_namedtuple_field(offer, origination_fee_bps=offer.origination_fee_bps + 1),
        replace_namedtuple_field(offer, min_collateral_amount=offer.min_collateral_amount + 1),
        replace_namedtuple_field(offer, max_iltv=offer.max_iltv + 1),
        replace_namedtuple_field(offer, available_liquidity=offer.available_liquidity + 1),
        replace_namedtuple_field(offer, call_eligibility=offer.call_eligibility + 1),
        replace_namedtuple_field(offer, call_window=offer.call_window + 1),
        replace_namedtuple_field(offer, liquidation_ltv=offer.liquidation_ltv + 1),
        replace_namedtuple_field(offer, oracle_addr=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, expiration=offer.expiration + 1),
        replace_namedtuple_field(offer, lender=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, borrower=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, tracing_id=b"\1" * 32),
    ]

    for invalid_offer in invalid_offers:
        print(f"{invalid_offer=}")
        with boa.reverts("offer not signed by lender"):
            p2p_usdc_weth.create_loan(
                SignedOffer(invalid_offer, signed_offer.signature), 1000, 1, kyc_borrower, kyc_lender, sender=borrower
            )

    with boa.reverts("invalid signature"):
        manipulated_sig_offer = replace_namedtuple_field(signed_offer, signature=manipulate_signature(signed_offer.signature))
        p2p_usdc_weth.create_loan(manipulated_sig_offer, 1000, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_expired(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        expiration=now,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("offer expired"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_duration_is_zero(p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=0,  # zero duration
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("duration is 0"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_payment_token_invalid(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=boa.env.generate_address("random"),  # invalid payment token
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("invalid payment token"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_collateral_token_invalid(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=boa.env.generate_address("random"),  # invalid collateral token
        duration=100,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("invalid collateral token"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_oracle_address_invalid(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        oracle_addr=boa.env.generate_address("random"),  # invalid oracle address
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("invalid oracle address"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_call_window_is_zero(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        call_eligibility=1,
        call_window=0,  # zero call window
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("call window is 0"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_min_collateral_and_max_iltv_are_zero(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=0,  # zero min collateral
        max_iltv=0,  # zero max iltv
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("no min collateral nor max iltv"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, 1, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_is_revoked(p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        max_iltv=10000,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)

    with boa.reverts("offer revoked"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, int(1e18), kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_offer_exceeds_count(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=0,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("offer fully utilized"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, int(1e18), kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_origination_fee_exceeds_principal(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        origination_fee_bps=10001,  # origination fee exceeds principal
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("origination fee gt principal"):
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, int(1e18), kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_collateral_not_approved(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=1000,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    collateral_amount = int(1e18)

    with boa.reverts():
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_lender_funds_not_approved(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=1000,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    with boa.reverts():
        p2p_usdc_weth.create_loan(signed_offer, offer.principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


def test_create_loan_reverts_if_borrower_kyc_not_correct(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_lender, kyc_validator_contract, usdc, weth, kyc_validator_key
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=1000,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    invalid_kyc_borrower_list = [
        sign_kyc(boa.env.generate_address("random"), now, kyc_validator_key, kyc_validator_contract.address),
        sign_kyc(borrower, now - 1, kyc_validator_key, kyc_validator_contract.address),
        sign_kyc(borrower, now, lender_key, kyc_validator_contract.address),
        sign_kyc(borrower, now, kyc_validator_key, boa.env.generate_address("random")),
    ]

    for kyc_borrower in invalid_kyc_borrower_list:
        print(f"{kyc_borrower=}")
        with boa.reverts("KYC validation fail"):
            p2p_usdc_weth.create_loan(
                signed_offer, offer.principal, offer.min_collateral_amount, kyc_borrower, kyc_lender, sender=borrower
            )


def test_create_loan_reverts_if_lender_kyc_not_correct(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_validator_contract, usdc, weth, kyc_validator_key
):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=1000,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    invalid_kyc_lender_list = [
        sign_kyc(boa.env.generate_address("random"), now, kyc_validator_key, kyc_validator_contract.address),
        sign_kyc(offer.lender, now - 1, kyc_validator_key, kyc_validator_contract.address),
        sign_kyc(offer.lender, now, lender_key, kyc_validator_contract.address),
        sign_kyc(offer.lender, now, kyc_validator_key, boa.env.generate_address("random")),
    ]

    for kyc_lender in invalid_kyc_lender_list:
        print(f"{kyc_lender=}")
        with boa.reverts("KYC validation fail"):
            p2p_usdc_weth.create_loan(
                signed_offer, offer.principal, offer.min_collateral_amount, kyc_borrower, kyc_lender, sender=borrower
            )


def test_create_loan(p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc, oracle):
    principal = 1000 * int(1e9)
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, weth, oracle)

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
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee(),
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_weth.oracle_addr(),
        initial_ltv=initial_ltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    assert p2p_usdc_weth.current_ltv(loan) == calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)


def test_create_loan_logs_event(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc, oracle
):
    principal = 1000 * int(1e9)
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_weth, "LoanCreated")
    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, weth, oracle)

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
    assert event.oracle_addr == p2p_usdc_weth.oracle_addr()
    assert event.initial_ltv == initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_weth.protocol_upfront_fee()
    assert event.protocol_settlement_fee == p2p_usdc_weth.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_weth.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id
    assert event.oracle_rate_num == oracle.latestRoundData().answer
    assert event.oracle_rate_den == 10 ** oracle.decimals()


def test_create_loan_transfers_collateral_to_escrow(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)
    borrower_collateral_balance_before = weth.balanceOf(borrower)

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert weth.balanceOf(p2p_usdc_weth.wallet_to_vault(borrower)) == collateral_amount
    assert weth.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount


def test_create_loan_transfers_principal_to_borrower(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        origination_fee_bps=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee


def test_create_loan_transfers_origination_fee_to_lender(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        origination_fee_bps=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)
    lender_balance_before = usdc.balanceOf(lender)
    origination_fee = offer.origination_fee_bps * principal // BPS

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee


def test_create_loan_updates_commited_liquidity(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_weth.commited_liquidity(liquidity_key) == principal


def test_create_loan_for_token_offer_revokes_normal_offer(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    offer_id = compute_signed_offer_id(signed_offer)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    event = get_last_event(p2p_usdc_weth, "OfferRevoked")
    assert event.offer_id == offer_id
    assert event.lender == offer.lender

    assert p2p_usdc_weth.revoked_offers(offer_id)


def test_create_loan_for_token_offer_doesnt_revoke_open_offer(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    offer_id = compute_signed_offer_id(signed_offer)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert len(get_events(p2p_usdc_weth, "OfferRevoked")) == 0
    assert not p2p_usdc_weth.revoked_offers(offer_id)


def test_create_loan_for_different_lenders_track_liquidity_separately(
    p2p_usdc_weth, borrower, now, lender, lender_key, lender2, lender2_key, kyc_borrower, kyc_lender, kyc_lender2, weth, usdc
):
    principal = 1000
    collateral_amount = int(1e18)
    offer1 = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    offer2 = replace_namedtuple_field(offer1, lender=lender2)
    signed_offer1 = sign_offer(offer1, lender_key, p2p_usdc_weth.address)
    signed_offer2 = sign_offer(offer2, lender2_key, p2p_usdc_weth.address)

    weth.deposit(value=2 * collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), 2 * collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)
    usdc.deposit(value=principal, sender=lender2)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender2)

    p2p_usdc_weth.create_loan(signed_offer1, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    p2p_usdc_weth.create_loan(signed_offer2, principal, collateral_amount, kyc_borrower, kyc_lender2, sender=borrower)

    liquidity_key1 = compute_liquidity_key(offer1.lender, offer1.tracing_id)
    liquidity_key2 = compute_liquidity_key(offer2.lender, offer2.tracing_id)
    assert liquidity_key1 != liquidity_key2
    assert p2p_usdc_weth.commited_liquidity(liquidity_key1) == principal
    assert p2p_usdc_weth.commited_liquidity(liquidity_key2) == principal


def test_create_loan_creates_vault_if_needed(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, weth, usdc
):
    # Check no vault exists initially for a new borrower
    borrower_vault = p2p_usdc_weth.wallet_to_vault(borrower)
    assert not boa.eval(f"{borrower_vault}.is_contract")

    # Create loan for new borrower
    collateral_amount = 10**18  # 1 WETH
    principal = 2000 * 10**6  # 2000 USDC

    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert boa.eval(f"{borrower_vault}.is_contract")


def test_create_vault_if_needed_registers_vault_with_registrar(
    p2p_usdc_weth, borrower, vault_registrar_mock, registrar_connector
):
    borrower_vault = p2p_usdc_weth.wallet_to_vault(borrower)
    assert not boa.eval(f"{borrower_vault}.is_contract")

    p2p_usdc_weth.create_vault_if_needed(borrower)

    assert boa.eval(f"{borrower_vault}.is_contract")
    assert vault_registrar_mock.isRegistered(borrower_vault, borrower)


def test_create_loan_works_with_lender_sc_wallet(
    p2p_usdc_weth,
    borrower,
    now,
    lender,
    lender_key,
    kyc_borrower,
    kyc_lender,
    weth,
    usdc,
    oracle,
    lender_sc_wallet,
    kyc_lender_sc_wallet,
):
    principal = 1000 * int(1e9)
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender_sc_wallet.address,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=principal, sender=lender)
    usdc.transfer(lender_sc_wallet.address, principal, sender=lender)
    lender_sc_wallet.approve_erc20(usdc.address, p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender_sc_wallet, sender=borrower
    )
    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, weth, oracle)

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
        lender=lender_sc_wallet.address,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee(),
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_weth.oracle_addr(),
        initial_ltv=initial_ltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
