"""Unit tests for the async (Centrifuge ERC-7540) leveraged-loan lifecycle.

Covers create_leveraged_loan (async branch), start_loan, cancel_pending_loan (liquidation-style),
cancel_redeem, and the Centrifuge async vault's own status/auth surface.

Each lifecycle stage has one flat fixture (`pending_loan`, `started_loan`, `redeeming_loan`) that runs
the whole path with concrete amounts: create -> fulfill_deposit -> start_loan -> redeem. Tests that set
custom fees/window (snapshotted onto the loan at creation) run the create inline instead.
`sign_centrifuge_offer` / `fund_centrifuge_leveraged` do the sign/mint/approve boilerplate;
`expected_pending_centrifuge_loan` builds the stored pending Loan for the hash assertion.

CentrifugeAsyncVaultMock stands in for the Centrifuge AsyncVault; its `fulfill_*` / `process_cancel_*`
hooks are the off-chain issuer, called inline where a test needs them.
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
)
from .conftest import expected_pending_centrifuge_loan

BPS = 10000
EMPTY_MINT_RESULT = ((ZERO_ADDRESS, 0, 0, 0), (0, 0, 0))
EMPTY_REDEEM_RESULT = ((ZERO_ADDRESS, 0, 0, 0), (0, 0, 0))


def _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, shares, assets):
    """Issuer settles the pending redeem of `shares` -> `assets` usdc, funding the mock to pay it out."""
    usdc.mint(centrifuge_async_vault_mock.address, assets)
    centrifuge_async_vault_mock.fulfill_redeem(vault_addr, shares, assets)


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

    start_loan runs via the protocol wallet (a non-borrower), also exercising the permissionless start.
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
    weth.mint(centrifuge_async_vault_mock.address, shares, sender=owner)  # mock pays shares from its own balance
    p2p_usdc_weth_centrifuge.start_loan(pending, EMPTY_MINT_RESULT, 0, sender=p2p_usdc_weth_centrifuge.protocol_wallet())
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
    p2p_usdc_weth_centrifuge.start_loan(pending, EMPTY_MINT_RESULT, 0, sender=p2p_usdc_weth_centrifuge.protocol_wallet())
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=pending.amount, collateral_amount=shares)

    p2p_usdc_weth_centrifuge.redeem(started, 0, sender=borrower)
    redeeming = started._replace(redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=0)
    return started, redeeming, vault_addr


# ---------------------------------------------------------------------------
# 1. create_leveraged_loan - async branch
# ---------------------------------------------------------------------------


def test_create_async_stores_pending_loan(p2p_usdc_weth_centrifuge, pending_loan):
    loan, _ = pending_loan
    assert loan.start_time == 0  # pending
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
    """The async create logs a full LoanCreated with start_time == 0 marking the loan pending.

    collateral_amount is the caller's expected amount until LoanStarted overwrites it with the actual
    minted shares. Created inline so the create tx is the p2p's last computation for get_last_event.
    """
    p2p = p2p_usdc_weth_centrifuge
    offer = centrifuge_signed_offer.offer
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    # Snapshot p2p fee getters before the create tx (reading them after would reset get_logs).
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
    assert event.start_time == 0  # start_time == 0 marks the loan pending
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
    """The async create logs LeveragedLoanCreated with pending=True, acquired_collateral=0, and
    mint_deadline == create_time + max_pending_window (fixture window is 50s).

    Created inline so the create tx is the p2p's last computation for get_last_event.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    fund_centrifuge_leveraged(principal, mint_spend)
    window = p2p.max_pending_window()
    assert window == 50  # fixture window (nonzero)

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
    assert event.mint_deadline == create_ts + window  # create_time + max_pending_window


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
    """The offer term must strictly outlast the pending window (so the permissionless-cancel valve opens
    before the loan can default). A `duration <= max_pending_window` offer must revert.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    p2p.set_max_pending_window(100, sender=owner)  # window == the offer's 100s duration -> boundary
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
    """A duration strictly below the window also reverts."""
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
    """Window 0 (valve disabled) passes the `duration > window` check for any duration.

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
    """With the pending window disabled (0), LeveragedLoanCreated logs mint_deadline == 0.

    The window must be set before create so it's snapshotted onto the loan; the create is the p2p's last
    computation so get_last_event sees these logs.
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
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)


def test_start_loan_reverts_if_mint_underfilled(p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower):
    """A partial fill leaves request_pending > 0, so the loan stays blocked from starting."""
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6 - 1, 10**18)  # under-fill by 1
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 1
    with boa.reverts("mint not settled"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)


def test_start_loan_activates_against_minted_shares(p2p_usdc_weth_centrifuge, started_loan):
    loan, _ = started_loan
    assert loan.start_time == loan.create_time  # started
    assert loan.collateral_amount == 10**18  # collateral == the actually-minted shares
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)


def test_start_loan_delivers_collateral_to_vault(started_loan, weth):
    _, vault_addr = started_loan
    assert weth.balanceOf(vault_addr) == 10**18  # the claimed shares landed in the loan vault


def test_start_loan_is_permissionless(p2p_usdc_weth_centrifuge, started_loan, borrower):
    """A keeper (not the borrower) can start a fully-fulfilled pending loan.

    The `started_loan` fixture starts via the protocol wallet (a non-borrower), so a successful start
    proves the permissionless path.
    """
    loan, _ = started_loan
    assert p2p_usdc_weth_centrifuge.protocol_wallet() != borrower
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)  # started by a non-borrower


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
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)


def test_start_loan_reverts_if_loan_invalid(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """Every single-field corruption fails `_is_loan_valid` before the mint gate.

    The deposit is fully fulfilled (so an unmutated loan would start), yet each mutated-hash loan reverts
    "invalid loan" at start_loan's first assert.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    for mutated in get_loan_mutations(loan):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth_centrifuge.start_loan(mutated, EMPTY_MINT_RESULT, 0, sender=borrower)


def test_start_loan_reverts_if_pending_loan_defaulted(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A pending loan past maturity can no longer be started (it would be born defaulted).

    The deposit is fully fulfilled (so the mint gate would otherwise pass), but time-travelling beyond
    the offer's 100s duration trips the earlier `not defaulted` gate.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    boa.env.time_travel(seconds=loan.maturity - loan.create_time + 1)  # 1s past maturity
    assert boa.eval("block.timestamp") > loan.maturity  # precondition: defaulted
    with boa.reverts("loan defaulted"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)


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
    """A fulfilled fill below the offer's min_collateral_amount cannot start (must be force-unwound).

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
        p2p.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)


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


# --- start_loan additional_collateral (borrower topup) ---


def test_start_loan_with_topup_backs_loan_with_summed_collateral(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """Borrower supplies a 0.3 weth topup alongside the 1.0 weth minted fill.

    The loan is backed by minted + additional_collateral: the stored Loan.collateral_amount and the
    LoanStarted event both report 1.3 weth, both the claimed shares and the topup land in the loan vault,
    and the topup is drained from the borrower's wallet.
    """
    loan, vault_addr = pending_loan
    A = 3 * 10**17  # 0.3 weth borrower topup

    # Fulfil the deposit fully (1.0 weth of shares) and fund the mock to pay them on claim.
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)

    # The borrower holds exactly the topup and approves the loan vault to pull it (like add_collateral).
    weth.mint(borrower, A, sender=owner)
    weth.approve(vault_addr, A, sender=borrower)

    vault_bal_before = weth.balanceOf(vault_addr)
    borrower_bal_before = weth.balanceOf(borrower)
    assert borrower_bal_before == A  # precondition: borrower funds only the topup (test is meaningful)
    assert vault_bal_before == 0  # precondition: no collateral in the vault before start

    p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, A, sender=borrower)

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanStarted")
    assert event.collateral_amount == 10**18 + A  # 1.3 weth

    started = loan._replace(start_time=boa.eval("block.timestamp"), initial_amount=loan.amount, collateral_amount=10**18 + A)
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(started)  # backed by minted + topup

    # Claimed shares (1.0 weth, paid to the vault on claim_mint) + the 0.3 weth topup both land in the vault.
    assert weth.balanceOf(vault_addr) == vault_bal_before + 10**18 + A
    assert weth.balanceOf(borrower) == borrower_bal_before - A == 0  # topup drained from the borrower


def test_start_loan_with_topup_logs_collateral_added_event(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, usdc, weth, oracle, owner, borrower, lender
):
    """A borrower topup at start emits LoanCollateralAdded.

    old_collateral_amount == minted (1.0 weth), new_collateral_amount == minted + topup (1.3 weth), and
    old/new LTVs match an independent computation over the start-block debt (amount + settlement interest).
    """
    loan, vault_addr = pending_loan
    minted = 10**18  # 1.0 weth fulfilled fill
    A = 3 * 10**17  # 0.3 weth borrower topup -> new collateral 1.3 weth

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, minted)
    weth.mint(centrifuge_async_vault_mock.address, minted, sender=owner)  # mock pays the claimed shares
    weth.mint(borrower, A, sender=owner)
    weth.approve(vault_addr, A, sender=borrower)

    p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, A, sender=borrower)

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanCollateralAdded")

    # Independent LTVs: debt = amount + settlement interest to the start block (ts == create_time -> 0).
    ts = boa.eval("block.timestamp")
    settlement_interest = loan.get_interest(ts)
    outstanding_debt = loan.amount + settlement_interest
    expected_old_ltv = calc_ltv(outstanding_debt, minted, usdc, weth, oracle)
    expected_new_ltv = calc_ltv(outstanding_debt, minted + A, usdc, weth, oracle)
    assert expected_new_ltv < expected_old_ltv  # sanity: more collateral, same debt -> healthier

    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_token == loan.collateral_token
    assert event.old_collateral_amount == minted  # collateral before the topup == the minted fill
    assert event.new_collateral_amount == minted + A  # 1.3 weth after the topup
    assert event.old_ltv == expected_old_ltv
    assert event.new_ltv == expected_new_ltv


def test_start_loan_with_zero_mint_topup_backs_loan_and_reports_zero_old_ltv(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, usdc, weth, oracle, owner, borrower, lender
):
    """Div-by-zero guard: a settled deposit that mints zero shares can still start via a borrower topup.

    The issuer fulfils the deposit (mint gate passes) at a price yielding 0 shares, so minted == 0. The
    offer's min_collateral_amount is 0, so the `minted + additional_collateral >= min` gate is satisfied
    by the 0.3 weth topup alone and the loan starts backed by the topup only. LoanCollateralAdded reports
    old_collateral_amount == 0 and old_ltv == 0 (no minted collateral to price, would divide by minted == 0).
    """
    loan, vault_addr = pending_loan
    minted = 0  # the fulfilled deposit yields NO shares
    A = 3 * 10**17  # 0.3 weth borrower topup -> the loan is backed by the topup alone

    assert loan.min_collateral_amount == 0  # precondition: any nonneg fill clears the gate

    # Fulfil the FULL mint_spend but at a share price of 0 -> deposit settles (claimable) yet mints nothing.
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, minted)  # shares == 0
    assert centrifuge_async_vault_mock.deposit_claimable(vault_addr) == 1500 * 10**6  # precondition: settled
    assert centrifuge_async_vault_mock.deposit_shares(vault_addr) == 0  # precondition: zero shares to claim

    # The borrower funds only the topup and approves the loan vault to pull it (like add_collateral).
    weth.mint(borrower, A, sender=owner)
    weth.approve(vault_addr, A, sender=borrower)
    assert weth.balanceOf(borrower) == A
    assert weth.balanceOf(vault_addr) == 0  # precondition: no collateral in the vault before start

    p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, A, sender=borrower)

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanCollateralAdded")

    # Independent new_ltv: debt = amount + settlement interest to the start block (ts == create_time -> 0).
    ts = boa.eval("block.timestamp")
    outstanding_debt = loan.amount + loan.get_interest(ts)
    expected_new_ltv = calc_ltv(outstanding_debt, A, usdc, weth, oracle)
    assert expected_new_ltv > 0  # sanity: the topup collateral prices to a real LTV

    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_token == loan.collateral_token
    assert event.old_collateral_amount == 0  # nothing minted
    assert event.new_collateral_amount == A  # backed by the topup alone
    assert event.old_ltv == 0  # undefined old LTV reported as 0, no div-by-zero on minted == 0
    assert event.new_ltv == expected_new_ltv

    started = loan._replace(start_time=ts, initial_amount=loan.amount, collateral_amount=A)
    assert started.collateral_amount == A
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(started)  # live, backed by the topup
    assert weth.balanceOf(vault_addr) == A  # only the topup landed in the vault (no minted shares)


def test_start_loan_topup_reverts_if_not_borrower(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A non-borrower supplying additional_collateral > 0 reverts "not borrower".

    additional_collateral is pulled from the borrower's wallet, so a keeper start must pass 0.
    """
    loan, vault_addr = pending_loan
    A = 3 * 10**17

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)

    keeper = p2p_usdc_weth_centrifuge.protocol_wallet()  # a non-borrower
    assert keeper != borrower  # precondition: caller is not the borrower
    with boa.reverts("not borrower"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, A, sender=keeper)


def test_start_loan_keeper_can_start_with_zero_topup(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A keeper starting with additional_collateral == 0 succeeds; the loan is backed by the minted 1.0
    weth only, no topup.
    """
    loan, vault_addr = pending_loan

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)

    keeper = p2p_usdc_weth_centrifuge.protocol_wallet()
    assert keeper != borrower  # precondition: permissionless (non-borrower) start
    p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=keeper)

    started = loan._replace(start_time=boa.eval("block.timestamp"), initial_amount=loan.amount, collateral_amount=10**18)
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(started)  # minted only, no topup


def test_start_loan_topup_can_satisfy_min_gate(
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
    """A borrower topup rescues a below-min fill: the min gate counts minted + additional_collateral.

    The offer demands 1.0 weth but the issuer fulfils only 0.9 weth of shares. A 0.2 weth topup lifts the
    total to 1.1 weth, clearing the min, so the borrower can start the below-min fill (the keeper path with
    0 topup still can't). The started loan is backed by 1.1 weth.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral, min_collateral = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    fulfilled_shares = 9 * 10**17  # 0.9 weth: below the 1.0 weth min
    A = 2 * 10**17  # 0.2 weth topup: minted + A = 1.1 weth >= min -> clears the gate
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

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, fulfilled_shares)  # fully fulfilled, low shares
    weth.mint(centrifuge_async_vault_mock.address, fulfilled_shares, sender=owner)  # mock pays the claimed shares
    weth.mint(borrower, A, sender=owner)  # borrower funds the topup
    weth.approve(vault_addr, A, sender=borrower)
    # precondition: the fill alone is below min, but fill + topup clears it -> the gate now counts the topup
    assert fulfilled_shares < min_collateral <= fulfilled_shares + A

    p2p.start_loan(loan, EMPTY_MINT_RESULT, A, sender=borrower)

    started = loan._replace(
        start_time=boa.eval("block.timestamp"), initial_amount=loan.amount, collateral_amount=fulfilled_shares + A
    )
    assert started.collateral_amount == fulfilled_shares + A  # 1.1 weth: minted + topup
    assert p2p.loans(loan.id) == compute_loan_hash(started)  # loan is live, backed by minted + topup
    assert weth.balanceOf(vault_addr) == fulfilled_shares + A  # both the claimed shares and the topup landed in the vault


def test_start_loan_reverts_if_minted_plus_topup_below_min(
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
    """An insufficient topup still reverts: minted + additional_collateral must reach the floor.

    The offer demands 1.0 weth, the issuer fulfils 0.9 weth, and the borrower tops up only 0.05 weth, so
    minted + topup (0.95 weth) is still below min and the start reverts "low collateral amount". The gate
    is on the sum, not satisfied by any positive topup.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral, min_collateral = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    fulfilled_shares = 9 * 10**17  # 0.9 weth: below the 1.0 weth min
    A = 5 * 10**16  # 0.05 weth topup: minted + A = 0.95 weth < min -> still short
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

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, fulfilled_shares)  # fully fulfilled, low shares
    weth.mint(centrifuge_async_vault_mock.address, fulfilled_shares, sender=owner)
    weth.mint(borrower, A, sender=owner)  # borrower can fund the (insufficient) topup
    weth.approve(vault_addr, A, sender=borrower)
    assert fulfilled_shares + A < min_collateral  # precondition: even WITH the topup the sum is below min

    with boa.reverts("low collateral amount"):
        p2p.start_loan(loan, EMPTY_MINT_RESULT, A, sender=borrower)


def test_start_loan_topup_reverts_if_borrower_lacks_shares(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """The borrower requests a topup but holds/approves no shares, so the vault's transferFrom of the
    remainder fails and the whole start reverts.

    WETH9Mock's transferFrom underflow-reverts (safe math) on the balance/allowance debit before the
    vault's "transferFrom failed" assert can observe a False return, so this is a bare ERC20 revert.
    """
    loan, vault_addr = pending_loan
    A = 3 * 10**17

    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)

    # Borrower requests a topup but never received or approved any weth for it.
    assert weth.balanceOf(borrower) == 0  # precondition: cannot cover the topup
    assert weth.allowance(borrower, vault_addr) == 0
    with boa.reverts():  # WETH9Mock underflow-reverts before the vault's assert
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, A, sender=borrower)


# ---------------------------------------------------------------------------
# 3. cancel_pending_loan  (two-phase deposit-cancel state machine, liquidation-style unwind)
# ---------------------------------------------------------------------------


def test_cancel_pending_requests_cancel_when_deposit_pending(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower
):
    """request_pending > 0: submit the cancellation, return False."""
    loan, vault_addr = pending_loan
    assert p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 0  # moved into the cancel pipeline
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True


def test_cancel_pending_returns_false_while_cancel_pending(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower
):
    """Cancel submitted but not yet processed: still return False, loan unchanged."""
    loan, vault_addr = pending_loan
    p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)  # request the cancel
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True

    assert p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)  # still pending


def test_cancel_pending_reverts_if_mint_claimable_and_startable(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A startable fulfilled deposit (fill >= min_collateral, not defaulted): must start, not cancel."""
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


def test_cancel_pending_reverts_if_loan_invalid(p2p_usdc_weth_centrifuge, pending_loan, borrower):
    """Every single-field corruption fails `_is_loan_valid` before any state/sender precondition."""
    loan, _ = pending_loan
    for mutated in get_loan_mutations(loan):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth_centrifuge.cancel_pending_loan(mutated, EMPTY_MINT_RESULT, sender=borrower)


def test_cancel_pending_is_permissionless_after_window(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower, accounts
):
    """After create_time + max_pending_window anyone may cancel a still-pending loan."""
    loan, vault_addr = pending_loan
    boa.env.time_travel(seconds=p2p_usdc_weth_centrifuge.max_pending_window() + 1)
    stranger = accounts[6]
    assert stranger != borrower
    assert (
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=stranger) is False
    )  # submits the cancel
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
    """Covered liquidation-style cancel: margin (500 USDC) >> interest, so the debt is fully covered.

    A keeper drives the permissionless cancel and earns the full liquidation fee; the lender recovers
    deployed capital + capped interest net of the protocol fee; the borrower keeps the surplus. Each leg
    is computed inline and asserted as a balance delta, plus the 4-leg conservation.
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
    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper)  # request the cancel
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
    # Covered cancel frees the full loan.amount (single-loan offer -> committed reaches exactly 0).
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
    """A shortfall cancel by a keeper while the borrower holds no funds must succeed.

    Margin is 100 wei, far below the accrued interest, so the debt can't be fully covered. The lender
    absorbs the shortfall as a liquidation loss, the borrower neither pays nor receives, and the keeper is
    still paid (no transferFrom from an unfunded borrower).
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

    # The borrower is completely unfunded: no balance and no allowance to top anything up.
    assert usdc.balanceOf(borrower) == 0
    assert usdc.allowance(borrower, p2p.address) == 0

    protocol_wallet = p2p.protocol_wallet()
    keeper_0, lender_0, protocol_0 = usdc.balanceOf(keeper), usdc.balanceOf(lender), usdc.balanceOf(protocol_wallet)

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

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
    """Interest is capped at maturity: a cancel ~10 years after a 100s loan charges only up-to-maturity
    interest.

    The maturity-capped interest is tiny (covered, borrower keeps a surplus); the uncapped
    block.timestamp-based interest would exceed the margin (shortfall, borrower gets 0). We assert the
    borrower received the surplus computed with the capped interest, proving no unbounded accrual.
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

    assert usdc.balanceOf(borrower) - borrower_0 == mint_spend - loan.amount - capped  # surplus uses capped interest
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

    p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)  # request the cancel
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
    """A pure cancel (never fulfilled) logs PendingLoanCancelled with all payment legs.

    reclaimed == mint_spend (1500 USDC), minted == 0, so every collateral leg is 0 and the estate is pure
    payment. Fees are 0 here -> caller/protocol legs 0, lender_payment == the covered debt (amount + capped
    interest), borrower_payment == the surplus.
    """
    loan, vault_addr = pending_loan
    mint_spend = 1500 * 10**6
    p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)
    p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)

    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    debt = (loan.amount - loan.origination_fee_amount) + interest  # origination fee 0 here
    lender_payment = debt  # fees 0 -> lender gets the whole debt (covered)
    borrower_payment = mint_spend - lender_payment

    event = get_last_event(p2p_usdc_weth_centrifuge, "PendingLoanCancelled")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == 0  # nothing was ever fulfilled
    assert event.payment_reclaimed == mint_spend
    assert event.lender_payment == lender_payment
    assert event.lender_collateral == 0
    assert event.liquidation_fee_payment == 0  # full_liquidation_fee 0
    assert event.liquidation_fee_collateral == 0
    assert event.protocol_fee_payment == 0  # settlement fee 0
    assert event.protocol_fee_collateral == 0
    assert event.borrower_payment == borrower_payment
    assert event.borrower_collateral == 0
    assert event.caller == borrower


# ---------------------------------------------------------------------------
# 3b. cancel_pending_loan force-unwind (fulfilled-but-not-startable deposit, share-denominated)
# ---------------------------------------------------------------------------
#
# When the deposit is fully fulfilled (request_claimable > 0) but the loan is not startable — a fill
# below min_collateral_amount, or a fill past maturity (defaulted) — the ERC-7540 request can't be
# cancelled, so cancel_pending_loan claims the shares and splits them oracle-valued, liquidation-style.
# All legs are paid in collateral shares (weth), unlike the payment-token cancel_claimable branch above.
#
# Oracle (conftest `oracle`): rate_num = 387780390000, rate_den = 10**8. usdc = 6 decimals, weth = 18
# decimals. minted_value (USDC) = minted * rate_num * 10**6 // (rate_den * 10**18); value -> shares is
# the exact inverse.

RATE_NUM = 387780390000
RATE_DEN = 10**8
PAYMENT_DEC = 10**6
COLLATERAL_DEC = 10**18


def _shares_to_value(shares):
    return shares * RATE_NUM * PAYMENT_DEC // (RATE_DEN * COLLATERAL_DEC)


def _value_to_shares(value):
    return value * RATE_DEN * COLLATERAL_DEC // (RATE_NUM * PAYMENT_DEC)


def _carve(target_value, pay, col):
    """Draw `target_value` payment-first, then collateral (mirrors the contract's carve).

    Returns (payment_taken, shares_taken, pay_left, col_left). Shares are rounded down (value->shares) and
    clamped to the available collateral, so a recipient never over-draws the collateral pot.
    """
    payment_taken = min(pay, target_value)
    remaining_value = target_value - payment_taken
    if remaining_value == 0 or col == 0:
        return payment_taken, 0, pay - payment_taken, col
    col_value = _shares_to_value(col)
    take_value = min(remaining_value, col_value)
    shares = min(_value_to_shares(take_value), col)
    return payment_taken, shares, pay - payment_taken, col - shares


def _distribute(reclaimed, minted, debt, interest, full_liquidation_fee, protocol_settlement_fee):
    """The combined-estate waterfall over {reclaimed payment, minted shares} (mirrors the contract).

    Returns a dict of (payment_leg, collateral_leg) tuples for caller/protocol/lender/borrower plus the
    scalar `lender_value` (used for the committed-liquidity fold-in). Priority: caller fee > protocol fee
    > lender recovery > borrower (dust).
    """
    col_value = _shares_to_value(minted)
    estate_value = reclaimed + col_value
    fee_value = min(debt * full_liquidation_fee // BPS, estate_value)
    value_after_fee = estate_value - fee_value
    protocol_value = min(protocol_settlement_fee * interest // BPS, value_after_fee)
    lender_value = (debt - protocol_value) if value_after_fee >= debt else (value_after_fee - protocol_value)

    pay, col = reclaimed, minted
    caller_pay, caller_col, pay, col = _carve(fee_value, pay, col)
    protocol_pay, protocol_col, pay, col = _carve(protocol_value, pay, col)
    lender_pay, lender_col, pay, col = _carve(lender_value, pay, col)
    borrower_pay, borrower_col = pay, col  # borrower absorbs the remainder (and rounding dust)
    return {
        "caller": (caller_pay, caller_col),
        "protocol": (protocol_pay, protocol_col),
        "lender": (lender_pay, lender_col),
        "borrower": (borrower_pay, borrower_col),
        "lender_value": lender_value,
    }


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
    """Covered force-unwind: a fulfilled-but-defaulted deposit (full 1 weth) is claimed and split in shares.

    minted_value (~3877 USDC) >> debt, so the waterfall pays keeper the liquidation fee, protocol the
    settlement fee on interest, the lender its deployed capital + interest net protocol fee, and the
    borrower the surplus shares (incl. dust). A keeper (post-window) drives it; all legs asserted as share
    balances plus the 4-leg conservation and the PendingLoanCancelled event. The estate is pure collateral
    (reclaimed == 0), so every payment leg is 0 and each share leg lands in the *_collateral field.
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
    # Exercises the defaulted force-unwind trigger: a full fill >= min IS startable, so it can only unwind
    # once past maturity. Travel past maturity (t=101), which also clears the window (50s) for the keeper.
    boa.env.time_travel(seconds=loan.maturity - loan.create_time + 1)
    assert boa.eval("block.timestamp") > loan.maturity  # defaulted -> not startable
    assert boa.eval("block.timestamp") > loan.create_time + loan.max_pending_window  # keeper allowed
    assert minted >= loan.min_collateral_amount  # the other unwind trigger (defaulted, not low-fill)

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

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p, "PendingLoanCancelled")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == minted
    assert event.payment_reclaimed == 0  # pure-collateral estate: nothing was reclaimed
    assert event.lender_collateral == lender_shares
    assert event.liquidation_fee_collateral == liquidation_fee_shares
    assert event.protocol_fee_collateral == protocol_fee_shares
    assert event.borrower_collateral == borrower_shares
    assert event.lender_payment == 0  # every payment leg is 0 (estate is pure collateral)
    assert event.liquidation_fee_payment == 0
    assert event.protocol_fee_payment == 0
    assert event.borrower_payment == 0
    assert event.caller == keeper

    assert weth.balanceOf(keeper) - keeper_0 == liquidation_fee_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert weth.balanceOf(protocol_wallet) - protocol_0 == protocol_fee_shares
    assert weth.balanceOf(borrower) - borrower_0 == borrower_shares
    assert liquidation_fee_shares + lender_shares + protocol_fee_shares + borrower_shares == minted  # conservation
    assert p2p.loans(loan.id) == ZERO_BYTES32
    # Covered force-unwind frees the full loan.amount (single-loan offer -> committed reaches 0).
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

    With window (50s) < duration (100s), a keeper can act past the window (t=51) while the loan is still
    pending (t < maturity 100), so the unwind fires purely on the below-min fill (minted 1 weth < min 2
    weth), not on default. The fill is worth ~3877 USDC so the split is covered: keeper takes the
    liquidation fee, protocol the settlement fee on the (uncapped) interest, the lender its deployed
    capital + interest, the borrower the surplus shares. All legs in weth; conservation +
    PendingLoanCancelled (pure-collateral: every payment leg 0, each share leg in *_collateral) asserted.
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

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p, "PendingLoanCancelled")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == minted
    assert event.payment_reclaimed == 0  # pure-collateral estate
    assert event.lender_collateral == lender_shares
    assert event.liquidation_fee_collateral == liquidation_fee_shares
    assert event.protocol_fee_collateral == protocol_fee_shares
    assert event.borrower_collateral == borrower_shares
    assert event.lender_payment == 0
    assert event.liquidation_fee_payment == 0
    assert event.protocol_fee_payment == 0
    assert event.borrower_payment == 0
    assert event.caller == keeper

    assert weth.balanceOf(keeper) - keeper_0 == liquidation_fee_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert weth.balanceOf(protocol_wallet) - protocol_0 == protocol_fee_shares
    assert weth.balanceOf(borrower) - borrower_0 == borrower_shares
    assert liquidation_fee_shares + lender_shares + protocol_fee_shares + borrower_shares == minted  # conservation
    assert p2p.loans(loan.id) == ZERO_BYTES32
    # Covered force-unwind frees the full loan.amount (single-loan offer -> committed reaches 0).
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
    """Shortfall force-unwind: a below-min fill so tiny its oracle value can't cover the debt.

    A 1000-wei fill (< min 10**18) is worth far less than the ~1000 USDC debt, so after the keeper fee the
    lender takes what its (shortfall-capped) recovery converts to in shares and the borrower absorbs only
    the rounding dust. Estate is pure collateral (reclaimed == 0); legs computed via `_distribute`.
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
    assert value_after_fee < debt  # precondition: SHORTFALL
    legs = _distribute(0, minted, debt, interest, 500, 1000)
    liquidation_fee_shares = legs["caller"][1]
    protocol_fee_shares = legs["protocol"][1]
    lender_shares = legs["lender"][1]
    borrower_shares = legs["borrower"][1]

    keeper_0, lender_0, borrower_0 = (weth.balanceOf(a) for a in (keeper, lender, borrower))

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    assert weth.balanceOf(keeper) - keeper_0 == liquidation_fee_shares
    assert weth.balanceOf(lender) - lender_0 == lender_shares
    assert weth.balanceOf(borrower) - borrower_0 == borrower_shares
    assert liquidation_fee_shares + protocol_fee_shares + lender_shares + borrower_shares == minted  # conservation
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
    """Borrower self-cancels a below-min fill before the window: the borrower-only auth path works.

    caller == borrower, so the borrower is paid the liquidation fee and (here, covered) the surplus —
    net-neutral vs a keeper unwind. Uses a full-value fill (~3877 USDC) still below-min (not startable) but
    covered.
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


def test_cancel_pending_partial_fill_requests_cancel_of_remainder(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A partial fill (request_claimable > 0 AND request_pending > 0) resolves the pending leg first.

    The contract submits a cancelDepositRequest of the remaining 1 wei and returns False, leaving the loan
    intact for a later terminal call. It does not claim the already-fulfilled slice or delete the loan on
    this pass.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6 - 1, 10**18)  # fulfil all but 1 wei of assets
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    assert centrifuge_async_vault_mock.deposit_claimable(vault_addr) == 1500 * 10**6 - 1  # fulfilled slice
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 1  # 1 wei still pending

    assert p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False

    # The remaining pending was moved into the cancel pipeline; the fulfilled slice is left untouched.
    assert centrifuge_async_vault_mock.deposit_pending(vault_addr) == 0
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True
    assert centrifuge_async_vault_mock.deposit_claimable(vault_addr) == 1500 * 10**6 - 1  # still claimable, not yet claimed
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)  # loan NOT deleted


# ---------------------------------------------------------------------------
# 3c. cancel_pending_loan MIXED terminal state (partial-fulfil + cancel-of-remainder)
# ---------------------------------------------------------------------------
#
# A Centrifuge deposit can be partially fulfilled AND partially cancelled at the same time (mixed state:
# request_claimable > 0 AND cancel_claimable > 0). cancel_pending_loan claims both legs and distributes
# the combined estate in one waterfall.


def _mock_mint_status(mock, vault_addr):
    """The status the vault's mint_status() would report, read from the mock's getters: pending/claimable
    request counters plus the cancel pending flag (as 0/1) and cancel-claimable payment.
    """
    return {
        "request_pending": mock.deposit_pending(vault_addr),
        "request_claimable": mock.deposit_claimable(vault_addr),
        "cancel_pending": 1 if mock.deposit_cancel_pending(vault_addr) else 0,
        "cancel_claimable": mock.deposit_cancel_claimable(vault_addr),
    }


def _mock_redeem_status(mock, vault_addr):
    """The status the vault's redeem_status() would report, read from the mock's redeem-side getters."""
    return {
        "request_pending": mock.redeem_pending(vault_addr),
        "request_claimable": mock.redeem_claimable(vault_addr),
        "cancel_pending": 1 if mock.redeem_cancel_pending(vault_addr) else 0,
        "cancel_claimable": mock.redeem_cancel_claimable(vault_addr),
    }


def _drive_to_mixed_terminal(mock, weth, usdc, owner, vault_addr, mint_spend, partial_assets, partial_shares):
    """Off-chain issuer hooks that leave the deposit in the mixed terminal state.

    Partially fulfil the deposit (partial_assets -> partial_shares), then cancel the still-pending
    remainder and process that cancellation. Result: request_claimable == partial_assets (with
    partial_shares to claim) AND cancel_claimable == mint_spend - partial_assets, both pendings zero. Funds
    the mock with `partial_shares` weth for the share claim; the usdc for the cancel-claim is already in
    the mock from requestDeposit.
    """
    mock.fulfill_deposit(vault_addr, partial_assets, partial_shares)  # fulfil a slice
    mock.cancelDepositRequest(0, vault_addr)  # cancel the pending remainder (issuer hook)
    mock.process_cancel_deposit(vault_addr)  # settle that cancellation -> cancel_claimable
    weth.mint(mock.address, partial_shares, sender=owner)  # mock pays the claimed shares from its own balance


def test_cancel_pending_mixed_terminal_distributes_both_legs(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    usdc,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """A mixed terminal deposit is cancelled and both legs distributed.

    The deposit is partially fulfilled (0.3 weth of shares claimable) AND the pending remainder is
    cancelled and reclaimed (a 100 USDC payment slice). Concretes are chosen so the estate mixes both
    tokens: the reclaimed 100 USDC covers the keeper fee, the tiny protocol fee, and a slice of the lender
    leg, then runs out — so the lender leg spans payment AND collateral, and the borrower dust lands purely
    in shares. Split caller-fee > protocol-fee > lender > borrower, payment-first per leg. Asserts every
    PendingLoanCancelled field and the weth/usdc balances of keeper/protocol/lender/borrower.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    origination_fee_bps = 100  # 1% -> lender never deploys the origination fee
    # Fulfil 1400 USDC of assets at a price yielding 0.3 weth (~1163 USDC of collateral); cancel and
    # reclaim the remaining 100 USDC. Estate = 100 USDC payment + 0.3 weth collateral (covered vs debt).
    partial_assets = 1400 * 10**6  # -> reclaimed = 100 USDC (the cancelled remainder)
    partial_shares = 3 * 10**17  # 0.3 weth of fulfilled shares (~1163 USDC of collateral)
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

    _drive_to_mixed_terminal(
        centrifuge_async_vault_mock, weth, usdc, owner, vault_addr, mint_spend, partial_assets, partial_shares
    )
    keeper = accounts[6]
    assert keeper not in {borrower, lender, owner}
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # past window -> permissionless keeper

    # PRECONDITION: mixed terminal state (both claimables > 0, both pendings 0).
    status = _mock_mint_status(centrifuge_async_vault_mock, vault_addr)
    assert status["request_claimable"] > 0
    assert status["cancel_claimable"] > 0
    assert status["request_pending"] == 0
    assert status["cancel_pending"] == 0

    reclaimed = mint_spend - partial_assets  # 100 USDC reclaimed by the cancellation
    minted = partial_shares  # 0.3 weth fulfilled shares
    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    debt = (loan.amount - loan.origination_fee_amount) + interest
    col_value = _shares_to_value(minted)
    estate_value = reclaimed + col_value
    fee_value = min(debt * 500 // BPS, estate_value)
    assert estate_value >= debt + fee_value  # precondition: covered overall
    assert reclaimed > fee_value  # keeper fee is fully payable in payment token
    legs = _distribute(reclaimed, minted, debt, interest, 500, 1000)
    caller_pay, caller_col = legs["caller"]
    protocol_pay, protocol_col = legs["protocol"]
    lender_pay, lender_col = legs["lender"]
    borrower_pay, borrower_col = legs["borrower"]
    # token-mix: fee leg is pure payment, the reclaimed payment runs out mid-lender-leg (lender paid in
    # both tokens), borrower dust is collateral only.
    assert caller_col == 0  # keeper fee has no collateral leg
    assert caller_pay == fee_value  # keeper fee fully in payment
    assert lender_pay > 0  # lender leg spans both tokens...
    assert lender_col > 0  # ...part payment, part collateral
    assert borrower_pay == 0  # borrower dust is collateral only
    assert borrower_col > 0

    protocol_wallet = p2p.protocol_wallet()
    kp0, lp0, bp0, pp0 = (usdc.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))
    kc0, lc0, bc0, pc0 = (weth.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))
    assert usdc.balanceOf(centrifuge_async_vault_mock.address) == mint_spend  # all usdc still in the mock

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p, "PendingLoanCancelled")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == minted
    assert event.payment_reclaimed == reclaimed
    assert event.liquidation_fee_payment == caller_pay
    assert event.liquidation_fee_collateral == caller_col
    assert event.protocol_fee_payment == protocol_pay
    assert event.protocol_fee_collateral == protocol_col
    assert event.lender_payment == lender_pay
    assert event.lender_collateral == lender_col
    assert event.borrower_payment == borrower_pay
    assert event.borrower_collateral == borrower_col
    assert event.caller == keeper

    # Balances: payment (usdc) legs.
    assert usdc.balanceOf(keeper) - kp0 == caller_pay
    assert usdc.balanceOf(protocol_wallet) - pp0 == protocol_pay
    assert usdc.balanceOf(lender) - lp0 == lender_pay
    assert usdc.balanceOf(borrower) - bp0 == borrower_pay
    # Balances: collateral (weth) legs.
    assert weth.balanceOf(keeper) - kc0 == caller_col
    assert weth.balanceOf(protocol_wallet) - pc0 == protocol_col
    assert weth.balanceOf(lender) - lc0 == lender_col
    assert weth.balanceOf(borrower) - bc0 == borrower_col
    # Conservation across both tokens.
    assert caller_pay + protocol_pay + lender_pay + borrower_pay == reclaimed
    assert caller_col + protocol_col + lender_col + borrower_col == minted
    assert p2p.loans(loan.id) == ZERO_BYTES32


def test_cancel_pending_mixed_terminal_ignores_payment_donation_into_vault(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    usdc,
    kyc_borrower,
    kyc_lender,
    borrower,
    lender,
    owner,
    accounts,
    now,
):
    """A USDC donation sitting in the vault is NOT swept into the cancel waterfall.

    Identical mixed-terminal setup to test_cancel_pending_mixed_terminal_distributes_both_legs, but a 500
    USDC donation is transferred directly into the per-loan vault before cancel. reclaimed comes from
    claim_mint's cancel-leg return (not balanceOf(vault) after the claim), so the donation is ignored: the
    waterfall distributes the same legs as the no-donation base case and the donation stays in the vault.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    origination_fee_bps = 100  # 1% -> lender never deploys the origination fee
    partial_assets = 1400 * 10**6  # -> reclaimed = 100 USDC (the cancelled remainder)
    partial_shares = 3 * 10**17  # 0.3 weth of fulfilled shares (~1163 USDC of collateral)
    signed_offer = sign_centrifuge_offer(principal, origination_fee_bps=origination_fee_bps)
    fund_centrifuge_leveraged(principal, mint_spend, origination_fee_bps=origination_fee_bps)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS  # nonzero fee snapshot

    _drive_to_mixed_terminal(
        centrifuge_async_vault_mock, weth, usdc, owner, vault_addr, mint_spend, partial_assets, partial_shares
    )

    # DONATION: 500 USDC transferred directly into the per-loan vault before cancel. A fresh centrifuge
    # vault holds no payment token, so the vault should hold exactly the donation right after.
    donation = 500 * 10**6
    usdc.mint(vault_addr, donation)
    vault_usdc_before = usdc.balanceOf(vault_addr)
    assert vault_usdc_before == donation  # nothing else in the vault yet (reclaimed lives in the mock)

    keeper = accounts[6]
    assert keeper not in {borrower, lender, owner}
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # past window -> permissionless keeper

    # PRECONDITION: mixed terminal state (both claimables > 0, both pendings 0).
    status = _mock_mint_status(centrifuge_async_vault_mock, vault_addr)
    assert status["request_claimable"] > 0
    assert status["cancel_claimable"] > 0
    assert status["request_pending"] == 0
    assert status["cancel_pending"] == 0

    # reclaimed is the genuinely-cancelled remainder only, NOT reclaimed + donation.
    reclaimed = mint_spend - partial_assets  # 100 USDC reclaimed by the cancellation
    minted = partial_shares  # 0.3 weth fulfilled shares
    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    debt = (loan.amount - loan.origination_fee_amount) + interest
    col_value = _shares_to_value(minted)
    estate_value = reclaimed + col_value
    fee_value = min(debt * 500 // BPS, estate_value)
    assert estate_value >= debt + fee_value  # precondition: COVERED overall
    assert reclaimed > fee_value  # keeper fee is fully payable in payment token
    legs = _distribute(reclaimed, minted, debt, interest, 500, 1000)
    caller_pay, caller_col = legs["caller"]
    protocol_pay, protocol_col = legs["protocol"]
    lender_pay, lender_col = legs["lender"]
    borrower_pay, borrower_col = legs["borrower"]
    # same token-mix shape as the no-donation base case.
    assert caller_col == 0
    assert caller_pay == fee_value
    assert lender_pay > 0
    assert lender_col > 0
    assert borrower_pay == 0
    assert borrower_col > 0

    protocol_wallet = p2p.protocol_wallet()
    kp0, lp0, bp0, pp0 = (usdc.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))
    kc0, lc0, bc0, pc0 = (weth.balanceOf(a) for a in (keeper, lender, borrower, protocol_wallet))
    assert usdc.balanceOf(centrifuge_async_vault_mock.address) == mint_spend  # reclaimed still in the mock

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True

    # Read the event before any p2p view call (a p2p getter resets boa's last-computation log buffer).
    event = get_last_event(p2p, "PendingLoanCancelled")
    assert event.id == loan.id
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_claimed == minted
    assert event.payment_reclaimed == reclaimed  # not reclaimed + donation
    assert event.liquidation_fee_payment == caller_pay
    assert event.liquidation_fee_collateral == caller_col
    assert event.protocol_fee_payment == protocol_pay
    assert event.protocol_fee_collateral == protocol_col
    assert event.lender_payment == lender_pay
    assert event.lender_collateral == lender_col
    assert event.borrower_payment == borrower_pay
    assert event.borrower_collateral == borrower_col
    assert event.caller == keeper

    # Balances unchanged vs the no-donation base case: payment (usdc) legs.
    assert usdc.balanceOf(keeper) - kp0 == caller_pay
    assert usdc.balanceOf(protocol_wallet) - pp0 == protocol_pay
    assert usdc.balanceOf(lender) - lp0 == lender_pay
    assert usdc.balanceOf(borrower) - bp0 == borrower_pay  # borrower does NOT receive the donation
    # Balances: collateral (weth) legs.
    assert weth.balanceOf(keeper) - kc0 == caller_col
    assert weth.balanceOf(protocol_wallet) - pc0 == protocol_col
    assert weth.balanceOf(lender) - lc0 == lender_col
    assert weth.balanceOf(borrower) - bc0 == borrower_col
    # Conservation across both tokens (over reclaimed, not reclaimed + donation).
    assert caller_pay + protocol_pay + lender_pay + borrower_pay == reclaimed
    assert caller_col + protocol_col + lender_col + borrower_col == minted

    # The donation was never swept in: it remains in the vault untouched.
    assert usdc.balanceOf(vault_addr) == donation
    assert p2p.loans(loan.id) == ZERO_BYTES32


def test_cancel_pending_mixed_but_cancel_still_settling_returns_false(
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
    """request_claimable > 0 AND cancel_pending > 0 -> return False, loan untouched.

    Partial fulfil then cancel the remainder but do not process it, so the cancellation is still in flight
    (cancel_pending). The terminal settlement must not fire while a cancel is settling: the call returns
    False and leaves the loan intact. Once the issuer processes the cancel, a second call reaches the mixed
    terminal state and returns True.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    partial_assets, partial_shares = 30 * 10**6, 10**17
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    loan = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )

    # Partial fulfil + cancel the remainder, but leave it unprocessed (cancel_pending stays True).
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, partial_assets, partial_shares)
    centrifuge_async_vault_mock.cancelDepositRequest(0, vault_addr)
    weth.mint(centrifuge_async_vault_mock.address, partial_shares, sender=owner)
    keeper = accounts[6]
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)

    status = _mock_mint_status(centrifuge_async_vault_mock, vault_addr)
    assert status["request_claimable"] > 0  # a fulfilled slice is claimable
    assert status["cancel_pending"] == 1  # but a cancellation is still settling
    assert status["cancel_claimable"] == 0

    # cancel_pending > 0 short-circuits first: return False, loan not deleted.
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is False
    assert p2p.loans(loan.id) == compute_loan_hash(loan)  # untouched

    # Issuer settles the cancellation -> mixed terminal state; the next call completes the unwind.
    centrifuge_async_vault_mock.process_cancel_deposit(vault_addr)
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True
    assert p2p.loans(loan.id) == ZERO_BYTES32


def test_cancel_pending_startable_clean_fill_still_reverts_and_start_succeeds(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """A cleanly-fulfilled startable deposit (no cancel) still can't be cancelled.

    request_claimable > 0, cancel_claimable == 0, minted >= min_collateral, not defaulted:
    cancel_pending_loan must revert "claimable mint, start instead" (the lender's interest is protected),
    and start_loan must succeed on the very same state.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)  # cleanly fulfilled, no cancel
    weth.mint(centrifuge_async_vault_mock.address, 10**18, sender=owner)
    assert loan.min_collateral_amount == 0  # any positive fill is >= min -> startable
    assert centrifuge_async_vault_mock.deposit_cancel_claimable(vault_addr) == 0  # no cancellation in play

    with boa.reverts("claimable mint, start instead"):
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)

    # The same state must be startable: start_loan succeeds and backs the loan with the minted shares.
    p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)
    started = loan._replace(start_time=boa.eval("block.timestamp"), initial_amount=loan.amount, collateral_amount=10**18)
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(started)


# ---------------------------------------------------------------------------
# 3d. cancel_pending_loan committed-liquidity fold-in (aggregated offer)
# ---------------------------------------------------------------------------


def _aggregated_async_offer(usdc, weth, oracle, lender, borrower, now, available_liquidity):
    """A reusable async offer (borrower == empty, principal 0) with a wide available_liquidity.

    borrower == empty(address) so the offer is not revoked after the first loan; principal 0 lets each
    reuse size to the remaining capacity. Two loans can then be opened against it, committing 2*P.
    """
    return Offer(
        principal=0,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=0,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=available_liquidity,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 10**6,
        lender=lender,
        borrower=ZERO_ADDRESS,
        tracing_id=ZERO_BYTES32,
    )


def test_cancel_pending_mixed_covered_frees_full_principal_on_aggregated_offer(
    p2p_usdc_weth_centrifuge,
    centrifuge_async_vault_mock,
    kyc_for,
    kyc_validator_contract,
    usdc,
    weth,
    oracle,
    borrower,
    lender,
    lender_key,
    owner,
    accounts,
    now,
):
    """Committed-liquidity fold-in, covered: the covered branch frees the full loan.amount == P.

    Aggregated offer (available_liquidity = 2*P) with two P loans open (committed == 2*P). One loan is
    driven to the mixed terminal state and cancelled; its estate (reclaimed payment + fulfilled shares)
    covers the debt, so the covered branch frees the full loan.amount and committed drops by exactly P
    (2P -> P).
    """
    p2p = p2p_usdc_weth_centrifuge
    P = 1000 * 10**6
    mint_spend = 1500 * 10**6  # per-loan spend (margin 500 USDC)
    collateral = 10**18
    offer = _aggregated_async_offer(usdc, weth, oracle, lender, borrower, now, available_liquidity=2 * P)
    signed_offer = sign_offer(offer, lender_key, p2p.address)

    # Fund + open TWO P loans from the aggregated offer (distinct create_time via a 1s time-travel).
    usdc.mint(lender, 2 * mint_spend)
    usdc.approve(p2p.address, 2 * mint_spend, sender=lender)
    usdc.mint(borrower, 2 * (mint_spend - P))
    usdc.approve(p2p.address, 2 * (mint_spend - P), sender=borrower)
    vault_addr = p2p.wallet_to_vault(borrower)

    kyc_b = kyc_for(borrower, kyc_validator_contract.address, now + 10**6)
    kyc_l = kyc_for(lender, kyc_validator_contract.address, now + 10**6)
    loan_id_a = p2p.create_leveraged_loan(signed_offer, P, collateral, kyc_b, kyc_l, mint_spend, collateral, sender=borrower)
    loan_a = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id_a, borrower, lender, now, principal=P, collateral=collateral, offer_principal=0
    )
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == P  # one loan committed

    boa.env.time_travel(seconds=1)  # distinct create_time for the second loan
    now2 = boa.eval("block.timestamp")
    kyc_b2 = kyc_for(borrower, kyc_validator_contract.address, now2 + 10**6)  # re-sign after time-travel
    kyc_l2 = kyc_for(lender, kyc_validator_contract.address, now2 + 10**6)
    p2p.create_leveraged_loan(signed_offer, P, collateral, kyc_b2, kyc_l2, mint_spend, collateral, sender=borrower)
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == 2 * P  # both committed

    # Drive loan A to the mixed terminal state (covered: reclaimed 1470 + 0.1 weth of shares > debt).
    partial_assets, partial_shares = 30 * 10**6, 10**17
    _drive_to_mixed_terminal(
        centrifuge_async_vault_mock, weth, usdc, owner, vault_addr, mint_spend, partial_assets, partial_shares
    )
    keeper = accounts[6]
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)

    reclaimed = mint_spend - partial_assets
    interest = loan_a.get_capped_interest(boa.eval("block.timestamp"))
    debt = (loan_a.amount - loan_a.origination_fee_amount) + interest
    legs = _distribute(reclaimed, partial_shares, debt, interest, 0, 0)  # fees 0 in this fixture
    assert legs["lender_value"] >= loan_a.amount  # COVERED: full principal recovered

    assert p2p.cancel_pending_loan(loan_a, EMPTY_MINT_RESULT, sender=keeper) is True
    # Covered -> frees the full loan.amount == P: 2P -> P (the other loan's commitment remains).
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == P


def test_cancel_pending_mixed_shortfall_frees_only_recovered_principal_on_aggregated_offer(
    p2p_usdc_weth_centrifuge,
    centrifuge_async_vault_mock,
    kyc_for,
    kyc_validator_contract,
    usdc,
    weth,
    oracle,
    borrower,
    lender,
    lender_key,
    owner,
    accounts,
    now,
):
    """Committed-liquidity fold-in, shortfall: freeing == lender_value (< P), the loss stays committed.

    Aggregated offer, two P loans (committed 2*P). Loan A's estate is cratered (tiny reclaimed + tiny
    fulfilled shares) so estate_value < principal: lender_value < P. Committed drops by only the recovered
    lender_value, leaving committed_after == 2P - lender_value (> P) — the unrecovered principal is a
    realized loss that stays committed.
    """
    p2p = p2p_usdc_weth_centrifuge
    P = 1000 * 10**6
    mint_spend = P + 100  # tiny margin
    collateral = 10**18
    offer = _aggregated_async_offer(usdc, weth, oracle, lender, borrower, now, available_liquidity=2 * P)
    signed_offer = sign_offer(offer, lender_key, p2p.address)

    usdc.mint(lender, 2 * mint_spend)
    usdc.approve(p2p.address, 2 * mint_spend, sender=lender)
    usdc.mint(borrower, 2 * (mint_spend - P))
    usdc.approve(p2p.address, 2 * (mint_spend - P), sender=borrower)
    vault_addr = p2p.wallet_to_vault(borrower)

    kyc_b = kyc_for(borrower, kyc_validator_contract.address, now + 10**6)
    kyc_l = kyc_for(lender, kyc_validator_contract.address, now + 10**6)
    loan_id_a = p2p.create_leveraged_loan(signed_offer, P, collateral, kyc_b, kyc_l, mint_spend, collateral, sender=borrower)
    loan_a = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id_a, borrower, lender, now, principal=P, collateral=collateral, offer_principal=0
    )

    boa.env.time_travel(seconds=1)
    now2 = boa.eval("block.timestamp")
    kyc_b2 = kyc_for(borrower, kyc_validator_contract.address, now2 + 10**6)
    kyc_l2 = kyc_for(lender, kyc_validator_contract.address, now2 + 10**6)
    p2p.create_leveraged_loan(signed_offer, P, collateral, kyc_b2, kyc_l2, mint_spend, collateral, sender=borrower)
    assert p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)) == 2 * P

    # Crater loan A's estate: fulfil ~all assets at ~0 shares (so shares are worthless), then cancel a
    # tiny 40-wei remainder. reclaimed == 40 wei and the fulfilled shares price to ~0 USDC, so the whole
    # estate is far below the ~1000 USDC principal -> genuine shortfall.
    partial_assets, partial_shares = mint_spend - 40, 1000  # fulfil all but 40 wei; 1000 wei shares ~= 0 USDC
    _drive_to_mixed_terminal(
        centrifuge_async_vault_mock, weth, usdc, owner, vault_addr, mint_spend, partial_assets, partial_shares
    )
    keeper = accounts[6]
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)

    reclaimed = mint_spend - partial_assets
    interest = loan_a.get_capped_interest(boa.eval("block.timestamp"))
    debt = (loan_a.amount - loan_a.origination_fee_amount) + interest
    legs = _distribute(reclaimed, partial_shares, debt, interest, 0, 0)
    lender_value = legs["lender_value"]
    assert lender_value < P  # precondition: genuine shortfall (estate can't cover principal)

    assert p2p.cancel_pending_loan(loan_a, EMPTY_MINT_RESULT, sender=keeper) is True
    committed_after = p2p.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32))
    assert committed_after == 2 * P - lender_value  # freed only the recovered principal
    assert committed_after > P  # the unrecovered loss stays committed (NOT freed down to P)


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
    """request_pending > 0: submit the redeem cancellation, return False."""
    _, redeeming, vault_addr = redeeming_loan
    assert p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower) is False
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) == 0
    assert centrifuge_async_vault_mock.redeem_cancel_pending(vault_addr) is True


def test_cancel_redeem_returns_false_while_cancel_pending(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower
):
    """Cancel submitted but not processed: still return False, loan unchanged."""
    _, redeeming, vault_addr = redeeming_loan
    p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)
    assert centrifuge_async_vault_mock.redeem_cancel_pending(vault_addr) is True
    assert p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower) is False
    assert p2p_usdc_weth_centrifuge.loans(redeeming.id) == compute_loan_hash(redeeming)


def test_cancel_redeem_reverses_redemption_when_cancel_claimable(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, weth, borrower
):
    """cancel_claimable > 0: reclaim the shares and reverse the redemption."""
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


def test_cancel_redeem_reverts_if_loan_invalid(p2p_usdc_weth_centrifuge, redeeming_loan, borrower):
    """Every single-field corruption fails `_is_loan_valid` before the redeeming/borrower preconditions."""
    _, redeeming, _ = redeeming_loan
    for mutated in get_loan_mutations(redeeming):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth_centrifuge.cancel_redeem(mutated, sender=borrower)


def test_cancel_redeem_reverts_if_not_borrower(p2p_usdc_weth_centrifuge, redeeming_loan, borrower, accounts):
    _, redeeming, _ = redeeming_loan
    stranger = accounts[6]
    assert stranger != borrower
    with boa.reverts("not borrower"):
        p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=stranger)


def test_cancel_redeem_reverts_if_redeem_claimable(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, usdc, borrower
):
    """Once the redemption is fully fulfilled (request_claimable > 0) the payment has landed, so the
    borrower must settle, not cancel."""
    _, redeeming, vault_addr = redeeming_loan
    shares, assets = 10**18, 900 * 10**6  # the whole redeemed collateral settles to 900 USDC
    usdc.mint(centrifuge_async_vault_mock.address, assets)  # fund the mock to pay the redeem out
    centrifuge_async_vault_mock.fulfill_redeem(vault_addr, shares, assets)
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == shares  # precondition: claimable (in shares)

    with boa.reverts("claimable redeem"):
        p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)


# ---------------------------------------------------------------------------
# 4b. transfer_loan of an async-redeeming loan
# ---------------------------------------------------------------------------


def test_transfer_loan_async_redeem_claims_and_migrates_proceeds(
    p2p_usdc_weth_centrifuge,
    redeeming_loan,
    centrifuge_async_vault_mock,
    transfer_agent,
    kyc_for,
    kyc_validator_contract,
    usdc,
    borrower,
    lender,
    now,
):
    """transfer_loan of a redeeming async loan claims the fulfilled proceeds into the old vault, migrates
    them to the new borrower's vault, and the new borrower can then settle.

    The ERC-7540 redeem request is keyed to the current vault as controller, so migrating without claiming
    would strand the proceeds in the old vault. When the redemption is fulfilled (request_claimable > 0),
    claim it before migrating; settle_loan then reads the already-claimed proceeds from the new vault.
    """
    p2p = p2p_usdc_weth_centrifuge
    _, redeeming, old_vault_addr = redeeming_loan
    shares, assets = 10**18, 1200 * 10**6  # proceeds > debt -> surplus for the borrower on settle
    _fulfil_redeem(centrifuge_async_vault_mock, usdc, old_vault_addr, shares, assets)
    assert centrifuge_async_vault_mock.redeem_claimable(old_vault_addr) == shares  # precondition: fulfilled, unclaimed
    assert usdc.balanceOf(old_vault_addr) == 0  # precondition: proceeds still in the async vault, not the loan vault

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    assert new_borrower != borrower

    p2p.transfer_loan(redeeming, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent)

    # The migrated loan: same fields, new borrower, vault_id == the new borrower's next vault (0).
    event = get_last_event(p2p, "LoanBorrowerTransferred")
    new_vault_addr = p2p.vault_id_to_vault(new_borrower, 0)  # the migrated loan's vault (vault_id 0)
    migrated = redeeming._replace(id=event.new_loan_id, borrower=new_borrower, vault_id=0)
    assert p2p.loans(migrated.id) == compute_loan_hash(migrated)  # migrated loan stored
    assert p2p.loans(redeeming.id) == ZERO_BYTES32  # old loan cleared

    # The async redemption was claimed into the old vault, then the proceeds moved to the new vault.
    assert centrifuge_async_vault_mock.redeem_claimable(old_vault_addr) == 0  # claimed (not left in-flight)
    assert usdc.balanceOf(old_vault_addr) == 0  # old vault emptied of payment token
    assert usdc.balanceOf(new_vault_addr) == assets  # proceeds migrated to the new borrower's vault, pre-settle

    # The new borrower settles from the migrated proceeds (async path ignores the redeem_result arg).
    interest = migrated.get_interest(boa.eval("block.timestamp"))
    protocol_fee = interest * migrated.protocol_settlement_fee // BPS  # settlement fee is 0 in this fixture
    assert protocol_fee == 0
    surplus = assets - migrated.amount - interest
    assert surplus > 0  # precondition: proceeds cover the debt with a surplus

    lender_0, borrower_0 = usdc.balanceOf(lender), usdc.balanceOf(new_borrower)
    p2p.settle_loan(migrated, EMPTY_REDEEM_RESULT, sender=new_borrower)

    assert p2p.loans(migrated.id) == ZERO_BYTES32  # settled, hash cleared
    assert usdc.balanceOf(new_vault_addr) == 0  # proceeds fully distributed out of the vault
    assert usdc.balanceOf(lender) - lender_0 == migrated.amount + interest - protocol_fee  # lender made whole
    assert usdc.balanceOf(new_borrower) - borrower_0 == surplus  # surplus to the NEW borrower


def test_transfer_loan_async_redeem_reverts_if_not_settled(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, transfer_agent, kyc_for, kyc_validator_contract
):
    """transfer_loan of an async-redeeming loan reverts until the redemption is fulfilled.

    With the redeem requested but not fulfilled (request_claimable == 0, request_pending > 0), there is
    nothing to claim, so the migrate-with-claim path refuses to run.
    """
    p2p = p2p_usdc_weth_centrifuge
    _, redeeming, old_vault_addr = redeeming_loan
    assert centrifuge_async_vault_mock.redeem_pending(old_vault_addr) > 0  # precondition: request in flight
    assert centrifuge_async_vault_mock.redeem_claimable(old_vault_addr) == 0  # precondition: not fulfilled

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    with boa.reverts("redeem not settled"):
        p2p.transfer_loan(redeeming, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent)


def test_transfer_loan_reverts_if_loan_invalid(
    p2p_usdc_weth_centrifuge, started_loan, transfer_agent, kyc_for, kyc_validator_contract, borrower
):
    """Every single-field corruption fails `_is_loan_valid` before the started/transfer-agent preconditions."""
    p2p = p2p_usdc_weth_centrifuge
    loan, _ = started_loan
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    assert new_borrower != borrower
    for mutated in get_loan_mutations(loan):
        with boa.reverts("invalid loan"):
            p2p.transfer_loan(mutated, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent)


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
# 6. mint_addr rotation + window-zero auth
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
    """Rotating mint_addr to a fresh AsyncVault must not activate a zero-collateral loan.

    After the deposit settles on the original mint_addr, the owner rotates mint_addr to a fresh AsyncVault
    whose mint_status reads all-zeros. The `request_claimable > 0` guard reverts "mint not settled" rather
    than activating a 0-collateral loan.
    """
    loan, vault_addr = pending_loan
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, 1500 * 10**6, 10**18)  # legit deposit settles
    assert centrifuge_async_vault_mock.deposit_claimable(vault_addr) == 1500 * 10**6

    fresh_mint = centrifuge_async_vault_mock_contract_def.deploy(usdc.address, weth.address)
    assert fresh_mint.deposit_claimable(vault_addr) == 0  # rotated addr reads all-zeros
    p2p_usdc_weth_centrifuge.set_mint_addr(fresh_mint.address, sender=owner)

    with boa.reverts("mint not settled"):
        p2p_usdc_weth_centrifuge.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=borrower)


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
    """max_pending_window == 0 disables permissionless cancel (borrower-only), not open from block zero."""
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
    """With the permissionless path disabled (window 0) the borrower can still cancel."""
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

    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower) is False  # submits the cancel
    assert centrifuge_async_vault_mock.deposit_cancel_pending(vault_addr) is True


# ---------------------------------------------------------------------------
# 7. Terminal "nothing to resolve" reverts (all four async counters zero)
# ---------------------------------------------------------------------------


def test_cancel_pending_reverts_when_no_pending_mint(
    p2p_usdc_weth_centrifuge, pending_loan, centrifuge_async_vault_mock, borrower
):
    """A pending loan whose deposit has been fully drained (all four mint counters zero) reverts.

    Drive the mock so the deposit is neither pending nor claimable nor cancelling: request the
    cancellation, process it, then claim the reclaimed payment DIRECTLY off the mock (the issuer surface,
    standing in for an out-of-band drain). cancel_pending_loan reaches the terminal branch, claims nothing
    (minted == 0 and reclaimed == 0), and reverts "no pending mint" at Loan.vy:411.
    """
    loan, vault_addr = pending_loan
    mock = centrifuge_async_vault_mock

    # Drain the pending deposit to all-zero via the mock's ERC-7887 surface (permissionless issuer hooks):
    # cancel the pending remainder, process it, then claim the reclaimed payment straight out.
    mock.cancelDepositRequest(0, vault_addr)  # pending -> cancel pipeline, cancel_pending True
    mock.process_cancel_deposit(vault_addr)  # -> cancel_claimable == mint_spend
    mock.claimCancelDepositRequest(0, vault_addr, vault_addr)  # drain the reclaimable payment out

    # PRECONDITION: all four mint counters zero, yet the loan is still stored pending.
    status = _mock_mint_status(mock, vault_addr)
    assert status == {"request_pending": 0, "request_claimable": 0, "cancel_pending": 0, "cancel_claimable": 0}
    assert loan.start_time == 0  # still pending
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == compute_loan_hash(loan)

    with boa.reverts("no pending mint"):
        p2p_usdc_weth_centrifuge.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_cancel_redeem_reverts_if_request_still_pending(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, weth, owner, borrower
):
    """cancel_claimable > 0 AND request_pending > 0 (request_claimable == 0) reverts "redeem still pending".

    The earlier "claimable redeem" guard only blocks a FULFILLED request (request_claimable > 0); here the
    fulfilled slice is zero but a fresh redeem request is in flight alongside a settled cancellation, so the
    cancel_claimable branch runs its `request_pending == 0` assert and reverts at Loan.vy:539.
    """
    _, redeeming, vault_addr = redeeming_loan
    mock = centrifuge_async_vault_mock

    # Settle a cancellation of the original redeem request (cancel_claimable > 0, pending drained to 0)...
    mock.cancelRedeemRequest(0, vault_addr)  # redeem_pending -> cancel pipeline
    mock.process_cancel_redeem(vault_addr)  # -> redeem_cancel_claimable == 10**18
    # ...then float a NEW pending redeem request so request_pending > 0 again (request_claimable stays 0).
    rerequest_shares = 10**17  # 0.1 weth, funded on a fresh owner the mock pulls from
    weth.mint(borrower, rerequest_shares, sender=owner)
    weth.approve(mock.address, rerequest_shares, sender=borrower)
    mock.requestRedeem(rerequest_shares, vault_addr, borrower)  # controller = the loan vault

    # PRECONDITION: cancel settled AND a fresh request still pending, nothing yet claimable.
    status = _mock_redeem_status(mock, vault_addr)
    assert status["cancel_claimable"] > 0
    assert status["request_pending"] > 0
    assert status["request_claimable"] == 0  # so the "claimable redeem" guard passes

    with boa.reverts("redeem still pending"):
        p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)


def test_cancel_redeem_reverts_when_no_pending_redeem(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower
):
    """A redeeming loan (redeem_start > 0) with all four redeem counters zero reverts "no pending redeem".

    Drain the in-flight redeem to all-zero (cancel, process, then claim the reclaimed shares directly off
    the mock). cancel_redeem passes every earlier guard and falls through the empty state machine to the
    terminal `raise "no pending redeem"` at Loan.vy:593.
    """
    _, redeeming, vault_addr = redeeming_loan
    mock = centrifuge_async_vault_mock
    assert redeeming.redeem_start > 0  # precondition: the loan IS redeeming

    mock.cancelRedeemRequest(0, vault_addr)  # redeem_pending -> cancel pipeline
    mock.process_cancel_redeem(vault_addr)  # -> redeem_cancel_claimable == 10**18
    mock.claimCancelRedeemRequest(0, vault_addr, vault_addr)  # drain the reclaimable shares out

    # PRECONDITION: all four redeem counters zero.
    status = _mock_redeem_status(mock, vault_addr)
    assert status == {"request_pending": 0, "request_claimable": 0, "cancel_pending": 0, "cancel_claimable": 0}

    with boa.reverts("no pending redeem"):
        p2p_usdc_weth_centrifuge.cancel_redeem(redeeming, sender=borrower)


# ---------------------------------------------------------------------------
# 8. Capability guards on a non-async-cancel market (Midas: MINT_SYNC | REDEEM_SYNC)
# ---------------------------------------------------------------------------
#
# The Midas sync market lacks MINT_ASYNC|MINT_CANCEL and REDEEM_ASYNC|REDEEM_CANCEL, so cancel_pending_loan
# and cancel_redeem must reject it at their capability asserts. Both asserts sit AFTER the loan-valid /
# state / sender checks but BEFORE _get_vault, so a fabricated loan whose hash is seeded straight into
# storage reaches the guard without any real mint/redeem scaffolding.


def _seed_loan(p2p, loan):
    """Store `loan`'s state hash so `_is_loan_valid` passes for a fabricated (never-created) loan."""
    p2p.eval(f"base.loans[{'0x' + loan.id.hex()}] = {'0x' + compute_loan_hash(loan).hex()}")


def _fabricated_loan(usdc, weth, oracle, borrower, lender, now, **overrides):
    """A self-consistent Loan (id == its own hash) with sane token/oracle fields, plus any overrides.

    Only the stored hash matters for the capability-guard reverts, but real token/oracle addresses keep the
    loan plausible and let the earlier validity/state asserts pass.
    """
    fields = {
        "offer_id": ZERO_BYTES32,
        "offer_tracing_id": ZERO_BYTES32,
        "initial_amount": 1000 * 10**6,
        "amount": 1000 * 10**6,
        "apr": 1000,
        "payment_token": usdc.address,
        "maturity": now + 100,
        "create_time": now,
        "start_time": 0,
        "accrual_start_time": now,
        "borrower": borrower,
        "lender": lender,
        "collateral_token": weth.address,
        "collateral_amount": 10**18,
        "min_collateral_amount": 0,
        "oracle_addr": oracle.address,
        "vault_id": 0,
    }
    fields.update(overrides)
    loan = Loan(**fields)
    return replace_namedtuple_field(loan, id=compute_loan_hash(loan))


def test_cancel_pending_reverts_cancel_not_supported(p2p_usdc_weth_sync, usdc, weth, oracle, borrower, lender, now):
    """cancel_pending_loan on a Midas (MINT_SYNC|REDEEM_SYNC) market reverts "cancel not supported".

    A fabricated PENDING loan (start_time 0) passes loan-valid / not-started / borrower, then trips the
    `(caps & (MINT_ASYNC|MINT_CANCEL))` guard at Loan.vy:391 (Midas has neither flag).
    """
    loan = _fabricated_loan(usdc, weth, oracle, borrower, lender, now, start_time=0)
    _seed_loan(p2p_usdc_weth_sync, loan)
    assert p2p_usdc_weth_sync.loans(loan.id) == compute_loan_hash(loan)  # precondition: valid & seeded

    with boa.reverts("cancel not supported"):
        p2p_usdc_weth_sync.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=borrower)


def test_cancel_redeem_reverts_redeem_cancel_not_supported(p2p_usdc_weth_sync, usdc, weth, oracle, borrower, lender, now):
    """cancel_redeem on a Midas (MINT_SYNC|REDEEM_SYNC) market reverts "redeem cancel not supported".

    A fabricated STARTED, redeeming loan (start_time == create_time, redeem_start > 0) passes loan-valid /
    started / redeeming / borrower, then trips the `(caps & (REDEEM_ASYNC|REDEEM_CANCEL))` guard at
    Loan.vy:529 (Midas has neither flag).
    """
    loan = _fabricated_loan(usdc, weth, oracle, borrower, lender, now, start_time=now, redeem_start=now)
    _seed_loan(p2p_usdc_weth_sync, loan)
    assert loan.start_time >= loan.create_time  # precondition: started
    assert loan.redeem_start > 0  # precondition: redeeming

    with boa.reverts("redeem cancel not supported"):
        p2p_usdc_weth_sync.cancel_redeem(loan, sender=borrower)


# ---------------------------------------------------------------------------
# 9. Async create guard variants (zero borrower margin; origination fee > BPS)
# ---------------------------------------------------------------------------


def test_create_leveraged_async_zero_borrower_margin(
    p2p_usdc_weth_centrifuge, sign_centrifuge_offer, kyc_borrower, kyc_lender, usdc, borrower, lender, owner
):
    """mint_spend == principal (origination fee 0) leaves borrower_margin == 0: the borrower is not debited.

    The lender funds the whole mint_spend; the borrower spends nothing and LeveragedLoanCreated reports
    borrower_margin == 0. The `if borrower_margin > 0` transferFrom is skipped entirely.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal = 1000 * 10**6
    mint_spend = principal  # == lender_to_vault (origination fee 0) -> borrower_margin 0
    collateral = 10**18
    signed_offer = sign_centrifuge_offer(principal)  # origination_fee_bps 0
    # Fund only the lender; deliberately leave the borrower with NOTHING to prove no debit occurs.
    usdc.mint(lender, mint_spend)
    usdc.approve(p2p.address, mint_spend, sender=lender)
    lender_0 = usdc.balanceOf(lender)
    assert usdc.balanceOf(borrower) == 0  # precondition: borrower holds no payment token
    assert usdc.allowance(borrower, p2p.address) == 0  # and grants no allowance

    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )

    event = get_last_event(p2p, "LeveragedLoanCreated")
    assert event.id == loan_id
    assert event.payment_spent == mint_spend
    assert event.borrower_margin == 0  # no borrower equity in the mint
    assert usdc.balanceOf(borrower) == 0  # borrower never debited
    assert lender_0 - usdc.balanceOf(lender) == mint_spend  # lender funded the whole spend


def test_create_leveraged_async_reverts_if_origination_fee_gt_bps(
    p2p_usdc_weth_centrifuge, usdc, weth, oracle, lender, borrower, lender_key, kyc_borrower, kyc_lender, now
):
    """An offer with origination_fee_bps > BPS reverts "origination fee gt principal" (Loan.vy:928).

    The async builder guards the fee before any mint, so no funding is needed. duration (100) > window (50)
    clears the earlier `duration le pending window` assert, isolating the fee guard.
    """
    p2p = p2p_usdc_weth_centrifuge
    principal, mint_spend, collateral = 1000 * 10**6, 1500 * 10**6, 10**18
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,  # > the fixture's 50s window (earlier guard passes)
        origination_fee_bps=BPS + 1,  # fee bps exceeds 100% of principal -> the guard under test
        max_iltv=8000,
        available_liquidity=principal,
        oracle_addr=oracle.address,
        expiration=now + 10**6,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p.address)
    assert signed_offer.offer.origination_fee_bps > BPS  # precondition: over the cap
    assert signed_offer.offer.duration > p2p.max_pending_window()  # earlier duration guard passes

    with boa.reverts("origination fee gt principal"):
        p2p.create_leveraged_loan(
            signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
        )


# ---------------------------------------------------------------------------
# 10. Centrifuge vault unsupported-capability stubs (mint_sync / mint_manual / redeem_sync / redeem_manual)
# ---------------------------------------------------------------------------


def test_centrifuge_vault_unsupported_ops_revert(centrifuge_async_vault_impl_contract_def, usdc, weth, owner):
    """The async vault stubs out the sync/manual mint & redeem ops; each raises its own "not supported".

    These stubs raise immediately with no caller guard, so any sender hits the raise. Same "these ops are
    unavailable on an async vault" assertion, one test with a block per op.
    """
    vault = _standalone_vault(centrifuge_async_vault_impl_contract_def, weth, owner)
    m = vault.address  # any address works; the stub raises before touching it

    with boa.reverts("mint_sync not supported"):
        vault.mint_sync(usdc.address, m, 0, 1)
    with boa.reverts("mint_manual not supported"):
        vault.mint_manual(usdc.address, m, 0, 1)
    with boa.reverts("redeem_sync not supported"):
        vault.redeem_sync(m, weth.address, 1, 1, 1)
    with boa.reverts("redeem_manual not supported"):
        vault.redeem_manual(m, weth.address, 1, 1, 1)
