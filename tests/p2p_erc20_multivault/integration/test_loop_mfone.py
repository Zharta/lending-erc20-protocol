"""
Integration tests for leveraged looping with mF-ONE token (Midas Fasanara ONE).
These tests use the actual mF-ONE token, Midas DepositVault, and Chainlink oracle on mainnet fork.

The leveraged loop pattern:
1. Borrower starts with some mfone collateral
2. Flash loan USDC from Balancer
3. Use USDC to buy additional mfone via Midas DepositVault (instant deposit)
4. Create a loan with total collateral (borrower's own + purchased)
5. Loan proceeds (USDC) repay the flash loan
"""

import json

import boa
import pytest
from eth_utils import keccak

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    RedeemResult,
    SecuritizeLoan,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_id,
    compute_securitize_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
    sign_redeem_result,
)

BPS = 10000


# Midas AccessControl at this fork block
MIDAS_DEFAULT_ADMIN = "0x875c06a295c41c27840b9c9dfda7f3d819d8bc6a"
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
def mfone_borrower(mfone, boa_env):
    """Generate a fresh borrower address and fund it with mfone from a known holder."""
    holder = "0x9Db5B0B081E2202fb588cbD541B01b77f45Cfe2d"
    borrower = boa.env.generate_address("mfone_borrower")
    boa.env.set_balance(borrower, 10**21)
    mfone.transfer(borrower, 500 * int(1e18), sender=holder)
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
        midas_vault_impl.address,
        transfer_agent,
        midas_deposit_vault,  # _mint_addr: Midas DepositVault for minting mfone
        redemption_vault,  # _redemption_addr: Midas RedemptionVault
        boa.eval("empty(address)"),  # _vault_registrar_addr: no registrar for mfone
    )


@pytest.fixture
def balancer(boa_env):
    return boa.load_abi("contracts/auxiliary/BalancerFlashLoanProvider.json", name="Balancer").at(
        "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
    )


@pytest.fixture
def midas_proxy_contract_def():
    return boa.load_partial("contracts/MidasProxy.vy")


@pytest.fixture
def midas_proxy(midas_proxy_contract_def, p2p_usdc_mfone, balancer):
    proxy = midas_proxy_contract_def.deploy(p2p_usdc_mfone.address, balancer.address)
    p2p_usdc_mfone.set_proxy_authorization(proxy, True)
    return proxy


@pytest.fixture
def midas_access_control(boa_env):
    """MidasAccessControl contract interface for granting roles."""
    return boa.load_abi("contracts/auxiliary/MidasAccessControl_abi.json", name="MidasAccessControl").at(
        "0x0312A9D1Ff2372DDEdCBB21e4B6389aFc919aC4B"
    )


@pytest.fixture(autouse=True)
def midas_vault_role_for_borrower(p2p_usdc_mfone, mfone_borrower, midas_access_control):
    """Grant GREENLISTED_ROLE to borrower's vault via MidasAccessControl.grantRole.

    Chain: DEFAULT_ADMIN_ROLE -> GREENLIST_OPERATOR_ROLE -> GREENLISTED_ROLE
    """
    boa.env.set_balance(MIDAS_DEFAULT_ADMIN, 10**18)
    midas_access_control.grantRole(GREENLIST_OPERATOR_ROLE, MIDAS_DEFAULT_ADMIN, sender=MIDAS_DEFAULT_ADMIN)
    vault_addr = p2p_usdc_mfone.wallet_to_vault(mfone_borrower)
    midas_access_control.grantRole(GREENLISTED_ROLE, vault_addr, sender=MIDAS_DEFAULT_ADMIN)


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture
def kyc_lender(lender, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender, kyc_validator_contract.address, expiration=now + 86400)


@pytest.fixture
def kyc_borrower_mfone(mfone_borrower, kyc_for, kyc_validator_contract):
    return kyc_for(mfone_borrower, kyc_validator_contract.address)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def max_collateral_to_buy(borrower_collateral: int, ltv: int):
    return borrower_collateral * ltv // (BPS - ltv)


def test_loop(
    p2p_usdc_mfone,
    mfone_borrower,
    lender,
    lender_key,
    kyc_borrower_mfone,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    mfone,
    oracle_mfone_usd,
    midas_proxy,
    midas_deposit_vault,
    balancer,
):
    """
    Leveraged looping test with max_iltv-based offer (principal computed from LTV).
    """
    borrower = mfone_borrower

    oracle_price_num = oracle_mfone_usd.latestRoundData()[1]
    oracle_price_den = 10 ** oracle_mfone_usd.decimals()
    mfone_decimals = 10 ** mfone.decimals()  # 10^18
    usdc_decimals = 10 ** usdc.decimals()  # 10^6

    initial_borrower_collateral = 200 * int(1e18)
    ltv = 6800  # 68% LTV
    # Use 50% of the theoretical max to leave room for the 15% slippage buffer.
    # At 100% of max, principal exactly equals collateral_to_buy_value (no room for buffer).
    collateral_to_buy = max_collateral_to_buy(initial_borrower_collateral, ltv) * 50 // 100
    collateral_amount = initial_borrower_collateral + collateral_to_buy

    # USDC value of collateral_to_buy, accounting for decimal difference (18 vs 6)
    # Add 15% slippage buffer for the Midas DepositVault
    collateral_to_buy_value = (
        collateral_to_buy * oracle_price_num * usdc_decimals * 115 // (oracle_price_den * mfone_decimals * 100)
    )

    # Principal from LTV: collateral_value * ltv / BPS
    principal = collateral_amount * oracle_price_num * ltv * usdc_decimals // (oracle_price_den * mfone_decimals * BPS)
    assert principal > collateral_to_buy_value, "principal must exceed flash loan amount"

    now = boa.eval("block.timestamp")
    offer = Offer(
        max_iltv=ltv,
        payment_token=p2p_usdc_mfone.payment_token(),
        collateral_token=p2p_usdc_mfone.collateral_token(),
        duration=100,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_mfone.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    # Preconditions
    assert mfone.balanceOf(borrower) >= initial_borrower_collateral, "borrower needs enough mfone"
    assert usdc.balanceOf(lender) >= principal, "lender needs enough USDC"
    assert usdc.balanceOf(balancer.address) >= collateral_to_buy_value, "Balancer needs enough USDC for flash loan"

    vault_id = p2p_usdc_mfone.vault_count(borrower)

    # Approvals
    mfone.approve(
        p2p_usdc_mfone.wallet_to_vault(borrower),
        collateral_amount - collateral_to_buy,
        sender=borrower,
    )
    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)
    usdc.approve(midas_proxy.address, collateral_to_buy_value, sender=borrower)

    # Capture before-state
    borrower_collateral_balance_before = mfone.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    now = boa.eval("block.timestamp")

    # Execute leveraged loop
    midas_proxy.create_loan(
        signed_offer,
        principal,
        collateral_amount,
        kyc_borrower,
        kyc_lender,
        collateral_to_buy,
        collateral_to_buy_value,
        oracle_mfone_usd.address,
        midas_deposit_vault,
        sender=borrower,
    )

    # 1. Verify LeveragedLoanCreated event from proxy
    event = get_last_event(midas_proxy, "LeveragedLoanCreated")
    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))
    assert event.loan_id == loan_id
    assert event.p2p_lending_erc20 == p2p_usdc_mfone.address
    assert event.principal == principal
    assert event.loan_collateral_amount == collateral_amount
    assert event.aquired_collateral == collateral_to_buy
    assert event.max_collateral_buy_value == collateral_to_buy_value
    assert event.flash_loan_amount == collateral_to_buy_value

    # Extract actual mfone received from vault's Buy event
    buy_event = get_last_event(midas_proxy, "Buy")
    mfone_received_from_midas = buy_event.mtoken_received
    assert mfone_received_from_midas >= collateral_to_buy, "received less mfone than minimum"

    # 2. Verify collateral in vault
    vault_addr = p2p_usdc_mfone.vault_id_to_vault(borrower, vault_id)
    assert mfone.balanceOf(vault_addr) == collateral_amount

    # 3. Verify borrower mfone balance (vault uses pending_transfers from buy first)
    assert mfone.balanceOf(borrower) == borrower_collateral_balance_before - (collateral_amount - mfone_received_from_midas)

    # 4. Verify borrower USDC balance
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - collateral_to_buy_value - origination_fee

    # 5. Verify lender USDC balance
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    # 6. Verify committed liquidity
    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal

    # 7. Verify loan hash
    initial_ltv_computed = offer.max_iltv
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
        lender=lender,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_mfone.protocol_upfront_fee(),
        protocol_settlement_fee=p2p_usdc_mfone.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_mfone.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_mfone.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_mfone.oracle_addr(),
        initial_ltv=initial_ltv_computed,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id)


def test_redeem(
    p2p_usdc_mfone,
    mfone_borrower,
    lender,
    lender_key,
    kyc_borrower_mfone,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    mfone,
    oracle_mfone_usd,
    midas_proxy,
    midas_deposit_vault,
    balancer,
    redemption_vault,
    owner_key,
):
    """
    Full lifecycle: leveraged loop create -> redeem -> settle.
    """
    borrower = mfone_borrower

    oracle_price_num = oracle_mfone_usd.latestRoundData()[1]
    oracle_price_den = 10 ** oracle_mfone_usd.decimals()
    mfone_decimals = 10 ** mfone.decimals()
    usdc_decimals = 10 ** usdc.decimals()

    # Collateral setup: borrower has 200 mfone, buys 50 more, total 250
    initial_borrower_collateral = 200 * int(1e18)
    collateral_to_buy = 50 * int(1e18)
    collateral_amount = initial_borrower_collateral + collateral_to_buy
    # Add 15% slippage buffer for the Midas DepositVault
    collateral_to_buy_value = (
        collateral_to_buy * oracle_price_num * usdc_decimals * 115 // (oracle_price_den * mfone_decimals * 100)
    )

    # Principal: enough to cover flash loan + some left over
    principal = collateral_amount * oracle_price_num * 7000 // (oracle_price_den * 10**12 * BPS)
    assert principal > collateral_to_buy_value, "principal must exceed flash loan amount"

    now = boa.eval("block.timestamp")
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_mfone.payment_token(),
        collateral_token=p2p_usdc_mfone.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_mfone.address)
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)

    vault_id = p2p_usdc_mfone.vault_count(borrower)

    # Approvals
    mfone.approve(p2p_usdc_mfone.wallet_to_vault(borrower), initial_borrower_collateral, sender=borrower)
    usdc.approve(p2p_usdc_mfone.address, principal, sender=lender)
    usdc.approve(midas_proxy.address, collateral_to_buy_value, sender=borrower)

    borrower_collateral_balance_before = mfone.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    now = boa.eval("block.timestamp")

    # ---------- Step 1: Create loan via leveraged loop ----------
    midas_proxy.create_loan(
        signed_offer,
        principal,
        collateral_amount,
        kyc_borrower,
        kyc_lender,
        collateral_to_buy,
        collateral_to_buy_value,
        oracle_mfone_usd.address,
        midas_deposit_vault,
        sender=borrower,
    )

    loan_id = compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    # Extract actual mfone received from vault's Buy event
    buy_event = get_last_event(midas_proxy, "Buy")
    mfone_received_from_midas = buy_event.mtoken_received
    assert mfone_received_from_midas >= collateral_to_buy, "received less mfone than minimum"

    initial_ltv = calc_ltv(principal, offer.min_collateral_amount, usdc, mfone, oracle_mfone_usd, oracle_reverse=False)
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
        lender=lender,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_mfone.protocol_upfront_fee(),
        protocol_settlement_fee=p2p_usdc_mfone.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_mfone.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_mfone.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_mfone.oracle_addr(),
        initial_ltv=initial_ltv,
        call_time=0,
        vault_id=vault_id,
        redeem_start=0,
        redeem_residual_collateral=0,
    )

    # Precondition: loan created correctly
    assert compute_securitize_loan_hash(loan) == p2p_usdc_mfone.loans(loan_id)

    vault_addr = p2p_usdc_mfone.vault_id_to_vault(borrower, vault_id)
    assert mfone.balanceOf(vault_addr) == collateral_amount

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == principal

    # Track borrower mfone balance after loop (needed for redeem/settle assertions)
    borrower_mfone_after_loop = borrower_collateral_balance_before - (collateral_amount - mfone_received_from_midas)

    # Verify post-loop balances
    assert mfone.balanceOf(borrower) == borrower_mfone_after_loop
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - collateral_to_buy_value - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    # ---------- Step 2: Redeem half the collateral ----------
    residual_collateral = collateral_amount // 2
    collateral_to_redeem = collateral_amount - residual_collateral

    p2p_usdc_mfone.redeem(loan, residual_collateral, sender=borrower)
    redeem_event = get_last_event(p2p_usdc_mfone, "LoanCollateralRedeemStarted")
    redeem_timestamp = boa.eval("block.timestamp")

    # Verify redeem event fields
    assert redeem_event.loan_id == loan.id
    assert redeem_event.borrower == loan.borrower
    assert redeem_event.lender == loan.lender
    assert redeem_event.collateral_token == loan.collateral_token
    assert redeem_event.vault_id == loan.vault_id
    assert redeem_event.redeem_start == redeem_timestamp
    assert redeem_event.redeem_residual_collateral == residual_collateral

    # Update loan struct with redeem state
    loan = replace_namedtuple_field(
        loan,
        redeem_start=redeem_timestamp,
        redeem_residual_collateral=residual_collateral,
    )
    assert compute_securitize_loan_hash(loan) == p2p_usdc_mfone.loans(loan.id)

    # Verify collateral movements from redeem
    assert mfone.balanceOf(vault_addr) == residual_collateral
    assert mfone.balanceOf(borrower) == borrower_mfone_after_loop

    # ---------- Step 3: Redemption proceeds ----------
    # The Midas RedemptionVault (with swapper) burns the redeemed mfone and delivers USDC straight
    # to the vault during redeem(), so the proceeds are already in the vault. The amount is the
    # oracle value of the redeemed collateral less the Midas instant-redeem fee. The vault held no
    # USDC before redeem, so its current USDC balance is exactly the redemption proceeds.
    redeem_usdc = usdc.balanceOf(vault_addr)
    oracle_redeem_usdc = collateral_to_redeem * oracle_price_num * usdc_decimals // (oracle_price_den * mfone_decimals)
    assert 0 < redeem_usdc <= oracle_redeem_usdc, "proceeds must be positive and net of the redeem fee"

    # ---------- Step 4: Settle the loan ----------
    settle_interest = loan.apr * loan.amount * (now - loan.accrual_start_time) // (365 * 86400 * BPS)
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
        usdc.approve(p2p_usdc_mfone.address, -borrower_funds_delta, sender=borrower)

    borrower_balance_before_settle = usdc.balanceOf(borrower)
    lender_balance_before_settle = usdc.balanceOf(lender)
    protocol_wallet_balance_before_settle = usdc.balanceOf(p2p_usdc_mfone.protocol_wallet())

    p2p_usdc_mfone.settle_loan(loan, signed_redeem_result, sender=borrower)
    settle_event = get_last_event(p2p_usdc_mfone, "LoanPaid")

    in_vault_collateral = residual_collateral + redeem_result.collateral_redeemed
    expected_lender_payment = loan.amount + settle_interest - settle_protocol_fee

    if borrower_funds_delta < 0:
        expected_borrower_balance = borrower_balance_before_settle + borrower_funds_delta
    else:
        expected_borrower_balance = borrower_balance_before_settle + borrower_funds_delta

    # 1. state: loan cleared
    assert p2p_usdc_mfone.loans(loan.id) == ZERO_BYTES32

    # 2. event assertions
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

    # 3. balance assertions
    assert usdc.balanceOf(vault_addr) == 0
    assert mfone.balanceOf(vault_addr) == 0
    assert usdc.balanceOf(lender) == lender_balance_before_settle + expected_lender_payment
    assert usdc.balanceOf(borrower) == expected_borrower_balance
    assert usdc.balanceOf(p2p_usdc_mfone.protocol_wallet()) == protocol_wallet_balance_before_settle + settle_protocol_fee

    # Residual collateral returned to borrower
    assert mfone.balanceOf(borrower) == borrower_mfone_after_loop + in_vault_collateral

    # 4. liquidity: committed liquidity decremented after settlement
    assert p2p_usdc_mfone.commited_liquidity(liquidity_key) == 0
