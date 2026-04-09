import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    RedeemResult,
    SecuritizeLoan,
    SignedRedeemResult,
    calc_ltv,
    compute_liquidity_key,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_securitize_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
    sign_redeem_result,
)

# Empty redeem result for non-redeemed loans
EMPTY_REDEEM_RESULT = SignedRedeemResult()

BPS = 10000


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
    print(event)
    print(loan)
    assert compute_securitize_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


def test_settle_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    for loan in get_securitize_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=ongoing_loan_usdc_weth.borrower)


def test_settle_loan_reverts_if_not_borrower(p2p_usdc_weth, ongoing_loan_usdc_weth, lender):
    with boa.reverts("not borrower"):
        p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, EMPTY_REDEEM_RESULT, sender=lender)


def test_settle_loan_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_default = ongoing_loan_usdc_weth.maturity - now
    boa.env.time_travel(seconds=time_to_default + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, EMPTY_REDEEM_RESULT, sender=ongoing_loan_usdc_weth.borrower)


def test_settle_loan_reverts_if_loan_already_settled(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.get_interest(now)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    with boa.reverts("invalid loan"):
        usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
        p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)


def test_settle_loan_reverts_if_funds_not_approved(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.get_interest(now)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle - 1, sender=ongoing_loan_usdc_weth.borrower)
    with boa.reverts():
        p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, EMPTY_REDEEM_RESULT, sender=ongoing_loan_usdc_weth.borrower)


def test_settle_loan(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.get_interest(now)
    amount_to_settle = loan.amount + interest

    vault_addr = p2p_usdc_weth.vault_id_to_vault(loan.borrower, loan.vault_id)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32
    assert weth.balanceOf(vault_addr) == 0


def test_settle_loan_updates_commited_liquidity(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    interest = loan.get_interest(now)
    amount_to_settle = loan.amount + interest

    liquidity_key = compute_liquidity_key(loan.lender, loan.offer_tracing_id)
    offer_liquidity_before = p2p_usdc_weth.commited_liquidity(liquidity_key)
    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    assert p2p_usdc_weth.commited_liquidity(liquidity_key) == offer_liquidity_before - loan.amount


def test_settle_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    protocol_fee_amount = interest * loan.protocol_settlement_fee // BPS

    assert interest > 0  # precondition: non-zero interest accrued
    assert protocol_fee_amount > 0  # precondition: non-zero protocol fee

    amount_to_settle = loan.amount + interest
    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

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
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    amount_to_settle = loan.amount + interest

    assert interest > 0  # precondition: non-zero interest accrued

    initial_borrower_balance = usdc.balanceOf(ongoing_loan_usdc_weth.borrower)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle + 1, sender=ongoing_loan_usdc_weth.borrower)
    p2p_usdc_weth.settle_loan(ongoing_loan_usdc_weth, EMPTY_REDEEM_RESULT, sender=ongoing_loan_usdc_weth.borrower)
    assert usdc.balanceOf(p2p_usdc_weth.address) == 0
    assert usdc.balanceOf(ongoing_loan_usdc_weth.borrower) == initial_borrower_balance - amount_to_settle


def test_settle_loan_transfers_collateral_to_borrower(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, now):
    loan = ongoing_loan_usdc_weth
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    amount_to_settle = loan.amount + interest

    vault_addr = p2p_usdc_weth.vault_id_to_vault(loan.borrower, loan.vault_id)
    borrower_balance_before = weth.balanceOf(loan.borrower)

    assert weth.balanceOf(vault_addr) > 0  # precondition: collateral in vault

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    assert weth.balanceOf(vault_addr) == 0
    assert weth.balanceOf(loan.borrower) == borrower_balance_before + loan.collateral_amount


def test_settle_loan_pays_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    protocol_fee_amount = interest * loan.protocol_settlement_fee // BPS
    amount_to_settle = loan.amount + interest
    amount_to_receive = loan.amount + interest - protocol_fee_amount

    assert interest > 0  # precondition: non-zero interest accrued
    assert amount_to_receive > loan.amount  # precondition: lender receives more than principal

    initial_lender_balance = usdc.balanceOf(loan.lender)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    assert usdc.balanceOf(loan.lender) == initial_lender_balance + amount_to_receive


def test_settle_loan_pays_protocol_fees(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    loan = ongoing_loan_usdc_weth
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    protocol_fee_amount = interest * loan.protocol_settlement_fee // BPS

    assert interest > 0  # precondition: non-zero interest accrued
    assert protocol_fee_amount > 0  # precondition: non-zero protocol fee

    amount_to_settle = loan.amount + interest
    initial_protocol_wallet_balance = usdc.balanceOf(p2p_usdc_weth.protocol_wallet())

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    assert usdc.balanceOf(p2p_usdc_weth.protocol_wallet()) == initial_protocol_wallet_balance + protocol_fee_amount


def test_settle_loan_creates_pending_transfer_on_erc20_transfer_fail(
    p2p_lending_securitize_erc20_contract_def,
    p2p_sec_refinance,
    p2p_sec_liquidation,
    securitize_vault_impl,
    failing_transfer_payment_erc20,
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
    transfer_agent,
    securitize_redemption_wallet,
):
    erc20 = failing_transfer_payment_erc20
    p2p_erc20_weth = p2p_lending_securitize_erc20_contract_def.deploy(
        erc20,
        weth,
        oracle,
        False,
        kyc_validator_contract,
        0,
        0,
        owner,
        10000,
        10000,
        0,
        0,
        p2p_sec_refinance.address,
        p2p_sec_liquidation.address,
        securitize_vault_impl.address,
        transfer_agent,
        securitize_redemption_wallet,
        boa.eval("empty(address)"),  # vault_registrar_addr
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
    weth.approve(p2p_erc20_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    loan_id = p2p_erc20_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
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
        protocol_upfront_fee_amount=p2p_erc20_weth.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_erc20_weth.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_erc20_weth.partial_liquidation_fee(),
        full_liquidation_fee=p2p_erc20_weth.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_erc20_weth.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=0,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_erc20_weth.loans(loan_id)

    p2p_erc20_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    interest = loan.get_interest(now)
    assert p2p_erc20_weth.pending_transfers(lender) == loan.amount + interest


def test_claim_pending_transfers(p2p_usdc_weth, usdc):
    user = boa.env.generate_address()
    value = 10**6

    p2p_usdc_weth.eval(f"base.pending_transfers[{user}] = {value}")
    usdc.mint(p2p_usdc_weth.address, value)

    assert usdc.balanceOf(user) == 0
    assert p2p_usdc_weth.pending_transfers(user) == value

    p2p_usdc_weth.claim_pending_transfers(sender=user)

    assert usdc.balanceOf(user) == value
    assert p2p_usdc_weth.pending_transfers(user) == 0


def test_claim_pending_transfers_reverts_if_no_pending(p2p_usdc_weth, usdc):
    user = boa.env.generate_address()

    with boa.reverts("no pending transfers"):
        p2p_usdc_weth.claim_pending_transfers(sender=user)


# ============================================================================
# REDEEMED LOAN SETTLEMENT TESTS
# ============================================================================


@pytest.fixture
def redeemed_loan_for_settle(
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
    Create a redeemed loan with payment tokens in the vault for settlement tests.
    Simulates: borrower redeems all collateral, Securitize converts to payment token,
    and vault receives payment tokens covering the debt.
    """
    loan = ongoing_loan_usdc_weth
    residual_collateral = 0

    # Redeem the loan (sends all collateral to redemption wallet)
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)

    # Capture actual timestamp after redeem
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=residual_collateral,
    )

    # Get the vault address for this loan
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Simulate redemption: payment tokens deposited to vault
    # Must cover loan.amount + interest at settlement time
    payment_redeemed = loan.amount + loan.amount  # generous amount covering debt + interest + surplus

    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time + 1,
    )

    return redeemed_loan, redeem_result, payment_redeemed


def test_settle_loan_reverts_if_redeem_not_concluded(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    """Settling a redeemed loan with empty/invalid redeem_result reverts."""
    loan = ongoing_loan_usdc_weth

    # Redeem the loan
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=0,
    )

    # Verify loan is redeemed
    assert redeemed_loan.redeem_start > 0

    # Try to settle with empty redeem result — should fail because
    # _is_loan_redeem_concluded returns False (timestamp=0 < redeem_start)
    with boa.reverts("redeem not concluded"):
        p2p_usdc_weth.settle_loan(redeemed_loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)


def test_settle_loan_reverts_if_invalid_redeem_payment_amount(
    p2p_usdc_weth, redeemed_loan_for_settle, usdc, owner_key, borrower
):
    """Settling a redeemed loan reverts when redeem_result.payment_redeemed exceeds vault's payment token balance."""
    redeemed_loan, redeem_result, _ = redeemed_loan_for_settle
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, redeemed_loan.vault_id)

    # Create a redeem result claiming more payment tokens than the vault actually has
    actual_vault_balance = usdc.balanceOf(vault_addr)
    inflated_redeem_result = RedeemResult(
        vault=redeem_result.vault,
        collateral_redeemed=redeem_result.collateral_redeemed,
        payment_redeemed=actual_vault_balance + 1,  # more than vault holds
        timestamp=redeem_result.timestamp,
    )
    signed_redeem_result = sign_redeem_result(inflated_redeem_result, owner_key)

    # Precondition: vault truly has less than claimed
    assert usdc.balanceOf(vault_addr) < inflated_redeem_result.payment_redeemed

    with boa.reverts("invalid redeem payment amount"):
        p2p_usdc_weth.settle_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.borrower)


def test_settle_loan_reverts_if_invalid_redeem_collateral_amnt(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, owner_key, borrower, now
):
    """Settling a redeemed loan reverts when redeem_result.collateral_redeemed + residual exceeds vault's collateral."""
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 2  # Keep 50% as residual

    # Redeem with residual collateral
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)

    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_time,
        redeem_residual_collateral=residual_collateral,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Mint some payment tokens to vault (simulating partial redemption)
    usdc.mint(vault_addr, loan.amount)

    # The vault's withdrawable_balance should be residual_collateral (the collateral that stayed)
    # The contract checks: withdrawable_balance >= loan.redeem_residual_collateral + redeem_result.collateral_redeemed
    # So claim collateral_redeemed that pushes the sum above what the vault actually holds
    vault_collateral_balance = weth.balanceOf(vault_addr)
    inflated_collateral_redeemed = vault_collateral_balance - residual_collateral + 1  # just enough to exceed

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=inflated_collateral_redeemed,
        payment_redeemed=loan.amount,
        timestamp=redeem_time + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    with boa.reverts("invalid redeem collateral amnt"):
        p2p_usdc_weth.settle_loan(redeemed_loan, signed_redeem_result, sender=loan.borrower)


def test_settle_redeemed_loan(p2p_usdc_weth, redeemed_loan_for_settle, usdc, weth, owner_key, borrower):
    """Happy path: settling a redeemed loan deletes loan state and empties vault."""
    redeemed_loan, redeem_result, _ = redeemed_loan_for_settle
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, redeemed_loan.vault_id)

    # Approve borrower to pay any remaining debt not covered by vault payment tokens
    # (in this case vault has enough, so borrower may receive surplus instead)
    usdc.approve(p2p_usdc_weth.address, redeemed_loan.amount * 2, sender=redeemed_loan.borrower)

    p2p_usdc_weth.settle_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.borrower)

    # Loan state deleted
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32
    # Vault emptied (collateral was already redeemed, payment tokens withdrawn)
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(vault_addr) == 0


def test_settle_redeemed_loan_pays_lender(
    p2p_usdc_weth, redeemed_loan_for_settle, usdc, owner_key, borrower, now, protocol_fees
):
    """Verify lender receives correct amount when settling a redeemed loan."""
    redeemed_loan, redeem_result, _ = redeemed_loan_for_settle
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Time travel a bit for non-zero interest
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta

    interest = redeemed_loan.get_interest(settle_time)
    protocol_fee_amount = interest * redeemed_loan.protocol_settlement_fee // BPS

    assert interest > 0  # precondition: non-zero interest accrued
    assert protocol_fee_amount > 0  # precondition: non-zero protocol fee

    # The lender should receive: loan.amount + interest - protocol_fee
    expected_lender_payment = redeemed_loan.amount + interest - protocol_fee_amount

    lender_balance_before = usdc.balanceOf(redeemed_loan.lender)

    # Approve borrower to pay any shortfall (vault has surplus, so may not need approval)
    usdc.approve(p2p_usdc_weth.address, redeemed_loan.amount * 2, sender=redeemed_loan.borrower)

    p2p_usdc_weth.settle_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.borrower)

    assert usdc.balanceOf(redeemed_loan.lender) == lender_balance_before + expected_lender_payment


def test_settle_redeemed_loan_logs_event(
    p2p_usdc_weth, redeemed_loan_for_settle, usdc, owner_key, borrower, now, protocol_fees
):
    """Verify LoanPaid event includes correct redemption-related fields for redeemed settlement."""
    redeemed_loan, redeem_result, payment_redeemed = redeemed_loan_for_settle
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    # Time travel for non-zero interest
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta

    interest = redeemed_loan.get_interest(settle_time)
    protocol_fee_amount = interest * redeemed_loan.protocol_settlement_fee // BPS

    assert interest > 0  # precondition: non-zero interest accrued

    usdc.approve(p2p_usdc_weth.address, redeemed_loan.amount * 2, sender=redeemed_loan.borrower)

    p2p_usdc_weth.settle_loan(redeemed_loan, signed_redeem_result, sender=redeemed_loan.borrower)

    event = get_last_event(p2p_usdc_weth, "LoanPaid")
    assert event.id == redeemed_loan.id
    assert event.borrower == redeemed_loan.borrower
    assert event.lender == redeemed_loan.lender
    assert event.payment_token == redeemed_loan.payment_token
    assert event.paid_principal == redeemed_loan.amount
    assert event.paid_interest == interest
    assert event.origination_fee_amount == redeemed_loan.origination_fee_amount
    assert event.protocol_upfront_fee_amount == redeemed_loan.protocol_upfront_fee_amount
    assert event.protocol_settlement_fee_amount == protocol_fee_amount
    # For redeemed loans, in_vault_payment_token reflects the redemption proceeds
    assert event.in_vault_payment_token == payment_redeemed
    # No collateral remaining since all was redeemed (residual_collateral=0, collateral_redeemed=0)
    # in_vault_collateral = loan.redeem_residual_collateral + redeem_result.collateral_redeemed = 0
    assert event.in_vault_collateral == 0


# ============================================================================
# MUTATION TESTING: boundary and variable coverage
# ============================================================================


def test_settle_loan_succeeds_at_exact_maturity(p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now):
    """Mutation kill: _is_loan_defaulted > to >= (Base line 472).
    Settling at exactly maturity should succeed (loan is NOT defaulted)."""
    loan = ongoing_loan_usdc_weth
    time_to_maturity = loan.maturity - now
    boa.env.time_travel(seconds=time_to_maturity)

    interest = loan.get_interest(loan.maturity)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=loan.borrower)

    assert p2p_usdc_weth.loans(loan.id) == ZERO_BYTES32


def test_settle_redeemed_loan_with_exact_timestamp_at_redeem_start(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, weth, borrower, owner_key, now, protocol_fees
):
    """Mutation kill: redeem_result.timestamp < to <= loan.redeem_start (Base line 494).
    A redeem result with timestamp exactly equal to redeem_start should be accepted."""
    loan = ongoing_loan_usdc_weth

    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)
    redeem_time = boa.env.evm.patch.timestamp

    redeemed_loan = replace_namedtuple_field(loan, redeem_start=redeem_time, redeem_residual_collateral=0)

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    payment_redeemed = loan.amount + loan.amount
    usdc.mint(vault_addr, payment_redeemed)

    # Use timestamp == redeem_start (exact boundary)
    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=redeem_time,  # exact boundary, not redeem_time + 1
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    usdc.approve(p2p_usdc_weth.address, loan.amount * 2, sender=loan.borrower)
    p2p_usdc_weth.settle_loan(redeemed_loan, signed_redeem_result, sender=loan.borrower)

    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32


def test_settle_loan_with_modified_amount_updates_commited_liquidity_correctly(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now
):
    """Mutation kill: loan.amount vs loan.initial_amount in _reduce_commited_liquidity (line 670).
    After modifying loan.amount (simulating partial liquidation), committed liquidity
    should be reduced by loan.amount, not loan.initial_amount."""
    loan = ongoing_loan_usdc_weth

    # Simulate partial liquidation by reducing loan.amount but keeping initial_amount
    reduced_amount = loan.amount // 2  # half of principal
    modified_loan = replace_namedtuple_field(loan, amount=reduced_amount)

    # Update the loan hash in the contract using hex-encoded bytes32
    new_hash = compute_securitize_loan_hash(modified_loan)
    loan_id_hex = "0x" + modified_loan.id.hex()
    hash_hex = "0x" + new_hash.hex()
    p2p_usdc_weth.eval(f"base.loans[{loan_id_hex}] = {hash_hex}")
    # Verify the modified loan is valid
    assert p2p_usdc_weth.loans(modified_loan.id) == new_hash

    liquidity_key = compute_liquidity_key(loan.lender, loan.offer_tracing_id)
    offer_liquidity_before = p2p_usdc_weth.commited_liquidity(liquidity_key)

    interest = modified_loan.get_interest(now)
    amount_to_settle = modified_loan.amount + interest
    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=modified_loan.borrower)
    p2p_usdc_weth.settle_loan(modified_loan, EMPTY_REDEEM_RESULT, sender=modified_loan.borrower)

    # Committed liquidity should be reduced by loan.amount (reduced), not initial_amount
    assert p2p_usdc_weth.commited_liquidity(liquidity_key) == offer_liquidity_before - reduced_amount


def test_settle_loan_interest_uses_accrual_start_time_not_start_time(
    p2p_usdc_weth, ongoing_loan_usdc_weth, usdc, now, protocol_fees
):
    """Mutation kill: accrual_start_time vs start_time in interest calc (Base line 361).
    After setting accrual_start_time > start_time (simulating post-partial-liquidation),
    interest should be computed from accrual_start_time."""
    loan = ongoing_loan_usdc_weth

    # Simulate partial liquidation having happened: advance time and set a later accrual_start_time
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    mid_time = now + time_delta

    # Create a loan where accrual_start_time is mid_time (later than start_time)
    modified_loan = replace_namedtuple_field(loan, accrual_start_time=mid_time)

    # Update the loan hash in the contract using hex-encoded bytes32
    new_hash = compute_securitize_loan_hash(modified_loan)
    loan_id_hex = "0x" + modified_loan.id.hex()
    hash_hex = "0x" + new_hash.hex()
    p2p_usdc_weth.eval(f"base.loans[{loan_id_hex}] = {hash_hex}")
    assert p2p_usdc_weth.loans(modified_loan.id) == new_hash

    # Time travel more so interest accrues from accrual_start_time
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta * 2

    # Interest should be calculated from accrual_start_time (mid_time), not start_time (now)
    expected_interest = modified_loan.apr * modified_loan.amount * (settle_time - mid_time) // (365 * 24 * 3600 * BPS)
    wrong_interest = modified_loan.apr * modified_loan.amount * (settle_time - now) // (365 * 24 * 3600 * BPS)

    assert expected_interest != wrong_interest  # precondition: values differ
    assert expected_interest > 0  # precondition: non-zero interest

    amount_to_settle = modified_loan.amount + expected_interest
    protocol_fee_amount = expected_interest * modified_loan.protocol_settlement_fee // BPS

    initial_lender_balance = usdc.balanceOf(modified_loan.lender)

    usdc.approve(p2p_usdc_weth.address, amount_to_settle, sender=modified_loan.borrower)
    p2p_usdc_weth.settle_loan(modified_loan, EMPTY_REDEEM_RESULT, sender=modified_loan.borrower)

    # Verify lender got the correct amount (based on accrual_start_time interest, not start_time)
    expected_lender_payment = modified_loan.amount + expected_interest - protocol_fee_amount
    assert usdc.balanceOf(modified_loan.lender) == initial_lender_balance + expected_lender_payment
