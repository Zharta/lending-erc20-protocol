"""
Integration tests for leveraged "loop" loans with the real ACRED Securitize DS token via
`create_leveraged_loan` on P2PLendingMultiVaultErc20, against the real ACRED DS token, the
Securitize on-ramp swap and the Chainlink oracle on a mainnet fork.

Leverage flow:
1. The loan vault (P2PLendingVaultSecuritizeMV, MINT_SYNC | REDEEM_MANUAL) is created by the lending
   contract and registered as a Securitize investor via the vault registrar.
2. The lender's principal (minus origination fee) and the borrower's margin
   (`mint_spend - (principal - origination_fee)`) are pulled into the vault.
3. `vault.mint_sync(...)` buys ACRED collateral from the vault's own USDC via the real SecuritizeSwap.
4. The loan is built against the actual minted collateral; fixed principal -> leftover to borrower.

Redeem/settle is manual/async: `redeem()` transfers the redeemed ACRED to the redemption_wallet with
no on-chain USDC payout. USDC proceeds arrive off-chain, simulated by transferring USDC from the
redemption_wallet into the vault before settlement.
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Loan,
    Offer,
    RedeemResult,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_loan_id,
    compute_signed_offer_id,
    get_last_event,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
    sign_redeem_result,
)

BPS = 10000


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture(autouse=True)
def borrower_usdc_funds(borrower, usdc, accounts):
    """Fund the borrower with USDC for the leverage margin (all collateral is minted, so the
    borrower never supplies ACRED of its own)."""
    usdc.transfer(borrower, 500_000 * int(1e6), sender=accounts[1])


@pytest.fixture
def kyc_lender(lender, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender, kyc_validator_contract.address, expiration=now + 86400)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# acred loop ladder: principal borrowed and collateral acquired per iteration, summed into a single
# create_leveraged_loan call (principal = sum(PRINCIPALS), collateral = sum(COLLATERAL_AMOUNTS)).
# Preserves the acred economics: principal ~194.3k USDC against ~261 ACRED, realized LTV ~68%.
PRINCIPALS = [70000000000, 49000000000, 34300000000, 24000000000, 17000000000]
COLLATERAL_AMOUNTS = [94000000, 66000000, 46000000, 32000000, 23000000]


def usdc_to_buy_acred(acred_amount, oracle):
    """USDC (6 dec) needed to buy `acred_amount` ACRED (6 dec) through the Securitize swap.

    The SecuritizeSwap on this fork quotes with zero fee at exactly the oracle rate
    (calculateDsTokenAmount(x) == x * price_den // price_num), so the inverse is the exact USDC cost.
    """
    price_num = oracle.latestRoundData()[1]
    price_den = 10 ** oracle.decimals()
    return acred_amount * price_num // price_den


def acred_from_usdc(usdc_amount, oracle):
    """ACRED (6 dec) obtainable for `usdc_amount` USDC through the swap (zero fee, oracle rate)."""
    price_num = oracle.latestRoundData()[1]
    price_den = 10 ** oracle.decimals()
    return usdc_amount * price_den // price_num


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_leveraged_loan(
    p2p_usdc_acred,
    borrower,
    borrower_account,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    acred,
    oracle_acred_usd,
    set_investor_sig,
):
    """Leveraged loop via create_leveraged_loan with a FIXED-principal offer: borrower supplies a
    USDC margin, lender supplies the principal, together they buy ACRED via the real SecuritizeSwap."""
    collateral_amount = sum(COLLATERAL_AMOUNTS)  # ~261 ACRED bought in one shot
    principal = sum(PRINCIPALS)  # ~194.3k USDC
    mint_spend = usdc_to_buy_acred(collateral_amount, oracle_acred_usd)

    origination_fee_bps = 100  # 1%
    max_iltv = 7000  # realized LTV ~ principal / mint_spend ~ 68%

    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    # 1% buffer below the swap's exact-rate, zero-fee output to absorb integer-division rounding.
    min_collateral_out = collateral_amount * 99 // 100

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=p2p_usdc_acred.payment_token(),
        collateral_token=p2p_usdc_acred.collateral_token(),
        duration=100,
        origination_fee_bps=origination_fee_bps,
        min_collateral_amount=min_collateral_out,
        max_iltv=max_iltv,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acred.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    # Preconditions
    assert usdc.balanceOf(lender) >= principal, "lender needs principal"
    assert usdc.balanceOf(borrower) >= borrower_margin, "borrower needs margin"
    assert mint_spend >= lender_to_vault, "mint_spend must cover lender principal"
    assert borrower_margin > 0, "this must be a leveraged loan (borrower contributes margin)"

    vault_id = p2p_usdc_acred.vault_count(borrower)
    assert vault_id == 0, "precondition: first vault for this borrower"
    vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, vault_id)

    # The borrower authorizes the connector to register its per-loan vault.
    set_investor_sig(borrower_account, now + 3600)

    # Lender approves the lending contract for the principal; borrower for the margin.
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)
    usdc.approve(p2p_usdc_acred.address, borrower_margin, sender=borrower)

    borrower_usdc_before = usdc.balanceOf(borrower)
    lender_usdc_before = usdc.balanceOf(lender)
    borrower_acred_before = acred.balanceOf(borrower)
    protocol_wallet_usdc_before = usdc.balanceOf(p2p_usdc_acred.protocol_wallet())

    now = boa.eval("block.timestamp")

    p2p_usdc_acred.create_leveraged_loan(
        signed_offer,
        principal,
        min_collateral_out,  # collateral_amount arg (loan uses the actual minted amount)
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )

    # Capture events before the getter calls below, which reset boa's per-call log buffer.
    lev_event = get_last_event(p2p_usdc_acred, "LeveragedLoanCreated")
    created = get_last_event(p2p_usdc_acred, "LoanCreated")

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    # ACRED held by the vault is the minted collateral (fixed principal + zero fee -> no refund).
    minted = acred.balanceOf(vault_addr)
    assert minted >= min_collateral_out, "minted collateral below the requested minimum"
    assert usdc.balanceOf(vault_addr) == 0, "no payment should be left in the vault"

    # 1. State: loan hash matches (fixed principal -> loan amount == principal).
    loan = Loan(
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
        collateral_amount=minted,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=origination_fee,
        protocol_upfront_fee_amount=p2p_usdc_acred.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_acred.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acred.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_acred.oracle_addr(),
        initial_ltv=max_iltv,  # fixed offer with max_iltv set -> loan.initial_ltv == max_iltv
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)

    realized_ltv = calc_ltv(principal, minted, usdc, acred, oracle_acred_usd, oracle_reverse=False)
    assert realized_ltv <= max_iltv, "realized LTV must respect the offer cap"

    # 2. Event: LeveragedLoanCreated (sync mint -> pending is False).
    assert lev_event.id == loan_id
    assert lev_event.principal == principal
    assert lev_event.collateral_amount == minted
    assert lev_event.acquired_collateral == minted
    assert lev_event.payment_spent == mint_spend
    assert lev_event.borrower_margin == borrower_margin
    assert lev_event.pending is False
    assert lev_event.mint_deadline == 0  # sync mint -> no pending window

    # 2b. Event: LoanCreated (all fields; expected values from the built loan/offer, not the contract).
    assert created.id == loan_id
    assert created.amount == principal
    assert created.apr == offer.apr
    assert created.payment_token == usdc.address
    assert created.maturity == loan.maturity
    assert created.create_time == now
    assert created.start_time == now
    assert created.borrower == borrower
    assert created.lender == lender
    assert created.collateral_token == acred.address
    assert created.collateral_amount == minted
    assert created.min_collateral_amount == offer.min_collateral_amount
    assert created.call_eligibility == offer.call_eligibility
    assert created.call_window == offer.call_window
    assert created.liquidation_ltv == offer.liquidation_ltv
    assert created.oracle_addr == p2p_usdc_acred.oracle_addr()
    assert created.initial_ltv == max_iltv
    assert created.origination_fee_amount == origination_fee
    assert created.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert created.protocol_settlement_fee == loan.protocol_settlement_fee
    assert created.partial_liquidation_fee == loan.partial_liquidation_fee
    assert created.full_liquidation_fee == loan.full_liquidation_fee
    assert created.offer_id == compute_signed_offer_id(signed_offer)
    assert created.offer_tracing_id == offer.tracing_id
    assert created.oracle_rate_num == oracle_acred_usd.latestRoundData()[1]
    assert created.oracle_rate_den == 10 ** oracle_acred_usd.decimals()
    assert created.vault_id == vault_id
    assert created.vault_addr == vault_addr

    # 3. Balances.
    # Lender deployed principal - origination_fee (origination fee stays with the lender).
    assert usdc.balanceOf(lender) == lender_usdc_before - lender_to_vault
    # Borrower contributed only the margin (no principal handed out).
    assert usdc.balanceOf(borrower) == borrower_usdc_before - borrower_margin
    # Borrower supplied no collateral of its own.
    assert acred.balanceOf(borrower) == borrower_acred_before
    assert acred.balanceOf(vault_addr) == minted
    assert usdc.balanceOf(vault_addr) == 0
    # protocol_upfront_fee == 0 in this market -> protocol wallet unchanged.
    assert usdc.balanceOf(p2p_usdc_acred.protocol_wallet()) == protocol_wallet_usdc_before

    # All USDC that moved came from lender + borrower: (lender_to_vault + borrower_margin) == mint_spend.
    assert lender_to_vault + borrower_margin == mint_spend

    # 4. Committed liquidity == principal (fixed principal).
    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal
    # A second vault was reserved for this borrower.
    assert p2p_usdc_acred.vault_count(borrower) == vault_id + 1


def test_redeem(
    p2p_usdc_acred,
    borrower,
    borrower_account,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    acred,
    oracle_acred_usd,
    redemption_wallet,
    owner_key,
    set_investor_sig,
):
    """Full lifecycle: create_leveraged_loan -> redeem -> settle.

    redeem() transfers the redeemed ACRED to the redemption wallet and keeps the residual in the vault
    with no on-chain USDC payout. USDC proceeds arrive off-chain, simulated by transferring USDC from
    the redemption wallet into the vault before settlement.
    """
    collateral_amount = sum(COLLATERAL_AMOUNTS)
    principal = sum(PRINCIPALS)
    mint_spend = usdc_to_buy_acred(collateral_amount, oracle_acred_usd)

    origination_fee_bps = 0  # keep the settle math clean
    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    min_collateral_out = collateral_amount * 99 // 100
    max_iltv = 7000

    oracle_price_num = oracle_acred_usd.latestRoundData()[1]
    oracle_price_den = 10 ** oracle_acred_usd.decimals()

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=principal,
        apr=0,  # no time-travel below (avoids Chainlink staleness) -> 0 interest
        payment_token=p2p_usdc_acred.payment_token(),
        collateral_token=p2p_usdc_acred.collateral_token(),
        duration=100,
        origination_fee_bps=origination_fee_bps,
        min_collateral_amount=min_collateral_out,
        max_iltv=max_iltv,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acred.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    vault_id = p2p_usdc_acred.vault_count(borrower)
    vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, vault_id)

    # The borrower authorizes the connector to register its per-loan vault.
    set_investor_sig(borrower_account, now + 3600)

    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)
    usdc.approve(p2p_usdc_acred.address, borrower_margin, sender=borrower)

    borrower_acred_before = acred.balanceOf(borrower)
    redemption_wallet_acred_before = acred.balanceOf(redemption_wallet)

    now = boa.eval("block.timestamp")

    # ---------- Step 1: Create the leveraged loan ----------
    p2p_usdc_acred.create_leveraged_loan(
        signed_offer,
        principal,
        min_collateral_out,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))
    minted = acred.balanceOf(vault_addr)

    loan = Loan(
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
        collateral_amount=minted,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=origination_fee,
        protocol_upfront_fee_amount=p2p_usdc_acred.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_acred.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acred.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_acred.oracle_addr(),
        initial_ltv=max_iltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )
    # Precondition: loan is on-chain with the minted collateral in its vault.
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id)
    assert acred.balanceOf(vault_addr) == minted
    assert usdc.balanceOf(vault_addr) == 0

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal

    # ---------- Step 2: Redeem half the collateral ----------
    residual_collateral = minted // 2
    collateral_to_redeem = minted - residual_collateral

    p2p_usdc_acred.redeem(loan, residual_collateral, sender=borrower)
    redeem_event = get_last_event(p2p_usdc_acred, "LoanCollateralRedeemStarted")
    redeem_timestamp = boa.eval("block.timestamp")

    assert redeem_event.loan_id == loan.id
    assert redeem_event.borrower == loan.borrower
    assert redeem_event.lender == loan.lender
    assert redeem_event.collateral_token == loan.collateral_token
    assert redeem_event.vault_id == loan.vault_id
    assert redeem_event.redeem_start == redeem_timestamp
    assert redeem_event.redeem_residual_collateral == residual_collateral

    loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_timestamp,
        redeem_residual_collateral=residual_collateral,
        max_pending_window=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan.id)

    # redeem transfers the redeemed ACRED to the redemption wallet, keeps the residual, no USDC payout.
    assert acred.balanceOf(redemption_wallet) == redemption_wallet_acred_before + collateral_to_redeem
    assert acred.balanceOf(vault_addr) == residual_collateral
    assert acred.balanceOf(borrower) == borrower_acred_before

    # ---------- Step 3: Simulate off-chain redemption proceeds ----------
    # USDC for the redeemed collateral arrives off-chain: transfer its exact-rate, zero-fee swap value
    # from the redemption wallet into the vault.
    redeem_usdc = collateral_to_redeem * oracle_price_num // oracle_price_den
    usdc.transfer(vault_addr, redeem_usdc, sender=redemption_wallet)

    # ---------- Step 4: Settle ----------
    settle_interest = loan.get_interest(boa.eval("block.timestamp"))
    assert settle_interest == 0, "apr=0 and no time-travel -> zero interest"
    settle_protocol_fee = settle_interest * loan.protocol_settlement_fee // BPS

    redeem_result = RedeemResult(
        vault=vault_addr,
        collateral_redeemed=0,
        payment_redeemed=redeem_usdc,
        timestamp=boa.eval("block.timestamp"),
    )
    signed_redeem_result = sign_redeem_result(redeem_result, owner_key)

    in_vault_payment_token = redeem_usdc
    borrower_funds_delta = in_vault_payment_token - (loan.amount + settle_interest)
    if borrower_funds_delta < 0:
        usdc.approve(p2p_usdc_acred.address, -borrower_funds_delta, sender=borrower)

    borrower_balance_before_settle = usdc.balanceOf(borrower)
    lender_balance_before_settle = usdc.balanceOf(lender)
    protocol_wallet_balance_before_settle = usdc.balanceOf(p2p_usdc_acred.protocol_wallet())

    p2p_usdc_acred.settle_loan(loan, signed_redeem_result, sender=borrower)
    settle_event = get_last_event(p2p_usdc_acred, "LoanPaid")

    in_vault_collateral = residual_collateral + redeem_result.collateral_redeemed
    expected_lender_payment = loan.amount + settle_interest - settle_protocol_fee

    # 1. state: loan cleared.
    assert p2p_usdc_acred.loans(loan.id) == ZERO_BYTES32

    # 2. event
    assert settle_event.id == loan.id
    assert settle_event.borrower == loan.borrower
    assert settle_event.lender == loan.lender
    assert settle_event.payment_token == loan.payment_token
    assert settle_event.paid_principal == loan.amount
    assert settle_event.paid_interest == settle_interest
    assert settle_event.origination_fee_amount == loan.origination_fee_amount
    assert settle_event.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert settle_event.protocol_settlement_fee_amount == settle_protocol_fee
    assert settle_event.in_vault_payment_token == in_vault_payment_token
    assert settle_event.in_vault_collateral == in_vault_collateral

    # 3. balances
    assert usdc.balanceOf(vault_addr) == 0
    assert acred.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(lender) == lender_balance_before_settle + expected_lender_payment
    assert usdc.balanceOf(borrower) == borrower_balance_before_settle + borrower_funds_delta
    assert usdc.balanceOf(p2p_usdc_acred.protocol_wallet()) == protocol_wallet_balance_before_settle + settle_protocol_fee
    # Residual collateral returned to the borrower.
    assert acred.balanceOf(borrower) == borrower_acred_before + in_vault_collateral

    # 4. liquidity decremented after settlement.
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == 0
