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


interface ProfitInterestPayment:
    def claimInterest(_amount: uint256): nonpayable

implements: Vault


VERSION: public(constant(String[30])) = "P2PLendingVault.20260113"

# Structs

event Deposit:
    wallet: address
    amount: uint256

event Withdraw:
    wallet: address
    amount: uint256


# Global variables


owner: public(address)
caller: public(address)
token: public(address)

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
@nonreentrant
def deposit(amount: uint256, wallet: address):
    """
    @notice Deposit tokens into the vault on behalf of a specified wallet.
    @dev Transfers tokens from the wallet to the vault and emits a Deposit event.
    @param amount The amount of tokens to deposit.
    @param wallet The address of the wallet from which tokens will be transferred.
    """

    assert msg.sender == self.caller, "unauthorized"
    assert extcall IERC20(self.token).transferFrom(wallet, self, amount), "transferFrom failed"
    log Deposit(wallet=wallet, amount=amount)

@external
@nonreentrant
def withdraw(amount: uint256, wallet: address):
    """
    @notice Withdraw tokens from the vault to a specified wallet.
    @dev Transfers tokens from the vault to the wallet and emits a Withdraw event.
    @param amount The amount of tokens to withdraw.
    @param wallet The address of the wallet to which tokens will be transferred.
    """
    assert msg.sender == self.caller, "unauthorized"
    assert extcall IERC20(self.token).transfer(wallet, amount), "transfer failed"
    log Withdraw(wallet=wallet, amount=amount)

@external
@nonreentrant
def claimInterest(interest_payment: address, payment_token: address, amount: uint256):
    balance_before: uint256 = staticcall IERC20(payment_token).balanceOf(self)
    extcall ProfitInterestPayment(interest_payment).claimInterest(amount)
    assert (staticcall IERC20(payment_token).balanceOf(self)) - balance_before == amount, "incorrect interest amount"
    assert extcall IERC20(payment_token).transfer(self.owner, amount), "transfer failed"
