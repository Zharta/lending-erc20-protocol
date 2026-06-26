import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    RedeemResult,
    SignedRedeemResult,
    calc_collateral_from_ltv,
    calc_full_liquidation,
    calc_full_liquidation_redeemed,
    calc_ltv,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
    sign_redeem_result,
)

BPS = 10000
DAY = 86400

# Empty redeem result for non-redeemed loan liquidations
EMPTY_REDEEM_RESULT = SignedRedeemResult()


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
    p2p_usdc_weth.set_partial_liquidation_fee(500, sender=p2p_usdc_weth.owner())
    p2p_usdc_weth.set_full_liquidation_fee(300, sender=p2p_usdc_weth.owner())
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
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=6000,
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
    usdc.mint(lender, lender_approval)
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
        create_time=now,
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
        max_pending_window=0,
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
    offer = replace_namedtuple_field(offer_usdc_weth.offer, liquidation_ltv=0)
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.mint(lender, lender_approval)
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
        create_time=now,
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
        max_pending_window=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


@pytest.fixture
def p2p_erc20_proxy(p2p_usdc_weth, p2p_lending_erc20_proxy_contract_def):
    return p2p_lending_erc20_proxy_contract_def.deploy(p2p_usdc_weth.address)


def test_liquidate_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    loan = ongoing_loan_usdc_weth
    boa.env.time_travel(seconds=loan.maturity + 1)  # Make loan defaulted
    for corrupted_loan in get_loan_mutations(loan):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.liquidate_loan(corrupted_loan, EMPTY_REDEEM_RESULT, sender=loan.lender)


def test_liquidate_loan_reverts_if_loan_not_defaulted_and_partial_disabled(
    p2p_usdc_weth, ongoing_loan_usdc_weth_without_soft_liquidation
):
    with boa.reverts("not defaulted, partial disabled"):
        p2p_usdc_weth.liquidate_loan(
            ongoing_loan_usdc_weth_without_soft_liquidation,
            EMPTY_REDEEM_RESULT,
            sender=ongoing_loan_usdc_weth_without_soft_liquidation.lender,
        )


def test_liquidate_loan_reverts_if_loan_not_defaulted_and_ltv_lt_partial_ltv(p2p_usdc_weth, ongoing_loan_usdc_weth):
    with boa.reverts("not defaulted, ltv lt partial"):
        p2p_usdc_weth.liquidate_loan(ongoing_loan_usdc_weth, EMPTY_REDEEM_RESULT, sender=ongoing_loan_usdc_weth.lender)


def test_liquidate_loan_reverts_if_loan_not_defaulted_and_partial_liquidation_possible(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    loan = ongoing_loan_usdc_weth
    oracle.set_rate(int(oracle.rate() / 2.5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.liquidation_ltv

    liquidator = boa.env.generate_address("liquidator")

    with boa.reverts("not defaulted, partial possible"):
        p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)


def test_liquidate_loan_not_defaulted_works_if_partial_liquidation_not_possible(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    """
    For non-redeemed Securitize loans, liquidation when partial is not possible:
    - Loan is not defaulted but LTV exceeds threshold and partial liquidation can't restore health
    - Third-party liquidator must pay (collateral_value - liquidation_fee) to receive collateral
    - Using lender as liquidator simplifies the test (no payment needed from liquidator)
    """
    loan = ongoing_loan_usdc_weth
    oracle.set_rate(int(oracle.rate() / 5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.liquidation_ltv

    # Use lender as liquidator to avoid needing to fund third party
    # Lender needs to approve protocol fee transfer
    current_interest = loan.get_interest(boa.env.evm.patch.timestamp)
    protocol_fee = loan.protocol_settlement_fee * current_interest // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    liquidation = calc_full_liquidation(loan, usdc, weth, oracle, now)
    lender_weth_before = weth.balanceOf(loan.lender)

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)
    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")
    assert event.id == loan.id

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert weth.balanceOf(loan.lender) == lender_weth_before + liquidation.send_to_liquidator
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_not_defaulted_non_redeemed_by_third_party(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    """
    Covers branch: non-defaulted, non-redeemed, third-party liquidator (liquidator != lender).
    When partial liquidation can't restore health and third party liquidates:
    - Liquidator pays remaining_collateral_value to receive all collateral
    - Lender receives remaining_collateral_value - protocol_fee
    - Shortfall case since oracle rate is very low
    """
    loan = ongoing_loan_usdc_weth
    oracle.set_rate(int(oracle.rate() / 5), sender=oracle.owner())
    current_ltv = calc_ltv(loan.amount, loan.collateral_amount, usdc, weth, oracle)
    assert current_ltv > loan.liquidation_ltv  # precondition

    liquidator = boa.env.generate_address("liquidator")

    # Calculate expected values
    rate_num = oracle.latestRoundData().answer
    rate_den = 10 ** oracle.decimals()
    pay_dec = 10 ** usdc.decimals()
    coll_dec = 10 ** weth.decimals()

    current_interest = loan.get_interest(boa.env.evm.patch.timestamp)
    outstanding_debt = loan.amount + current_interest

    # Non-redeemed: in_vault_payment_token = 0, fee from collateral
    liquidation_fee_value = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = min(
        loan.collateral_amount,
        liquidation_fee_value * rate_den * coll_dec // (rate_num * pay_dec),
    )
    remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    remaining_collateral_value = remaining_collateral * rate_num * pay_dec // (rate_den * coll_dec)
    protocol_settlement_fee_amount = min(
        loan.protocol_settlement_fee * current_interest // BPS,
        remaining_collateral_value,
    )

    # Shortfall: liquidator pays remaining_collateral_value, receives all collateral
    usdc.mint(liquidator, remaining_collateral_value)
    usdc.approve(p2p_usdc_weth.address, remaining_collateral_value, sender=liquidator)

    lender_balance_before = usdc.balanceOf(loan.lender)
    liquidator_weth_before = weth.balanceOf(liquidator)

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert usdc.balanceOf(loan.lender) == lender_balance_before + remaining_collateral_value - protocol_settlement_fee_amount
    assert weth.balanceOf(liquidator) == liquidator_weth_before + loan.collateral_amount

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_non_redeemed_by_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower):
    """
    For non-redeemed Securitize loans liquidated BY THE LENDER:
    - Lender receives collateral directly (different code path)
    - Lender needs to approve protocol fee transfer
    - With very low oracle rate, this is a shortfall case
    - Lender receives full collateral
    """
    loan = ongoing_loan_usdc_weth
    liquidation_time = loan.maturity + 1
    boa.env.time_travel(seconds=liquidation_time - now)

    # Very low rate creates shortfall scenario
    oracle.set_rate(oracle.rate() // 100, sender=oracle.owner())

    # Calculate protocol settlement fee for lender to approve
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    # Lender liquidates their own loan - uses different code path
    lender_weth_before = weth.balanceOf(loan.lender)
    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    assert weth.balanceOf(loan.lender) == lender_weth_before + loan.collateral_amount
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_deletes_loan_state(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now):
    """Verify loan state is deleted after liquidation."""
    loan = ongoing_loan_usdc_weth

    boa.env.time_travel(seconds=loan.maturity - now + 1)

    # Calculate protocol settlement fee for lender to approve
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    # Lender liquidates their own loan (simplest path)
    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32


def test_liquidate_loan_non_redeemed_transfers_collateral_to_lender_liquidator(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    """
    For non-redeemed Securitize loans liquidated by lender:
    - Lender receives collateral_for_debt + liquidation_fee_collateral
    - With high collateral value (surplus case), borrower gets remainder
    """
    loan = ongoing_loan_usdc_weth
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    # With higher oracle rate, collateral value exceeds debt
    oracle.set_rate(oracle.rate() * 2, sender=oracle.owner())

    # Compute expected values matching the contract's exact integer division order.
    # Non-redeemed: in_vault_payment_token = 0, in_vault_collateral = loan.collateral_amount
    # Contract computes liquidation_fee (value) first, then converts to collateral.
    rate_num = oracle.latestRoundData().answer
    rate_den = 10 ** oracle.decimals()
    pay_dec = 10 ** usdc.decimals()
    coll_dec = 10 ** weth.decimals()

    current_interest = loan.get_interest(loan.maturity)
    outstanding_debt = loan.amount + current_interest

    # Contract: liquidation_fee = outstanding_debt * full_liquidation_fee // BPS (in payment value)
    # Then: liquidation_fee_collateral = min(collateral, (fee - 0) * rate_den * coll_dec // (rate_num * pay_dec))
    # Then: liquidation_fee = 0, in_vault_payment_token = 0
    liquidation_fee_value = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = min(
        loan.collateral_amount,
        liquidation_fee_value * rate_den * coll_dec // (rate_num * pay_dec),
    )

    remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    remaining_collateral_value = remaining_collateral * rate_num * pay_dec // (rate_den * coll_dec)
    assert remaining_collateral_value >= outstanding_debt  # precondition: surplus

    collateral_for_debt = outstanding_debt * rate_den * coll_dec // (rate_num * pay_dec)
    protocol_settlement_fee_amount = min(loan.protocol_settlement_fee * current_interest // BPS, remaining_collateral_value)

    # Surplus branch (in_vault_payment_token + remaining_collateral_value >= outstanding_debt):
    # liquidator_collateral_delta = min(collateral_for_debt, remaining_collateral) + liquidation_fee_collateral
    # borrower_collateral_delta = in_vault_collateral - liquidator_collateral_delta
    expected_lender_collateral = min(collateral_for_debt, remaining_collateral) + liquidation_fee_collateral
    expected_borrower_collateral = loan.collateral_amount - expected_lender_collateral
    assert expected_borrower_collateral > 0  # precondition: borrower gets something back

    # Calculate protocol settlement fee for lender to approve
    usdc.approve(p2p_usdc_weth.address, protocol_settlement_fee_amount, sender=loan.lender)

    borrower_weth_balance_before = weth.balanceOf(borrower)
    lender_weth_balance_before = weth.balanceOf(loan.lender)
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Lender liquidates their own loan
    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    # Verify individual collateral distribution with exact expected amounts
    assert weth.balanceOf(loan.lender) == lender_weth_balance_before + expected_lender_collateral
    assert weth.balanceOf(borrower) == borrower_weth_balance_before + expected_borrower_collateral
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_with_shortfall_by_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower):
    """
    For non-redeemed loans with shortfall (low oracle rate) liquidated by lender:
    - Lender receives remaining collateral
    - Borrower receives nothing (no surplus in shortfall case)
    """
    loan = ongoing_loan_usdc_weth
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    oracle.set_rate(oracle.rate() // 4, sender=oracle.owner())

    # For shortfall case, protocol fee is min(fee, remaining_collateral_value)
    # which may be less than the normal calculation. Approve a generous amount.
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    borrower_weth_balance_before = weth.balanceOf(borrower)
    lender_weth_balance_before = weth.balanceOf(loan.lender)
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Lender liquidates to recover what they can
    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    # In shortfall case, lender gets remaining_collateral
    assert weth.balanceOf(loan.lender) == lender_weth_balance_before + loan.collateral_amount
    assert weth.balanceOf(borrower) == borrower_weth_balance_before
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_non_redeemed_lender_receives_payment(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now):
    """
    For non-redeemed loans liquidated by third party:
    - Liquidator pays outstanding_debt - liquidation_fee
    - Lender receives the debt repayment
    """
    loan = ongoing_loan_usdc_weth
    liquidator = boa.env.generate_address("liquidator")
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    oracle.set_rate(oracle.rate() * 2, sender=oracle.owner())

    # Calculate expected payment from liquidator
    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)

    lender_usdc_balance_before = usdc.balanceOf(loan.lender)

    # Fund and approve liquidator
    usdc.mint(liquidator, outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=liquidator)

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    # Lender received payment (minus protocol fee)
    # Non-redeemed surplus: lender_funds_delta = outstanding_debt - protocol_settlement_fee_amount
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    assert usdc.balanceOf(loan.lender) == lender_usdc_balance_before + outstanding_debt - protocol_fee

    vault_addr = p2p_usdc_weth.vault_id_to_vault(loan.borrower, loan.vault_id)
    assert usdc.balanceOf(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_with_shortfall_lender_receives_partial_payment(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now
):
    """
    For non-redeemed loans with shortfall liquidated by third party:
    - Liquidator pays remaining_collateral_value - liquidation_fee
    - Lender receives partial payment (the collateral value minus fee)
    """
    loan = ongoing_loan_usdc_weth
    liquidator = boa.env.generate_address("liquidator")
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    # Set oracle rate to 1/4, creating a shortfall
    oracle.set_rate(oracle.rate() // 4, sender=oracle.owner())

    lender_usdc_balance_before = usdc.balanceOf(loan.lender)

    # Calculate expected values following contract logic for non-redeemed shortfall
    rate_num = oracle.latestRoundData().answer
    rate_den = 10 ** oracle.decimals()
    pay_dec = 10 ** usdc.decimals()
    coll_dec = 10 ** weth.decimals()

    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)
    current_interest = loan.get_interest(loan.maturity)

    # Non-redeemed: in_vault_payment_token = 0, fee taken entirely from collateral
    liquidation_fee_payment = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = min(
        loan.collateral_amount,
        liquidation_fee_payment * rate_den * coll_dec // (rate_num * pay_dec),
    )
    remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    remaining_collateral_value = remaining_collateral * rate_num * pay_dec // (rate_den * coll_dec)
    protocol_settlement_fee_amount = min(
        loan.protocol_settlement_fee * current_interest // BPS,
        remaining_collateral_value,
    )

    # Shortfall branch: liquidator pays remaining_collateral_value
    usdc.mint(liquidator, remaining_collateral_value)
    usdc.approve(p2p_usdc_weth.address, remaining_collateral_value, sender=liquidator)

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    # Shortfall: lender_funds_delta = remaining_collateral_value - protocol_settlement_fee_amount
    assert (
        usdc.balanceOf(loan.lender) == lender_usdc_balance_before + remaining_collateral_value - protocol_settlement_fee_amount
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(loan.borrower, loan.vault_id)
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0


def test_liquidate_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now):
    """
    For non-redeemed loans liquidated by lender:
    - remaining_collateral = in_vault_collateral - liquidation_fee_collateral
      (liquidation fee is taken in collateral since no payment tokens in vault)
    - remaining_collateral_value = remaining_collateral value at oracle rate
    - shortfall = 0 if remaining_collateral_value >= outstanding_debt
    """
    loan = ongoing_loan_usdc_weth
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    oracle.set_rate(int(oracle.rate() * 2), sender=oracle.owner())

    # Calculate protocol settlement fee for lender to approve
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    # Lender liquidates their own loan
    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    # For defaulted loans, interest is calculated up to maturity
    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    payment_token_decimals = 10 ** usdc.decimals()
    collateral_token_decimals = 10 ** weth.decimals()

    # For non-redeemed loans, liquidation_fee is taken from collateral
    # liquidation_fee_collateral = liquidation_fee * (rate.denom / rate.num) * (coll_decimals / pay_decimals)
    liquidation_fee = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = (
        liquidation_fee * oracle_decimals * collateral_token_decimals // (rate * payment_token_decimals)
    )

    # remaining_collateral = in_vault_collateral - liquidation_fee_collateral
    expected_remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    expected_remaining_collateral_value = (
        expected_remaining_collateral * rate * payment_token_decimals // (oracle_decimals * collateral_token_decimals)
    )

    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")
    assert event.id == loan.id
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.liquidator == loan.lender  # Lender is the liquidator
    assert event.outstanding_debt == outstanding_debt
    assert event.remaining_collateral == expected_remaining_collateral
    assert event.remaining_collateral_value == expected_remaining_collateral_value
    # shortfall = 0 if remaining_collateral_value >= outstanding_debt
    if expected_remaining_collateral_value >= outstanding_debt:
        assert event.shortfall == 0
    else:
        assert event.shortfall == outstanding_debt - expected_remaining_collateral_value


def test_liquidate_loan_reverts_if_redeem_not_concluded(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now):
    """Securitize: liquidation of redeemed loan reverts if redeem process not concluded."""
    loan = ongoing_loan_usdc_weth

    # Redeem the loan first
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    # Update loan with redeem_start
    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    # Make loan defaulted
    boa.env.time_travel(seconds=loan.maturity - now + 1)

    # Securitize allows liquidation of redeemed loans once redeem is concluded
    # If redeem is not concluded, it reverts with "redeem not concluded"
    with boa.reverts("redeem not concluded"):
        p2p_usdc_weth.liquidate_loan(redeemed_loan, EMPTY_REDEEM_RESULT, sender=loan.lender)


# ============================================================================
# REDEEMED LOAN LIQUIDATION TESTS
# ============================================================================


@pytest.fixture
def redeemed_loan_with_payment(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    borrower,
    now,
    owner_key,
    securitize_redemption_wallet,
):
    """
    Create a redeemed loan where the vault has payment tokens from redemption.
    Simulates: borrower redeems collateral, Securitize converts to payment token.
    """
    loan = ongoing_loan_usdc_weth

    # Redeem the loan (sends collateral to redemption wallet)
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    # Update loan state to reflect redemption
    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    # Get the vault address for this loan
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Calculate payment amount from redemption (simulate full conversion at good rate)
    # Outstanding debt at maturity + liquidation fee + some surplus
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    liquidation_fee = outstanding_debt_at_maturity * loan.full_liquidation_fee // BPS
    payment_redeemed = outstanding_debt_at_maturity + liquidation_fee + 100 * 10**6  # surplus

    # Mint payment tokens to vault (simulating Securitize redemption)
    usdc.mint(vault_addr, payment_redeemed)

    # Create signed redeem result
    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,  # All collateral was converted to payment
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,  # After redeem_start
    )

    return redeemed_loan, redeem_result, payment_redeemed


@pytest.fixture
def redeemed_loan_with_collateral(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    borrower,
    now,
    owner_key,
    securitize_redemption_wallet,
):
    """
    Create a redeemed loan where the vault has both payment tokens and residual collateral.
    """
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 4  # Keep 25% as collateral

    # Redeem the loan with residual collateral
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)

    # Update loan state to reflect redemption
    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )

    # Get the vault address for this loan
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Partial payment from redemption (covers part of debt)
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity // 2  # 50% of debt

    # Mint payment tokens to vault
    usdc.mint(vault_addr, payment_redeemed)

    # Create redeem result
    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,  # collateral_redeemed is from redemption, not residual
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,
    )

    return redeemed_loan, redeem_result, payment_redeemed, residual_collateral


def test_liquidate_redeemed_loan_with_surplus_pays_all_parties(
    p2p_usdc_weth,
    redeemed_loan_with_payment,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
):
    """
    Redeemed loan with payment surplus (no residual collateral):
    - in_vault_payment_token (after liquidation_fee deduction) >= outstanding_debt
    - in_vault_collateral = 0, so remaining_collateral_value = 0
    - protocol_settlement_fee_amount = min(fee, in_vault_payment_token + remaining_collateral_value)
    - Lender receives outstanding_debt - protocol_fee
    - Protocol receives protocol_fee
    - Liquidator receives liquidation_fee
    - Borrower receives surplus
    """
    redeemed_loan, redeem_result, payment_redeemed = redeemed_loan_with_payment
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )
    assert liq.in_vault_payment_token >= liq.outstanding_debt  # precondition: surplus scenario

    # Get balances before liquidation
    lender_balance_before = usdc.balanceOf(redeemed_loan.lender)
    borrower_balance_before = usdc.balanceOf(borrower)
    protocol_balance_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())
    liquidator_balance_before = usdc.balanceOf(liquidator)

    # Liquidate
    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Verify distributions
    assert usdc.balanceOf(redeemed_loan.lender) == lender_balance_before + liq.lender_funds_delta
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_balance_before + liq.protocol_settlement_fee_amount
    assert usdc.balanceOf(liquidator) == liquidator_balance_before + liq.liquidator_funds_delta
    assert usdc.balanceOf(borrower) == borrower_balance_before + liq.borrower_funds_delta

    vault_addr = p2p_usdc_weth.vault_id_to_vault(redeemed_loan.borrower, redeemed_loan.vault_id)
    assert usdc.balanceOf(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_redeemed_loan_with_collateral_and_payment(
    p2p_usdc_weth,
    redeemed_loan_with_collateral,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
):
    """
    Redeemed loan with partial payment and residual collateral:
    - Liquidator pays shortfall and receives collateral
    """
    redeemed_loan, redeem_result, payment_redeemed, residual_collateral = redeemed_loan_with_collateral
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=residual_collateral,
    )
    # Precondition: scenario 2 (payment + collateral cover debt)
    assert liq.in_vault_payment_token < liq.outstanding_debt
    assert liq.in_vault_payment_token + liq.remaining_collateral_value >= liq.outstanding_debt

    liquidator_collateral_before = weth.balanceOf(liquidator)
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, redeemed_loan.vault_id)

    # Fund liquidator (overfund to ensure sufficient)
    usdc.mint(liquidator, liq.outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, liq.outstanding_debt, sender=liquidator)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Verify loan is deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Verify liquidator received exact collateral amount
    assert weth.balanceOf(liquidator) == liquidator_collateral_before + liq.liquidator_collateral_delta
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0


def test_liquidate_redeemed_loan_logs_event_with_correct_values(
    p2p_usdc_weth,
    redeemed_loan_with_payment,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
):
    """Verify LoanLiquidated event has correct values for redeemed loan with surplus."""
    redeemed_loan, redeem_result, payment_redeemed = redeemed_loan_with_payment
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")
    assert event.id == redeemed_loan.id
    assert event.borrower == redeemed_loan.borrower
    assert event.lender == redeemed_loan.lender
    assert event.liquidator == liquidator
    assert event.outstanding_debt == liq.outstanding_debt
    assert event.remaining_collateral == liq.remaining_collateral
    assert event.remaining_collateral_value == liq.remaining_collateral_value
    # shortfall is based on collateral value, NOT payment tokens
    assert event.shortfall == liq.shortfall
    assert event.protocol_settlement_fee_amount == liq.protocol_settlement_fee_amount


def test_liquidate_redeemed_loan_with_shortfall(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Redeemed loan where payment + collateral value < outstanding_debt:
    - Shortfall case
    - Lender receives less than full debt
    - Note: When liquidator != lender and there's no collateral, the contract's shortfall
      branch would underflow. So we use lender as liquidator for this scenario.
    """
    loan = ongoing_loan_usdc_weth

    # Redeem with no residual collateral
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    # Capture actual timestamp after redeem (contract uses block.timestamp)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Small payment (much less than debt) - creates shortfall
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity // 10  # Only 10% of debt

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,  # After redeem_start
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )
    assert liq.shortfall > 0  # precondition: shortfall scenario

    # For shortfall with no collateral, use lender as liquidator to avoid underflow
    usdc.approve(p2p_usdc_weth.address, 0, sender=loan.lender)

    # Verify loan hash matches before liquidation
    assert compute_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

    lender_balance_before = usdc.balanceOf(loan.lender)
    protocol_wallet = p2p_usdc_weth.protocol_wallet()
    protocol_balance_before = usdc.balanceOf(protocol_wallet)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Since liquidator == lender: net = lender_funds_delta + liquidator_funds_delta
    expected_lender_net = liq.lender_funds_delta + liq.liquidator_funds_delta

    assert usdc.balanceOf(loan.lender) == lender_balance_before + expected_lender_net
    assert usdc.balanceOf(protocol_wallet) == protocol_balance_before + liq.protocol_settlement_fee_amount

    vault_addr = p2p_usdc_weth.vault_id_to_vault(loan.borrower, loan.vault_id)
    assert usdc.balanceOf(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_redeemed_loan_not_defaulted_uses_adjusted_ltv(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Scenario:
    - Loan: 1 WETH collateral (~3877 USDC value), 1000 USDC principal
    - Redemption: 75% collateral redeemed, 25% residual (0.25 WETH, ~969 USDC value)
    - Payment from redemption: 10 USDC (tiny)
    - Original LTV: 1000 / 3877 ~ 26% < 60% threshold → rejected
    - Adjusted LTV: (1000 - 10) / 969 ~ 102% > 60% threshold → allowed
    """
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 4  # Keep 25%

    # Redeem the loan
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Small payment from redemption (10 USDC vs ~1000 USDC debt)
    payment_redeemed = 10 * 10**6
    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Verify loan hash matches
    assert compute_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

    # Loan is NOT defaulted (before maturity).
    # With the fix, the non-defaulted path uses remaining collateral and net debt for LTV:
    #   LTV = (debt - payment) / remaining_collateral_value ~ 102% > 60% → passes
    # Before the fix, it used original values:
    #   LTV = debt / original_collateral_value ~ 26% < 60% → reverted "not defaulted, ltv lt partial"

    # Lender as liquidator (simplest path for shortfall case)
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(boa.env.evm.patch.timestamp) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)

    # Verify liquidation succeeded (loan state deleted)
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32


def test_liquidate_redeemed_loan_not_defaulted_zero_collateral_with_remaining_debt(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Scenario: All collateral redeemed, partial payment from redemption, loan not defaulted.
    - Loan: 1 WETH collateral, 1000 USDC principal
    - Redemption: ALL collateral redeemed (redeem_residual_collateral=0)
    - Payment from redemption: 500 USDC (less than outstanding debt ~1000 USDC)
    - in_vault_collateral = 0, so current_ltv = 0

    Before the fix: current_ltv (0) >= liquidation_ltv (6000) was always FALSE,
      so it reverted with "not defaulted, ltv lt partial" even though the position
      was effectively unsecured debt.
    After the fix: when current_ltv == 0, the code checks if remaining debt > 0
      (i.e. loan.amount + interest > in_vault_payment_token) and allows liquidation.
    """
    loan = ongoing_loan_usdc_weth

    # Redeem ALL collateral (no residual)
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Payment from redemption covers only ~50% of debt
    outstanding_debt = loan.amount + loan.get_interest(boa.env.evm.patch.timestamp)
    payment_redeemed = outstanding_debt // 2
    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Verify loan hash matches
    assert compute_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

    # Loan is NOT defaulted (before maturity)
    # in_vault_collateral = 0 → current_ltv = 0
    # remaining debt = outstanding_debt - payment_redeemed > 0 → should allow liquidation
    # Use lender as liquidator (simplest path for no-collateral case)
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(boa.env.evm.patch.timestamp) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)

    # Verify liquidation succeeded
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32


def test_liquidate_redeemed_loan_not_defaulted_zero_collateral_no_remaining_debt_reverts(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Scenario: All collateral redeemed, payment from redemption covers entire debt.
    - in_vault_collateral = 0, so current_ltv = 0
    - in_vault_payment_token >= outstanding_debt, so no remaining debt
    - Should revert with "not defaulted, no debt" (position is fully covered)
    """
    loan = ongoing_loan_usdc_weth

    # Redeem ALL collateral (no residual)
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Payment from redemption covers MORE than the outstanding debt
    outstanding_debt = loan.amount + loan.get_interest(boa.env.evm.patch.timestamp)
    liquidation_fee = outstanding_debt * loan.full_liquidation_fee // BPS
    payment_redeemed = outstanding_debt + liquidation_fee + 100 * 10**6  # surplus
    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Verify loan hash matches
    assert compute_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

    # Loan is NOT defaulted, no collateral, but payment covers debt → no liquidation needed
    with boa.reverts("not defaulted, no debt"):
        p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)


def test_liquidate_redeemed_loan_by_lender(
    p2p_usdc_weth,
    redeemed_loan_with_payment,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
):
    """
    When lender is the liquidator, special handling applies in the contract.
    For surplus case: lender receives debt + liquidation_fee - protocol_fee, protocol gets fee, borrower gets surplus.
    """
    redeemed_loan, redeem_result, payment_redeemed = redeemed_loan_with_payment
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )
    assert liq.in_vault_payment_token >= liq.outstanding_debt  # precondition: surplus scenario

    lender_balance_before = usdc.balanceOf(redeemed_loan.lender)
    protocol_balance_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())
    borrower_balance_before = usdc.balanceOf(borrower)

    # Lender liquidates their own loan
    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.lender)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # For lender as liquidator: combined = lender_funds_delta + liquidator_funds_delta
    expected_lender_net = liq.lender_funds_delta + liq.liquidator_funds_delta
    assert usdc.balanceOf(redeemed_loan.lender) == lender_balance_before + expected_lender_net
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_balance_before + liq.protocol_settlement_fee_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + liq.borrower_funds_delta

    vault_addr = p2p_usdc_weth.vault_id_to_vault(redeemed_loan.borrower, redeemed_loan.vault_id)
    assert usdc.balanceOf(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_loan_reverts_if_oracle_answer_zero(p2p_usdc_weth, ongoing_loan_usdc_weth, oracle, owner, now):
    loan = ongoing_loan_usdc_weth

    # Default the loan first
    boa.env.time_travel(seconds=loan.maturity - now + 1)

    oracle.set_rate(0, sender=owner)

    with boa.reverts("invalid oracle rate"):
        p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)


def test_liquidate_redeemed_loan_lender_receives_redeemed_payment(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    ZHAR3-6: Lenders are at risk of losing their funds if they liquidate their
    loan which was previously redeemed.

    Scenario:
    - Borrower redeems 100% of collateral for 99% of the debt
    - No residual collateral remains
    - Lender calls liquidate_loan() as the liquidator
    - Falls into the shortfall else branch because
      in_vault_payment_token + remaining_collateral_value (0) < outstanding_debt

    Bug: In the shortfall branch when liquidator == lender, the contract only
    sends liquidation_fee to the lender. The in_vault_payment_token withdrawn
    from the vault is never sent, causing the lender to lose those funds.

    Expected: lender receives in_vault_payment_token + liquidation_fee
    """
    loan = ongoing_loan_usdc_weth

    # Redeem with no residual collateral
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Payment from redemption: 99% of debt (creates shortfall)
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity * 99 // 100

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # lender is the liquidator
    liquidator = redeemed_loan.lender

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )
    # Verify we're in the shortfall branch
    assert liq.in_vault_payment_token < liq.outstanding_debt
    assert liq.in_vault_payment_token + liq.remaining_collateral_value < liq.outstanding_debt

    liquidator_collateral_before = weth.balanceOf(liquidator)
    usdc.approve(p2p_usdc_weth.address, liq.outstanding_debt, sender=liquidator)
    liquidator_payment_before = usdc.balanceOf(liquidator)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    collateral_received = weth.balanceOf(liquidator) - liquidator_collateral_before
    payment_received = usdc.balanceOf(liquidator) - liquidator_payment_before

    assert collateral_received == 0

    # Lender (as liquidator): combined = lender_funds_delta + liquidator_funds_delta
    expected_payment = liq.lender_funds_delta + liq.liquidator_funds_delta
    assert expected_payment > 0
    assert payment_received == expected_payment, (
        f"Lender should receive {expected_payment} payment tokens (redeemed from vault) but received {payment_received}"
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(loan.borrower, loan.vault_id)
    assert usdc.balanceOf(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0


@pytest.fixture
def redeemed_loan_zhar3_2(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    borrower,
    now,
    owner_key,
    securitize_redemption_wallet,
):
    """
    ZHAR3-2 PoC: Redeemed loan with 101% of debt as payment and 50% residual collateral.
    This triggers an underflow in liquidate_loan when a third-party liquidator tries to liquidate.
    """
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 2  # Keep 50% as collateral

    # Redeem the loan with residual collateral
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)

    # Update loan state to reflect redemption
    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )

    # Get the vault address for this loan
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Partial payment from redemption: 101% of debt
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity * 101 // 100  # 101% of debt

    # Mint payment tokens to vault
    usdc.mint(vault_addr, payment_redeemed)

    # Create redeem result
    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,  # collateral_redeemed is from redemption, not residual
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,
    )

    return redeemed_loan, redeem_result, payment_redeemed, residual_collateral


def test_liquidate_redeemed_loan_no_underflow_when_payment_covers_debt(
    p2p_usdc_weth,
    redeemed_loan_zhar3_2,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
):
    """
    ZHAR3-2: Loan liquidation underflow could lead to frozen assets.

    When a redeemed loan has payment tokens covering 101% of the debt and a 3% liquidation fee,
    the _receive_funds call in the elif branch computes:
      outstanding_debt - in_vault_payment_token - liquidation_fee
    where in_vault_payment_token = payment_redeemed - liquidation_fee = 98% of debt
    and liquidation_fee = 3% of debt, causing:
      100% - 98% - 3% = -1% -> underflow/revert

    This makes the loan permanently unliquidatable by third-party liquidators.
    """
    redeemed_loan, redeem_result, _, _ = redeemed_loan_zhar3_2
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    # Calculate expected values
    outstanding_debt = redeemed_loan.amount + redeemed_loan.get_interest(redeemed_loan.maturity)

    # Fund liquidator with enough to cover the debt
    usdc.mint(liquidator, outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=liquidator)

    # This call should succeed but will revert due to underflow if ZHAR3-2 is present
    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)


def test_liquidate_non_redeemed_shortfall_third_party_exact_balances(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    """
    Non-redeemed loan, shortfall, third-party liquidator:
    Verifies the liquidation_fee_collateral is NOT stranded in the vault.
    With the fix, the liquidator receives all collateral (including fee portion)
    and the vault is fully emptied.

    Branch 3 (shortfall): remaining_collateral_value < outstanding_debt
    - liquidator_collateral_delta = in_vault_collateral (all collateral)
    - borrower_collateral_delta = 0
    - No collateral left in vault
    """
    loan = ongoing_loan_usdc_weth
    liquidator = boa.env.generate_address("liquidator")
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    # Set low oracle rate to create shortfall
    oracle.set_rate(oracle.rate() // 4, sender=oracle.owner())

    # Get oracle parameters for manual calculations
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    payment_token_decimals = 10 ** usdc.decimals()
    collateral_token_decimals = 10 ** weth.decimals()

    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)
    current_interest = loan.get_interest(loan.maturity)

    # Non-redeemed: in_vault_payment_token = 0, in_vault_collateral = loan.collateral_amount
    # Liquidation fee is taken from collateral
    liquidation_fee = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = min(
        loan.collateral_amount,
        liquidation_fee * oracle_decimals * collateral_token_decimals // (rate * payment_token_decimals),
    )

    remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    remaining_collateral_value = (
        remaining_collateral * rate * payment_token_decimals // (oracle_decimals * collateral_token_decimals)
    )
    assert remaining_collateral_value < outstanding_debt  # confirm shortfall

    protocol_settlement_fee_amount = min(
        loan.protocol_settlement_fee * current_interest // BPS,
        0 + remaining_collateral_value,  # in_vault_payment_token = 0
    )

    # Branch 3 deltas (shortfall, third-party liquidator, non-redeemed):
    # lender_funds_delta = 0 + remaining_collateral_value - protocol_fee
    # liquidator_funds_delta = liquidation_fee - remaining_collateral_value (negative: liquidator pays)
    # liquidator_collateral_delta = in_vault_collateral (ALL collateral)
    # borrower_collateral_delta = 0

    # Fund liquidator
    usdc.mint(liquidator, outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=liquidator)

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    lender_usdc_before = usdc.balanceOf(loan.lender)
    lender_weth_before = weth.balanceOf(loan.lender)
    borrower_usdc_before = usdc.balanceOf(borrower)
    borrower_weth_before = weth.balanceOf(borrower)
    liquidator_usdc_before = usdc.balanceOf(liquidator)
    liquidator_weth_before = weth.balanceOf(liquidator)
    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32

    # Verify vault is completely empty (no stranded funds)
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0

    # Verify lender received payment (remaining collateral value minus protocol fee)
    assert usdc.balanceOf(loan.lender) == lender_usdc_before + remaining_collateral_value - protocol_settlement_fee_amount

    # Verify protocol received fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + protocol_settlement_fee_amount

    # Verify borrower received nothing
    assert usdc.balanceOf(borrower) == borrower_usdc_before
    assert weth.balanceOf(borrower) == borrower_weth_before

    # Verify liquidator received ALL collateral (including liquidation_fee_collateral)
    assert weth.balanceOf(liquidator) == liquidator_weth_before + loan.collateral_amount

    # Verify lender received no collateral (shortfall case)
    assert weth.balanceOf(loan.lender) == lender_weth_before

    # Verify liquidator USDC balance: for non-redeemed shortfall, liquidation_fee (payment token) = 0
    # after the contract's fee-split logic (full fee goes to collateral), so liquidator_funds_delta = -remaining_collateral_value.  # noqa: E501
    # Liquidator pays remaining_collateral_value (which goes to lender/protocol) and receives no payment tokens back.
    assert usdc.balanceOf(liquidator) == liquidator_usdc_before - remaining_collateral_value


def test_liquidate_non_redeemed_surplus_third_party_exact_balances(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    """
    Non-redeemed loan, no shortfall, third-party liquidator:
    Verifies correct fund distribution when collateral value exceeds debt.

    Branch 2 (combined coverage): in_vault_payment_token + remaining_collateral_value >= outstanding_debt
    For non-redeemed: in_vault_payment_token = 0, liquidation_fee taken entirely from collateral
    - After fee block: liquidation_fee (payment) = 0, fee is in liquidation_fee_collateral
    - Liquidator pays full outstanding_debt and receives collateral (debt + fee portions)
    - Borrower receives remaining collateral
    """
    loan = ongoing_loan_usdc_weth
    liquidator = boa.env.generate_address("liquidator")
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    # Double oracle rate so collateral value exceeds debt
    oracle.set_rate(oracle.rate() * 2, sender=oracle.owner())

    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    payment_token_decimals = 10 ** usdc.decimals()
    collateral_token_decimals = 10 ** weth.decimals()

    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)
    current_interest = loan.get_interest(loan.maturity)

    # For non-redeemed: in_vault_payment_token = 0, fee goes to else branch
    # liquidation_fee_collateral = fee converted to collateral
    # liquidation_fee (payment tokens) becomes 0
    liquidation_fee_raw = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = min(
        loan.collateral_amount,
        liquidation_fee_raw * oracle_decimals * collateral_token_decimals // (rate * payment_token_decimals),
    )

    remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    remaining_collateral_value = (
        remaining_collateral * rate * payment_token_decimals // (oracle_decimals * collateral_token_decimals)
    )
    assert remaining_collateral_value >= outstanding_debt  # no shortfall

    collateral_for_debt = outstanding_debt * oracle_decimals * collateral_token_decimals // (rate * payment_token_decimals)

    protocol_settlement_fee_amount = min(
        loan.protocol_settlement_fee * current_interest // BPS,
        0 + remaining_collateral_value,  # in_vault_payment_token = 0
    )

    # Branch 2 deltas (after fee block: liquidation_fee=0, in_vault_payment_token=0):
    # liquidator_funds_delta = 0 + 0 - outstanding_debt = -outstanding_debt (liquidator pays)
    # liquidator_collateral_delta = min(collateral_for_debt, remaining_collateral) + liq_fee_collateral
    # borrower_collateral_delta = in_vault_collateral - liquidator_collateral_delta

    liquidator_collateral_delta = min(collateral_for_debt, remaining_collateral) + liquidation_fee_collateral
    borrower_collateral_delta = (
        loan.collateral_amount - liquidator_collateral_delta if loan.collateral_amount > liquidator_collateral_delta else 0
    )

    # Fund liquidator
    usdc.mint(liquidator, outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=liquidator)

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    lender_usdc_before = usdc.balanceOf(loan.lender)
    borrower_weth_before = weth.balanceOf(borrower)
    liquidator_usdc_before = usdc.balanceOf(liquidator)
    liquidator_weth_before = weth.balanceOf(liquidator)
    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    # Verify vault is completely empty
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0

    # Verify lender received outstanding_debt - protocol_fee
    assert usdc.balanceOf(loan.lender) == lender_usdc_before + outstanding_debt - protocol_settlement_fee_amount

    # Verify protocol received fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + protocol_settlement_fee_amount

    # Verify liquidator paid full outstanding_debt (fee is in collateral, not payment tokens)
    assert usdc.balanceOf(liquidator) == liquidator_usdc_before - outstanding_debt
    # Verify liquidator received collateral_for_debt + liquidation_fee_collateral
    assert weth.balanceOf(liquidator) == liquidator_weth_before + liquidator_collateral_delta

    # Verify borrower received surplus collateral
    assert weth.balanceOf(borrower) == borrower_weth_before + borrower_collateral_delta


def test_liquidate_redeemed_combined_coverage_third_party_exact_balances(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Redeemed loan, branch 2 (payment + collateral cover debt), third-party liquidator:
    Verifies the ZHAR3-2 fix with exact balance verification for ALL parties.

    Setup: 80% of debt as payment tokens + 50% residual collateral
    The combined value covers the debt. Liquidator receives surplus payment.
    """
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 2

    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity * 80 // 100  # 80% of debt

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=residual_collateral,
    )
    # Confirm we're in branch 2
    assert liq.in_vault_payment_token < liq.outstanding_debt
    assert liq.in_vault_payment_token + liq.remaining_collateral_value >= liq.outstanding_debt

    # Fund liquidator
    usdc.mint(liquidator, liq.outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, liq.outstanding_debt, sender=liquidator)

    lender_usdc_before = usdc.balanceOf(redeemed_loan.lender)
    borrower_usdc_before = usdc.balanceOf(borrower)
    borrower_weth_before = weth.balanceOf(borrower)
    liquidator_usdc_before = usdc.balanceOf(liquidator)
    liquidator_weth_before = weth.balanceOf(liquidator)
    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Verify vault is completely empty
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0

    # Verify lender received outstanding_debt - protocol_fee
    assert usdc.balanceOf(redeemed_loan.lender) == lender_usdc_before + liq.lender_funds_delta

    # Verify protocol received fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + liq.protocol_settlement_fee_amount

    # Verify liquidator balance changes
    assert usdc.balanceOf(liquidator) == liquidator_usdc_before + liq.liquidator_funds_delta
    assert weth.balanceOf(liquidator) == liquidator_weth_before + liq.liquidator_collateral_delta

    # Verify borrower received surplus collateral
    assert weth.balanceOf(borrower) == borrower_weth_before + liq.borrower_collateral_delta
    assert usdc.balanceOf(borrower) == borrower_usdc_before  # no payment surplus in branch 2


def test_liquidate_redeemed_shortfall_third_party_exact_balances(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Redeemed loan, branch 3 (shortfall), third-party liquidator:
    Verifies correct fund distribution when payment + collateral < debt.
    This is the scenario where the old code could underflow for third-party liquidators.

    Setup: 30% of debt as payment tokens, no residual collateral.
    """
    loan = ongoing_loan_usdc_weth

    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity * 30 // 100  # 30% of debt

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )
    # Confirm we're in branch 3 (shortfall)
    assert liq.in_vault_payment_token + liq.remaining_collateral_value < liq.outstanding_debt

    lender_usdc_before = usdc.balanceOf(redeemed_loan.lender)
    borrower_usdc_before = usdc.balanceOf(borrower)
    liquidator_usdc_before = usdc.balanceOf(liquidator)
    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Verify vault is completely empty
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0

    # Verify lender received partial payment
    assert usdc.balanceOf(redeemed_loan.lender) == lender_usdc_before + liq.lender_funds_delta

    # Verify protocol received fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + liq.protocol_settlement_fee_amount

    # Verify liquidator received liquidation fee (from withdrawn vault payment tokens)
    assert usdc.balanceOf(liquidator) == liquidator_usdc_before + liq.liquidator_funds_delta

    # Verify borrower received nothing
    assert usdc.balanceOf(borrower) == borrower_usdc_before


def test_liquidate_redeemed_surplus_protocol_fee_properly_applied(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Protocol settlement fee fix verification:
    With the old code, protocol_settlement_fee_amount = min(fee, remaining_collateral_value).
    For redeemed loans with no collateral, remaining_collateral_value = 0, so protocol got nothing.
    With the fix, protocol_settlement_fee_amount = min(fee, in_vault_payment_token + remaining_collateral_value),
    so the protocol correctly receives its fee from the payment tokens.

    This test explicitly verifies that:
    1. protocol_settlement_fee_amount > 0 for redeemed loans with payment tokens
    2. The fee is properly deducted from the lender's share
    3. The protocol wallet receives the fee
    """
    loan = ongoing_loan_usdc_weth

    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Payment covers more than the debt + fee
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    liquidation_fee = outstanding_debt_at_maturity * loan.full_liquidation_fee // BPS
    payment_redeemed = outstanding_debt_at_maturity + liquidation_fee + 200 * 10**6

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=0,
    )

    # Key assertion: protocol fee MUST be non-zero
    assert liq.protocol_settlement_fee_amount > 0, "Protocol fee should be non-zero for redeemed loans with payment tokens"

    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())
    lender_usdc_before = usdc.balanceOf(redeemed_loan.lender)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Protocol wallet received the fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + liq.protocol_settlement_fee_amount

    # Lender receives outstanding_debt minus protocol fee (NOT full outstanding_debt)
    assert usdc.balanceOf(redeemed_loan.lender) == lender_usdc_before + liq.lender_funds_delta

    # Vault is empty
    assert usdc.balanceOf(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0


def test_liquidate_redeemed_combined_coverage_lender_as_liquidator(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """
    Redeemed loan, branch 2, lender-as-liquidator:
    When lender == liquidator, the contract combines lender_funds_delta and liquidator_funds_delta.
    The net amount should be: outstanding_debt - protocol_fee + liquidation_fee + in_vault_payment - outstanding_debt
                            = in_vault_payment + liquidation_fee - protocol_fee
                            = payment_redeemed - protocol_fee

    Setup: 80% of debt as payment tokens + 25% residual collateral (covers debt).
    """
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 4

    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    payment_redeemed = outstanding_debt_at_maturity * 80 // 100

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    liq = calc_full_liquidation_redeemed(
        redeemed_loan,
        usdc,
        weth,
        oracle,
        in_vault_payment_token=payment_redeemed,
        in_vault_collateral=residual_collateral,
    )
    # Confirm branch 2
    assert liq.in_vault_payment_token < liq.outstanding_debt
    assert liq.in_vault_payment_token + liq.remaining_collateral_value >= liq.outstanding_debt

    lender_usdc_before = usdc.balanceOf(redeemed_loan.lender)
    lender_weth_before = weth.balanceOf(redeemed_loan.lender)
    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())
    borrower_weth_before = weth.balanceOf(borrower)

    # Lender might need to pay if combined is negative, or receive if positive
    usdc.approve(p2p_usdc_weth.address, liq.outstanding_debt, sender=redeemed_loan.lender)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.lender)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Verify vault is completely empty
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0

    # Verify lender (as liquidator) received combined amount
    expected_combined = liq.lender_funds_delta + liq.liquidator_funds_delta
    assert usdc.balanceOf(redeemed_loan.lender) == lender_usdc_before + expected_combined

    # Verify protocol received fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + liq.protocol_settlement_fee_amount

    # Verify lender received collateral
    assert weth.balanceOf(redeemed_loan.lender) == lender_weth_before + liq.liquidator_collateral_delta
    assert weth.balanceOf(borrower) == borrower_weth_before + liq.borrower_collateral_delta


def test_liquidate_non_redeemed_shortfall_lender_gets_all_collateral(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower
):
    """
    Non-redeemed shortfall, lender-as-liquidator:
    - liquidator_collateral_delta = in_vault_collateral (ALL collateral)
    - lender (as liquidator) receives everything
    - Vault is completely empty
    """
    loan = ongoing_loan_usdc_weth
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    # Low oracle rate creates shortfall
    oracle.set_rate(oracle.rate() // 4, sender=oracle.owner())

    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    ptd = 10 ** usdc.decimals()
    ctd = 10 ** weth.decimals()

    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)
    current_interest = loan.get_interest(loan.maturity)

    liquidation_fee_raw = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = min(
        loan.collateral_amount,
        liquidation_fee_raw * oracle_decimals * ctd // (rate * ptd),
    )

    remaining_collateral = loan.collateral_amount - liquidation_fee_collateral
    remaining_collateral_value = remaining_collateral * rate * ptd // (oracle_decimals * ctd)
    assert remaining_collateral_value < outstanding_debt  # confirm shortfall

    protocol_settlement_fee_amount = min(
        loan.protocol_settlement_fee * current_interest // BPS,
        remaining_collateral_value,
    )

    # For lender-as-liquidator in shortfall:
    # lender_funds_delta = 0 + remaining_collateral_value - protocol_fee
    # liquidator_funds_delta = liquidation_fee - remaining_collateral_value
    # Combined: liquidation_fee - protocol_fee
    # liquidator_collateral_delta = loan.collateral_amount (ALL collateral)

    # Lender may need to pay if combined is negative
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=loan.lender)

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    lender_weth_before = weth.balanceOf(loan.lender)
    lender_usdc_before = usdc.balanceOf(loan.lender)
    borrower_weth_before = weth.balanceOf(borrower)
    protocol_usdc_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    # KEY ASSERTION: Lender gets ALL collateral (not just remaining_collateral)
    assert weth.balanceOf(loan.lender) == lender_weth_before + loan.collateral_amount

    # Vault is completely empty - no stranded liquidation_fee_collateral
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0

    # Borrower gets nothing in shortfall
    assert weth.balanceOf(borrower) == borrower_weth_before

    # Protocol receives fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_usdc_before + protocol_settlement_fee_amount

    # Lender (as liquidator) net USDC change: combined delta = -protocol_settlement_fee_amount
    # non-redeemed: liquidation_fee=0, so combined = 0 - remaining_collateral_value + remaining_collateral_value - protocol_fee
    assert usdc.balanceOf(loan.lender) == lender_usdc_before - protocol_settlement_fee_amount


def test_liquidate_loan_reverts_if_invalid_redeem_payment_amount(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """Liquidating a redeemed loan reverts when redeem_result.payment_redeemed exceeds vault's payment token balance."""
    loan = ongoing_loan_usdc_weth

    # Redeem the loan (sends all collateral to redemption wallet)
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Mint some payment tokens to vault (simulating partial redemption)
    actual_payment = 100 * 10**6
    usdc.mint(vault_addr, actual_payment)

    # Create redeem result that claims more payment than vault has
    inflated_redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=actual_payment + 1,  # more than vault holds
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(inflated_redeem_result, owner_key)

    # Preconditions
    assert usdc.balanceOf(vault_addr) < inflated_redeem_result.payment_redeemed
    assert redeemed_loan.redeem_start > 0  # loan is redeemed

    # Make loan defaulted so we can liquidate
    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    with boa.reverts("invalid redeem payment amount"):
        p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)


def test_liquidate_loan_reverts_if_invalid_redeem_collateral_amnt(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    usdc,
    weth,
    oracle,
    now,
    owner_key,
    borrower,
    securitize_redemption_wallet,
):
    """Liquidating a redeemed loan reverts when redeem_result.collateral_redeemed + residual exceeds vault's collateral."""
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 2  # Keep 50% as residual

    # Redeem with residual collateral
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)

    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Mint some payment tokens to vault (simulating redemption)
    usdc.mint(vault_addr, loan.amount)

    # The vault's withdrawable_balance should be residual_collateral (the collateral that stayed)
    # The contract checks: withdrawable_balance >= loan.redeem_residual_collateral + redeem_result.collateral_redeemed
    # Claim more collateral_redeemed than what the vault actually holds minus residual
    vault_collateral_balance = weth.balanceOf(vault_addr)
    inflated_collateral_redeemed = vault_collateral_balance - residual_collateral + 1

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=inflated_collateral_redeemed,
        payment_redeemed=loan.amount,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Precondition: the sum exceeds what the vault holds
    assert residual_collateral + inflated_collateral_redeemed > vault_collateral_balance

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    with boa.reverts("invalid redeem collateral amnt"):
        p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)
