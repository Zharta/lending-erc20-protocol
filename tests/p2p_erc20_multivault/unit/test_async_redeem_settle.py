"""Unit tests for settling / liquidating an async (Centrifuge ERC-7540) loan whose
redemption has been fulfilled on-chain - the path audit fix A1 unblocked.

Previously nothing claimed a fulfilled async redemption out of the AsyncVault, so an async `redeem()`
could never settle (deadlock). `base._resolve_redeem_balances` now claims the proceeds on-chain for a
REDEEM_ASYNC vault (asserting "redeem not settled" until it is fulfilled), so `settle_loan` /
`liquidate_loan` ignore their `redeem_result` arg on the async path (pass an empty SignedRedeemResult).

Each lifecycle stage has ONE flat fixture defined in this file (`started_loan`, `redeeming_loan`) that
runs the whole path with concrete amounts visible in sequence: `create_leveraged_loan(...)` ->
`fulfill_deposit(...)` -> `start_loan(...)` -> `redeem(...)`. The surplus test sets a custom settlement
fee (which must be snapshotted at creation), so it runs the path inline instead.

The CentrifugeAsyncVaultMock pays `asset` (usdc) out on a redeem claim from its own balance, so a test funds the
mock with the redeem proceeds before settling (the `_fulfil_redeem` two-liner below).
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    SignedRedeemResult,
    compute_liquidity_key,
    get_last_event,
)
from .conftest import expected_pending_centrifuge_loan

BPS = 10000
EMPTY_MINT_RESULT = ((ZERO_ADDRESS, 0, 0, 0), (0, 0, 0))
EMPTY_REDEEM_RESULT = SignedRedeemResult()  # ignored on the async path (claims on-chain)


def _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, shares, assets):
    """Issuer settles the pending redeem of `shares` -> `assets` usdc, funding the mock to pay it out."""
    usdc.mint(centrifuge_async_vault_mock.address, assets)
    centrifuge_async_vault_mock.fulfill_redeem(vault_addr, shares, assets)


# ---------------------------------------------------------------------------
# Lifecycle-stage fixtures (flat: each runs the full path from create with concrete amounts)
# ---------------------------------------------------------------------------


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
    """A STARTED async loan (default fees): create -> issuer fulfils the deposit -> start_loan claims 1 weth."""
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
# settle a fulfilled async redemption
# ---------------------------------------------------------------------------


def test_settle_async_surplus_pays_all_parties_and_clears_loan(
    p2p_usdc_weth_centrifuge,
    sign_centrifuge_offer,
    fund_centrifuge_leveraged,
    centrifuge_async_vault_mock,
    weth,
    owner,
    kyc_borrower,
    kyc_lender,
    usdc,
    borrower,
    lender,
    now,
):
    """Surplus (proceeds > debt): claim the proceeds, pay lender (debt - fee), protocol (fee), borrower (surplus).

    Runs the lifecycle inline (not via a fixture) because the 5% settlement fee must be set BEFORE create
    so the loan snapshots it.
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_protocol_fee(0, 500, sender=owner)  # 5% settlement fee (default is 0)
    principal, mint_spend, collateral, shares = 1000 * 10**6, 1500 * 10**6, 10**18, 10**18
    signed_offer = sign_centrifuge_offer(principal)
    fund_centrifuge_leveraged(principal, mint_spend)
    vault_addr = p2p.wallet_to_vault(borrower)
    loan_id = p2p.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, collateral, sender=borrower
    )
    pending = expected_pending_centrifuge_loan(
        p2p, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    centrifuge_async_vault_mock.fulfill_deposit(vault_addr, mint_spend, shares)
    weth.mint(centrifuge_async_vault_mock.address, shares, sender=owner)
    p2p.start_loan(pending, EMPTY_MINT_RESULT, 0, sender=p2p.protocol_wallet())
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=pending.amount, collateral_amount=shares)

    p2p.redeem(started, 0, sender=borrower)  # residual 0
    loan = started._replace(redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=0)
    assert loan.protocol_settlement_fee == 500

    boa.env.time_travel(seconds=50)  # accrue interest (within the 100s term)
    assets = 1200 * 10**6  # assets > debt -> surplus
    _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, shares, assets)
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == shares  # fulfilled, not yet claimed

    interest = loan.get_interest(boa.eval("block.timestamp"))
    protocol_fee = interest * 500 // BPS
    surplus = assets - loan.amount - interest
    assert interest > 0
    assert protocol_fee > 0
    assert surplus > 0

    lender_0, borrower_0 = usdc.balanceOf(lender), usdc.balanceOf(borrower)
    protocol_0 = usdc.balanceOf(p2p.protocol_wallet())

    p2p.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)

    event = get_last_event(p2p, "LoanPaid")
    assert event.id == loan.id
    assert event.paid_principal == loan.amount
    assert event.paid_interest == interest
    assert event.protocol_settlement_fee_amount == protocol_fee
    assert event.in_vault_payment_token == assets  # the claimed proceeds
    assert event.in_vault_collateral == 0

    assert p2p.loans(loan.id) == ZERO_BYTES32
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0  # A1: the redemption was actually claimed
    assert usdc.balanceOf(lender) - lender_0 == loan.amount + interest - protocol_fee
    assert usdc.balanceOf(p2p.protocol_wallet()) - protocol_0 == protocol_fee
    assert usdc.balanceOf(borrower) - borrower_0 == surplus
    assert weth.balanceOf(borrower) == 0  # no residual collateral


def test_settle_async_shortfall_borrower_tops_up(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, usdc, borrower, lender
):
    """Proceeds below the debt: the borrower tops up the difference, the lender is still made whole (fee 0)."""
    _, loan, vault_addr = redeeming_loan
    shares, assets = 10**18, 800 * 10**6
    _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, shares, assets)

    interest = loan.get_interest(boa.eval("block.timestamp"))
    debt = loan.amount + interest
    shortfall = debt - assets
    assert shortfall > 0

    usdc.mint(borrower, shortfall)
    usdc.approve(p2p_usdc_weth_centrifuge.address, shortfall, sender=borrower)
    lender_0, borrower_0 = usdc.balanceOf(lender), usdc.balanceOf(borrower)

    p2p_usdc_weth_centrifuge.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)

    assert p2p_usdc_weth_centrifuge.loans(loan.id) == ZERO_BYTES32
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0
    assert usdc.balanceOf(lender) - lender_0 == debt  # fee 0
    assert borrower_0 - usdc.balanceOf(borrower) == shortfall


def test_settle_async_with_residual_returns_collateral(
    p2p_usdc_weth_centrifuge, started_loan, centrifuge_async_vault_mock, usdc, weth, borrower, lender
):
    """A redemption keeping residual collateral only redeems `collateral - residual` shares and returns
    the residual weth to the borrower on settle."""
    started, vault_addr = started_loan
    residual = 2 * 10**17  # keep 0.2 weth
    redeemed_shares = 10**18 - residual
    p2p_usdc_weth_centrifuge.redeem(started, residual, sender=borrower)
    loan = started._replace(redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=residual)
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) == redeemed_shares  # only non-residual shares redeemed
    assert weth.balanceOf(vault_addr) == residual  # residual stays in the vault

    assets = 1200 * 10**6
    _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, redeemed_shares, assets)
    interest = loan.get_interest(boa.eval("block.timestamp"))
    surplus = assets - loan.amount - interest
    assert surplus > 0

    lender_0, borrower_usdc_0 = usdc.balanceOf(lender), usdc.balanceOf(borrower)
    p2p_usdc_weth_centrifuge.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)

    assert p2p_usdc_weth_centrifuge.loans(loan.id) == ZERO_BYTES32
    assert weth.balanceOf(borrower) == residual  # residual returned
    assert weth.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(lender) - lender_0 == loan.amount + interest
    assert usdc.balanceOf(borrower) - borrower_usdc_0 == surplus


def test_settle_async_reverts_if_redeem_still_pending(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower
):
    """The redemption was requested but not fulfilled (request_claimable == 0)."""
    _, loan, vault_addr = redeeming_loan
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) > 0
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0
    with boa.reverts("redeem not settled"):
        p2p_usdc_weth_centrifuge.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)


def test_settle_async_reverts_if_cancel_in_flight(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, borrower
):
    """A redeem-cancel is in flight (cancel_pending > 0) before any fulfillment."""
    _, loan, vault_addr = redeeming_loan
    p2p_usdc_weth_centrifuge.cancel_redeem(loan, sender=borrower)  # request the cancellation
    assert centrifuge_async_vault_mock.redeem_cancel_pending(vault_addr) is True
    with boa.reverts("redeem not settled"):
        p2p_usdc_weth_centrifuge.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)


# ---------------------------------------------------------------------------
# liquidate a defaulted async loan mid-redemption
# ---------------------------------------------------------------------------


def test_liquidate_async_claims_proceeds_and_clears_loan(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, usdc, weth, borrower, lender, accounts
):
    """A defaulted async loan whose redemption is fulfilled liquidates by claiming the proceeds; with
    proceeds below the debt (shortfall) the lender recovers exactly the claimed proceeds."""
    _, loan, vault_addr = redeeming_loan
    shares, assets = 10**18, 500 * 10**6  # < debt -> shortfall
    _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, shares, assets)

    boa.env.time_travel(seconds=loan.maturity - boa.eval("block.timestamp") + 1)  # default
    interest = loan.get_liquidation_interest()
    outstanding_debt = loan.amount + interest
    assert assets < outstanding_debt

    liquidator = accounts[5]
    committed_0, lender_0 = (
        p2p_usdc_weth_centrifuge.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)),
        usdc.balanceOf(lender),
    )
    assert committed_0 == loan.amount  # precondition: single-loan offer committed exactly the principal

    p2p_usdc_weth_centrifuge.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanLiquidated")
    assert event.id == loan.id
    assert event.liquidator == liquidator
    assert event.outstanding_debt == outstanding_debt
    assert event.shortfall == outstanding_debt  # no collateral value to offset the debt
    assert event.protocol_settlement_fee_amount == 0

    assert p2p_usdc_weth_centrifuge.loans(loan.id) == ZERO_BYTES32
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0  # claimed
    assert usdc.balanceOf(lender) - lender_0 == assets  # lender recovers exactly the proceeds
    assert usdc.balanceOf(liquidator) == 0  # no fee, no surplus
    # Audit finding #6 refinement (shortfall branch): free only the principal actually RECOVERED
    # (min(lender_funds_delta, loan.amount)), not the full loan.amount. The unrecovered principal is a
    # realized loss that must stay committed. Here the loan is redeemed with proceeds in the vault, so
    # lender_funds_delta = in_vault_payment_token + remaining_collateral_value - protocol_fee
    #                    = assets + 0 - 0 = assets, and assets < loan.amount, so the reduction is `assets`.
    # committed drops by exactly the recovered proceeds; the loss (loan.amount - assets) stays committed.
    recovered = assets  # remaining_collateral_value == 0 and protocol fee == 0 here
    assert recovered < loan.amount  # genuine principal-shortfall
    committed_after = p2p_usdc_weth_centrifuge.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32))
    assert committed_0 - committed_after == recovered
    assert committed_after == loan.amount - recovered  # the realized loss stays committed


def test_liquidate_async_reverts_if_redeem_not_settled(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, accounts
):
    """A defaulted async loan whose redemption is not yet fulfilled cannot be liquidated."""
    _, loan, vault_addr = redeeming_loan
    boa.env.time_travel(seconds=loan.maturity - boa.eval("block.timestamp") + 1)
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0
    with boa.reverts("redeem not settled"):
        p2p_usdc_weth_centrifuge.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=accounts[5])
