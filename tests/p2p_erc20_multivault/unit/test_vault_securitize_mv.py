"""Focused unit tests for P2PLendingVaultSecuritizeMV (the MultiVault Securitize vault).

This is the MV vault (`P2PLendingVaultSecuritizeMV.vy`, caps MINT_SYNC | REDEEM_MANUAL), NOT the legacy
`P2PLendingVaultSecuritize.vy` exercised by test_vault_securitize.py (which has buy()/_check_user/proxies).

Security regression: `mint_sync` is caller-only (`assert msg.sender == self.caller`). Under the MultiVault
funding model (D2) the vault spends its OWN pre-funded balance, so an owner-callable mint_sync would let
the borrower convert any payment token sitting in the loan vault (e.g. redemption proceeds awaiting the
manual-redeem settle) into DS credited to pending_transfers[owner] and drain it via withdraw_pending — a
real theft vector during the SecuritizeMV manual-redeem settle window. The prior `_check_user(self.owner)`
owner path (and its P2PLendingContract interface) were deleted; only the lending contract may call.

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
    """Regression: a borrower/owner-sender mint_sync over the vault's payment balance reverts "unauthorized".

    Pre-fix this would have SUCCEEDED — converting the vault's USDC (redemption proceeds awaiting settle)
    into DS credited to pending_transfers[owner], drainable via withdraw_pending (the theft vector).
    We fund the vault with USDC as if redemption proceeds landed in it, then the borrower attempts to
    convert the FULL vault balance. It must be rejected before any swap occurs.
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

    This proves the ONLY barrier in the theft test was the caller check — the vault's pre-funded USDC IS
    convertible into DS credited to pending_transfers[owner]; the fix is purely who may trigger it.
    With oracle num=1500, den=10**12: ds = 1500e6 * 1e12 // 1500 = 1e18, consuming the full 1500e6 USDC.
    """
    stable_coin_amount = 1500 * 10**6
    expected_minted = stable_coin_amount * 10**12 // 1500  # 1e18 DS
    usdc.mint(mv_vault.address, stable_coin_amount)

    minted, refunded = mv_vault.mint_sync(usdc.address, ds_token.address, 0, stable_coin_amount, sender=caller_addr)

    assert minted == expected_minted
    assert refunded == 0  # full spend at this rate
    assert mv_vault.pending_transfers(borrower) == expected_minted  # credited to the owner/borrower
    assert mv_vault.pending_transfers_total() == expected_minted
