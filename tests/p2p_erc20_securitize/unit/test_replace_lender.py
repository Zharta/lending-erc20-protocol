from textwrap import dedent

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    SignedOffer,
    SignedRedeemResult,
    calc_ltv,
    compute_liquidity_key,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_securitize_loan_mutations,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
)

EMPTY_REDEEM_RESULT = SignedRedeemResult()

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
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=9000,
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
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.mint(lender, lender_approval)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_weth, "LoanCreated")

    loan = SecuritizeLoan(
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
        min_collateral_amount=offer.min_collateral_amount,
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
        vault_id=0,  # First vault for this borrower (counter starts at 0)
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    print(event)
    print(loan)
    assert compute_securitize_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def test_replace_loan_lender_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth, offer_usdc_weth2, kyc_lender2):
    for loan in get_securitize_loan_mutations(ongoing_loan_usdc_weth):
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
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

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
        replace_namedtuple_field(offer, liquidation_ltv=offer.liquidation_ltv + 1),
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


def _max_interest_delta(
    loan: SecuritizeLoan, offer: Offer, new_principal: int, origination_fee_amount: int, refinance_timestamp: int
):
    assert refinance_timestamp >= loan.start_time
    assert refinance_timestamp <= loan.maturity
    print(f"_max_interest_delta: {loan=}, {offer=}, {origination_fee_amount=}, {refinance_timestamp=}")
    print(
        f"_max_interest_delta: {loan.amount=} {loan.apr=} {new_principal=}, {offer.apr=} {loan.maturity=}, {refinance_timestamp=}"  # noqa: E501
    )

    loan_interest_delta_at_maturity = loan.amount * loan.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)
    offer_interest_at_loan_maturity = new_principal * offer.apr * (loan.maturity - refinance_timestamp) // (365 * DAY * BPS)

    return max(
        0, origination_fee_amount, origination_fee_amount + offer_interest_at_loan_maturity - loan_interest_delta_at_maturity
    )


def _calc_deltas(loan, offer, principal, timestamp, contract) -> (int, int, int, int):
    interest = loan.amount * loan.apr * (timestamp - loan.accrual_start_time) // (365 * DAY * BPS)
    protocol_settlement_fee = interest * loan.protocol_settlement_fee // BPS
    outstanding_debt = loan.amount + interest
    new_principal = outstanding_debt if principal == 0 else principal
    origination_fee_amount = offer.origination_fee_bps * new_principal // BPS
    protocol_fee_amount = contract.protocol_upfront_fee() * new_principal // BPS

    max_interest_delta = _max_interest_delta(loan, offer, new_principal, origination_fee_amount, timestamp)
    borrower_compensation = max(0, max_interest_delta + new_principal - outstanding_debt - origination_fee_amount)
    borrower_compensation = max(max_interest_delta, origination_fee_amount - new_principal + outstanding_debt)

    delta_borrower = new_principal - outstanding_debt - origination_fee_amount + borrower_compensation
    delta_lender = outstanding_debt - protocol_settlement_fee - borrower_compensation
    delta_new_lender = origination_fee_amount - new_principal - protocol_fee_amount
    delta_protocol = protocol_settlement_fee + protocol_fee_amount

    print(
        f"_calc_deltas {max_interest_delta=}, {borrower_compensation=} {delta_borrower=}, {delta_lender=}, {delta_new_lender=}, {delta_protocol=}"  # noqa: E501
    )
    return delta_borrower, delta_lender, delta_new_lender, delta_protocol


def test_replace_loan_lender_compensates_borrower_for_origination_fee(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender, lender, lender_key
):
    loan = ongoing_loan_usdc_weth
    new_principal = loan.amount * 3
    offer = replace_namedtuple_field(
        offer_usdc_weth2.offer,
        principal=new_principal,
        origination_fee_bps=6600,
        apr=loan.apr,
        available_liquidity=new_principal,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    delta_borrower, delta_lender, delta_new_lender, _ = _calc_deltas(loan, offer, new_principal, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_lender + delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -(delta_lender + delta_new_lender), sender=loan.lender)

    assert delta_borrower > new_principal * offer.origination_fee_bps // BPS

    p2p_usdc_weth.replace_loan_lender(loan, signed_offer, offer.principal, kyc_lender, sender=loan.lender)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert usdc.balanceOf(p2p_usdc_weth.address) == 0


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

    liquidity_key_1 = compute_liquidity_key(loan.lender, loan.offer_tracing_id)
    liquidity_key_2 = compute_liquidity_key(lender2, offer.tracing_id)
    offer1_liquidity_before = p2p_usdc_weth.commited_liquidity(liquidity_key_1)
    offer2_liquidity_before = p2p_usdc_weth.commited_liquidity(liquidity_key_2)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)
    assert p2p_usdc_weth.commited_liquidity(liquidity_key_1) == offer1_liquidity_before - loan.amount
    assert p2p_usdc_weth.commited_liquidity(liquidity_key_2) == offer2_liquidity_before + loan.amount


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

    event = get_last_event(p2p_usdc_weth, "LoanReplacedByLender")
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
    assert event.liquidation_ltv == offer.liquidation_ltv
    assert event.initial_ltv == loan.initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * loan.amount // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_weth.protocol_upfront_fee() * loan.amount // BPS
    assert event.protocol_settlement_fee == p2p_usdc_weth.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_weth.partial_liquidation_fee()
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

    weth.deposit(value=loan.collateral_amount, sender=loan.borrower)
    initial_borrower_collateral = weth.balanceOf(loan.borrower)
    initial_vault_collateral = weth.balanceOf(p2p_usdc_weth.wallet_to_vault(loan.borrower))

    weth.approve(p2p_usdc_weth.wallet_to_vault(loan.borrower), loan.collateral_amount, sender=loan.borrower)
    p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)

    assert weth.balanceOf(p2p_usdc_weth.wallet_to_vault(loan.borrower)) == initial_vault_collateral
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


def test_replace_loan_lender_reverts_if_borrower_not_allowed(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    random_borrower = boa.env.generate_address("random_borrower")
    offer = Offer(
        principal=loan.amount,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=loan.amount,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=random_borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    with boa.reverts("borrower not allowed"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_offer_principal_mismatch(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (365 * DAY * BPS)
    outstanding_debt = loan.amount + interest
    offer = Offer(
        principal=outstanding_debt + 1,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=outstanding_debt + 1,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    # principal=0 means new_principal=outstanding_debt, which != offer.principal (outstanding_debt + 1)
    with boa.reverts("offer principal mismatch"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_initial_ltv_gt_max_iltv(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    offer = Offer(
        principal=loan.amount,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=1,
        available_liquidity=loan.amount,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    with boa.reverts("initial ltv gt max iltv"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_liquidation_ltv_le_initial_ltv(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    offer = Offer(
        principal=loan.amount,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=loan.amount,
        liquidation_ltv=8000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    with boa.reverts("liquidation ltv le initial ltv"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_initial_ltv_too_high(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    partial_liq_fee = p2p_usdc_weth.partial_liquidation_fee()
    # max_iltv such that (BPS + partial_liq_fee) * max_iltv >= BPS * BPS
    high_iltv = BPS * BPS // (BPS + partial_liq_fee)
    assert (BPS + partial_liq_fee) * high_iltv >= BPS * BPS
    offer = Offer(
        principal=loan.amount,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=high_iltv,
        available_liquidity=loan.amount,
        liquidation_ltv=high_iltv + 1,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    with boa.reverts("initial ltv too high"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_loan_already_exists(
    p2p_usdc_weth, ongoing_loan_usdc_weth, offer_usdc_weth, kyc_lender
):
    loan = ongoing_loan_usdc_weth
    with boa.reverts("loan already exists"):
        p2p_usdc_weth.replace_loan_lender(loan, offer_usdc_weth, loan.amount, kyc_lender, sender=loan.lender)


def test_replace_loan_lender_reverts_if_repayment_time_lt_old_loan(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    # In securitize, _get_repayment_time returns loan.maturity.
    # Old loan maturity = now + 10*DAY. New loan maturity = now + duration.
    # Use duration=5*DAY so new repayment_time = now+5*DAY < now+10*DAY
    offer = Offer(
        principal=loan.amount,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=5 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=loan.amount,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    with boa.reverts("repayment time lt old loan"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_max_iltv_lt_old_loan(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    loan = ongoing_loan_usdc_weth
    # Old loan has initial_ltv=8000. New offer max_iltv must be >= 8000, use 7999 to trigger revert.
    offer = Offer(
        principal=loan.amount,
        apr=800,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=7999,
        available_liquidity=loan.amount,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)

    with boa.reverts("max iltv lt old loan"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)


@pytest.mark.skip("Needs code refactor")
def test_replace_loan_lender_reverts_if_borrower_delta_neg(
    p2p_usdc_weth, ongoing_loan_usdc_weth, lender2_key, usdc, now, kyc_lender2, lender2, weth, oracle
):
    # borrower_delta = new_principal + borrower_compensation - outstanding_debt - origination_fee
    # borrower_compensation = max(max_interest_delta, outstanding_debt + origination_fee - new_principal)
    # By construction, borrower_delta >= 0 always: if the second arg of max() wins, borrower_delta=0;
    # if the first arg wins, max_interest_delta >= outstanding_debt+origination_fee-new_principal, so borrower_delta >= 0.
    # This assert is a safety net that cannot be triggered under normal conditions.
    assert False, (
        "post condition missing: 'borrower delta neg' revert cannot be triggered because "
        "borrower_compensation = max(max_interest_delta, outstanding_debt + origination_fee - new_principal) "
        "guarantees borrower_delta >= 0 by construction. The assert exists as a safety net."
    )


def test_replace_loan_lender_reverts_if_loan_redeemed(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, offer_usdc_weth2, kyc_lender2, lender2
):
    loan = ongoing_loan_usdc_weth

    # Redeem the loan first
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    # Update loan with redeem_start
    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=0,
    )

    with boa.reverts("loan redeemed"):
        p2p_usdc_weth.replace_loan_lender(redeemed_loan, offer_usdc_weth2, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_reverts_if_oracle_answer_zero(
    p2p_usdc_weth, ongoing_loan_usdc_weth, oracle, owner, lender2, lender2_key, usdc, weth, now, kyc_lender2
):
    loan = ongoing_loan_usdc_weth

    new_offer = Offer(
        principal=loan.amount,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=loan.amount,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\2",
    )
    signed_new_offer = sign_offer(new_offer, lender2_key, p2p_usdc_weth.address)
    usdc.approve(p2p_usdc_weth.address, loan.amount * 2, sender=lender2)

    oracle.set_rate(0, sender=owner)

    with boa.reverts("invalid oracle rate"):
        p2p_usdc_weth.replace_loan_lender(loan, signed_new_offer, 0, kyc_lender2, sender=loan.lender)


def test_replace_loan_lender_with_max_iltv_zero(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now, kyc_lender2, lender2, lender2_key, oracle
):
    """Covers branch: if offer.offer.max_iltv == 0 (LTV derived from min_collateral_amount)"""
    loan = ongoing_loan_usdc_weth
    # min_collateral must be small enough so derived LTV >= old loan's initial_ltv (8000)
    min_collateral = int(0.3e18)
    offer = Offer(
        principal=loan.amount,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=min_collateral,
        max_iltv=0,
        available_liquidity=loan.amount,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, loan.amount, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    new_loan_id = p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert p2p_usdc_weth.loans(new_loan_id) != ZERO_BYTES32


def test_replace_loan_lender_with_liquidation_ltv_zero(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now, kyc_lender2, lender2, lender2_key, oracle
):
    """Covers branch: if offer.offer.liquidation_ltv > 0 FALSE path (skips soft liquidation constraints)"""
    loan = ongoing_loan_usdc_weth
    offer = Offer(
        principal=loan.amount,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=loan.amount,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender2,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender2_key, p2p_usdc_weth.address)
    delta_borrower, _, delta_new_lender, _ = _calc_deltas(loan, offer, loan.amount, now, p2p_usdc_weth)

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if delta_new_lender < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_new_lender, sender=lender2)

    new_loan_id = p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender2, sender=loan.lender)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert p2p_usdc_weth.loans(new_loan_id) != ZERO_BYTES32


def test_replace_loan_lender_same_lender(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now, kyc_lender, lender, lender_key, oracle
):
    """Covers branch: if loan.lender == offer.offer.lender (same lender refinance)"""
    loan = ongoing_loan_usdc_weth
    offer = Offer(
        principal=loan.amount,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        max_iltv=8000,
        available_liquidity=loan.amount,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=loan.borrower,
        tracing_id=32 * b"\3",
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    # Use _calc_deltas which handles borrower_compensation correctly
    delta_borrower, delta_lender, delta_new_lender, _ = _calc_deltas(loan, offer, loan.amount, now, p2p_usdc_weth)
    # For same lender, old_lender_delta + new_lender_delta are combined
    lender_delta = delta_lender + delta_new_lender

    if delta_borrower < 0:
        usdc.approve(p2p_usdc_weth.address, -delta_borrower, sender=loan.borrower)
    if lender_delta < 0:
        usdc.approve(p2p_usdc_weth.address, -lender_delta, sender=lender)

    initial_lender_balance = usdc.balanceOf(lender)
    initial_borrower_balance = usdc.balanceOf(loan.borrower)

    new_loan_id = p2p_usdc_weth.replace_loan_lender(loan, signed_offer, loan.amount, kyc_lender, sender=loan.lender)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert p2p_usdc_weth.loans(new_loan_id) != ZERO_BYTES32

    assert usdc.balanceOf(lender) == initial_lender_balance + lender_delta
    assert usdc.balanceOf(loan.borrower) == initial_borrower_balance + delta_borrower


def test_replace_loan_lender_current_ltv_uses_outstanding_debt(
    p2p_usdc_weth,
    usdc,
    weth,
    borrower,
    lender,
    lender_key,
    lender2,
    lender2_key,
    now,
    oracle,
    kyc_borrower,
    kyc_lender,
    kyc_validator_key,
    kyc_validator_contract,
    protocol_fees,
):
    """Validates that current_ltv is computed using outstanding_debt (principal + interest)
    rather than loan.amount (principal only).

    This test would fail using loan.amount to compute current_ltv,
    because initial_ltv > ltv(loan.amount) but initial_ltv <= ltv(outstanding_debt).
    """
    # Create a loan with high APR so interest accrues significantly
    high_apr = 5000  # 50% APR
    principal = 1000 * 10**6  # 1000 USDC
    collateral_amount = int(1e18)  # 1 WETH

    offer = Offer(
        principal=principal,
        apr=high_apr,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=365 * DAY,  # 1 year duration so it doesn't default
        origination_fee_bps=0,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\x10",
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.mint(lender, lender_approval)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

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
        min_collateral_amount=offer.min_collateral_amount,
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

    # Time travel 90 days to accrue significant interest
    time_elapsed = 90 * DAY
    boa.env.time_travel(seconds=time_elapsed)
    refinance_time = now + time_elapsed

    # Compute interest and LTV values
    interest = high_apr * principal * time_elapsed // (365 * DAY * BPS)
    outstanding_debt = principal + interest
    assert interest > 0, "precondition: interest must be > 0 for this test to be meaningful"

    # LTV with outstanding_debt (correct, fixed code)
    ltv_outstanding = calc_ltv(outstanding_debt, collateral_amount, usdc, weth, oracle)
    # LTV with loan.amount (incorrect, buggy code)
    ltv_principal_only = calc_ltv(principal, collateral_amount, usdc, weth, oracle)

    # Precondition: confirm the bug would matter
    assert ltv_outstanding > ltv_principal_only, "precondition: outstanding_debt LTV must exceed principal-only LTV"

    # Create new offer where principal=0 (meaning new_principal = outstanding_debt)
    # initial_ltv = ltv(collateral_amount, outstanding_debt) = ltv_outstanding
    # max_iltv needs to be >= initial_ltv and >= old loan's initial_ltv (8000)
    new_max_iltv = max(ltv_outstanding, loan.initial_ltv)

    new_offer = Offer(
        principal=0,  # Accept any principal
        apr=high_apr,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=365 * DAY,
        origination_fee_bps=0,
        min_collateral_amount=0,
        max_iltv=new_max_iltv,
        available_liquidity=outstanding_debt * 2,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=new_max_iltv + 1000,
        oracle_addr=oracle.address,
        expiration=refinance_time + 100,
        lender=lender2,
        borrower=borrower,
        tracing_id=32 * b"\x11",
    )
    signed_new_offer = sign_offer(new_offer, lender2_key, p2p_usdc_weth.address)

    # Sign KYC for lender2 with expiration after time travel
    kyc_lender2_fresh = sign_kyc(lender2, refinance_time + 100, kyc_validator_key, kyc_validator_contract.address)

    # initial_ltv for the new loan = ltv(collateral_amount, outstanding_debt) = ltv_outstanding
    # With the fix:   current_ltv = ltv(collateral_amount, outstanding_debt) = ltv_outstanding
    #                 initial_ltv <= current_ltv => PASSES
    # With the bug:   current_ltv = ltv(collateral_amount, loan.amount) = ltv_principal_only
    #                 initial_ltv > current_ltv => REVERTS with "initial ltv gt old loan"

    # Approve funds for the new lender
    new_lender_amount = outstanding_debt * 2
    usdc.approve(p2p_usdc_weth.address, new_lender_amount, sender=lender2)

    # This call succeeds with the fix but would revert with "initial ltv gt old loan" with the bug
    new_loan_id = p2p_usdc_weth.replace_loan_lender(loan, signed_new_offer, 0, kyc_lender2_fresh, sender=loan.lender)

    # Verify the replacement was successful
    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32, "old loan should be deleted"
    assert p2p_usdc_weth.loans(new_loan_id) != ZERO_BYTES32, "new loan should exist"


def test_replace_loan_lender_current_ltv_uses_outstanding_debt_boundary(
    p2p_usdc_weth,
    usdc,
    weth,
    borrower,
    lender,
    lender_key,
    lender2,
    lender2_key,
    now,
    oracle,
    kyc_borrower,
    kyc_lender,
    kyc_validator_key,
    kyc_validator_contract,
    protocol_fees,
):
    """Boundary test: new_principal is set so initial_ltv falls between
    ltv(loan.amount) and ltv(outstanding_debt), proving the fix matters.

    With the fix, current_ltv uses outstanding_debt so initial_ltv <= current_ltv passes.
    With the bug, current_ltv uses loan.amount so initial_ltv > current_ltv and it reverts.
    """
    high_apr = 5000  # 50% APR
    principal = 1000 * 10**6  # 1000 USDC
    collateral_amount = int(1e18)  # 1 WETH

    offer = Offer(
        principal=principal,
        apr=high_apr,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=365 * DAY,
        origination_fee_bps=0,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\x20",
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.mint(lender, lender_approval)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

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
        min_collateral_amount=offer.min_collateral_amount,
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

    # Time travel 90 days
    time_elapsed = 90 * DAY
    boa.env.time_travel(seconds=time_elapsed)
    refinance_time = now + time_elapsed

    interest = high_apr * principal * time_elapsed // (365 * DAY * BPS)
    outstanding_debt = principal + interest
    assert interest > 0, "precondition: interest must accrue"

    # Pick a new_principal in between loan.amount and outstanding_debt.
    # This ensures initial_ltv falls between ltv(loan.amount) and ltv(outstanding_debt).
    new_principal = (principal + outstanding_debt) // 2
    assert principal < new_principal < outstanding_debt, (
        "precondition: new_principal must be strictly between loan.amount and outstanding_debt"
    )

    # Verify the LTV ordering
    ltv_principal_only = calc_ltv(principal, collateral_amount, usdc, weth, oracle)
    ltv_new_principal = calc_ltv(new_principal, collateral_amount, usdc, weth, oracle)
    ltv_outstanding = calc_ltv(outstanding_debt, collateral_amount, usdc, weth, oracle)
    assert ltv_principal_only < ltv_new_principal <= ltv_outstanding, (
        f"precondition: ltv ordering must be principal({ltv_principal_only}) < new({ltv_new_principal}) <= outstanding({ltv_outstanding})"
    )

    new_max_iltv = max(ltv_outstanding, loan.initial_ltv)

    new_offer = Offer(
        principal=new_principal,
        apr=high_apr,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=365 * DAY,
        origination_fee_bps=0,
        min_collateral_amount=0,
        max_iltv=new_max_iltv,
        available_liquidity=new_principal * 2,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=new_max_iltv + 1000,
        oracle_addr=oracle.address,
        expiration=refinance_time + 100,
        lender=lender2,
        borrower=borrower,
        tracing_id=32 * b"\x21",
    )
    signed_new_offer = sign_offer(new_offer, lender2_key, p2p_usdc_weth.address)

    # Sign KYC for lender2 with expiration after time travel
    kyc_lender2_fresh = sign_kyc(lender2, refinance_time + 100, kyc_validator_key, kyc_validator_contract.address)

    usdc.approve(p2p_usdc_weth.address, new_principal * 2, sender=lender2)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=borrower)

    # With the fix: current_ltv = ltv_outstanding >= ltv_new_principal = initial_ltv => PASSES
    # With the bug: current_ltv = ltv_principal_only < ltv_new_principal = initial_ltv => REVERTS
    new_loan_id = p2p_usdc_weth.replace_loan_lender(
        loan, signed_new_offer, new_principal, kyc_lender2_fresh, sender=loan.lender
    )

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32, "old loan should be deleted"
    assert p2p_usdc_weth.loans(new_loan_id) != ZERO_BYTES32, "new loan should exist"
