import boa
import pytest


def get_transfer_events(entry_contract, token_address, sender, receiver):
    """Return Transfer events for a given token emitted during the last call to entry_contract."""
    return [
        e
        for e in entry_contract.get_logs(strict=False)
        if type(e).__name__ == "Transfer" and e.address == token_address and e.sender == sender and e.receiver == receiver
    ]


@pytest.fixture
def vault_owner():
    """Distinct vault owner address, separate from the lending contract caller."""
    addr = boa.env.generate_address("vault_owner")
    boa.env.set_balance(addr, 10**21)
    return addr


@pytest.fixture
def vault(securitize_vault_contract_def, vault_owner, acred, min_vault_manager):
    """Vault with distinct owner and caller (min_vault_manager), using acred token."""
    v = securitize_vault_contract_def.deploy()
    v.initialise(vault_owner, acred.address, sender=min_vault_manager.address)
    return v


@pytest.fixture
def weth_vault(securitize_vault_contract_def, vault_owner, weth, min_vault_manager):
    """Vault with WETH token for deposit/withdraw testing."""
    v = securitize_vault_contract_def.deploy()
    v.initialise(vault_owner, weth.address, sender=min_vault_manager.address)
    return v


def test_buy_refunds_swap_leftover_from_10(vault, vault_owner, acred, usdc):
    """AcredMock swap direction is consistent: ds = stable*den//num, liquidity pulled = ds*num//den.

    With oracle rate num=3, den=10:
    - swap(10): ds = 10*10//3 = 33, liquidity pulled = 33*3//10 = 9
    - Only 9 of 10 stablecoins consumed, 1 refunded to the caller.
    """
    stable_amount = 10
    ds = stable_amount * 10 // 3  # 33
    liquidity_pulled = ds * 3 // 10  # 9
    refund = stable_amount - liquidity_pulled  # 1
    assert refund == 1  # precondition: partial spend leaves a refund
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=vault_owner)

    vault.buy(usdc.address, 0, stable_amount, sender=vault_owner)

    refund_transfers = get_transfer_events(vault, usdc.address, vault.address, vault_owner)
    assert len(refund_transfers) == 1
    assert refund_transfers[0].value == refund
    assert usdc.balanceOf(vault.address) == 0  # 9 pulled into swap, 1 refunded
    assert vault.pending_transfers(vault_owner) == ds  # calculateDsTokenAmount
    assert vault.pending_transfers_total() == ds


def test_buy_refund_preserves_preexisting_balance(vault, vault_owner, acred, usdc):
    """A pre-existing vault balance is preserved; only the swap leftover is refunded."""
    preexisting = 100
    usdc.mint(vault_owner, preexisting)
    usdc.transfer(vault.address, preexisting, sender=vault_owner)
    assert usdc.balanceOf(vault.address) == preexisting

    stable_amount = 10
    ds = stable_amount * 10 // 3  # 33
    liquidity_pulled = ds * 3 // 10  # 9
    refund = stable_amount - liquidity_pulled  # 1
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=vault_owner)

    vault.buy(usdc.address, 0, stable_amount, sender=vault_owner)

    refund_transfers = get_transfer_events(vault, usdc.address, vault.address, vault_owner)
    assert len(refund_transfers) == 1
    assert refund_transfers[0].value == refund
    assert usdc.balanceOf(vault.address) == preexisting  # only the swap leftover refunded, seed untouched
    assert vault.pending_transfers(vault_owner) == ds
    assert vault.pending_transfers_total() == ds


def test_buy_refunds_excess_when_remaining_exceeds_initial(vault, vault_owner, acred, usdc):
    """When remaining_balance > initial_balance, excess stablecoins are transferred back.

    With oracle rate num=3, den=10:
    - swap(11): ds = 11*10//3 = 36, liquidity pulled = 36*3//10 = 10
    - Only 10 of 11 stablecoins consumed, 1 returned to sender.
    """
    stable_amount = 11
    ds = stable_amount * 10 // 3  # 36
    liquidity_pulled = ds * 3 // 10  # 10
    refund = stable_amount - liquidity_pulled  # 1
    assert refund == 1  # precondition
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=vault_owner)

    vault.buy(usdc.address, 0, stable_amount, sender=vault_owner)

    refund_transfers = get_transfer_events(vault, usdc.address, vault.address, vault_owner)
    assert len(refund_transfers) == 1
    assert refund_transfers[0].value == refund
    assert usdc.balanceOf(vault.address) == 0
    assert vault.pending_transfers(vault_owner) == ds
    assert vault.pending_transfers_total() == ds


def test_buy_updates_pending_when_called_by_owner(vault, vault_owner, min_vault_manager, acred, usdc):
    """buy() authorizes on owner, not caller: when owner != caller, only the owner can call buy."""
    assert vault_owner != min_vault_manager.address  # precondition: owner != caller

    stable_amount = 10
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=vault_owner)

    vault.buy(usdc.address, 0, stable_amount, sender=vault_owner)

    expected_ds_tokens = stable_amount * 10 // 3  # oracle rate 3, decimals 1
    assert vault.pending_transfers(vault_owner) == expected_ds_tokens
    assert vault.pending_transfers_total() == expected_ds_tokens


def test_buy_reverts_if_unauthorized_caller(vault, vault_owner, min_vault_manager, acred, usdc):
    """The caller (min_vault_manager) that initialized the vault should NOT be able to call buy."""
    assert vault_owner != min_vault_manager.address  # precondition: owner != caller

    stable_amount = 10
    usdc.mint(min_vault_manager.address, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=min_vault_manager.address)

    with boa.reverts("unauthorized"):
        vault.buy(usdc.address, 0, stable_amount, sender=min_vault_manager.address)


def test_buy_succeeds_when_ds_token_equals_min(
    securitize_vault_contract_def, acred_contract_def, oracle_contract_def, weth9_contract_def, owner
):
    """When min_ds_token_amount equals the calculated amount exactly (>= boundary), buy succeeds.

    Uses a 1:1 oracle rate so calculateDsTokenAmount and swap return the same value.
    """
    oracle_1to1 = oracle_contract_def.deploy(1, 10)
    usdc_1to1 = weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)
    acred_1to1 = acred_contract_def.deploy("ACRED", "ACRED", 6, 10**6, oracle_1to1.address, usdc_1to1.address)

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
    acred_1to1 = acred_contract_def.deploy("ACRED", "ACRED", 6, 10**6, oracle_1to1.address, usdc_1to1.address)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred_1to1.address, sender=owner)

    stable_amount = 100

    usdc_1to1.mint(owner, stable_amount)
    usdc_1to1.approve(vault.address, stable_amount, sender=owner)

    with boa.reverts("ds token amount lt min"):
        vault.buy(usdc_1to1.address, 101, stable_amount, sender=owner)


def test_buy_credits_pending_to_owner_not_sender(
    securitize_vault_contract_def,
    acred_contract_def,
    oracle_contract_def,
    weth9_contract_def,
    owner,
    min_vault_manager,
    vault_proxy,
):
    """DS tokens from buy are credited to self.owner (the borrower), not msg.sender.

    Uses a proxy to call buy so msg.sender != self.owner, exercising the proxy path in _check_user.
    """
    # Set up fresh contracts with 1:1 oracle for simplicity
    oracle = oracle_contract_def.deploy(1, 10)
    usdc = weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)
    acred = acred_contract_def.deploy("ACRED", "ACRED", 6, 10**6, oracle.address, usdc.address)

    # Initialize vault: owner is 'owner' (the test EOA), caller is min_vault_manager
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred.address, sender=min_vault_manager.address)

    # Authorize the proxy
    min_vault_manager.set_proxy(vault_proxy.address, True)

    # Fund and approve
    stable_amount = 100
    usdc.mint(owner, stable_amount)
    usdc.approve(vault_proxy.address, stable_amount, sender=owner)

    # Call buy through proxy: msg.sender=proxy, tx.origin=owner==self.owner
    vault_proxy.proxy_buy(vault.address, usdc.address, 0, stable_amount, sender=owner)

    expected_ds_tokens = 100  # 1:1 rate

    assert vault.pending_transfers(owner) == expected_ds_tokens
    assert vault.pending_transfers(vault_proxy.address) == 0
    assert vault.pending_transfers_total() == expected_ds_tokens


def test_deposit_uses_pending_when_covers_full_amount(weth_vault, weth, vault_owner, min_vault_manager):
    """Covers branch: if pending >= amount (deposit uses pending transfers, no transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    deposit_amount = 60
    assert pending_amount > deposit_amount  # precondition: pending fully covers deposit

    # Seed pending transfers
    weth_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    weth_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    # Vault needs the tokens to have correct balance accounting
    boa.env.set_balance(vault_owner, pending_amount)
    weth.deposit(value=pending_amount, sender=vault_owner)
    weth.transfer(weth_vault.address, pending_amount, sender=vault_owner)

    weth_vault.deposit(deposit_amount, wallet, sender=min_vault_manager.address)

    assert weth_vault.pending_transfers(wallet) == pending_amount - deposit_amount
    assert weth_vault.pending_transfers_total() == pending_amount - deposit_amount


def test_deposit_uses_pending_when_equals_amount(securitize_vault_contract_def, no_zero_transfer_erc20, owner):
    """When pending == amount exactly (>= boundary), the full-pending branch is taken (no transferFrom).

    Uses a token that reverts on zero-amount transferFrom to catch a fall-through to transferFrom(0).
    """
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, no_zero_transfer_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    amount = 100

    vault.eval(f"self.pending_transfers[{wallet}] = {amount}")
    vault.eval(f"self.pending_transfers_total = {amount}")
    no_zero_transfer_erc20.eval(f"self.balances[{vault.address}] = {amount}")

    # pending >= amount, so no transferFrom is called
    vault.deposit(amount, wallet, sender=owner)

    assert vault.pending_transfers(wallet) == 0
    assert vault.pending_transfers_total() == 0
    assert vault.withdrawable_balance() == amount


def test_deposit_uses_partial_pending_and_transfer(weth_vault, weth, vault_owner, min_vault_manager):
    """Covers branch: elif pending > 0 (partial pending used, rest from transferFrom)."""
    wallet = boa.env.generate_address()
    pending_amount = 40
    deposit_amount = 100
    assert 0 < pending_amount < deposit_amount  # precondition: partial pending

    weth_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    weth_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    boa.env.set_balance(vault_owner, pending_amount)
    weth.deposit(value=pending_amount, sender=vault_owner)
    weth.transfer(weth_vault.address, pending_amount, sender=vault_owner)

    # wallet needs tokens and approval for the remainder
    transfer_amount = deposit_amount - pending_amount
    boa.env.set_balance(wallet, transfer_amount)
    weth.deposit(value=transfer_amount, sender=wallet)
    weth.approve(weth_vault.address, transfer_amount, sender=wallet)

    weth_vault.deposit(deposit_amount, wallet, sender=min_vault_manager.address)

    assert weth_vault.pending_transfers(wallet) == 0
    assert weth_vault.pending_transfers_total() == 0
    assert weth.balanceOf(weth_vault.address) == deposit_amount


def test_withdrawable_balance_subtracts_pending(weth_vault, weth, vault_owner):
    """withdrawable_balance is balanceOf - pending_transfers_total (not +)."""
    wallet = boa.env.generate_address()
    total_balance = 200
    pending_amount = 80
    assert pending_amount < total_balance  # precondition: pending is a subset of balance

    boa.env.set_balance(vault_owner, total_balance)
    weth.deposit(value=total_balance, sender=vault_owner)
    weth.transfer(weth_vault.address, total_balance, sender=vault_owner)
    weth_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    weth_vault.eval(f"self.pending_transfers_total = {pending_amount}")

    withdrawable = weth_vault.withdrawable_balance()
    assert withdrawable == total_balance - pending_amount


def test_withdraw_pending_transfers_partial_amount(weth_vault, weth, vault_owner):
    """Covers: withdraw_pending with partial amount."""
    wallet = boa.env.generate_address()
    pending_amount = 100
    withdraw_amount = 60
    assert withdraw_amount < pending_amount  # precondition: partial withdrawal

    weth_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    weth_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    boa.env.set_balance(vault_owner, pending_amount)
    weth.deposit(value=pending_amount, sender=vault_owner)
    weth.transfer(weth_vault.address, pending_amount, sender=vault_owner)

    balance_before = weth.balanceOf(wallet)
    weth_vault.withdraw_pending(withdraw_amount, sender=wallet)

    assert weth.balanceOf(wallet) == balance_before + withdraw_amount
    assert weth_vault.pending_transfers(wallet) == pending_amount - withdraw_amount
    assert weth_vault.pending_transfers_total() == pending_amount - withdraw_amount


def test_withdraw_pending_transfers_exact_full_amount(weth_vault, weth, vault_owner):
    """Withdrawing exactly the full pending amount (>= boundary) succeeds, not reverts."""
    wallet = boa.env.generate_address()
    pending_amount = 100

    weth_vault.eval(f"self.pending_transfers[{wallet}] = {pending_amount}")
    weth_vault.eval(f"self.pending_transfers_total = {pending_amount}")
    boa.env.set_balance(vault_owner, pending_amount)
    weth.deposit(value=pending_amount, sender=vault_owner)
    weth.transfer(weth_vault.address, pending_amount, sender=vault_owner)

    balance_before = weth.balanceOf(wallet)
    weth_vault.withdraw_pending(pending_amount, sender=wallet)

    assert weth.balanceOf(wallet) == balance_before + pending_amount
    assert weth_vault.pending_transfers(wallet) == 0
    assert weth_vault.pending_transfers_total() == 0


def test_withdraw_pending_reverts_if_insufficient(weth_vault):
    """Covers: withdraw_pending revert when amount > pending."""
    wallet = boa.env.generate_address()
    weth_vault.eval(f"self.pending_transfers[{wallet}] = 10")
    weth_vault.eval("self.pending_transfers_total = 10")

    with boa.reverts("insufficient pending collateral"):
        weth_vault.withdraw_pending(11, sender=wallet)


def test_transfer_funds_skips_transfer_when_zero_amount(securitize_vault_contract_def, zero_revert_erc20, owner):
    """When amount == 0 and the token reverts on zero transfers, transfer_funds skips the transfer."""
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, zero_revert_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    vault.transfer_funds(zero_revert_erc20.address, 0, wallet, sender=owner)

    assert zero_revert_erc20.was_transfer_called() is False


def test_withdraw_creates_pending_when_transfer_fails(securitize_vault_contract_def, failing_transfer_erc20, owner):
    """withdraw with a failing transfer creates a pending transfer."""
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, failing_transfer_erc20.address, sender=owner)

    wallet = boa.env.generate_address()
    deposit_amount = 100

    # Deposit (transferFrom succeeds, balance tracked on vault)
    vault.deposit(deposit_amount, wallet, sender=owner)
    assert failing_transfer_erc20.balanceOf(vault.address) == deposit_amount

    # Withdraw (transfer fails → creates pending)
    vault.withdraw(deposit_amount, wallet, sender=owner)

    assert vault.pending_transfers(wallet) == deposit_amount
    assert vault.pending_transfers_total() == deposit_amount


def test_buy_refund_goes_to_caller_not_owner(
    securitize_vault_contract_def,
    acred_contract_def,
    oracle_contract_def,
    weth9_contract_def,
    owner,
    min_vault_manager,
    vault_proxy,
):
    """buy() refunds excess stablecoins to msg.sender (the caller), not self.owner.

    Exercised via the proxy path: an authorized proxy calls buy, refund lands on the proxy.
    """
    # Set up fresh contracts with oracle rate 3/10 so swap consumes less than input
    oracle = oracle_contract_def.deploy(1, 3)
    usdc = weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)
    acred = acred_contract_def.deploy("ACRED", "ACRED", 6, 10**6, oracle.address, usdc.address)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred.address, sender=min_vault_manager.address)
    assert vault.owner() == owner
    assert vault.owner() != vault_proxy.address  # precondition: owner != proxy (msg.sender)

    # Authorize the proxy
    min_vault_manager.set_proxy(vault_proxy.address, True)

    # Use stable_amount=11 with oracle rate num=3, den=10:
    # swap(11): ds = 11*10//3 = 36, liquidity pulled = 36*3//10 = 10
    # So 10 of 11 stablecoins consumed, 1 refunded
    stable_amount = 11
    usdc.mint(owner, stable_amount)
    usdc.approve(vault_proxy.address, stable_amount, sender=owner)

    proxy_balance_before = usdc.balanceOf(vault_proxy.address)
    owner_balance_before = usdc.balanceOf(owner)

    vault_proxy.proxy_buy(vault.address, usdc.address, 0, stable_amount, sender=owner)

    # Refund of 1 USDC lands on the proxy (msg.sender), not on owner
    assert usdc.balanceOf(vault_proxy.address) == proxy_balance_before + 1
    # Owner paid stable_amount to proxy, so owner balance decreased by stable_amount
    assert usdc.balanceOf(owner) == owner_balance_before - stable_amount


def test_buy_reverts_when_ds_token_amount_below_min(vault, vault_owner, acred, usdc):
    """When min_ds_token_amount exceeds the calculated ds_token_amount, buy() reverts "ds token amount lt min"."""
    stable_amount = 10
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=vault_owner)

    # With oracle rate 3/10: calculateDsTokenAmount(10) = 10 * 10 // 3 = 33
    expected_ds_tokens = 10 * 10 // 3
    assert expected_ds_tokens == 33  # precondition

    # Request more than possible -> must revert
    with boa.reverts("ds token amount lt min"):
        vault.buy(usdc.address, expected_ds_tokens + 1, stable_amount, sender=vault_owner)


def test_buy_reverts_if_called_by_unauthorized(vault, vault_owner, min_vault_manager, acred, usdc):
    """buy() rejects callers that are neither the owner nor an authorized proxy."""
    unauthorized = boa.env.generate_address("rando")
    assert unauthorized != vault_owner  # precondition: not the owner
    assert unauthorized != min_vault_manager.address  # precondition: not the caller

    stable_amount = 10
    usdc.mint(unauthorized, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=unauthorized)

    with boa.reverts("unauthorized"):
        vault.buy(usdc.address, 0, stable_amount, sender=unauthorized)
