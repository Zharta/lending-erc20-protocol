# @version 0.4.3

"""
@title P2PLendingVaultCentrifugeAsync
@author [Zharta](https://zharta.io/)
@notice This contract implements a vault to hold Centrifuge ERC-7540 AsyncVault share
        collateral for peer-to-peer loans.
@dev Actual vaults are minimal proxy contracts to this, deployed via CREATE2 by the lending
     contract. Unlike the Midas vault (instant mint/redeem), this vault wraps the
     Centrifuge ERC-7540 async flow: deposits and redemptions are requested now and settle
     later, with on-chain queryable status (pending/claimable) and ERC-7887 cancellation.

"""

# Interfaces

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingMultiVaultBase as base

# Centrifuge ERC-7540 AsyncVault (+ ERC-7887 cancellation). The vault is always its own
# controller and owner; Centrifuge uses a single request per controller, so requestId == 0.
interface AsyncVault:
    # ERC-7540 deposit
    def requestDeposit(assets: uint256, controller: address, owner: address) -> uint256: nonpayable
    def pendingDepositRequest(requestId: uint256, controller: address) -> uint256: view
    def claimableDepositRequest(requestId: uint256, controller: address) -> uint256: view
    def deposit(assets: uint256, receiver: address, controller: address) -> uint256: nonpayable
    # ERC-7887 deposit cancellation
    def cancelDepositRequest(requestId: uint256, controller: address): nonpayable
    def pendingCancelDepositRequest(requestId: uint256, controller: address) -> bool: view
    def claimableCancelDepositRequest(requestId: uint256, controller: address) -> uint256: view
    def claimCancelDepositRequest(requestId: uint256, receiver: address, controller: address) -> uint256: nonpayable
    # ERC-7540 redeem
    def requestRedeem(shares: uint256, controller: address, owner: address) -> uint256: nonpayable
    def pendingRedeemRequest(requestId: uint256, controller: address) -> uint256: view
    def claimableRedeemRequest(requestId: uint256, controller: address) -> uint256: view
    def redeem(shares: uint256, receiver: address, controller: address) -> uint256: nonpayable
    # ERC-7887 redeem cancellation
    def cancelRedeemRequest(requestId: uint256, controller: address): nonpayable
    def pendingCancelRedeemRequest(requestId: uint256, controller: address) -> bool: view
    def claimableCancelRedeemRequest(requestId: uint256, controller: address) -> uint256: view
    def claimCancelRedeemRequest(requestId: uint256, receiver: address, controller: address) -> uint256: nonpayable


implements: base.Vault


VERSION: public(constant(String[31])) = "P2PLendingVaultCfAsync.20260714"

REQUEST_ID: constant(uint256) = 0

capabilities: public(constant(uint256)) = base.MINT_ASYNC | base.MINT_STATUS | base.MINT_CANCEL | base.REDEEM_ASYNC | base.REDEEM_STATUS | base.REDEEM_CANCEL


# Events

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

event MintRequested:
    owner: address
    deposit_vault: address
    stable_coin_amount: uint256

event MintClaimed:
    owner: address
    deposit_vault: address
    assets_claimed: uint256
    shares_received: uint256

event MintCancelled:
    owner: address
    deposit_vault: address
    payment_reclaimed: uint256

event RedeemRequested:
    owner: address
    redemption_vault: address
    shares_amount: uint256

event RedeemClaimed:
    owner: address
    redemption_vault: address
    shares_claimed: uint256
    assets_received: uint256

event RedeemCancelled:
    owner: address
    redemption_vault: address
    shares_reclaimed: uint256

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
def mint_sync(payment_token: address, deposit_vault: address, min_mtoken_amount: uint256, stable_coin_amount: uint256) -> (uint256, uint256):
    raise "mint_sync not supported"


@external
def mint_manual(payment_token: address, deposit_vault: address, min_collateral_out: uint256, stable_coin_amount: uint256):
    raise "mint_manual not supported"


@external
def redeem_sync(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256) -> (uint256, uint256):
    raise "redeem_sync not supported"


@external
def redeem_manual(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256):
    raise "redeem_manual not supported"


@external
@nonreentrant
def mint_async(payment_token: address, deposit_vault: address, min_collateral_out: uint256, stable_coin_amount: uint256):
    """
    @notice Request an asynchronous deposit (mint) of collateral shares via a Centrifuge
            ERC-7540 AsyncVault, spending the vault's pre-funded stablecoin balance.
    @param payment_token The address of the stablecoin (payment token) to spend.
    @param deposit_vault The address of the Centrifuge ERC-7540 AsyncVault.
    @param min_collateral_out The minimum amount of collateral shares expected (off-chain accounting).
    @param stable_coin_amount The amount of stablecoins to deposit (in native token decimals).
    """

    assert msg.sender == self.caller, "unauthorized"

    extcall IERC20(payment_token).approve(deposit_vault, stable_coin_amount)
    extcall AsyncVault(deposit_vault).requestDeposit(stable_coin_amount, self, self)

    log MintRequested(owner=self.owner, deposit_vault=deposit_vault, stable_coin_amount=stable_coin_amount)


@external
@view
def mint_status(mint_vault: address) -> base.AsyncStatus:
    """
    @notice The full ERC-7540 / ERC-7887 status of the in-flight async deposit (mint) request.
    @param mint_vault The address of the Centrifuge ERC-7540 AsyncVault the request was made to.
    @return An AsyncStatus(request_pending, request_claimable, cancel_pending, cancel_claimable):
            request_pending   - pendingDepositRequest (assets still being fulfilled)
            request_claimable - claimableDepositRequest (settled assets ready to claim)
            cancel_pending    - 1 if a deposit cancellation is in-flight, else 0
            cancel_claimable  - claimableCancelDepositRequest (reclaimable payment)
    """
    if mint_vault == empty(address):
        return base.AsyncStatus(request_pending=0, request_claimable=0, cancel_pending=0, cancel_claimable=0)

    return base.AsyncStatus(
        request_pending=staticcall AsyncVault(mint_vault).pendingDepositRequest(REQUEST_ID, self),
        request_claimable=staticcall AsyncVault(mint_vault).claimableDepositRequest(REQUEST_ID, self),
        cancel_pending=1 if staticcall AsyncVault(mint_vault).pendingCancelDepositRequest(REQUEST_ID, self) else 0,
        cancel_claimable=staticcall AsyncVault(mint_vault).claimableCancelDepositRequest(REQUEST_ID, self),
    )


@external
@nonreentrant
def claim_mint(mint_vault: address, claim_deposit: bool, claim_cancel: bool) -> uint256:
    """
    @notice Claim a settled async deposit and/or a settled deposit cancellation.
    @dev Two independent claim legs driven by the lending contract once mint_status reports the
         corresponding amounts as claimable:
         - claim_deposit: claims the full claimable deposit via ERC-7540 deposit(assets, self, self).
           The received shares are credited to pending_transfers[owner] (mirroring the Midas
           mint_sync credit), to be consumed by _receive_collateral when the loan starts.
         - claim_cancel: claims the ERC-7887 deposit cancellation via
           claimCancelDepositRequest(self, self), pulling the reclaimed payment back into the vault,
           where it stays for the lending contract to handle.
    @param claim_deposit Whether to claim the settled deposit (mint shares).
    @param claim_cancel Whether to claim the settled deposit cancellation (reclaim payment).
    @return When claim_deposit is set, the amount of collateral shares minted and credited; else when
            only claim_cancel is set, the amount of payment reclaimed into the vault; else 0.
    """

    assert msg.sender == self.caller, "unauthorized"

    shares: uint256 = 0
    reclaimed: uint256 = 0

    if claim_deposit:
        assets: uint256 = staticcall AsyncVault(mint_vault).claimableDepositRequest(REQUEST_ID, self)
        shares = extcall AsyncVault(mint_vault).deposit(assets, self, self)

        self.pending_transfers[self.owner] += shares
        self.pending_transfers_total += shares

        log MintClaimed(owner=self.owner, deposit_vault=mint_vault, assets_claimed=assets, shares_received=shares)

    if claim_cancel:
        reclaimed = extcall AsyncVault(mint_vault).claimCancelDepositRequest(REQUEST_ID, self, self)

        log MintCancelled(owner=self.owner, deposit_vault=mint_vault, payment_reclaimed=reclaimed)

    return shares if claim_deposit else reclaimed


@external
@nonreentrant
def cancel_mint(mint_vault: address):
    """
    @notice Request cancellation of the in-flight async deposit request.
    @param mint_vault The address of the Centrifuge ERC-7540 AsyncVault the request was made to.
    """

    assert msg.sender == self.caller, "unauthorized"

    extcall AsyncVault(mint_vault).cancelDepositRequest(REQUEST_ID, self)


@external
@nonreentrant
def redeem_async(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256):
    """
    @notice Request an asynchronous redemption of collateral shares back to payment token via a
            Centrifuge ERC-7540 AsyncVault.
    @param redemption_vault The address of the Centrifuge ERC-7540 AsyncVault.
    @param token_out The address of the token to receive from redemption (off-chain accounting).
    @param amount_mtoken The amount of collateral shares to redeem.
    @param oracle_rate_num The numerator of the collateral->payment token oracle rate (unused).
    @param oracle_rate_den The denominator of the collateral->payment token oracle rate (unused).
    """

    assert msg.sender == self.caller, "unauthorized"

    extcall IERC20(self.token).approve(redemption_vault, amount_mtoken)
    extcall AsyncVault(redemption_vault).requestRedeem(amount_mtoken, self, self)

    log RedeemRequested(owner=self.owner, redemption_vault=redemption_vault, shares_amount=amount_mtoken)


@external
@view
def redeem_status(redemption_vault: address) -> base.AsyncStatus:
    """
    @notice The full ERC-7540 / ERC-7887 status of the in-flight async redeem request.
    @param redemption_vault The address of the Centrifuge ERC-7540 AsyncVault the request was made to.
    @return An AsyncStatus(request_pending, request_claimable, cancel_pending, cancel_claimable):
            request_pending   - pendingRedeemRequest (shares still being fulfilled)
            request_claimable - claimableRedeemRequest (settled shares ready to claim -> payment)
            cancel_pending    - 1 if a redeem cancellation is in-flight, else 0
            cancel_claimable  - claimableCancelRedeemRequest (reclaimable collateral shares)
    """
    if redemption_vault == empty(address):
        return base.AsyncStatus(request_pending=0, request_claimable=0, cancel_pending=0, cancel_claimable=0)

    return base.AsyncStatus(
        request_pending=staticcall AsyncVault(redemption_vault).pendingRedeemRequest(REQUEST_ID, self),
        request_claimable=staticcall AsyncVault(redemption_vault).claimableRedeemRequest(REQUEST_ID, self),
        cancel_pending=1 if staticcall AsyncVault(redemption_vault).pendingCancelRedeemRequest(REQUEST_ID, self) else 0,
        cancel_claimable=staticcall AsyncVault(redemption_vault).claimableCancelRedeemRequest(REQUEST_ID, self),
    )


@external
@nonreentrant
def claim_redeem(redemption_vault: address, claim_redeem: bool, claim_cancel: bool) -> uint256:
    """
    @notice Claim a settled async redemption and/or a settled redeem cancellation.
    @dev Mirror of claim_mint. Two independent claim legs driven by the lending contract once
         redeem_status reports the corresponding amounts as claimable:
         - claim_redeem: claims the full claimable redemption via ERC-7540
           redeem(claimableRedeemRequest, self, self). The resulting payment token lands in the
           vault, where it stays for the lending contract to handle.
         - claim_cancel: claims the ERC-7887 redeem cancellation via
           claimCancelRedeemRequest(self, self), returning the reclaimed collateral shares to the
           vault, where they stay (the redemption is reversed).
    @param claim_redeem Whether to claim the settled redemption (collateral shares -> payment).
    @param claim_cancel Whether to claim the settled redeem cancellation (reclaim collateral shares).
    @return When claim_redeem is set, the amount of payment assets received into the vault; else when
            only claim_cancel is set, the amount of collateral shares reclaimed into the vault; else 0.
    """

    assert msg.sender == self.caller, "unauthorized"

    assets: uint256 = 0
    shares: uint256 = 0

    if claim_redeem:
        claimable_shares: uint256 = staticcall AsyncVault(redemption_vault).claimableRedeemRequest(REQUEST_ID, self)
        assets = extcall AsyncVault(redemption_vault).redeem(claimable_shares, self, self)

        log RedeemClaimed(owner=self.owner, redemption_vault=redemption_vault, shares_claimed=claimable_shares, assets_received=assets)

    if claim_cancel:
        shares = extcall AsyncVault(redemption_vault).claimCancelRedeemRequest(REQUEST_ID, self, self)

        log RedeemCancelled(owner=self.owner, redemption_vault=redemption_vault, shares_reclaimed=shares)

    return assets if claim_redeem else shares


@external
@nonreentrant
def cancel_redeem(redemption_vault: address):
    """
    @notice Request cancellation of the in-flight async redeem request.
    @param redemption_vault The address of the Centrifuge ERC-7540 AsyncVault the request was made to.
    """

    assert msg.sender == self.caller, "unauthorized"

    extcall AsyncVault(redemption_vault).cancelRedeemRequest(REQUEST_ID, self)
