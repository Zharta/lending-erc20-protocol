# @version 0.4.3

"""
@title P2PLendingVault
@author [Zharta](https://zharta.io/)
@notice This contract implements a vault to hold collateral for peer-to-peer loans
@dev Actual vaults are minimal proxy contracts to this, deployed via CREATE2 by the lending contract

"""

# Interfaces

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

interface Vault:
    def initialise(_owner: address, _token: address): nonpayable
    def deposit(amount: uint256, wallet: address): nonpayable
    def withdraw(amount: uint256, wallet: address): nonpayable
    def withdrawable_balance() -> uint256: view
    def withdraw_funds(payment_token: address, amount: uint256): nonpayable


interface SecuritizeSwap:
    def calculateDsTokenAmount(_stableCoinAmount: uint256) -> (uint256, uint256): view
    def calculateStableCoinAmount(_dsTokenAmount: uint256) -> uint256: view
    def buy(_dsTokenAmount: uint256, _maxStableCoinAmount: uint256): nonpayable


interface SecuritizeDSToken:
    def getDSService(_serviceId: uint256) -> address: view

interface P2PLendingContract:
    def authorized_proxies(proxy: address) -> bool: view

implements: Vault


VERSION: public(constant(String[30])) = "P2PLendingVaultSecur.20251211"

# Structs

event Deposit:
    wallet: address
    amount: uint256

event Withdraw:
    wallet: address
    amount: uint256

event TransferFailed:
    wallet: address
    amount: uint256

event WithdrawPending:
    wallet: address
    amount: uint256

# Global variables


owner: public(address)
caller: public(address)
token: public(address)
pending_transfers: public(HashMap[address, uint256])
pending_transfers_total: public(uint256)


@deploy
def __init__():
    pass


@external
def initialise(_owner: address, _token: address):

    """
    @notice Initialize a vault with the given owner, enabling it to receive specific tokens.
    @dev Ensures that the vault is not already initialized before setting the owner and caller.
    @param _owner The address of the vault's owner.
    @param _token The address of the ERC20 token that the vault will hold.
    """

    assert self.caller == empty(address), "already initialised"

    self.caller = msg.sender
    self.owner = _owner
    self.token = _token


@external
def deposit(amount: uint256, wallet: address):
    """
    @notice Deposit tokens into the vault on behalf of a specified wallet.
    @dev Transfers tokens from the wallet to the vault and emits a Deposit event.
    @param amount The amount of tokens to deposit.
    @param wallet The address of the wallet from which tokens will be transferred.
    """

    assert msg.sender == self.caller, "unauthorized"

    pending: uint256 = self.pending_transfers[wallet]
    if pending >= amount:
        self.pending_transfers[wallet] = pending - amount
        self.pending_transfers_total -= amount
        log WithdrawPending(wallet=wallet, amount=amount)
    elif pending > 0:
        self.pending_transfers_total -= pending
        self.pending_transfers[wallet] = 0
        log WithdrawPending(wallet=wallet, amount=pending)
        assert extcall IERC20(self.token).transferFrom(wallet, self, amount - pending), "transferFrom failed"
    else:
        assert extcall IERC20(self.token).transferFrom(wallet, self, amount), "transferFrom failed"
    log Deposit(wallet=wallet, amount=amount)

@external
def withdraw(amount: uint256, wallet: address):
    """
    @notice Withdraw tokens from the vault to a specified wallet.
    @dev Transfers tokens from the vault to the wallet and emits a Withdraw event.
    @param amount The amount of tokens to withdraw.
    @param wallet The address of the wallet to which tokens will be transferred.
    """
    assert msg.sender == self.caller, "unauthorized"
    assert amount + self.pending_transfers_total <= staticcall IERC20(self.token).balanceOf(self), "insufficient balance"

    success: bool = False
    response: Bytes[32] = b""

    success, response = raw_call(
        self.token,
        abi_encode(wallet, amount, method_id=method_id("transfer(address,uint256)")),
        max_outsize=32,
        revert_on_failure=False
    )

    if not success or not convert(response, bool):
        log TransferFailed(wallet=wallet, amount=amount)
        self.pending_transfers[wallet] += amount
        self.pending_transfers_total += amount
    else:
        log Withdraw(wallet=wallet, amount=amount)


@external
@view
def withdrawable_balance() -> uint256:
    """
    @notice Get the withdrawable balance of the vault.
    @dev Calculates the withdrawable balance by subtracting pending transfers from the total token balance.
    @return The withdrawable balance of the vault.
    """
    return staticcall IERC20(self.token).balanceOf(self) - self.pending_transfers_total


@external
def withdraw_pending(amount: uint256):
    """
    @notice Withdraw tokens from the vault that are pending transfer to the sender.
    @dev Transfers tokens from the vault to the sender and emits a WithdrawPending event.
    @param amount The amount of tokens to withdraw.
    """
    assert self.pending_transfers[msg.sender] >= amount, "insufficient pending collateral"
    self.pending_transfers[msg.sender] -= amount
    self.pending_transfers_total -= amount
    assert extcall IERC20(self.token).transfer(msg.sender, amount), "transfer failed"
    log WithdrawPending(wallet=msg.sender, amount=amount)


@external
def withdraw_funds(payment_token: address, amount: uint256):
    """
    @notice Withdraw specified funds from the vault to the caller.
    @dev Transfers the specified amount of payment tokens from the vault to the caller (main contract).
    @param payment_token The address of the payment token to withdraw.
    @param amount The amount of tokens to withdraw.
    """

    assert self._check_user(self.caller), "unauthorized"
    assert extcall IERC20(payment_token).transfer(self.caller, amount), "transfer failed"


@external
def buy(payment_token: address, ds_token_amount: uint256, max_stable_coin_amount: uint256):
    """
    @notice Buy DS tokens using stable coins via the SecuritizeSwap contract.
    @dev Approves the SecuritizeSwap contract to spend stable coins and executes the buy operation.
    @param ds_token_amount The amount of DS tokens to buy.
    @param max_stable_coin_amount The maximum amount of stable coins to spend.
    """

    assert self._check_user(self.owner), "unauthorized"

    securitize_swap_contract: address = staticcall SecuritizeDSToken(self.token).getDSService(1<<14)

    initial_balance: uint256 = staticcall IERC20(payment_token).balanceOf(self)
    extcall IERC20(payment_token).transferFrom(msg.sender, self, max_stable_coin_amount)
    extcall IERC20(payment_token).approve(securitize_swap_contract, max_stable_coin_amount)
    extcall SecuritizeSwap(securitize_swap_contract).buy(ds_token_amount, max_stable_coin_amount)

    self.pending_transfers[self.owner] += ds_token_amount
    self.pending_transfers_total += ds_token_amount

    remaining_balance: uint256 = staticcall IERC20(payment_token).balanceOf(self)
    extcall IERC20(payment_token).transfer(msg.sender, remaining_balance - initial_balance)

@internal
def _check_user(user: address) -> bool:
    return msg.sender == user or (staticcall P2PLendingContract(self.caller).authorized_proxies(msg.sender) and user == tx.origin)
