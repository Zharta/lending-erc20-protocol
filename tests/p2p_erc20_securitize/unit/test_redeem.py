import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    SecuritizeLoan,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_securitize_loan_mutations,
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


def test_redeem_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    for loan in get_securitize_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.redeem(loan, 0, sender=ongoing_loan_usdc_weth.borrower)


def test_redeem_reverts_if_redemption_wallet_not_set(p2p_usdc_weth, ongoing_loan_usdc_weth):
    # Set redemption wallet to zero address
    p2p_usdc_weth.set_securitize_redemption_wallet(ZERO_ADDRESS, sender=p2p_usdc_weth.owner())

    with boa.reverts("redemption wallet not set"):
        p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, 0, sender=ongoing_loan_usdc_weth.borrower)


def test_redeem_reverts_if_not_borrower(p2p_usdc_weth, ongoing_loan_usdc_weth, lender):
    with boa.reverts("not borrower"):
        p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, 0, sender=lender)


def test_redeem_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    time_to_default = ongoing_loan_usdc_weth.maturity - now
    boa.env.time_travel(seconds=time_to_default + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, 0, sender=ongoing_loan_usdc_weth.borrower)


def test_redeem_reverts_if_already_redeemed(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    # First redeem
    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, 0, sender=ongoing_loan_usdc_weth.borrower)

    # Update loan with redeem_start
    redeemed_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        redeem_start=now,
        redeem_residual_collateral=0,
    )

    # Try to redeem again
    with boa.reverts("loan already redeemed"):
        p2p_usdc_weth.redeem(redeemed_loan, 0, sender=ongoing_loan_usdc_weth.borrower)


def test_redeem_reverts_if_residual_gt_collateral(p2p_usdc_weth, ongoing_loan_usdc_weth):
    residual_collateral = ongoing_loan_usdc_weth.collateral_amount + 1

    with boa.reverts("residual collateral gt total"):
        p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual_collateral, sender=ongoing_loan_usdc_weth.borrower)


def test_redeem_updates_loan_state(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    residual_collateral = ongoing_loan_usdc_weth.collateral_amount // 2

    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual_collateral, sender=ongoing_loan_usdc_weth.borrower)

    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        redeem_start=now,
        redeem_residual_collateral=residual_collateral,
    )
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id)


def test_redeem_transfers_collateral_to_redemption_wallet(
    p2p_usdc_weth, ongoing_loan_usdc_weth, weth, securitize_redemption_wallet
):
    residual_collateral = ongoing_loan_usdc_weth.collateral_amount // 4
    collateral_to_transfer = ongoing_loan_usdc_weth.collateral_amount - residual_collateral

    # Get the correct vault for this loan's vault_id
    vault_addr = p2p_usdc_weth.vault_id_to_vault(ongoing_loan_usdc_weth.borrower, ongoing_loan_usdc_weth.vault_id)

    redemption_wallet_balance_before = weth.balanceOf(securitize_redemption_wallet)
    vault_balance_before = weth.balanceOf(vault_addr)

    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual_collateral, sender=ongoing_loan_usdc_weth.borrower)

    assert weth.balanceOf(securitize_redemption_wallet) == redemption_wallet_balance_before + collateral_to_transfer
    assert weth.balanceOf(vault_addr) == vault_balance_before - collateral_to_transfer


def test_redeem_with_zero_residual_transfers_all_collateral(
    p2p_usdc_weth, ongoing_loan_usdc_weth, weth, securitize_redemption_wallet
):
    residual_collateral = 0
    collateral_to_transfer = ongoing_loan_usdc_weth.collateral_amount

    # Get the correct vault for this loan's vault_id
    vault_addr = p2p_usdc_weth.vault_id_to_vault(ongoing_loan_usdc_weth.borrower, ongoing_loan_usdc_weth.vault_id)

    redemption_wallet_balance_before = weth.balanceOf(securitize_redemption_wallet)

    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual_collateral, sender=ongoing_loan_usdc_weth.borrower)

    assert weth.balanceOf(securitize_redemption_wallet) == redemption_wallet_balance_before + collateral_to_transfer
    assert weth.balanceOf(vault_addr) == 0


def test_redeem_with_full_residual_transfers_no_collateral(
    p2p_usdc_weth, ongoing_loan_usdc_weth, weth, securitize_redemption_wallet
):
    residual_collateral = ongoing_loan_usdc_weth.collateral_amount

    # Get the correct vault for this loan's vault_id
    vault_addr = p2p_usdc_weth.vault_id_to_vault(ongoing_loan_usdc_weth.borrower, ongoing_loan_usdc_weth.vault_id)

    redemption_wallet_balance_before = weth.balanceOf(securitize_redemption_wallet)
    vault_balance_before = weth.balanceOf(vault_addr)

    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual_collateral, sender=ongoing_loan_usdc_weth.borrower)

    assert weth.balanceOf(securitize_redemption_wallet) == redemption_wallet_balance_before
    assert weth.balanceOf(vault_addr) == vault_balance_before


def test_redeem_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    residual_collateral = ongoing_loan_usdc_weth.collateral_amount // 3

    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual_collateral, sender=ongoing_loan_usdc_weth.borrower)

    event = get_last_event(p2p_usdc_weth, "LoanCollateralRedeemStarted")
    assert event.loan_id == ongoing_loan_usdc_weth.id
    assert event.borrower == ongoing_loan_usdc_weth.borrower
    assert event.lender == ongoing_loan_usdc_weth.lender
    assert event.collateral_token == ongoing_loan_usdc_weth.collateral_token
    assert event.vault_id == ongoing_loan_usdc_weth.vault_id
    assert event.redeem_start == now


def test_redeem_marks_loan_as_redeemed(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    assert not p2p_usdc_weth.is_loan_redeemed(ongoing_loan_usdc_weth)

    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, 0, sender=ongoing_loan_usdc_weth.borrower)

    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        redeem_start=now,
        redeem_residual_collateral=0,
    )
    assert p2p_usdc_weth.is_loan_redeemed(updated_loan)


def test_add_collateral_reverts_after_redeem(p2p_usdc_weth, ongoing_loan_usdc_weth, weth, now):
    # First redeem the loan
    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, 0, sender=ongoing_loan_usdc_weth.borrower)

    # Update loan with redeem_start
    redeemed_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        redeem_start=now,
        redeem_residual_collateral=0,
    )

    # Try to add collateral
    additional_collateral = 1000
    # Get the correct vault for this loan's vault_id
    vault_addr = p2p_usdc_weth.vault_id_to_vault(ongoing_loan_usdc_weth.borrower, ongoing_loan_usdc_weth.vault_id)
    weth.deposit(value=additional_collateral, sender=ongoing_loan_usdc_weth.borrower)
    weth.approve(
        vault_addr,
        additional_collateral,
        sender=ongoing_loan_usdc_weth.borrower,
    )

    with boa.reverts("loan redeemed"):
        p2p_usdc_weth.add_collateral_to_loan(redeemed_loan, additional_collateral, sender=ongoing_loan_usdc_weth.borrower)


def test_remove_collateral_reverts_after_redeem(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    # First redeem the loan with some residual
    residual = ongoing_loan_usdc_weth.collateral_amount // 2
    p2p_usdc_weth.redeem(ongoing_loan_usdc_weth, residual, sender=ongoing_loan_usdc_weth.borrower)

    # Update loan with redeem_start
    redeemed_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        redeem_start=now,
        redeem_residual_collateral=residual,
    )

    # Try to remove collateral
    with boa.reverts("loan redeemed"):
        p2p_usdc_weth.remove_collateral_from_loan(redeemed_loan, 1000, sender=ongoing_loan_usdc_weth.borrower)
