import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    RedeemResult,
    SecuritizeLoan,
    SignedRedeemResult,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    replace_namedtuple_field,
    sign_offer,
    sign_redeem_result,
)

BPS = 10000

SEC_REG_ACCREDITED = 2
SEC_REG_APPROVED = 1


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e11))


@pytest.fixture(autouse=True)
def borrower_funds(borrower, usdc):
    usdc.transfer(borrower, int(1e11))


@pytest.fixture
def protocol_fees(p2p_usdc_acred):
    settlement_fee = 1000
    upfront_fee = 11
    p2p_usdc_acred.set_protocol_fee(upfront_fee, settlement_fee, sender=p2p_usdc_acred.owner())
    p2p_usdc_acred.change_protocol_wallet(p2p_usdc_acred.owner(), sender=p2p_usdc_acred.owner())
    return settlement_fee


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def offer_usdc_acred(now, borrower, lender, oracle_acred_usd, lender_key, usdc, acred, p2p_usdc_acred):
    principal = 100 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=acred.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle_acred_usd.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    return sign_offer(offer, lender_key, p2p_usdc_acred.address)


@pytest.fixture
def ongoing_loan_usdc_acred(
    p2p_usdc_acred,
    offer_usdc_acred,
    usdc,
    acred,
    borrower,
    lender,
    lender_key,
    now,
    protocol_fees,
    kyc_borrower,
    kyc_lender,
    oracle_acred_usd,
):
    offer = offer_usdc_acred.offer
    principal = offer.principal
    collateral_amount = 20 * int(1e6)
    lender_approval = principal + (p2p_usdc_acred.protocol_upfront_fee() - offer.origination_fee_bps) * principal // BPS

    vault_id = p2p_usdc_acred.vault_count(borrower)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, lender_approval, sender=lender)

    loan_id = p2p_usdc_acred.create_loan(
        offer_usdc_acred, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower
    )

    loan = SecuritizeLoan(
        id=loan_id,
        offer_id=compute_signed_offer_id(offer_usdc_acred),
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
        protocol_upfront_fee_amount=p2p_usdc_acred.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_acred.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acred.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)
    return loan


def _register_investor(wallet, securitize_registry, securitize_owner, acred_ds_token, token_issuer, now):
    """Register a wallet as a Securitize investor and issue ACRED so the VaultRegistrar can create vaults for it."""
    securitize_registry.updateInvestor(
        f"investor_{wallet[:10]}",
        "",
        "PT",
        [wallet],
        [SEC_REG_ACCREDITED],
        [SEC_REG_APPROVED],
        [now + 86400 * 365],
        sender=securitize_owner,
    )
    acred_ds_token.issueTokens(wallet, 1, sender=token_issuer)


def test_transfer_loan_non_redeemed(
    p2p_usdc_acred,
    ongoing_loan_usdc_acred,
    transfer_agent,
    kyc_for,
    kyc_validator_contract,
    acred,
    usdc,
    borrower,
    securitize_registry,
    securitize_owner,
    now,
    acred_ds_token,
    token_issuer,
):
    """Transfer a non-redeemed loan: collateral moves to new vault, old loan cleared, new loan valid."""
    loan = ongoing_loan_usdc_acred

    old_vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, loan.vault_id)
    old_vault_collateral = acred.balanceOf(old_vault_addr)

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    # Register new_borrower as a Securitize investor so the VaultRegistrar can create vaults for them
    _register_investor(new_borrower, securitize_registry, securitize_owner, acred_ds_token, token_issuer, now)

    p2p_usdc_acred.transfer_loan(loan, new_borrower, new_borrower_kyc, SignedRedeemResult(), sender=transfer_agent)

    event = get_last_event(p2p_usdc_acred, "LoanBorrowerTransferred")

    # Old loan cleared
    assert p2p_usdc_acred.loans(loan.id) == ZERO_BYTES32

    # New loan valid
    updated_loan = replace_namedtuple_field(
        loan,
        borrower=new_borrower,
        id=event.new_loan_id,
        vault_id=0,
    )
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_acred.loans(updated_loan.id)

    # Collateral moved to new vault
    new_vault_addr = p2p_usdc_acred.vault_id_to_vault(new_borrower, 0)
    assert acred.balanceOf(old_vault_addr) == 0
    assert acred.balanceOf(new_vault_addr) == old_vault_collateral

    # Event correct
    assert event.loan_id == loan.id
    assert event.old_borrower == loan.borrower
    assert event.new_borrower == new_borrower
    assert event.lender == loan.lender
    assert event.vault_id == 0


def test_transfer_loan_redeemed(
    p2p_usdc_acred,
    ongoing_loan_usdc_acred,
    transfer_agent,
    kyc_for,
    kyc_validator_contract,
    acred,
    usdc,
    borrower,
    owner_key,
    now,
    securitize_registry,
    securitize_owner,
    acred_ds_token,
    token_issuer,
):
    """Transfer a redeemed loan after redemption concludes: collateral and payment tokens move to new vault."""
    loan = ongoing_loan_usdc_acred
    residual_collateral = loan.collateral_amount // 4
    collateral_redeemed = loan.collateral_amount // 10

    # Start redemption with residual collateral
    p2p_usdc_acred.redeem(loan, residual_collateral, sender=loan.borrower)

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=residual_collateral,
    )

    vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, loan.vault_id)

    # Simulate redemption conclusion: transfer ACRED from borrower to vault
    acred.transfer(vault_addr, collateral_redeemed, sender=borrower)
    payment_redeemed = loan.amount + 100 * 10**6
    usdc.transfer(vault_addr, payment_redeemed, sender=borrower)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=collateral_redeemed,
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    old_vault_collateral = acred.balanceOf(vault_addr)
    old_vault_payment = usdc.balanceOf(vault_addr)
    assert old_vault_collateral == residual_collateral + collateral_redeemed

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    # Register new_borrower as a Securitize investor so the VaultRegistrar can create vaults for them
    _register_investor(new_borrower, securitize_registry, securitize_owner, acred_ds_token, token_issuer, now)

    p2p_usdc_acred.transfer_loan(redeemed_loan, new_borrower, new_borrower_kyc, signed_redeem_result, sender=transfer_agent)

    event = get_last_event(p2p_usdc_acred, "LoanBorrowerTransferred")

    # Old loan cleared
    assert p2p_usdc_acred.loans(redeemed_loan.id) == ZERO_BYTES32

    # New loan valid
    updated_loan = replace_namedtuple_field(
        redeemed_loan,
        borrower=new_borrower,
        id=event.new_loan_id,
        vault_id=0,
    )
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_acred.loans(updated_loan.id)

    # All collateral moved to new vault
    new_vault_addr = p2p_usdc_acred.vault_id_to_vault(new_borrower, 0)
    assert acred.balanceOf(vault_addr) == 0
    assert acred.balanceOf(new_vault_addr) == old_vault_collateral

    # All payment tokens moved to new vault
    assert usdc.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(new_vault_addr) == old_vault_payment

    # Event correct
    assert event.loan_id == redeemed_loan.id
    assert event.old_borrower == redeemed_loan.borrower
    assert event.new_borrower == new_borrower
    assert event.lender == redeemed_loan.lender
    assert event.vault_id == 0
