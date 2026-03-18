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


@pytest.fixture
def p2p_mock_contract():
    """Mock P2PLendingContract that implements authorized_proxies."""
    return boa.loads(
        dedent("""
        authorized: HashMap[address, bool]

        @external
        def authorized_proxies(proxy: address) -> bool:
            return self.authorized[proxy]

        @external
        def set_proxy(proxy: address, is_authorized: bool):
            self.authorized[proxy] = is_authorized
    """)
    )


@pytest.fixture
def vault_separate_owner(securitize_vault_contract_def, acred, p2p_mock_contract):
    """Vault where owner != caller for access control testing."""
    vault_owner = boa.env.generate_address("vault_owner")
    v = securitize_vault_contract_def.deploy()
    v.initialise(vault_owner, acred.address, sender=p2p_mock_contract.address)
    return v, vault_owner, p2p_mock_contract


def test_buy_skips_refund_when_remaining_equals_initial(vault, acred, usdc_buy, owner):
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


def test_buy_skips_refund_when_remaining_equals_initial_nonzero(vault, acred, usdc_buy, owner):
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


def test_buy_refunds_excess_when_remaining_exceeds_initial(vault, acred, usdc_buy, owner):
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


def test_buy_updates_pending_when_called_by_owner(vault_separate_owner, acred, usdc_buy, oracle_buy):
    """Kills mutation: L211 `self._check_user(self.owner)` -> `self._check_user(self.caller)`.

    The buy function should authorize based on owner, not caller. When owner != caller,
    only the owner should be able to call buy.
    """
    vault, vault_owner, p2p_mock = vault_separate_owner
    assert vault_owner != p2p_mock.address  # precondition: owner != caller

    stable_amount = 10
    usdc_buy.mint(vault_owner, stable_amount)
    usdc_buy.approve(vault.address, stable_amount, sender=vault_owner)

    vault.buy(usdc_buy.address, 0, stable_amount, sender=vault_owner)

    expected_ds_tokens = stable_amount * 10 // 3  # oracle rate 3, decimals 1
    assert vault.pending_transfers(vault_owner) == expected_ds_tokens
    assert vault.pending_transfers_total() == expected_ds_tokens


def test_buy_reverts_if_unauthorized_caller(vault_separate_owner, acred, usdc_buy, oracle_buy):
    """The caller (p2p_mock) that initialized the vault should NOT be able to call buy."""
    vault, vault_owner, p2p_mock = vault_separate_owner
    assert vault_owner != p2p_mock.address  # precondition: owner != caller

    stable_amount = 10
    usdc_buy.mint(p2p_mock.address, stable_amount)
    usdc_buy.approve(vault.address, stable_amount, sender=p2p_mock.address)

    with boa.reverts("unauthorized"):
        vault.buy(usdc_buy.address, 0, stable_amount, sender=p2p_mock.address)


def test_buy_succeeds_when_ds_token_equals_min(
    securitize_vault_contract_def, acred_contract_def, oracle_contract_def, weth9_contract_def, owner
):
    """Kills mutation: L216 `>=` -> `>` in buy min_ds_token check.

    When min_ds_token_amount equals the calculated amount exactly, buy should
    succeed (not revert). Uses 1:1 oracle rate so calculateDsTokenAmount and
    swap both return the same value.
    """
    oracle_1to1 = oracle_contract_def.deploy(1, 10)
    usdc_1to1 = weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)
    acred_1to1 = acred_contract_def.deploy(10**6, oracle_1to1.address, usdc_1to1.address)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred_1to1.address, sender=owner)

    stable_amount = 100
    # With rate=10, decimals=1: calculateDsTokenAmount(100) = 100 * 10 // 10 = 100
    expected_ds_tokens = 100
    assert expected_ds_tokens == stable_amount  # precondition: 1:1 rate produces boundary condition

    usdc_1to1.mint(owner, stable_amount)
    usdc_1to1.approve(vault.address, stable_amount, sender=owner)

    # This should succeed with min == exact calculated amount
    vault.buy(usdc_1to1.address, expected_ds_tokens, stable_amount, sender=owner)

    assert vault.pending_transfers(owner) == expected_ds_tokens
    assert vault.pending_transfers_total() == expected_ds_tokens


def test_buy_reverts_if_ds_token_below_min(
    securitize_vault_contract_def, acred_contract_def, oracle_contract_def, weth9_contract_def, owner
):
    """Validates that buy reverts when calculated ds_token_amount < min_ds_token_amount."""
    oracle_1to1 = oracle_contract_def.deploy(1, 10)
    usdc_1to1 = weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)
    acred_1to1 = acred_contract_def.deploy(10**6, oracle_1to1.address, usdc_1to1.address)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred_1to1.address, sender=owner)

    stable_amount = 100

    usdc_1to1.mint(owner, stable_amount)
    usdc_1to1.approve(vault.address, stable_amount, sender=owner)

    with boa.reverts("ds token amount lt min"):
        vault.buy(usdc_1to1.address, 101, stable_amount, sender=owner)


def test_buy_credits_pending_to_owner_not_sender(
    securitize_vault_contract_def, acred_contract_def, oracle_contract_def, weth9_contract_def, owner
):
    """Kills mutation: L223 `self.pending_transfers[self.owner]` -> `self.pending_transfers[msg.sender]`.

    DS tokens from buy should be credited to self.owner (the borrower), not msg.sender.
    Uses a proxy contract to call buy so msg.sender != self.owner, exercising the
    proxy path in _check_user.
    """
    # Set up fresh contracts with 1:1 oracle for simplicity
    oracle = oracle_contract_def.deploy(1, 10)
    usdc = weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)
    acred = acred_contract_def.deploy(10**6, oracle.address, usdc.address)

    # Create mock P2P lending contract that tracks authorized proxies
    p2p_mock = boa.loads(
        dedent("""
        authorized: HashMap[address, bool]

        @external
        def authorized_proxies(proxy: address) -> bool:
            return self.authorized[proxy]

        @external
        def set_proxy(proxy: address, is_authorized: bool):
            self.authorized[proxy] = is_authorized
    """)
    )

    # Create a proxy contract that calls vault.buy()
    buy_proxy = boa.loads(
        dedent("""
        from ethereum.ercs import IERC20

        interface VaultBuy:
            def buy(payment_token: address, min_ds_token_amount: uint256, stable_coin_amount: uint256): nonpayable

        @external
        def proxy_buy(vault: address, payment_token: address, min_ds_token: uint256, stable_amount: uint256):
            extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_amount)
            extcall IERC20(payment_token).approve(vault, stable_amount)
            extcall VaultBuy(vault).buy(payment_token, min_ds_token, stable_amount)
    """)
    )

    # Initialize vault: owner is 'owner' (the test EOA), caller is p2p_mock
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred.address, sender=p2p_mock.address)

    # Authorize the proxy
    p2p_mock.set_proxy(buy_proxy.address, True)

    # Fund and approve
    stable_amount = 100
    usdc.mint(owner, stable_amount)
    usdc.approve(buy_proxy.address, stable_amount, sender=owner)

    # Call buy through proxy: msg.sender=proxy, tx.origin=owner==self.owner
    buy_proxy.proxy_buy(vault.address, usdc.address, 0, stable_amount, sender=owner)

    expected_ds_tokens = 100  # 1:1 rate

    # With original code: pending credited to self.owner (== owner)
    # With mutation: pending credited to msg.sender (== buy_proxy.address)
    assert vault.pending_transfers(owner) == expected_ds_tokens
    assert vault.pending_transfers(buy_proxy.address) == 0
    assert vault.pending_transfers_total() == expected_ds_tokens


def test_deposit_uses_pending_when_covers_full_amount(simple_vault, weth, owner):
    """Covers branch: if pending >= amount (deposit uses pending transfers, no transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    deposit_amount = 60
    assert pending_amount > deposit_amount  # precondition: pending fully covers deposit

    # Seed pending transfers
    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    # Vault needs the tokens to have correct balance accounting
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(simple_vault.address, pending_amount, sender=owner)

    simple_vault.deposit(deposit_amount, wallet, sender=owner)

    assert simple_vault.pending_transfers(wallet) == pending_amount - deposit_amount
    assert simple_vault.pending_transfers_total() == pending_amount - deposit_amount


def test_deposit_uses_pending_when_equals_amount(securitize_vault_contract_def, owner):
    """Kills mutation: L107 `pending >= amount` -> `pending > amount`.

    When pending == amount exactly, the full-pending branch should be taken
    (no transferFrom). Uses a token that reverts on zero-amount transferFrom
    to ensure the mutation (which falls through to the elif branch and calls
    transferFrom(wallet, self, 0)) is caught.
    """
    no_zero_transfer_erc20 = boa.loads(
        dedent("""
        balances: HashMap[address, uint256]

        @external
        @view
        def balanceOf(_owner: address) -> uint256:
            return self.balances[_owner]

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            self.balances[msg.sender] -= _value
            self.balances[_to] += _value
            return True

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            assert _value > 0, "zero transferFrom not allowed"
            self.balances[_from] -= _value
            self.balances[_to] += _value
            return True
    """)
    )

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, no_zero_transfer_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    amount = 100

    vault.eval(f"self.pending_transfers[{wallet}] = {amount}")
    vault.eval(f"self.pending_transfers_total = {amount}")
    no_zero_transfer_erc20.eval(f"self.balances[{vault.address}] = {amount}")

    # With original code: pending >= amount is True, so no transferFrom is called
    # With mutation: pending > amount is False, falls to elif, calls transferFrom(0) -> reverts
    vault.deposit(amount, wallet, sender=owner)

    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0


def test_deposit_uses_partial_pending_and_transfer(simple_vault, weth, owner):
    """Covers branch: elif pending > 0 (partial pending used, rest from transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 40
    deposit_amount = 100
    assert 0 < pending_amount < deposit_amount  # precondition: partial pending

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


def test_withdrawable_balance_subtracts_pending(simple_vault, weth, owner):
    """Kills mutation: L157 `-` -> `+` in withdrawable_balance.

    When there are pending transfers, withdrawable_balance must be
    balanceOf - pending_transfers_total, not balanceOf + pending_transfers_total.
    """
    wallet = boa.env.generate_address()
    total_balance = 200
    pending_amount = 80
    assert pending_amount < total_balance  # precondition: pending is a subset of balance

    weth.deposit(value=total_balance, sender=owner)
    weth.transfer(simple_vault.address, total_balance, sender=owner)
    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")

    withdrawable = simple_vault.withdrawable_balance()
    assert withdrawable == total_balance - pending_amount


def test_withdraw_pending_transfers_partial_amount(simple_vault, weth, owner):
    """Covers: withdraw_pending with partial amount."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    withdraw_amount = 60
    assert withdraw_amount < pending_amount  # precondition: partial withdrawal

    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(simple_vault.address, pending_amount, sender=owner)

    balance_before = weth.balanceOf(wallet)
    simple_vault.withdraw_pending(withdraw_amount, sender=wallet)

    assert weth.balanceOf(wallet) == balance_before + withdraw_amount
    assert simple_vault.pending_transfers(wallet) == pending_amount - withdraw_amount
    assert simple_vault.pending_transfers_total() == pending_amount - withdraw_amount


def test_withdraw_pending_transfers_exact_full_amount(simple_vault, weth, owner):
    """Kills mutation: L167 `>=` -> `>` in withdraw_pending.

    Withdrawing exactly the full pending amount should succeed, not revert.
    """
    wallet = boa.env.generate_address()
    pending_amount = 100

    simple_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    simple_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    weth.deposit(value=pending_amount, sender=owner)
    weth.transfer(simple_vault.address, pending_amount, sender=owner)

    balance_before = weth.balanceOf(wallet)
    simple_vault.withdraw_pending(pending_amount, sender=wallet)

    assert weth.balanceOf(wallet) == balance_before + pending_amount
    assert simple_vault.pending_transfers(wallet) == 0
    assert simple_vault.pending_transfers_total() == 0


def test_withdraw_pending_reverts_if_insufficient(simple_vault, weth, owner):
    """Covers: withdraw_pending revert when amount > pending."""
    wallet = boa.env.generate_address()
    simple_vault.eval(f"self.pending_transfers[{wallet}] = 10")
    simple_vault.eval("self.pending_transfers_total = 10")

    with boa.reverts("insufficient pending collateral"):
        simple_vault.withdraw_pending(11, sender=wallet)


def test_transfer_funds_skips_transfer_when_zero_amount(securitize_vault_contract_def, owner):
    """Kills mutation: L198 `amount > 0` -> `amount >= 0`.

    When amount=0 and the token reverts on zero transfers, transfer_funds
    should succeed (skipping the transfer entirely).
    """
    zero_revert_erc20 = boa.loads(
        dedent("""
        transfer_called: bool

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            assert _value > 0, "zero transfer"
            self.transfer_called = True
            return True

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            return True

        @external
        @view
        def was_transfer_called() -> bool:
            return self.transfer_called
    """)
    )

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, zero_revert_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    vault.transfer_funds(zero_revert_erc20.address, 0, wallet, sender=owner)

    assert zero_revert_erc20.was_transfer_called() is False


def test_withdraw_creates_pending_when_transfer_fails(securitize_vault_contract_def, owner):
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
