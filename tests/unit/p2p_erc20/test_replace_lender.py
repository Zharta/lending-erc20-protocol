from textwrap import dedent

import boa
import pytest

from ...conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    SignedOffer,
    calc_ltv,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
)

BPS = 10000
DAY = 86400
MAX_UINT256 = 2**256 - 1


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc):
    usdc.mint(lender, 10**12)


@pytest.fixture(autouse=True)
def lender2_funds(lender2, usdc):
    usdc.mint(lender2, 10**12)


@pytest.fixture(autouse=True)
def borrower_funds(borrower, usdc):
    usdc.mint(borrower, 10**12)


@pytest.fixture
def protocol_fees(p2p_usdc_weth):
    settlement_fee = 100
    upfront_fee = 11
    p2p_usdc_weth.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_weth.owner())
    p2p_usdc_weth.change_protocol_wallet(p2p_usdc_weth.owner(), sender=p2p_usdc_weth.owner())
    return settlement_fee


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
def offer_usdc_weth(now, borrower, lender, oracle, lender_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=1 * DAY,
        call_window=1 * DAY,
        soft_liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\1",
    )
    return sign_offer(offer, lender_key, p2p_usdc_weth.address)


@pytest.fixture
def offer_usdc_weth2(now, borrower, lender2, oracle, lender2_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    offer = Offer(
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=borrower,
        tracing_id=32 * b"\2",
    )
    return sign_offer(offer, lender2_key, p2p_usdc_weth.address)


@pytest.fixture
def ongoing_loan_usdc_weth(
    p2p_usdc_weth,
    offer_usdc_weth,
    usdc,
    weth,
    borrower,
    lender,
    lender_key,
    now,
    protocol_fees,
    kyc_borrower,
    kyc_lender,
    oracle,
):
    offer = offer_usdc_weth.offer
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.address, collateral_amount, sender=borrower)
    usdc.deposit(value=lender_approval, sender=lender)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_weth, "LoanCreated")

    loan = Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(offer_usdc_weth),
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
        soft_liquidation_fee=p2p_usdc_weth.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    print(event)
    print(loan)
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def test_replace_loan_lender_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth, offer_usdc_weth2, kyc_lender2):
    for loan in get_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_loan_defaulted(
    p2p_usdc_weth, ongoing_loan_usdc_weth, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    time_to_default = ongoing_loan_usdc_weth.maturity - now
    boa.env.time_travel(seconds=time_to_default + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_loan_already_settled(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    with boa.reverts("invalid loan"):
        usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_funds_not_approved(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    with boa.reverts():
        usdc.approve(p2p_usdc_weth.address, amount_to_settle - 1, sender=ongoing_loan_usdc_weth.borrower)
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=ongoing_loan_usdc_weth.lender)


def test_replace_loan_lender_reverts_if_not_lender(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.lender)

    with boa.reverts("not lender"):
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.borrower)


def test_replace_loan_lender_reverts_if_offer_not_signed_by_lender(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender_key
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    tampered_offer = sign_offer(offer_usdc_weth2.offer, lender_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.lender)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.replace_loan_lender(loan, tampered_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_offer_has_invalid_signature(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest
    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

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
        replace_namedtuple_field(offer, soft_liquidation_ltv=offer.soft_liquidation_ltv + 1),
        replace_namedtuple_field(offer, oracle_addr=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, expiration=offer.expiration + 1),
        replace_namedtuple_field(offer, lender=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, borrower=boa.env.generate_address("random")),
        replace_namedtuple_field(offer, tracing_id=b"\1" * 32),
    ]

    for offer in invalid_offers:
        with boa.reverts("offer not signed by lender"):
            print(f"{offer=}")
            p2p_usdc_weth.replace_loan_lender(
                loan,
                SignedOffer(offer, offer_usdc_weth2.signature),
                0,
                kyc_lender2,
                sender=loan.lender,
            )


def test_replace_loan_lender_reverts_if_offer_expired(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    expired_offer = replace_namedtuple_field(offer_usdc_weth2.offer, expiration=now - 1)
    signed_expired_offer = sign_offer(expired_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.lender)

    with boa.reverts("offer expired"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_expired_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_duration_is_zero(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, duration=0)
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("duration is 0"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_payment_token_invalid(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, payment_token=boa.env.generate_address("random"))
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("invalid payment token"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_collateral_token_invalid(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, collateral_token=boa.env.generate_address("random"))
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("invalid collateral token"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_oracle_address_invalid(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, oracle_addr=boa.env.generate_address("random"))
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("invalid oracle address"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_call_window_is_zero(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, call_eligibility=1, call_window=0)
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("call window is 0"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_min_collateral_and_max_iltv_are_zero(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, min_collateral_amount=0, max_iltv=0)
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("no min collateral nor max iltv"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_lowers_soft_liquidation_ltv(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, soft_liquidation_ltv=loan.soft_liquidation_ltv - 1)
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("liquidation ltv lt old loan"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_offer_is_revoked(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    p2p_usdc_weth.revoke_offer(offer_usdc_weth2, sender=offer_usdc_weth2.offer.lender)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("offer revoked"):
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_offer_exceeds_count(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, available_liquidity=0)
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("offer fully utilized"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_origination_fee_exceeds_principal(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, lender2_key, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    invalid_offer = replace_namedtuple_field(offer_usdc_weth2.offer, origination_fee_bps=BPS + 1)
    signed_invalid_offer = sign_offer(invalid_offer, lender2_key, p2p_usdc_weth.address)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)

    with boa.reverts("origination fee gt principal"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_invalid_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_collateral_not_approved(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth

    with boa.reverts():
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_lender_funds_not_approved(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2
):
    loan = ongoing_loan_usdc_weth

    usdc.approve(p2p_usdc_weth.address, MAX_UINT256, sender=loan.borrower)

    with boa.reverts():
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_lender_kyc_not_correct(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    now,
    offer_usdc_weth2,
    kyc_lender2,
    kyc_validator_key,
    kyc_validator_contract,
    lender_key,
    lender2,
):
    loan = ongoing_loan_usdc_weth

    invalid_kyc_lender_list = [
        sign_kyc(boa.env.generate_address("random"), now, kyc_validator_key, kyc_validator_contract.address),
        sign_kyc(lender2, now - 1, kyc_validator_key, kyc_validator_contract.address),
        sign_kyc(lender2, now, lender_key, kyc_validator_contract.address),
        sign_kyc(lender2, now, kyc_validator_key, boa.env.generate_address("random")),
    ]

    for kyc_lender in invalid_kyc_lender_list:
        print(f"{kyc_lender=}")
        with boa.reverts("KYC validation fail"):
            p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender, sender=loan.lender)


def _max_interest_delta(loan: Loan, offer: Offer, new_principal: int, refinance_timestamp: int):
    assert refinance_timestamp >= loan.start_time
    assert refinance_timestamp <= loan.maturity
    print(f"_max_interest_delta: {loan=}, {offer=}, {refinance_timestamp=}")
    print(
        f"_max_interest_delta: {loan.amount=} {loan.apr=} {new_principal=}, {offer.apr=} {loan.maturity=}, {refinance_timestamp=}"  # noqa: E501
    )  # noqa: E501

    loan_interest_delta_at_maturity = loan.amount * loan.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)
    offer_interest_at_loan_maturity = new_principal * offer.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)

    return max(0, offer_interest_at_loan_maturity - loan_interest_delta_at_maturity)


def _calc_deltas(loan, offer, principal, timestamp, contract) -> (int, int, int, int):
    interest = loan.amount * loan.apr * (timestamp - loan.accrual_start_time) // (365 * DAY * BPS)
    protocol_settlement_fee = interest * loan.protocol_settlement_fee // BPS
    outstanding_debt = loan.amount + interest
    new_principal = outstanding_debt if principal == 0 else principal
    origination_fee_amount = offer.origination_fee_bps * new_principal // BPS
    protocol_fee_amount = contract.protocol_upfront_fee() * new_principal // BPS

    max_interest_delta = _max_interest_delta(loan, offer, new_principal, timestamp)
    borrower_compensation = max(0, max_interest_delta + new_principal - outstanding_debt - origination_fee_amount)
    borrower_compensation = max(max_interest_delta, origination_fee_amount - new_principal + outstanding_debt)

    delta_borrower = new_principal - outstanding_debt - origination_fee_amount + borrower_compensation
    delta_lender = outstanding_debt - protocol_settlement_fee - borrower_compensation
    delta_new_lender = origination_fee_amount - new_principal - protocol_fee_amount
    delta_protocol = protocol_settlement_fee + protocol_fee_amount

    print(
        f"_calc_deltas {max_interest_delta=}, {borrower_compensation=} {delta_borrower=}, {delta_lender=}, {delta_new_lender=}, {delta_protocol=}"  # noqa: E501
    )  # noqa: E501
    return delta_borrower, delta_lender, delta_new_lender, delta_protocol


def test_replace_loan_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert usdc.balanceOf(p2p_usdc_weth.address) == 0


def test_replace_loan_lender_updates_commited_liquidity(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    offer1_liquidity_before = p2p_usdc_weth.commited_liquidity(ongoing_loan_usdc_weth.offer_tracing_id)
    offer2_liquidity_before = p2p_usdc_weth.commited_liquidity(offer.tracing_id)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)
    assert p2p_usdc_weth.commited_liquidity(ongoing_loan_usdc_weth.offer_tracing_id) == offer1_liquidity_before - loan.amount
    assert p2p_usdc_weth.commited_liquidity(offer.tracing_id) == offer2_liquidity_before + loan.amount


@pytest.mark.skip(reason="boa doesnt catch 'unused' events and fails")
def test_replace_loan_lender_logs_event(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    new_loan_id = p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)

    event = get_last_event(p2p_usdc_weth, "LoanReplaced")
    assert event.id == new_loan_id
    assert event.amount == loan.amount
    assert event.apr == offer.apr
    assert event.maturity == now + offer.duration
    assert event.start_time == now
    assert event.borrower == loan.borrower
    assert event.lender == lender2
    assert event.collateral_amount == loan.collateral_amount
    assert event.min_collateral_amount == offer.min_collateral_amount
    assert event.call_eligibility == offer.call_eligibility
    assert event.call_window == offer.call_window
    assert event.soft_liquidation_ltv == offer.soft_liquidation_ltv
    assert event.initial_ltv == loan.initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * loan.amount // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_weth.protocol_upfront_fee() * loan.amount // BPS
    assert event.protocol_settlement_fee == p2p_usdc_weth.protocol_settlement_fee()
    assert event.soft_liquidation_fee == p2p_usdc_weth.soft_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(offer_usdc_weth2)
    assert event.offer_tracing_id == offer.tracing_id
    assert event.original_loan_id == loan.id
    assert event.paid_principal == loan.amount
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    assert event.paid_interest == interest
    assert event.paid_protocol_settlement_fee_amount == interest * loan.protocol_settlement_fee // 10000


def test_replace_loan_lender_keeps_collateral_in_escrow(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now, offer_usdc_weth2, kyc_lender2, lender2
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    weth.mint(loan.borrower, loan.collateral_amount)
    initial_borrower_collateral = weth.balanceOf(loan.borrower)
    initial_protocol_collateral = weth.balanceOf(p2p_usdc_weth.address)

    weth.approve(p2p_usdc_weth.address, loan.collateral_amount, sender=loan.borrower)
    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)

    assert weth.balanceOf(p2p_usdc_weth.address) == initial_protocol_collateral
    assert weth.balanceOf(loan.borrower) == initial_borrower_collateral


def test_replace_loan_lender_receives_payment_from_new_lender(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2, lender2_key
):
    loan = ongoing_loan_usdc_weth
    new_loan_principal = loan.amount // 2
    offer = replace_namedtuple_field(offer_usdc_weth2.offer, principal=new_loan_principal)
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, new_loan_principal, now, p2p_usdc_weth)

    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    initial_borrower_balance = usdc.balanceOf(loan.borrower)
    initial_new_lender_balance = usdc.balanceOf(lender2)
    p2p_usdc_weth.replace_loan_lender(loan, signed_offer, new_loan_principal, kyc_lender2, sender=loan.lender)

    assert usdc.balanceOf(loan.borrower) == initial_borrower_balance + delta_borrower
    assert usdc.balanceOf(lender2) == initial_new_lender_balance + delta_new_lender


def test_replace_loan_lender_pays_lender(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    delta_borrower, delta_lender, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    initial_lender_balance = usdc.balanceOf(loan.lender)
    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)
    assert usdc.balanceOf(loan.lender) == initial_lender_balance + delta_lender


def test_replace_loan_lender_pays_protocol_fees(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2
):
    loan = ongoing_loan_usdc_weth
    offer = offer_usdc_weth2.offer
    delta_borrower, _, delta_new_lender, protocol_delta = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    initial_protocol_wallet_balance = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)

    assert protocol_delta > 0
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == initial_protocol_wallet_balance + protocol_delta


def test_replace_loan_lender_creates_pending_transfer_on_erc20_transfer_fail(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    weth,
    owner,
    borrower,
    lender,
    lender_key,
    oracle,
    kyc_validator_contract,
    kyc_borrower,
    kyc_lender,
    now,
    offer_usdc_weth2,
    kyc_lender2,
    lender2,
    lender2_key,
):
    failing_erc20_code = dedent("""

            @external
            @view
            def decimals() -> uint256:
                return 9

            @external
            def transfer(_to : address, _value : uint256) -> bool:
                return False

            @external
            def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
                return True

            """)

    erc20 = boa.loads(failing_erc20_code)
    p2p_erc20_weth = p2p_lending_erc20_contract_def.deploy(
        erc20, weth, oracle, False, kyc_validator_contract, 0, 0, owner, 10000, 10000, 0, p2p_refinance.address
    )
    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=erc20.address,
        collateral_token=weth.address,
        duration=100,
        max_iltv=8000,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_erc20_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_erc20_weth.address, collateral_amount, sender=borrower)

    loan_id = p2p_erc20_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
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
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_erc20_weth.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_erc20_weth.protocol_settlement_fee(),
        soft_liquidation_fee=p2p_erc20_weth.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=p2p_erc20_weth.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_erc20_weth.loans(loan_id)

    offer = replace_namedtuple_field(
        offer_usdc_weth2.offer, principal=loan.amount, available_liquidity=loan.amount, payment_token=erc20.address
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_erc20_weth.address)
    _, delta_lender, _, _ = _calc_deltas(loan, offer, 0, now, p2p_erc20_weth)
    p2p_erc20_weth.replace_loan_lender(loan, signed_offer, 0, kyc_lender2, sender=loan.lender)

    assert p2p_erc20_weth.pending_transfers(lender) == delta_lender


def test_replace_loan_lender_for_borrower_offer_revokes_offer(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2, lender2_key
):
    loan = ongoing_loan_usdc_weth
    offer = replace_namedtuple_field(offer_usdc_weth2.offer, borrower=loan.borrower)
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    assert not p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))

    p2p_usdc_weth.replace_loan_lender(loan, signed_offer, 0, kyc_lender2, sender=loan.lender)

    assert p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))


def test_replace_loan_lender_for_normal_offer_doesnt_revoke_offer(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2, lender2_key
):
    loan = ongoing_loan_usdc_weth
    offer = replace_namedtuple_field(offer_usdc_weth2.offer, borrower=ZERO_ADDRESS)
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, 0, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    assert not p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))

    p2p_usdc_weth.replace_loan_lender(loan, signed_offer, 0, kyc_lender2, sender=loan.lender)

    assert not p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))
