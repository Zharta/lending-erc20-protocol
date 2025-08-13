from textwrap import dedent

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
    sign_offer,
)

FOREVER = 2**256 - 1


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


def test_settle_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    for loan in get_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.settle_loan(loan, sender=ongoing_loan_usdc_weth.borrower)


def test_settle_loan_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_default = ongoing_loan_usdc_weth.maturity - now
    boa.env.time_travel(seconds=time_to_default + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_settle_loan_reverts_if_loan_already_settled(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    with boa.reverts("invalid loan"):
        usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
        p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)


def test_settle_loan_reverts_if_funds_not_approved(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    with boa.reverts():
        usdc.approve(p2p_usdc_weth.address, amount_to_settle - 1, sender=ongoing_loan_usdc_weth.borrower)
        p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)


def test_settle_loan(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert usdc.balanceOf(p2p_usdc_weth.address) == 0


def test_settle_loan_decreases_offer_count(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    offer_liquidity_before = p2p_usdc_weth.commited_liquidity(ongoing_loan_usdc_weth.offer_tracing_id)
    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    assert p2p_usdc_weth.commited_liquidity(ongoing_loan_usdc_weth.offer_tracing_id) == offer_liquidity_before - loan.amount


def test_settle_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest
    protocol_fee_amount = interest * loan.protocol_settlement_fee // 10000

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    event = get_last_event(p2p_usdc_weth, "LoanPaid")
    assert event.id == loan.id
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.payment_token == loan.payment_token
    assert event.paid_principal == loan.amount
    assert event.paid_interest == interest
    assert event.origination_fee_amount == loan.origination_fee_amount
    assert event.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert event.protocol_settlement_fee_amount == protocol_fee_amount


def test_settle_loan_doesnt_transfer_excess_amount_from_borrower(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest
    initial_borrower_balance = usdc.balanceOf(ongoing_loan_usdc_weth.borrower)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle + 1, sender=ongoing_loan_usdc_weth.borrower)
    p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, sender=ongoing_loan_usdc_weth.borrower)
    assert usdc.balanceOf(p2p_usdc_weth.address) == 0
    assert usdc.balanceOf(ongoing_loan_usdc_weth.borrower) == initial_borrower_balance - amount_to_settle


def test_settle_loan_transfers_collateral_to_borrower(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    borrower_balance_before = weth.balanceOf(loan.borrower)
    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    assert weth.balanceOf(loan.borrower) == borrower_balance_before + loan.collateral_amount


def test_settle_loan_pays_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest
    protocol_fee_amount = interest * loan.protocol_settlement_fee // 10000
    amount_to_receive = loan.amount + interest - protocol_fee_amount
    initial_lender_balance = usdc.balanceOf(loan.lender)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    assert usdc.balanceOf(loan.lender) == initial_lender_balance + amount_to_receive


def test_settle_loan_pays_protocol_fees(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest
    protocol_fee_amount = interest * loan.protocol_settlement_fee // 10000
    initial_protocol_wallet_balance = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, sender=loan.borrower)

    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == initial_protocol_wallet_balance + protocol_fee_amount


def test_settle_loan_creates_pending_transfer_on_erc20_transfer_fail(
    p2p_lending_erc20_contract_def,
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
        erc20, weth, oracle, kyc_validator_contract, 0, 0, owner, 10000, 10000, 0
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
    lender_approval = principal - offer.origination_fee_amount + (p2p_erc20_weth.protocol_upfront_fee() * principal // 10000)

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_erc20_weth.address, collateral_amount, sender=borrower)
    # erc20.deposit(value=lender_approval, sender=lender)
    # erc20.approve(p2p_erc20_weth.address, lender_approval, sender=lender)

    loan_id = p2p_erc20_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    initial_ltv = calc_ltv(principal, collateral_amount, erc20, weth, oracle)
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
        origination_fee_amount=offer.origination_fee_amount,
        protocol_upfront_fee_amount=p2p_erc20_weth.protocol_upfront_fee() * principal // 10000,
        protocol_settlement_fee=p2p_erc20_weth.protocol_settlement_fee(),
        soft_liquidation_fee=p2p_erc20_weth.soft_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        soft_liquidation_ltv=offer.soft_liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=initial_ltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_erc20_weth.loans(loan_id)

    p2p_erc20_weth.settle_loan(loan, sender=loan.borrower)

    interest = loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    assert p2p_erc20_weth.pending_transfers(lender) == loan.amount + interest


def test_claim_pending_transactions(p2p_usdc_weth, usdc):
    user = boa.env.generate_address()
    value = 10**6

    p2p_usdc_weth.eval(f"self.pending_transfers[{user}] = {value}")
    boa.env.set_balance(p2p_usdc_weth.address, value)
    usdc.deposit(value=value, sender=p2p_usdc_weth.address)

    assert usdc.balanceOf(user) == 0
    assert p2p_usdc_weth.pending_transfers(user) == value

    p2p_usdc_weth.claim_pending_transfers(sender=user)

    assert usdc.balanceOf(user) == value
    assert p2p_usdc_weth.pending_transfers(user) == 0

    with boa.reverts("no pending transfers"):
        p2p_usdc_weth.claim_pending_transfers(sender=user)
