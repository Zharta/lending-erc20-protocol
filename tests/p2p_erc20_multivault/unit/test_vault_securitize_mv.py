"""Focused unit tests for P2PLendingVaultSecuritizeMV (the MultiVault Securitize vault).

This is the MV vault (`P2PLendingVaultSecuritizeMV.vy`, caps MINT_SYNC | REDEEM_MANUAL), NOT the legacy
`P2PLendingVaultSecuritize.vy` exercised by test_vault_securitize.py (which has buy()/_check_user/proxies).

Security: `mint_sync` is caller-only (`assert msg.sender == self.caller`). Under the MultiVault funding
model the vault spends its OWN pre-funded balance, so an owner-callable mint_sync would let the borrower
convert any payment token sitting in the loan vault (e.g. redemption proceeds awaiting the manual-redeem
settle) into DS credited to pending_transfers[owner] and drain it via withdraw_pending — a theft vector
during the SecuritizeMV manual-redeem settle window. Only the lending contract may call.

The MV vault resolves its swap connector from the collateral token via getDSService(1<<14), so the
collateral MUST be an AcredMock (its getDSService(1<<14) returns self).
"""

import boa
import pytest


@pytest.fixture
def caller_addr():
    """Stand-in for the lending contract — the ONLY authorized mint_sync caller."""
    return boa.env.generate_address("lending_contract")


@pytest.fixture
def borrower():
    """The vault owner (the borrower). Distinct from the caller so the caller-only guard is meaningful."""
    return boa.env.generate_address("borrower")


@pytest.fixture
def usdc(weth9_contract_def):
    """6-dec USDC — the payment token that redemption proceeds land in."""
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


@pytest.fixture
def ds_oracle(oracle_contract_def):
    """Oracle for the AcredMock swap: decimals=12, rate=1500 (num=1500, den=10**12).

    Maps 6-dec USDC -> 18-dec DS: ds = stable * den // num. A full 1500e6 USDC mint -> exactly 1e18 DS.
    """
    return oracle_contract_def.deploy(12, 1500)


@pytest.fixture
def ds_token(acred_contract_def, ds_oracle, usdc):
    """18-dec AcredMock standing in for the Securitize DS collateral token.

    Its getDSService(1<<14) returns self, so mint_sync resolves the swap connector to this same contract.
    """
    return acred_contract_def.deploy("ACREDMV", "ACREDMV", 18, 10**6, ds_oracle.address, usdc.address)


@pytest.fixture
def mv_vault(securitize_mv_vault_contract_def, ds_token, caller_addr, borrower):
    """A directly-initialised P2PLendingVaultSecuritizeMV.

    caller == caller_addr (lending contract), owner == borrower, token == the AcredMock DS token.
    caller and owner are DISTINCT so the caller-only guard on mint_sync is exercised meaningfully.
    """
    vault = securitize_mv_vault_contract_def.deploy()
    vault.initialise(borrower, ds_token.address, sender=caller_addr)  # caller = msg.sender = caller_addr
    return vault


def test_mint_sync_reverts_when_borrower_tries_to_drain_redemption_proceeds(mv_vault, ds_token, usdc, caller_addr, borrower):
    """A borrower/owner-sender mint_sync over the vault's payment balance reverts "unauthorized".

    An owner-callable mint_sync would convert the vault's USDC (redemption proceeds awaiting settle) into
    DS credited to pending_transfers[owner], drainable via withdraw_pending (the theft vector). We fund
    the vault with USDC as if redemption proceeds landed in it, then the borrower attempts to convert the
    FULL vault balance. It must be rejected before any swap occurs.
    """
    redemption_proceeds = 1500 * 10**6  # USDC sitting in the loan vault awaiting settle
    usdc.mint(mv_vault.address, redemption_proceeds)

    # precondition: the vault holds the payment token, and nothing is credited as pending yet
    assert usdc.balanceOf(mv_vault.address) == redemption_proceeds
    assert mv_vault.pending_transfers(borrower) == 0
    assert mv_vault.pending_transfers_total() == 0

    # The borrower/owner tries to convert the vault's own USDC into DS credited to themselves.
    with boa.reverts("unauthorized"):
        mv_vault.mint_sync(usdc.address, ds_token.address, 0, redemption_proceeds, sender=borrower)

    # A random EOA is likewise rejected.
    with boa.reverts("unauthorized"):
        mv_vault.mint_sync(usdc.address, ds_token.address, 0, redemption_proceeds, sender=boa.env.generate_address("rando"))

    # Nothing moved: no DS credited, redemption proceeds untouched (would be drainable if mint had run).
    assert mv_vault.pending_transfers(borrower) == 0
    assert mv_vault.pending_transfers_total() == 0
    assert usdc.balanceOf(mv_vault.address) == redemption_proceeds


def test_mint_sync_succeeds_from_caller_over_vault_balance(mv_vault, ds_token, usdc, caller_addr, borrower):
    """Positive control: the SAME mint the borrower was blocked from succeeds when the lending contract calls.

    The vault's pre-funded USDC IS convertible into DS credited to pending_transfers[owner]; the only
    barrier is who may trigger it. With oracle num=1500, den=10**12: ds = 1500e6 * 1e12 // 1500 = 1e18,
    consuming the full 1500e6 USDC.
    """
    stable_coin_amount = 1500 * 10**6
    expected_minted = stable_coin_amount * 10**12 // 1500  # 1e18 DS
    usdc.mint(mv_vault.address, stable_coin_amount)

    minted, refunded = mv_vault.mint_sync(usdc.address, ds_token.address, 0, stable_coin_amount, sender=caller_addr)

    assert minted == expected_minted
    assert refunded == 0  # full spend at this rate
    assert mv_vault.pending_transfers(borrower) == expected_minted  # credited to the owner/borrower
    assert mv_vault.pending_transfers_total() == expected_minted


def test_mint_sync_credits_measured_delta_when_swap_under_delivers(mv_vault, ds_token, usdc, caller_addr, borrower):
    """mint_sync must credit/return the MEASURED DS delivered by swap(), not the pre-swap
    `calculateDsTokenAmount` VIEW estimate.

    We make the AcredMock under-deliver: the view still quotes `full` DS, but swap() delivers only 99% of
    it. mint_sync snapshots balanceOf before swap() and credits the real delta, so `minted`, the vault's
    actual DS balance, and pending_transfers[owner] all equal the DELIVERED amount — the invariant
    (credited == held) that keeps every later withdraw/redeem_manual (which asserts amount <= balanceOf)
    solvent. Crediting `full` instead would over-credit by `full - delivered` and freeze the collateral.
    """
    stable_coin_amount = 1500 * 10**6
    full = stable_coin_amount * 10**12 // 1500  # what the VIEW (calculateDsTokenAmount) quotes: 1e18
    delivered = full * 9900 // 10000  # what swap() actually mints at 99% delivery
    assert delivered < full  # precondition: the swap under-delivers relative to the view
    ds_token.set_swap_delivery_bps(9900)
    usdc.mint(mv_vault.address, stable_coin_amount)

    # precondition: the view really does quote `full`
    assert ds_token.calculateDsTokenAmount(stable_coin_amount)[0] == full

    minted, refunded = mv_vault.mint_sync(usdc.address, ds_token.address, 0, stable_coin_amount, sender=caller_addr)

    # minted is the MEASURED delivery, NOT the view estimate
    assert minted == delivered
    assert minted != full
    # the swap only pulled the stablecoin matching the DELIVERED DS, so the rest is refunded to the vault
    spent = delivered * 1500 // 10**12  # ds * num // den
    assert refunded == stable_coin_amount - spent
    # credited (pending) == held (real DS balance): the solvency invariant
    assert mv_vault.pending_transfers(borrower) == delivered
    assert mv_vault.pending_transfers_total() == delivered
    assert ds_token.balanceOf(mv_vault.address) == delivered
    assert mv_vault.pending_transfers_total() == ds_token.balanceOf(mv_vault.address)


def test_withdraw_funds_zero_amount_makes_no_transfer(mv_vault, zero_revert_erc20, caller_addr):
    """withdraw_funds(token, 0) must not attempt an ERC20 transfer — the settle/liquidation paths call
    it with 0 when the vault holds no leftover payment, and some tokens revert on a 0-value transfer."""
    assert zero_revert_erc20.was_transfer_called() is False
    mv_vault.withdraw_funds(zero_revert_erc20.address, 0, sender=caller_addr)  # must NOT revert
    assert zero_revert_erc20.was_transfer_called() is False


# ============================================================================
# redeem_manual (direct vault-level guards)
# ============================================================================
#
# redeem_manual is exercised indirectly by p2p.redeem() elsewhere; these hit its guards directly.


def test_redeem_manual_reverts_if_not_caller(mv_vault, ds_token, borrower, caller_addr):
    """redeem_manual is caller-only (the lending contract). A non-caller sending DS collateral to an
    arbitrary redemption_vault is a collateral-exfiltration vector — it must revert before any transfer.
    Mirror of the mint_sync caller-guard: both the owner/borrower AND a random EOA are rejected."""
    redemption_vault = boa.env.generate_address("redemption_vault")
    amount = 10**18
    ds_token.mint(mv_vault.address, amount)

    # precondition: the vault holds redeemable DS
    assert ds_token.balanceOf(mv_vault.address) == amount

    # The owner/borrower is rejected.
    with boa.reverts("unauthorized"):
        mv_vault.redeem_manual(redemption_vault, ds_token.address, amount, 1, 1, sender=borrower)

    # A random EOA is likewise rejected.
    with boa.reverts("unauthorized"):
        mv_vault.redeem_manual(redemption_vault, ds_token.address, amount, 1, 1, sender=boa.env.generate_address("rando"))

    # Nothing moved: DS still fully in the vault (would be gone if the transfer had run).
    assert ds_token.balanceOf(mv_vault.address) == amount
    assert ds_token.balanceOf(redemption_vault) == 0


def test_redeem_manual_reverts_when_amount_exceeds_free_balance(mv_vault, ds_token, usdc, borrower, caller_addr):
    """redeem_manual may only move the FREE balance (balanceOf - pending_transfers_total). Pending DS is
    owed to the borrower (credited by a prior mint) and must not be redeemable out from under them.
    Redeeming one unit above (balanceOf - pending) reverts "insufficient balance"."""
    # Create pending DS the real way: a caller mint_sync credits pending_transfers[owner] and mints DS
    # into the vault. 300 USDC -> 3e17 DS at oracle num=1500, den=1e12 (ds = stable * den // num).
    stable_coin_amount = 300 * 10**6
    pending = stable_coin_amount * 10**12 // 1500  # 3e17 DS credited to the owner/borrower
    usdc.mint(mv_vault.address, stable_coin_amount)
    minted, _ = mv_vault.mint_sync(usdc.address, ds_token.address, 0, stable_coin_amount, sender=caller_addr)
    assert minted == pending  # precondition: pending credit established

    # Add extra FREE (unencumbered) DS on top of the pending credit.
    extra_free = 5 * 10**17
    ds_token.mint(mv_vault.address, extra_free)

    balance = ds_token.balanceOf(mv_vault.address)
    pending_total = mv_vault.pending_transfers_total()
    free = balance - pending_total
    # preconditions: exactly `pending` is encumbered, the rest is the free extra
    assert pending_total == pending
    assert free == extra_free

    redemption_vault = boa.env.generate_address("redemption_vault")

    # Redeeming the full free balance is fine (not executed here) but one unit above it must revert:
    # amount_in + pending_transfers_total > balanceOf.
    with boa.reverts("insufficient balance"):
        mv_vault.redeem_manual(redemption_vault, ds_token.address, free + 1, 1, 1, sender=caller_addr)

    # Nothing moved.
    assert ds_token.balanceOf(mv_vault.address) == balance
    assert ds_token.balanceOf(redemption_vault) == 0


def test_redeem_manual_zero_amount_is_noop(mv_vault, zero_revert_erc20, caller_addr):
    """redeem_manual(..., amount_in=0) hits the `if amount_in == 0: return` early return BEFORE the
    balance check and the transfer. Using a token that reverts on a 0-value transfer proves no transfer
    is attempted (mirror of test_withdraw_funds_zero_amount_makes_no_transfer)."""
    assert zero_revert_erc20.was_transfer_called() is False
    redemption_vault = boa.env.generate_address("redemption_vault")
    mv_vault.redeem_manual(redemption_vault, zero_revert_erc20.address, 0, 1, 1, sender=caller_addr)  # no revert
    assert zero_revert_erc20.was_transfer_called() is False


# ============================================================================
# Unsupported-capability stubs (REDEEM_MANUAL vault lacks the async + mint_manual/redeem_sync paths)
# ============================================================================


def test_securitize_mv_unsupported_ops_revert(mv_vault, ds_token, caller_addr):
    """Every capability SecuritizeMV does NOT implement is a stub that `raise`s immediately (before any
    caller guard or state access), so any sender triggers the revert. Locks the exact strings."""
    v = mv_vault
    dummy = boa.env.generate_address("dummy")

    with boa.reverts("mint_async not supported"):
        v.mint_async(ds_token.address, dummy, 0, 0, sender=caller_addr)
    with boa.reverts("mint_manual not supported"):
        v.mint_manual(ds_token.address, dummy, 0, 0, sender=caller_addr)
    with boa.reverts("mint_status not supported"):
        v.mint_status(dummy, sender=caller_addr)
    with boa.reverts("claim_mint not supported"):
        v.claim_mint(dummy, True, True, sender=caller_addr)
    with boa.reverts("cancel_mint not supported"):
        v.cancel_mint(dummy, sender=caller_addr)
    with boa.reverts("redeem_sync not supported"):
        v.redeem_sync(dummy, ds_token.address, 0, 1, 1, sender=caller_addr)
    with boa.reverts("redeem_async not supported"):
        v.redeem_async(dummy, ds_token.address, 0, 1, 1, sender=caller_addr)
    with boa.reverts("redeem_status not supported"):
        v.redeem_status(dummy, sender=caller_addr)
    with boa.reverts("claim_redeem not supported"):
        v.claim_redeem(dummy, True, True, sender=caller_addr)
    with boa.reverts("cancel_redeem not supported"):
        v.cancel_redeem(dummy, sender=caller_addr)
