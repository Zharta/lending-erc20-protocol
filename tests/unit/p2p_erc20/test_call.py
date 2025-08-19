import boa
import pytest

from ...conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_ltv,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc):
    usdc.mint(lender, 10**12)


@pytest.fixture(autouse=True)
def borrower_funds(borrower, usdc):
    usdc.mint(borrower, 10**12)


@pytest.fixture
def protocol_fees(p2p_usdc_weth):
    settlement_fee = 1000
    upfront_fee = 11
    p2p_usdc_weth.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_weth.owner())
    p2p_usdc_weth.change_protocol_wallet(p2p_usdc_weth.owner(), sender=p2p_usdc_weth.owner())
    return settlement_fee


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def offer_usdc_weth(now, borrower, lender, oracle, lender_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    originating_fee = 10 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_amount=originating_fee,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=10,
        call_window=20,
        soft_liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    return sign_offer(offer, lender_key, p2p_usdc_weth.address)


@pytest.fixture
def non_callable_offer_usdc_weth(now, borrower, lender, oracle, lender_key, usdc, weth, p2p_usdc_weth):
    principal = 1000 * 10**6
    originating_fee = 10 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_amount=originating_fee,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        soft_liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    return sign_offer(offer, lender_key, p2p_usdc_weth.address)


@pytest.fixture
def non_callable_loan_usdc_weth(
    p2p_usdc_weth,
    non_callable_offer_usdc_weth,
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
    offer = non_callable_offer_usdc_weth.offer
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal - offer.origination_fee_amount + (p2p_usdc_weth.protocol_upfront_fee() * principal // 10000)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.address, collateral_amount, sender=borrower)
    usdc.deposit(value=lender_approval, sender=lender)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        non_callable_offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_weth, "LoanCreated")
    initial_ltv = calc_ltv(principal, collateral_amount, usdc, weth, oracle)

    loan = Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(non_callable_offer_usdc_weth),
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
        origination_fee_amount=offer.origination_fee_amount,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee() * principal // 10000,
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        soft_liquidation_fee=p2p_usdc_weth.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=initial_ltv,
        call_time=0,
    )
    print(event)
    print(loan)
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


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
    lender_approval = principal - offer.origination_fee_amount + (p2p_usdc_weth.protocol_upfront_fee() * principal // 10000)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.address, collateral_amount, sender=borrower)
    usdc.deposit(value=lender_approval, sender=lender)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_weth, "LoanCreated")
    initial_ltv = calc_ltv(principal, collateral_amount, usdc, weth, oracle)

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
        origination_fee_amount=offer.origination_fee_amount,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee() * principal // 10000,
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        soft_liquidation_fee=p2p_usdc_weth.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=initial_ltv,
        call_time=0,
    )
    print(event)
    print(loan)
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


@pytest.fixture
def p2p_erc20_proxy(p2p_usdc_weth, p2p_lending_erc20_proxy_contract_def):
    return p2p_lending_erc20_proxy_contract_def.deploy(p2p_usdc_weth.address)


def test_call_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    for loan in get_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.call_loan(loan, sender=ongoing_loan_usdc_weth.borrower)


def test_call_loan_reverts_if_not_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, now, p2p_erc20_proxy):
    with boa.reverts("not lender"):
        p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)

    p2p_usdc_weth.set_proxy_authorization(p2p_erc20_proxy, True, sender=p2p_usdc_weth.owner())
    with boa.reverts("not lender"):
        p2p_erc20_proxy.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_call_loan_reverts_if_not_callable(p2p_usdc_weth, non_callable_loan_usdc_weth, now):
    with boa.reverts("loan not callable"):
        p2p_usdc_weth.call_loan(non_callable_loan_usdc_weth, sender=non_callable_loan_usdc_weth.lender)


def test_call_loan_reverts_if_already_called(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    boa.env.time_travel(seconds=ongoing_loan_usdc_weth.call_eligibility)
    p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)
    boa.env.time_travel(seconds=1)
    updated_loan = replace_namedtuple_field(ongoing_loan_usdc_weth, call_time=now + ongoing_loan_usdc_weth.call_eligibility)

    with boa.reverts("loan already called"):
        p2p_usdc_weth.call_loan(updated_loan, sender=ongoing_loan_usdc_weth.lender)


def test_call_loan_reverts_if_eligibility_not_met(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_call = ongoing_loan_usdc_weth.start_time + ongoing_loan_usdc_weth.call_eligibility - now
    boa.env.time_travel(seconds=time_to_call - 1)

    with boa.reverts("call eligibility not reached"):
        p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)


def test_call_loan_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_default = ongoing_loan_usdc_weth.maturity - now
    boa.env.time_travel(seconds=time_to_default + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)


def test_call_loan_reverts_with_unauth_proxy(p2p_usdc_weth, ongoing_loan_usdc_weth, now, usdc, p2p_erc20_proxy):
    with boa.reverts("not lender"):
        p2p_erc20_proxy.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)


def test_call_loan_works_with_proxy(p2p_usdc_weth, ongoing_loan_usdc_weth, now, usdc, p2p_erc20_proxy):
    p2p_usdc_weth.set_proxy_authorization(p2p_erc20_proxy, True, sender=p2p_usdc_weth.owner())

    boa.env.time_travel(seconds=ongoing_loan_usdc_weth.call_eligibility)

    p2p_erc20_proxy.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)

    updated_loan = replace_namedtuple_field(ongoing_loan_usdc_weth, call_time=now + ongoing_loan_usdc_weth.call_eligibility)
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id)


def test_call_loan_updates_loan_state(p2p_usdc_weth, ongoing_loan_usdc_weth, now, usdc):
    boa.env.time_travel(seconds=ongoing_loan_usdc_weth.call_eligibility)

    p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)

    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        call_time=now + ongoing_loan_usdc_weth.call_eligibility,
    )
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id)


def test_call_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, now, usdc):
    boa.env.time_travel(seconds=ongoing_loan_usdc_weth.call_eligibility)

    p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)

    event = get_last_event(p2p_usdc_weth, "LoanCalled")
    assert event.id == ongoing_loan_usdc_weth.id
    assert event.borrower == ongoing_loan_usdc_weth.borrower
    assert event.lender == ongoing_loan_usdc_weth.lender
    assert event.call_time == now + ongoing_loan_usdc_weth.call_eligibility


def test_call_loan_defaults_loan_after_call_window(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_call = ongoing_loan_usdc_weth.start_time + ongoing_loan_usdc_weth.call_eligibility
    boa.env.time_travel(seconds=time_to_call - now)

    p2p_usdc_weth.call_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.lender)

    time_to_default = time_to_call + ongoing_loan_usdc_weth.call_window
    boa.env.time_travel(seconds=time_to_default)

    assert p2p_usdc_weth.is_loan_defaulted(ongoing_loan_usdc_weth)
