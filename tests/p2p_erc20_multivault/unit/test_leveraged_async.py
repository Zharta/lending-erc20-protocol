"""Unit tests for the async (Centrifuge ERC-7540) leveraged-loan lifecycle.

Covers create_leveraged_loan (async branch), start_loan, cancel_pending_loan (liquidation-style,
A4/M4), cancel_redeem, and the Centrifuge async vault's own status/auth surface.

Each lifecycle stage has ONE flat fixture defined in this file (`pending_loan`, `started_loan`,
`redeeming_loan`) that runs the whole path with concrete amounts visible in sequence:
`create_leveraged_loan(...)` -> `fulfill_deposit(...)` -> `start_loan(...)` -> `redeem(...)`. Tests that
set custom fees/window (which must be snapshotted onto the loan at creation) run the create inline
instead. The `sign_centrifuge_offer` / `fund_centrifuge_leveraged` fixtures do the flat sign/mint/approve
boilerplate; `expected_pending_centrifuge_loan` builds the stored pending Loan for the hash assertion.

The CentrifugeAsyncVaultMock stands in for the Centrifuge AsyncVault; its `fulfill_*` / `process_cancel_*` hooks
are the off-chain issuer and are called inline where a test needs them.
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    RedeemResult,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    sign_offer,
    sign_redeem_result,
)
from .conftest import expected_pending_centrifuge_loan

BPS = 10000
EMPTY_MINT_RESULT = ((ZERO_ADDRESS, 0, 0, 0), (0, 0, 0))
EMPTY_REDEEM_RESULT = ((ZERO_ADDRESS, 0, 0, 0), (0, 0, 0))


# ---------------------------------------------------------------------------
# Lifecycle-stage fixtures (flat: each runs the full path from create with concrete amounts)
# ---------------------------------------------------------------------------


@pytest.fixture
def pending_loan(
    p2p_usdc_weth_centrifuge, sign_centrifuge_offer, fund_centrifuge_leveraged, kyc_borrower, kyc_lender, borrower, lender, now
):
    """A PENDING async loan (principal 1000 USDC, mint_spend 1500 -> 500 margin): deposit requested, not settled."""
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p_usdc_weth_centrifuge.wallet_to_vault(borrower)
    loan_id = p2p_usdc_weth_centrifuge.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p_usdc_weth_centrifuge, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    return loan, vault_addr


@pytest.fixture
def started_loan(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    owner,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    now,
):
    """A STARTED async loan: create -> issuer fulfils the deposit -> start_loan claims 1 weth of shares.

    start_loan runs via the protocol wallet (a non-borrower), so consuming this fixture also exercises
    the permissionless-start path.
    """
    principal, mint_spend, collateral, shares = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p_usdc_weth_centrifuge.wallet_to_vault(borrower)
    loan_id = p2p_usdc_weth_centrifuge.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    pending = expected_pending_centrifuge_loan(
        p2p_usdc_weth_centrifuge, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, shares)
    weth.mint(centrifuge_async_vault_mock.address, shares, sender=owner)  # the mock pays shares from its own balance
    p2p_usdc_weth_centrifuge.start_loan(pending, EMPTY_MINT_RESULT, sender=p2p_usdc_weth_centrifuge.protocol_wallet())
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=pending.amount, collateral_amount=shares)
    return started, vault_addr


@pytest.fixture
def redeeming_loan(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    owner,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    now,
):
    """(started_loan, redeeming_loan, vault_addr): a started async loan put into redemption (residual 0).

    Runs the full path inline: create -> fulfil deposit -> start_loan -> redeem(residual 0).
    """
    principal, mint_spend, collateral, shares = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p_usdc_weth_centrifuge.wallet_to_vault(borrower)
    loan_id = p2p_usdc_weth_centrifuge.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    pending = expected_pending_centrifuge_loan(
        p2p_usdc_weth_centrifuge, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, shares)
    weth.mint(centrifuge_async_vault_mock.address, shares, sender=owner)
    p2p_usdc_weth_centrifuge.start_loan(pending, EMPTY_MINT_RESULT, sender=p2p_usdc_weth_centrifuge.protocol_wallet())
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=pending.amount, collateral_amount=shares)

    p2p_usdc_weth_centrifuge.redeem(started, 0, sender=borrower)
    redeeming = started._replace(redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=0)
    return started, redeeming, vault_addr


# ---------------------------------------------------------------------------
# 1. create_leveraged_loan - async branch
# ---------------------------------------------------------------------------


def test_create_async_stores_pending_loan(p2p_usdc_weth_centrifuge, pending_loan):
    loan, _ = pending_loan
    assert loan.start_time == 0  # pending: not started
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)


def test_create_async_requests_deposit_of_full_mint_spend(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, usdc
):
    _, vault_addr = pending_loan
    mint_spend = 1500 * 10**6
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == mint_spend
    assert usdc.balanceOf(centrifuge_async_vault_mock.address) == mint_spend
    assert usdc.balanceOf(vault_addr) == 0  # funds went to the AsyncVault, not the loan vault


def test_create_async_mints_no_collateral_yet(pending_loan, weth):
    _, vault_addr = pending_loan
    assert weth.balanceOf(vault_addr) == 0  # no shares until the deposit settles and the loan starts


def test_create_async_commits_full_principal(p2p_usdc_weth_centrifuge, pending_loan, lender):
    loan, _ = pending_loan
    assert p2p_usdc_weth_centrifuge.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == loan.amount


def test_create_async_deploys_lender_and_borrower_funds(
    p2p_usdc_weth_centrifuge, centrifuge_signed_offer, kyc_borrower, kyc_lender, usdc, borrower, lender
):
    principal = 1000 * 10**6
    mint_spend = 1500 * 10**6
    borrower_margin = mint_spend - principal  # 500 USDC; origination fee 0

    usdc.mint(lender, principal)
    usdc.mint(borrower, borrower_margin)
    usdc.approve(p2p_usdc_weth_centrifuge.address, principal, sender=lender)
    usdc.approve(p2p_usdc_weth_centrifuge.address, borrower_margin, sender=borrower)
    lender_0, borrower_0 = usdc.balanceOf(lender), usdc.balanceOf(borrower)

    p2p_usdc_weth_centrifuge.create_leveraged_loan(
        centrifuge_signed_offer, principal, 10**18, kyc_borrower, kyc_lender, mint_spend, 10**18, sender=borrower
    )

    assert lender_0 - usdc.balanceOf(lender) == principal  # lender deploys the principal (net origination fee)
    assert borrower_0 - usdc.balanceOf(borrower) == borrower_margin  # borrower deploys the margin


def test_create_async_transfers_protocol_upfront_fee_to_wallet(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    owner,
):
    """The protocol upfront fee is pulled from the lender to the protocol wallet at create (async branch)."""
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_protocol_fee(200, 0, sender=owner)  # 2% upfront fee, lender-funded
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    protocol_upfront = 200 * principal // BPS  # 20 USDC
    signed_offer = sign_centrifuge_offer(principal)  # origination fee 0
    fund_centrifuge_leveraged(principal, mint_spend)
    protocol_wallet = p2p.protocol_wallet()
    lender_0, protocol_0 = usdc.balanceOf(lender), usdc.balanceOf(protocol_wallet)

    p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )

    assert usdc.balanceOf(protocol_wallet) - protocol_0 == protocol_upfront  # lender -> protocol wallet
    assert lender_0 - usdc.balanceOf(lender) == principal + protocol_upfront  # principal (net orig 0) + upfront


def test_create_async_logs_loan_created_event(
    p2p_usdc_weth_centrifuge,
    centrifuge_signed_offer,
    fund_centrifuge_leveraged,
    oracle,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    now,
):
    """D31: the async branch logs a full LoanCreated with start_time == 0 marking the loan pending.

    Replaces the deleted PendingLoanCreated event: the async create now emits the SAME pair as the sync
    branch (LoanCreated + LeveragedLoanCreated). collateral_amount is the caller's expected amount until
    LoanStarted overwrites it with the actual minted shares. Created inline (not via a fixture) so the
    create tx is the p2p's last computation for get_last_event — a p2p getter read would reset boa's log
    buffer (see the module docstring).
    """
    p2p = p2p_usdc_weth_centrifuge
    offer = centrifuge_signed_offer.offer
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    # Snapshot p2p fee getters BEFORE the create tx (reading them after would reset get_logs).
    upfront_fee_amount = p2p.protocol_upfront_fee() * principal // BPS
    settlement_fee = p2p.protocol_settlement_fee()
    partial_fee = p2p.partial_liquidation_fee()
    full_fee = p2p.full_liquidation_fee()

    loan_id = p2p.create_leveraged_loan(
        centrifuge_signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        collateral,
        sender=borrower,
    )

    # Reads on OTHER contracts (oracle) are safe after the tx; only a p2p view call resets get_logs.
    rate_num = oracle.latestRoundData().answer
    rate_den = 10 ** oracle.decimals()

    event = get_last_event(p2p, "LoanCreated")
    assert event.id == loan_id
    assert event.amount == principal
    assert event.apr == offer.apr
    assert event.payment_token == offer.payment_token
    assert event.maturity == now + offer.duration
    assert event.create_time == now
    assert event.start_time == 0  # D31: start_time == 0 marks the loan pending
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_token == offer.collateral_token
    assert event.collateral_amount == collateral  # the caller's expected amount, until LoanStarted
    assert event.min_collateral_amount == offer.min_collateral_amount
    assert event.call_eligibility == offer.call_eligibility
    assert event.call_window == offer.call_window
    assert event.liquidation_ltv == offer.liquidation_ltv
    assert event.oracle_addr == offer.oracle_addr
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == upfront_fee_amount
    assert event.protocol_settlement_fee == settlement_fee
    assert event.partial_liquidation_fee == partial_fee
    assert event.full_liquidation_fee == full_fee
    assert event.offer_id == compute_signed_offer_id(centrifuge_signed_offer)
    assert event.offer_tracing_id == offer.tracing_id
    assert event.oracle_rate_num == rate_num
    assert event.oracle_rate_den == rate_den
    assert event.vault_id == 0
    assert event.vault_addr == vault_addr


def test_create_async_logs_leveraged_event(
    p2p_usdc_weth_centrifuge, centrifuge_signed_offer, fund_centrifuge_leveraged, kyc_borrower, kyc_lender, borrower
):
    """D31: the async branch logs LeveragedLoanCreated with pending=True, acquired_collateral=0, and
    mint_deadline == create_time + max_pending_window (the Centrifuge-async fixture window is 50s).

    Created inline so the create tx is the p2p's last computation for get_last_event.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    fund_centrifuge_leveraged(principal, mint_spend)
    window = p2p.max_pending_window()
    assert window == 50  # Centrifuge-async fixture window (nonzero)

    create_ts = boa.eval("block.timestamp")
    loan_id = p2p.create_leveraged_loan(
        centrifuge_signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        collateral,
        sender=borrower,
    )

    event = get_last_event(p2p, "LeveragedLoanCreated")
    assert event.id == loan_id
    assert event.principal == principal  # async commits the FULL principal
    assert event.collateral_amount == collateral  # the caller's expected amount
    assert event.acquired_collateral == 0  # no shares minted yet (deposit still in flight)
    assert event.payment_spent == mint_spend
    assert event.borrower_margin == mint_spend - principal
    assert event.pending is True
    assert event.mint_deadline == create_ts + window  # create_time + max_pending_window (50s)


def test_create_async_reverts_if_mint_spend_lt_principal(
    p2p_usdc_weth_centrifuge, centrifuge_signed_offer, kyc_borrower, kyc_lender, borrower
):
    principal = 1000 * 10**6
    with boa.reverts("mint_spend lt principal"):
        p2p_usdc_weth_centrifuge.create_leveraged_loan(
            centrifuge_signed_offer,
            principal,
            10**18,
            kyc_borrower,
            kyc_lender,
            principal - 1,
            10**18,
            sender=borrower,
        )


def test_create_async_reverts_if_duration_le_pending_window(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    kyc_borrower,
    kyc_lender,
    lender_key,
    borrower,
    owner,
):
    """D30: the offer term must strictly outlast the pending window, so the permissionless-cancel valve
    opens before the loan can default. A `duration <= max_pending_window` offer must revert.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    p2p.set_max_pending_window(100, sender=owner)  # window == the async offer's 100s duration -> boundary
    base = sign_centrifuge_offer(principal)  # duration 100 (== window)
    signed_offer = sign_offer(base.offer, lender_key, p2p.address)  # re-sign to be explicit (unchanged)
    fund_centrifuge_leveraged(principal, mint_spend)
    assert signed_offer.offer.duration == p2p.max_pending_window()  # precondition: boundary (equality, not <)

    with boa.reverts("duration le pending window"):
        p2p.create_leveraged_loan(
            signed_offer,
            principal,
            collateral,
            kyc_borrower,
            kyc_lender,
            mint_spend,
            collateral,
            sender=borrower,
        )


def test_create_async_reverts_if_duration_lt_pending_window(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    kyc_borrower,
    kyc_lender,
    lender_key,
    borrower,
    owner,
):
    """D30 strict-inequality: a duration strictly BELOW the window also reverts."""
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    p2p.set_max_pending_window(200, sender=owner)  # window 200 > the offer's 100s duration
    base = sign_centrifuge_offer(principal)  # duration 100 < window 200
    signed_offer = sign_offer(base.offer, lender_key, p2p.address)
    fund_centrifuge_leveraged(principal, mint_spend)
    assert signed_offer.offer.duration < p2p.max_pending_window()  # precondition: strictly below the window

    with boa.reverts("duration le pending window"):
        p2p.create_leveraged_loan(
            signed_offer,
            principal,
            collateral,
            kyc_borrower,
            kyc_lender,
            mint_spend,
            collateral,
            sender=borrower,
        )


def test_create_async_window_zero_allows_any_duration(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    kyc_borrower,
    kyc_lender,
    lender_key,
    borrower,
    lender,
    owner,
    now,
):
    """D30: window 0 (valve disabled) passes the `duration > window` check trivially for ANY duration.

    Uses a short 1s duration to prove even the smallest positive term is accepted when the window is 0.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    p2p.set_max_pending_window(0, sender=owner)  # valve disabled
    base = sign_centrifuge_offer(principal)
    offer = base.offer._replace(duration=1)  # tiny 1s term: would fail against any positive window
    signed_offer = sign_offer(offer, lender_key, p2p.address)
    fund_centrifuge_leveraged(principal, mint_spend)
    assert signed_offer.offer.duration == 1
    assert p2p.max_pending_window() == 0  # precondition: window disabled

    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.maturity == now + 1  # 1s term accepted
    assert p2p.loans(loan.id) == compute_loan_hash(loan)  # pending loan created


def test_create_async_window_zero_logs_zero_mint_deadline(
    p2p_usdc_weth_centrifuge, centrifuge_signed_offer, fund_centrifuge_leveraged, kyc_borrower, kyc_lender, borrower, owner
):
    """D31: with the pending window disabled (0), the async LeveragedLoanCreated logs mint_deadline == 0.

    The window must be set BEFORE create so it's snapshotted onto the loan; the create is the p2p's last
    computation so get_last_event sees these logs (no p2p getter read afterwards).
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    p2p.set_max_pending_window(0, sender=owner)  # valve disabled BEFORE create -> snapshotted as 0
    fund_centrifuge_leveraged(principal, mint_spend)
    assert p2p.max_pending_window() == 0  # precondition: window disabled

    loan_id = p2p.create_leveraged_loan(
        centrifuge_signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        collateral,
        sender=borrower,
    )

    event = get_last_event(p2p, "LeveragedLoanCreated")
    assert event.id == loan_id
    assert event.pending is True  # still an async pending loan (duration 100 > window 0)
    assert event.acquired_collateral == 0
    assert event.mint_deadline == 0  # window 0 -> deadline 0 (valve disabled)


# ---------------------------------------------------------------------------
# 2. start_loan
# ---------------------------------------------------------------------------


def test_start_loan_reverts_if_mint_unfulfilled(p2p_usdc_weth_centrifuge, pending_loan, borrower):
    loan, _ = pending_loan
    with boa.reverts("mint not settled"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_start_loan_reverts_if_mint_underfilled(p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower):
    """D16/N5: a partial fill leaves request_pending > 0, so the loan stays blocked from starting."""
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6 - 1, 10**18)  # under-fill by 1
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 1
    with boa.reverts("mint not settled"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_start_loan_activates_against_minted_shares(p2p_usdc_weth_centrifuge, started_loan):
    loan, _ = started_loan
    assert loan.start_time == loan.create_time  # _is_loan_started
    assert loan.collateral_amount == 10**18  # collateral == the actually-minted shares
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)


def test_start_loan_delivers_collateral_to_vault(started_loan, weth):
    _, vault_addr = started_loan
    assert weth.balanceOf(vault_addr) == 10**18  # the claimed shares landed in the loan vault


def test_start_loan_is_permissionless(p2p_usdc_weth_centrifuge, started_loan, borrower):
    """D20: a keeper (not the borrower) can start a fully-fulfilled pending loan.

    The `started_loan` fixture starts the loan via the protocol wallet (a non-borrower), so a successful
    start proves the permissionless path.
    """
    loan, _ = started_loan
    assert p2p_usdc_weth_centrifuge.protocol_wallet() != borrower
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)  # started successfully by a non-borrower


def test_start_loan_logs_event(p2p_usdc_weth_centrifuge, started_loan, borrower, lender):
    loan, _ = started_loan
    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanStarted")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.start_time == loan.start_time
    assert event.maturity == loan.maturity
    assert event.collateral_amount == 10**18


def test_start_loan_reverts_if_already_started(p2p_usdc_weth_centrifuge, started_loan, borrower):
    loan, _ = started_loan
    with boa.reverts("loan started"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_start_loan_reverts_if_loan_invalid(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    with boa.reverts("invalid loan"):
        p2p_usdc_weth_centrifuge.start_loan(loan._replace(amount=loan.amount + 1), EMPTY_MINT_RESULT, sender=borrower)


def test_start_loan_reverts_if_pending_loan_defaulted(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """D28: a pending loan past maturity can no longer be started (it would be born defaulted).

    The deposit is fully fulfilled (so the mint gate would otherwise pass), but time-travelling beyond
    the offer's 100s duration trips the earlier `not defaulted` gate.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    boa.env.time_travel(seconds=loan.maturity - loan.create_time + 1)  # 1s past maturity
    assert boa.eval("block.timestamp") > loan.maturity  # precondition: defaulted
    with boa.reverts("loan defaulted"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_start_loan_reverts_if_minted_below_min_collateral(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    owner,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    now,
):
    """D28: a fulfilled fill below the offer's min_collateral_amount cannot start (must be force-unwound).

    The offer demands min_collateral_amount == 10**18 but the issuer fulfils only 0.9 weth of shares.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral, min_collateral = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    fulfilled_shares = 9 * 10**17  # 0.9 weth: below the 1.0 weth min
    signed_offer = sign_centrifuge_offer(principal, min_collateral_amount=min_collateral)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.min_collateral_amount == min_collateral

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, fulfilled_shares)  # fully fulfilled, but low shares
    weth.mint(centrifuge_async_vault_mock.address, fulfilled_shares, sender=owner)
    assert fulfilled_shares < loan.min_collateral_amount  # precondition: below min
    with boa.reverts("low collateral amount"):
        p2p.start_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_started_async_loan_settles_like_any_loan(p2p_usdc_weth_centrifuge, started_loan, usdc, weth, borrower, lender):
    """Normal-lifecycle sanity: a started async loan settles like a plain loan."""
    loan, _ = started_loan
    boa.env.time_travel(seconds=50)
    interest = loan.get_interest(boa.eval("block.timestamp"))
    assert interest > 0

    lender_0 = usdc.balanceOf(lender)
    usdc.mint(borrower, loan.amount + interest)
    usdc.approve(p2p_usdc_weth_centrifuge.address, loan.amount + interest, sender=borrower)
    p2p_usdc_weth_centrifuge.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)

    assert p2p_usdc_weth_centrifuge.loans(loan.id) == ZERO_BYTES32
    assert weth.balanceOf(borrower) == 10**18  # collateral returned
    assert usdc.balanceOf(lender) - lender_0 == loan.amount + interest  # settlement fee is 0


# ---------------------------------------------------------------------------
# 3. cancel_pending_loan  (two-phase deposit-cancel state machine, liquidation-style unwind)
# ---------------------------------------------------------------------------


def test_cancel_pending_requests_cancel_when_deposit_pending(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower
):
    """Branch 1 (request_pending > 0): submit the cancellation, return False."""
    loan, vault_addr = pending_loan
    assert p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 0  # moved into the cancel pipeline
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True


def test_cancel_pending_returns_false_while_cancel_pending(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower
):
    """Branch 2 (cancel submitted, not yet processed): still return False, loan unchanged."""
    loan, vault_addr = pending_loan
    p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)  # request the cancel
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True

    assert p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)  # still pending


def test_cancel_pending_reverts_if_mint_claimable_and_startable(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A STARTABLE fulfilled deposit (fill >= min_collateral, not defaulted): the borrower must start, not cancel."""
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)  # deposit settled -> claimable
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)  # so the claim (undone by the revert) can pay
    assert loan.min_collateral_amount == 0  # any positive fill is >= min -> startable
    with boa.reverts("claimable mint, start instead"):
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_cancel_pending_reverts_if_not_borrower_before_window(p2p_usdc_weth_centrifuge, pending_loan, borrower, accounts):
    loan, _ = pending_loan
    stranger = accounts[6]
    assert stranger != borrower
    with boa.reverts("not borrower"):
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=stranger)


def test_cancel_pending_is_permissionless_after_window(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower, accounts
):
    """D18: after create_time + max_pending_window anyone may cancel a still-pending loan."""
    loan, vault_addr = pending_loan
    boa.env.time_travel(seconds=p2p_usdc_weth_centrifuge.max_pending_window() + 1)
    stranger = accounts[6]
    assert stranger != borrower
    assert (
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=stranger) is False
    )  # branch 1: submits the cancel
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True


def test_cancel_pending_covered_pays_keeper_lender_protocol_and_surplus(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """COVERED liquidation-style cancel (A4): margin (500 USDC) >> interest, so the debt is fully covered.

    A keeper drives the permissionless cancel and earns the full liquidation fee; the lender recovers
    deployed capital + capped interest net of the protocol fee; the borrower keeps the surplus. Each leg
    is computed inline from the loan and asserted as a balance delta, plus the 4-leg conservation.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18  # margin 500 USDC
    origination_fee_bps = 100  # 1% -> lender_deployed = loan.amount - origination_fee_amount
    signed_offer = sign_centrifuge_offer(principal, origination_fee_bps=origination_fee_bps)
    fund_centrifuge_leveraged(principal, mint_spend, origination_fee_bps=origination_fee_bps)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.full_liquidation_fee == 500  # snapshotted onto the loan
    assert loan.protocol_settlement_fee == 1000
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS  # nonzero fee snapshot

    keeper = accounts[6]
    assert keeper not in {borrower, lender, owner}
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # past window -> permissionless
    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper)  # phase 1: request the cancel
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)  # issuer settles it -> cancel_claimable

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    lender_deployed = loan.amount - loan.origination_fee_amount  # lender never deployed the origination fee
    debt = lender_deployed + interest
    keeper_fee = debt * 500 // BPS
    protocol_fee = interest * 1000 // BPS
    lender_recovery = debt - protocol_fee
    borrower_surplus = mint_spend - keeper_fee - debt
    assert lender_deployed < loan.amount  # the origination-fee term actually bites
    assert interest > 0  # covered, both fees live
    assert keeper_fee > 0
    assert protocol_fee > 0
    assert borrower_surplus > 0

    protocol_wallet = p2p.protocol_wallet()
    keeper_0, lender_0, borrower_0, protocol_0 = (usdc.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))
    assert usdc.balanceOf(centrifuge_async_vault_mock.address) == mint_spend  # available == the reclaimed payment

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    assert usdc.balanceOf(keeper) - keeper_0 == keeper_fee
    assert usdc.balanceOf(lender) - lender_0 == lender_recovery
    assert usdc.balanceOf(protocol_wallet) - protocol_0 == protocol_fee
    assert usdc.balanceOf(borrower) - borrower_0 == borrower_surplus
    assert keeper_fee + lender_recovery + protocol_fee + borrower_surplus == mint_spend  # conservation
    assert p2p.loans(loan.id) == ZERO_BYTES32
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == 0


def test_cancel_pending_shortfall_permissionless_with_unfunded_borrower(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """A4 REGRESSION LOCK: a shortfall cancel by a keeper while the borrower holds NO funds must SUCCEED.

    Margin is 100 wei, far below the accrued interest, so the debt can't be fully covered. Pre-fix the
    settle branch pulled the shortfall from the borrower via transferFrom and REVERTED for an
    absent/unfunded borrower (a stuck-funds vector). Post-fix the lender absorbs the shortfall as a
    liquidation loss, the borrower neither pays nor receives, and the keeper is still paid.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)
    p2p.set_protocol_fee(0, 1000, sender=owner)
    principal, collateral = 1000 * 10**6, 10**18
    mint_spend = principal + 100  # margin = 100 wei << accrued interest -> shortfall
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )

    keeper = accounts[6]
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # past window (t=51), still pending (< maturity 100)
    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper)
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    assert boa.eval("block.timestamp") <= loan.maturity  # precondition: not maturity-capped, accrues to now
    assert interest > mint_spend - loan.amount  # precondition: interest ate the whole margin (shortfall)
    keeper_fee = (loan.amount + interest) * 500 // BPS
    available_after_fee = mint_spend - keeper_fee
    protocol_fee = interest * 1000 // BPS
    lender_recovery = available_after_fee - protocol_fee  # lender absorbs the loss; gets < debt

    # A4 CORE: the borrower is completely unfunded - no balance and no allowance to top anything up.
    assert usdc.balanceOf(borrower) == 0
    assert usdc.allowance(borrower, p2p.address) == 0

    protocol_wallet = p2p.protocol_wallet()
    keeper_0, lender_0, protocol_0 = usdc.balanceOf(keeper), usdc.balanceOf(lender), usdc.balanceOf(protocol_wallet)

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True  # pre-fix this reverted

    assert usdc.balanceOf(keeper) - keeper_0 == keeper_fee  # keeper still paid
    assert usdc.balanceOf(lender) - lender_0 == lender_recovery
    assert lender_recovery < loan.amount + interest  # lender absorbed the uncollected interest
    assert usdc.balanceOf(protocol_wallet) - protocol_0 == protocol_fee
    assert usdc.balanceOf(borrower) == 0  # borrower neither paid in nor received anything
    assert keeper_fee + lender_recovery + protocol_fee == mint_spend  # conservation, no borrower leg


def test_cancel_pending_interest_capped_at_maturity(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    accounts,
    now,
):
    """M4: interest is capped at maturity - a cancel ~10 years after a 100s loan charges only up-to-maturity interest.

    The maturity-capped interest is tiny (covered, borrower keeps a surplus); the UNCAPPED
    block.timestamp-based interest would exceed the margin (shortfall, borrower gets 0). We assert the
    borrower received the surplus computed with the CAPPED interest, proving no unbounded accrual.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18  # margin 500 USDC
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )

    keeper = accounts[6]
    boa.env.time_travel(seconds=10 * 365 * 24 * 3600)  # 10 years: far past the 100s maturity
    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper)
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)

    ts = boa.eval("block.timestamp")
    capped = loan.get_capped_interest(ts)
    uncapped = loan.get_interest(ts)  # unbounded: block.timestamp - accrual_start
    assert uncapped > capped  # precondition: the cap actually bites
    assert mint_spend >= loan.amount + capped  # capped -> covered
    assert mint_spend < loan.amount + uncapped  # uncapped would be a shortfall

    borrower_0, lender_0 = usdc.balanceOf(borrower), usdc.balanceOf(lender)
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    assert usdc.balanceOf(borrower) - borrower_0 == mint_spend - loan.amount - capped  # surplus uses CAPPED interest
    assert usdc.balanceOf(lender) - lender_0 == loan.amount + capped  # lender: deployed + capped interest (fees 0)


def test_cancel_pending_borrower_self_cancel_keeps_fee(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    owner,
    now,
):
    """Borrower self-cancel: the keeper fee returns to the borrower (net-neutral vs a keeper cancel)."""
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )

    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)  # phase 1
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    debt = loan.amount + interest
    keeper_fee = debt * 500 // BPS
    borrower_surplus = mint_spend - keeper_fee - debt

    borrower_0, lender_0 = usdc.balanceOf(borrower), usdc.balanceOf(lender)
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is True

    # caller == borrower -> the borrower receives BOTH the keeper fee and the surplus
    assert usdc.balanceOf(borrower) - borrower_0 == keeper_fee + borrower_surplus
    assert usdc.balanceOf(lender) - lender_0 == debt  # protocol fee is 0


def test_cancel_pending_zero_liquidation_fee_pays_no_keeper(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    accounts,
    now,
):
    """full_liquidation_fee == 0 (default): the caller earns nothing; lender + borrower split the payment."""
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.full_liquidation_fee == 0
    assert loan.protocol_settlement_fee == 0

    keeper = accounts[6]
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)
    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper)
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    lender_recovery = loan.amount + interest
    borrower_surplus = mint_spend - lender_recovery

    keeper_0, lender_0, borrower_0 = usdc.balanceOf(keeper), usdc.balanceOf(lender), usdc.balanceOf(borrower)
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    assert usdc.balanceOf(keeper) == keeper_0  # no keeper cut
    assert usdc.balanceOf(lender) - lender_0 == lender_recovery
    assert usdc.balanceOf(borrower) - borrower_0 == borrower_surplus
    assert lender_recovery + borrower_surplus == mint_spend


def test_cancel_pending_logs_event(p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower, lender):
    loan, vault_addr = pending_loan
    p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)
    p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)

    event = get_last_event(p2p_usdc_weth_centrifuge, "PendingLoanCancelled")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.payment_refunded == 1500 * 10**6
    assert event.caller == borrower


# ---------------------------------------------------------------------------
# 3b. cancel_pending_loan force-unwind (fulfilled-but-not-startable deposit, share-denominated)
# ---------------------------------------------------------------------------
#
# When the deposit is FULLY fulfilled (request_claimable > 0) but the loan is NOT startable — a fill
# below min_collateral_amount, or a fill past maturity (defaulted) — the ERC-7540 request can't be
# cancelled, so cancel_pending_loan claims the shares and splits them oracle-valued, liquidation-style.
# All legs are paid in COLLATERAL SHARES (weth), unlike the payment-token cancel_claimable branch above.
#
# Oracle (conftest `oracle`): rate_num = 387780390000, rate_den = 10**8. usdc = 6 decimals,
# weth = 18 decimals. minted_value (USDC) = minted * rate_num * 10**6 // (rate_den * 10**18);
# value -> shares is the exact inverse the contract uses.

RATE_NUM = 387780390000
RATE_DEN = 10**8
PAYMENT_DEC = 10**6
COLLATERAL_DEC = 10**18


def _shares_to_value(shares):
    return shares * RATE_NUM * PAYMENT_DEC // (RATE_DEN * COLLATERAL_DEC)


def _value_to_shares(value):
    return value * RATE_DEN * COLLATERAL_DEC // (RATE_NUM * PAYMENT_DEC)


def test_cancel_pending_force_unwind_covered_splits_shares(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """COVERED force-unwind: a fulfilled-but-defaulted deposit (full 1 weth) is claimed and split in shares.

    minted_value (~3877 USDC) >> debt, so the waterfall pays keeper the liquidation fee, protocol the
    settlement fee on interest, the lender its deployed capital + interest net protocol fee, and the
    borrower the surplus shares (incl. dust). A keeper (post-window) drives it; all legs asserted as
    share balances plus the 4-leg conservation and the PendingLoanLiquidated event.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    minted = 10**18  # full fill (>= min 0), but defaulted -> not startable
    origination_fee_bps = 100  # 1% -> lender never deploys the origination fee
    signed_offer = sign_centrifuge_offer(principal, origination_fee_bps=origination_fee_bps)
    fund_centrifuge_leveraged(principal, mint_spend, origination_fee_bps=origination_fee_bps)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.full_liquidation_fee == 500
    assert loan.protocol_settlement_fee == 1000
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS  # nonzero fee snapshot

    # Fulfil the deposit fully, fund the mock to pay the shares, then default the loan.
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, minted)
    weth.mint(centrifuge_async_vault_mock.address, minted, sender=owner)
    keeper = accounts[6]
    assert keeper not in {borrower, lender, owner}
    # This test exercises the DEFAULTED force-unwind trigger (a full fill >= min IS startable, so it can
    # only unwind once past maturity). Window (50s) < maturity (100s) now, so travel explicitly PAST
    # MATURITY (t=101) — that also clears the window, unlocking the permissionless keeper path.
    boa.env.time_travel(seconds=loan.maturity - loan.create_time + 1)
    assert boa.eval("block.timestamp") > loan.maturity  # defaulted -> not startable
    assert boa.eval("block.timestamp") > loan.create_time + loan.max_pending_window  # keeper allowed
    assert minted >= loan.min_collateral_amount  # the OTHER unwind trigger (defaulted, not low-fill)

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))  # capped at maturity
    lender_deployed = loan.amount - loan.origination_fee_amount
    debt = lender_deployed + interest
    minted_value = _shares_to_value(minted)
    liquidation_fee_value = min(debt * 500 // BPS, minted_value)
    value_after_fee = minted_value - liquidation_fee_value
    protocol_fee_value = min(1000 * interest // BPS, value_after_fee)
    assert value_after_fee >= debt  # precondition: COVERED
    liquidation_fee_shares = _value_to_shares(liquidation_fee_value)
    protocol_fee_shares = _value_to_shares(protocol_fee_value)
    lender_shares = _value_to_shares(debt - protocol_fee_value)
    borrower_shares = minted - liquidation_fee_shares - protocol_fee_shares - lender_shares
    assert liquidation_fee_shares > 0
    assert protocol_fee_shares > 0
    assert borrower_shares > 0  # surplus kept by the borrower

    protocol_wallet = p2p.protocol_wallet()
    keeper_0, lender_0, borrower_0, protocol_0 = (weth.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    # Read the event first: any later same-contract view call resets boa's last-computation log buffer.
    event = get_last_event(p2p, "PendingLoanLiquidated")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == minted
    assert event.lender_amount == lender_shares
    assert event.liquidation_fee == liquidation_fee_shares
    assert event.protocol_fee == protocol_fee_shares
    assert event.borrower_amount == borrower_shares
    assert event.caller == keeper

    assert weth.balanceOf(keeper) - keeper_0 == liquidation_fee_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert weth.balanceOf(protocol_wallet) - protocol_0 == protocol_fee_shares
    assert weth.balanceOf(borrower) - borrower_0 == borrower_shares
    assert liquidation_fee_shares + lender_shares + protocol_fee_shares + borrower_shares == minted  # conservation
    assert p2p.loans(loan.id) == ZERO_BYTES32
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == 0


def test_cancel_pending_force_unwind_keeper_below_min_not_defaulted_covered_splits_shares(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """Keeper force-unwind of a below-min fill that is NOT defaulted (the low-fill trigger in isolation).

    Previously untestable: with window > maturity, "past window" always implied "past maturity", so the
    keeper path could only reach the DEFAULTED trigger. With window (50s) < duration (100s), a keeper can
    now act past the window (t=51) while the loan is still pending (t < maturity 100). The unwind fires
    purely on the below-min fill (minted 1 weth < min 2 weth), not on default. The fill is worth ~3877
    USDC so the split is COVERED: keeper takes the liquidation fee, protocol the settlement fee on the
    (uncapped, accrue-to-now) interest, the lender its deployed capital + interest, the borrower the
    surplus shares. All legs in weth; conservation + the PendingLoanLiquidated event asserted.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    min_collateral = 2 * 10**18  # demand 2 weth
    collateral_estimate = min_collateral  # the create-time estimate must satisfy the offer min
    minted = 10**18  # ACTUAL fill: 1 weth, below min (not startable) but worth ~3877 USDC (covered)
    origination_fee_bps = 100  # 1% -> lender never deploys the origination fee
    signed_offer = sign_centrifuge_offer(
        principal, origination_fee_bps=origination_fee_bps, min_collateral_amount=min_collateral
    )
    fund_centrifuge_leveraged(principal, mint_spend, origination_fee_bps=origination_fee_bps)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral_estimate,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral,
        sender=borrower,
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral_estimate
    )
    assert loan.full_liquidation_fee == 500
    assert loan.protocol_settlement_fee == 1000
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS  # nonzero fee snapshot

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, minted)  # fully fulfilled, below-min shares
    weth.mint(centrifuge_async_vault_mock.address, minted, sender=owner)
    keeper = accounts[6]
    assert keeper not in {borrower, lender, owner}
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # t=51: past window, still pending

    # Preconditions: the trigger is the below-min fill, NOT default; interest accrues to NOW (uncapped).
    now_ts = boa.eval("block.timestamp")
    assert now_ts > loan.create_time + loan.max_pending_window  # keeper allowed (past window)
    assert now_ts <= loan.maturity  # NOT defaulted
    assert minted < loan.min_collateral_amount  # THE trigger: below-min fill
    assert loan.get_capped_interest(now_ts) == loan.get_interest(now_ts)  # capped path is NOT active

    interest = loan.get_capped_interest(now_ts)
    lender_deployed = loan.amount - loan.origination_fee_amount
    debt = lender_deployed + interest
    minted_value = _shares_to_value(minted)
    liquidation_fee_value = min(debt * 500 // BPS, minted_value)
    value_after_fee = minted_value - liquidation_fee_value
    protocol_fee_value = min(1000 * interest // BPS, value_after_fee)
    assert value_after_fee >= debt  # precondition: COVERED
    liquidation_fee_shares = _value_to_shares(liquidation_fee_value)
    protocol_fee_shares = _value_to_shares(protocol_fee_value)
    lender_shares = _value_to_shares(debt - protocol_fee_value)
    borrower_shares = minted - liquidation_fee_shares - protocol_fee_shares - lender_shares
    assert liquidation_fee_shares > 0
    assert protocol_fee_shares > 0
    assert borrower_shares > 0  # surplus kept by the borrower

    protocol_wallet = p2p.protocol_wallet()
    keeper_0, lender_0, borrower_0, protocol_0 = (weth.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    # Read the event first: any later same-contract view call resets boa's last-computation log buffer.
    event = get_last_event(p2p, "PendingLoanLiquidated")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == minted
    assert event.lender_amount == lender_shares
    assert event.liquidation_fee == liquidation_fee_shares
    assert event.protocol_fee == protocol_fee_shares
    assert event.borrower_amount == borrower_shares
    assert event.caller == keeper

    assert weth.balanceOf(keeper) - keeper_0 == liquidation_fee_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert weth.balanceOf(protocol_wallet) - protocol_0 == protocol_fee_shares
    assert weth.balanceOf(borrower) - borrower_0 == borrower_shares
    assert liquidation_fee_shares + lender_shares + protocol_fee_shares + borrower_shares == minted  # conservation
    assert p2p.loans(loan.id) == ZERO_BYTES32
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == 0


def test_cancel_pending_force_unwind_shortfall_gives_lender_all_shares(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """SHORTFALL force-unwind: a below-min fill so tiny its oracle value can't cover the debt.

    A 1000-wei fill (< min 10**18) is worth far less than the ~1000 USDC debt, so after the keeper fee
    the lender absorbs the whole remainder (all remaining shares) and the borrower gets 0.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)
    p2p.set_protocol_fee(0, 1000, sender=owner)
    principal, mint_spend, collateral, min_collateral = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    minted = 1000  # 1000 wei of weth: below min AND worth ~0 USDC -> shortfall
    signed_offer = sign_centrifuge_offer(principal, min_collateral_amount=min_collateral)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, minted)
    weth.mint(centrifuge_async_vault_mock.address, minted, sender=owner)
    keeper = accounts[6]
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # past window -> keeper allowed
    assert minted < loan.min_collateral_amount  # below-min -> not startable (the unwind trigger)

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    debt = loan.amount - loan.origination_fee_amount + interest
    minted_value = _shares_to_value(minted)
    liquidation_fee_value = min(debt * 500 // BPS, minted_value)
    value_after_fee = minted_value - liquidation_fee_value
    protocol_fee_value = min(1000 * interest // BPS, value_after_fee)
    assert value_after_fee < debt  # precondition: SHORTFALL
    liquidation_fee_shares = _value_to_shares(liquidation_fee_value)
    protocol_fee_shares = _value_to_shares(protocol_fee_value)
    lender_shares = minted - liquidation_fee_shares - protocol_fee_shares  # lender absorbs all remaining

    keeper_0, lender_0, borrower_0 = (weth.balanceOf(a) for a in (keeper, lender, borrower))

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    assert weth.balanceOf(keeper) - keeper_0 == liquidation_fee_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert weth.balanceOf(borrower) == borrower_0  # borrower gets NOTHING on a shortfall
    assert liquidation_fee_shares + protocol_fee_shares + lender_shares == minted  # conservation
    assert p2p.loans(loan.id) == ZERO_BYTES32


def test_cancel_pending_force_unwind_borrower_self_cancel_before_window(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    now,
):
    """Borrower self-cancels a below-min fill BEFORE the window: the borrower-only auth path works.

    caller == borrower, so the borrower is paid the liquidation fee AND (here, covered) the surplus —
    net-neutral vs a keeper unwind. Uses a full-value fill (worth ~3877 USDC) that is still below-min so
    it is not startable but IS covered.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    min_collateral = 2 * 10**18  # demand 2 weth
    collateral_estimate = min_collateral  # the create-time estimate must satisfy the offer min
    minted = 10**18  # ACTUAL fill: 1 weth, below min (not startable) but worth ~3877 USDC (covered)
    signed_offer = sign_centrifuge_offer(principal, min_collateral_amount=min_collateral)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral_estimate,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral,
        sender=borrower,
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral_estimate
    )
    assert loan.min_collateral_amount == min_collateral

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, minted)
    weth.mint(centrifuge_async_vault_mock.address, minted, sender=owner)
    assert minted < loan.min_collateral_amount  # below-min -> not startable
    assert boa.eval("block.timestamp") < loan.create_time + loan.max_pending_window  # before window

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    debt = loan.amount - loan.origination_fee_amount + interest
    minted_value = _shares_to_value(minted)
    liquidation_fee_value = min(debt * 500 // BPS, minted_value)
    value_after_fee = minted_value - liquidation_fee_value
    assert value_after_fee >= debt  # covered
    liquidation_fee_shares = _value_to_shares(liquidation_fee_value)
    lender_shares = _value_to_shares(debt)  # protocol fee is 0
    borrower_surplus_shares = minted - liquidation_fee_shares - lender_shares

    borrower_0, lender_0 = weth.balanceOf(borrower), weth.balanceOf(lender)

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is True  # borrower-only path

    # caller == borrower -> borrower receives BOTH the liquidation fee and the surplus shares
    assert weth.balanceOf(borrower) - borrower_0 == liquidation_fee_shares + borrower_surplus_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert p2p.loans(loan.id) == ZERO_BYTES32


def test_cancel_pending_force_unwind_reverts_if_partial_fill(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A partial fill leaves request_pending > 0 alongside request_claimable > 0 -> "deposit still pending".

    The claimable branch refuses to act while the deposit could still change (N5 partial-fill guard).
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6 - 1, 10**18)  # fulfil all but 1 wei of assets
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    assert centrifuge_async_vault_mock.deposit_claimable(vault_addr) > 0
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 1  # still 1 wei pending
    with boa.reverts("deposit still pending"):
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


# ---------------------------------------------------------------------------
# 4. cancel_redeem  (two-phase redeem-cancel state machine)
# ---------------------------------------------------------------------------


def test_redeem_requests_async_redemption(p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, weth):
    _, redeeming, vault_addr = redeeming_loan
    assert redeeming.redeem_start > 0
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) == 10**18  # shares pulled into the AsyncVault
    assert weth.balanceOf(vault_addr) == 0
    assert p2p_usdc_weth_centrifuge.loans(redeeming.id) == compute_loan_hash(redeeming)


def test_cancel_redeem_requests_cancel_when_redeem_pending(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower
):
    """Branch 1 (request_pending > 0): submit the redeem cancellation, return False."""
    _, redeeming, vault_addr = redeeming_loan
    assert p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower) is False
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) == 0
    assert centrifuge_async_vault_mock.redeem_cancel_pending(vault_addr) is True


def test_cancel_redeem_returns_false_while_cancel_pending(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower
):
    """Branch 2 (cancel submitted, not processed): still return False, loan unchanged."""
    _, redeeming, vault_addr = redeeming_loan
    p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)
    assert centrifuge_async_vault_mock.redeem_cancel_pending(vault_addr) is True
    assert p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower) is False
    assert p2p_usdc_weth_centrifuge.loans(redeeming.id) == compute_loan_hash(redeeming)


def test_cancel_redeem_reverses_redemption_when_cancel_claimable(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, weth, borrower
):
    """Branch 3 (cancel_claimable > 0): reclaim the shares and reverse the redemption (D4)."""
    started, redeeming, vault_addr = redeeming_loan
    p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)  # request cancel
    centrifuge_async_vault_mock.process_cancel_redeem(vault_addr)  # issuer settles it

    assert p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower) is True
    assert p2p_usdc_weth_centrifuge.loans(started.id) == compute_loan_hash(started)  # back to the pre-redeem loan
    assert weth.balanceOf(vault_addr) == 10**18  # shares reclaimed into the vault
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) == 0


def test_cancel_redeem_logs_event(p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower, lender):
    _, redeeming, vault_addr = redeeming_loan
    p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)
    centrifuge_async_vault_mock.process_cancel_redeem(vault_addr)
    p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)

    event = get_last_event(p2p_usdc_weth_centrifuge, "RedeemCancelled")
    assert event.loan_id == redeeming.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.vault_id == 0


def test_cancel_redeem_reverts_if_not_redeeming(p2p_usdc_weth_centrifuge, started_loan, borrower):
    loan, _ = started_loan  # started but never entered redemption
    with boa.reverts("not redeeming"):
        p2p_usdc_weth_centrifuge.cancel_redeem(loan, sender=borrower)


def test_cancel_redeem_reverts_if_not_borrower(p2p_usdc_weth_centrifuge, redeeming_loan, borrower, accounts):
    _, redeeming, _ = redeeming_loan
    stranger = accounts[6]
    assert stranger != borrower
    with boa.reverts("not borrower"):
        p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=stranger)


def test_cancel_redeem_reverts_if_redeem_claimable(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, usdc, borrower
):
    """Guard twin of "claimable mint, start instead": once the redemption is fully fulfilled
    (request_claimable > 0) the payment has landed, so the borrower must settle, not cancel."""
    _, redeeming, vault_addr = redeeming_loan
    shares, assets = 10**18, 900 * 10**6  # the whole redeemed collateral settles to 900 USDC
    usdc.mint(centrifuge_async_vault_mock.address, assets)  # fund the mock to pay the redeem out
    centrifuge_async_vault_mock.fulfill_redeem(vault_addr, shares, assets)
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == shares  # precondition: claimable (in shares)

    with boa.reverts("claimable redeem, settle first"):
        p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)


# ---------------------------------------------------------------------------
# 4b. transfer_loan of an async-redeeming loan (D29)
# ---------------------------------------------------------------------------


def test_transfer_loan_reverts_for_async_redeem_even_with_valid_attestation(
    p2p_usdc_weth_centrifuge, redeeming_loan, transfer_agent, kyc_for, kyc_validator_contract, owner_key, now
):
    """D29: transfer_loan of a REDEEM_ASYNC loan in redemption reverts even WITH a valid owner attestation.

    `_is_loan_redeem_concluded` now returns False for REDEEM_ASYNC unconditionally: the ERC-7540 claim
    is bound to THIS vault and only executes inside settle/liquidate, so accepting an owner-signed result
    here would move the loan to a new vault and orphan the in-flight redeem. A correctly owner-signed,
    vault-bound, post-redeem-start RedeemResult must still be rejected.
    """
    _, redeeming, vault_addr = redeeming_loan
    p2p = p2p_usdc_weth_centrifuge

    # A redeem result that WOULD conclude a manual redemption: owner-signed, this vault, after redeem_start.
    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=redeeming.amount,
        timestamp=redeeming.redeem_start + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)
    assert redeem_result.timestamp >= redeeming.redeem_start  # precondition: attestation is fresh
    assert redeem_result.vault == vault_addr  # precondition: attestation is vault-bound

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    with boa.reverts("redeem not concluded"):
        p2p.transfer_loan(redeeming, new_borrower, new_borrower_kyc, signed_redeem_result, sender=transfer_agent)


# ---------------------------------------------------------------------------
# 5. Direct P2PLendingVaultCentrifugeAsync unit tests (status views + caller auth)
# ---------------------------------------------------------------------------


def _standalone_vault(centrifuge_async_vault_impl_contract_def, token, owner):
    vault = centrifuge_async_vault_impl_contract_def.deploy()
    vault.initialise(owner, token.address)  # caller = boa.env.eoa (owner)
    return vault


def test_mint_status_zero_for_empty_vault_address(centrifuge_async_vault_impl_contract_def, weth, owner):
    vault = _standalone_vault(centrifuge_async_vault_impl_contract_def, weth, owner)
    assert tuple(vault.mint_status(ZERO_ADDRESS)) == (0, 0, 0, 0)


def test_mint_status_reflects_pending_then_claimable(
    centrifuge_async_vault_impl_contract_def, centrifuge_async_vault_mock, usdc, weth, owner
):
    vault = _standalone_vault(centrifuge_async_vault_impl_contract_def, weth, owner)
    amount, shares = 1000 * 10**6, 10**18
    usdc.mint(vault.address, amount)
    vault.mint_async(usdc.address, centrifuge_async_vault_mock.address, 0, amount, sender=owner)
    assert tuple(vault.mint_status(centrifuge_async_vault_mock.address)) == (amount, 0, 0, 0)  # pending

    centrifuge_async_vault_mock.fulfill_deposit(vault.address, amount, shares)
    assert tuple(vault.mint_status(centrifuge_async_vault_mock.address)) == (0, amount, 0, 0)  # claimable


def test_mint_status_reflects_cancel_states(
    centrifuge_async_vault_impl_contract_def, centrifuge_async_vault_mock, usdc, weth, owner
):
    vault = _standalone_vault(centrifuge_async_vault_impl_contract_def, weth, owner)
    amount = 1000 * 10**6
    usdc.mint(vault.address, amount)
    vault.mint_async(usdc.address, centrifuge_async_vault_mock.address, 0, amount, sender=owner)

    vault.cancel_mint(centrifuge_async_vault_mock.address, sender=owner)
    assert tuple(vault.mint_status(centrifuge_async_vault_mock.address)) == (0, 0, 1, 0)  # cancel in-flight

    centrifuge_async_vault_mock.process_cancel_deposit(vault.address)
    assert tuple(vault.mint_status(centrifuge_async_vault_mock.address)) == (0, 0, 0, amount)  # reclaimable payment


def test_redeem_status_reflects_pending_and_cancel(
    centrifuge_async_vault_impl_contract_def, centrifuge_async_vault_mock, weth, owner
):
    vault = _standalone_vault(centrifuge_async_vault_impl_contract_def, weth, owner)
    shares = 10**18
    weth.mint(vault.address, shares, sender=owner)
    vault.redeem_async(centrifuge_async_vault_mock.address, weth.address, shares, 1, 1, sender=owner)
    assert tuple(vault.redeem_status(centrifuge_async_vault_mock.address)) == (shares, 0, 0, 0)

    vault.cancel_redeem(centrifuge_async_vault_mock.address, sender=owner)
    assert tuple(vault.redeem_status(centrifuge_async_vault_mock.address)) == (0, 0, 1, 0)

    centrifuge_async_vault_mock.process_cancel_redeem(vault.address)
    assert tuple(vault.redeem_status(centrifuge_async_vault_mock.address)) == (0, 0, 0, shares)


def test_centrifuge_async_vault_caller_gated_functions_revert_for_stranger(
    centrifuge_async_vault_impl_contract_def, centrifuge_async_vault_mock, usdc, weth, owner, accounts
):
    vault = _standalone_vault(centrifuge_async_vault_impl_contract_def, weth, owner)
    m = centrifuge_async_vault_mock.address
    stranger = accounts[6]
    for call in (
        lambda: vault.mint_async(usdc.address, m, 0, 1, sender=stranger),
        lambda: vault.claim_mint(m, True, False, sender=stranger),
        lambda: vault.cancel_mint(m, sender=stranger),
        lambda: vault.redeem_async(m, weth.address, 1, 1, 1, sender=stranger),
        lambda: vault.claim_redeem(m, True, False, sender=stranger),
        lambda: vault.cancel_redeem(m, sender=stranger),
    ):
        with boa.reverts("unauthorized"):
            call()


# ---------------------------------------------------------------------------
# 6. Audit regressions (A2 / A5)
# ---------------------------------------------------------------------------


def test_start_loan_reverts_if_mint_addr_rotated_to_empty(
    p2p_usdc_weth_centrifuge,
    pending_loan,
    centrifuge_async_vault_mock,
    centrifuge_async_vault_mock_contract_def,
    usdc,
    weth,
    owner,
    borrower,
):
    """A2: rotating mint_addr to a fresh AsyncVault must not activate a zero-collateral loan.

    After the deposit settles on the original mint_addr, the owner rotates mint_addr to a fresh
    AsyncVault whose mint_status reads all-zeros. The `request_claimable > 0` guard reverts "mint not
    settled"; pre-fix the all-zeros status passed the gate and start_loan activated a 0-collateral loan.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)  # legit deposit settles
    assert centrifuge_async_vault_mock.deposit_claimable(vault_addr) == 1500 * 10**6

    fresh_mint = centrifuge_async_vault_mock_contract_def.deploy(usdc.address, weth.address)
    assert fresh_mint.deposit_claimable(vault_addr) == 0  # rotated addr reads all-zeros
    p2p_usdc_weth_centrifuge.set_mint_addr(fresh_mint.address, sender=owner)

    with boa.reverts("mint not settled"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_cancel_pending_borrower_only_when_window_zero(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """A5: max_pending_window == 0 DISABLES permissionless cancel (borrower-only), not open from block zero."""
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_max_pending_window(0, sender=owner)  # before create -> loan snapshots window 0
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.max_pending_window == 0

    boa.env.time_travel(seconds=10**9)  # far future: still borrower-only because window == 0
    stranger = accounts[6]
    assert stranger != borrower
    with boa.reverts("not borrower"):
        p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=stranger)


def test_cancel_pending_borrower_can_cancel_when_window_zero(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    now,
):
    """A5: with the permissionless path disabled (window 0) the borrower can still cancel."""
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_max_pending_window(0, sender=owner)
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.max_pending_window == 0

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False  # branch 1
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True
