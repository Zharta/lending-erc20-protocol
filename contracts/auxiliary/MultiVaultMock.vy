# @version 0.4.3

"""
@title MultiVaultMock
@notice Mock vault for MultiVault unit tests implementing the 4-arg buy/redeem interface.
@dev Mirrors the Vault interface expected by P2PLendingMultiVaultBase but uses
     simple token transfer logic instead of Midas external contracts.
"""

from ethereum.ercs import IERC20

interface P2PLendingContract:
    def authorized_proxies(proxy: address) -> bool: view

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
    assert self.caller == empty(address), "already initialised"
    self.caller = msg.sender
    self.owner = _owner
    self.token = _token


@external
def deposit(amount: uint256, wallet: address):
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
    return staticcall IERC20(self.token).balanceOf(self) - self.pending_transfers_total


@external
def withdraw_pending(amount: uint256):
    assert self.pending_transfers[msg.sender] >= amount, "insufficient pending collateral"
    self.pending_transfers[msg.sender] -= amount
    self.pending_transfers_total -= amount
    assert extcall IERC20(self.token).transfer(msg.sender, amount), "transfer failed"
    log WithdrawPending(wallet=msg.sender, amount=amount)


@external
def withdraw_funds(payment_token: address, amount: uint256):
    assert self._check_user(self.caller), "unauthorized"
    assert extcall IERC20(payment_token).transfer(self.caller, amount), "transfer failed"


@external
def transfer_funds(payment_token: address, amount: uint256, wallet: address):
    assert self._check_user(self.caller), "unauthorized"
    if amount > 0:
        assert extcall IERC20(payment_token).transfer(wallet, amount), "transfer failed"


@external
@nonreentrant
def buy(payment_token: address, deposit_vault: address, min_mtoken_amount: uint256, stable_coin_amount: uint256):
    """
    @notice Mock buy - simply transfers stablecoins from caller and credits pending.
    @dev In the mock, we skip actual Midas interaction. Just move tokens in/out.
    """
    assert self._check_user(self.owner), "unauthorized"

    assert extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_coin_amount), "transferFrom failed"

    # Mock: credit the stable_coin_amount as pending collateral tokens to owner
    self.pending_transfers[self.owner] += stable_coin_amount
    self.pending_transfers_total += stable_coin_amount


@external
@nonreentrant
def redeem(redemption_vault: address, token_out: address, amount_mtoken: uint256, oracle_rate_num: uint256, oracle_rate_den: uint256) -> uint256:
    """
    @notice Mock redeem - transfers collateral tokens to the redemption_vault and credits
            an equivalent amount of payment tokens.
    @dev In the mock, we just transfer the collateral token to the redemption vault address.
         The lending contract handles the rest.
    """
    assert self._check_user(self.caller), "unauthorized"

    # Transfer collateral to redemption vault
    if amount_mtoken > 0:
        assert extcall IERC20(self.token).transfer(redemption_vault, amount_mtoken), "transfer failed"

    return amount_mtoken


@internal
def _check_user(user: address) -> bool:
    return msg.sender == user or (staticcall P2PLendingContract(self.caller).authorized_proxies(msg.sender) and user == tx.origin)
