import boa
import pytest

from ...conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    SoftLiquidationResult,
    calc_collateral_from_ltv,
    calc_ltv,
    calc_soft_liquidation,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000
DAY = 86400


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
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=int(0.5e18),
        max_iltv=5000,
        available_liquidity=principal,
        call_eligibility=1 * DAY,
        call_window=1 * DAY,
        soft_liquidation_ltv=6000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=32 * b"\1",
    )
    return sign_offer(offer, lender_key, p2p_usdc_weth.address)


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
    usdc.deposit(value=lender_approval, sender=lender)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        offer_usdc_weth, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )

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
        min_collateral_amount=offer.min_collateral_amount,
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
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


@pytest.fixture
def ongoing_loan_usdc_weth_without_soft_liquidation(
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
    offer = replace_namedtuple_field(offer_usdc_weth.offer, soft_liquidation_ltv=0)
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.deposit(value=lender_approval, sender=lender)
    usdc.approve(p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

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
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


@pytest.fixture
def p2p_erc20_proxy(p2p_usdc_weth, p2p_lending_erc20_proxy_contract_def):
    return p2p_lending_erc20_proxy_contract_def.deploy(p2p_usdc_weth.address)


def test_soft_liquidate_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    for loan in get_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.soft_liquidate_loan(loan, sender=ongoing_loan_usdc_weth.borrower)


def test_soft_liquidate_loan_reverts_if_soft_liquidation_disabled(
    p2p_usdc_weth, ongoing_loan_usdc_weth_without_soft_liquidation, lender
):
    with boa.reverts("soft liquidation disabled"):
        p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth_without_soft_liquidation, sender=lender)


def test_soft_liquidate_loan_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_default = ongoing_loan_usdc_weth.maturity - now
    boa.env.time_travel(seconds=time_to_default + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_soft_liquidate_loan_reverts_if_debt_written_off_ge_debt(
    p2p_usdc_weth, borrower, now, lender, weth, ongoing_loan_usdc_weth, oracle
):
    oracle.set_rate(oracle.rate() // 10, sender=oracle.owner())
    with boa.reverts("written off ge debt"):
        p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_simulate_soft_liquidation_loan_reverts_if_debt_written_off_ge_debt(
    p2p_usdc_weth, borrower, now, lender, weth, ongoing_loan_usdc_weth, oracle
):
    oracle.set_rate(oracle.rate() // 10, sender=oracle.owner())
    with boa.reverts("written off ge debt"):
        p2p_usdc_weth.simulate_soft_liquidation(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_soft_liquidate_loan_reverts_if_above_liquidation_ltv(
    p2p_usdc_weth, borrower, now, lender, usdc, weth, ongoing_loan_usdc_weth, oracle
):
    loan = ongoing_loan_usdc_weth
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv < loan.soft_liquidation_ltv

    with boa.reverts("ltv lt liquidation ltv"):
        p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_soft_liquidate_loan_works_with_proxy(p2p_usdc_weth, ongoing_loan_usdc_weth, p2p_erc20_proxy, weth, usdc, oracle):
    loan = ongoing_loan_usdc_weth
    p2p_usdc_weth.set_proxy_authorization(p2p_erc20_proxy, True, sender=p2p_usdc_weth.owner())
    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.soft_liquidation_ltv

    p2p_erc20_proxy.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)

    event = get_last_event(p2p_erc20_proxy, "LoanSoftLiquidated")
    assert event.id == ongoing_loan_usdc_weth.id


def test_soft_liquidate_loan_updates_loan_state(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, oracle, usdc, now):
    liquidator = boa.env.generate_address("liquidator")
    loan = ongoing_loan_usdc_weth
    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.soft_liquidation_ltv

    principal_written_off, collateral_claimed, _ = calc_soft_liquidation(loan, usdc, weth, oracle, now)

    p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=liquidator)

    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        collateral_amount=loan.collateral_amount - collateral_claimed,
        amount=loan.amount + loan.get_interest(now) - principal_written_off,
        accrual_start_time=now,
    )
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id)


def test_soft_liquidate_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now):
    liquidator = boa.env.generate_address("liquidator")
    loan = ongoing_loan_usdc_weth
    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.soft_liquidation_ltv

    principal_written_off, collateral_claimed, liquidation_fee = calc_soft_liquidation(loan, usdc, weth, oracle, now)

    p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=liquidator)

    event = get_last_event(p2p_usdc_weth, "LoanSoftLiquidated")
    assert event.id == loan.id
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.written_off == principal_written_off
    assert event.collateral_claimed == collateral_claimed
    assert event.liquidation_fee == liquidation_fee
    assert event.updated_amount == loan.amount + loan.get_interest(now) - principal_written_off
    assert event.updated_collateral_amount == loan.collateral_amount - collateral_claimed
    assert event.updated_accrual_start_time == now
    assert event.liquidator == liquidator
    assert event.old_ltv == current_ltv
    assert event.new_ltv == calc_ltv(event.updated_amount, event.updated_collateral_amount, usdc, weth, oracle)


def test_soft_liquidate_loan_transfers_collateral(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, oracle, usdc, now):
    liquidator = boa.env.generate_address("liquidator")
    loan = ongoing_loan_usdc_weth

    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.soft_liquidation_ltv

    lender_balance_before = weth.balanceOf(loan.lender)
    protocol_balance_before = weth.balanceOf(p2p_usdc_weth.wallet_to_vault(loan.borrower))

    _, collateral_claimed, liquidation_fee = calc_soft_liquidation(loan, usdc, weth, oracle, now)
    p2p_usdc_weth.soft_liquidate_loan(loan, sender=liquidator)

    assert weth.balanceOf(p2p_usdc_weth.wallet_to_vault(loan.borrower)) == protocol_balance_before - collateral_claimed
    assert weth.balanceOf(loan.lender) == lender_balance_before + collateral_claimed - liquidation_fee


def test_soft_liquidate_loan_pays_liquidation_fee(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, oracle, usdc, now):
    liquidator = boa.env.generate_address("liquidator")
    loan = ongoing_loan_usdc_weth

    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.soft_liquidation_ltv

    liquidator_fee_before = weth.balanceOf(ongoing_loan_usdc_weth.borrower)

    _, _, liquidation_fee = calc_soft_liquidation(loan, usdc, weth, oracle, now)
    p2p_usdc_weth.soft_liquidate_loan(loan, sender=liquidator)

    assert weth.balanceOf(liquidator) == liquidator_fee_before + liquidation_fee


def test_soft_liquidate_loan_consistent_with_simulation(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, oracle, usdc, now):
    liquidator = boa.env.generate_address("liquidator")
    loan = ongoing_loan_usdc_weth
    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.soft_liquidation_ltv

    principal_written_off, collateral_claimed, liquidation_fee = calc_soft_liquidation(loan, usdc, weth, oracle, now)

    soft_liquidation_result = p2p_usdc_weth.simulate_soft_liquidation(ongoing_loan_usdc_weth)
    p2p_usdc_weth.soft_liquidate_loan(ongoing_loan_usdc_weth, sender=liquidator)

    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        collateral_amount=loan.collateral_amount - collateral_claimed,
        amount=loan.amount + loan.get_interest(now) - principal_written_off,
        accrual_start_time=now,
    )
    assert compute_loan_hash(updated_loan) == p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id)

    assert soft_liquidation_result.collateral_claimed == collateral_claimed
    assert soft_liquidation_result.liquidation_fee == liquidation_fee
    assert soft_liquidation_result.debt_written_off == principal_written_off
    assert soft_liquidation_result.updated_ltv == calc_ltv(
        updated_loan.amount, updated_loan.collateral_amount, usdc, weth, oracle
    )
