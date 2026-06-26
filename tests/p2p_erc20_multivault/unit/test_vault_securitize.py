import boa
import pytest

from tests.p2p_erc20_multivault.conftest_base import get_calls


@pytest.fixture
def caller_addr():
    """Plain address to fulfill the lending contract caller role."""
    return boa.env.generate_address("lending_contract")


@pytest.fixture
def token(weth9_contract_def, owner):
    """Collateral token (ERC20 mock)."""
    return weth9_contract_def.deploy("TestToken", "TT", 18, 10**20)


@pytest.fixture
def payment_token(weth9_contract_def, owner):
    """Payment token for transfer_funds / withdraw_funds."""
    return weth9_contract_def.deploy("PayToken", "PT", 6, 10**20)


@pytest.fixture
def vault_for_lending(securitize_vault_contract_def, caller_addr, token, owner):
    """Vault initialized with caller_addr as caller and owner as owner."""
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, token.address, sender=caller_addr)
    return v


@pytest.fixture
def vault_with_token(securitize_vault_contract_def, caller_addr, token, owner):
    """Vault initialized with a blacklistable token for testing failed transfers."""
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, token.address, sender=caller_addr)
    return v


@pytest.fixture
def vault_acred(securitize_vault_contract_def, caller_addr, owner, acred):
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, acred.address, sender=caller_addr)
    return v


# ===========================================================================
# initialise tests
# ===========================================================================


def test_initialise_sets_state(securitize_vault_contract_def, token, owner):
    v = securitize_vault_contract_def.deploy()
    caller_addr = boa.env.generate_address("caller")
    v.initialise(owner, token.address, sender=caller_addr)

    assert v.owner() == owner
    assert v.caller() == caller_addr
    assert v.token() == token.address


def test_initialise_reverts_if_already_initialized(vault_for_lending, token, owner):
    with boa.reverts("already initialised"):
        vault_for_lending.initialise(owner, token.address, sender=owner)


# ===========================================================================
# deposit tests
# ===========================================================================


def test_deposit_reverts_if_not_caller(vault_for_lending, token, owner):
    """Deposit must be called by self.caller (the lending contract), not by owner or anyone else."""
    unauthorized = boa.env.generate_address("unauthorized")
    with boa.reverts("unauthorized"):
        vault_for_lending.deposit(100, owner, sender=unauthorized)

    # Even the vault owner cannot call deposit directly
    with boa.reverts("unauthorized"):
        vault_for_lending.deposit(100, owner, sender=owner)


def test_deposit_transfers_tokens_when_no_pending(vault_for_lending, caller_addr, token, owner):
    """Normal deposit path: no pending transfers, tokens transferred from wallet."""
    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(vault_for_lending.address, amount, sender=owner)

    vault_for_lending.deposit(amount, owner, sender=caller_addr)

    assert token.balanceOf(vault_for_lending.address) == amount
    assert vault_for_lending.pending_transfers(owner) == 0
    assert vault_for_lending.pending_transfers_total() == 0


def test_deposit_pending_exact_match(vault_with_token, caller_addr, token, owner):
    """When pending[wallet] == deposit amount, no token transfer occurs and pending is zeroed."""
    v = vault_with_token

    # Step 1: Deposit some tokens normally to build vault balance
    deposit_amount = 1000
    token.deposit(value=deposit_amount, sender=owner)
    token.approve(v.address, deposit_amount, sender=owner)
    v.deposit(deposit_amount, owner, sender=caller_addr)
    assert token.balanceOf(v.address) == deposit_amount

    # Step 2: Blacklist the owner so withdraw transfer fails, creating pending
    token.blacklist(owner, True, sender=owner)
    v.withdraw(deposit_amount, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == deposit_amount
    assert v.pending_transfers_total() == deposit_amount

    # Step 3: Un-blacklist the owner for future operations
    token.blacklist(owner, False, sender=owner)

    # Step 4: Deposit again with amount == pending (exact match - if branch)
    v.deposit(deposit_amount, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == 0
    assert v.pending_transfers_total() == 0


def test_deposit_pending_greater_than_amount(vault_with_token, caller_addr, token, owner):
    """When pending[wallet] > deposit amount, pending is reduced by amount (if branch)."""
    v = vault_with_token

    # Build vault balance
    deposit_amount = 1000
    token.deposit(value=deposit_amount, sender=owner)
    token.approve(v.address, deposit_amount, sender=owner)
    v.deposit(deposit_amount, owner, sender=caller_addr)

    # Create pending via failed withdraw
    token.blacklist(owner, True, sender=owner)
    v.withdraw(deposit_amount, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == deposit_amount

    token.blacklist(owner, False, sender=owner)

    # Deposit less than pending (if branch, pending > amount)
    smaller_deposit = 400
    v.deposit(smaller_deposit, owner, sender=caller_addr)

    # pending should be reduced by the deposit amount, NOT set to amount - pending
    assert v.pending_transfers(owner) == deposit_amount - smaller_deposit
    assert v.pending_transfers_total() == deposit_amount - smaller_deposit


def test_deposit_pending_less_than_amount(vault_with_token, caller_addr, token, owner):
    """When 0 < pending[wallet] < amount, pending is zeroed and remaining transferred (elif branch)."""
    v = vault_with_token

    # Build vault balance
    initial_deposit = 500
    token.deposit(value=initial_deposit, sender=owner)
    token.approve(v.address, initial_deposit, sender=owner)
    v.deposit(initial_deposit, owner, sender=caller_addr)

    # Create pending via failed withdraw
    token.blacklist(owner, True, sender=owner)
    v.withdraw(initial_deposit, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == initial_deposit
    assert v.pending_transfers_total() == initial_deposit

    token.blacklist(owner, False, sender=owner)

    # Deposit more than pending (elif branch)
    larger_deposit = 800
    extra_needed = larger_deposit - initial_deposit
    token.deposit(value=extra_needed, sender=owner)
    token.approve(v.address, extra_needed, sender=owner)

    v.deposit(larger_deposit, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == 0
    assert v.pending_transfers_total() == 0


# ===========================================================================
# withdraw tests
# ===========================================================================


def test_withdraw_reverts_if_not_caller(vault_for_lending, owner):
    """Withdraw must be called by self.caller (lending contract)."""
    unauthorized = boa.env.generate_address("unauthorized")
    with boa.reverts("unauthorized"):
        vault_for_lending.withdraw(100, owner, sender=unauthorized)

    with boa.reverts("unauthorized"):
        vault_for_lending.withdraw(100, owner, sender=owner)


def test_withdraw_transfer_failure_tracks_pending(vault_with_token, caller_addr, token, owner):
    """When withdraw transfer fails, pending_transfers and pending_transfers_total must be updated."""
    v = vault_with_token

    # Deposit tokens
    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(v.address, amount, sender=owner)
    v.deposit(amount, owner, sender=caller_addr)

    # Blacklist owner to cause transfer failure
    token.blacklist(owner, True, sender=owner)
    v.withdraw(amount, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == amount
    assert v.pending_transfers_total() == amount
    assert token.balanceOf(v.address) == amount


def test_withdraw_transfer_failure_or_semantics(vault_with_token, caller_addr, token, owner):
    """Withdraw uses 'or' (not 'and') in failure check: either !success or !response triggers pending."""
    v = vault_with_token

    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(v.address, amount, sender=owner)
    v.deposit(amount, owner, sender=caller_addr)

    # Blacklist causes reverts in WETH9Mock, which means success=False
    token.blacklist(owner, True, sender=owner)
    v.withdraw(amount, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == amount
    assert v.pending_transfers_total() == amount


# ===========================================================================
# withdraw_pending tests
# ===========================================================================


def test_withdraw_pending_exact_amount(vault_with_token, caller_addr, token, owner):
    """User can withdraw exactly their full pending balance."""
    v = vault_with_token

    # Build pending via deposit + failed withdraw
    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(v.address, amount, sender=owner)
    v.deposit(amount, owner, sender=caller_addr)
    token.blacklist(owner, True, sender=owner)
    v.withdraw(amount, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == amount

    token.blacklist(owner, False, sender=owner)

    owner_balance_before = token.balanceOf(owner)
    v.withdraw_pending(amount, sender=owner)

    assert v.pending_transfers(owner) == 0
    assert v.pending_transfers_total() == 0
    assert token.balanceOf(owner) == owner_balance_before + amount


def test_withdraw_pending_partial_amount(vault_with_token, caller_addr, token, owner):
    """User can withdraw a partial amount of their pending balance."""
    v = vault_with_token

    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(v.address, amount, sender=owner)
    v.deposit(amount, owner, sender=caller_addr)
    token.blacklist(owner, True, sender=owner)
    v.withdraw(amount, owner, sender=caller_addr)

    token.blacklist(owner, False, sender=owner)

    partial = 400
    v.withdraw_pending(partial, sender=owner)

    assert v.pending_transfers(owner) == amount - partial
    assert v.pending_transfers_total() == amount - partial


def test_withdraw_pending_reverts_if_exceeds_pending(vault_with_token, caller_addr, token, owner):
    """Cannot withdraw more than pending balance."""
    v = vault_with_token

    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(v.address, amount, sender=owner)
    v.deposit(amount, owner, sender=caller_addr)
    token.blacklist(owner, True, sender=owner)
    v.withdraw(amount, owner, sender=caller_addr)

    token.blacklist(owner, False, sender=owner)

    with boa.reverts("insufficient pending collateral"):
        v.withdraw_pending(amount + 1, sender=owner)


# ===========================================================================
# withdraw_funds tests
# ===========================================================================


def test_withdraw_funds_reverts_if_not_authorized(
    securitize_vault_contract_def, payment_token, token, owner, min_vault_manager
):
    """Only the lending contract (self.caller) or authorized proxy can call withdraw_funds."""
    # Need a mock contract because _check_user does a staticcall to self.caller.authorized_proxies()
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, token.address, sender=min_vault_manager.address)

    unauthorized = boa.env.generate_address("unauthorized")
    with boa.reverts("unauthorized"):
        v.withdraw_funds(payment_token.address, 100, sender=unauthorized)


# ===========================================================================
# transfer_funds tests
# ===========================================================================


def test_transfer_funds_skips_zero_amount(vault_for_lending, payment_token, caller_addr):
    """When amount is 0, no ERC20 transfer should occur."""
    wallet = boa.env.generate_address("recipient")
    wallet_balance_before = payment_token.balanceOf(wallet)

    vault_for_lending.transfer_funds(payment_token.address, 0, wallet, sender=caller_addr)

    assert payment_token.balanceOf(wallet) == wallet_balance_before


def test_transfer_funds_transfers_nonzero_amount(vault_for_lending, payment_token, caller_addr, owner):
    """When amount > 0, tokens are transferred to the wallet."""
    amount = 500
    wallet = boa.env.generate_address("recipient")

    payment_token.mint(vault_for_lending.address, amount)

    vault_for_lending.transfer_funds(payment_token.address, amount, wallet, sender=caller_addr)

    assert payment_token.balanceOf(wallet) == amount


# ===========================================================================
# buy tests - authorization and slippage
# ===========================================================================


def test_buy_only_owner_can_call(securitize_vault_contract_def, usdc, owner, acred, min_vault_manager):
    """buy() requires _check_user(self.owner), not _check_user(self.caller).

    Only the vault owner (or an authorized proxy with owner as tx.origin) should
    be able to call buy(). The lending contract (self.caller) should NOT be able
    to call buy() unless it is also the owner.
    """
    # Need a mock contract because _check_user does a staticcall to self.caller.authorized_proxies()
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, acred.address, sender=min_vault_manager.address)

    stable_amount = 10
    usdc.mint(owner, stable_amount)
    usdc.approve(v.address, stable_amount, sender=owner)

    # Owner can buy
    v.buy(usdc.address, 0, stable_amount, sender=owner)

    # Lending contract (caller) should NOT be able to buy
    usdc.mint(min_vault_manager.address, stable_amount)
    usdc.approve(v.address, stable_amount, sender=min_vault_manager.address)
    with boa.reverts("unauthorized"):
        v.buy(usdc.address, 0, stable_amount, sender=min_vault_manager.address)


def test_buy_pending_transfers_credited_to_owner(vault_acred, caller_addr, usdc, owner):
    """buy() must credit pending_transfers to self.owner, not self.caller."""
    stable_amount = 10
    usdc.mint(owner, stable_amount)
    usdc.approve(vault_acred.address, stable_amount, sender=owner)

    vault_acred.buy(usdc.address, 0, stable_amount, sender=owner)

    expected_ds_tokens = 10 * 10 // 3  # calculateDsTokenAmount with oracle rate 3/10

    assert vault_acred.pending_transfers(owner) == expected_ds_tokens
    assert vault_acred.pending_transfers(caller_addr) == 0
    assert vault_acred.pending_transfers_total() == expected_ds_tokens


def test_buy_reverts_if_ds_token_amount_below_minimum(vault_acred, usdc, owner):
    """buy() must revert when calculated ds_token_amount < min_ds_token_amount (slippage protection)."""
    stable_amount = 10
    usdc.mint(owner, stable_amount)
    usdc.approve(vault_acred.address, stable_amount, sender=owner)

    expected_ds_tokens = 10 * 10 // 3  # = 33

    with boa.reverts("ds token amount lt min"):
        vault_acred.buy(usdc.address, expected_ds_tokens + 1, stable_amount, sender=owner)


def test_buy_succeeds_with_exact_min_ds_token_amount(vault_acred, usdc, owner):
    """buy() succeeds when calculated ds_token_amount == min_ds_token_amount."""
    stable_amount = 10
    usdc.mint(owner, stable_amount)
    usdc.approve(vault_acred.address, stable_amount, sender=owner)

    min_amount = 3
    expected_ds_tokens = 10 * 10 // 3  # = 33 (from calculateDsTokenAmount)

    vault_acred.buy(usdc.address, min_amount, stable_amount, sender=owner)

    assert vault_acred.pending_transfers(owner) == expected_ds_tokens


def test_initialise_sets_owner_to_param_not_sender(securitize_vault_contract_def, token):
    """After initialise(_owner, _token), owner() is _owner (the borrower), not msg.sender."""
    borrower = boa.env.generate_address("borrower_addr")
    lending_contract = boa.env.generate_address("lending_addr")
    assert borrower != lending_contract  # precondition

    v = securitize_vault_contract_def.deploy()
    v.initialise(borrower, token.address, sender=lending_contract)

    assert v.owner() == borrower
    assert v.owner() != lending_contract
    assert v.caller() == lending_contract


def test_deposit_partial_pending_clears_pending_to_zero(vault_with_token, caller_addr, token, owner):
    """In the elif branch (0 < pending < amount), pending_transfers[wallet] is zeroed after deposit."""
    v = vault_with_token

    # Build vault balance
    initial_deposit = 500
    token.deposit(value=initial_deposit, sender=owner)
    token.approve(v.address, initial_deposit, sender=owner)
    v.deposit(initial_deposit, owner, sender=caller_addr)

    # Create pending via failed withdraw
    token.blacklist(owner, True, sender=owner)
    v.withdraw(initial_deposit, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == initial_deposit  # precondition

    token.blacklist(owner, False, sender=owner)

    # Deposit more than pending (elif branch: 0 < pending < amount)
    larger_deposit = 800
    extra_needed = larger_deposit - initial_deposit
    token.deposit(value=extra_needed, sender=owner)
    token.approve(v.address, extra_needed, sender=owner)

    v.deposit(larger_deposit, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == 0
    assert v.pending_transfers_total() == 0


def test_withdraw_reverts_when_amount_plus_pending_exceeds_balance(vault_with_token, caller_addr, token, owner):
    """withdraw checks amount + pending_total against balance, so a withdraw that fits without
    counting pending must still revert with "insufficient balance"."""
    v = vault_with_token

    # Deposit tokens to build vault balance
    vault_balance = 1000
    token.deposit(value=vault_balance, sender=owner)
    token.approve(v.address, vault_balance, sender=owner)
    v.deposit(vault_balance, owner, sender=caller_addr)

    # Create pending via failed withdraw (600 pending out of 1000)
    pending_amount = 600
    token.blacklist(owner, True, sender=owner)
    v.withdraw(pending_amount, owner, sender=caller_addr)
    token.blacklist(owner, False, sender=owner)

    assert v.pending_transfers_total() == pending_amount  # precondition
    assert token.balanceOf(v.address) == vault_balance  # precondition

    # amount + pending > balance but amount < balance: must revert
    withdraw_amount = 500
    assert withdraw_amount + pending_amount > vault_balance  # precondition
    assert withdraw_amount < vault_balance  # precondition

    wallet = boa.env.generate_address("recipient")
    with boa.reverts("insufficient balance"):
        v.withdraw(withdraw_amount, wallet, sender=caller_addr)


def test_withdraw_failure_credits_pending_to_wallet_not_sender(securitize_vault_contract_def, failing_transfer_erc20, owner):
    """When withdraw transfer fails, pending is credited to `wallet` (the recipient), not msg.sender."""
    caller = boa.env.generate_address("lending_contract")
    wallet = boa.env.generate_address("recipient_wallet")
    assert caller != wallet  # precondition: caller and wallet are different

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, failing_transfer_erc20.address, sender=caller)

    deposit_amount = 100
    v.deposit(deposit_amount, wallet, sender=caller)
    assert failing_transfer_erc20.balanceOf(v.address) == deposit_amount  # precondition

    # Withdraw to wallet; transfer fails -> pending credited
    v.withdraw(deposit_amount, wallet, sender=caller)

    assert v.pending_transfers(wallet) == deposit_amount
    assert v.pending_transfers(caller) == 0


def test_withdraw_pending_transfers_actual_tokens(vault_with_token, caller_addr, token, owner):
    """After withdraw_pending, the caller receives actual tokens (balance up by `amount`)."""
    v = vault_with_token

    # Build pending via deposit + failed withdraw
    amount = 1000
    token.deposit(value=amount, sender=owner)
    token.approve(v.address, amount, sender=owner)
    v.deposit(amount, owner, sender=caller_addr)
    token.blacklist(owner, True, sender=owner)
    v.withdraw(amount, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == amount  # precondition

    token.blacklist(owner, False, sender=owner)

    owner_balance_before = token.balanceOf(owner)
    vault_balance_before = token.balanceOf(v.address)

    v.withdraw_pending(amount, sender=owner)

    assert token.balanceOf(owner) == owner_balance_before + amount
    assert token.balanceOf(v.address) == vault_balance_before - amount


def test_deposit_pending_equals_one_takes_partial_path(securitize_vault_contract_def, tracking_erc20, owner):
    """When pending_transfers[wallet] == 1 (boundary), the partial-pending elif branch is taken."""
    caller = boa.env.generate_address("lending_contract")
    wallet = boa.env.generate_address("wallet")

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, tracking_erc20.address, sender=caller)

    # Set pending_transfers[wallet] = 1 (boundary value)
    v.eval(f"self.pending_transfers[{wallet}] = 1")
    v.eval("self.pending_transfers_total = 1")
    tracking_erc20.eval(f"self.balances[{v.address}] = 1")

    # Deposit amount = 10; with pending = 1, elif branch should transfer 10 - 1 = 9
    deposit_amount = 10
    tracking_erc20.eval(f"self.balances[{wallet}] = {deposit_amount}")

    v.deposit(deposit_amount, wallet, sender=caller)

    # elif branch: transferFrom pulls amount - pending = 9
    assert tracking_erc20.last_transfer_from_amount() == deposit_amount - 1
    assert v.pending_transfers(wallet) == 0
    assert v.pending_transfers_total() == 0


def test_withdraw_pending_reverts_if_amount_exceeds_pending(vault_with_token, caller_addr, token, owner):
    """withdraw_pending with amount > pending reverts "insufficient pending collateral"."""
    v = vault_with_token

    # Build pending via deposit + failed withdraw
    pending_amount = 100
    token.deposit(value=pending_amount, sender=owner)
    token.approve(v.address, pending_amount, sender=owner)
    v.deposit(pending_amount, owner, sender=caller_addr)
    token.blacklist(owner, True, sender=owner)
    v.withdraw(pending_amount, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == pending_amount  # precondition

    token.blacklist(owner, False, sender=owner)

    # Try to withdraw more than pending
    with boa.reverts("insufficient pending collateral"):
        v.withdraw_pending(pending_amount + 1, sender=owner)


def test_withdraw_multiple_failures_accumulate_pending(vault_with_token, caller_addr, token, owner):
    """Two consecutive failed withdrawals to the same wallet accumulate pending additively."""
    v = vault_with_token

    # Deposit enough tokens for two withdrawals
    total = 1000
    token.deposit(value=total, sender=owner)
    token.approve(v.address, total, sender=owner)
    v.deposit(total, owner, sender=caller_addr)

    # Blacklist owner to cause transfer failures
    token.blacklist(owner, True, sender=owner)

    # First failed withdraw
    first_amount = 400
    v.withdraw(first_amount, owner, sender=caller_addr)
    assert v.pending_transfers(owner) == first_amount
    assert v.pending_transfers_total() == first_amount

    # Second failed withdraw must accumulate, not overwrite
    second_amount = 300
    v.withdraw(second_amount, owner, sender=caller_addr)

    assert v.pending_transfers(owner) == first_amount + second_amount
    assert v.pending_transfers_total() == first_amount + second_amount


def test_withdraw_funds_transfers_correct_amount(securitize_vault_contract_def, weth9_contract_def, owner, min_vault_manager):
    """After withdraw_funds, the caller (lending contract) receives the requested amount."""
    payment_tok = weth9_contract_def.deploy("PaymentToken", "PT", 6, 10**20)

    v = securitize_vault_contract_def.deploy()
    token = weth9_contract_def.deploy("CollatToken", "CT", 18, 10**20)
    v.initialise(owner, token.address, sender=min_vault_manager.address)

    # Fund the vault with payment tokens
    amount = 500
    payment_tok.mint(v.address, amount)

    caller_balance_before = payment_tok.balanceOf(min_vault_manager.address)

    # withdraw_funds should transfer `amount` of payment_tok to self.caller
    v.withdraw_funds(payment_tok.address, amount, sender=min_vault_manager.address)

    caller_balance_after = payment_tok.balanceOf(min_vault_manager.address)
    assert caller_balance_after == caller_balance_before + amount
    assert payment_tok.balanceOf(v.address) == 0


def test_withdraw_funds_uses_payment_token_not_collateral(
    securitize_vault_contract_def, weth9_contract_def, owner, min_vault_manager
):
    """withdraw_funds transfers the payment_token parameter, not self.token (collateral)."""
    collateral_tok = weth9_contract_def.deploy("Collateral", "COL", 18, 10**20)
    payment_tok = weth9_contract_def.deploy("PaymentToken", "PT", 6, 10**20)

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, collateral_tok.address, sender=min_vault_manager.address)

    amount = 500

    # Fund vault with BOTH tokens
    collateral_tok.deposit(value=amount, sender=owner)
    collateral_tok.transfer(v.address, amount, sender=owner)
    payment_tok.mint(v.address, amount)

    collateral_before = collateral_tok.balanceOf(v.address)
    payment_before = payment_tok.balanceOf(v.address)

    v.withdraw_funds(payment_tok.address, amount, sender=min_vault_manager.address)

    # Payment token should have been transferred, not collateral
    assert payment_tok.balanceOf(v.address) == payment_before - amount
    assert collateral_tok.balanceOf(v.address) == collateral_before  # unchanged


def test_buy_twice_accumulates_pending(vault_acred, caller_addr, usdc, owner):
    """Two consecutive buy() calls accumulate pending additively, not overwrite."""
    v = vault_acred

    # First buy
    stable_amount_1 = 10
    usdc.mint(owner, stable_amount_1)
    usdc.approve(v.address, stable_amount_1, sender=owner)
    v.buy(usdc.address, 0, stable_amount_1, sender=owner)

    # With oracle rate 3/10: ds_tokens = 10 * 10 // 3 = 33
    first_ds = v.pending_transfers(owner)
    first_total = v.pending_transfers_total()
    assert first_ds > 0

    # Second buy
    stable_amount_2 = 10
    usdc.mint(owner, stable_amount_2)
    usdc.approve(v.address, stable_amount_2, sender=owner)
    v.buy(usdc.address, 0, stable_amount_2, sender=owner)

    second_ds = v.pending_transfers(owner)
    second_total = v.pending_transfers_total()

    assert second_ds == first_ds * 2
    assert second_total == first_total * 2


def test_buy_approves_correct_spender(securitize_vault_contract_def, acred, usdc, owner):
    """The approve targets the SecuritizeSwap contract (getDSService(1<<14)), not self.token."""
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, acred.address, sender=owner)

    # Get the swap contract address (same as what buy() would compute)
    swap_addr = acred.getDSService(1 << 14)

    stable_amount = 10
    # oracle num=3, den=10: ds = 10*10//3 = 33, swap pulls 33*3//10 = 9, leaving 1 of the approval unused
    liquidity_pulled = (stable_amount * 10 // 3) * 3 // 10  # 9
    residual_allowance = stable_amount - liquidity_pulled  # 1
    usdc.mint(owner, stable_amount)
    usdc.approve(v.address, stable_amount, sender=owner)

    # Before buy, swap contract has no allowance
    assert usdc.allowance(v.address, swap_addr) == 0

    v.buy(usdc.address, 0, stable_amount, sender=owner)

    # buy approved the swap contract for stable_amount; the swap's transferFrom then pulled 9,
    # leaving the residual allowance on the swap contract. A nonzero residual proves the approve
    # (and the consuming transferFrom) targeted the swap contract, not some other address.
    assert usdc.allowance(v.address, swap_addr) == residual_allowance


def test_deposit_partial_pending_multi_wallet(securitize_vault_contract_def, failing_transfer_erc20, owner):
    """A partial-pending deposit decrements pending_transfers_total by that wallet's pending
    only, leaving other wallets' pending in the total."""
    caller = boa.env.generate_address("lending_contract")
    wallet_a = boa.env.generate_address("wallet_a")
    wallet_b = boa.env.generate_address("wallet_b")

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, failing_transfer_erc20.address, sender=caller)

    # Deposit tokens for both wallets (failing_transfer_erc20 tracks balances)
    deposit_a = 500
    deposit_b = 300
    v.deposit(deposit_a, wallet_a, sender=caller)
    v.deposit(deposit_b, wallet_b, sender=caller)

    assert failing_transfer_erc20.balanceOf(v.address) == deposit_a + deposit_b

    # Withdraw for both wallets -- transfer always fails in this mock,
    # so both go to pending
    v.withdraw(deposit_a, wallet_a, sender=caller)
    v.withdraw(deposit_b, wallet_b, sender=caller)

    assert v.pending_transfers(wallet_a) == deposit_a
    assert v.pending_transfers(wallet_b) == deposit_b
    assert v.pending_transfers_total() == deposit_a + deposit_b

    # Now deposit for wallet_a with amount > pending (elif branch: partial pending)
    new_deposit = deposit_a + 100  # 600, larger than pending 500
    v.deposit(new_deposit, wallet_a, sender=caller)

    # wallet_a's pending should be cleared (0)
    assert v.pending_transfers(wallet_a) == 0

    # Total decremented by wallet_a's pending (500), leaving wallet_b's (300)
    assert v.pending_transfers_total() == deposit_b


def test_check_user_proxy_requires_tx_origin_match(
    securitize_vault_contract_def, acred, usdc, owner, min_vault_manager, vault_proxy
):
    """An authorized proxy may act only when user == tx.origin; a call from anyone other than
    the vault owner reverts even though the proxy is authorized."""
    vault_owner = boa.env.generate_address("vault_owner")
    different_user = boa.env.generate_address("different_user")
    boa.env.set_balance(vault_owner, 10**21)
    boa.env.set_balance(different_user, 10**21)

    v = securitize_vault_contract_def.deploy()
    v.initialise(vault_owner, acred.address, sender=min_vault_manager.address)

    # Authorize the vault_proxy contract
    min_vault_manager.set_proxy(vault_proxy.address, True)

    stable_amount = 10

    # When vault_owner (== user) initiates the transaction through the proxy,
    # tx.origin == vault_owner == user, so _check_user passes
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault_proxy.address, stable_amount, sender=vault_owner)
    vault_proxy.proxy_buy(v.address, usdc.address, 0, stable_amount, sender=vault_owner)

    assert v.pending_transfers(vault_owner) > 0  # buy succeeded

    # When a different_user initiates through the same proxy,
    # tx.origin == different_user != vault_owner, so _check_user fails
    usdc.mint(different_user, stable_amount)
    usdc.approve(vault_proxy.address, stable_amount, sender=different_user)
    with boa.reverts("unauthorized"):
        vault_proxy.proxy_buy(v.address, usdc.address, 0, stable_amount, sender=different_user)


def test_initialise_checks_caller_not_owner(securitize_vault_contract_def, owner):
    """Initialise guard checks self.caller == empty(address), not self.owner: re-initialising
    after a first init with _owner=empty(address) must still revert."""
    acred = boa.load(
        "contracts/auxiliary/AcredMock.vy",
        "ACRED",
        "ACRED",
        6,
        10**6,
        boa.load("contracts/auxiliary/OracleMock.vy", 1, 1).address,
        boa.env.generate_address("usdc"),
    )

    vault = securitize_vault_contract_def.deploy()

    # First initialise with _owner = empty(address) -- a valid (if unusual) setup
    vault.initialise(boa.eval("empty(address)"), acred.address, sender=owner)

    # caller should now be set to owner (msg.sender of first call)
    assert vault.caller() == owner

    # Second initialise must revert because caller is already set
    with boa.reverts("already initialised"):
        vault.initialise(owner, acred.address, sender=owner)


def test_deposit_uses_full_pending_path_when_pending_exceeds_amount(
    securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner
):
    """When pending_transfers[wallet] > deposit amount, the full-pending (pending >= amount) branch is used."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    # Deposit some tokens normally so vault has balance
    token.mint(owner, 200)
    token.approve(vault.address, 200, sender=owner)
    vault.deposit(200, owner, sender=min_vault_manager.address)
    assert token.balanceOf(vault.address) == 200

    # Simulate a failed withdraw: blacklist the recipient so raw_call fails
    recipient = boa.env.generate_address("recipient")
    boa.env.set_balance(recipient, 10**18)
    token.blacklist(recipient, True, sender=owner)

    # Withdraw to blacklisted recipient -- transfer will fail, creating pending
    vault.withdraw(150, recipient, sender=min_vault_manager.address)
    assert vault.pending_transfers(recipient) == 150
    assert vault.pending_transfers_total() == 150

    # Now deposit 50 for recipient (pending=150, amount=50, so pending > amount)
    # With correct code (>=), this should use full-pending path:
    #   pending_transfers[recipient] = 150 - 50 = 100
    #   pending_transfers_total -= 50 -> 100
    #   No transferFrom needed
    vault.deposit(50, recipient, sender=min_vault_manager.address)

    # After deposit: pending should be reduced by amount (50), not cleared
    assert vault.pending_transfers(recipient) == 100
    assert vault.pending_transfers_total() == 100

    # Token balance unchanged (no transferFrom in full-pending path)
    assert token.balanceOf(vault.address) == 200


def test_withdraw_funds_sends_to_caller_not_msg_sender(
    securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner, vault_proxy
):
    """withdraw_funds transfers to self.caller (lending contract), not msg.sender: via a proxy
    (msg.sender != caller) funds go to the lending contract, not the proxy."""
    payment_token = weth9_contract_def.deploy("PAY", "PAY", 18, 10**30)
    collateral_token = weth9_contract_def.deploy("COL", "COL", 18, 10**30)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, collateral_token.address, sender=min_vault_manager.address)

    # Authorize the proxy in the vault manager mock
    min_vault_manager.set_proxy(vault_proxy.address, True)

    # Fund the vault with payment tokens
    amount = 1000
    payment_token.mint(vault.address, amount)

    vault_manager_balance_before = payment_token.balanceOf(min_vault_manager.address)
    proxy_balance_before = payment_token.balanceOf(vault_proxy.address)

    vault_proxy.proxy_withdraw_funds(vault.address, payment_token.address, amount, sender=min_vault_manager.address)

    # Funds should go to self.caller (min_vault_manager), NOT to vault_proxy (msg.sender)
    assert payment_token.balanceOf(min_vault_manager.address) == vault_manager_balance_before + amount
    assert payment_token.balanceOf(vault_proxy.address) == proxy_balance_before  # proxy gets nothing


def test_buy_transfers_from_msg_sender_not_owner(
    securitize_vault_contract_def, min_vault_manager, acred, usdc, owner, vault_proxy
):
    """buy() does transferFrom(msg.sender, ...), not transferFrom(self.owner, ...): via a proxy
    call the funds come from the actual caller, not the vault owner."""
    # Create vault with a specific owner (different from proxy caller)
    vault_owner = boa.env.generate_address("vault_owner")
    boa.env.set_balance(vault_owner, 10**18)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(vault_owner, acred.address, sender=min_vault_manager.address)

    # Authorize the vault_proxy in the vault manager mock
    min_vault_manager.set_proxy(vault_proxy.address, True)

    stable_amount = 10
    # Fund vault_owner with stablecoins (they transfer to proxy, which transfers to vault)
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault_proxy.address, stable_amount, sender=vault_owner)

    vault_proxy.proxy_buy(vault.address, usdc.address, 0, stable_amount, sender=vault_owner)

    # Verify the buy succeeded
    assert vault.pending_transfers(vault_owner) == 10 * 10 // 3  # credited to owner
    assert usdc.balanceOf(vault_owner) == 0  # vault_owner spent all their USDC


def test_buy_refund_goes_to_msg_sender_not_caller(
    securitize_vault_contract_def, min_vault_manager, acred, usdc, owner, vault_proxy
):
    """buy() refund goes to msg.sender (proxy), not self.caller: excess stablecoins after the
    swap return to whoever called buy, not the lending contract."""
    vault_owner = boa.env.generate_address("vault_owner2")
    boa.env.set_balance(vault_owner, 10**18)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(vault_owner, acred.address, sender=min_vault_manager.address)

    # Authorize the vault_proxy in the vault manager mock
    min_vault_manager.set_proxy(vault_proxy.address, True)

    # Use stable_amount=11 to trigger refund (with oracle rate num=3, den=10):
    # swap(11): ds = 11*10//3 = 36, liquidity pulled = 36*3//10 = 10
    # Only 10 of 11 consumed, 1 returned
    stable_amount = 11
    usdc.mint(vault_owner, stable_amount)
    usdc.approve(vault_proxy.address, stable_amount, sender=vault_owner)

    vault_manager_usdc_before = usdc.balanceOf(min_vault_manager.address)

    vault_proxy.proxy_buy(vault.address, usdc.address, 0, stable_amount, sender=vault_owner)

    # Refund (1 USDC) should go to vault_proxy (msg.sender in vault context), NOT min_vault_manager (self.caller)
    assert usdc.balanceOf(vault_proxy.address) == 1  # proxy gets the refund
    assert usdc.balanceOf(min_vault_manager.address) == vault_manager_usdc_before  # vault manager unchanged


def test_deposit_emits_deposit_event(securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner):
    """Deposit emits a Deposit event."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    amount = 100
    token.mint(owner, amount)
    token.approve(vault.address, amount, sender=owner)

    vault.deposit(amount, owner, sender=min_vault_manager.address)

    events = [e for e in vault.get_logs() if type(e).__name__ == "Deposit"]
    assert len(events) == 1
    assert events[0].wallet == owner
    assert events[0].amount == amount


def test_withdraw_success_emits_withdraw_event(securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner):
    """Successful withdraw emits a Withdraw event."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    # Deposit first
    amount = 100
    token.mint(owner, amount)
    token.approve(vault.address, amount, sender=owner)
    vault.deposit(amount, owner, sender=min_vault_manager.address)

    # Withdraw
    recipient = boa.env.generate_address("recipient")
    boa.env.set_balance(recipient, 10**18)
    vault.withdraw(50, recipient, sender=min_vault_manager.address)

    events = [e for e in vault.get_logs() if type(e).__name__ == "Withdraw"]
    assert len(events) == 1
    assert events[0].wallet == recipient
    assert events[0].amount == 50


def test_withdraw_failure_emits_transfer_failed_event(
    securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner
):
    """Failed withdraw emits a TransferFailed event."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    amount = 100
    token.mint(owner, amount)
    token.approve(vault.address, amount, sender=owner)
    vault.deposit(amount, owner, sender=min_vault_manager.address)

    # Blacklist recipient to cause transfer failure
    recipient = boa.env.generate_address("blocked")
    boa.env.set_balance(recipient, 10**18)
    token.blacklist(recipient, True, sender=owner)

    vault.withdraw(50, recipient, sender=min_vault_manager.address)

    events = [e for e in vault.get_logs() if type(e).__name__ == "TransferFailed"]
    assert len(events) == 1
    assert events[0].wallet == recipient
    assert events[0].amount == 50


def test_withdraw_pending_emits_event(securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner):
    """withdraw_pending emits a WithdrawPending event."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    # Create pending: deposit, then withdraw to blacklisted address
    amount = 100
    token.mint(owner, amount)
    token.approve(vault.address, amount, sender=owner)
    vault.deposit(amount, owner, sender=min_vault_manager.address)

    recipient = boa.env.generate_address("blocked2")
    boa.env.set_balance(recipient, 10**18)
    token.blacklist(recipient, True, sender=owner)
    vault.withdraw(50, recipient, sender=min_vault_manager.address)
    assert vault.pending_transfers(recipient) == 50

    # Unblacklist and withdraw_pending
    token.blacklist(recipient, False, sender=owner)
    vault.withdraw_pending(30, sender=recipient)

    events = [e for e in vault.get_logs() if type(e).__name__ == "WithdrawPending"]
    assert len(events) == 1
    assert events[0].wallet == recipient
    assert events[0].amount == 30


def test_deposit_full_pending_emits_correct_withdraw_pending_amount(
    securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner
):
    """In the full-pending deposit branch, WithdrawPending logs amount (not pending)."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    # Deposit tokens to vault
    token.mint(owner, 200)
    token.approve(vault.address, 200, sender=owner)
    vault.deposit(200, owner, sender=min_vault_manager.address)

    # Create pending via failed withdraw
    recipient = boa.env.generate_address("rec_event1")
    boa.env.set_balance(recipient, 10**18)
    token.blacklist(recipient, True, sender=owner)
    vault.withdraw(100, recipient, sender=min_vault_manager.address)
    assert vault.pending_transfers(recipient) == 100

    # Now deposit 50 for recipient (pending=100 >= amount=50, full-pending path)
    vault.deposit(50, recipient, sender=min_vault_manager.address)

    # The WithdrawPending event should log amount=50 (the deposit amount), NOT amount=100 (pending)
    wp_events = [e for e in vault.get_logs() if type(e).__name__ == "WithdrawPending"]
    assert len(wp_events) == 1
    assert wp_events[0].wallet == recipient
    assert wp_events[0].amount == 50  # This is the deposit amount, not the pending amount


def test_deposit_partial_pending_emits_correct_withdraw_pending_amount(
    securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner
):
    """In the partial-pending deposit branch, WithdrawPending logs pending (not amount)."""
    token = weth9_contract_def.deploy("TOK", "TOK", 18, 10**30)
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    # Deposit tokens to vault
    token.mint(owner, 200)
    token.approve(vault.address, 200, sender=owner)
    vault.deposit(200, owner, sender=min_vault_manager.address)

    # Create pending via failed withdraw
    recipient = boa.env.generate_address("rec_event2")
    boa.env.set_balance(recipient, 10**18)
    token.blacklist(recipient, True, sender=owner)
    vault.withdraw(30, recipient, sender=min_vault_manager.address)
    assert vault.pending_transfers(recipient) == 30

    # Unblacklist so transferFrom succeeds in the elif branch
    token.blacklist(recipient, False, sender=owner)

    # Now deposit 100 for recipient (pending=30 < amount=100, partial-pending path)
    token.mint(recipient, 70)  # recipient needs 100-30=70 tokens for transferFrom
    token.approve(vault.address, 70, sender=recipient)
    vault.deposit(100, recipient, sender=min_vault_manager.address)

    # The WithdrawPending event should log amount=30 (the pending amount), NOT amount=100
    wp_events = [e for e in vault.get_logs() if type(e).__name__ == "WithdrawPending"]
    assert len(wp_events) == 1
    assert wp_events[0].wallet == recipient
    assert wp_events[0].amount == 30  # This is the pending amount, not the deposit amount


def test_transfer_funds_reverts_if_not_authorized(securitize_vault_contract_def, min_vault_manager, weth9_contract_def, owner):
    """transfer_funds is callable only by the lending contract (self.caller) or an authorized
    proxy; an unauthorized sender is rejected with "unauthorized"."""
    token = weth9_contract_def.deploy("COL", "COL", 18, 10**30)
    payment_tok = weth9_contract_def.deploy("PAY", "PAY", 6, 10**20)

    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, token.address, sender=min_vault_manager.address)

    # Fund the vault with payment tokens so the transfer itself would succeed
    amount = 500
    payment_tok.mint(vault.address, amount)

    # An unauthorized address should be rejected
    unauthorized = boa.env.generate_address("unauthorized")
    with boa.reverts("unauthorized"):
        vault.transfer_funds(payment_tok.address, amount, unauthorized, sender=unauthorized)


def test_buy_passes_min_ds_token_to_swap(vault_acred, acred, usdc, owner):
    """The vault forwards min_ds_token_amount to swap(), not zero (verified via trace inspection)."""

    stable_amount = 10
    min_ds = 3  # AcredMock rate 3/10: calculateDsTokenAmount(10) = 3, so the min-ds check passes
    usdc.mint(owner, stable_amount)
    usdc.approve(vault_acred.address, stable_amount, sender=owner)

    vault_acred.buy(usdc.address, min_ds, stable_amount, sender=owner)

    # Inspect the swap(uint256,uint256) call in the computation trace
    swap_calls = get_calls(vault_acred, "swap(uint256,uint256)", ["uint256", "uint256"])
    assert len(swap_calls) == 1
    assert swap_calls[0][1] == min_ds  # second arg is minOutAmount


def test_buy_refund_only_excess_not_full_balance(securitize_vault_contract_def, acred, usdc, owner):
    """With a pre-existing payment-token balance, the refund returns only the swap excess
    (remaining - initial), not the full remaining balance."""
    vault = securitize_vault_contract_def.deploy()
    vault.initialise(owner, acred.address, sender=owner)

    # Pre-fund the vault with 100 USDC (this is the pre-existing balance)
    pre_existing = 100
    usdc.mint(vault.address, pre_existing)
    assert usdc.balanceOf(vault.address) == pre_existing

    # Call buy with stable_amount=11 to trigger a 1 USDC refund
    # With oracle rate num=3, den=10:
    #   swap(11): ds = 11*10//3 = 36, liquidity pulled = 36*3//10 = 10
    #   Only 10 of 11 stablecoins consumed, 1 returned to vault
    stable_amount = 11
    usdc.mint(owner, stable_amount)
    usdc.approve(vault.address, stable_amount, sender=owner)

    owner_usdc_before = usdc.balanceOf(owner)
    vault.buy(usdc.address, 0, stable_amount, sender=owner)

    # refund = remaining(101) - initial(100) = 1; owner spent 11, gets 1 back -> net spend 10
    assert usdc.balanceOf(owner) == owner_usdc_before - stable_amount + 1

    # Vault should retain its pre-existing 100 USDC
    assert usdc.balanceOf(vault.address) == pre_existing


def test_transfer_funds_transfers_amount_one(securitize_vault_contract_def, weth9_contract_def, owner, min_vault_manager):
    """When amount == 1 (boundary), transfer_funds still calls ERC20.transfer and moves the token."""
    payment_tok = weth9_contract_def.deploy("PayToken", "PT", 6, 10**20)
    collateral_tok = weth9_contract_def.deploy("CollatToken", "CT", 18, 10**20)

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, collateral_tok.address, sender=min_vault_manager.address)

    # Fund the vault with 1 payment token
    payment_tok.mint(v.address, 1)

    wallet = boa.env.generate_address("recipient")
    assert payment_tok.balanceOf(wallet) == 0

    v.transfer_funds(payment_tok.address, 1, wallet, sender=min_vault_manager.address)

    assert payment_tok.balanceOf(wallet) == 1
    assert payment_tok.balanceOf(v.address) == 0


def test_transfer_funds_reverts_if_transfer_returns_false(
    securitize_vault_contract_def, failing_transfer_erc20, owner, min_vault_manager
):
    """When the token's transfer() returns False, transfer_funds reverts with "transfer failed"."""
    collateral_tok = failing_transfer_erc20  # has transfer->False, transferFrom->True

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, collateral_tok.address, sender=min_vault_manager.address)

    # Fund the vault with tokens via transferFrom (which returns True in this mock)
    v.deposit(100, owner, sender=min_vault_manager.address)
    assert collateral_tok.balanceOf(v.address) == 100

    wallet = boa.env.generate_address("recipient")

    # transfer_funds calls IERC20(payment_token).transfer(wallet, amount)
    # The failing_transfer_erc20's transfer() returns False
    with boa.reverts("transfer failed"):
        v.transfer_funds(collateral_tok.address, 50, wallet, sender=min_vault_manager.address)


def test_withdraw_funds_reverts_if_transfer_returns_false(
    securitize_vault_contract_def, failing_transfer_erc20, weth9_contract_def, owner, min_vault_manager
):
    """When the payment token's transfer() returns False, withdraw_funds reverts."""
    collateral_tok = weth9_contract_def.deploy("Collateral", "COL", 18, 10**20)
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, collateral_tok.address, sender=min_vault_manager.address)

    # Fund the vault with the false-transfer payment token
    failing_transfer_erc20.mint(v.address, 500)
    assert failing_transfer_erc20.balanceOf(v.address) == 500

    # withdraw_funds calls IERC20(payment_token).transfer(self.caller, amount)
    # The failing_transfer_erc20's transfer() returns False -> must revert
    with boa.reverts("transfer failed"):
        v.withdraw_funds(failing_transfer_erc20.address, 100, sender=min_vault_manager.address)


def test_withdraw_pending_reverts_if_collateral_transfer_returns_false(
    securitize_vault_contract_def, failing_transfer_erc20, owner
):
    """When the collateral token's transfer() returns False, withdraw_pending reverts."""
    caller_addr = boa.env.generate_address("lending_contract")
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, failing_transfer_erc20.address, sender=caller_addr)

    wallet = boa.env.generate_address("wallet")

    # Deposit to build vault balance (transferFrom works in failing_transfer_erc20)
    v.deposit(100, wallet, sender=caller_addr)
    assert failing_transfer_erc20.balanceOf(v.address) == 100

    # Withdraw to create pending (transfer fails -> pending created)
    v.withdraw(50, wallet, sender=caller_addr)
    assert v.pending_transfers(wallet) == 50

    # Now try withdraw_pending: calls IERC20(self.token).transfer(msg.sender, amount)
    # The failing_transfer_erc20's transfer returns False -> must revert
    with boa.reverts("transfer failed"):
        v.withdraw_pending(50, sender=wallet)


def test_deposit_partial_pending_reverts_if_transfer_from_returns_false(
    securitize_vault_contract_def, false_transfer_from_erc20, owner
):
    """In the deposit elif branch (0 < pending < amount), a failing transferFrom reverts
    with "transferFrom failed"."""
    caller_addr = boa.env.generate_address("lending_contract")
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, false_transfer_from_erc20.address, sender=caller_addr)

    wallet = boa.env.generate_address("wallet")

    # Set up pending < deposit amount to enter elif branch
    pending = 30
    deposit_amount = 100
    v.eval(f"self.pending_transfers[{wallet}] = {pending}")
    v.eval(f"self.pending_transfers_total = {pending}")
    # Give vault a balance so it looks consistent
    false_transfer_from_erc20.eval(f"self.balances[{v.address}] = {pending}")

    # deposit enters elif branch (pending > 0 and pending < amount)
    # calls transferFrom(wallet, self, 70) which returns False -> must revert
    with boa.reverts("transferFrom failed"):
        v.deposit(deposit_amount, wallet, sender=caller_addr)


def test_deposit_no_pending_reverts_if_transfer_from_returns_false(
    securitize_vault_contract_def, false_transfer_from_erc20, owner
):
    """In the deposit else branch (no pending), a failing transferFrom reverts with "transferFrom failed"."""
    caller_addr = boa.env.generate_address("lending_contract")
    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, false_transfer_from_erc20.address, sender=caller_addr)

    wallet = boa.env.generate_address("wallet")

    # No pending -> enters else branch
    assert v.pending_transfers(wallet) == 0

    # transferFrom returns False -> must revert
    with boa.reverts("transferFrom failed"):
        v.deposit(100, wallet, sender=caller_addr)


def test_buy_reverts_if_payment_transfer_from_returns_false(
    securitize_vault_contract_def, false_transfer_from_erc20, acred_contract_def, oracle_contract_def, owner
):
    """When the payment token's transferFrom() returns False, buy reverts with "transferFrom failed"."""
    oracle = oracle_contract_def.deploy(1, 3)
    acred = acred_contract_def.deploy("ACRED", "ACRED", 6, 10**6, oracle.address, false_transfer_from_erc20.address)

    v = securitize_vault_contract_def.deploy()
    v.initialise(owner, acred.address, sender=owner)

    stable_amount = 10
    false_transfer_from_erc20.mint(owner, stable_amount)
    false_transfer_from_erc20.approve(v.address, stable_amount, sender=owner)

    # buy calls IERC20(payment_token).transferFrom(msg.sender, self, stable_coin_amount)
    # With false_transfer_from_erc20, transferFrom returns False -> must revert
    with boa.reverts("transferFrom failed"):
        v.buy(false_transfer_from_erc20.address, 0, stable_amount, sender=owner)
