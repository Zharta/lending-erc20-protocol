"""
Tests for maturity extension functionality in Securitize contracts.

Tests cover:
- extend_loan(): borrower-initiated with lender signature
- extend_loan_lender(): lender-initiated without signature
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    LoanExtensionOffer,
    Offer,
    SecuritizeLoan,
    SignedLoanExtensionOffer,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    get_securitize_loan_mutations,
    replace_namedtuple_field,
    sign_extension_offer,
    sign_offer,
)

BPS = 10000
DAY = 86400


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
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=9000,
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
    now,
    protocol_fees,
    kyc_borrower,
    kyc_lender,
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


@pytest.fixture
def lender_sc_wallet(sc_wallet_contract_def, lender):
    # smart-contract wallet owned by lender_key (owner == lender)
    return sc_wallet_contract_def.deploy(lender)


@pytest.fixture
def kyc_lender_sc_wallet(lender_sc_wallet, kyc_for, kyc_validator_contract):
    return kyc_for(lender_sc_wallet.address, kyc_validator_contract.address)


@pytest.fixture
def ongoing_loan_sc_wallet_lender(
    p2p_usdc_weth,
    usdc,
    weth,
    borrower,
    lender,
    lender_key,
    now,
    oracle,
    protocol_fees,
    kyc_borrower,
    lender_sc_wallet,
    kyc_lender_sc_wallet,
):
    """An ongoing loan whose lender is an ERC-1271 smart-contract wallet (owned by lender_key)."""
    principal = 1000 * 10**6
    collateral_amount = int(1e18)
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=10 * DAY,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=9000,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender_sc_wallet.address,
        borrower=borrower,
        tracing_id=32 * b"\1",
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    lender_approval = principal + (p2p_usdc_weth.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.mint(lender, lender_approval)
    usdc.transfer(lender_sc_wallet.address, lender_approval, sender=lender)
    lender_sc_wallet.approve_erc20(usdc.address, p2p_usdc_weth.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(
        signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender_sc_wallet, sender=borrower
    )

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
        lender=lender_sc_wallet.address,
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
    assert compute_securitize_loan_hash(loan) == p2p_usdc_weth.loans(loan_id)
    return loan


# ============== Tests for extend_loan (borrower-initiated) ==============


def test_extend_loan_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    for corrupted_loan in get_securitize_loan_mutations(loan):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.extend_loan(corrupted_loan, signed_extension, new_maturity, sender=loan.borrower)


def test_extend_loan_reverts_if_not_borrower(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key, lender):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("not borrower"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=lender)


def test_extend_loan_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key, now):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    # Make loan defaulted
    boa.env.time_travel(seconds=loan.maturity - now + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)


def test_extend_loan_reverts_if_offer_not_signed_by_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, borrower_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    # Sign with borrower key instead of lender key
    signed_extension = sign_extension_offer(extension_offer, borrower_key, p2p_usdc_weth.address)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)


# Any nonzero bytecode simulates an EIP-7702 delegation designator. It is NOT a real
# ERC-1271 wallet, so if extend_loan ever routed a 7702-delegated EOA lender down the
# 1271 path it would call isValidSignature on the code and revert. Success proves the
# ecrecover-first branch of _is_extension_offer_signed_by_lender is taken.
EIP7702_CODE = bytes.fromhex("ef01000000000000000000000000000000000000000000")


def test_extend_loan_works_with_7702_delegated_eoa_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key, lender):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    # extension signed by the lender's own ECDSA key
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    # simulate EIP-7702 delegation: lender EOA now has nonzero code
    boa.env.set_code(lender, EIP7702_CODE)
    assert boa.eval(f"{lender}.is_contract")  # precondition: lender has code (7702)

    p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)

    # updated loan hash stored == the ecrecover-first branch accepted the plain ECDSA sig.
    # If it had fallen through to the 1271 path, the staticcall to the non-wallet 7702 code
    # would have reverted instead of updating the loan.
    updated_loan = replace_namedtuple_field(loan, maturity=new_maturity)
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(loan.id)


def test_extend_loan_works_with_sc_wallet_lender(p2p_usdc_weth, ongoing_loan_sc_wallet_lender, lender_key):
    loan = ongoing_loan_sc_wallet_lender
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    # extension signed by the SC wallet owner's key => isValidSignature returns the magic value
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)

    # updated loan hash stored == the ERC-1271 (standard selector) path returned the magic
    # value for the SC-wallet lender and the extension was applied.
    updated_loan = replace_namedtuple_field(loan, maturity=new_maturity)
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(loan.id)


def test_extend_loan_reverts_if_sc_wallet_lender_wrong_signer(p2p_usdc_weth, ongoing_loan_sc_wallet_lender, borrower_key):
    loan = ongoing_loan_sc_wallet_lender
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    # signed by borrower_key, not the SC wallet owner => isValidSignature returns 0x00000000
    signed_extension = sign_extension_offer(extension_offer, borrower_key, p2p_usdc_weth.address)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)


def test_extend_loan_reverts_if_new_maturity_le_current(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity  # Same as current
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("new maturity le current"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)


def test_extend_loan_reverts_if_offer_loan_id_mismatch(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=ZERO_BYTES32,  # Wrong loan ID
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("offer loan id mismatch"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)


def test_extend_loan_reverts_if_offer_maturity_mismatch(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity + 1,  # Wrong maturity
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("offer maturity mismatch"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)


def test_extend_loan_reverts_if_new_maturity_gt_offer(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    offer_new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=offer_new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    # Try to extend more than offer allows
    requested_maturity = offer_new_maturity + 1

    with boa.reverts("new maturity gt offer"):
        p2p_usdc_weth.extend_loan(loan, signed_extension, requested_maturity, sender=loan.borrower)


def test_extend_loan_updates_loan_state(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)

    # Verify loan state updated
    updated_loan = replace_namedtuple_field(loan, maturity=new_maturity)
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(loan.id)


def test_extend_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, lender_key):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.extend_loan(loan, signed_extension, new_maturity, sender=loan.borrower)

    event = get_last_event(p2p_usdc_weth, "LoanMaturityExtended")
    assert event.loan_id == loan.id
    assert event.original_maturity == loan.maturity
    assert event.new_maturity == new_maturity
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.caller == loan.borrower


# ============== Tests for extend_loan_lender (lender-initiated) ==============


def test_extend_loan_lender_reverts_if_loan_invalid(p2p_usdc_weth, ongoing_loan_usdc_weth):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY

    for corrupted_loan in get_securitize_loan_mutations(loan):
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.extend_loan_lender(corrupted_loan, new_maturity, sender=loan.lender)


def test_extend_loan_lender_reverts_if_not_lender(p2p_usdc_weth, ongoing_loan_usdc_weth, borrower):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY

    with boa.reverts("not lender"):
        p2p_usdc_weth.extend_loan_lender(loan, new_maturity, sender=borrower)


def test_extend_loan_lender_reverts_if_loan_defaulted(p2p_usdc_weth, ongoing_loan_usdc_weth, now):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY

    # Make loan defaulted
    boa.env.time_travel(seconds=loan.maturity - now + 1)

    with boa.reverts("loan defaulted"):
        p2p_usdc_weth.extend_loan_lender(loan, new_maturity, sender=loan.lender)


def test_extend_loan_lender_reverts_if_new_maturity_le_current(p2p_usdc_weth, ongoing_loan_usdc_weth):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity  # Same as current

    with boa.reverts("new maturity le current"):
        p2p_usdc_weth.extend_loan_lender(loan, new_maturity, sender=loan.lender)


def test_extend_loan_lender_updates_loan_state(p2p_usdc_weth, ongoing_loan_usdc_weth):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY

    p2p_usdc_weth.extend_loan_lender(loan, new_maturity, sender=loan.lender)

    # Verify loan state updated
    updated_loan = replace_namedtuple_field(loan, maturity=new_maturity)
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(loan.id)


def test_extend_loan_lender_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth):
    loan = ongoing_loan_usdc_weth
    new_maturity = loan.maturity + 10 * DAY

    p2p_usdc_weth.extend_loan_lender(loan, new_maturity, sender=loan.lender)

    event = get_last_event(p2p_usdc_weth, "LoanMaturityExtended")
    assert event.loan_id == loan.id
    assert event.original_maturity == loan.maturity
    assert event.new_maturity == new_maturity
    assert event.borrower == loan.borrower
    assert event.lender == loan.lender
    assert event.caller == loan.lender
