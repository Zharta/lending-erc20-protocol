# @version 0.4.3

"""
@title MidasVaultMock
@notice Consolidated mock of the Midas DepositVault + RedemptionVault for P2PLendingVaultMidas
        unit tests (replaces MidasRedemptionVaultMock).
@dev Implements only the surface P2PLendingVaultMidas calls: `depositInstant` on the mint side and
     `redeemInstant` + the fee getters (`instantFee` / `tokensConfig` / `waivedFeeRestriction`) on
     the redeem side.

     Midas normalizes external amounts to base18 across its boundary: `amountToken` /
     `amountMTokenIn` / `minReceiveAmount` all arrive in base18.

     Mint side — `depositInstant`:
       (a) pulls tokenIn (converting the base18 amount back to native decimals), capped by
           `max_deposit_spend` when set — the P2P vault measures the spend via balance delta, so a
           cap below the requested amount yields a refund (the D13/D23 partial-spend scenario),
       (b) normalizes the configured `deposit_deliver_amount` (mtoken native decimals) to base18 and
           enforces the slippage floor against `minReceiveAmount`,
       (c) pays out `deposit_deliver_amount` of mtoken to `tokensReceiver` from the mock's own
           balance (tests pre-fund the mock, mirroring the AsyncVaultMock convention).

     Redeem side — `redeemInstant`: verbatim behavior of the former MidasRedemptionVaultMock:
       (a) pulls the mtokens (base18 -> native), (b) enforces the slippage floor on the
       base18-normalized `deliver_amount` (the F1 guard), (c) pays out `deliver_amount` of
       token_out.

     All knobs are test-configurable so a test can simulate exact, full, or under-delivery and
     partial spends independently of any rate math.
"""

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

struct MidasTokenConfig:
    dataFeed: address
    fee: uint256
    allowance: uint256
    stable: bool

BPS: constant(uint256) = 10000

mtoken: public(address)            # the mToken this vault mints/burns (== the P2P vault's token)
instant_fee: public(uint256)       # instant-redeem fee, bps
token_fee: public(uint256)         # per-token_out fee, bps
waived: public(bool)               # whether the caller's fee is waived

# ------------------------------- mint (deposit) side -------------------------------
deposit_deliver_amount: public(uint256)   # mtoken (native decimals) paid out on the next depositInstant
max_deposit_spend: public(uint256)        # tokenIn (native decimals) cap on the pull; 0 = pull the full amount
last_deposit_min_receive: public(uint256) # base18 minReceiveAmount seen on the last depositInstant
last_token_in_pulled: public(uint256)     # tokenIn (native decimals) pulled on the last depositInstant

# ------------------------------- redeem side -------------------------------
deliver_amount: public(uint256)    # token_out (native decimals) paid out on the next redeemInstant
last_min_receive: public(uint256)  # base18 minReceiveAmount seen on the last redeemInstant
last_mtoken_pulled: public(uint256)


@deploy
def __init__(_mtoken: address, _instant_fee: uint256):
    self.mtoken = _mtoken
    self.instant_fee = _instant_fee


# --------------------------- test configuration ---------------------------

@external
def set_deposit_deliver_amount(amount: uint256):
    self.deposit_deliver_amount = amount


@external
def set_max_deposit_spend(amount: uint256):
    self.max_deposit_spend = amount


@external
def set_deliver_amount(amount: uint256):
    self.deliver_amount = amount


@external
def set_token_fee(fee: uint256):
    self.token_fee = fee


@external
def set_waived(w: bool):
    self.waived = w


# ------------------------------ depositInstant ------------------------------

@external
def depositInstant(tokenIn: address, amountToken: uint256, minReceiveAmount: uint256, referrerId: bytes32, tokensReceiver: address):
    self.last_deposit_min_receive = minReceiveAmount

    # (a) pull tokenIn (base18 -> native decimals), capped by max_deposit_spend when set
    token_in_decimals: uint256 = convert(staticcall IERC20Detailed(tokenIn).decimals(), uint256)
    requested_native: uint256 = amountToken * (10 ** token_in_decimals) // (10 ** 18)
    pull_native: uint256 = requested_native
    if self.max_deposit_spend > 0 and self.max_deposit_spend < requested_native:
        pull_native = self.max_deposit_spend
    self.last_token_in_pulled = pull_native
    if pull_native > 0:
        assert extcall IERC20(tokenIn).transferFrom(msg.sender, self, pull_native), "tokenIn pull failed"

    # (b) enforce the slippage floor on the base18-normalized delivered mtoken amount
    mtoken_decimals: uint256 = convert(staticcall IERC20Detailed(self.mtoken).decimals(), uint256)
    delivered_base18: uint256 = self.deposit_deliver_amount * (10 ** 18) // (10 ** mtoken_decimals)
    assert delivered_base18 >= minReceiveAmount, "insufficient output amount"

    # (c) pay out the mtokens from the mock's own balance
    if self.deposit_deliver_amount > 0:
        assert extcall IERC20(self.mtoken).transfer(tokensReceiver, self.deposit_deliver_amount), "mtoken payout failed"


# ------------------------- fee getters (read by vault) -------------------------

@external
@view
def instantFee() -> uint256:
    return self.instant_fee


@external
@view
def waivedFeeRestriction(user: address) -> bool:
    return self.waived


@external
@view
def tokensConfig(token: address) -> MidasTokenConfig:
    return MidasTokenConfig(dataFeed=empty(address), fee=self.token_fee, allowance=0, stable=False)


# ------------------------------ redeemInstant ------------------------------

@external
def redeemInstant(tokenOut: address, amountMTokenIn: uint256, minReceiveAmount: uint256):
    self.last_min_receive = minReceiveAmount

    # (a) pull the mtokens (base18 -> native mtoken decimals, matching what the vault approved)
    mtoken_decimals: uint256 = convert(staticcall IERC20Detailed(self.mtoken).decimals(), uint256)
    mtoken_native: uint256 = amountMTokenIn * (10 ** mtoken_decimals) // (10 ** 18)
    self.last_mtoken_pulled = mtoken_native
    assert extcall IERC20(self.mtoken).transferFrom(msg.sender, self, mtoken_native), "mtoken pull failed"

    # (b) enforce the slippage floor on the base18-normalized delivered value
    token_out_decimals: uint256 = convert(staticcall IERC20Detailed(tokenOut).decimals(), uint256)
    delivered_base18: uint256 = self.deliver_amount * (10 ** 18) // (10 ** token_out_decimals)
    assert delivered_base18 >= minReceiveAmount, "insufficient output amount"

    # (c) pay out the token_out
    if self.deliver_amount > 0:
        assert extcall IERC20(tokenOut).transfer(msg.sender, self.deliver_amount), "token_out payout failed"
