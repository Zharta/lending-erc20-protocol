"""Unit tests for `redeem_and_settle` (atomic REDEEM_SYNC path) against the REAL Midas vault.

`redeem_and_settle` is the atomic entry point for REDEEM_SYNC vaults: it redeems the loan's
non-residual collateral to payment token on-chain (via `redeem_sync`) and settles the loan in the
same transaction — no `redeem_start`, no owner-signed RedeemResult. Semantics mirror `settle_loan`.

These tests run against the REAL `P2PLendingVaultMidas` impl (`p2p_usdc_weth_sync`, MINT_SYNC |
REDEEM_SYNC). Its `redeem_sync` approves the market's `redemption_addr` (a `MidasVaultMock`) for the
redeemed collateral, calls `redeemInstant` on it (which pulls the weth collateral from the vault and
pays out a configured amount of usdc), and returns the delivered usdc as the redeemed proceeds the
settle logic consumes. Tests configure the mock: `set_waived(True)` (zero fee), `set_deliver_amount`
(the usdc paid out), and pre-fund it with usdc. The delivered amount must clear the vault's oracle
floor `min_receive = collateral_redeemed_base18 * oracle_num // oracle_den` (weth is 18-dec so
amount_mtoken_base18 == native; fee waived so amount_without_fee == amount_mtoken).

The default `p2p_usdc_weth` fixture is the real SecuritizeMV (MINT_SYNC | REDEEM_MANUAL), used only for
the "sync redeem not supported" revert (a manual vault rejects the atomic path).
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)

BPS = 10000


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc):
    usdc.mint(lender, 10**12)


@pytest.fixture(autouse=True)
def borrower_funds(borrower, usdc):
    usdc.mint(borrower, 10**12)


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


def _create_ongoing_loan(p2p, offer_signed, usdc, weth, borrower, lender, now, kyc_borrower, kyc_lender):
    """Create and start a loan on `p2p`, returning the mirrored `Loan` namedtuple."""
    offer = offer_signed.offer
    principal = offer.principal
    collateral_amount = int(1e18)
    lender_approval = principal + (p2p.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.mint(lender, lender_approval)
    usdc.approve(p2p.address, lender_approval, sender=lender)

    loan_id = p2p.create_loan(offer_signed, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    loan = Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(offer_signed),
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
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p.protocol_settlement_fee(),
        partial_liquidation_fee=p2p.partial_liquidation_fee(),
        full_liquidation_fee=p2p.full_liquidation_fee(),
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
    assert compute_loan_hash(loan) == p2p.loans(loan_id)
    return loan


def _make_offer(p2p, now, borrower, lender, lender_key, oracle, usdc, weth):
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
    return sign_offer(offer, lender_key, p2p.address)


@pytest.fixture
def protocol_fees_sync(p2p_usdc_weth_sync):
    settlement_fee = 1000
    upfront_fee = 11
    p2p_usdc_weth_sync.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_weth_sync.owner())
    p2p_usdc_weth_sync.change_protocol_wallet(p2p_usdc_weth_sync.owner(), sender=p2p_usdc_weth_sync.owner())
    return settlement_fee


@pytest.fixture
def ongoing_loan_sync(
    p2p_usdc_weth_sync, usdc, weth, borrower, lender, lender_key, oracle, now, kyc_borrower, kyc_lender, protocol_fees_sync
):
    offer_signed = _make_offer(p2p_usdc_weth_sync, now, borrower, lender, lender_key, oracle, usdc, weth)
    return _create_ongoing_loan(p2p_usdc_weth_sync, offer_signed, usdc, weth, borrower, lender, now, kyc_borrower, kyc_lender)


@pytest.fixture
def ongoing_loan_manual(p2p_usdc_weth, usdc, weth, borrower, lender, lender_key, oracle, now, kyc_borrower, kyc_lender):
    """An ongoing loan on the default MINT_SYNC | REDEEM_MANUAL p2p (for the non-sync revert)."""
    offer_signed = _make_offer(p2p_usdc_weth, now, borrower, lender, lender_key, oracle, usdc, weth)
    return _create_ongoing_loan(p2p_usdc_weth, offer_signed, usdc, weth, borrower, lender, now, kyc_borrower, kyc_lender)


def _redemption_floor(collateral_redeemed, oracle):
    """The vault's slippage floor on the delivered usdc: collateral_redeemed_base18 * num // den.

    Fee is waived in these tests so amount_without_fee == collateral_redeemed; weth is 18-dec so
    amount_mtoken_base18 == the native amount. The result is base18; the delivered usdc (6-dec) is
    normalized to base18 (`* 10**12`) inside the mock, so `deliver_usdc * 10**12` must be >= this.
    """
    num = oracle.rate()
    den = 10 ** oracle.decimals()
    return collateral_redeemed * num // den


def _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, deliver_usdc):
    """Configure the Midas redemption mock to pay `deliver_usdc` (6-dec) for the redeemed collateral.

    Waives the fee, sets the delivered amount, and pre-funds the mock with usdc for the payout. Asserts
    the delivered amount clears the oracle floor (else redeemInstant would revert "insufficient output").
    Returns `deliver_usdc` — the redeemed proceeds the settle logic consumes.
    """
    collateral_redeemed = loan.collateral_amount - residual
    floor_base18 = _redemption_floor(collateral_redeemed, oracle)
    assert deliver_usdc * 10**12 >= floor_base18  # precondition: delivery clears the vault slippage floor
    midas_redemption_vault.set_waived(True)
    midas_redemption_vault.set_deliver_amount(deliver_usdc)
    usdc.mint(midas_redemption_vault.address, deliver_usdc)
    return deliver_usdc


# ============================================================================
# HAPPY PATH — SURPLUS (redeemed proceeds exceed principal + interest)
# ============================================================================


def test_redeem_and_settle_removes_loan(p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    boa.env.time_travel(seconds=50)
    _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert p2p_usdc_weth_sync.loans(loan.id) == ZERO_BYTES32


def test_redeem_and_settle_reduces_commited_liquidity(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner
):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    key = compute_liquidity_key(loan.lender, loan.offer_tracing_id)
    committed_before = p2p_usdc_weth_sync.commited_liquidity(key)
    assert committed_before == loan.amount  # precondition

    boa.env.time_travel(seconds=50)
    _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert p2p_usdc_weth_sync.commited_liquidity(key) == committed_before - loan.amount


def test_redeem_and_settle_pays_lender(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner, now
):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    protocol_fee = interest * loan.protocol_settlement_fee // BPS
    assert interest > 0  # precondition
    assert protocol_fee > 0  # precondition

    _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)
    lender_balance_before = usdc.balanceOf(loan.lender)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert usdc.balanceOf(loan.lender) == lender_balance_before + loan.amount + interest - protocol_fee


def test_redeem_and_settle_pays_protocol_fees(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner, now
):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    protocol_fee = interest * loan.protocol_settlement_fee // BPS
    assert protocol_fee > 0  # precondition

    _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)
    protocol_wallet = p2p_usdc_weth_sync.protocol_wallet()
    protocol_balance_before = usdc.balanceOf(protocol_wallet)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert usdc.balanceOf(protocol_wallet) == protocol_balance_before + protocol_fee


def test_redeem_and_settle_returns_surplus_to_borrower(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner, now
):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)

    redeemed = _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)
    surplus = redeemed - (loan.amount + interest)
    assert surplus > 0  # precondition: redeemed proceeds exceed the debt
    borrower_balance_before = usdc.balanceOf(loan.borrower)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert usdc.balanceOf(loan.borrower) == borrower_balance_before + surplus


def test_redeem_and_settle_returns_residual_collateral_to_borrower(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, weth, usdc, owner
):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    boa.env.time_travel(seconds=50)
    _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)
    borrower_weth_before = weth.balanceOf(loan.borrower)
    vault_addr = p2p_usdc_weth_sync.vault_id_to_vault(loan.borrower, loan.vault_id)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert weth.balanceOf(loan.borrower) == borrower_weth_before + residual
    assert weth.balanceOf(vault_addr) == 0


def test_redeem_and_settle_redeems_collateral_to_redemption_vault(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, weth, usdc, owner
):
    """The redeemed collateral (weth) is pulled by redeemInstant into the Midas redemption vault mock."""
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 4
    collateral_redeemed = loan.collateral_amount - residual
    boa.env.time_travel(seconds=50)
    # residual = collateral/4 -> collateral_redeemed = 0.75e18; floor ~2908e6, so deliver 3000e6.
    _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 3000 * 10**6)
    redemption_weth_before = weth.balanceOf(midas_redemption_vault.address)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert weth.balanceOf(midas_redemption_vault.address) == redemption_weth_before + collateral_redeemed


def test_redeem_and_settle_logs_event(p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner, now):
    loan = ongoing_loan_sync
    residual = loan.collateral_amount // 2
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)
    protocol_fee = interest * loan.protocol_settlement_fee // BPS

    redeemed = _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, 2000 * 10**6)

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    event = get_last_event(p2p_usdc_weth_sync, "LoanPaid")
    assert event.id == loan.id
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.payment_token == loan.payment_token
    assert event.paid_principal == loan.amount
    assert event.paid_interest == interest
    assert event.origination_fee_amount == loan.origination_fee_amount
    assert event.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert event.protocol_settlement_fee_amount == protocol_fee
    assert event.in_vault_payment_token == redeemed
    assert event.in_vault_collateral == residual


# ============================================================================
# HAPPY PATH — SHORTFALL (borrower tops up the difference)
# ============================================================================


def test_redeem_and_settle_tops_up_borrower_shortfall(
    p2p_usdc_weth_sync, ongoing_loan_sync, midas_redemption_vault, oracle, usdc, owner, now
):
    loan = ongoing_loan_sync
    # Keep almost all collateral as residual so only a small chunk is redeemed. A small redeemed chunk
    # keeps the oracle floor below the debt, letting the mock deliver less than (principal + interest).
    residual = loan.collateral_amount - 10**17  # redeem 0.1 weth; floor ~387.78e6 (< the 500e6 delivered)
    redeemed_target = 500 * 10**6
    time_delta = 50
    boa.env.time_travel(seconds=time_delta)
    settle_time = now + time_delta
    interest = loan.get_interest(settle_time)

    redeemed = _configure_redemption(midas_redemption_vault, oracle, usdc, owner, loan, residual, redeemed_target)
    assert redeemed == redeemed_target
    shortfall = (loan.amount + interest) - redeemed
    assert shortfall > 0  # precondition: borrower must cover the gap

    # Borrower approves the p2p to pull the shortfall.
    usdc.approve(p2p_usdc_weth_sync.address, shortfall, sender=loan.borrower)
    borrower_balance_before = usdc.balanceOf(loan.borrower)
    lender_balance_before = usdc.balanceOf(loan.lender)
    protocol_fee = interest * loan.protocol_settlement_fee // BPS

    p2p_usdc_weth_sync.redeem_and_settle(loan, residual, sender=loan.borrower)

    assert usdc.balanceOf(loan.borrower) == borrower_balance_before - shortfall
    assert usdc.balanceOf(loan.lender) == lender_balance_before + loan.amount + interest - protocol_fee
    assert p2p_usdc_weth_sync.loans(loan.id) == ZERO_BYTES32


# ============================================================================
# REVERTS
# ============================================================================


def test_redeem_and_settle_reverts_if_loan_invalid(p2p_usdc_weth_sync, ongoing_loan_sync):
    for loan in get_loan_mutations(ongoing_loan_sync):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth_sync.redeem_and_settle(loan, 0, sender=ongoing_loan_sync.borrower)


def test_redeem_and_settle_reverts_if_not_borrower(p2p_usdc_weth_sync, ongoing_loan_sync, lender):
    with boa.reverts("not borrower"):
        p2p_usdc_weth_sync.redeem_and_settle(ongoing_loan_sync, 0, sender=lender)


def test_redeem_and_settle_reverts_if_loan_defaulted(p2p_usdc_weth_sync, ongoing_loan_sync, now):
    boa.env.time_travel(seconds=ongoing_loan_sync.maturity - now + 1)
    with boa.reverts("loan defaulted"):
        p2p_usdc_weth_sync.redeem_and_settle(ongoing_loan_sync, 0, sender=ongoing_loan_sync.borrower)


def test_redeem_and_settle_reverts_if_residual_gt_collateral(p2p_usdc_weth_sync, ongoing_loan_sync):
    residual = ongoing_loan_sync.collateral_amount + 1
    with boa.reverts("residual collateral gt total"):
        p2p_usdc_weth_sync.redeem_and_settle(ongoing_loan_sync, residual, sender=ongoing_loan_sync.borrower)


def test_redeem_and_settle_reverts_if_redemption_addr_not_set(p2p_usdc_weth_sync, ongoing_loan_sync):
    p2p_usdc_weth_sync.set_redemption_addr(ZERO_ADDRESS, sender=p2p_usdc_weth_sync.owner())
    with boa.reverts("redemption addr not set"):
        p2p_usdc_weth_sync.redeem_and_settle(ongoing_loan_sync, 0, sender=ongoing_loan_sync.borrower)


def test_redeem_and_settle_reverts_if_already_redeemed(p2p_usdc_weth_sync, ongoing_loan_sync, now):
    """A loan already in the deferred redeemed state (redeem_start > 0) cannot be atomically settled.

    Sync vaults never set redeem_start via the normal flow, so seed the redeemed hash directly.
    """
    loan = ongoing_loan_sync
    redeemed_loan = replace_namedtuple_field(loan, redeem_start=now)
    lid = "0x" + loan.id.hex()
    h = "0x" + compute_loan_hash(redeemed_loan).hex()
    p2p_usdc_weth_sync.eval(f"base.loans[{lid}] = {h}")

    with boa.reverts("loan already redeemed"):
        p2p_usdc_weth_sync.redeem_and_settle(redeemed_loan, 0, sender=loan.borrower)


def test_redeem_and_settle_reverts_if_loan_not_started(p2p_usdc_weth_sync, ongoing_loan_sync):
    """`_is_loan_started` is `start_time >= create_time`; a pending loan (start_time 0) reverts."""
    loan = ongoing_loan_sync
    pending_loan = replace_namedtuple_field(loan, start_time=0)
    lid = "0x" + loan.id.hex()
    h = "0x" + compute_loan_hash(pending_loan).hex()
    p2p_usdc_weth_sync.eval(f"base.loans[{lid}] = {h}")

    with boa.reverts("loan not started"):
        p2p_usdc_weth_sync.redeem_and_settle(pending_loan, 0, sender=loan.borrower)


def test_redeem_and_settle_reverts_if_non_sync_vault(p2p_usdc_weth, ongoing_loan_manual):
    """A MINT_SYNC | REDEEM_MANUAL vault rejects the atomic path."""
    with boa.reverts("sync redeem not supported"):
        p2p_usdc_weth.redeem_and_settle(ongoing_loan_manual, 0, sender=ongoing_loan_manual.borrower)
