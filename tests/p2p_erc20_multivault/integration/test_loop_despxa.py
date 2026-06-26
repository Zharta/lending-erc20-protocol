"""Integration tests for the ASYNC (Centrifuge ERC-7540) leveraged-loan lifecycle of
`P2PLendingMultiVaultErc20`, driven against the REAL deSPXA/USDC AsyncVault on a BASE MAINNET fork.

This is the deSPXA-on-Base honest sibling of `test_loop_dejaaa.py`: it exercises the SAME
`P2PLendingVaultCentrifugeAsync` impl and the SAME chain-neutral `centrifuge_*` fulfilment recipe, but against the
real deSPXA token on Base. The Base Centrifuge V3 deployment shares the identical manager / spoke / hook /
root addresses as Ethereum's (Centrifuge deploys deterministically), so the fulfilment / whitelisting is
verbatim; only the token / vault / pool-id / scid / asset-id and the oracle differ.

The Base RPC is derived from BOA_FORK_RPC_URL (eth-mainnet -> base-mainnet); if that substring is absent
the whole module skips (see the base_boa_env fixture). deSPXA and USDC decimals match deJAAA's (18 / 6), so
the sizing / split math is identical — the only numeric difference is the price (~757 USDC/deSPXA vs
~1.04 USDC/deJAAA), which every amount is derived from live via the fresh CentrifugeOracleAdapter and the
AsyncVault's convertToShares.

Same all-effects standard as the deJAAA suite (state hash + events + balances + liquidity). boa quirk:
events must be read IMMEDIATELY after the tx that emits them — any subsequent call (even a view getter)
resets boa's last computation and get_logs returns []. The create tests capture their events first, then
run the state/balance assertions.
"""

import os

import boa
import pytest
from boa.environment import Env

from ...conftest_base import BASE_FORK_BLOCK
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
    centrifuge_fulfill_cancel_deposit,
    centrifuge_fulfill_cancel_redeem,
    centrifuge_fulfill_deposit,
    centrifuge_fulfill_redeem,
    centrifuge_whitelist,
)

BPS = 10000
EMPTY_MINT_RESULT = ((boa.eval("empty(address)"), 0, 0, 0), (0, 0, 0))
EMPTY_REDEEM_RESULT = ((boa.eval("empty(address)"), 0, 0, 0), (0, 0, 0))
TARGET_LTV = 6800  # realized LTV we size collateral for (well under the 8000 offer cap)
MAX_ILTV = 8000

DESPXA = "0x9c5C365e764829876243d0b289733B9D2b729685"  # Centrifuge share token (collateral, 18 dec)
DESPXA_ASYNC_VAULT = "0x2dA40F061536c2f3a8f95f23a5f4c133d07D393a"  # deSPXA/USDC ERC-7540 AsyncVault (ERC-7575)
DESPXA_MANAGER = "0xF48256AbDDf96EcDDc4B3DbD23E8C1921f9761Ae"  # AsyncRequestManager (same addr as Ethereum)
DESPXA_SPOKE = "0xEC3582fcDc34078a4B7a8c75a5a3AE46f48525aB"  # Centrifuge spoke (same addr as Ethereum)
DESPXA_ROOT = "0x7Ed48C31f2fdC40d37407cBaBf0870B2b688368f"  # root, warded on the hook (same addr as Ethereum)
DESPXA_HOOK = "0x2a9B9C14851Baf7AD19f26607C9171CA1E7a1A61"  # restriction hook (same addr as Ethereum)
DESPXA_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base USDC (6 dec)
DESPXA_USDC_WHALE = "0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB"  # Aave aBasUSDC pool, ~32M USDC on-fork
DESPXA_POOL_ID = 281474976710668
DESPXA_SCID = bytes.fromhex("000100000000000c0000000000000001")


# --- Base fork env + deployments (everything the deSPXA market needs lives under the Base env) ---------
#
# A Base fork needs its OWN boa env (different chain + block) and therefore its own facets / kyc / market
# deployed UNDER that env — a market wired to the Ethereum-env facets would delegatecall into empty code on
# Base and silently no-op. The env-agnostic contract DEFS (bytecode / abi) come from conftest; only the
# deployments and the real-address handles are Base-specific, so they live here, next to their only users.


@pytest.fixture
def base_boa_env():
    BASE_FORK_RPC_URL = os.environ.get("BOA_BASE_FORK_RPC_URL")
    if not BASE_FORK_RPC_URL:
        BASE_FORK_RPC_URL = os.environ.get("BOA_FORK_RPC_URL", "").replace("eth-mainnet", "base-mainnet")
    new_env = Env()
    with boa.swap_env(new_env):
        boa.env.fork(BASE_FORK_RPC_URL, block_identifier=BASE_FORK_BLOCK)
        yield


@pytest.fixture
def base_accounts(base_boa_env):
    _accounts = [boa.env.generate_address() for _ in range(10)]
    for account in _accounts:
        boa.env.set_balance(account, 10**21)
    return _accounts


@pytest.fixture
def base_owner(owner_account, base_boa_env):
    boa.env.eoa = owner_account.address
    boa.env.set_balance(owner_account.address, 10**21)
    return owner_account.address


@pytest.fixture
def base_borrower(borrower_account, base_boa_env):
    boa.env.set_balance(borrower_account.address, 10**21)
    return borrower_account.address


@pytest.fixture
def base_lender(lender_account, base_boa_env):
    boa.env.set_balance(lender_account.address, 10**21)
    return lender_account.address


@pytest.fixture
def base_keeper(base_accounts, base_borrower, base_lender):
    """A non-borrower keeper used to prove permissionless start / post-window cancel paths."""
    keeper = base_accounts[5]
    assert keeper not in {base_borrower, base_lender}
    return keeper


@pytest.fixture
def base_kyc_validator(kyc_validator_account, base_boa_env):
    boa.env.set_balance(kyc_validator_account.address, 10**21)
    return kyc_validator_account.address


@pytest.fixture
def base_usdc(base_accounts, base_owner, erc20_contract_def):
    """Base USDC, funded onto the test accounts + owner from a real Base USDC whale (honest transfer)."""
    erc20 = erc20_contract_def.at(DESPXA_USDC)
    boa.env.set_balance(DESPXA_USDC_WHALE, 10**20)
    for account in base_accounts:
        erc20.transfer(account, 10**10, sender=DESPXA_USDC_WHALE)
    erc20.transfer(base_owner, 10**10, sender=DESPXA_USDC_WHALE)
    return erc20


@pytest.fixture
def base_kyc_validator_contract(kyc_validator_contract_def, base_kyc_validator):
    return kyc_validator_contract_def.deploy(base_kyc_validator)


@pytest.fixture
def base_mv_refinance(p2p_lending_multivault_refinance_contract_def, base_boa_env):
    return p2p_lending_multivault_refinance_contract_def.deploy()


@pytest.fixture
def base_mv_liquidation(p2p_lending_multivault_liquidation_contract_def, base_boa_env):
    return p2p_lending_multivault_liquidation_contract_def.deploy()


@pytest.fixture
def base_mv_loan(p2p_lending_multivault_loan_contract_def, base_boa_env):
    return p2p_lending_multivault_loan_contract_def.deploy()


# --- deSPXA fixtures (real deployed handles bound under the Base fork env) ----------------------------


@pytest.fixture(scope="session")
def centrifuge_oracle_adapter_contract_def():
    return boa.load_partial("contracts/CentrifugeOracleAdapter.vy")


@pytest.fixture
def despxa_token(centrifuge_share_token_contract_def, base_boa_env):
    return centrifuge_share_token_contract_def.at(DESPXA)


@pytest.fixture
def despxa_oracle(centrifuge_oracle_adapter_contract_def, base_boa_env):
    """A FRESH CentrifugeOracleAdapter deployed on the Base fork (no Base p2p config / oracle exists yet).

    It prices deSPXA off the real Centrifuge spoke (~757 USDC/deSPXA) through the Chainlink
    AggregatorV3 interface the lending contract expects; deploying it fresh (rather than mocking)
    keeps the price honest and it survives the time-travel flows (never-stale marker).
    """
    return centrifuge_oracle_adapter_contract_def.deploy(DESPXA_SPOKE, DESPXA)


@pytest.fixture
def despxa_async_vault(centrifuge_async_vault_contract_def, base_boa_env):
    """The real deSPXA/USDC ERC-7540 AsyncVault."""
    return centrifuge_async_vault_contract_def.at(DESPXA_ASYNC_VAULT)


@pytest.fixture
def despxa_manager(centrifuge_manager_contract_def, base_boa_env):
    return centrifuge_manager_contract_def.at(DESPXA_MANAGER)


@pytest.fixture
def despxa_hook(centrifuge_hook_contract_def, despxa_token):
    """The share token's CURRENTLY active restriction hook (read live). Exposes updateMember."""
    return centrifuge_hook_contract_def.at(despxa_token.hook())


@pytest.fixture
def despxa_asset_id(centrifuge_spoke_contract_def, base_boa_env):
    return centrifuge_spoke_contract_def.at(DESPXA_SPOKE).assetToId(DESPXA_USDC, 0)


@pytest.fixture
def centrifuge_async_vault_impl_base(centrifuge_async_vault_impl_contract_def, base_boa_env):
    """The P2PLendingVaultCentrifugeAsync impl (the code under test), deployed under the Base fork env."""
    return centrifuge_async_vault_impl_contract_def.deploy()


@pytest.fixture
def p2p_usdc_despxa(
    p2p_lending_multivault_erc20_contract_def,
    base_mv_refinance,
    base_mv_liquidation,
    base_mv_loan,
    centrifuge_async_vault_impl_base,
    despxa_oracle,
    base_kyc_validator_contract,
    base_owner,
    transfer_agent,
    base_boa_env,
):
    """Despxa (async ERC-7540) market wired to the REAL deSPXA AsyncVault (Base mainnet).

    All deployments (facets, kyc, vault impl, oracle adapter, market) MUST live under the Base env —
    a market wired to another env's facet addresses delegatecalls into empty code and silently
    no-ops. The AsyncVault is BOTH mint_addr and redemption_addr (D24). max_pending_window (50s) <
    the async offers' 100s duration (D30). All fees start at zero; individual tests bump them.
    """
    return p2p_lending_multivault_erc20_contract_def.deploy(
        DESPXA_USDC,  # payment_token
        DESPXA,  # collateral_token
        despxa_oracle.address,  # oracle_addr
        False,  # oracle_reverse
        base_kyc_validator_contract,  # kyc_validator_addr
        0,  # protocol_upfront_fee
        0,  # protocol_settlement_fee
        base_owner,  # protocol_wallet
        10000,  # max_protocol_upfront_fee
        10000,  # max_protocol_settlement_fee
        0,  # partial_liquidation_fee
        0,  # full_liquidation_fee
        base_mv_refinance.address,  # refinance_addr
        base_mv_liquidation.address,  # liquidation_addr
        base_mv_loan.address,  # loan_addr
        centrifuge_async_vault_impl_base.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        DESPXA_ASYNC_VAULT,  # mint_addr (D24: the Centrifuge AsyncVault)
        DESPXA_ASYNC_VAULT,  # redemption_addr (D24)
        boa.eval("empty(address)"),  # vault_registrar_addr
        50,  # max_pending_window (< the async offers' 100s duration, D30)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _size_leverage(principal, oracle, async_vault):
    """Return (collateral, mint_spend) that realize ~TARGET_LTV against the real oracle + AsyncVault price.

    collateral is chosen so `calc_ltv(principal, collateral) == TARGET_LTV`; mint_spend is the USDC needed
    to acquire that many deSPXA shares at the vault's convertToShares rate. deSPXA is 18-dec, USDC 6-dec —
    identical to the deJAAA suite, so the sizing math is shared verbatim.
    """
    rate = oracle.latestRoundData()[1]
    odec = 10 ** oracle.decimals()
    collateral = principal * BPS * odec * (10**18) // (TARGET_LTV * rate * (10**6))
    shares_per_usdc = async_vault.convertToShares(10**6)
    mint_spend = collateral * 10**6 // shares_per_usdc
    return collateral, mint_spend


def _sign_despxa_offer(p2p, lender, lender_key, borrower, now, *, principal, min_collateral, origination_fee_bps=0):
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
    p2p_usdc_despxa,
    base_borrower,
    base_lender,
    lender_key,
    base_keeper,
    base_kyc_validator_contract,
    kyc_validator_key,
    base_usdc,
    despxa_token,
    despxa_oracle,
    despxa_async_vault,
    despxa_hook,
    despxa_manager,
    despxa_asset_id,
):
    p2p, despxa, oracle, usdc = p2p_usdc_despxa, despxa_token, despxa_oracle, base_usdc
    borrower, lender, keeper = base_borrower, base_lender, base_keeper
    kyc_validator_contract = base_kyc_validator_contract

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, despxa_async_vault)
    min_collateral_out = collateral * 97 // 100
    origination_fee = 0  # keep settle math clean (apr>0 but no time-travel -> interest 0)
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_despxa_offer(
        p2p, lender, lender_key, borrower, now, principal=principal, min_collateral=min_collateral_out
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    # Preconditions
    assert borrower_margin > 0, "must be a leveraged loan (borrower contributes margin)"
    assert p2p.vault_count(borrower) == 0, "first vault for this borrower"
    vault_addr = p2p.vault_id_to_vault(borrower, 0)

    # Fund lender (principal) + borrower (margin); the loan vault must be whitelisted before requestDeposit.
    usdc.transfer(lender, mint_spend, sender=DESPXA_USDC_WHALE)
    usdc.transfer(borrower, borrower_margin, sender=DESPXA_USDC_WHALE)
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(despxa_hook, DESPXA, vault_addr, DESPXA_ROOT)

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
    # check independently pins EVERY field of the created loan.
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
    assert created_event.collateral_token == despxa.address
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
    assert despxa.balanceOf(vault_addr) == 0, "no shares until the deposit settles and the loan starts"
    assert despxa_async_vault.pendingDepositRequest(0, vault_addr) == mint_spend

    # Liquidity: full principal committed.
    liquidity_key = compute_liquidity_key(lender, offer.tracing_id)
    assert p2p.commited_liquidity(liquidity_key) == principal
    assert p2p.vault_count(borrower) == 1

    # ---- issuer fulfils the deposit ----
    shares = despxa_async_vault.convertToShares(mint_spend)
    centrifuge_fulfill_deposit(
        despxa_manager, DESPXA_POOL_ID, DESPXA_SCID, despxa_asset_id, vault_addr, mint_spend, shares, DESPXA_SPOKE
    )
    assert despxa_async_vault.pendingDepositRequest(0, vault_addr) == 0
    assert despxa_async_vault.claimableDepositRequest(0, vault_addr) > 0

    # ---- start_loan by a NON-borrower keeper (permissionless, D20) ----
    assert keeper != borrower
    p2p.start_loan(pending, EMPTY_MINT_RESULT, sender=keeper)
    started_event = get_last_event(p2p, "LoanStarted")
    start_time = boa.eval("block.timestamp")

    # The ACTUAL minted collateral now backs the loan (ground truth from the vault balance).
    minted = despxa.balanceOf(vault_addr)
    assert minted >= min_collateral_out, "minted below the offer's minimum"
    realized_ltv = calc_ltv(principal, minted, usdc, despxa, oracle, oracle_reverse=False)
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
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == minted
    assert despxa.balanceOf(vault_addr) == 0, "shares moved into the redeem request"

    redeem_assets = despxa_async_vault.convertToAssets(minted)  # USDC the issuer settles the redeem for
    centrifuge_fulfill_redeem(
        despxa_manager, DESPXA_POOL_ID, DESPXA_SCID, despxa_asset_id, vault_addr, minted, redeem_assets, DESPXA_SPOKE
    )
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == 0
    assert despxa_async_vault.claimableRedeemRequest(0, vault_addr) > 0

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
    assert despxa.balanceOf(vault_addr) == 0
    assert despxa_async_vault.claimableRedeemRequest(0, vault_addr) == 0, "the redemption was actually claimed"

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
    assert despxa.balanceOf(borrower) == 0, "no residual collateral to return"


# ---------------------------------------------------------------------------
# 2. Cancel a pending (unfilled) loan — liquidation-style USDC waterfall
# ---------------------------------------------------------------------------


def test_cancel_pending_unfilled_loan(
    p2p_usdc_despxa,
    base_borrower,
    base_lender,
    lender_key,
    base_keeper,
    base_owner,
    base_kyc_validator_contract,
    kyc_validator_key,
    base_usdc,
    despxa_oracle,
    despxa_async_vault,
    despxa_hook,
    despxa_manager,
    despxa_asset_id,
):
    """Create -> cancel_pending_loan (deposit never filled). On the BASE Centrifuge deployment the ERC-7887
    deposit cancellation is ASYNCHRONOUS (unlike Ethereum's synchronous cancel): the phase-1 call only
    SUBMITS the cancel (pendingCancelDeposit -> True, the reclaimed payment not yet claimable). The issuer
    must relay a FulfilledDepositRequest with cancelledAssets == mint_spend before the reclaimed payment is
    claimable; only then does the next call run the D27 liquidation-style USDC waterfall and clear the loan.
    This exercises the contract's async-cancel state machine (request_pending -> cancel_pending ->
    cancel_claimable). Nonzero origination + settlement + full-liquidation fees make the money math real; a
    keeper drives it post-window (permissionless, D18).
    """
    p2p, oracle, usdc = p2p_usdc_despxa, despxa_oracle, base_usdc
    borrower, lender, keeper, owner = base_borrower, base_lender, base_keeper, base_owner
    kyc_validator_contract = base_kyc_validator_contract

    p2p.set_full_liquidation_fee(500, sender=owner)  # 5% keeper incentive
    p2p.set_protocol_fee(0, 1000, sender=owner)  # 10% settlement fee on interest

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, despxa_async_vault)
    min_collateral_out = collateral * 97 // 100
    origination_fee_bps = 100  # 1% -> lender never deploys the origination fee
    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_despxa_offer(
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
    usdc.transfer(lender, mint_spend, sender=DESPXA_USDC_WHALE)
    usdc.transfer(borrower, borrower_margin, sender=DESPXA_USDC_WHALE)
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(despxa_hook, DESPXA, vault_addr, DESPXA_ROOT)

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
    assert despxa_async_vault.pendingDepositRequest(0, vault_addr) == mint_spend

    # Past the pending window -> a keeper may cancel (D18).
    boa.env.time_travel(seconds=p2p.max_pending_window() + 1)
    assert keeper not in {borrower, lender, owner}

    # Phase 1: submit the cancel. On Base this only SUBMITS it (async cancel) — the deposit is still
    # pending and the reclaimed payment is NOT yet claimable, so the call returns False.
    assert p2p.cancel_pending_loan(loan, EMPTY_MINT_RESULT, sender=keeper) is False
    assert despxa_async_vault.pendingDepositRequest(0, vault_addr) == mint_spend, "deposit still pending (async cancel)"
    assert despxa_async_vault.claimableCancelDepositRequest(0, vault_addr) == 0, "cancel not yet claimable"

    # Issuer fulfils the cancel: the reclaimed payment becomes claimable (deposit request cleared).
    centrifuge_fulfill_cancel_deposit(
        despxa_manager, DESPXA_POOL_ID, DESPXA_SCID, despxa_asset_id, vault_addr, mint_spend, DESPXA_SPOKE
    )
    assert despxa_async_vault.pendingDepositRequest(0, vault_addr) == 0
    assert despxa_async_vault.claimableCancelDepositRequest(0, vault_addr) == mint_spend

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
    p2p_usdc_despxa,
    base_borrower,
    base_lender,
    lender_key,
    base_keeper,
    base_owner,
    base_kyc_validator_contract,
    kyc_validator_key,
    base_usdc,
    despxa_token,
    despxa_oracle,
    despxa_async_vault,
    despxa_hook,
    despxa_manager,
    despxa_asset_id,
):
    """A deposit that FILLS but below the offer's min_collateral_amount: start_loan reverts "low collateral
    amount"; the fulfilled ERC-7540 request can't be cancelled, so cancel_pending_loan force-unwinds by
    claiming the shares and splitting them oracle-valued, liquidation-style. All legs are paid in deSPXA
    SHARES (not USDC). Every share leg is computed independently from the real oracle rate.
    """
    p2p, despxa, oracle, usdc = p2p_usdc_despxa, despxa_token, despxa_oracle, base_usdc
    borrower, lender, keeper, owner = base_borrower, base_lender, base_keeper, base_owner
    kyc_validator_contract = base_kyc_validator_contract

    p2p.set_full_liquidation_fee(500, sender=owner)
    p2p.set_protocol_fee(0, 1000, sender=owner)

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, despxa_async_vault)
    # The offer demands the full estimate but the issuer will fill ~half -> below min, not startable.
    min_collateral_out = collateral
    origination_fee_bps = 100
    origination_fee = origination_fee_bps * principal // BPS
    lender_to_vault = principal - origination_fee
    borrower_margin = mint_spend - lender_to_vault

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_despxa_offer(
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
    usdc.transfer(lender, mint_spend, sender=DESPXA_USDC_WHALE)
    usdc.transfer(borrower, borrower_margin, sender=DESPXA_USDC_WHALE)
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(despxa_hook, DESPXA, vault_addr, DESPXA_ROOT)

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
    low_shares = despxa_async_vault.convertToShares(mint_spend) * 80 // 100
    centrifuge_fulfill_deposit(
        despxa_manager, DESPXA_POOL_ID, DESPXA_SCID, despxa_asset_id, vault_addr, mint_spend, low_shares, DESPXA_SPOKE
    )
    assert despxa_async_vault.pendingDepositRequest(0, vault_addr) == 0
    assert despxa_async_vault.claimableDepositRequest(0, vault_addr) > 0

    # Precondition: start_loan is blocked because the claimable fill is below min_collateral_amount.
    with boa.reverts("low collateral amount"):
        p2p.start_loan(loan, EMPTY_MINT_RESULT, sender=keeper)

    # cancel_pending_loan force-unwinds: claim the shares and split them oracle-valued, in SHARES.
    # The exact minted SHARE amount that claim_mint yields is a manager-priced on-chain quantity, not
    # predictable from the claimable ASSETS pre-tx; take it as ground truth from the captured
    # PendingLoanLiquidated.collateral_claimed, then recompute every split leg from THAT with the exact
    # integer math the contract uses (base.cancel_pending_loan force-unwind branch).
    rate_num = oracle.latestRoundData()[1]
    rate_den = 10 ** oracle.decimals()
    payment_dec = 10 ** usdc.decimals()
    collateral_dec = 10 ** despxa.decimals()

    def shares_to_value(sh):
        return sh * rate_num * payment_dec // (rate_den * collateral_dec)

    def value_to_shares(v):
        return v * rate_den * collateral_dec // (rate_num * payment_dec)

    keeper_before = despxa.balanceOf(keeper)
    lender_before = despxa.balanceOf(lender)
    borrower_before = despxa.balanceOf(borrower)
    protocol_before = despxa.balanceOf(p2p.protocol_wallet())

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
    # + borrower surplus). minted_value (~half the collateral, still ~700 USDC) comfortably exceeds the debt.
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

    # Balances: legs paid in deSPXA shares, plus share conservation.
    assert despxa.balanceOf(keeper) == keeper_before + liquidation_fee_shares
    assert despxa.balanceOf(lender) == lender_before + lender_shares
    assert despxa.balanceOf(p2p.protocol_wallet()) == protocol_before + protocol_fee_shares
    assert despxa.balanceOf(borrower) == borrower_before + borrower_shares
    assert liquidation_fee_shares + lender_shares + protocol_fee_shares + borrower_shares == minted

    assert p2p.loans(loan_id) == ZERO_BYTES32
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == 0
    assert despxa.balanceOf(vault_addr) == 0


# ---------------------------------------------------------------------------
# 4. Async redeem lifecycle: settle blocked until the redemption is fulfilled
# ---------------------------------------------------------------------------


def test_async_redeem_blocks_settle_until_fulfilled(
    p2p_usdc_despxa,
    base_borrower,
    base_lender,
    lender_key,
    base_keeper,
    base_kyc_validator_contract,
    kyc_validator_key,
    base_usdc,
    despxa_token,
    despxa_oracle,
    despxa_async_vault,
    despxa_hook,
    despxa_manager,
    despxa_asset_id,
):
    """A started loan is put into redemption; settle_loan reverts "redeem not settled" until the issuer
    fulfils the ERC-7540 redemption, then settle claims the proceeds on-chain (empty SignedRedeemResult).
    Keeps a residual so the collateral-return leg is exercised too.
    """
    p2p, despxa, oracle, usdc = p2p_usdc_despxa, despxa_token, despxa_oracle, base_usdc
    borrower, lender, keeper = base_borrower, base_lender, base_keeper
    kyc_validator_contract = base_kyc_validator_contract

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, despxa_async_vault)
    min_collateral_out = collateral * 97 // 100
    borrower_margin = mint_spend - principal

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_despxa_offer(
        p2p, lender, lender_key, borrower, now, principal=principal, min_collateral=min_collateral_out
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    vault_addr = p2p.vault_id_to_vault(borrower, 0)
    usdc.transfer(lender, mint_spend, sender=DESPXA_USDC_WHALE)
    usdc.transfer(borrower, borrower_margin, sender=DESPXA_USDC_WHALE)
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(despxa_hook, DESPXA, vault_addr, DESPXA_ROOT)

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
        despxa_manager,
        DESPXA_POOL_ID,
        DESPXA_SCID,
        despxa_asset_id,
        vault_addr,
        mint_spend,
        despxa_async_vault.convertToShares(mint_spend),
        DESPXA_SPOKE,
    )
    p2p.start_loan(pending, EMPTY_MINT_RESULT, sender=keeper)
    minted = despxa.balanceOf(vault_addr)
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
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == redeemed_shares
    assert despxa.balanceOf(vault_addr) == residual, "residual stays in the loan vault"

    # Precondition: settle is blocked until the redemption is fulfilled.
    with boa.reverts("redeem not settled"):
        p2p.settle_loan(redeeming, EMPTY_REDEEM_RESULT, sender=borrower)

    # ---- issuer fulfils the redemption ----
    redeem_assets = despxa_async_vault.convertToAssets(redeemed_shares)
    centrifuge_fulfill_redeem(
        despxa_manager,
        DESPXA_POOL_ID,
        DESPXA_SCID,
        despxa_asset_id,
        vault_addr,
        redeemed_shares,
        redeem_assets,
        DESPXA_SPOKE,
    )
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == 0
    assert despxa_async_vault.claimableRedeemRequest(0, vault_addr) > 0

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
    assert despxa_async_vault.claimableRedeemRequest(0, vault_addr) == 0
    assert paid_event.in_vault_collateral == residual

    assert usdc.balanceOf(lender) == lender_before + expected_lender_payment
    assert usdc.balanceOf(borrower) == borrower_before + surplus
    assert expected_lender_payment + protocol_fee + surplus == claimed_usdc, "USDC conservation"
    assert despxa.balanceOf(borrower) == residual, "residual collateral returned to the borrower"
    assert despxa.balanceOf(vault_addr) == 0
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == 0


# ---------------------------------------------------------------------------
# 5. Cancel an in-flight redemption -> loan back to normal active state
# ---------------------------------------------------------------------------


def test_cancel_redeem_restores_active_loan(
    p2p_usdc_despxa,
    base_borrower,
    base_lender,
    lender_key,
    base_keeper,
    base_kyc_validator_contract,
    kyc_validator_key,
    base_usdc,
    despxa_token,
    despxa_oracle,
    despxa_async_vault,
    despxa_hook,
    despxa_manager,
    despxa_asset_id,
):
    """A started loan enters redemption, then cancel_redeem reverses it. On the BASE Centrifuge deployment
    the redeem cancellation is ASYNCHRONOUS (unlike Ethereum): cancel_redeem phase-1 only SUBMITS the cancel
    (pendingCancelRedeem -> True, shares not yet claimable). The issuer must relay a FulfilledRedeemRequest
    with cancelledShares == minted before the reclaimed shares are claimable; only then does the next
    cancel_redeem call reclaim the shares, reset redeem_start, and return the loan to its normal active
    state with all shares back in the vault.
    """
    p2p, despxa, oracle, usdc = p2p_usdc_despxa, despxa_token, despxa_oracle, base_usdc
    borrower, lender, keeper = base_borrower, base_lender, base_keeper
    kyc_validator_contract = base_kyc_validator_contract

    principal = 1000 * 10**6
    collateral, mint_spend = _size_leverage(principal, oracle, despxa_async_vault)
    min_collateral_out = collateral * 97 // 100
    borrower_margin = mint_spend - principal

    now = boa.eval("block.timestamp")
    offer, signed_offer = _sign_despxa_offer(
        p2p, lender, lender_key, borrower, now, principal=principal, min_collateral=min_collateral_out
    )
    kyc_borrower = sign_kyc(borrower, now, kyc_validator_key, kyc_validator_contract.address)
    kyc_lender = sign_kyc(lender, now + 86400, kyc_validator_key, kyc_validator_contract.address)

    vault_addr = p2p.vault_id_to_vault(borrower, 0)
    usdc.transfer(lender, mint_spend, sender=DESPXA_USDC_WHALE)
    usdc.transfer(borrower, borrower_margin, sender=DESPXA_USDC_WHALE)
    usdc.approve(p2p.address, principal, sender=lender)
    usdc.approve(p2p.address, borrower_margin, sender=borrower)
    centrifuge_whitelist(despxa_hook, DESPXA, vault_addr, DESPXA_ROOT)

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
        despxa_manager,
        DESPXA_POOL_ID,
        DESPXA_SCID,
        despxa_asset_id,
        vault_addr,
        mint_spend,
        despxa_async_vault.convertToShares(mint_spend),
        DESPXA_SPOKE,
    )
    p2p.start_loan(pending, EMPTY_MINT_RESULT, sender=keeper)
    minted = despxa.balanceOf(vault_addr)
    started = pending._replace(start_time=boa.eval("block.timestamp"), initial_amount=principal, collateral_amount=minted)

    # ---- redeem the whole balance ----
    p2p.redeem(started, 0, sender=borrower)
    redeeming = replace_namedtuple_field(started, redeem_start=boa.eval("block.timestamp"), redeem_residual_collateral=0)
    assert compute_loan_hash(redeeming) == p2p.loans(loan_id)
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == minted
    assert despxa.balanceOf(vault_addr) == 0, "shares moved into the redeem request"

    # ---- cancel_redeem: phase 1 submits (async cancel on Base), issuer fulfils, phase 3 completes ----
    assert p2p.cancel_redeem(redeeming, sender=borrower) is False
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == minted, "redeem still pending (async cancel)"
    assert despxa_async_vault.claimableCancelRedeemRequest(0, vault_addr) == 0, "cancel not yet claimable"

    centrifuge_fulfill_cancel_redeem(
        despxa_manager, DESPXA_POOL_ID, DESPXA_SCID, despxa_asset_id, vault_addr, minted, DESPXA_SPOKE
    )
    assert despxa_async_vault.claimableCancelRedeemRequest(0, vault_addr) == minted, "cancel now claimable"

    assert p2p.cancel_redeem(redeeming, sender=borrower) is True
    cancel_event = get_last_event(p2p, "RedeemCancelled")

    assert cancel_event.loan_id == loan_id
    assert cancel_event.borrower == borrower
    assert cancel_event.lender == lender
    assert cancel_event.vault_id == 0

    # State: the loan is back to a normal active loan (redeem_start reset), shares back in the vault.
    assert compute_loan_hash(started) == p2p.loans(loan_id)
    assert despxa.balanceOf(vault_addr) == minted, "all redeemed shares reclaimed into the loan vault"
    assert despxa_async_vault.pendingRedeemRequest(0, vault_addr) == 0
    assert p2p.commited_liquidity(compute_liquidity_key(lender, offer.tracing_id)) == principal
