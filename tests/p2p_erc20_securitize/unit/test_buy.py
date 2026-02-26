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
