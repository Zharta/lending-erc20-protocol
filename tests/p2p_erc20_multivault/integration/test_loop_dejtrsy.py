"""Integration tests for the ASYNC (Centrifuge ERC-7540) leveraged-loan lifecycle of
`P2PLendingMultiVaultErc20`, driven against the REAL deJTRSY/USDC AsyncVault on an ETHEREUM MAINNET fork.

This is the deJTRSY-on-Ethereum honest sibling of `test_loop_dejaaa.py`: it exercises the SAME
`P2PLendingVaultCentrifugeAsync` impl and the SAME chain-neutral `centrifuge_*` fulfilment recipe, against
a DIFFERENT real Centrifuge V3 pool (deJTRSY) on the same Ethereum fork. deJTRSY shares the identical
Centrifuge V3 deployment as deJAAA — same AsyncRequestManager / spoke / root addresses, and the vault is
the same fully-async AsyncVault implementation (identical runtime bytecode, differing only in its embedded
pool-id / scid immutables) — so the fulfilment / whitelisting recipe is reused verbatim; only the token /
vault / pool-id / scid / oracle and the (live-read) restriction hook differ.

Everything async is otherwise only unit-tested against `CentrifugeAsyncVaultMock`. These fork tests validate
the assumptions a mock can't: real Centrifuge V3 fulfilment semantics (a three-message ApprovedDeposits ->
IssuedShares -> FulfilledDepositRequest relay), request-id-0-per-controller, share-token restriction-hook
membership, and — the single biggest deviation from the mock — that ERC-7887 cancellation is processed
SYNCHRONOUSLY by the AsyncRequestManager on Ethereum (the cancel is claimable in the same tx the vault
requests it, so `cancel_pending_loan` / `cancel_redeem` need only two back-to-back calls, with NO issuer
step between).

Fulfilment is impersonated at the Centrifuge SPOKE via the manager's `callback(...)` (see the dejtrsy_*
fixtures below + the centrifuge_fulfill_* / centrifuge_whitelist helpers in conftest.py and the agent-memory
note `despxa-centrifuge-fork` for the full recipe). This runs on the dir's shared mainnet fork block
(ETH_FORK_BLOCK). deJTRSY's restriction hook is DIFFERENT from deJAAA's, so the hook is read live via
`share.hook()` (never a hardcoded address).

boa quirk: events must be read IMMEDIATELY after the tx that emits them — any subsequent call (even a
view getter) resets boa's last computation and get_logs returns []. The create tests capture their
events first, then run the state/balance assertions.

Sizing note: the deJTRSY oracle is 18-decimal here (the live CentrifugeOracleAdapter reports 18).
deJTRSY ~1.029 USDC. All collateral / mint_spend amounts are derived from the real oracle rate and the
AsyncVault's convertToShares so realized LTV lands under the offer cap. The ACTUAL minted collateral (a hair
below the fulfilled shares, from claim-side rounding) is read as ground truth from
`dejtrsy.balanceOf(vault_addr)` after start_loan, exactly like the dejaaa suite reads its minted amount.
"""

import boa
import pytest

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
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
)
from .conftest import (
    centrifuge_fulfill_deposit,
    centrifuge_fulfill_redeem,
    centrifuge_whitelist,
)

BPS = 10000
EMPTY_MINT_RESULT = ((boa.eval("empty(address)"), 0, 0, 0), (0, 0, 0))
EMPTY_REDEEM_RESULT = ((boa.eval("empty(address)"), 0, 0, 0), (0, 0, 0))
TARGET_LTV = 6800  # realized LTV we size collateral for (well under the 8000 offer cap)
MAX_ILTV = 8000

# --- deJTRSY (Ethereum mainnet) constants -----------------------------------------------------------
DEJTRSY = "0xA6233014B9b7aaa74f38fa1977ffC7A89642dC72"  # Centrifuge share token (collateral, 18 dec)
DEJTRSY_ASYNC_VAULT = "0x18Ab9fC0B2e4Fef9e0e03c8EC63BA287a3238257"  # deJTRSY/USDC ERC-7540 AsyncVault
DEJTRSY_MANAGER = "0xF48256AbDDf96EcDDc4B3DbD23E8C1921f9761Ae"  # AsyncRequestManager (same addr as deJAAA)
DEJTRSY_SPOKE = "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"  # warded on the manager -> impersonate to fulfil
DEJTRSY_ROOT = "0x7Ed48C31f2fdC40d37407cBaBf0870B2b688368f"  # warded on the hook -> impersonate to whitelist
DEJTRSY_ORACLE = "0xB3fa00f2F9DD20E5503bB1EBe398074eAbf418d9"  # CentrifugeOracleAdapter deJTRSY/USD (18 dec)
DEJTRSY_USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
DEJTRSY_POOL_ID = 281474976710660
DEJTRSY_SCID = bytes.fromhex("00010000000000040000000000000001")


# --- deJTRSY fixtures (real deployed handles bound under the dir's Ethereum fork env) -----------------


@pytest.fixture
def dejtrsy_keeper(accounts, borrower, lender):
    """A non-borrower keeper used to prove permissionless start / post-window cancel paths."""
    keeper = accounts[5]
    assert keeper not in {borrower, lender}
    return keeper


@pytest.fixture
def dejtrsy_token(centrifuge_share_token_contract_def, boa_env):
    return centrifuge_share_token_contract_def.at(DEJTRSY)


@pytest.fixture
def dejtrsy_oracle(oracle_contract_def, boa_env):
    return oracle_contract_def.at(DEJTRSY_ORACLE)


@pytest.fixture
def dejtrsy_async_vault(centrifuge_async_vault_contract_def, boa_env):
    """The real deJTRSY/USDC ERC-7540 AsyncVault."""
    return centrifuge_async_vault_contract_def.at(DEJTRSY_ASYNC_VAULT)


@pytest.fixture
def dejtrsy_manager(centrifuge_manager_contract_def, boa_env):
    return centrifuge_manager_contract_def.at(DEJTRSY_MANAGER)


@pytest.fixture
def dejtrsy_hook(centrifuge_hook_contract_def, dejtrsy_token):
    """The share token's CURRENTLY active restriction hook (read `share.hook()` live — deJTRSY's is a
    DIFFERENT hook than deJAAA's). Exposes updateMember for whitelisting the loan vault."""
    return centrifuge_hook_contract_def.at(dejtrsy_token.hook())


@pytest.fixture
def dejtrsy_asset_id(centrifuge_spoke_contract_def, boa_env):
    return centrifuge_spoke_contract_def.at(DEJTRSY_SPOKE).assetToId(DEJTRSY_USDC, 0)


@pytest.fixture
def centrifuge_async_vault_impl(centrifuge_async_vault_impl_contract_def, boa_env):
    """The P2PLendingVaultCentrifugeAsync impl (the code under test), deployed under the Ethereum fork env."""
    return centrifuge_async_vault_impl_contract_def.deploy()


@pytest.fixture
def p2p_usdc_dejtrsy(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    centrifuge_async_vault_impl,
    kyc_validator_contract,
    owner,
    transfer_agent,
    boa_env,
):
    """Centrifuge async (ERC-7540) market wired to the REAL deJTRSY AsyncVault (Ethereum mainnet).

    The AsyncVault is BOTH mint_addr and redemption_addr (D24). max_pending_window (50s) < the async
    offers' 100s duration (D30). All fees start at zero; individual tests bump them.
    """
    return p2p_lending_multivault_erc20_contract_def.deploy(
        DEJTRSY_USDC,  # payment_token
        DEJTRSY,  # collateral_token
        DEJTRSY_ORACLE,  # oracle_addr
        False,  # oracle_reverse
        kyc_validator_contract,  # kyc_validator_addr
        0,  # protocol_upfront_fee
        0,  # protocol_settlement_fee
        owner,  # protocol_wallet
        10000,  # max_protocol_upfront_fee
        10000,  # max_protocol_settlement_fee
        0,  # partial_liquidation_fee
        0,  # full_liquidation_fee
        p2p_mv_refinance.address,  # refinance_addr
        p2p_mv_liquidation.address,  # liquidation_addr
        p2p_mv_loan.address,  # loan_addr
        centrifuge_async_vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        DEJTRSY_ASYNC_VAULT,  # mint_addr (D24: the Centrifuge AsyncVault)
        DEJTRSY_ASYNC_VAULT,  # redemption_addr (D24)
        boa.eval("empty(address)"),  # vault_registrar_addr
        50,  # max_pending_window (< the async offers' 100s duration, D30)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _size_leverage(principal, oracle, async_vault):
    """Return (collateral, mint_spend) that realize ~TARGET_LTV against the real oracle + AsyncVault price.

    collateral is chosen so `calc_ltv(principal, collateral) == TARGET_LTV`; mint_spend is the USDC needed
    to acquire that many deJTRSY shares at the vault's convertToShares rate (zero-fee, oracle-rate on-ramp).
    """
    rate = oracle.latestRoundData()[1]
    odec = 10 ** oracle.decimals()
    collateral = principal * BPS * odec * (10**18) // (TARGET_LTV * rate * (10**6))
    shares_per_usdc = async_vault.convertToShares(10**6)
    mint_spend = collateral * 10**6 // shares_per_usdc
    return collateral, mint_spend


def _sign_centrifuge_offer(p2p, lender, lender_key, borrower, now, *, principal, min_collateral, origination_fee_bps=0):
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=p2p.payment_token(),
        collateral_token=p2p.collateral_token(),
        duration=100,
        origination_fee_bps=origination_fee_bps,
        min_collateral_amount=min_collateral,
        max_iltv=MAX_ILTV,
        available_liquidity=principal,
        expiration=now + 10**6,
        lender=lender,
        borrower=borrower,
    )
    return offer, sign_offer(offer, lender_key, p2p.address)


def _expected_pending_loan(p2p, signed_offer, offer, loan_id, borrower, lender, now, *, principal, collateral):
    """The Loan an async create_leveraged_loan stores while PENDING (start_time == 0)."""
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
        start_time=0,
        accrual_start_time=now,
        borrower=borrower,
        lender=lender,
        collateral_amount=collateral,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p.protocol_settlement_fee(),
        partial_liquidation_fee=p2p.partial_liquidation_fee(),
        full_liquidation_fee=p2p.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p.oracle_addr(),
        initial_ltv=MAX_ILTV,
        call_time=0,
        vault_id=0,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=p2p.max_pending_window(),
    )


# ---------------------------------------------------------------------------
# 1. Full happy path: create (pending) -> fulfil -> start (keeper) -> settle
# ---------------------------------------------------------------------------


def test_create_start_and_settle_async_loan(
    p2p_usdc_dejtrsy,
    borrower,
    lender,
    lender_key,
    dejtrsy_keeper,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    dejtrsy_token,
    dejtrsy_oracle,
    dejtrsy_async_vault,
    dejtrsy_hook,
    dejtrsy_manager,
    dejtrsy_asset_id,
):
    p2p, dejtrsy, oracle = p2p_usdc_dejtrsy, dejtrsy_token, dejtrsy_oracle
    keeper = dejtrsy_keeper

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, dejtrsy_async_vault)
    min_collateral_out = collateral * 97 // 100
    origination_fee = 0  # keep settle math clean (apr>0 but no time-travel -> interest 0)
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_centrifuge_offer(
        p2p, lender, lender_key, borrower, now, principal=principal, min_collateral=min_collateral_out
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    # Preconditions
    assert borrower_margin > 0, "must be a leveraged loan (borrower contributes margin)"
    assert p2p.vault_count(borrower) == 0, "first vault for this borrower"
    vault_addr = p2p.vault_id_to_vault(borrower, 0)

    # Fund lender (principal) + borrower (margin); the loan vault must be whitelisted before requestDeposit.
    usdc.transfer(lender, mint_spend, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.transfer(borrower, borrower_margin, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(dejtrsy_hook, DEJTRSY, vault_addr, DEJTRSY_ROOT)

    lender_usdc_before = usdc.balanceOf(lender)
    borrower_usdc_before = usdc.balanceOf(borrower)

    # ---- create_leveraged_loan (async -> PENDING) ----
    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )
    # Events must be read IMMEDIATELY after the create tx: any later call on `p2p` — including the view
    # getters inside _expected_pending_loan — resets boa's last computation and get_logs returns [].
    created_event = get_last_event(p2p, "LoanCreated")
    leveraged_event = get_last_event(p2p, "LeveragedLoanCreated")

    assert loan_id == compute_loan_id(borrower, lender, now, compute_signed_offer_id(signed_offer))

    # State: PENDING loan stored (start_time == 0), collateral == the caller's estimate. This loan-hash
    # check independently pins EVERY field of the created loan (principal, fees, maturity, collateral,
    # initial_ltv, window).
    pending = _expected_pending_loan(
        p2p, signed_offer, offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert compute_loan_hash(pending) == p2p.loans(loan_id)

    # Events (D31): LoanCreated with start_time == 0 marks the loan pending; collateral is the caller's
    # estimate until LoanStarted reports the actual minted amount.
    assert created_event.id == loan_id
    assert created_event.amount == principal
    assert created_event.start_time == 0
    assert created_event.create_time == pending.create_time
    assert created_event.maturity == pending.maturity
    assert created_event.borrower == borrower
    assert created_event.lender == lender
    assert created_event.collateral_token == dejtrsy.address
    assert created_event.collateral_amount == collateral
    assert created_event.min_collateral_amount == min_collateral_out
    assert created_event.offer_id == pending.offer_id
    assert created_event.vault_id == 0
    assert created_event.vault_addr == vault_addr
    assert leveraged_event.id == loan_id
    assert leveraged_event.principal == principal
    assert leveraged_event.collateral_amount == collateral
    assert leveraged_event.acquired_collateral == 0
    assert leveraged_event.payment_spent == mint_spend
    assert leveraged_event.borrower_margin == borrower_margin
    assert leveraged_event.pending is True
    assert leveraged_event.mint_deadline == pending.create_time + pending.max_pending_window

    # Balances: lender + borrower funds moved into the AsyncVault's global escrow (nothing left in loan vault).
    assert usdc.balanceOf(lender) == lender_usdc_before - lender_to_vault
    assert usdc.balanceOf(borrower) == borrower_usdc_before - borrower_margin
    assert usdc.balanceOf(vault_addr) == 0, "funds routed to the Centrifuge escrow, not the loan vault"
    assert dejtrsy.balanceOf(vault_addr) == 0, "no shares until the deposit settles and the loan starts"
    assert dejtrsy_async_vault.pendingDepositRequest(0, vault_addr) == mint_spend

    # Liquidity: full principal committed.
    liquidity_key = compute_liquidity_key(lender, offer.tracing_id)
    assert p2p.commited_liquidity(liquidity_key) == principal
    assert p2p.vault_count(borrower) == 1

    # ---- issuer fulfils the deposit ----
    shares = dejtrsy_async_vault.convertToShares(mint_spend)
    centrifuge_fulfill_deposit(
        dejtrsy_manager, DEJTRSY_POOL_ID, DEJTRSY_SCID, dejtrsy_asset_id, vault_addr, mint_spend, shares, DEJTRSY_SPOKE
    )
    assert dejtrsy_async_vault.pendingDepositRequest(0, vault_addr) == 0
    assert dejtrsy_async_vault.claimableDepositRequest(0, vault_addr) > 0

    # ---- start_loan by a NON-borrower keeper (permissionless, D20) ----
    assert keeper != borrower
    p2p.start_loan(pending, EMPTY_MINT_RESULT, 0, sender=keeper)
    started_event = get_last_event(p2p, "LoanStarted")
    start_time = boa.eval("block.timestamp")

    # The ACTUAL minted collateral now backs the loan (ground truth from the vault balance).
    minted = dejtrsy.balanceOf(vault_addr)
    assert minted >= min_collateral_out, "minted below the offer's minimum"
    realized_ltv = calc_ltv(principal, minted, usdc, dejtrsy, oracle, oracle_reverse=False)
    assert realized_ltv <= MAX_ILTV, "realized LTV must respect the cap"

    started = pending._replace(start_time=start_time, initial_amount=principal, collateral_amount=minted)
    assert compute_loan_hash(started) == p2p.loans(loan_id)

    assert started_event.id == loan_id
    assert started_event.borrower == borrower
    assert started_event.lender == lender
    assert started_event.start_time == start_time
    assert started_event.maturity == started.maturity
    assert started_event.collateral_amount == minted
    assert started_event.caller == keeper

    # ---- redeem the whole collateral, fulfil the redemption, settle ----
    p2p.redeem(started, 0, sender=borrower)
    redeem_start = boa.eval("block.timestamp")
    redeeming = replace_namedtuple_field(started, redeem_start=redeem_start, redeem_residual_collateral=0)
    assert compute_loan_hash(redeeming) == p2p.loans(loan_id)
    assert dejtrsy_async_vault.pendingRedeemRequest(0, vault_addr) == minted
    assert dejtrsy.balanceOf(vault_addr) == 0, "shares moved into the redeem request"

    redeem_assets = dejtrsy_async_vault.convertToAssets(minted)  # USDC the issuer settles the redeem for
    centrifuge_fulfill_redeem(
        dejtrsy_manager, DEJTRSY_POOL_ID, DEJTRSY_SCID, dejtrsy_asset_id, vault_addr, minted, redeem_assets, DEJTRSY_SPOKE
    )
    # The redemption is now claimable (the exact claimable shares differ from `minted` by a few wei due to
    # the manager's redeemPrice rounding; settle claims whatever is claimable and pays out `redeem_assets`).
    assert dejtrsy_async_vault.pendingRedeemRequest(0, vault_addr) == 0
    assert dejtrsy_async_vault.claimableRedeemRequest(0, vault_addr) > 0

    interest = redeeming.get_interest(boa.eval("block.timestamp"))
    assert interest == 0, "apr>0 but no time-travel -> zero interest, so settle math stays exact"
    protocol_fee = interest * redeeming.protocol_settlement_fee // BPS  # == 0
    expected_lender_payment = redeeming.amount + interest - protocol_fee

    lender_before_settle = usdc.balanceOf(lender)
    borrower_before_settle = usdc.balanceOf(borrower)
    protocol_before_settle = usdc.balanceOf(p2p.protocol_wallet())

    p2p.settle_loan(redeeming, EMPTY_REDEEM_RESULT, sender=borrower)
    paid_event = get_last_event(p2p, "LoanPaid")

    # State: loan cleared, liquidity released, no residual anything in the vault.
    assert p2p.loans(loan_id) == ZERO_BYTES32
    assert p2p.commited_liquidity(liquidity_key) == 0
    assert usdc.balanceOf(vault_addr) == 0
    assert dejtrsy.balanceOf(vault_addr) == 0
    assert dejtrsy_async_vault.claimableRedeemRequest(0, vault_addr) == 0, "the redemption was actually claimed"

    # The ACTUAL claimed proceeds are ground truth (the manager's redeemPrice rounds the claim a hair below
    # convertToAssets, and being an on-chain claim it can't be predicted exactly); measure it from the event
    # and bound it against the estimate. Every other leg (lender payment, surplus, fee) is exact off it.
    claimed_usdc = paid_event.in_vault_payment_token
    assert 0 < claimed_usdc <= redeem_assets
    assert redeem_assets - claimed_usdc <= 2, "claim rounding is at most a couple wei off convertToAssets"
    surplus = claimed_usdc - redeeming.amount - interest
    assert surplus > 0, "redeemed value exceeds principal -> borrower gets a surplus"

    # Event: LoanPaid with the claimed proceeds.
    assert paid_event.id == loan_id
    assert paid_event.borrower == borrower
    assert paid_event.lender == lender
    assert paid_event.paid_principal == redeeming.amount
    assert paid_event.paid_interest == interest
    assert paid_event.protocol_settlement_fee_amount == protocol_fee
    assert paid_event.in_vault_collateral == 0

    # Balances: lender made whole, borrower keeps the surplus, protocol takes its (zero) fee.
    # Conservation: lender payment + protocol fee + borrower surplus == the claimed proceeds.
    assert usdc.balanceOf(lender) == lender_before_settle + expected_lender_payment
    assert usdc.balanceOf(borrower) == borrower_before_settle + surplus
    assert usdc.balanceOf(p2p.protocol_wallet()) == protocol_before_settle + protocol_fee
    assert expected_lender_payment + protocol_fee + surplus == claimed_usdc, "USDC conservation"
    assert dejtrsy.balanceOf(borrower) == 0, "no residual collateral to return"


# ---------------------------------------------------------------------------
# 2. Cancel a pending (unfilled) loan — liquidation-style USDC waterfall
# ---------------------------------------------------------------------------


def test_cancel_pending_unfilled_loan(
    p2p_usdc_dejtrsy,
    borrower,
    lender,
    lender_key,
    dejtrsy_keeper,
    owner,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    dejtrsy_oracle,
    dejtrsy_async_vault,
    dejtrsy_hook,
):
    """Create -> cancel_pending_loan (deposit never filled). On the REAL manager the ERC-7887 cancellation
    is SYNCHRONOUS: the phase-1 call that submits it also makes it claimable, so the immediately-following
    call runs the D27 liquidation-style USDC waterfall and clears the loan. Nonzero origination + settlement
    + full-liquidation fees make the money math real; a keeper drives it post-window (permissionless, D18).
    """
    p2p, oracle = p2p_usdc_dejtrsy, dejtrsy_oracle
    keeper = dejtrsy_keeper

    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, dejtrsy_async_vault)
    min_collateral_out = collateral * 97 // 100
    origination_fee_bps = 100  # 1% -> lender never deploys the origination fee
    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_centrifuge_offer(
        p2p,
        lender,
        lender_key,
        borrower,
        now,
        principal=principal,
        min_collateral=min_collateral_out,
        origination_fee_bps=origination_fee_bps,
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    vault_addr = p2p.vault_id_to_vault(borrower, 0)
    usdc.transfer(lender, mint_spend, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.transfer(borrower, borrower_margin, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(dejtrsy_hook, DEJTRSY, vault_addr, DEJTRSY_ROOT)

    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )
    loan = _expected_pending_loan(
        p2p, signed_offer, offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert loan.full_liquidation_fee == 500  # snapshotted onto the loan
    assert loan.protocol_settlement_fee == 1000
    assert loan.origination_fee_amount == origination_fee
    assert compute_loan_hash(loan) == p2p.loans(loan_id)

    # Precondition: the full mint_spend is sitting in the escrow as a pending, unfulfilled deposit.
    assert dejtrsy_async_vault.pendingDepositRequest(0, vault_addr) == mint_spend

    # Past the pending window -> a keeper may cancel (D18).
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)
    assert keeper not in {borrower, lender, owner}

    # Phase 1: submit the cancel. On the real manager this ALSO makes it claimable in the same tx.
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is False
    assert dejtrsy_async_vault.pendingDepositRequest(0, vault_addr) == 0
    assert dejtrsy_async_vault.claimableCancelDepositRequest(0, vault_addr) == mint_spend

    # Waterfall legs (D27): keeper fee -> protocol fee on interest -> lender recovery -> borrower surplus.
    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    lender_deployed = loan.amount - loan.origination_fee_amount
    debt = lender_deployed + interest
    keeper_fee = debt * loan.full_liquidation_fee // BPS
    protocol_fee = interest * loan.protocol_settlement_fee // BPS
    lender_recovery = debt - protocol_fee
    borrower_surplus = mint_spend - keeper_fee - lender_recovery - protocol_fee
    assert lender_deployed < loan.amount, "the origination-fee term actually bites"
    assert keeper_fee > 0
    assert borrower_surplus > 0, "margin covers the debt -> borrower keeps a surplus"

    keeper_before = usdc.balanceOf(keeper)
    lender_before = usdc.balanceOf(lender)
    borrower_before = usdc.balanceOf(borrower)
    protocol_before = usdc.balanceOf(p2p.protocol_wallet())

    # Phase 3: cancel completes (claim the reclaimed payment, run the waterfall, clear the loan).
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True
    cancelled_event = get_last_event(p2p, "PendingLoanCancelled")

    assert cancelled_event.id == loan_id
    assert cancelled_event.borrower == borrower
    assert cancelled_event.lender == lender
    assert cancelled_event.payment_refunded == mint_spend
    assert cancelled_event.caller == keeper

    assert usdc.balanceOf(keeper) == keeper_before + keeper_fee
    assert usdc.balanceOf(lender) == lender_before + lender_recovery
    assert usdc.balanceOf(borrower) == borrower_before + borrower_surplus
    assert usdc.balanceOf(p2p.protocol_wallet()) == protocol_before + protocol_fee
    assert keeper_fee + lender_recovery + protocol_fee + borrower_surplus == mint_spend, "USDC conservation"

    assert p2p.loans(loan_id) == ZERO_BYTES32
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == 0
    assert usdc.balanceOf(vault_addr) == 0


# ---------------------------------------------------------------------------
# 3. Force-unwind (D28): a fulfilled deposit that can't start -> share-denominated split
# ---------------------------------------------------------------------------


def test_force_unwind_fulfilled_below_min_collateral(
    p2p_usdc_dejtrsy,
    borrower,
    lender,
    lender_key,
    dejtrsy_keeper,
    owner,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    dejtrsy_token,
    dejtrsy_oracle,
    dejtrsy_async_vault,
    dejtrsy_hook,
    dejtrsy_manager,
    dejtrsy_asset_id,
):
    """A deposit that FILLS but below the offer's min_collateral_amount: start_loan reverts "low collateral
    amount"; the fulfilled ERC-7540 request can't be cancelled, so cancel_pending_loan force-unwinds by
    claiming the shares and splitting them oracle-valued, liquidation-style. All legs are paid in deJTRSY
    SHARES (not USDC). Every share leg is computed independently from the real oracle rate.
    """
    p2p, dejtrsy, oracle = p2p_usdc_dejtrsy, dejtrsy_token, dejtrsy_oracle
    keeper = dejtrsy_keeper

    p2p.set_full_liquidation_fee(500, sender=owner)
    p2p.set_protocol_fee(0, 1000, sender=owner)

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, dejtrsy_async_vault)
    # The offer demands the full estimate but the issuer will fill ~80% -> below min, not startable.
    min_collateral_out = collateral
    origination_fee_bps = 100
    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_centrifuge_offer(
        p2p,
        lender,
        lender_key,
        borrower,
        now,
        principal=principal,
        min_collateral=min_collateral_out,
        origination_fee_bps=origination_fee_bps,
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    vault_addr = p2p.vault_id_to_vault(borrower, 0)
    usdc.transfer(lender, mint_spend, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.transfer(borrower, borrower_margin, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(dejtrsy_hook, DEJTRSY, vault_addr, DEJTRSY_ROOT)

    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )
    loan = _expected_pending_loan(
        p2p, signed_offer, offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    assert compute_loan_hash(loan) == p2p.loans(loan_id)

    # Issuer fulfils the deposit fully (request_pending -> 0) but issues only 80% of the shares: below the
    # offer's min_collateral (== the full estimate, so start is blocked), yet the collateral value still
    # exceeds the debt -> a COVERED force-unwind that pays every waterfall leg.
    low_shares = dejtrsy_async_vault.convertToShares(mint_spend) * 80 // 100
    centrifuge_fulfill_deposit(
        dejtrsy_manager, DEJTRSY_POOL_ID, DEJTRSY_SCID, dejtrsy_asset_id, vault_addr, mint_spend, low_shares, DEJTRSY_SPOKE
    )
    assert dejtrsy_async_vault.pendingDepositRequest(0, vault_addr) == 0
    assert dejtrsy_async_vault.claimableDepositRequest(0, vault_addr) > 0

    # Precondition: start_loan is blocked because the claimable fill is below min_collateral_amount.
    with boa.reverts("low collateral amount"):
        p2p.start_loan(loan, EMPTY_MINT_RESULT, 0, sender=keeper)

    # cancel_pending_loan force-unwinds: claim the shares and split them oracle-valued, in SHARES.
    # The exact minted SHARE amount that claim_mint yields (deposit(claimableDeposit) -> shares) is a
    # manager-priced on-chain quantity, not predictable from the claimable ASSETS pre-tx; take it as ground
    # truth from the captured PendingLoanLiquidated.collateral_claimed, then recompute every split leg from
    # THAT with the exact integer math the contract uses (base.cancel_pending_loan force-unwind branch).
    rate_num = oracle.latestRoundData()[1]
    rate_den = 10 ** oracle.decimals()
    payment_dec = 10 ** usdc.decimals()
    collateral_dec = 10 ** dejtrsy.decimals()

    def shares_to_value(sh):
        return sh * rate_num * payment_dec // (rate_den * collateral_dec)

    def value_to_shares(v):
        return v * rate_den * collateral_dec // (rate_num * payment_dec)

    keeper_before = dejtrsy.balanceOf(keeper)
    lender_before = dejtrsy.balanceOf(lender)
    borrower_before = dejtrsy.balanceOf(borrower)
    protocol_before = dejtrsy.balanceOf(p2p.protocol_wallet())

    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)  # keeper (permissionless) drives the unwind
    interest = loan.get_capped_interest(boa.eval("block.timestamp"))
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is True
    liq_event = get_last_event(p2p, "PendingLoanLiquidated")

    minted = liq_event.collateral_claimed  # ground-truth minted shares actually claimed
    lender_deployed = loan.amount - loan.origination_fee_amount
    debt = lender_deployed + interest
    minted_value = shares_to_value(minted)
    liquidation_fee_value = min(debt * loan.full_liquidation_fee // BPS, minted_value)
    value_after_fee = minted_value - liquidation_fee_value
    protocol_fee_value = min(loan.protocol_settlement_fee * interest // BPS, value_after_fee)
    liquidation_fee_shares = value_to_shares(liquidation_fee_value)
    protocol_fee_shares = value_to_shares(protocol_fee_value)
    if value_after_fee >= debt:
        lender_shares = value_to_shares(debt - protocol_fee_value)
        borrower_shares = minted - liquidation_fee_shares - protocol_fee_shares - lender_shares
    else:
        lender_shares = minted - liquidation_fee_shares - protocol_fee_shares
        borrower_shares = 0
    # Preconditions on the SCENARIO: a covered force-unwind that pays every leg (keeper + protocol + lender
    # + borrower surplus). minted_value (~80% of the collateral) comfortably exceeds the debt.
    assert minted >= 10**18, "claimed a meaningful share amount"
    assert value_after_fee >= debt, "covered force-unwind (minted value >> debt)"
    assert liquidation_fee_shares > 0
    assert borrower_shares > 0

    # Event: every split leg matches the independent computation.
    assert liq_event.id == loan_id
    assert liq_event.borrower == borrower
    assert liq_event.lender == lender
    assert liq_event.lender_amount == lender_shares
    assert liq_event.liquidation_fee == liquidation_fee_shares
    assert liq_event.protocol_fee == protocol_fee_shares
    assert liq_event.borrower_amount == borrower_shares
    assert liq_event.caller == keeper

    # Balances: legs paid in deJTRSY shares, plus share conservation.
    assert dejtrsy.balanceOf(keeper) == keeper_before + liquidation_fee_shares
    assert dejtrsy.balanceOf(lender) == lender_before + lender_shares
    assert dejtrsy.balanceOf(p2p.protocol_wallet()) == protocol_before + protocol_fee_shares
    assert dejtrsy.balanceOf(borrower) == borrower_before + borrower_shares
    assert liquidation_fee_shares + lender_shares + protocol_fee_shares + borrower_shares == minted

    assert p2p.loans(loan_id) == ZERO_BYTES32
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == 0
    assert dejtrsy.balanceOf(vault_addr) == 0


# ---------------------------------------------------------------------------
# 4. Async redeem lifecycle: settle blocked until the redemption is fulfilled
# ---------------------------------------------------------------------------


def test_async_redeem_blocks_settle_until_fulfilled(
    p2p_usdc_dejtrsy,
    borrower,
    lender,
    lender_key,
    dejtrsy_keeper,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    dejtrsy_token,
    dejtrsy_oracle,
    dejtrsy_async_vault,
    dejtrsy_hook,
    dejtrsy_manager,
    dejtrsy_asset_id,
):
    """A started loan is put into redemption; settle_loan reverts "redeem not settled" until the issuer
    fulfils the ERC-7540 redemption, then settle claims the proceeds on-chain (empty SignedRedeemResult).
    Keeps a residual so the collateral-return leg is exercised too.
    """
    p2p, dejtrsy, oracle = p2p_usdc_dejtrsy, dejtrsy_token, dejtrsy_oracle
    keeper = dejtrsy_keeper

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, dejtrsy_async_vault)
    min_collateral_out = collateral * 97 // 100
    borrower_margin = mint_spend - principal

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_centrifuge_offer(
        p2p, lender, lender_key, borrower, now, principal=principal, min_collateral=min_collateral_out
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    vault_addr = p2p.vault_id_to_vault(borrower, 0)
    usdc.transfer(lender, mint_spend, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.transfer(borrower, borrower_margin, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(dejtrsy_hook, DEJTRSY, vault_addr, DEJTRSY_ROOT)

    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )
    pending = _expected_pending_loan(
        p2p, signed_offer, offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )

    centrifuge_fulfill_deposit(
        dejtrsy_manager,
        DEJTRSY_POOL_ID,
        DEJTRSY_SCID,
        dejtrsy_asset_id,
        vault_addr,
        mint_spend,
        dejtrsy_async_vault.convertToShares(mint_spend),
        DEJTRSY_SPOKE,
    )
    p2p.start_loan(pending, EMPTY_MINT_RESULT, 0, sender=keeper)
    minted = dejtrsy.balanceOf(vault_addr)
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=principal, collateral_amount=minted)
    assert compute_loan_hash(started) == p2p.loans(loan_id)

    # ---- redeem, keeping a residual ----
    residual = minted // 5
    redeemed_shares = minted - residual
    p2p.redeem(started, residual, sender=borrower)
    redeem_event = get_last_event(p2p, "LoanCollateralRedeemStarted")
    redeem_start = boa.eval("block.timestamp")
    redeeming = replace_namedtuple_field(started, redeem_start=redeem_start, redeem_residual_collateral=residual)
    assert compute_loan_hash(redeeming) == p2p.loans(loan_id)

    assert redeem_event.loan_id == loan_id
    assert redeem_event.redeem_residual_collateral == residual
    assert dejtrsy_async_vault.pendingRedeemRequest(0, vault_addr) == redeemed_shares
    assert dejtrsy.balanceOf(vault_addr) == residual, "residual stays in the loan vault"

    # Precondition: settle is blocked until the redemption is fulfilled.
    with boa.reverts("redeem not settled"):
        p2p.settle_loan(redeeming, EMPTY_REDEEM_RESULT, sender=borrower)

    # ---- issuer fulfils the redemption ----
    redeem_assets = dejtrsy_async_vault.convertToAssets(redeemed_shares)
    centrifuge_fulfill_redeem(
        dejtrsy_manager,
        DEJTRSY_POOL_ID,
        DEJTRSY_SCID,
        dejtrsy_asset_id,
        vault_addr,
        redeemed_shares,
        redeem_assets,
        DEJTRSY_SPOKE,
    )
    # Claimable (differs from redeemed_shares by a few wei of manager redeemPrice rounding); settle claims it.
    assert dejtrsy_async_vault.pendingRedeemRequest(0, vault_addr) == 0
    assert dejtrsy_async_vault.claimableRedeemRequest(0, vault_addr) > 0

    interest = redeeming.get_interest(boa.eval("block.timestamp"))
    assert interest == 0, "no time-travel -> zero interest"
    protocol_fee = interest * redeeming.protocol_settlement_fee // BPS
    expected_lender_payment = redeeming.amount + interest - protocol_fee

    lender_before = usdc.balanceOf(lender)
    borrower_before = usdc.balanceOf(borrower)

    p2p.settle_loan(redeeming, EMPTY_REDEEM_RESULT, sender=borrower)
    paid_event = get_last_event(p2p, "LoanPaid")

    # Actual claimed proceeds are ground truth (on-chain claim rounding, not predictable pre-tx).
    claimed_usdc = paid_event.in_vault_payment_token
    assert 0 < claimed_usdc <= redeem_assets
    assert redeem_assets - claimed_usdc <= 2, "claim rounding is at most a couple wei off convertToAssets"
    surplus = claimed_usdc - redeeming.amount - interest
    assert surplus > 0

    assert p2p.loans(loan_id) == ZERO_BYTES32
    assert dejtrsy_async_vault.claimableRedeemRequest(0, vault_addr) == 0
    assert paid_event.in_vault_collateral == residual

    assert usdc.balanceOf(lender) == lender_before + expected_lender_payment
    assert usdc.balanceOf(borrower) == borrower_before + surplus
    assert expected_lender_payment + protocol_fee + surplus == claimed_usdc, "USDC conservation"
    assert dejtrsy.balanceOf(borrower) == residual, "residual collateral returned to the borrower"
    assert dejtrsy.balanceOf(vault_addr) == 0
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == 0


# ---------------------------------------------------------------------------
# 5. Cancel an in-flight redemption -> loan back to normal active state
# ---------------------------------------------------------------------------


def test_cancel_redeem_restores_active_loan(
    p2p_usdc_dejtrsy,
    borrower,
    lender,
    lender_key,
    dejtrsy_keeper,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    dejtrsy_token,
    dejtrsy_oracle,
    dejtrsy_async_vault,
    dejtrsy_hook,
    dejtrsy_manager,
    dejtrsy_asset_id,
):
    """A started loan enters redemption, then cancel_redeem reverses it. On the real manager the redeem
    cancellation is SYNCHRONOUS, so cancel_redeem phase-1 (submit) is immediately followed by phase-3
    (claim reclaimed shares, reset redeem_start) — the loan returns to its normal active state with all
    shares back in the vault.
    """
    p2p, dejtrsy, oracle = p2p_usdc_dejtrsy, dejtrsy_token, dejtrsy_oracle
    keeper = dejtrsy_keeper

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, dejtrsy_async_vault)
    min_collateral_out = collateral * 97 // 100
    borrower_margin = mint_spend - principal

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_centrifuge_offer(
        p2p, lender, lender_key, borrower, now, principal=principal, min_collateral=min_collateral_out
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    vault_addr = p2p.vault_id_to_vault(borrower, 0)
    usdc.transfer(lender, mint_spend, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.transfer(borrower, borrower_margin, sender="0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1")
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(dejtrsy_hook, DEJTRSY, vault_addr, DEJTRSY_ROOT)

    loan_id = p2p.create_leveraged_loan(
        signed_offer,
        principal,
        collateral,
        kyc_borrower,
        kyc_lender,
        mint_spend,
        min_collateral_out,
        sender=borrower,
    )
    pending = _expected_pending_loan(
        p2p, signed_offer, offer, loan_id, borrower, lender, now, principal=principal, collateral=collateral
    )
    centrifuge_fulfill_deposit(
        dejtrsy_manager,
        DEJTRSY_POOL_ID,
        DEJTRSY_SCID,
        dejtrsy_asset_id,
        vault_addr,
        mint_spend,
        dejtrsy_async_vault.convertToShares(mint_spend),
        DEJTRSY_SPOKE,
    )
    p2p.start_loan(pending, EMPTY_MINT_RESULT, 0, sender=keeper)
    minted = dejtrsy.balanceOf(vault_addr)
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=principal, collateral_amount=minted)

    # ---- redeem the whole balance ----
    p2p.redeem(started, 0, sender=borrower)
    redeeming = replace_namedtuple_field(started, redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=0)
    assert compute_loan_hash(redeeming) == p2p.loans(loan_id)
    assert dejtrsy_async_vault.pendingRedeemRequest(0, vault_addr) == minted
    assert dejtrsy.balanceOf(vault_addr) == 0, "shares moved into the redeem request"

    # ---- cancel_redeem: phase 1 submits, phase 3 completes (synchronous cancel on the real manager) ----
    assert p2p.cancel_redeem(redeeming, sender=borrower) is False
    assert dejtrsy_async_vault.claimableCancelRedeemRequest(0, vault_addr) == minted, "cancel already claimable"

    assert p2p.cancel_redeem(redeeming, sender=borrower) is True
    cancel_event = get_last_event(p2p, "RedeemCancelled")

    assert cancel_event.loan_id == loan_id
    assert cancel_event.borrower == borrower
    assert cancel_event.lender == lender
    assert cancel_event.vault_id == 0

    # State: the loan is back to a normal active loan (redeem_start reset), shares back in the vault.
    assert compute_loan_hash(started) == p2p.loans(loan_id)
    assert dejtrsy.balanceOf(vault_addr) == minted, "all redeemed shares reclaimed into the loan vault"
    assert dejtrsy_async_vault.pendingRedeemRequest(0, vault_addr) == 0
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == principal
