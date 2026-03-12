from textwrap import dedent

import boa
import pytest


def get_transfer_events(entry_contract, token_address, sender, receiver):
    """Return Transfer events for a given token emitted during the last call to entry_contract."""
    return [
        e
        for e in entry_contract.get_logs()
        if type(e).__name__ == "Transfer" and e.address == token_address and e.sender == sender and e.receiver == receiver
    ]


@pytest.fixture
def oracle_buy(oracle_contract_def):
    """Oracle with rate 3/10 to produce rounding in swaps."""
    return oracle_contract_def.deploy(1, 3)


@pytest.fixture
def usdc_buy(weth9_contract_def, owner):
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


@pytest.fixture
def acred_contract_def():
    return boa.load_partial("contracts/auxiliary/AcredMock.vy")


@pytest.fixture
def acred(acred_contract_def, oracle_buy, usdc_buy):
    return acred_contract_def.deploy(10**6, oracle_buy.address, usdc_buy.address)


@pytest.fixture
def vault(securitize_vault_contract_def, owner, acred):
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, acred.address, sender=owner)
    return v


@pytest.fixture
def simple_vault(securitize_vault_contract_def, owner, weth):
    """Vault using a standard ERC20 (WETH) for direct deposit/withdraw testing."""
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, weth.address, sender=owner)
    return v


def test_buy_no_transfer_when_remaining_equals_initial(vault, acred, usdc_buy, owner):
    """When remaining_balance == initial_balance (both zero), no stablecoin transfer back occurs.

    With oracle rate 3/10:
    - swap(10): _dsTokenAmount = 10*3//10 = 3, _liquidityAmount = 3*10//3 = 10
    - All stablecoins consumed exactly, remaining_balance == initial_balance == 0
    """
    stable_amount = 10
    usdc_buy.mint(owner, stable_amount)
    usdc_buy.approve(vault.address, stable_amount, sender=owner)

    vault.buy(usdc_buy.address, 0, stable_amount, sender=owner)

    refund_transfers = get_transfer_events(vault, usdc_buy.address, vault.address, owner)
    assert len(refund_transfers) == 0
    assert usdc_buy.balanceOf(vault.address) == 0
    assert vault.pending_transfers(owner) == 10 * 10 // 3  # calculateDsTokenAmount
    assert vault.pending_transfers_total() == 10 * 10 // 3


def test_buy_no_transfer_when_remaining_equals_initial_nonzero(vault, acred, usdc_buy, owner):
    """When vault has pre-existing stablecoin balance and remaining == initial, no transfer occurs."""
    preexisting = 100
    usdc_buy.mint(owner, preexisting)
    usdc_buy.transfer(vault.address, preexisting, sender=owner)
    assert usdc_buy.balanceOf(vault.address) == preexisting

    stable_amount = 10
    usdc_buy.mint(owner, stable_amount)
    usdc_buy.approve(vault.address, stable_amount, sender=owner)

    vault.buy(usdc_buy.address, 0, stable_amount, sender=owner)

    # only transfer to vault is the pre-seeding, no refund from vault to owner
    refund_transfers = get_transfer_events(vault, usdc_buy.address, vault.address, owner)
    assert len(refund_transfers) == 0
    assert usdc_buy.balanceOf(vault.address) == preexisting
    assert vault.pending_transfers(owner) == 10 * 10 // 3
    assert vault.pending_transfers_total() == 10 * 10 // 3


def test_buy_transfers_excess_when_remaining_exceeds_initial(vault, acred, usdc_buy, owner):
    """When remaining_balance > initial_balance, excess stablecoins are transferred back.

    With oracle rate 3/10:
    - swap(11): _dsTokenAmount = 11*3//10 = 3, _liquidityAmount = 3*10//3 = 10
    - Only 10 of 11 stablecoins consumed, 1 returned to sender
    """
    stable_amount = 11
    usdc_buy.mint(owner, stable_amount)
    usdc_buy.approve(vault.address, stable_amount, sender=owner)

    vault.buy(usdc_buy.address, 0, stable_amount, sender=owner)

    refund_transfers = get_transfer_events(vault, usdc_buy.address, vault.address, owner)
    assert len(refund_transfers) == 1
    assert refund_transfers[0].value == 1
    assert usdc_buy.balanceOf(vault.address) == 0
    assert vault.pending_transfers(owner) == 11 * 10 // 3
    assert vault.pending_transfers_total() == 11 * 10 // 3


# --- Vault deposit with pending transfers ---


def test_deposit_with_pending_covers_full_amount(simple_vault, weth, owner):
    """Covers branch: if pending >= amount (deposit uses pending transfers, no transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    deposit_amount = 60

    # Seed pending transfers
    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    # Vault needs the tokens to have correct balance accounting
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

    # wallet needs tokens and approval for the remainder
    transfer_amount = deposit_amount - pending_amount
    boa.env.set_balance(wallet, transfer_amount)
    weth.deposit(value=transfer_amount, sender=wallet)
    weth.approve(simple_vault.address, transfer_amount, sender=wallet)

    simple_vault.deposit(deposit_amount, wallet, sender=owner)

    assert simple_vault.pending_transfers(wallet) == 0
    assert simple_vault.pending_transfers_total() == 0
    assert weth.balanceOf(simple_vault.address) == deposit_amount


# --- Vault withdraw_pending ---


def test_withdraw_pending(simple_vault, weth, owner):
    """Covers: withdraw_pending (lines 167-171)."""
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


def test_withdraw_pending_reverts_if_insufficient(simple_vault, weth, owner):
    """Covers: withdraw_pending revert when amount > pending."""
    wallet = boa.env.generate_address()
    simple_vault.eval(f"self.pending_transfers[{wallet}] = 10")
    simple_vault.eval("self.pending_transfers_total = 10")

    with boa.reverts("insufficient pending collateral"):
        simple_vault.withdraw_pending(11, sender=wallet)


# --- Vault transfer_funds with amount=0 ---


def test_transfer_funds_with_zero_amount(simple_vault, weth, owner):
    """Covers branch: if amount > 0 FALSE path in transfer_funds (line 198)."""
    wallet = boa.env.generate_address()
    balance_before = weth.balanceOf(wallet)

    simple_vault.transfer_funds(weth.address, 0, wallet, sender=owner)

    assert weth.balanceOf(wallet) == balance_before


# --- Vault withdraw transfer failure ---


def test_withdraw_creates_pending_on_transfer_failure(securitize_vault_contract_def, owner):
    """Covers branch: withdraw with transfer failure creates pending transfer (lines 141-144)."""

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

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, failing_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    deposit_amount = 100

    # Deposit (transferFrom succeeds, balance tracked on vault)
    vault.deposit(deposit_amount, wallet, sender=owner)
    assert failing_erc20.balanceOf(vault.address) == deposit_amount

    # Withdraw (transfer fails → creates pending)
    vault.withdraw(deposit_amount, wallet, sender=owner)

    assert vault.pending_transfers(wallet) == deposit_amount
    assert vault.pending_transfers_total() == deposit_amount
