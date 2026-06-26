"""
Integration tests for leveraged "loop" loans with the mF-ONE token (Midas Fasanara ONE).

These tests use the actual mF-ONE token, Midas DepositVault, and Chainlink oracle on a
mainnet fork.

NEW first-class leverage flow (no proxy, no flash loan):
1. The loan vault is created by the lending contract (P2PLendingMultiVaultErc20).
2. The lender's principal (minus origination fee) is pulled into the loan vault.
3. The borrower's margin (`mint_spend - (principal - origination_fee)`) is pulled into the
   loan vault.
4. `vault.mint_sync(...)` mints mF-ONE collateral straight from the vault's own balance via the
   real Midas DepositVault (instant deposit). No Balancer flash loan, no MidasProxy.
5. The loan is built against the actual minted collateral and the principal is reconciled
   per Decision Log D13 (fixed-principal -> leftover to borrower; flexible-principal ->
   principal reduced + lender refunded).

Driven entirely through `create_leveraged_loan` on the lending contract. The retired
proxy/flash-loan path (`MidasProxy` + Balancer) is intentionally NOT used here.
"""

import boa
import pytest
from eth_utils import keccak

from ..conftest_base import (
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_loan_id,
    compute_signed_offer_id,
    get_last_event,
    sign_kyc,
    sign_offer,
)

BPS = 10000


MIDAS_DEFAULT_ADMIN = "0xd4195CF4df289a4748C1A7B6dDBE770e27bA1227"
MIDAS_DV_ADMIN = "0x2acb4bdcbef02f81bf713b696ac26390d7f79a12"
GREENLISTED_ROLE = keccak(b"GREENLISTED_ROLE")
GREENLIST_OPERATOR_ROLE = keccak(b"GREENLIST_OPERATOR_ROLE")


# ---------------------------------------------------------------------------
# mfone-specific fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mfone(erc20_contract_def, boa_env):
    return erc20_contract_def.at("0x238a700eD6165261Cf8b2e544ba797BC11e466Ba")


@pytest.fixture
def oracle_mfone_usd(oracle_contract_def, boa_env):
    return oracle_contract_def.at("0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C")


@pytest.fixture
def mfone_borrower(boa_env):
    """A fresh borrower address. In the leveraged flow the borrower supplies a USDC margin
    (not collateral) - all collateral is minted - so it only needs ETH for gas and USDC."""
    borrower = boa.env.generate_address("mfone_borrower")
    boa.env.set_balance(borrower, 10**21)
    return borrower


@pytest.fixture
def midas_deposit_vault(boa_env):
    """Midas DepositVault for instant USDC -> mfone deposits."""
    contract_def = boa.load_abi("contracts/auxiliary/Midas_DepositVault_abi.json", name="MidasDepositVault")
    vault = contract_def.at("0x41438435c20B1C2f1fcA702d387889F346A0C3DE")
    vault.setMinMTokenAmountForFirstDeposit(0, sender=MIDAS_DV_ADMIN)
    return vault


@pytest.fixture
def redemption_vault(boa_env):
    """Midas RedemptionVault for mfone -> USDC redemptions."""
    return "0x44b0440e35c596e858cEA433D0d82F5a985fD19C"


@pytest.fixture(scope="session")
def midas_vault_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVaultMidas.vy")


@pytest.fixture
def midas_vault_impl(midas_vault_contract_def):
    return midas_vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_mfone(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    midas_vault_impl,
    usdc,
    mfone,
    oracle_mfone_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
    midas_deposit_vault,
    redemption_vault,
):
    """Multivault market wired with the Midas vault impl (capabilities MINT_SYNC | REDEEM_SYNC),
    so `create_leveraged_loan` resolves to the synchronous mint-and-start path."""
    return p2p_lending_multivault_erc20_contract_def.deploy(
        usdc,
        mfone,
        oracle_mfone_usd,
        False,  # oracle_reverse (mF-ONE/USD oracle is not reversed)
        kyc_validator_contract,
        0,  # protocol_upfront_fee
        0,  # protocol_settlement_fee
        owner,  # protocol_wallet
        10000,  # max_protocol_upfront_fee
        10000,  # max_protocol_settlement_fee
        0,  # partial_liquidation_fee
        0,  # full_liquidation_fee
        p2p_mv_refinance.address,
        p2p_mv_liquidation.address,
        p2p_mv_loan.address,
        midas_vault_impl.address,  # Midas vault impl -> vault_capabilities = MINT_SYNC | REDEEM_SYNC
        transfer_agent,
        midas_deposit_vault,  # _mint_addr: Midas DepositVault for minting mfone
        redemption_vault,  # _redemption_addr: Midas RedemptionVault
        boa.eval("empty(address)"),  # _vault_registrar_addr: no registrar for mfone
        0,  # max_pending_window
    )


@pytest.fixture
def midas_access_control(boa_env):
    """MidasAccessControl contract interface for granting roles."""
    return boa.load_abi("contracts/auxiliary/MidasAccessControl_abi.json", name="MidasAccessControl").at(
        "0x0312A9D1Ff2372DDEdCBB21e4B6389aFc919aC4B"
    )


@pytest.fixture(autouse=True)
def midas_vault_role_for_borrower(p2p_usdc_mfone, mfone_borrower, midas_access_control):
    """Grant GREENLISTED_ROLE to the borrower's (next) loan vault via MidasAccessControl.grantRole.

    The vault that `create_leveraged_loan` creates is the deterministic CREATE2 address for the
    borrower's next vault_id (vault_count == 0), which is exactly what `wallet_to_vault` returns.

    Chain: DEFAULT_ADMIN_ROLE -> GREENLIST_OPERATOR_ROLE -> GREENLISTED_ROLE
    """
    boa.env.set_balance(MIDAS_DEFAULT_ADMIN, 10**18)
    midas_access_control.grantRole(GREENLIST_OPERATOR_ROLE, MIDAS_DEFAULT_ADMIN, sender=MIDAS_DEFAULT_ADMIN)
    vault_addr = p2p_usdc_mfone.wallet_to_vault(mfone_borrower)
    midas_access_control.grantRole(GREENLISTED_ROLE, vault_addr, sender=MIDAS_DEFAULT_ADMIN)


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture(autouse=True)
def borrower_usdc_funds(mfone_borrower, usdc, accounts):
    """Fund the borrower with USDC for the leverage margin (all collateral is minted, so the
    borrower never supplies mfone)."""
    usdc.transfer(mfone_borrower, 500_000 * int(1e6), sender=accounts[0])


@pytest.fixture
def kyc_lender(lender, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender, kyc_validator_contract.address, expiration=now + 86400)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def expected_mfone_from_usdc(usdc_amount, oracle, mfone, usdc):
    """Oracle-implied mfone (18 dec) obtainable for `usdc_amount` USDC (6 dec), ignoring the
    Midas deposit fee/slippage. Used only to size a conservative `min_collateral_out`."""
    price_num = oracle.latestRoundData()[1]
    price_den = 10 ** oracle.decimals()
    mfone_dec = 10 ** mfone.decimals()
    usdc_dec = 10 ** usdc.decimals()
    return usdc_amount * price_den * mfone_dec // (price_num * usdc_dec)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_leveraged_loan_fixed_principal(
    p2p_usdc_mfone,
    mfone_borrower,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    mfone,
    oracle_mfone_usd,
    midas_deposit_vault,
):
    """Leveraged loop via `create_leveraged_loan` with a FIXED-principal offer.

    Borrower supplies a USDC margin, lender supplies the principal; together they mint mfone
    collateral straight through the real Midas DepositVault. No proxy, no flash loan.
    """
    borrower = mfone_borrower

    usdc_dec = 10 ** usdc.decimals()

    principal = 50_000 * usdc_dec
    mint_spend = 100_000 * usdc_dec  # lender principal + borrower margin routed to the mint
    origination_fee_bps = 100  # 1%
    max_iltv = 7000  # generous cap; realized LTV ~ principal / minted_value ~ 50%

    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    # Conservative min collateral: 80% of the oracle-implied amount leaves room for the Midas fee.
    expected_mfone = expected_mfone_from_usdc(mint_spend, oracle_mfone_usd, mfone, usdc)
    min_collateral_out = expected_mfone * 80 // 100

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=p2p_usdc_mfone.payment_token(),
        collateral_token=p2p_usdc_mfone.collateral_token(),
        duration=100,
        origination_fee_bps=origination_fee_bps,
        min_collateral_amount=min_collateral_out,
        max_iltv=max_iltv,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_mfone.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    # Preconditions
    assert usdc.balanceOf(lender) >= principal, "lender needs principal"
    assert usdc.balanceOf(borrower) >= borrower_margin, "borrower needs margin"
    assert mint_spend >= lender_to_vault, "mint_spend must cover lender principal"
    assert borrower_margin > 0, "this must be a leveraged loan (borrower contributes margin)"

    vault_id = p2p_usdc_mfone.vault_count(borrower)
    assert vault_id == 0, "precondition: first vault for this borrower"
    vault_addr = p2p_usdc_mfone.vault_id_to_vault(borrower, vault_id)

    # Approvals: lender approves the LENDING CONTRACT for the principal; borrower for the margin.
    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)
    usdc.approve(p2p_usdc_mfone.address, borrower_margin, sender=borrower)

    # Capture before-state
    borrower_usdc_before = usdc.balanceOf(borrower)
    lender_usdc_before = usdc.balanceOf(lender)
    borrower_mfone_before = mfone.balanceOf(borrower)
    protocol_wallet_usdc_before = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet())

    now = boa.eval("block.timestamp")

    # ---- Execute the leveraged loop directly on the lending contract ----
    p2p_usdc_mfone.create_leveraged_loan(
        signed_offer,
        principal,
        min_collateral_out,  # collateral_amount arg (unused by the facet; loan uses actual minted)
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )

    # Capture events immediately: boa's get_logs returns logs from the most recent call to the
    # contract, and the assertions below make further (getter) calls to the lending contract.
    lev_event = get_last_event(p2p_usdc_mfone, "LeveragedLoanCreated")
    created = get_last_event(p2p_usdc_mfone, "LoanCreated")

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    # The mfone physically held by the loan vault IS the minted collateral (refund is 0 because
    # mint_sync spends the full mint_spend). This is the ground-truth collateral amount.
    minted = mfone.balanceOf(vault_addr)
    assert minted >= min_collateral_out, "minted collateral below the requested minimum"
    assert usdc.balanceOf(vault_addr) == 0, "no payment should be left in the vault"

    # 1. State: loan hash matches the expected Loan (fixed principal -> new_principal == principal).
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
        protocol_upfront_fee_amount=p2p_usdc_mfone.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_mfone.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_mfone.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_mfone.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_mfone.oracle_addr(),
        initial_ltv=max_iltv,  # fixed offer with max_iltv set -> loan.initial_ltv == max_iltv
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id)

    # Realized LTV must be within the cap (re-checked by the contract; assert it here too).
    realized_ltv = calc_ltv(principal, minted, usdc, mfone, oracle_mfone_usd, oracle_reverse=False)
    assert realized_ltv <= max_iltv, "realized LTV must respect the offer cap"

    # 2. Event: LeveragedLoanCreated (sync mint -> pending is False).
    assert lev_event.id == loan_id
    assert lev_event.principal == principal
    assert lev_event.collateral_amount == minted
    assert lev_event.acquired_collateral == minted
    assert lev_event.payment_spent == mint_spend
    assert lev_event.borrower_margin == borrower_margin
    assert lev_event.pending is False

    # 2b. Event: LoanCreated mirrors the started loan.
    assert created.id == loan_id
    assert created.amount == principal
    assert created.collateral_amount == minted
    assert created.borrower == borrower
    assert created.lender == lender
    assert created.start_time == now
    assert created.create_time == now
    assert created.vault_id == vault_id
    assert created.vault_addr == vault_addr
    assert created.collateral_token == mfone.address
    assert created.payment_token == usdc.address
    assert created.origination_fee_amount == origination_fee
    assert created.initial_ltv == max_iltv

    # 3. Balances.
    # Lender deployed (principal - origination_fee); the origination fee stays with the lender.
    assert usdc.balanceOf(lender) == lender_usdc_before - lender_to_vault
    # Borrower contributed only the margin (no principal handed out - this is leverage).
    assert usdc.balanceOf(borrower) == borrower_usdc_before - borrower_margin
    # Borrower supplied NO collateral of its own.
    assert mfone.balanceOf(borrower) == borrower_mfone_before
    # Vault holds exactly the minted collateral, no leftover payment token.
    assert mfone.balanceOf(vault_addr) == minted
    assert usdc.balanceOf(vault_addr) == 0
    # protocol_upfront_fee == 0 in this market -> protocol wallet unchanged.
    assert usdc.balanceOf(p2p_usdc_mfone.protocol_wallet()) == protocol_wallet_usdc_before

    # NO flash lender / proxy involved: the only USDC that moved came from the lender + borrower,
    # and it is fully accounted for by (lender_to_vault + borrower_margin) == mint_spend.
    assert lender_to_vault + borrower_margin == mint_spend

    # 4. Committed liquidity == principal (fixed principal).
    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal
    # A second vault was reserved for this borrower.
    assert p2p_usdc_mfone.vault_count(borrower) == vault_id + 1


def test_create_leveraged_loan_flexible_principal(
    p2p_usdc_mfone,
    mfone_borrower,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    mfone,
    oracle_mfone_usd,
    midas_deposit_vault,
):
    """Leveraged loop via `create_leveraged_loan` with a FLEXIBLE-principal offer
    (offer.principal == 0). The mint_sync spends the full mint_spend so nothing is refunded;
    new_principal therefore equals the requested principal, but the loan's initial_ltv is
    computed from (min_collateral_amount, principal) rather than taken from max_iltv.
    """
    borrower = mfone_borrower

    usdc_dec = 10 ** usdc.decimals()

    principal = 50_000 * usdc_dec
    mint_spend = 100_000 * usdc_dec
    origination_fee_bps = 0  # keep flexible-principal math clean

    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    expected_mfone = expected_mfone_from_usdc(mint_spend, oracle_mfone_usd, mfone, usdc)
    min_collateral_out = expected_mfone * 80 // 100

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=0,  # FLEXIBLE
        apr=1000,
        payment_token=p2p_usdc_mfone.payment_token(),
        collateral_token=p2p_usdc_mfone.collateral_token(),
        duration=100,
        origination_fee_bps=origination_fee_bps,
        min_collateral_amount=min_collateral_out,
        max_iltv=0,  # -> initial_ltv computed from (min_collateral_amount, principal)
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_mfone.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    # Preconditions
    assert usdc.balanceOf(lender) >= principal
    assert usdc.balanceOf(borrower) >= borrower_margin
    assert borrower_margin > 0, "leveraged loan: borrower contributes margin"

    vault_id = p2p_usdc_mfone.vault_count(borrower)
    assert vault_id == 0
    vault_addr = p2p_usdc_mfone.vault_id_to_vault(borrower, vault_id)

    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)
    usdc.approve(p2p_usdc_mfone.address, borrower_margin, sender=borrower)

    borrower_usdc_before = usdc.balanceOf(borrower)
    lender_usdc_before = usdc.balanceOf(lender)
    borrower_mfone_before = mfone.balanceOf(borrower)

    now = boa.eval("block.timestamp")

    p2p_usdc_mfone.create_leveraged_loan(
        signed_offer,
        principal,
        min_collateral_out,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )

    # Capture the event immediately (subsequent getter calls to the lending contract would
    # otherwise clear boa's per-call log buffer).
    lev_event = get_last_event(p2p_usdc_mfone, "LeveragedLoanCreated")

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    minted = mfone.balanceOf(vault_addr)
    assert minted >= min_collateral_out
    # mint_sync spent the full mint_spend, so nothing was refunded -> principal is unchanged.
    assert usdc.balanceOf(vault_addr) == 0, "no refund expected; new_principal == principal"

    # Flexible offer with max_iltv == 0: loan.initial_ltv is derived from min_collateral_amount.
    expected_initial_ltv = calc_ltv(principal, min_collateral_out, usdc, mfone, oracle_mfone_usd, oracle_reverse=False)

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
        protocol_upfront_fee_amount=p2p_usdc_mfone.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_mfone.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_mfone.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_mfone.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_mfone.oracle_addr(),
        initial_ltv=expected_initial_ltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id)

    # Event
    assert lev_event.id == loan_id
    assert lev_event.principal == principal  # no refund -> new_principal == principal
    assert lev_event.collateral_amount == minted
    assert lev_event.acquired_collateral == minted
    assert lev_event.payment_spent == mint_spend
    assert lev_event.borrower_margin == borrower_margin
    assert lev_event.pending is False

    # Balances
    assert usdc.balanceOf(lender) == lender_usdc_before - lender_to_vault
    assert usdc.balanceOf(borrower) == borrower_usdc_before - borrower_margin
    assert mfone.balanceOf(borrower) == borrower_mfone_before
    assert mfone.balanceOf(vault_addr) == minted
    assert usdc.balanceOf(vault_addr) == 0

    # Committed liquidity == new_principal == principal.
    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal


def test_leveraged_loan_redeem_and_settle(
    p2p_usdc_mfone,
    mfone_borrower,
    lender,
    lender_key,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    mfone,
    oracle_mfone_usd,
    midas_deposit_vault,
):
    """Full lifecycle on the atomic REDEEM_SYNC path: create_leveraged_loan -> redeem_and_settle.

    The Midas vault is REDEEM_SYNC, so redemption and settlement happen atomically in a single tx
    via `redeem_and_settle` (no deferred "redeeming" state, no owner-signed RedeemResult). The
    non-residual collateral is converted mfone -> USDC on-chain and the loan is settled from those
    proceeds: the lender is paid principal + interest - fee, the residual collateral is returned to
    the borrower, and the loan is cleared.
    """
    borrower = mfone_borrower

    oracle_price_num = oracle_mfone_usd.latestRoundData()[1]
    oracle_price_den = 10 ** oracle_mfone_usd.decimals()
    mfone_dec = 10 ** mfone.decimals()
    usdc_dec = 10 ** usdc.decimals()

    # Small sizes: the Midas RedemptionVault instant-redeem path is limited at this fork block, so
    # keep the redeemed collateral modest (the retired proxy lifecycle test redeemed ~125 mfone).
    principal = 130 * usdc_dec
    mint_spend = 260 * usdc_dec
    lender_to_vault = principal  # origination_fee == 0 here
    borrower_margin = mint_spend - lender_to_vault

    expected_mfone = expected_mfone_from_usdc(mint_spend, oracle_mfone_usd, mfone, usdc)
    min_collateral_out = expected_mfone * 80 // 100

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=principal,
        apr=0,  # no time-travel below (avoids Chainlink staleness on the fork) -> 0 interest
        payment_token=p2p_usdc_mfone.payment_token(),
        collateral_token=p2p_usdc_mfone.collateral_token(),
        duration=100,
        min_collateral_amount=min_collateral_out,
        max_iltv=7000,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_mfone.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    vault_id = p2p_usdc_mfone.vault_count(borrower)
    vault_addr = p2p_usdc_mfone.vault_id_to_vault(borrower, vault_id)

    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)
    usdc.approve(p2p_usdc_mfone.address, borrower_margin, sender=borrower)

    borrower_mfone_before = mfone.balanceOf(borrower)

    now = boa.eval("block.timestamp")

    # ---------- Step 1: Create the leveraged loan ----------
    p2p_usdc_mfone.create_leveraged_loan(
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
    minted = mfone.balanceOf(vault_addr)

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
        origination_fee_amount=0,
        protocol_upfront_fee_amount=0,
        protocol_settlement_fee=p2p_usdc_mfone.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_mfone.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_mfone.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_mfone.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )
    # Precondition: leverage-created loan is on-chain with the minted collateral in its vault.
    assert compute_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id)
    assert mfone.balanceOf(vault_addr) == minted

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal

    # ---------- Step 2: Atomically redeem half the collateral AND settle in one tx ----------
    # REDEEM_SYNC (Midas) markets convert collateral->payment on-chain and instantly, so redemption
    # and settlement happen atomically via `redeem_and_settle`: there is NO deferred "redeeming"
    # state (redeem_start stays 0), NO LoanCollateralRedeemStarted event, and NO owner-signed
    # RedeemResult. redeem_sync converts (collateral_amount - residual_collateral) mfone -> USDC and
    # the loan is settled from those proceeds exactly like settle_loan.
    residual_collateral = minted // 2
    collateral_to_redeem = minted - residual_collateral

    # Oracle-implied upper bound on the redeem proceeds (actual is net of the Midas redeem fee).
    oracle_redeem_usdc = collateral_to_redeem * oracle_price_num * usdc_dec // (oracle_price_den * mfone_dec)

    # Interest/fee are independent: apr=0 and no time-travel -> zero interest -> zero settlement fee.
    settle_interest = loan.get_interest(boa.eval("block.timestamp"))
    assert settle_interest == 0, "apr=0 and no time-travel -> zero interest"
    settle_protocol_fee = settle_interest * loan.protocol_settlement_fee // BPS
    assert settle_protocol_fee == 0

    # Lender is paid principal + interest - fee (all independent of the fork's redeem fee).
    expected_lender_payment = loan.amount + settle_interest - settle_protocol_fee  # == principal

    # The redeem proceeds are net of the Midas redeem fee, so they fall just short of the principal
    # and the borrower must top up the shortfall inside the same tx. The exact proceeds are only
    # known post-tx (the flow is atomic), so approve an upper bound: the shortfall is at most
    # (loan.amount + interest) because the proceeds are strictly positive.
    usdc.approve(p2p_usdc_mfone.address, loan.amount + settle_interest, sender=borrower)

    borrower_balance_before_settle = usdc.balanceOf(borrower)
    lender_balance_before_settle = usdc.balanceOf(lender)
    protocol_wallet_balance_before_settle = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet())

    p2p_usdc_mfone.redeem_and_settle(loan, residual_collateral, sender=borrower)
    # Capture the facet-emitted event immediately, before any further call to the lending contract.
    settle_event = get_last_event(p2p_usdc_mfone, "LoanPaid")

    # 1. state: loan cleared (no intermediate "redeeming" state existed - it was atomic).
    assert p2p_usdc_mfone.loans(loan.id) == ZERO_BYTES32

    # 3. balances.
    # Vault fully drained: redeemed USDC withdrawn, residual collateral returned.
    assert usdc.balanceOf(vault_addr) == 0
    assert mfone.balanceOf(vault_addr) == 0
    # Lender received exactly principal + interest - protocol fee (independent exact value).
    assert usdc.balanceOf(lender) == lender_balance_before_settle + expected_lender_payment
    # Protocol fee == 0 in this market -> protocol wallet unchanged.
    assert usdc.balanceOf(p2p_usdc_mfone.protocol_wallet()) == protocol_wallet_balance_before_settle + settle_protocol_fee
    # Residual collateral returned to the borrower (independent exact value).
    assert mfone.balanceOf(borrower) == borrower_mfone_before + residual_collateral

    # Ground-truth redeem proceeds: the total USDC dispensed by the settlement equals the sum of
    # every recipient's REAL balance delta (the borrower delta is signed and nets the shortfall
    # top-up). By USDC conservation this sum equals exactly the redeemed amount, measured from real
    # token movements rather than any contract return value.
    lender_delta = usdc.balanceOf(lender) - lender_balance_before_settle
    borrower_delta = usdc.balanceOf(borrower) - borrower_balance_before_settle
    protocol_delta = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet()) - protocol_wallet_balance_before_settle
    measured_redeemed = lender_delta + borrower_delta + protocol_delta
    assert 0 < measured_redeemed <= oracle_redeem_usdc, "proceeds must be positive and net of the redeem fee"

    # 2. event.
    assert settle_event.id == loan.id
    assert settle_event.borrower == loan.borrower
    assert settle_event.lender == loan.lender
    assert settle_event.payment_token == loan.payment_token
    assert settle_event.paid_principal == loan.amount
    assert settle_event.paid_interest == settle_interest
    assert settle_event.origination_fee_amount == loan.origination_fee_amount
    assert settle_event.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert settle_event.protocol_settlement_fee_amount == settle_protocol_fee
    # The contract's reported in_vault_payment_token must equal the real USDC that moved.
    assert settle_event.in_vault_payment_token == measured_redeemed
    assert settle_event.in_vault_collateral == residual_collateral

    # 4. liquidity decremented after settlement.
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == 0
