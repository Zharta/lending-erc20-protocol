"""
Integration tests for leveraged "loop" loans with the mF-ONE token (Midas Fasanara ONE), against the
real mF-ONE token, Midas DepositVault and Chainlink oracle on a mainnet fork.

Leverage flow via create_leveraged_loan:
1. The loan vault is created by the lending contract (P2PLendingMultiVaultErc20).
2. The lender's principal (minus origination fee) and the borrower's margin
   (`mint_spend - (principal - origination_fee)`) are pulled into the vault.
3. `vault.mint_sync(...)` mints mF-ONE from the vault's own balance via the real Midas DepositVault.
4. The loan is built against the actual minted collateral; fixed-principal -> leftover to borrower,
   flexible-principal -> principal reduced + lender refunded.
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
    """Fresh borrower address. It supplies a USDC margin (not collateral, all collateral is minted),
    so it only needs ETH for gas and USDC."""
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
    """Grant GREENLISTED_ROLE to the borrower's next loan vault (the CREATE2 address wallet_to_vault
    returns for vault_count == 0). Role chain: DEFAULT_ADMIN_ROLE -> GREENLIST_OPERATOR_ROLE ->
    GREENLISTED_ROLE."""
    boa.env.set_balance(MIDAS_DEFAULT_ADMIN, 10**18)
    midas_access_control.grantRole(GREENLIST_OPERATOR_ROLE, MIDAS_DEFAULT_ADMIN, sender=MIDAS_DEFAULT_ADMIN)
    vault_addr = p2p_usdc_mfone.wallet_to_vault(mfone_borrower)
    midas_access_control.grantRole(GREENLISTED_ROLE, vault_addr, sender=MIDAS_DEFAULT_ADMIN)


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture(autouse=True)
def borrower_usdc_funds(mfone_borrower, usdc, accounts):
    """Fund the borrower with USDC for the leverage margin (all collateral is minted)."""
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
    """Leveraged loop via create_leveraged_loan with a FIXED-principal offer: borrower supplies a USDC
    margin, lender supplies the principal, together they mint mfone via the real Midas DepositVault."""
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

    # Lender approves the lending contract for the principal; borrower for the margin.
    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)
    usdc.approve(p2p_usdc_mfone.address, borrower_margin, sender=borrower)

    borrower_usdc_before = usdc.balanceOf(borrower)
    lender_usdc_before = usdc.balanceOf(lender)
    borrower_mfone_before = mfone.balanceOf(borrower)
    protocol_wallet_usdc_before = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet())

    now = boa.eval("block.timestamp")

    p2p_usdc_mfone.create_leveraged_loan(
        signed_offer,
        principal,
        min_collateral_out,  # collateral_amount arg (loan uses actual minted)
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )

    # Capture events before the getter calls below, which reset boa's per-call log buffer.
    lev_event = get_last_event(p2p_usdc_mfone, "LeveragedLoanCreated")
    created = get_last_event(p2p_usdc_mfone, "LoanCreated")

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    # mfone held by the vault is the minted collateral (mint_sync spends the full mint_spend -> no refund).
    minted = mfone.balanceOf(vault_addr)
    assert minted >= min_collateral_out, "minted collateral below the requested minimum"
    assert usdc.balanceOf(vault_addr) == 0, "no payment should be left in the vault"

    # 1. State: loan hash matches (fixed principal -> new_principal == principal).
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
    assert created.collateral_token == mfone.address
    assert created.collateral_amount == minted
    assert created.min_collateral_amount == offer.min_collateral_amount
    assert created.call_eligibility == offer.call_eligibility
    assert created.call_window == offer.call_window
    assert created.liquidation_ltv == offer.liquidation_ltv
    assert created.oracle_addr == p2p_usdc_mfone.oracle_addr()
    assert created.initial_ltv == max_iltv
    assert created.origination_fee_amount == origination_fee
    assert created.protocol_upfront_fee_amount == loan.protocol_upfront_fee_amount
    assert created.protocol_settlement_fee == loan.protocol_settlement_fee
    assert created.partial_liquidation_fee == loan.partial_liquidation_fee
    assert created.full_liquidation_fee == loan.full_liquidation_fee
    assert created.offer_id == compute_signed_offer_id(signed_offer)
    assert created.offer_tracing_id == offer.tracing_id
    assert created.oracle_rate_num == oracle_mfone_usd.latestRoundData()[1]
    assert created.oracle_rate_den == 10 ** oracle_mfone_usd.decimals()
    assert created.vault_id == vault_id
    assert created.vault_addr == vault_addr

    # 3. Balances.
    # Lender deployed principal - origination_fee (origination fee stays with the lender).
    assert usdc.balanceOf(lender) == lender_usdc_before - lender_to_vault
    # Borrower contributed only the margin (no principal handed out).
    assert usdc.balanceOf(borrower) == borrower_usdc_before - borrower_margin
    # Borrower supplied no collateral of its own.
    assert mfone.balanceOf(borrower) == borrower_mfone_before
    assert mfone.balanceOf(vault_addr) == minted
    assert usdc.balanceOf(vault_addr) == 0
    # protocol_upfront_fee == 0 in this market -> protocol wallet unchanged.
    assert usdc.balanceOf(p2p_usdc_mfone.protocol_wallet()) == protocol_wallet_usdc_before

    # All USDC that moved came from lender + borrower: (lender_to_vault + borrower_margin) == mint_spend.
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
    """Leveraged loop via create_leveraged_loan with a FLEXIBLE-principal offer (offer.principal == 0).
    mint_sync spends the full mint_spend so nothing is refunded and new_principal == requested principal,
    but initial_ltv is computed from (min_collateral_amount, principal) rather than taken from max_iltv."""
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
    protocol_wallet_usdc_before = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet())

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

    # Capture the event before the getter calls below, which reset boa's per-call log buffer.
    lev_event = get_last_event(p2p_usdc_mfone, "LeveragedLoanCreated")

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    minted = mfone.balanceOf(vault_addr)
    assert minted >= min_collateral_out
    # mint_sync spent the full mint_spend -> nothing refunded -> principal unchanged.
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
    assert lev_event.mint_deadline == 0  # sync mint -> no pending window

    # Balances
    assert usdc.balanceOf(lender) == lender_usdc_before - lender_to_vault
    assert usdc.balanceOf(borrower) == borrower_usdc_before - borrower_margin
    assert mfone.balanceOf(borrower) == borrower_mfone_before
    assert mfone.balanceOf(vault_addr) == minted
    assert usdc.balanceOf(vault_addr) == 0
    # protocol_upfront_fee == 0 in this market -> protocol wallet unchanged.
    assert usdc.balanceOf(p2p_usdc_mfone.protocol_wallet()) == protocol_wallet_usdc_before

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

    The Midas vault is REDEEM_SYNC, so redemption and settlement happen atomically via redeem_and_settle
    (no deferred "redeeming" state, no owner-signed RedeemResult). The non-residual collateral is
    converted mfone -> USDC on-chain and the loan is settled from those proceeds: lender is paid
    principal + interest - fee, residual collateral is returned to the borrower, loan is cleared.
    """
    borrower = mfone_borrower

    oracle_price_num = oracle_mfone_usd.latestRoundData()[1]
    oracle_price_den = 10 ** oracle_mfone_usd.decimals()
    mfone_dec = 10 ** mfone.decimals()
    usdc_dec = 10 ** usdc.decimals()

    # Small sizes: the Midas RedemptionVault instant-redeem path is limited at this fork block, so
    # keep the redeemed collateral modest (~125 mfone).
    principal = 130 * usdc_dec
    mint_spend = 260 * usdc_dec
    lender_to_vault = principal  # origination_fee == 0 here
    borrower_margin = mint_spend - lender_to_vault

    expected_mfone = expected_mfone_from_usdc(mint_spend, oracle_mfone_usd, mfone, usdc)
    min_collateral_out = expected_mfone * 80 // 100

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=principal,
        apr=0,  # no time-travel below (avoids Chainlink staleness) -> 0 interest
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
    # Precondition: loan is on-chain with the minted collateral in its vault.
    assert compute_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id)
    assert mfone.balanceOf(vault_addr) == minted

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal

    # ---------- Step 2: Atomically redeem half the collateral AND settle in one tx ----------
    # REDEEM_SYNC markets convert collateral->payment on-chain instantly, so redeem_and_settle does it
    # atomically: no deferred "redeeming" state (redeem_start stays 0), no LoanCollateralRedeemStarted
    # event, no owner-signed RedeemResult. (collateral_amount - residual_collateral) mfone is converted
    # to USDC and the loan is settled from the proceeds like settle_loan.
    residual_collateral = minted // 2
    collateral_to_redeem = minted - residual_collateral

    # Oracle-implied upper bound on the redeem proceeds (actual is net of the Midas redeem fee).
    oracle_redeem_usdc = collateral_to_redeem * oracle_price_num * usdc_dec // (oracle_price_den * mfone_dec)

    # apr=0 and no time-travel -> zero interest -> zero settlement fee.
    settle_interest = loan.get_interest(boa.eval("block.timestamp"))
    assert settle_interest == 0, "apr=0 and no time-travel -> zero interest"
    settle_protocol_fee = settle_interest * loan.protocol_settlement_fee // BPS
    assert settle_protocol_fee == 0

    # Lender is paid principal + interest - fee (independent of the fork's redeem fee).
    expected_lender_payment = loan.amount + settle_interest - settle_protocol_fee  # == principal

    # Proceeds are net of the Midas redeem fee, so they fall just short of the principal and the borrower
    # tops up the shortfall in the same tx. Exact proceeds are only known post-tx, so approve an upper
    # bound: the shortfall is at most (loan.amount + interest) since proceeds are strictly positive.
    usdc.approve(p2p_usdc_mfone.address, loan.amount + settle_interest, sender=borrower)

    borrower_balance_before_settle = usdc.balanceOf(borrower)
    lender_balance_before_settle = usdc.balanceOf(lender)
    protocol_wallet_balance_before_settle = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet())

    p2p_usdc_mfone.redeem_and_settle(loan, residual_collateral, sender=borrower)
    # Capture the event before any further call to the lending contract.
    settle_event = get_last_event(p2p_usdc_mfone, "LoanPaid")

    # 1. state: loan cleared (the flow was atomic, no intermediate "redeeming" state).
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

    # Ground-truth redeem proceeds: sum of every recipient's real balance delta (borrower delta is
    # signed and nets the shortfall top-up). By USDC conservation this equals the redeemed amount,
    # measured from token movements rather than any contract return value.
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
    # Reported in_vault_payment_token must equal the real USDC that moved.
    assert settle_event.in_vault_payment_token == measured_redeemed
    assert settle_event.in_vault_collateral == residual_collateral

    # 4. liquidity decremented after settlement.
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == 0
