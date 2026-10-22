# @version 0.4.3

"""
@title P2PLendingVaultMidas
@author [Zharta](https://zharta.io/)
@notice This contract implements a vault to hold Midas mToken collateral for peer-to-peer loans
@dev Actual vaults are minimal proxy contracts to this, deployed via CREATE2 by the lending contract

"""

# Interfaces

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingMultiVaultBase as base

interface MidasDepositVault:
    def depositInstant(tokenIn: address, amountToken: uint256, minReceiveAmount: uint256, referrerId: bytes32, tokensReceiver: address): nonpayable

interface MidasRedemptionVault:
    def redeemInstant(tokenOut: address, amountMTokenIn: uint256, minReceiveAmount: uint256): nonpayable
    def instantFee() -> uint256: view
    def tokensConfig(token: address) -> MidasTokenConfig: view
    def waivedFeeRestriction(user: address) -> bool: view



BPS: constant(uint256) = 10000

implements: base.Vault


VERSION: public(constant(String[30])) = "P2PLendingVaultMidas.20260423"

# Midas supports instant mint (depositInstant) and instant redeem (redeemInstant).
capabilities: public(constant(uint256)) = base.MINT_SYNC | base.REDEEM_SYNC

# Structs

struct MidasTokenConfig:
    dataFeed: address
    fee: uint256
    allowance: uint256
    stable: bool


# Events
#
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

event Buy:
    owner: address
    deposit_vault: address
    stable_coin_amount: uint256
    mtoken_received: uint256

event Redeem:
    owner: address
    redemption_vault: address
    mtoken_amount: uint256
    token_out_received: uint256

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
@nonreentrant
def mint_sync(payment_token: address, deposit_vault: address, min_mtoken_amount: uint256, stable_coin_amount: uint256) -> (uint256, uint256):
    """
    @notice Buy mTokens using stablecoins via a Midas DepositVault contract.
    @dev Approves the DepositVault to spend stablecoins and executes the deposit operation.
    @param payment_token The address of the stablecoin to spend.
    @param deposit_vault The address of the Midas DepositVault contract.
    @param min_mtoken_amount The minimum amount of mTokens to receive
    @param stable_coin_amount The amount of stablecoins to spend (in native token decimals).
    @return A tuple (minted, refunded): the amount of mTokens received and credited to the owner as
            pending, and the payment token balance left in the vault after the mint (the unspent
            pre-funded payment, per Decision Log D2). The lending contract handles the refund.
    """

    assert msg.sender == self.caller, "unauthorized"

    token_decimals: uint256 = convert(staticcall IERC20Detailed(payment_token).decimals(), uint256)
    mtoken_decimals: uint256 = convert(staticcall IERC20Detailed(self.token).decimals(), uint256)

    initial_mtoken_balance: uint256 = staticcall IERC20(self.token).balanceOf(self)
    initial_payment_balance: uint256 = staticcall IERC20(payment_token).balanceOf(self)

    extcall IERC20(payment_token).approve(deposit_vault, stable_coin_amount)
    extcall MidasDepositVault(deposit_vault).depositInstant(
        payment_token,
        stable_coin_amount * (10 ** 18) // (10 ** token_decimals),
        min_mtoken_amount * (10 ** 18) // (10 ** mtoken_decimals),
        empty(bytes32),
        self
    )

    mtoken_received: uint256 = staticcall IERC20(self.token).balanceOf(self) - initial_mtoken_balance
    self.pending_transfers[self.owner] += mtoken_received
    self.pending_transfers_total += mtoken_received

    log Buy(owner=self.owner, deposit_vault=deposit_vault, stable_coin_amount=stable_coin_amount, mtoken_received=mtoken_received)

    spent: uint256 = initial_payment_balance - staticcall IERC20(payment_token).balanceOf(self)
    return mtoken_received, stable_coin_amount - spent


@external
def redeem_manual(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256):
    raise "redeem_manual not supported"


@external
def mint_manual(payment_token: address, deposit_vault: address, min_collateral_out: uint256, stable_coin_amount: uint256):
    raise "mint_manual not supported"


@external
def mint_async(payment_token: address, deposit_vault: address, min_collateral_out: uint256, stable_coin_amount: uint256):
    raise "mint_async not supported"


@external
@view
def mint_status(mint_vault: address) -> base.AsyncStatus:
    raise "mint_status not supported"


@external
def claim_mint(mint_vault: address, claim_deposit: bool, claim_cancel: bool) -> (uint256, uint256):
    raise "claim_mint not supported"


@external
def cancel_mint(mint_vault: address):
    raise "cancel_mint not supported"


@external
def redeem_async(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256):
    raise "redeem_async not supported"


@external
@view
def redeem_status(redemption_vault: address) -> base.AsyncStatus:
    raise "redeem_status not supported"


@external
def claim_redeem(redemption_vault: address, claim_redeem: bool, claim_cancel: bool) -> (uint256, uint256):
    raise "claim_redeem not supported"


@external
def cancel_redeem(redemption_vault: address):
    raise "cancel_redeem not supported"


@external
@nonreentrant
def redeem_sync(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256) -> (uint256, uint256):
    """
    @notice Redeem mTokens back to stablecoins via a Midas RedemptionVault contract.
    @dev Approves the RedemptionVault to spend mTokens and executes the redemption. The minimum
         receive amount is the oracle-implied value of the redeemed mTokens, discounted by the
         RedemptionVault's instant-redeem fee so the call does not revert on that fee.
    @param redemption_vault The address of the Midas RedemptionVault contract.
    @param token_out The address of the token to receive from redemption.
    @param amount_mtoken The amount of mTokens to redeem
    @param oracle_rate_num The numerator of the collateral->payment token oracle rate.
    @param oracle_rate_den The denominator of the collateral->payment token oracle rate.
    """

    assert msg.sender == self.caller, "unauthorized"

    mtoken_decimals: uint256 = convert(staticcall IERC20Detailed(self.token).decimals(), uint256)
    initial_balance: uint256 = staticcall IERC20(token_out).balanceOf(self)

    amount_mtoken_base18: uint256 = amount_mtoken * (10 ** 18) // (10 ** mtoken_decimals)

    fee_percent: uint256 = self._midas_redeem_fee(redemption_vault, token_out)
    amount_without_fee: uint256 = amount_mtoken_base18 - amount_mtoken_base18 * fee_percent // BPS
    min_receive_amount: uint256 = amount_without_fee * oracle_rate_num // oracle_rate_den

    extcall IERC20(self.token).approve(redemption_vault, amount_mtoken)
    extcall MidasRedemptionVault(redemption_vault).redeemInstant(
        token_out,
        amount_mtoken_base18,
        min_receive_amount,
    )

    token_out_received: uint256 = staticcall IERC20(token_out).balanceOf(self) - initial_balance

    log Redeem(owner=self.owner, redemption_vault=redemption_vault, mtoken_amount=amount_mtoken, token_out_received=token_out_received)

    # Midas has no partial-redeem leftover
    return token_out_received, 0


@view
@internal
def _midas_redeem_fee(redemption_vault: address, token_out: address) -> uint256:
    """
    @notice The Midas instant-redeem fee for this vault, in  BPS.
    @dev Mirrors ManageableVault._getFeeAmount: instant fee + per-token fee, waived for whitelisted users.
    """
    if staticcall MidasRedemptionVault(redemption_vault).waivedFeeRestriction(self):
        return 0
    fee_percent: uint256 = (
        staticcall MidasRedemptionVault(redemption_vault).instantFee()
        + (staticcall MidasRedemptionVault(redemption_vault).tokensConfig(token_out)).fee
    )
    return min(fee_percent, BPS)
