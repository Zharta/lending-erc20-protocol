from textwrap import dedent

import boa
import pytest


@pytest.fixture
def simple_vault(vault_contract_def, owner, weth):
    """Vault using WETH for direct deposit/withdraw testing."""
    v = vault_contract_def.deploy()
    v.initialise(owner, weth.address, sender=owner)
    return v


def test_deposit_with_pending_covers_full_amount(simple_vault, weth, owner):
    """Covers branch: if pending >= amount (deposit uses pending transfers, no transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    deposit_amount = 60

    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(simple_vault.address, pending_amount, sender=owner)

    simple_vault.deposit(deposit_amount, wallet, sender=owner)

    assert simple_vault.pending_transfers(wallet) == pending_amount - deposit_amount
    assert simple_vault.pending_transfers_total() == pending_amount - deposit_amount


def test_deposit_with_partial_pending(simple_vault, weth, owner):
    """Covers branch: elif pending > 0 (partial pending used, rest from transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 40
    deposit_amount = 100

    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(simple_vault.address, pending_amount, sender=owner)

    transfer_amount = deposit_amount - pending_amount
    boa.env.set_balance(wallet, transfer_amount)
    weth.deposit(value=transfer_amount, sender=wallet)
    weth.approve(simple_vault.address, transfer_amount, sender=wallet)

    simple_vault.deposit(deposit_amount, wallet, sender=owner)

    assert simple_vault.pending_transfers(wallet) == 0
    assert simple_vault.pending_transfers_total() == 0
    assert weth.balanceOf(simple_vault.address) == deposit_amount


def test_withdraw_pending(simple_vault, weth, owner):
    """Covers: withdraw_pending function (lines 139-143)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    withdraw_amount = 60

    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(simple_vault.address, pending_amount, sender=owner)

    balance_before = weth.balanceOf(wallet)
    simple_vault.withdraw_pending(withdraw_amount, sender=wallet)

    assert weth.balanceOf(wallet) == balance_before + withdraw_amount
    assert simple_vault.pending_transfers(wallet) == pending_amount - withdraw_amount
    assert simple_vault.pending_transfers_total() == pending_amount - withdraw_amount


def test_withdraw_pending_reverts_if_insufficient(simple_vault):
    """Covers: withdraw_pending revert when amount > pending."""
    wallet = boa.env.generate_address()
    simple_vault.eval(f"self.pending_transfers[{wallet}] = 10")
    simple_vault.eval("self.pending_transfers_total = 10")

    with boa.reverts("insufficient pending collateral"):
        simple_vault.withdraw_pending(11, sender=wallet)


def test_withdraw_creates_pending_on_transfer_failure(vault_contract_def, owner):
    """Covers branch: withdraw with transfer failure creates pending transfer (lines 124-127)."""
    failing_erc20 = boa.loads(
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

    vault = vault_contract_def.deploy()
    vault.initialise(owner, failing_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    deposit_amount = 100

    vault.deposit(deposit_amount, wallet, sender=owner)
    assert failing_erc20.balanceOf(vault.address) == deposit_amount

    vault.withdraw(deposit_amount, wallet, sender=owner)

    assert vault.pending_transfers(wallet) == deposit_amount
    assert vault.pending_transfers_total() == deposit_amount
