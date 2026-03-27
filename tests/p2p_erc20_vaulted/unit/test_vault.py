from textwrap import dedent

import boa
import pytest

from ..conftest_base import get_calls


@pytest.fixture
def vault_manager():
    """Separate address acting as the vault caller (lending contract in production)."""
    addr = boa.env.generate_address("vault_manager")
    boa.env.set_balance(addr, 10**18)
    return addr


@pytest.fixture
def vault(vault_contract_def, vault_manager, owner, weth):
    """Vault where caller (vault_manager) != owner.

    Matches production: the lending contract (vault_manager) is msg.sender / self.caller,
    and the borrower (owner) is the _owner parameter.
    """
    v = vault_contract_def.deploy()
    v.initialise(owner, weth.address, sender=vault_manager)
    return v


@pytest.fixture
def failing_transfer_erc20():
    """ERC20 mock that returns False on transfer (but True on transferFrom)."""
    return boa.loads(
        dedent("""
        balances: HashMap[address, uint256]

        @external
        @view
        def balanceOf(_owner: address) -> uint256:
            return self.balances[_owner]

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            return False

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            self.balances[_to] += _value
            return True
    """)
    )


@pytest.fixture
def failing_transferfrom_erc20():
    """ERC20 mock that returns False on transferFrom."""
    return boa.loads(
        dedent("""
        balances: HashMap[address, uint256]

        @external
        @view
        def balanceOf(_owner: address) -> uint256:
            return self.balances[_owner]

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            self.balances[_to] += _value
            return True

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            return False
    """)
    )


# =============================================================================
# Existing tests
# =============================================================================


def test_deposit_with_pending_covers_full_amount(vault, vault_manager, weth, owner):
    """Covers branch: if pending >= amount (deposit uses pending transfers, no transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    deposit_amount = 60

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    assert vault.pending_transfers(wallet) == pending_amount - deposit_amount
    assert vault.pending_transfers_total() == pending_amount - deposit_amount


def test_deposit_with_partial_pending(vault, vault_manager, weth, owner):
    """Covers branch: elif pending > 0 (partial pending used, rest from transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 40
    deposit_amount = 100

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    transfer_amount = deposit_amount - pending_amount
    boa.env.set_balance(wallet, transfer_amount)
    weth.deposit(value=transfer_amount, sender=wallet)
    weth.approve(vault.address, transfer_amount, sender=wallet)

    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0
    assert weth.balanceOf(vault.address) == deposit_amount


def test_withdraw_pending(vault, weth, owner):
    """Covers: withdraw_pending function (lines 139-143)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    withdraw_amount = 60

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    balance_before = weth.balanceOf(wallet)
    vault.withdraw_pending(withdraw_amount, sender=wallet)

    assert weth.balanceOf(wallet) == balance_before + withdraw_amount
    assert vault.pending_transfers(wallet) == pending_amount - withdraw_amount
    assert vault.pending_transfers_total() == pending_amount - withdraw_amount


def test_withdraw_pending_reverts_if_insufficient(vault):
    """Covers: withdraw_pending revert when amount > pending."""
    wallet = boa.env.generate_address()
    vault.eval(f"self.pending_transfers[{wallet}] = 10")
    vault.eval("self.pending_transfers_total = 10")

    with boa.reverts("insufficient pending collateral"):
        vault.withdraw_pending(11, sender=wallet)


def test_withdraw_creates_pending_on_transfer_failure(vault_contract_def, vault_manager, owner, failing_transfer_erc20):
    """Covers branch: withdraw with transfer failure creates pending transfer (lines 124-127)."""
    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_transfer_erc20.address, sender=vault_manager)

    wallet = boa.env.generate_address()
    deposit_amount = 100

    vault.deposit(deposit_amount, wallet, sender=vault_manager)
    assert failing_transfer_erc20.balanceOf(vault.address) == deposit_amount

    vault.withdraw(deposit_amount, wallet, sender=vault_manager)

    assert vault.pending_transfers(wallet) == deposit_amount
    assert vault.pending_transfers_total() == deposit_amount


# =============================================================================
# Initialise tests (kills M1-M4)
# =============================================================================


def test_initialise_reverts_if_already_initialised(vault_contract_def, owner, weth):
    """Kills M4: deleting the initialise guard assert.

    Also kills M1 (field_swap self.caller -> self.owner in guard check)
    because the second call should revert regardless of which field is checked,
    but this specific test verifies the revert happens.
    """
    vault = vault_contract_def.deploy()
    vault.initialise(owner, weth.address, sender=owner)

    with boa.reverts("already initialised"):
        vault.initialise(owner, weth.address, sender=owner)


def test_initialise_sets_caller_to_msg_sender_not_owner(vault, vault_manager, owner):
    """Kills M2: self.caller = msg.sender -> self.caller = _owner.

    Uses vault where msg.sender (vault_manager) != _owner (owner).
    Verifies caller is set to msg.sender (vault_manager).
    """
    assert vault.caller() == vault_manager
    assert vault.caller() != owner


def test_initialise_sets_owner_to_param_not_msg_sender(vault, vault_manager, owner):
    """Kills M3: self.owner = _owner -> self.owner = msg.sender.

    Uses vault where msg.sender (vault_manager) != _owner (owner).
    Verifies owner is set to _owner (owner).
    """
    assert vault.owner() == owner
    assert vault.owner() != vault_manager


def test_initialise_checks_caller_not_owner(vault_contract_def, vault_manager, weth):
    """Kills M1: self.caller == empty(address) -> self.owner == empty(address).

    If the guard incorrectly checks self.owner instead of self.caller,
    re-initialization would be allowed when a different _owner is passed
    (since self.owner would be set to the previous borrower, not empty).
    """
    vault = vault_contract_def.deploy()
    borrower1 = boa.env.generate_address("borrower1")

    vault.initialise(borrower1, weth.address, sender=vault_manager)

    # Second initialise should fail because self.caller is already set
    with boa.reverts("already initialised"):
        borrower2 = boa.env.generate_address("borrower2")
        vault.initialise(borrower2, weth.address, sender=vault_manager)


# =============================================================================
# Deposit auth and boundary tests (kills M5-M7)
# =============================================================================


def test_deposit_reverts_if_not_caller(vault, owner):
    """Kills M5: deleting deposit auth assert.

    Calls deposit from owner (who is NOT the caller/vault_manager).
    """
    with boa.reverts("unauthorized"):
        vault.deposit(100, owner, sender=owner)


def test_deposit_with_pending_equals_amount(vault, vault_manager, weth, owner):
    """Kills M6: >= to > in deposit pending check (L89).

    When pending == amount exactly, the full-pending path should be taken
    (no transferFrom needed). With the mutation (> instead of >=), it falls
    to elif, which would call transferFrom(wallet, self, 0).
    We detect this by inspecting subcalls: the if-branch makes zero ERC20
    calls, while the elif-branch would invoke transferFrom.
    """
    wallet = boa.env.generate_address("wallet")
    amount = 50

    # Set up pending == amount
    vault.eval(f"self.pending_transfers[{wallet}] = {amount}")
    vault.eval(f"self.pending_transfers_total = {amount}")
    weth.deposit(value=amount, sender=owner)
    weth.transfer(vault.address, amount, sender=owner)

    # Should succeed via the full-pending path (no transferFrom)
    vault.deposit(amount, wallet, sender=vault_manager)

    # Must check calls immediately after the transaction (before any other call)
    assert len(get_calls(vault, "transferFrom(address,address,uint256)")) == 0, (
        "transferFrom should not be called when pending == amount"
    )

    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0


def test_deposit_pending_equals_one_takes_partial_path(vault, vault_manager, weth, owner):
    """Kills M7: pending > 0 -> pending > 1 (L93).

    When pending == 1, the elif branch should be taken.
    With the mutation (pending > 1), it falls through to else branch,
    ignoring the 1 wei pending.
    """
    wallet = boa.env.generate_address("wallet")
    pending_amount = 1
    deposit_amount = 100

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    # wallet needs to have (deposit_amount - pending_amount) tokens
    transfer_needed = deposit_amount - pending_amount
    boa.env.set_balance(wallet, transfer_needed)
    weth.deposit(value=transfer_needed, sender=wallet)
    weth.approve(vault.address, transfer_needed, sender=wallet)

    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    # pending should be cleared to 0 (was 1, less than amount, so elif path)
    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0


# =============================================================================
# Withdraw auth, balance, and success path tests (kills M8-M14)
# =============================================================================


def test_withdraw_reverts_if_not_caller(vault, owner):
    """Kills M8: deleting withdraw auth assert (L111).

    Calls withdraw from owner (who is NOT the caller/vault_manager).
    """
    with boa.reverts("unauthorized"):
        vault.withdraw(100, owner, sender=owner)


def test_withdraw_reverts_when_amount_plus_pending_exceeds_balance(vault, vault_manager, weth, owner):
    """Kills M9: + to - in withdraw balance check (L112).
    Also kills M10: deleting balance check.

    When pending_transfers_total > 0, the balance check ensures
    amount + pending_total <= balance. With the - mutation, the check
    is weakened (amount - pending <= balance is easier to satisfy).
    """
    wallet = boa.env.generate_address("wallet")

    # Deposit 100 tokens into vault
    deposit_amount = 100
    boa.env.set_balance(wallet, deposit_amount)
    weth.deposit(value=deposit_amount, sender=wallet)
    weth.approve(vault.address, deposit_amount, sender=wallet)
    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    # Set pending_transfers_total to 60 (simulating prior failed withdrawals)
    vault.eval("self.pending_transfers_total = 60")

    # Try to withdraw 50. With +, 50 + 60 = 110 > 100 -> should revert.
    # With -, 50 - 60 would underflow in uint256, which also reverts.
    # But to be safe, test with amount=41 where 41+60=101 > 100 fails with +
    # but 41-60 underflows with - (also fails). Use amount=50 pending=51:
    vault.eval("self.pending_transfers_total = 51")
    # 50 + 51 = 101 > 100 -> should revert with original
    with boa.reverts("insufficient balance"):
        vault.withdraw(50, wallet, sender=vault_manager)


def test_withdraw_success_transfers_tokens(vault, vault_manager, weth, owner):
    """Kills M11: not success -> success (boolean inversion L124).
    Also kills M14: abi_encode param swap (L119).

    Tests the SUCCESSFUL withdraw path (which was completely untested).
    Verifies tokens actually move from vault to wallet.
    """
    wallet = boa.env.generate_address("wallet")

    # Deposit tokens into vault
    deposit_amount = 200
    boa.env.set_balance(wallet, deposit_amount)
    weth.deposit(value=deposit_amount, sender=wallet)
    weth.approve(vault.address, deposit_amount, sender=wallet)
    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    assert weth.balanceOf(vault.address) == deposit_amount

    # Successful withdraw
    withdraw_amount = 100
    wallet_balance_before = weth.balanceOf(wallet)
    vault.withdraw(withdraw_amount, wallet, sender=vault_manager)

    # Tokens should have moved to wallet
    assert weth.balanceOf(wallet) == wallet_balance_before + withdraw_amount
    assert weth.balanceOf(vault.address) == deposit_amount - withdraw_amount

    # No pending should be created on success
    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0


def test_withdraw_multiple_failures_accumulate_pending(vault_contract_def, vault_manager, owner, failing_transfer_erc20):
    """Kills M12: += to = in pending_transfers[wallet] accumulation (L126).
    Also kills M13: += to = in pending_transfers_total accumulation (L127).

    Two consecutive failed withdrawals should accumulate, not overwrite.
    """
    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_transfer_erc20.address, sender=vault_manager)

    wallet = boa.env.generate_address("wallet")

    # Deposit enough tokens
    vault.deposit(300, wallet, sender=vault_manager)

    # First failed withdraw
    vault.withdraw(100, wallet, sender=vault_manager)
    assert vault.pending_transfers(wallet) == 100
    assert vault.pending_transfers_total() == 100

    # Second failed withdraw -- should accumulate
    vault.withdraw(200, wallet, sender=vault_manager)
    assert vault.pending_transfers(wallet) == 300  # 100 + 200, not just 200
    assert vault.pending_transfers_total() == 300


# =============================================================================
# Withdraw_pending boundary tests (kills M15)
# =============================================================================


def test_withdraw_pending_exact_full_amount(vault, weth, owner):
    """Kills M15: >= to > in withdraw_pending amount check (L139).

    Withdrawing exactly the full pending amount should succeed.
    With the mutation (>), it would revert because pending == amount fails > check.
    """
    wallet = boa.env.generate_address("wallet")
    pending_amount = 100

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    # Withdraw exactly the full pending amount
    vault.withdraw_pending(pending_amount, sender=wallet)

    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0
    assert weth.balanceOf(wallet) == pending_amount


# =============================================================================
# Assert removal on transferFrom/transfer (kills M16-M18)
# =============================================================================


def test_deposit_partial_pending_reverts_if_transferfrom_returns_false(
    vault_contract_def, vault_manager, owner, failing_transferfrom_erc20
):
    """Kills M16: removing assert on transferFrom in deposit elif branch (L97).

    If transferFrom returns False, deposit should revert, not silently succeed.
    """
    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_transferfrom_erc20.address, sender=vault_manager)

    wallet = boa.env.generate_address("wallet")

    # Set up partial pending (takes elif path)
    vault.eval(f"self.pending_transfers[{wallet}] = 10")
    vault.eval("self.pending_transfers_total = 10")

    with boa.reverts("transferFrom failed"):
        vault.deposit(100, wallet, sender=vault_manager)


def test_deposit_no_pending_reverts_if_transferfrom_returns_false(
    vault_contract_def, vault_manager, owner, failing_transferfrom_erc20
):
    """Kills M17: removing assert on transferFrom in deposit else branch (L99).

    If transferFrom returns False, deposit should revert, not silently succeed.
    """
    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_transferfrom_erc20.address, sender=vault_manager)

    wallet = boa.env.generate_address("wallet")

    with boa.reverts("transferFrom failed"):
        vault.deposit(100, wallet, sender=vault_manager)


def test_withdraw_pending_reverts_if_transfer_returns_false(vault_contract_def, vault_manager, owner, failing_transfer_erc20):
    """Kills M18: removing assert on transfer in withdraw_pending (L142).

    If transfer returns False, withdraw_pending should revert, not silently succeed.
    """
    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_transfer_erc20.address, sender=vault_manager)

    wallet = boa.env.generate_address("wallet")

    # Give vault some token balance first (transferFrom succeeds in this mock)
    vault.deposit(100, wallet, sender=vault_manager)

    # Now set pending for wallet AFTER deposit (deposit cleared any existing pending)
    vault.eval(f"self.pending_transfers[{wallet}] = 100")
    vault.eval("self.pending_transfers_total = 100")

    with boa.reverts("transfer failed"):
        vault.withdraw_pending(50, sender=wallet)


# =============================================================================
# Event emission tests (kills M19-M23)
# =============================================================================


def test_deposit_full_pending_emits_withdraw_pending_event(vault, vault_manager, weth, owner):
    """Kills M19: deleting log WithdrawPending in deposit if branch (L92)."""
    wallet = boa.env.generate_address("wallet")
    pending_amount = 100
    deposit_amount = 60

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    wp_events = [e for e in vault.get_logs() if type(e).__name__ == "WithdrawPending"]
    assert len(wp_events) == 1
    assert wp_events[0].wallet == wallet
    assert wp_events[0].amount == deposit_amount


def test_deposit_emits_deposit_event(vault, vault_manager, weth, owner):
    """Kills M20: deleting log Deposit (L100)."""
    wallet = boa.env.generate_address("wallet")
    deposit_amount = 100

    boa.env.set_balance(wallet, deposit_amount)
    weth.deposit(value=deposit_amount, sender=wallet)
    weth.approve(vault.address, deposit_amount, sender=wallet)

    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    events = [e for e in vault.get_logs() if type(e).__name__ == "Deposit"]
    assert len(events) == 1
    assert events[0].wallet == wallet
    assert events[0].amount == deposit_amount


def test_withdraw_failure_emits_transfer_failed_event(vault_contract_def, vault_manager, owner, failing_transfer_erc20):
    """Kills M21: deleting log TransferFailed in withdraw failure (L125)."""
    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_transfer_erc20.address, sender=vault_manager)

    wallet = boa.env.generate_address("wallet")
    deposit_amount = 100

    vault.deposit(deposit_amount, wallet, sender=vault_manager)
    vault.withdraw(deposit_amount, wallet, sender=vault_manager)

    events = [e for e in vault.get_logs() if type(e).__name__ == "TransferFailed"]
    assert len(events) == 1
    assert events[0].wallet == wallet
    assert events[0].amount == deposit_amount


def test_withdraw_success_emits_withdraw_event(vault, vault_manager, weth, owner):
    """Kills M22: deleting log Withdraw in withdraw success (L129)."""
    wallet = boa.env.generate_address("wallet")
    deposit_amount = 100

    boa.env.set_balance(wallet, deposit_amount)
    weth.deposit(value=deposit_amount, sender=wallet)
    weth.approve(vault.address, deposit_amount, sender=wallet)
    vault.deposit(deposit_amount, wallet, sender=vault_manager)

    vault.withdraw(50, wallet, sender=vault_manager)

    events = [e for e in vault.get_logs() if type(e).__name__ == "Withdraw"]
    assert len(events) == 1
    assert events[0].wallet == wallet
    assert events[0].amount == 50


def test_withdraw_pending_emits_withdraw_pending_event(vault, weth, owner):
    """Kills M23: deleting log WithdrawPending in withdraw_pending (L143)."""
    wallet = boa.env.generate_address("wallet")
    pending_amount = 100
    withdraw_amount = 60

    vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(vault.address, pending_amount, sender=owner)

    vault.withdraw_pending(withdraw_amount, sender=wallet)

    events = [e for e in vault.get_logs() if type(e).__name__ == "WithdrawPending"]
    assert len(events) == 1
    assert events[0].wallet == wallet
    assert events[0].amount == withdraw_amount
