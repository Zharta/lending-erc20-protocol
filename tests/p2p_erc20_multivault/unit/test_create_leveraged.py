"""Unit tests for `create_leveraged_loan` (sync MINT_SYNC branch) against the REAL vault.

The collateral is minted through the real `P2PLendingVaultSecuritizeMV` vault (the `p2p_usdc_acred`
market) + an `AcredMock` DS token. The lending contract pre-funds the loan vault with
(lender principal - origination_fee) + borrower_margin (= mint_spend), calls `vault.mint_sync`, which
resolves the swap connector FROM the collateral token (getDSService(1<<14) -> the AcredMock itself),
calls the AcredMock `swap` (which pulls the stablecoin from the vault via transferFrom and mints DS to
it), then reconciles the principal per D13 (flexible `offer.principal == 0` -> reduce principal + refund
the lender; fixed -> refund leftover to the borrower) and stores the loan against the actual minted
collateral.

Collateral math: `minted = mint_spend * RATE_DEN // RATE_NUM` (the AcredMock rate). With the market's
rate (num=1500, den=10**12) a full mint of 1500e6 USDC yields exactly 1e18 DS and consumes all 1500e6
(refund 0). Refunds are driven by `acred_lev.set_max_mint_amount(cap)`: with a cap the swap mints only
`cap` DS and pulls `cap * RATE_NUM // RATE_DEN` stablecoin, leaving the rest as a refund in the vault.

Two DISTINCT minimum checks now exist:
- `min_collateral_out` (7th arg) -> the vault's `min_ds_token_amount`; the AcredMock reverts
  "ds token amount lt min" when the swap-calculated DS falls below it.
- `offer.min_collateral_amount` -> re-validated in `_validate_and_build_loan`; reverts
  "low collateral amount" when the actually-minted collateral is below the offer floor.

Fees (origination + protocol upfront) are snapshotted on the ORIGINAL offer principal (`fee_principal`),
NOT the D13-reconciled principal. `expected_leveraged_loan` therefore takes an explicit `offer_principal`
for the fee basis; tests exercising money math run with a nonzero fee so that basis is actually verified.
The sync mint target is sourced from the market's `mint_addr` (set at deployment), not passed per-call.
"""

import boa

from ..conftest_base import (
    ZERO_BYTES32,
    Loan,
    Offer,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    sign_offer,
)
from .conftest import ACRED_LEV_ORACLE_DECIMALS, ACRED_LEV_ORACLE_RATE

BPS = 10000

# AcredMock rate for the leveraged market: ds = stable * RATE_DEN // RATE_NUM (see conftest).
RATE_NUM = ACRED_LEV_ORACLE_RATE  # 1500
RATE_DEN = 10**ACRED_LEV_ORACLE_DECIMALS  # 10**12


def _minted(mint_spend, *, cap=0):
    """The DS collateral the AcredMock swap mints for `mint_spend` stablecoin, capped by `cap` (0=none)."""
    ds = mint_spend * RATE_DEN // RATE_NUM
    return min(ds, cap) if 0 < cap < ds else ds


def _spent(minted):
    """The stablecoin the AcredMock swap actually pulls for `minted` DS (== mint_spend on a full mint)."""
    return minted * RATE_NUM // RATE_DEN


def _sign_leveraged_offer(
    p2p,
    usdc,
    acred_lev,
    oracle,
    lender,
    borrower,
    lender_key,
    now,
    principal,
    *,
    flexible=False,
    origination_fee_bps=0,
    min_collateral_amount=0,
):
    """Build + sign a sync-market leveraged offer (collateral token = the AcredMock `acred_lev`).

    `flexible=True` sets `offer.principal` to 0 (the D13 flexible branch, where a partial mint reduces the
    stored principal) while keeping `available_liquidity` at the requested principal.
    """
    offer = Offer(
        principal=0 if flexible else principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=acred_lev.address,
        duration=100,
        origination_fee_bps=origination_fee_bps,
        min_collateral_amount=min_collateral_amount,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 10**6,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    return sign_offer(offer, lender_key, p2p.address)


def _fund_leveraged(p2p, usdc, borrower, lender, principal, mint_spend, *, origination_fee_bps=0):
    """Pre-fund a sync create_leveraged_loan: mint+approve the lender's principal (net origination fee)
    and the borrower's margin (= mint_spend - lender's contribution).

    No collateral seeding: the AcredMock swap mints the DS collateral to the vault against the `mint_spend`
    stablecoin the contract routes into the vault (the vault approves the swap and it pulls via transferFrom).
    """
    lender_to_vault = principal - origination_fee_bps * principal // BPS
    borrower_margin = mint_spend - lender_to_vault
    usdc.mint(lender, mint_spend)
    usdc.approve(p2p.address, mint_spend, sender=lender)
    if borrower_margin > 0:
        usdc.mint(borrower, borrower_margin)
        usdc.approve(p2p.address, borrower_margin, sender=borrower)


def expected_leveraged_loan(p2p, signed_offer, loan_id, borrower, lender, now, *, principal, collateral, offer_principal=None):
    """The Loan a sync create_leveraged_loan stores: principal reconciled per D13, collateral == minted.

    `principal` is the reconciled amount stored on the loan (flexible partial mint reduces it; fixed
    keeps it at the requested value); `collateral` is the actually-minted collateral held by the vault.
    Fees are snapshotted on the ORIGINAL offer principal (`offer_principal`, the contract's
    `fee_principal`), which differs from the stored `principal` on a flexible partial mint — pass
    `offer_principal` in that case (defaults to `principal` when they coincide).
    """
    fee_principal = principal if offer_principal is None else offer_principal
    offer = signed_offer.offer
    return Loan(
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
        collateral_amount=collateral,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * fee_principal // BPS,
        protocol_upfront_fee_amount=p2p.protocol_upfront_fee() * fee_principal // BPS,
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


# --------------------------------------------------------------------------- FIXED principal


def test_fixed_creates_loan(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, owner, now
):
    """Both fee fields nonzero so the stored fee snapshot (part of the loan hash) is actually verified."""
    p2p_usdc_acred.set_protocol_fee(200, 0, sender=owner)  # 2% upfront fee snapshotted onto the loan
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)  # 1e18
    origination_fee_bps = 100  # 1%
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        origination_fee_bps=origination_fee_bps,
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    loan = expected_leveraged_loan(
        p2p_usdc_acred, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS  # nonzero, on original principal
    assert loan.protocol_upfront_fee_amount == 200 * principal // BPS
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)


def test_fixed_with_origination_fee(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """Origination fee reduces the lender funds routed to the vault but not the principal."""
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    origination_fee_bps = 100  # 1%
    lender_to_vault = principal - origination_fee_bps * principal // BPS
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        origination_fee_bps=origination_fee_bps,
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)
    lender_before = usdc.balanceOf(lender)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    loan = expected_leveraged_loan(
        p2p_usdc_acred, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)
    assert lender_before - usdc.balanceOf(lender) == lender_to_vault  # lender deploys principal net of fee


def test_fixed_transfers_protocol_upfront_fee_to_wallet(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, owner, now
):
    """The protocol upfront fee is pulled from the lender to the protocol wallet at create."""
    p2p_usdc_acred.set_protocol_fee(200, 0, sender=owner)  # 2% upfront fee, lender-funded
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    protocol_upfront = 200 * principal // BPS  # 20 USDC
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal
    )  # origination fee 0
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)
    protocol_wallet = p2p_usdc_acred.protocol_wallet()
    lender_before, protocol_before = usdc.balanceOf(lender), usdc.balanceOf(protocol_wallet)

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    assert usdc.balanceOf(protocol_wallet) - protocol_before == protocol_upfront  # lender -> protocol wallet
    assert lender_before - usdc.balanceOf(lender) == principal + protocol_upfront  # principal (net orig 0) + upfront


def test_fixed_transfers_collateral_to_vault(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    signed_offer = _sign_leveraged_offer(p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal)
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)
    vault_addr = p2p_usdc_acred.wallet_to_vault(borrower)

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    assert acred_lev.balanceOf(vault_addr) == collateral  # minted DS collateral held by the loan vault


def test_fixed_deploys_lender_and_borrower_funds(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, owner, now
):
    """With both fees live: lender deploys (principal - origination) to the vault + the upfront fee to
    the protocol wallet; the borrower covers the remaining margin."""
    p2p_usdc_acred.set_protocol_fee(200, 0, sender=owner)  # 2% upfront (lender-funded)
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    origination_fee_bps = 100  # 1%
    protocol_upfront = 200 * principal // BPS
    lender_to_vault = principal - origination_fee_bps * principal // BPS
    borrower_margin = mint_spend - lender_to_vault
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        origination_fee_bps=origination_fee_bps,
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)
    lender_before, borrower_before = usdc.balanceOf(lender), usdc.balanceOf(borrower)

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    assert lender_before - usdc.balanceOf(lender) == lender_to_vault + protocol_upfront
    assert borrower_before - usdc.balanceOf(borrower) == borrower_margin


def test_fixed_logs_loan_created_event(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    signed_offer = _sign_leveraged_offer(p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal)
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    event = get_last_event(p2p_usdc_acred, "LoanCreated")
    assert event.id == loan_id
    assert event.amount == principal
    assert event.collateral_amount == collateral


def test_logs_leveraged_event(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    borrower_margin = mint_spend - principal  # 500 USDC; origination fee 0
    signed_offer = _sign_leveraged_offer(p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal)
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    event = get_last_event(p2p_usdc_acred, "LeveragedLoanCreated")
    assert event.id == loan_id
    assert event.principal == principal
    assert event.collateral_amount == collateral
    assert event.acquired_collateral == collateral
    assert event.payment_spent == mint_spend
    assert event.borrower_margin == borrower_margin
    assert event.pending is False
    assert event.mint_deadline == 0  # D31: sync branch always logs mint_deadline 0


# --------------------------------------------------------------------------- FLEXIBLE principal


def test_flexible_full_mint_keeps_principal(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, owner, now
):
    """Flexible offer, full mint (refund 0): principal stays at the requested amount; fees nonzero."""
    p2p_usdc_acred.set_protocol_fee(200, 0, sender=owner)  # 2% upfront fee
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)  # full mint -> refund 0
    origination_fee_bps = 100  # 1%
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        flexible=True,
        origination_fee_bps=origination_fee_bps,
    )
    assert signed_offer.offer.principal == 0  # flexible
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    # full mint: reconciled principal == original -> offer_principal == principal
    loan = expected_leveraged_loan(
        p2p_usdc_acred, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)


def test_flexible_partial_mint_reduces_principal_and_refunds_lender(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """D13 flexible branch: the refund reduces the principal and is returned to the lender.

    The origination fee stays snapshotted on the ORIGINAL principal even though the stored principal is
    reduced — this is exactly the fee-basis the helper must mirror (`offer_principal=principal`).
    """
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    origination_fee_bps = 100  # 1%
    origination_fee = origination_fee_bps * principal // BPS
    cap = 8 * 10**17  # cap the mint below the full 1e18 -> partial spend
    collateral = _minted(mint_spend, cap=cap)  # == cap
    refund = mint_spend - _spent(collateral)  # 1500e6 - 1200e6 = 300e6
    assert refund > 0  # precondition: partial mint leaves a refund
    new_principal = principal - refund  # lender_refund = min(refund, principal) = refund
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        flexible=True,
        origination_fee_bps=origination_fee_bps,
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)
    acred_lev.set_max_mint_amount(cap)  # force the partial mint
    lender_before = usdc.balanceOf(lender)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    loan = expected_leveraged_loan(
        p2p_usdc_acred,
        signed_offer,
        loan_id,
        borrower,
        lender,
        now,
        principal=new_principal,
        collateral=collateral,
        offer_principal=principal,  # fee basis is the ORIGINAL principal, not the reduced one
    )
    assert loan.origination_fee_amount == origination_fee  # on the original principal, > fee on new_principal
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)
    # lender deployed (principal - origination) to the vault, then got `refund` back -> net new_principal - fee
    assert lender_before - usdc.balanceOf(lender) == new_principal - origination_fee


def test_flexible_partial_mint_preserves_borrower_margin(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """D13 flexible branch: the whole refund goes to the lender; the borrower margin stays as equity."""
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    origination_fee_bps = 100  # 1%
    lender_to_vault = principal - origination_fee_bps * principal // BPS
    borrower_margin = mint_spend - lender_to_vault
    cap = 8 * 10**17
    refund = mint_spend - _spent(_minted(mint_spend, cap=cap))  # 300e6, refund <= principal -> borrower_refund 0
    assert refund <= principal
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        flexible=True,
        origination_fee_bps=origination_fee_bps,
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)
    acred_lev.set_max_mint_amount(cap)
    borrower_before = usdc.balanceOf(borrower)

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer,
        principal,
        _minted(mint_spend, cap=cap),
        kyc_borrower,
        kyc_lender,
        mint_spend,
        0,
        sender=borrower,
    )

    assert borrower_before - usdc.balanceOf(borrower) == borrower_margin  # full margin paid, nothing back


def test_flexible_partial_mint_updates_committed_liquidity(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    cap = 8 * 10**17
    refund = mint_spend - _spent(_minted(mint_spend, cap=cap))  # 300e6
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal, flexible=True
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)
    acred_lev.set_max_mint_amount(cap)
    key = compute_liquidity_key(lender, signed_offer.offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(key) == 0

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer,
        principal,
        _minted(mint_spend, cap=cap),
        kyc_borrower,
        kyc_lender,
        mint_spend,
        0,
        sender=borrower,
    )

    assert p2p_usdc_acred.commited_liquidity(key) == principal - refund  # tracks the reduced principal


# --------------------------------------------------------------------------- FIXED principal, partial mint


def test_fixed_partial_mint_keeps_principal(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, owner, now
):
    """D13 fixed branch: the principal is binding, so the leftover does NOT reduce it; fees nonzero."""
    p2p_usdc_acred.set_protocol_fee(200, 0, sender=owner)  # 2% upfront fee
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    cap = 8 * 10**17
    collateral = _minted(mint_spend, cap=cap)
    origination_fee_bps = 100  # 1%
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        origination_fee_bps=origination_fee_bps,
    )  # fixed offer
    assert signed_offer.offer.principal != 0
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)
    acred_lev.set_max_mint_amount(cap)

    loan_id = p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    # fixed: reconciled principal == original -> offer_principal == principal
    loan = expected_leveraged_loan(
        p2p_usdc_acred, signed_offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.origination_fee_amount == origination_fee_bps * principal // BPS
    assert loan.protocol_upfront_fee_amount == 200 * principal // BPS
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)


def test_fixed_partial_mint_refunds_borrower(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """D13 fixed branch: leftover payment goes to the borrower; the lender deploys principal net of fee."""
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    origination_fee_bps = 100  # 1%
    lender_to_vault = principal - origination_fee_bps * principal // BPS
    borrower_margin = mint_spend - lender_to_vault
    cap = 8 * 10**17
    collateral = _minted(mint_spend, cap=cap)
    refund = mint_spend - _spent(collateral)  # 300e6
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        origination_fee_bps=origination_fee_bps,
    )  # fixed offer
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend, origination_fee_bps=origination_fee_bps)
    acred_lev.set_max_mint_amount(cap)
    vault_addr = p2p_usdc_acred.wallet_to_vault(borrower)
    lender_before, borrower_before = usdc.balanceOf(lender), usdc.balanceOf(borrower)

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer, principal, collateral, kyc_borrower, kyc_lender, mint_spend, 0, sender=borrower
    )

    assert lender_before - usdc.balanceOf(lender) == lender_to_vault  # lender deploys principal net of fee
    assert borrower_before - usdc.balanceOf(borrower) == borrower_margin - refund  # got the leftover back
    assert usdc.balanceOf(vault_addr) == 0  # nothing stuck in the vault


# --------------------------------------------------------------------------- reverts


def test_reverts_if_collateral_lt_offer_min(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """`offer.min_collateral_amount` above the actually-minted collateral reverts in _validate_and_build_loan."""
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)  # 1e18
    min_collateral_amount = 2 * 10**18  # minted collateral falls below the offer floor
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred,
        usdc,
        acred_lev,
        oracle,
        lender,
        borrower,
        lender_key,
        now,
        principal,
        min_collateral_amount=min_collateral_amount,
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)

    with boa.reverts("low collateral amount"):
        p2p_usdc_acred.create_leveraged_loan(
            signed_offer,
            principal,
            collateral,
            kyc_borrower,
            kyc_lender,
            mint_spend,
            0,
            sender=borrower,
        )


def test_reverts_if_minted_lt_min_collateral_out(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """`min_collateral_out` above the swap-calculated DS reverts INSIDE the vault (AcredMock guard)."""
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)  # 1e18
    min_collateral_out = collateral + 1  # one unit above what the swap can mint
    signed_offer = _sign_leveraged_offer(p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal)
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)

    with boa.reverts("ds token amount lt min"):
        p2p_usdc_acred.create_leveraged_loan(
            signed_offer,
            principal,
            collateral,
            kyc_borrower,
            kyc_lender,
            mint_spend,
            min_collateral_out,
            sender=borrower,
        )


def test_reverts_if_zero_principal(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """Flexible offer whose mint is fully refunded leaves no position -> 'zero principal'."""
    principal, mint_spend = 1000 * 10**6, 1000 * 10**6  # mint_spend == principal (origination 0)
    # Cap the mint to ~0 DS so almost the whole mint_spend is refunded (refund >= principal).
    cap = 1  # 1 DS -> spent = 1*num//den = 0, refund = mint_spend
    collateral = _minted(mint_spend, cap=cap)
    refund = mint_spend - _spent(collateral)
    assert refund >= principal  # precondition: lender_refund == principal -> new principal 0
    signed_offer = _sign_leveraged_offer(
        p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal, flexible=True
    )
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)
    acred_lev.set_max_mint_amount(cap)

    with boa.reverts("zero principal"):
        p2p_usdc_acred.create_leveraged_loan(
            signed_offer,
            principal,
            collateral,
            kyc_borrower,
            kyc_lender,
            mint_spend,
            0,
            sender=borrower,
        )


def test_reverts_if_mint_spend_lt_principal(
    p2p_usdc_acred, usdc, acred_lev, oracle, kyc_borrower, kyc_lender, borrower, lender, lender_key, now
):
    """mint_spend below (principal - origination_fee) reverts before any vault interaction."""
    principal, mint_spend = 1000 * 10**6, 1500 * 10**6
    collateral = _minted(mint_spend)
    signed_offer = _sign_leveraged_offer(p2p_usdc_acred, usdc, acred_lev, oracle, lender, borrower, lender_key, now, principal)
    _fund_leveraged(p2p_usdc_acred, usdc, borrower, lender, principal, mint_spend)

    with boa.reverts("mint_spend lt principal"):
        p2p_usdc_acred.create_leveraged_loan(
            signed_offer,
            principal,
            collateral,
            kyc_borrower,
            kyc_lender,
            principal - 1,
            0,
            sender=borrower,
        )
