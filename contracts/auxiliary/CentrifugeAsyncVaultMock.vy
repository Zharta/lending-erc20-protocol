# @version 0.4.3

"""
@title CentrifugeAsyncVaultMock
@notice Mock Centrifuge ERC-7540 / ERC-7887 AsyncVault for MultiVault P2PLendingVaultCentrifugeAsync unit tests.
@dev Models the async deposit (mint) and redeem lifecycles the P2PLendingVaultCentrifugeAsync vault drives,
     with test-only hooks (`fulfill_*` / `process_cancel_*`) that stand in for the off-chain issuer
     settling requests. State is keyed per `controller` (each loan uses its own P2P loan vault, which is
     always its own controller/owner). `requestId` is accepted for ABI conformance but ignored
     (Centrifuge uses a single request per controller, id 0).

     Token model: `asset` is the deposited stablecoin (payment token), `share` is the minted vault
     share (collateral token the P2P loan vault holds).
       - deposit:  requestDeposit pulls `asset` from owner; on claim `deposit()` pays out `share`.
       - redeem:   requestRedeem pulls `share` from owner; on claim `redeem()` pays out `asset`.
     The mock pays out `share` (deposit claim) and `asset` (redeem claim) from its OWN balance, so a
     test must pre-fund it with enough of each. Cancel claims return exactly what was pulled in.

     Cancel model (so the lending contract's two-phase cancel state machine's three branches are all reachable):
       - cancel*Request moves the still-pending amount OUT of `pending` into an internal cancel
         pipeline and sets `cancel_pending = True` (state: pending==0, cancel_pending==True).
       - process_cancel_* (test hook) moves the pipeline amount into `cancel_claimable` and clears
         `cancel_pending` (state: cancel_claimable>0, cancel_pending==False).
       - claimCancel*Request pays the reclaimed amount back and clears `cancel_claimable`.
     Fulfilment and cancellation are NOT mutually exclusive: `fulfill_*` supports PARTIAL settlement
     (it only requires `pending >= amount` and decrements it), so an issuer can fulfil a slice of a
     request and leave the remainder pending. Cancelling that remainder (cancel*Request +
     process_cancel_*) then yields the MIXED terminal state `claimable > 0 AND cancel_claimable > 0`
     with both pendings zero — a single request that was partly fulfilled and partly cancelled.
     This holds symmetrically for both the deposit (fulfill_deposit) and redeem (fulfill_redeem) legs.
"""

from ethereum.ercs import IERC20

REQUEST_ID: constant(uint256) = 0

asset: public(address)   # deposited stablecoin (payment token)
share: public(address)   # minted vault share (collateral token)

# --- deposit (mint) side, keyed by controller ---
deposit_pending: public(HashMap[address, uint256])          # requested assets, not yet fulfilled/cancelled
deposit_claimable: public(HashMap[address, uint256])        # fulfilled assets, ready to claim -> shares
deposit_shares: public(HashMap[address, uint256])           # shares minted when the claimable deposit is claimed
deposit_cancel_pending: public(HashMap[address, bool])      # cancellation requested, not yet processed
deposit_cancel_amount: public(HashMap[address, uint256])    # assets in the cancel pipeline (internal)
deposit_cancel_claimable: public(HashMap[address, uint256]) # assets reclaimable after cancel processed

# --- redeem side, keyed by controller ---
redeem_pending: public(HashMap[address, uint256])           # requested shares, not yet fulfilled/cancelled
redeem_claimable: public(HashMap[address, uint256])         # fulfilled shares, ready to claim -> assets
redeem_assets: public(HashMap[address, uint256])            # assets paid out when the claimable redeem is claimed
redeem_cancel_pending: public(HashMap[address, bool])       # cancellation requested, not yet processed
redeem_cancel_amount: public(HashMap[address, uint256])     # shares in the cancel pipeline (internal)
redeem_cancel_claimable: public(HashMap[address, uint256])  # shares reclaimable after cancel processed


@deploy
def __init__(_asset: address, _share: address):
    self.asset = _asset
    self.share = _share


# ============================ ERC-7540 deposit ============================

@external
def requestDeposit(assets: uint256, controller: address, owner: address) -> uint256:
    assert extcall IERC20(self.asset).transferFrom(owner, self, assets), "asset pull failed"
    self.deposit_pending[controller] += assets
    return REQUEST_ID


@external
@view
def pendingDepositRequest(requestId: uint256, controller: address) -> uint256:
    return self.deposit_pending[controller]


@external
@view
def claimableDepositRequest(requestId: uint256, controller: address) -> uint256:
    return self.deposit_claimable[controller]


@external
def deposit(assets: uint256, receiver: address, controller: address) -> uint256:
    # Claim a fulfilled deposit: consume `assets` of the claimable and pay out the fulfilled shares.
    assert self.deposit_claimable[controller] >= assets, "not claimable"
    shares: uint256 = self.deposit_shares[controller]
    self.deposit_claimable[controller] -= assets
    self.deposit_shares[controller] = 0
    if shares > 0:
        assert extcall IERC20(self.share).transfer(receiver, shares), "share payout failed"
    return shares


# ========================= ERC-7887 deposit cancel =========================

@external
def cancelDepositRequest(requestId: uint256, controller: address):
    # Can only cancel a still-pending (unfulfilled) deposit. Moves it into the cancel pipeline.
    assert self.deposit_pending[controller] > 0, "nothing to cancel"
    self.deposit_cancel_amount[controller] += self.deposit_pending[controller]
    self.deposit_pending[controller] = 0
    self.deposit_cancel_pending[controller] = True


@external
@view
def pendingCancelDepositRequest(requestId: uint256, controller: address) -> bool:
    return self.deposit_cancel_pending[controller]


@external
@view
def claimableCancelDepositRequest(requestId: uint256, controller: address) -> uint256:
    return self.deposit_cancel_claimable[controller]


@external
def claimCancelDepositRequest(requestId: uint256, receiver: address, controller: address) -> uint256:
    amount: uint256 = self.deposit_cancel_claimable[controller]
    self.deposit_cancel_claimable[controller] = 0
    if amount > 0:
        assert extcall IERC20(self.asset).transfer(receiver, amount), "asset refund failed"
    return amount


# ============================= ERC-7540 redeem =============================

@external
def requestRedeem(shares: uint256, controller: address, owner: address) -> uint256:
    assert extcall IERC20(self.share).transferFrom(owner, self, shares), "share pull failed"
    self.redeem_pending[controller] += shares
    return REQUEST_ID


@external
@view
def pendingRedeemRequest(requestId: uint256, controller: address) -> uint256:
    return self.redeem_pending[controller]


@external
@view
def claimableRedeemRequest(requestId: uint256, controller: address) -> uint256:
    return self.redeem_claimable[controller]


@external
def redeem(shares: uint256, receiver: address, controller: address) -> uint256:
    # Claim a fulfilled redemption: consume `shares` of the claimable and pay out the fulfilled assets.
    assert self.redeem_claimable[controller] >= shares, "not claimable"
    assets: uint256 = self.redeem_assets[controller]
    self.redeem_claimable[controller] -= shares
    self.redeem_assets[controller] = 0
    if assets > 0:
        assert extcall IERC20(self.asset).transfer(receiver, assets), "asset payout failed"
    return assets


# ========================= ERC-7887 redeem cancel =========================

@external
def cancelRedeemRequest(requestId: uint256, controller: address):
    assert self.redeem_pending[controller] > 0, "nothing to cancel"
    self.redeem_cancel_amount[controller] += self.redeem_pending[controller]
    self.redeem_pending[controller] = 0
    self.redeem_cancel_pending[controller] = True


@external
@view
def pendingCancelRedeemRequest(requestId: uint256, controller: address) -> bool:
    return self.redeem_cancel_pending[controller]


@external
@view
def claimableCancelRedeemRequest(requestId: uint256, controller: address) -> uint256:
    return self.redeem_cancel_claimable[controller]


@external
def claimCancelRedeemRequest(requestId: uint256, receiver: address, controller: address) -> uint256:
    amount: uint256 = self.redeem_cancel_claimable[controller]
    self.redeem_cancel_claimable[controller] = 0
    if amount > 0:
        assert extcall IERC20(self.share).transfer(receiver, amount), "share refund failed"
    return amount


# =============================== test hooks ===============================

@external
def fulfill_deposit(controller: address, assets: uint256, shares: uint256):
    # Issuer settles `assets` of the pending deposit at a price yielding `shares`.
    assert self.deposit_pending[controller] >= assets, "over-fulfill"
    self.deposit_pending[controller] -= assets
    self.deposit_claimable[controller] += assets
    self.deposit_shares[controller] += shares


@external
def process_cancel_deposit(controller: address):
    # Issuer processes a requested deposit cancellation, making the reclaimed assets claimable.
    assert self.deposit_cancel_pending[controller], "no cancel pending"
    self.deposit_cancel_claimable[controller] += self.deposit_cancel_amount[controller]
    self.deposit_cancel_amount[controller] = 0
    self.deposit_cancel_pending[controller] = False


@external
def fulfill_redeem(controller: address, shares: uint256, assets: uint256):
    # Issuer settles `shares` of the pending redeem at a price yielding `assets`.
    assert self.redeem_pending[controller] >= shares, "over-fulfill"
    self.redeem_pending[controller] -= shares
    self.redeem_claimable[controller] += shares
    self.redeem_assets[controller] += assets


@external
def process_cancel_redeem(controller: address):
    # Issuer processes a requested redeem cancellation, making the reclaimed shares claimable.
    assert self.redeem_cancel_pending[controller], "no cancel pending"
    self.redeem_cancel_claimable[controller] += self.redeem_cancel_amount[controller]
    self.redeem_cancel_amount[controller] = 0
    self.redeem_cancel_pending[controller] = False
