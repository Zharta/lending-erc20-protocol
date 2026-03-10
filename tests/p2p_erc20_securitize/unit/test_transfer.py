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
    get_securitize_loan_mutations,
    replace_namedtuple_field,
    sign_offer,
    sign_redeem_result,
)

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


# ============================================================================
# REVERT TESTS
# ============================================================================


def test_transfer_loan_reverts_if_loan_invalid(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract
):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    for loan in get_securitize_loan_mutations(ongoing_loan_usdc_weth):
        print(f"{loan=}")
        with boa.reverts("invalid loan"):
            p2p_usdc_weth.transfer_loan(loan, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent)


def test_transfer_loan_reverts_if_not_transfer_agent(p2p_usdc_weth, ongoing_loan_usdc_weth, kyc_for, kyc_validator_contract):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)
    with boa.reverts("not transfer agent"):
        p2p_usdc_weth.transfer_loan(
            ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=boa.env.generate_address()
        )


def test_transfer_loan_reverts_if_redeem_not_concluded(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract, now
):
    """Transfer reverts when loan redemption has started but not concluded."""
    loan = ongoing_loan_usdc_weth

    # Start redemption
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=0,
    )

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    with boa.reverts("redeem not concluded"):
        p2p_usdc_weth.transfer_loan(redeemed_loan, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent)


# ============================================================================
# NON-REDEEMED LOAN TRANSFER TESTS
# ============================================================================


def test_transfer_loan_changes_borrower(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract
):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(
        ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent
    )

    event = get_last_event(p2p_usdc_weth, "LoanBorrowerTransferred")
    updated_loan = replace_namedtuple_field(
        ongoing_loan_usdc_weth,
        borrower=new_borrower,
        id=event.new_loan_id,
        vault_id=0,
    )
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(updated_loan.id)


def test_transfer_loan_clears_old_loan(p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(
        ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent
    )

    assert p2p_usdc_weth.loans(ongoing_loan_usdc_weth.id) == ZERO_BYTES32


def test_transfer_loan_transfers_collateral_to_new_vault(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract, weth, borrower
):
    loan = ongoing_loan_usdc_weth
    old_vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    old_vault_balance = weth.balanceOf(old_vault_addr)

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(
        ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent
    )

    new_vault_addr = p2p_usdc_weth.vault_id_to_vault(new_borrower, 0)
    assert weth.balanceOf(old_vault_addr) == 0
    assert weth.balanceOf(new_vault_addr) == old_vault_balance


def test_transfer_loan_logs_event(p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract):
    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(
        ongoing_loan_usdc_weth, new_borrower, new_borrower_kyc, EMPTY_REDEEM_RESULT, sender=transfer_agent
    )

    event = get_last_event(p2p_usdc_weth, "LoanBorrowerTransferred")
    assert event.loan_id == ongoing_loan_usdc_weth.id
    assert event.old_borrower == ongoing_loan_usdc_weth.borrower
    assert event.new_borrower == new_borrower
    assert event.lender == ongoing_loan_usdc_weth.lender
    assert event.vault_id == 0


# ============================================================================
# REDEEMED LOAN TRANSFER TESTS (redeem concluded)
# ============================================================================


def test_transfer_redeemed_loan_changes_borrower(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract, usdc, now, owner_key, borrower
):
    """Transfer succeeds when loan redemption has fully concluded."""
    loan = ongoing_loan_usdc_weth

    # Start redemption
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=0,
    )

    # Simulate redemption conclusion: deposit payment tokens to vault
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    payment_redeemed = loan.amount + 100 * 10**6
    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(redeemed_loan, new_borrower, new_borrower_kyc, signed_redeem_result, sender=transfer_agent)

    event = get_last_event(p2p_usdc_weth, "LoanBorrowerTransferred")
    updated_loan = replace_namedtuple_field(
        redeemed_loan,
        borrower=new_borrower,
        id=event.new_loan_id,
        vault_id=0,
    )
    assert compute_securitize_loan_hash(updated_loan) == p2p_usdc_weth.loans(updated_loan.id)
    assert p2p_usdc_weth.loans(redeemed_loan.id) == ZERO_BYTES32


def test_transfer_redeemed_loan_transfers_collateral_to_new_vault(
    p2p_usdc_weth,
    ongoing_loan_usdc_weth,
    transfer_agent,
    kyc_for,
    kyc_validator_contract,
    usdc,
    weth,
    now,
    owner_key,
    borrower,
):
    """Residual collateral and redeemed collateral in vault are transferred to the new borrower's vault."""
    loan = ongoing_loan_usdc_weth
    residual_collateral = loan.collateral_amount // 4
    collateral_redeemed = loan.collateral_amount // 10

    # Start redemption with residual collateral
    p2p_usdc_weth.redeem(loan, residual_collateral, sender=loan.borrower)

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=residual_collateral,
    )

    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)

    # Simulate redemption conclusion: Securitize returns some collateral and payment tokens to vault
    weth.deposit(value=collateral_redeemed, sender=borrower)
    weth.transfer(vault_addr, collateral_redeemed, sender=borrower)
    payment_redeemed = loan.amount + 100 * 10**6
    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=collateral_redeemed,
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    old_vault_collateral = weth.balanceOf(vault_addr)
    assert old_vault_collateral == residual_collateral + collateral_redeemed

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(redeemed_loan, new_borrower, new_borrower_kyc, signed_redeem_result, sender=transfer_agent)

    new_vault_addr = p2p_usdc_weth.vault_id_to_vault(new_borrower, 0)
    assert weth.balanceOf(vault_addr) == 0
    assert weth.balanceOf(new_vault_addr) == residual_collateral + collateral_redeemed


def test_transfer_redeemed_loan_transfers_payment_tokens(
    p2p_usdc_weth, ongoing_loan_usdc_weth, transfer_agent, kyc_for, kyc_validator_contract, usdc, now, owner_key, borrower
):
    """Payment tokens in vault are transferred to the new borrower's vault."""
    loan = ongoing_loan_usdc_weth

    # Start redemption
    p2p_usdc_weth.redeem(loan, 0, sender=loan.borrower)

    redeemed_loan = replace_namedtuple_field(
        loan,
        redeem_start=now,
        redeem_residual_collateral=0,
    )

    # Simulate redemption conclusion: deposit payment tokens to vault
    vault_addr = p2p_usdc_weth.vault_id_to_vault(borrower, loan.vault_id)
    payment_redeemed = loan.amount + 100 * 10**6
    usdc.mint(vault_addr, payment_redeemed)

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=payment_redeemed,
        timestamp=now + 1,
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    new_borrower = boa.env.generate_address("new_borrower")
    new_borrower_kyc = kyc_for(new_borrower, kyc_validator_contract.address)

    p2p_usdc_weth.transfer_loan(redeemed_loan, new_borrower, new_borrower_kyc, signed_redeem_result, sender=transfer_agent)

    new_vault_addr = p2p_usdc_weth.vault_id_to_vault(new_borrower, 0)
    assert usdc.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(new_vault_addr) == payment_redeemed
