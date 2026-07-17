"""Unit tests for P2PLendingVaultMidas against the consolidated MidasVaultMock.

Redeem side (redeem_sync): the F1 fix to the slippage floor. `min_receive_amount` is the base18
oracle-implied value `amount_without_fee * oracle_rate_num // oracle_rate_den`. Before F1 it was
additionally divided by `scale*scale` (scale = 10**(18 - token_out_decimals)), which collapsed the
floor to ~0 for sub-18 decimal payment tokens like USDC, leaving the slippage guard inert.

Mint side (mint_sync): the vault approves a MidasVaultMock deposit vault and calls `depositInstant`,
which pulls the stablecoin (capped by `set_max_deposit_spend` -> the D23 partial-spend/refund case) and
pays out `set_deposit_deliver_amount` mtoken from its own (pre-funded) balance, enforcing the base18
min-out floor. The vault credits the delivered mtoken to `pending_transfers[owner]` and returns
`(minted, refunded)` where refunded = stable_coin_amount - spent.

MidasVaultMock (contracts/auxiliary/MidasVaultMock.vy) stands in for BOTH the Midas DepositVault and
RedemptionVault: it records the base18 amounts it was passed, enforces the floors against
test-configured delivered amounts, and pays out from its own balance (tests pre-fund it).
"""

import boa
import pytest

BPS = 10000
INSTANT_FEE_BPS = 100  # 1% instant-redeem fee configured on the redemption mock


@pytest.fixture(scope="session")
def midas_vault_impl_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVaultMidas.vy")


@pytest.fixture(scope="session")
def midas_vault_mock_def(boa_env):
    return boa.load_partial("contracts/auxiliary/MidasVaultMock.vy")


@pytest.fixture
def mtoken(weth9_contract_def, owner):
    """Midas mTokens are 18-decimal; the vault holds these as collateral."""
    return weth9_contract_def.deploy("mTBILL", "MTBILL", 18, 10**12)


@pytest.fixture
def token_out_usdc(weth9_contract_def, owner):
    """6-decimal payment token (the case where the pre-F1 bug collapsed the floor)."""
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**12)


@pytest.fixture
def token_out_dai(weth9_contract_def, owner):
    """18-decimal payment token (old and new floor math coincide)."""
    return weth9_contract_def.deploy("DAI", "DAI", 18, 10**12)


@pytest.fixture
def caller_addr():
    """Stand-in for the lending contract — the ONLY authorized mint_sync/redeem_sync caller."""
    return boa.env.generate_address("lending_contract")


@pytest.fixture
def midas_vault(midas_vault_impl_def, mtoken, caller_addr, owner):
    """A directly-initialised Midas vault.

    caller == caller_addr (the lending contract), owner == the borrower, token == the mtoken.
    caller and owner are DISTINCT so the caller-only guard on mint_sync/redeem_sync is exercised
    meaningfully: driving mint_sync as `owner` must now revert, only `caller_addr` is authorized.
    """
    vault = midas_vault_impl_def.deploy()
    vault.initialise(owner, mtoken.address, sender=caller_addr)  # caller = msg.sender = caller_addr
    return vault


@pytest.fixture
def redemption_mock(midas_vault_mock_def, mtoken, owner):
    """MidasVaultMock used on the redeem side (instant_fee = INSTANT_FEE_BPS)."""
    return midas_vault_mock_def.deploy(mtoken.address, INSTANT_FEE_BPS)


@pytest.fixture
def deposit_mock(midas_vault_mock_def, mtoken, owner):
    """MidasVaultMock used on the mint (deposit) side (no instant fee on the deposit path)."""
    return midas_vault_mock_def.deploy(mtoken.address, 0)


def _expected_min_receive(amount_mtoken, num, den):
    """The corrected base18 floor: amount_without_fee * num // den (mtoken is 18-dec -> base18 == native)."""
    amount_without_fee = amount_mtoken - amount_mtoken * INSTANT_FEE_BPS // BPS
    return amount_without_fee * num // den


# ============================================================================
# redeem_sync
# ============================================================================


def test_redeem_sync_succeeds_with_6dec_token_out(midas_vault, redemption_mock, mtoken, token_out_usdc, caller_addr, owner):
    """(1) 6-dec token_out, mock delivers exactly the oracle-implied amount -> succeeds, returns it."""
    amount_mtoken = 10**18
    num, den = 5, 1
    mtoken.mint(midas_vault.address, amount_mtoken, sender=owner)  # fund vault with mtokens to redeem

    expected_min_receive = _expected_min_receive(amount_mtoken, num, den)  # base18
    deliver_native = expected_min_receive // 10 ** (18 - 6)  # exact oracle-implied amount in native 6-dec
    assert deliver_native * 10 ** (18 - 6) == expected_min_receive  # precondition: divisible, no rounding slack
    token_out_usdc.mint(redemption_mock.address, deliver_native, sender=owner)
    redemption_mock.set_deliver_amount(deliver_native)

    redeemed, refunded = midas_vault.redeem_sync(
        redemption_mock.address, token_out_usdc.address, amount_mtoken, num, den, sender=caller_addr
    )

    assert redeemed == deliver_native  # returns the delivered token_out
    assert refunded == 0
    assert token_out_usdc.balanceOf(midas_vault.address) == deliver_native
    assert redemption_mock.last_mtoken_pulled() == amount_mtoken  # mtokens were pulled
    # F1: the floor is the base18 oracle value, NOT collapsed by the 6-dec token_out scale
    assert redemption_mock.last_min_receive() == expected_min_receive


def test_redeem_sync_reverts_when_delivery_below_floor(
    midas_vault, redemption_mock, mtoken, token_out_usdc, caller_addr, owner
):
    """(2) Regression lock: delivering one unit below the corrected floor reverts.

    Pre-fix the floor was divided by an extra (10**(18-6))**2 == 10**24, collapsing it to ~0, so this
    under-delivery would NOT have reverted (the slippage guard was inert for USDC-like payment tokens).
    """
    amount_mtoken = 10**18
    num, den = 5, 1
    mtoken.mint(midas_vault.address, amount_mtoken, sender=owner)

    expected_min_receive = _expected_min_receive(amount_mtoken, num, den)
    full_native = expected_min_receive // 10 ** (18 - 6)
    deliver_native = full_native - 1  # one unit below the floor
    token_out_usdc.mint(redemption_mock.address, full_native, sender=owner)
    redemption_mock.set_deliver_amount(deliver_native)

    with boa.reverts("insufficient output amount"):
        midas_vault.redeem_sync(redemption_mock.address, token_out_usdc.address, amount_mtoken, num, den, sender=caller_addr)


def test_redeem_sync_succeeds_with_18dec_token_out(midas_vault, redemption_mock, mtoken, token_out_dai, caller_addr, owner):
    """(3) 18-dec token_out sanity: old and new floor math coincide; floor is decimals-independent."""
    amount_mtoken = 10**18
    num, den = 5, 1
    mtoken.mint(midas_vault.address, amount_mtoken, sender=owner)

    expected_min_receive = _expected_min_receive(amount_mtoken, num, den)
    deliver_native = expected_min_receive  # 18-dec: native == base18
    token_out_dai.mint(redemption_mock.address, deliver_native, sender=owner)
    redemption_mock.set_deliver_amount(deliver_native)

    redeemed, refunded = midas_vault.redeem_sync(
        redemption_mock.address, token_out_dai.address, amount_mtoken, num, den, sender=caller_addr
    )

    assert redeemed == deliver_native
    assert refunded == 0
    # identical base18 floor to the 6-dec case -> proves min_receive is independent of token_out decimals
    assert redemption_mock.last_min_receive() == expected_min_receive


def test_redeem_sync_reverts_if_not_caller(midas_vault, redemption_mock, token_out_usdc, accounts):
    """redeem_sync is caller-only (the lending contract), even before touching the redemption vault."""
    with boa.reverts("unauthorized"):
        midas_vault.redeem_sync(redemption_mock.address, token_out_usdc.address, 10**18, 5, 1, sender=accounts[6])


# ============================================================================
# mint_sync (deposit side)
# ============================================================================


def test_mint_sync_credits_minted_to_pending_transfers(midas_vault, deposit_mock, mtoken, token_out_usdc, caller_addr, owner):
    """mint_sync credits the delivered mtoken to pending_transfers[owner] and returns it as `minted`."""
    stable_coin_amount = 1500 * 10**6  # 6-dec USDC routed to the deposit
    minted_mtoken = 10**18  # mtoken the deposit vault delivers
    token_out_usdc.mint(midas_vault.address, stable_coin_amount, sender=owner)  # vault pre-funded with payment
    mtoken.mint(deposit_mock.address, minted_mtoken, sender=owner)  # deposit vault pre-funded with mtoken to pay out
    deposit_mock.set_deposit_deliver_amount(minted_mtoken)

    # Driven by the lending contract (caller_addr), NOT the owner/borrower — mint_sync is caller-only.
    minted, refunded = midas_vault.mint_sync(
        token_out_usdc.address, deposit_mock.address, 0, stable_coin_amount, sender=caller_addr
    )

    assert minted == minted_mtoken  # full delivered mtoken returned as minted
    assert refunded == 0  # full spend (no deposit-spend cap)
    assert midas_vault.pending_transfers(owner) == minted_mtoken  # credited to the owner
    assert midas_vault.pending_transfers_total() == minted_mtoken
    assert deposit_mock.last_token_in_pulled() == stable_coin_amount  # full stablecoin pulled


def test_mint_sync_refunds_unspent_when_deposit_spend_capped(
    midas_vault, deposit_mock, mtoken, token_out_usdc, caller_addr, owner
):
    """D23: a deposit-spend cap below the requested amount yields a refund (stable_coin_amount - spent)."""
    stable_coin_amount = 1500 * 10**6
    spend_cap = 1200 * 10**6  # deposit vault only pulls this much
    refund = stable_coin_amount - spend_cap  # 300 USDC left unspent in the vault
    minted_mtoken = 8 * 10**17
    token_out_usdc.mint(midas_vault.address, stable_coin_amount, sender=owner)
    mtoken.mint(deposit_mock.address, minted_mtoken, sender=owner)
    deposit_mock.set_deposit_deliver_amount(minted_mtoken)
    deposit_mock.set_max_deposit_spend(spend_cap)

    minted, refunded = midas_vault.mint_sync(
        token_out_usdc.address, deposit_mock.address, 0, stable_coin_amount, sender=caller_addr
    )

    assert minted == minted_mtoken
    assert refunded == refund  # unspent payment returned to the lending contract to reconcile
    assert deposit_mock.last_token_in_pulled() == spend_cap  # only the capped amount was pulled
    assert token_out_usdc.balanceOf(midas_vault.address) == refund  # refund left in the vault


def test_mint_sync_reverts_when_delivery_below_min(midas_vault, deposit_mock, mtoken, token_out_usdc, caller_addr, owner):
    """The deposit vault reverts when the delivered mtoken is below the base18 min-out floor."""
    stable_coin_amount = 1500 * 10**6
    min_mtoken = 10**18  # require 1e18 mtoken out
    deliver_below = min_mtoken - 1  # deposit vault delivers one unit short of the floor
    token_out_usdc.mint(midas_vault.address, stable_coin_amount, sender=owner)
    mtoken.mint(deposit_mock.address, deliver_below, sender=owner)  # pre-fund even the short amount
    deposit_mock.set_deposit_deliver_amount(deliver_below)

    with boa.reverts("insufficient output amount"):
        midas_vault.mint_sync(token_out_usdc.address, deposit_mock.address, min_mtoken, stable_coin_amount, sender=caller_addr)


def test_mint_sync_forwards_min_out_floor_base18(midas_vault, deposit_mock, mtoken, token_out_usdc, caller_addr, owner):
    """mint_sync forwards min_mtoken normalized to base18 as the deposit vault's minReceiveAmount.

    mtoken is 18-dec so base18 == native; the assertion locks the normalization the vault performs.
    """
    stable_coin_amount = 1500 * 10**6
    min_mtoken = 5 * 10**17
    minted_mtoken = 10**18  # clears the floor
    token_out_usdc.mint(midas_vault.address, stable_coin_amount, sender=owner)
    mtoken.mint(deposit_mock.address, minted_mtoken, sender=owner)
    deposit_mock.set_deposit_deliver_amount(minted_mtoken)

    midas_vault.mint_sync(token_out_usdc.address, deposit_mock.address, min_mtoken, stable_coin_amount, sender=caller_addr)

    assert deposit_mock.last_deposit_min_receive() == min_mtoken * 10**18 // 10**18  # base18 (mtoken 18-dec)


def test_mint_sync_reverts_if_not_caller(midas_vault, deposit_mock, mtoken, token_out_usdc, caller_addr, owner, accounts):
    stable_coin_amount = 1500 * 10**6
    minted_mtoken = 10**18
    token_out_usdc.mint(midas_vault.address, stable_coin_amount, sender=owner)
    mtoken.mint(deposit_mock.address, minted_mtoken, sender=owner)
    deposit_mock.set_deposit_deliver_amount(minted_mtoken)

    # A random EOA is rejected.
    with boa.reverts("unauthorized"):
        midas_vault.mint_sync(token_out_usdc.address, deposit_mock.address, 0, stable_coin_amount, sender=accounts[6])

    # The vault owner/borrower is ALSO rejected (the closed theft vector).
    with boa.reverts("unauthorized"):
        midas_vault.mint_sync(token_out_usdc.address, deposit_mock.address, 0, stable_coin_amount, sender=owner)

    # Sanity: the SAME call succeeds from the authorized caller, proving only the sender differed.
    minted, _refunded = midas_vault.mint_sync(
        token_out_usdc.address, deposit_mock.address, 0, stable_coin_amount, sender=caller_addr
    )
    assert minted == minted_mtoken
    assert midas_vault.pending_transfers(owner) == minted_mtoken


def test_withdraw_funds_zero_amount_makes_no_transfer(midas_vault, zero_revert_erc20, caller_addr):
    """withdraw_funds(token, 0) must not attempt an ERC20 transfer — the settle/liquidation paths call
    it with 0 when the vault holds no leftover payment, and some tokens revert on a 0-value transfer.
    `zero_revert_erc20.transfer` reverts "zero transfer" on 0 and records whether it was called."""
    assert zero_revert_erc20.was_transfer_called() is False
    midas_vault.withdraw_funds(zero_revert_erc20.address, 0, sender=caller_addr)  # must NOT revert
    assert zero_revert_erc20.was_transfer_called() is False
