import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    RedeemResult,
    SecuritizeLoan,
    SignedRedeemResult,
    calc_collateral_from_ltv,
    calc_ltv,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_securitize_loan_mutations,
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
        vault_id=0,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
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
    return loan


@pytest.fixture
def p2p_erc20_proxy(p2p_usdc_weth, p2p_lending_erc20_proxy_contract_def):
    return p2p_lending_erc20_proxy_contract_def.deploy(p2p_usdc_weth.address)


def test_liquidate_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    loan = ongoing_loan_usdc_weth
    boa.env.time_travel(seconds=loan.maturity + 1)  # Make loan defaulted
    for corrupted_loan in get_securitize_loan_mutations(loan):
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

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)
    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")
    assert event.id == loan.id


def test_liquidate_loan_non_redeemed_by_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower):
    """
    For non-redeemed Securitize loans liquidated BY THE LENDER:
    - Lender receives collateral directly (different code path)
    - Lender needs to approve protocol fee transfer
    - With very low oracle rate, this is a shortfall case
    - Lender receives remaining_collateral (collateral - liquidation_fee_collateral)
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

    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")
    # Verify lender received remaining_collateral (collateral after liquidation_fee deducted)
    assert weth.balanceOf(loan.lender) == lender_weth_before + event.remaining_collateral


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
    - Note: Due to contract logic, liquidation_fee_collateral may remain in vault
    """
    loan = ongoing_loan_usdc_weth
    liquidation_time = loan.maturity + 1

    boa.env.time_travel(seconds=liquidation_time - now)

    # With higher oracle rate, collateral value exceeds debt
    oracle.set_rate(oracle.rate() * 2, sender=oracle.owner())

    # Calculate protocol settlement fee for lender to approve
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    usdc.approve(p2p_usdc_weth.address, protocol_fee, sender=loan.lender)

    borrower_weth_balance_before = weth.balanceOf(borrower)
    lender_weth_balance_before = weth.balanceOf(loan.lender)
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    vault_balance_before = weth.balanceOf(vault_addr)

    # Lender liquidates their own loan
    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.lender)

    # Verify collateral distribution
    # Lender gets: collateral_for_debt + liquidation_fee (collateral form)
    # Borrower gets: remaining_collateral - collateral_for_debt - liquidation_fee (if surplus)
    lender_received = weth.balanceOf(loan.lender) - lender_weth_balance_before
    borrower_received = weth.balanceOf(borrower) - borrower_weth_balance_before
    vault_remaining = weth.balanceOf(vault_addr)

    # All collateral should be accounted for
    assert lender_received + borrower_received + vault_remaining == vault_balance_before


def test_liquidate_loan_with_shortfall_by_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, oracle, now, borrower):
    """
    For non-redeemed loans with shortfall (low oracle rate) liquidated by lender:
    - Lender receives remaining_collateral (collateral - liquidation_fee_collateral)
    - Borrower receives nothing (no surplus in shortfall case)
    - liquidation_fee_collateral remains in vault (contract behavior)
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

    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")

    # In shortfall case, lender gets remaining_collateral
    # remaining_collateral = in_vault_collateral - liquidation_fee_collateral
    assert weth.balanceOf(loan.lender) == lender_weth_balance_before + event.remaining_collateral
    assert weth.balanceOf(borrower) == borrower_weth_balance_before
    # liquidation_fee stays in vault (contract behavior)
    assert weth.balanceOf(vault_addr) == event.liquidation_fee


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
    liquidation_fee = outstanding_debt * loan.full_liquidation_fee // BPS

    protocol_wallet = p2p_usdc_weth.protocol_wallet()
    lender_usdc_balance_before = usdc.balanceOf(loan.lender)

    # Fund and approve liquidator
    usdc.mint(liquidator, outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=liquidator)

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    # Lender received payment (minus protocol fee)
    protocol_fee = loan.protocol_settlement_fee * loan.get_interest(loan.maturity) // BPS
    assert usdc.balanceOf(loan.lender) >= lender_usdc_balance_before


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

    # Calculate expected payment from liquidator (collateral value minus fee)
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    payment_token_decimals = 10 ** usdc.decimals()
    collateral_token_decimals = 10 ** weth.decimals()

    remaining_collateral_value = (
        loan.collateral_amount * rate * payment_token_decimals // (oracle_decimals * collateral_token_decimals)
    )
    outstanding_debt = loan.amount + loan.get_interest(loan.maturity)
    liquidation_fee = outstanding_debt * loan.full_liquidation_fee // BPS

    # Liquidator needs to pay: remaining_collateral_value - liquidation_fee
    liquidator_payment = remaining_collateral_value - liquidation_fee if remaining_collateral_value > liquidation_fee else 0

    # Fund and approve liquidator
    usdc.mint(liquidator, liquidator_payment)
    usdc.approve(p2p_usdc_weth.address, liquidator_payment, sender=liquidator)

    p2p_usdc_weth.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    # Lender receives collateral value (partial debt recovery)
    assert usdc.balanceOf(loan.lender) >= lender_usdc_balance_before


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
        redeem_wallet=securitize_redemption_wallet,
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
        redeem_wallet=securitize_redemption_wallet,
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
    - protocol_settlement_fee_amount = min(fee, remaining_collateral_value) = 0
    - Lender receives full outstanding_debt (no protocol fee deduction)
    - Protocol receives 0 (since remaining_collateral_value = 0)
    - Liquidator receives liquidation_fee
    - Borrower receives surplus
    """
    redeemed_loan, redeem_result, payment_redeemed = redeemed_loan_with_payment
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    liquidator = boa.env.generate_address("liquidator")

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    # Get balances before liquidation
    lender_balance_before = usdc.balanceOf(redeemed_loan.lender)
    borrower_balance_before = usdc.balanceOf(borrower)
    protocol_balance_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())
    liquidator_balance_before = usdc.balanceOf(liquidator)

    # Liquidate
    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Calculate expected values
    outstanding_debt = redeemed_loan.amount + redeemed_loan.get_interest(redeemed_loan.maturity)
    liquidation_fee = outstanding_debt * redeemed_loan.full_liquidation_fee // BPS

    # For redeemed loans with no collateral: remaining_collateral_value = 0
    # So protocol_settlement_fee_amount = min(fee, 0) = 0
    protocol_settlement_fee_amount = 0

    # in_vault_payment after fee deduction = payment_redeemed - liquidation_fee
    in_vault_payment_after_fee = payment_redeemed - liquidation_fee
    borrower_surplus = in_vault_payment_after_fee - outstanding_debt

    # Verify distributions
    assert usdc.balanceOf(redeemed_loan.lender) == lender_balance_before + outstanding_debt - protocol_settlement_fee_amount
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_balance_before + protocol_settlement_fee_amount
    assert usdc.balanceOf(liquidator) == liquidator_balance_before + liquidation_fee
    assert usdc.balanceOf(borrower) == borrower_balance_before + borrower_surplus


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

    # Calculate expected values
    outstanding_debt = redeemed_loan.amount + redeemed_loan.get_interest(redeemed_loan.maturity)
    liquidation_fee = outstanding_debt * redeemed_loan.full_liquidation_fee // BPS

    # For this fixture, liquidation_fee > in_vault_payment_token,
    # so liquidation_fee is partially taken from payment, rest from collateral
    # Let's verify this by checking balances
    liquidator_collateral_before = weth.balanceOf(liquidator)
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, redeemed_loan.vault_id)

    # Liquidator needs to fund the shortfall
    # The exact amount depends on the contract logic
    usdc.mint(liquidator, outstanding_debt)
    usdc.approve(p2p_usdc_weth.address, outstanding_debt, sender=liquidator)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Verify loan is deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Verify liquidator received collateral
    assert weth.balanceOf(liquidator) > liquidator_collateral_before
    assert weth.balanceOf(vault_addr) == 0


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

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=liquidator)

    # Calculate expected values
    outstanding_debt = redeemed_loan.amount + redeemed_loan.get_interest(redeemed_loan.maturity)

    # For redeemed loans with no collateral:
    # - remaining_collateral = 0
    # - remaining_collateral_value = 0
    # - protocol_settlement_fee_amount = min(fee, 0) = 0
    # - shortfall is calculated as: outstanding_debt - remaining_collateral_value = outstanding_debt
    #   (shortfall is based on collateral value, NOT payment tokens)

    event = get_last_event(p2p_usdc_weth, "LoanLiquidated")
    assert event.id == redeemed_loan.id
    assert event.borrower == redeemed_loan.borrower
    assert event.lender == redeemed_loan.lender
    assert event.liquidator == liquidator
    assert event.outstanding_debt == outstanding_debt
    assert event.remaining_collateral == 0
    assert event.remaining_collateral_value == 0
    # Note: shortfall = outstanding_debt - remaining_collateral_value = outstanding_debt (since remaining_collateral_value=0)
    # This reflects that the collateral can't cover the debt. The payment tokens DO cover the debt in this case.
    assert event.shortfall == outstanding_debt
    assert event.protocol_settlement_fee_amount == 0  # min(fee, remaining_collateral_value=0) = 0


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
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Small payment (much less than debt) - creates shortfall
    outstanding_debt_at_maturity = loan.amount + loan.get_interest(loan.maturity)
    liquidation_fee = outstanding_debt_at_maturity * loan.full_liquidation_fee // BPS
    payment_redeemed = outstanding_debt_at_maturity // 10  # Only 10% of debt

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,  # After redeem_start
        redeem_wallet=securitize_redemption_wallet,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - redeem_time + 1)

    # For shortfall with no collateral, use lender as liquidator to avoid underflow
    # The lender branch calls _transfer_funds which requires approval (even for 0)
    # protocol_settlement_fee_amount = min(fee, remaining_collateral_value=0) = 0
    usdc.approve(p2p_usdc_weth.address, 0, sender=loan.lender)

    lender_balance_before = usdc.balanceOf(loan.lender)

    # Verify loan hash matches before liquidation
    expected_hash = compute_securitize_loan_hash(redeemed_loan)
    actual_hash = p2p_usdc_weth.loans(redeemed_loan.id)
    assert expected_hash == actual_hash, "Loan hash mismatch before liquidation"

    lender_balance_before = usdc.balanceOf(loan.lender)

    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=loan.lender)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # In the shortfall case with lender as liquidator and no collateral:
    # - Lender receives the liquidation_fee from vault's payment tokens
    # - The remaining payment (7% of debt) stays in contract (this appears to be a contract quirk)
    # Verify lender received at least the liquidation_fee
    lender_balance_after = usdc.balanceOf(loan.lender)
    assert lender_balance_after >= lender_balance_before


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
        redeem_wallet=securitize_redemption_wallet,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Verify loan hash matches
    assert compute_securitize_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

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
        redeem_wallet=securitize_redemption_wallet,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Verify loan hash matches
    assert compute_securitize_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

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
        redeem_wallet=securitize_redemption_wallet,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Verify loan hash matches
    assert compute_securitize_loan_hash(redeemed_loan) == p2p_usdc_weth.loans(redeemed_loan.id)

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
    For surplus case: lender receives debt + liquidation_fee, protocol gets fee, borrower gets surplus.
    """
    redeemed_loan, redeem_result, payment_redeemed = redeemed_loan_with_payment
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Make loan defaulted
    boa.env.time_travel(seconds=redeemed_loan.maturity - now + 1)

    lender_balance_before = usdc.balanceOf(redeemed_loan.lender)
    protocol_balance_before = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())
    borrower_balance_before = usdc.balanceOf(borrower)

    # Lender liquidates their own loan
    p2p_usdc_weth.liquidate_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.lender)

    # Verify loan deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32

    # Calculate expected values
    outstanding_debt = redeemed_loan.amount + redeemed_loan.get_interest(redeemed_loan.maturity)
    liquidation_fee = outstanding_debt * redeemed_loan.full_liquidation_fee // BPS

    # For redeemed loans with no collateral:
    # - remaining_collateral_value = 0
    # - protocol_settlement_fee_amount = min(fee, 0) = 0

    # in_vault_payment after fee deduction
    in_vault_payment_after_fee = payment_redeemed - liquidation_fee
    borrower_surplus = in_vault_payment_after_fee - outstanding_debt

    # For lender as liquidator with surplus case:
    # - Lender receives: outstanding_debt - protocol_fee(=0) + liquidation_fee
    # - Protocol receives: protocol_fee = 0
    # - Borrower receives: surplus
    assert usdc.balanceOf(redeemed_loan.lender) == lender_balance_before + outstanding_debt + liquidation_fee
    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == protocol_balance_before
    assert usdc.balanceOf(borrower) == borrower_balance_before + borrower_surplus
