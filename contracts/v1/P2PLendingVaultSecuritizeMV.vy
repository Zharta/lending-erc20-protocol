# @version 0.4.3

"""
@title P2PLendingVaultSecuritizeMV
@author [Zharta](https://zharta.io/)
@notice MultiVault-native vault holding Securitize DS Token collateral for peer-to-peer loans
@dev Actual vaults are minimal proxy contracts to this, deployed via CREATE2 by the lending contract.
     This is the MultiVault (P2PLendingMultiVaultErc20) variant, it `implements: base.Vault`.
"""

# Interfaces

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingMultiVaultBase as base

struct DsTokenAmountResult:
    ds_token_amount: uint256
    rate: uint256
    fee: uint256

interface SecuritizeSwap:
    def calculateDsTokenAmount(_stableCoinAmount: uint256) -> DsTokenAmountResult: view
    def swap(_liquidityAmount: uint256, _minOutAmount: uint256): nonpayable


interface SecuritizeDSToken:
    def getDSService(_serviceId: uint256) -> address: view


implements: base.Vault


VERSION: public(constant(String[30])) = "P2PLendingVaultSecMV.20260701"

# Securitize supports instant mint (swap) and manual async redeem.
capabilities: public(constant(uint256)) = base.MINT_SYNC | base.REDEEM_MANUAL

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

    assert msg.sender == self.caller, "unauthorized"
    if amount > 0:
        assert extcall IERC20(payment_token).transfer(self.caller, amount), "transfer failed"


@external
def transfer_funds(payment_token: address, amount: uint256, wallet: address):
    """
    @notice Transfer specified funds from the vault to a specified wallet.
    @dev Transfers the specified amount of payment tokens from the vault to the specified wallet.
    @param payment_token The address of the payment token to withdraw.
    @param amount The amount of tokens to withdraw.
    @param wallet The address of the wallet to which tokens will be transferred.
    """

    assert msg.sender == self.caller, "unauthorized"
    if amount > 0:
        assert extcall IERC20(payment_token).transfer(wallet, amount), "transfer failed"


@external
def mint_sync(payment_token: address, deposit_vault: address, min_ds_token_amount: uint256, stable_coin_amount: uint256) -> (uint256, uint256):
    """
    @notice Buy DS tokens using stable coins via the SecuritizeSwap contract.
    @param payment_token The address of the stable coin to spend.
    @param deposit_vault Ignored in this implementation (not used).
    @param min_ds_token_amount The minimum amount of DS tokens to receive.
    @param stable_coin_amount The amount of stable coins to spend.
    @return A tuple (minted, refunded): the amount of DS tokens received and credited to the owner as
            pending, and the payment token balance left in the vault after the mint (the unspent
            pre-funded payment).
    """

    assert msg.sender == self.caller, "unauthorized"

    securitize_swap_contract: address = staticcall SecuritizeDSToken(self.token).getDSService(1<<14)

    ds_token_amount: DsTokenAmountResult = staticcall SecuritizeSwap(securitize_swap_contract).calculateDsTokenAmount(stable_coin_amount)
    assert ds_token_amount.ds_token_amount >= min_ds_token_amount, "ds token amount lt min"

    initial_ds_balance: uint256 = staticcall IERC20(self.token).balanceOf(self)
    initial_payment_balance: uint256 = staticcall IERC20(payment_token).balanceOf(self)
    extcall IERC20(payment_token).approve(securitize_swap_contract, stable_coin_amount)
    extcall SecuritizeSwap(securitize_swap_contract).swap(stable_coin_amount, min_ds_token_amount)

    ds_received: uint256 = staticcall IERC20(self.token).balanceOf(self) - initial_ds_balance
    self.pending_transfers[self.owner] += ds_received
    self.pending_transfers_total += ds_received

    spent: uint256 = initial_payment_balance - staticcall IERC20(payment_token).balanceOf(self)
    return ds_received, stable_coin_amount - spent


@external
def redeem_manual(redemption_vault: address, token_out: address, amount_in: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256):
    """
    @notice Redeem DS tokens for a specified output token via transfer to a redemption vault.
    @param redemption_vault The address of the vault to which redeemed tokens will be sent.
    @param token_out Ignored in this implementation.
    @param amount_in The amount of DS tokens to redeem.
    @param oracle_rate_num Ignored in this implementation (redemption is async, attested off-chain).
    @param oracle_rate_den Ignored in this implementation (redemption is async, attested off-chain).
    """

    assert msg.sender == self.caller, "unauthorized"
    if amount_in == 0:
        return

    assert amount_in + self.pending_transfers_total <= staticcall IERC20(self.token).balanceOf(self), "insufficient balance"
    assert (extcall IERC20(self.token).transfer(redemption_vault, amount_in, default_return_value=True)), "transfer failed"
    log Withdraw(wallet=redemption_vault, amount=amount_in)


@external
def mint_async(payment_token: address, deposit_vault: address, min_collateral_out: uint256, stable_coin_amount: uint256):
    raise "mint_async not supported"


@external
def mint_manual(payment_token: address, deposit_vault: address, min_collateral_out: uint256, stable_coin_amount: uint256):
    raise "mint_manual not supported"


@external
@view
def mint_status(mint_vault: address) -> base.AsyncStatus:
    raise "mint_status not supported"


@external
def claim_mint(mint_vault: address, claim_deposit: bool, claim_cancel: bool) -> uint256:
    raise "claim_mint not supported"


@external
def cancel_mint(mint_vault: address):
    raise "cancel_mint not supported"


@external
def redeem_sync(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256) -> (uint256, uint256):
    raise "redeem_sync not supported"


@external
def redeem_async(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256):
    raise "redeem_async not supported"


@external
@view
def redeem_status(redemption_vault: address) -> base.AsyncStatus:
    raise "redeem_status not supported"


@external
def claim_redeem(redemption_vault: address, claim_redeem: bool, claim_cancel: bool) -> uint256:
    raise "claim_redeem not supported"


@external
def cancel_redeem(redemption_vault: address):
    raise "cancel_redeem not supported"
