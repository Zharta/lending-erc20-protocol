"""Unit tests for settling / liquidating an async (Centrifuge ERC-7540) loan whose
redemption has been fulfilled on-chain.

`base._resolve_redeem_balances` claims the proceeds on-chain for a REDEEM_ASYNC vault (reverting
"redeem not settled" until fulfilled), so `settle_loan` / `liquidate_loan` ignore their `redeem_result`
arg on the async path (pass an empty SignedRedeemResult).

The `started_loan` / `redeeming_loan` fixtures run the whole path with concrete amounts:
create_leveraged_loan -> fulfill_deposit -> start_loan -> redeem. The surplus test sets a custom
settlement fee (snapshotted at creation), so it runs the path inline instead.

The CentrifugeAsyncVaultMock pays usdc out on a redeem claim from its own balance, so tests fund the
mock with the redeem proceeds before settling (`_fulfil_redeem` below).
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
EMPTY_REDEEM_RESULT = SignedRedeemResult()  # ignored on the async path


def _fulfil_redeem(centrifuge_async_vault_mock, usdc, vault_addr, shares, assets):
    """Issuer settles the pending redeem of `shares` -> `assets` usdc, funding the mock to pay it out."""
    usdc.mint(centrifuge_async_vault_mock.address, assets)
    centrifuge_async_vault_mock.fulfill_redeem(vault_addr, shares, assets)


# ---------------------------------------------------------------------------
# Lifecycle-stage fixtures (each runs the full path from create with concrete amounts)
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
    """A started async loan (default fees): create -> fulfil deposit -> start_loan claims 1 weth."""
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
    """(started_loan, redeeming_loan, vault_addr): a started async loan put into redemption (residual 0)."""
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

    Inline because the 5% settlement fee must be set before create so the loan snapshots it.
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
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0  # redemption was actually claimed
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
    # Shortfall branch: committed drops by the principal actually RECOVERED (min(lender_funds_delta,
    # loan.amount)), not the full loan.amount; the unrecovered principal stays committed as a realized loss.
    # Here lender_funds_delta = assets + 0 collateral - 0 fee = assets < loan.amount, so the drop is `assets`.
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


# ---------------------------------------------------------------------------
# Mixed redeem terminal state (partially fulfilled AND partially cancelled)
#
# An async ERC-7540 redeem can end up with request_claimable > 0 (fulfilled slice -> payment) AND
# cancel_claimable > 0 (cancelled remainder -> reclaimed collateral shares), both pendings zero.
# settle/liquidate forward-resolve this by claiming BOTH legs (fulfilled payment via
# claim_redeem(True,False); reclaimed collateral via claim_redeem(False,True)) and closing the loan
# against the combined estate. cancel_redeem stays blocked — a partially-fulfilled redeem cannot be
# cleanly reversed, so the borrower settles forward instead.
#
# Reaching the mixed state (the mock hooks stand in for the off-chain issuer):
#   redeem(residual)                     -> requestRedeem(collateral - residual): redeem_pending set
#   fulfill_redeem(vault, part, assets)  -> partial fulfil: pending -= part, claimable += part
#   cancelRedeemRequest(0, vault)        -> move the still-pending remainder into the cancel pipeline
#   process_cancel_redeem(vault)         -> cancel_claimable := remainder
# yields redeem_claimable = part (payment=assets), redeem_cancel_claimable = remainder, both pendings 0.
# ---------------------------------------------------------------------------


def _drive_to_mixed_redeem(centrifuge_async_vault_mock, usdc, vault_addr, fulfilled_shares, assets):
    """Put an already-requested redeem into the MIXED terminal state (fulfilled slice + cancelled rest).

    Precondition: redeem_pending(vault_addr) > fulfilled_shares (a genuine remainder to cancel).
    Partially fulfils `fulfilled_shares` -> `assets` usdc (funding the mock to pay the fulfilled claim),
    then cancels + processes the remaining pending. Leaves redeem_claimable == fulfilled_shares and
    redeem_cancel_claimable == the un-fulfilled remainder, both pendings zero.
    """
    remainder = centrifuge_async_vault_mock.redeem_pending(vault_addr) - fulfilled_shares
    assert remainder > 0, "no remainder to cancel — not a mixed state"
    usdc.mint(centrifuge_async_vault_mock.address, assets)
    centrifuge_async_vault_mock.fulfill_redeem(vault_addr, fulfilled_shares, assets)  # fulfil a slice
    centrifuge_async_vault_mock.cancelRedeemRequest(0, vault_addr)  # issuer cancels the remainder
    centrifuge_async_vault_mock.process_cancel_redeem(vault_addr)  # issuer settles the cancellation
    return remainder


def test_settle_async_mixed_state_forward_resolves_and_clears_loan(
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
    """A redeem that is partially fulfilled AND partially cancelled settles by claiming both legs.

    Estate: fulfilled payment repays the debt (surplus -> borrower); the residual weth PLUS the reclaimed
    (cancelled) shares are returned to the borrower as collateral. Inline (5% settlement fee snapshotted
    at create).
    """
    p2p = p2p_usdc_weth_centrifuge
    p2p.set_protocol_fee(0, 500, sender=owner)  # 5% settlement fee
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

    # redeem keeping 0.2 weth residual in the vault; 0.8 weth is requested for redemption
    residual = 2 * 10**17
    redeemed_shares = collateral - residual  # 0.8 weth requested
    p2p.redeem(started, residual, sender=borrower)
    loan = started._replace(redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=residual)
    assert loan.protocol_settlement_fee == 500
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) == redeemed_shares

    # drive to the mixed state: fulfil 0.5 weth -> 1200e6 usdc, cancel the remaining 0.3 weth
    fulfilled_shares = 5 * 10**17  # 0.5 weth fulfilled
    assets = 1200 * 10**6  # payment for the fulfilled slice (> debt -> surplus)
    reclaimed = _drive_to_mixed_redeem(centrifuge_async_vault_mock, usdc, vault_addr, fulfilled_shares, assets)
    assert reclaimed == redeemed_shares - fulfilled_shares == 3 * 10**17  # 0.3 weth cancelled remainder

    # precondition: genuinely mixed — both legs claimable, no pendings
    status = centrifuge_async_vault_mock
    assert status.redeem_claimable(vault_addr) == fulfilled_shares
    assert status.redeem_cancel_claimable(vault_addr) == reclaimed
    assert status.redeem_pending(vault_addr) == 0
    assert status.redeem_cancel_pending(vault_addr) is False

    boa.env.time_travel(seconds=50)  # accrue interest within the 100s term
    interest = loan.get_interest(boa.eval("block.timestamp"))
    protocol_fee = interest * 500 // BPS
    debt = loan.amount + interest
    surplus = assets - debt
    returned_collateral = residual + reclaimed  # 0.2 + 0.3 = 0.5 weth
    assert interest > 0
    assert protocol_fee > 0
    assert surplus > 0

    lender_0, borrower_usdc_0 = usdc.balanceOf(lender), usdc.balanceOf(borrower)
    protocol_0 = usdc.balanceOf(p2p.protocol_wallet())
    borrower_weth_0 = weth.balanceOf(borrower)

    p2p.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)

    event = get_last_event(p2p, "LoanPaid")
    assert event.id == loan.id
    assert event.paid_principal == loan.amount
    assert event.paid_interest == interest
    assert event.protocol_settlement_fee_amount == protocol_fee
    assert event.in_vault_payment_token == assets  # only the fulfilled slice's proceeds
    assert event.in_vault_collateral == returned_collateral  # residual + reclaimed shares

    # loan closed; both async legs consumed
    assert p2p.loans(loan.id) == ZERO_BYTES32
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0  # fulfilled leg claimed
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) == 0  # cancelled leg claimed
    assert weth.balanceOf(vault_addr) == 0  # all collateral left the vault

    # estate distribution
    assert usdc.balanceOf(lender) - lender_0 == debt - protocol_fee  # lender: debt net of fee
    assert usdc.balanceOf(p2p.protocol_wallet()) - protocol_0 == protocol_fee
    assert usdc.balanceOf(borrower) - borrower_usdc_0 == surplus  # borrower: surplus payment
    assert weth.balanceOf(borrower) - borrower_weth_0 == returned_collateral  # borrower: combined collateral


def test_liquidate_async_mixed_state_forward_resolves_and_clears_loan(
    p2p_usdc_weth_centrifuge,
    redeeming_loan,
    centrifuge_async_vault_mock,
    usdc,
    weth,
    borrower,
    lender,
    accounts,
):
    """A defaulted loan in the mixed redeem state liquidates by claiming both legs.

    The fulfilled payment alone covers the debt (in_vault_payment_token >= outstanding_debt branch): the
    lender is paid the debt, and the reclaimed collateral shares are returned to the borrower.
    """
    _, loan, vault_addr = redeeming_loan  # residual 0; 1 weth requested for redemption
    assert loan.redeem_residual_collateral == 0
    assert centrifuge_async_vault_mock.redeem_pending(vault_addr) == 10**18

    # mixed state: fulfil 0.6 weth -> 1500e6 usdc (> debt), cancel the remaining 0.4 weth
    fulfilled_shares = 6 * 10**17
    assets = 1500 * 10**6
    reclaimed = _drive_to_mixed_redeem(centrifuge_async_vault_mock, usdc, vault_addr, fulfilled_shares, assets)
    assert reclaimed == 4 * 10**17  # 0.4 weth reclaimed

    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == fulfilled_shares
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) == reclaimed

    boa.env.time_travel(seconds=loan.maturity - boa.eval("block.timestamp") + 1)  # default
    interest = loan.get_liquidation_interest()
    outstanding_debt = loan.amount + interest
    assert assets >= outstanding_debt  # payment leg alone covers the debt (fee 0)

    liquidator = accounts[5]
    committed_0, lender_0, borrower_usdc_0 = (
        p2p_usdc_weth_centrifuge.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32)),
        usdc.balanceOf(lender),
        usdc.balanceOf(borrower),
    )
    borrower_weth_0 = weth.balanceOf(borrower)
    assert committed_0 == loan.amount

    p2p_usdc_weth_centrifuge.liquidate_loan(loan, EMPTY_REDEEM_RESULT, sender=liquidator)

    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanLiquidated")
    assert event.id == loan.id
    assert event.liquidator == liquidator
    assert event.outstanding_debt == outstanding_debt
    assert event.shortfall == 0  # payment covers the debt
    assert event.protocol_settlement_fee_amount == 0

    # loan closed; both async legs consumed
    assert p2p_usdc_weth_centrifuge.loans(loan.id) == ZERO_BYTES32
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) == 0
    assert weth.balanceOf(vault_addr) == 0

    # payment leg fully covers the debt: lender gets the debt, borrower gets the surplus payment and
    # ALL the collateral back (the reclaimed shares), liquidator gets nothing (fee 0).
    assert usdc.balanceOf(lender) - lender_0 == outstanding_debt
    assert usdc.balanceOf(borrower) - borrower_usdc_0 == assets - outstanding_debt
    assert weth.balanceOf(borrower) - borrower_weth_0 == reclaimed  # reclaimed collateral returned
    assert usdc.balanceOf(liquidator) == 0
    assert weth.balanceOf(liquidator) == 0
    committed_after = p2p_usdc_weth_centrifuge.commited_liquidity(compute_liquidity_key(lender, ZERO_BYTES32))
    assert committed_0 - committed_after == loan.amount  # covered: full principal freed


def test_cancel_redeem_still_blocked_in_mixed_state(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, usdc, borrower
):
    """A partially-fulfilled redeem cannot be cleanly reversed: cancel_redeem reverts "claimable redeem"
    in the mixed state — the borrower must settle forward instead."""
    _, loan, vault_addr = redeeming_loan
    _drive_to_mixed_redeem(centrifuge_async_vault_mock, usdc, vault_addr, 6 * 10**17, 1200 * 10**6)
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) > 0  # fulfilled slice present
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) > 0  # cancelled slice present
    with boa.reverts("claimable redeem"):
        p2p_usdc_weth_centrifuge.cancel_redeem(loan, sender=borrower)


def test_settle_async_cancel_only_returns_residual_plus_reclaimed(
    p2p_usdc_weth_centrifuge, redeeming_loan, centrifuge_async_vault_mock, usdc, weth, borrower, lender
):
    """Cancel-only branch under settle: request never fulfilled (request_claimable == 0), the whole redeem
    is cancelled. settle takes the else leg: payment = vault balance (0 here), collateral = residual +
    reclaimed. The borrower tops up the full debt (no proceeds), lender made whole.
    """
    _, loan, vault_addr = redeeming_loan  # residual 0; 1 weth requested for redemption
    reclaimed = 10**18
    # cancel the ENTIRE pending redeem (no fulfillment) -> pure cancel_claimable, request_claimable == 0
    centrifuge_async_vault_mock.cancelRedeemRequest(0, vault_addr)
    centrifuge_async_vault_mock.process_cancel_redeem(vault_addr)
    assert centrifuge_async_vault_mock.redeem_claimable(vault_addr) == 0
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) == reclaimed

    interest = loan.get_interest(boa.eval("block.timestamp"))
    debt = loan.amount + interest
    usdc.mint(borrower, debt)
    usdc.approve(p2p_usdc_weth_centrifuge.address, debt, sender=borrower)
    lender_0, borrower_weth_0 = usdc.balanceOf(lender), weth.balanceOf(borrower)

    p2p_usdc_weth_centrifuge.settle_loan(loan, EMPTY_REDEEM_RESULT, sender=borrower)

    event = get_last_event(p2p_usdc_weth_centrifuge, "LoanPaid")
    assert event.in_vault_payment_token == 0  # nothing fulfilled -> no payment proceeds
    assert event.in_vault_collateral == reclaimed  # residual (0) + reclaimed collateral

    assert p2p_usdc_weth_centrifuge.loans(loan.id) == ZERO_BYTES32
    assert centrifuge_async_vault_mock.redeem_cancel_claimable(vault_addr) == 0  # reclaimed leg claimed
    assert usdc.balanceOf(lender) - lender_0 == debt  # lender made whole from the borrower's topup
    assert weth.balanceOf(borrower) - borrower_weth_0 == reclaimed  # all collateral back
    assert weth.balanceOf(vault_addr) == 0
