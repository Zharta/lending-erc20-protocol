# @version 0.4.3

"""
@title P2PLendingBase
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.
@dev Keep all state here so that the storage layout is consistent across contracts

"""

# Interfaces

from ethereum.ercs import IERC721
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

struct AggregatorV3LatestRoundData:
    roundId: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80

interface AggregatorV3Interface:
    def decimals() -> uint8: view
    def latestRoundData() -> AggregatorV3LatestRoundData: view

interface KYCValidator:
    def check_validation(validation: SignedWalletValidation) -> bool: view
    def check_validations_pair(validation1: SignedWalletValidation, validation2: SignedWalletValidation) -> bool: view

# Structs

BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

struct WalletValidation:
    wallet: address
    expiration_time: uint256

struct SignedWalletValidation:
    validation: WalletValidation
    signature: Signature

struct Offer:
    principal: uint256 # optional
    apr: uint256
    payment_token: address
    collateral_token: address
    duration: uint256
    origination_fee_bps: uint256

    min_collateral_amount: uint256 # optional
    max_iltv: uint256 # max initial LTV, optional and needs to be set if min_collateral_amount isn't specified
    available_liquidity: uint256 # amount of the principal token allocated to the offer
    call_eligibility: uint256 # when the loan starts to be callable, 0 if not callable
    call_window: uint256 # time after the loan is called where the borrower can repay the loan or the loan defaults entirely
    soft_liquidation_ltv: uint256 # optional, used if > 0
    oracle_addr: address # optional, must match the oracle used for collateral valuation if defined

    expiration: uint256
    lender: address
    borrower: address
    tracing_id: bytes32


struct Signature:
    v: uint256
    r: uint256
    s: uint256

struct SignedOffer:
    offer: Offer
    signature: Signature

struct Loan:
    id: bytes32
    offer_id: bytes32
    offer_tracing_id: bytes32
    initial_amount: uint256
    amount: uint256
    apr: uint256
    payment_token: address
    maturity: uint256
    start_time: uint256
    accrual_start_time: uint256 # either start_time or last soft liquidation time
    borrower: address
    lender: address
    collateral_token: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    soft_liquidation_fee: uint256
    call_eligibility: uint256 # amount of seconds after the start of the loan when the loan starts to be callable, 0 if not callable
    call_window: uint256 # amount of seconds after the loan is called where the borrower can repay the loan or the loan defaults entirely, optional and needs to be set if loan is callable
    soft_liquidation_ltv: uint256 # needs to be higher than the initial ltv, optional and used if > 0
    oracle_addr: address # optional, needs to be set if soft_liquidaiton is defined
    initial_ltv: uint256 # initial ltv, needs to be set if soft_liquidation is defined
    call_time: uint256 # the time when the loan was called, 0 if not called

struct UInt256Rational:
    numerator: uint256
    denominator: uint256


struct SoftLiquidationResult:
    collateral_claimed: uint256
    liquidation_fee: uint256
    debt_written_off: uint256
    updated_ltv: uint256


event OfferRevoked:
    offer_id: bytes32
    lender: address

event TransferFailed:
    _to: address
    amount: uint256

# Global variables


owner: public(address)
proposed_owner: public(address)

payment_token: public(immutable(address))
collateral_token: public(immutable(address))
oracle_addr: public(immutable(address))
oracle_reverse: public(immutable(bool))
kyc_validator_addr: public(immutable(address))

loans: public(HashMap[bytes32, bytes32])

protocol_wallet: public(address)
protocol_upfront_fee: public(uint256)
soft_liquidation_fee: public(uint256)
protocol_settlement_fee: public(uint256)
max_protocol_upfront_fee: public(immutable(uint256))
max_protocol_settlement_fee: public(immutable(uint256))

payment_token_decimals: public(immutable(uint256))
collateral_token_decimals: public(immutable(uint256))


commited_liquidity: public(HashMap[bytes32, uint256])
revoked_offers: public(HashMap[bytes32, bool])

authorized_proxies: public(HashMap[address, bool])
pending_transfers: public(HashMap[address, uint256])

ZHARTA_DOMAIN_NAME: constant(String[6]) = "Zharta"
ZHARTA_DOMAIN_VERSION: constant(String[1]) = "1"

DOMAIN_TYPE_HASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
OFFER_TYPE_DEF: constant(String[370]) = "Offer(uint256 principal,uint256 apr,address payment_token,address collateral_token,uint256 duration," \
                                        "uint256 origination_fee_bps,uint256 min_collateral_amount,uint256 max_iltv,uint256 available_liquidity," \
                                        "uint256 call_eligibility,uint256 call_window,uint256 soft_liquidation_ltv,address oracle_addr," \
                                        "uint256 expiration,address lender,address borrower,bytes32 tracing_id)"
OFFER_TYPE_HASH: constant(bytes32) = keccak256(OFFER_TYPE_DEF)

offer_sig_domain_separator: immutable(bytes32)


@deploy
def __init__(
    _payment_token: address,
    _collateral_token: address,
    _oracle_addr: address,
    _oracle_reverse: bool,
    _kyc_validator_addr: address,
    _protocol_upfront_fee: uint256,
    _protocol_settlement_fee: uint256,
    _protocol_wallet: address,
    _max_protocol_upfront_fee: uint256,
    _max_protocol_settlement_fee: uint256,
    _soft_liquidation_fee: uint256,
):

    """
    @notice Initialize the contract with the given parameters.
    @param _payment_token The address of the payment token.
    @param _collateral_token The address of the collateral token.
    @param _oracle_addr The address of the oracle contract for collateral valuation.
    @param _oracle_reverse Whether the oracle returns the collateral price in reverse (i.e., 1 / price).
    @param _protocol_upfront_fee The percentage (bps) of the principal paid to the protocol at origination.
    @param _protocol_settlement_fee The percentage (bps) of the interest paid to the protocol at settlement.
    @param _protocol_wallet The address where the protocol fees are accrued.
    @param _max_protocol_upfront_fee The maximum percentage (bps) of the principal that can be charged as protocol upfront fee.
    @param _max_protocol_settlement_fee The maximum percentage (bps) of the interest that can be charged as protocol settlement fee.
    @param _soft_liquidation_fee The percentage (bps) of the principal that is charged as a liquidation fee when a loan is soft liquidated.
    """

    assert _protocol_wallet != empty(address)
    assert _payment_token != empty(address)
    assert _collateral_token != empty(address)
    assert _oracle_addr != empty(address)

    assert _max_protocol_settlement_fee <= BPS
    assert _protocol_upfront_fee <= _max_protocol_upfront_fee
    assert _protocol_settlement_fee <= _max_protocol_settlement_fee

    self.owner = msg.sender
    payment_token = _payment_token
    collateral_token = _collateral_token
    oracle_addr = _oracle_addr
    oracle_reverse = _oracle_reverse
    kyc_validator_addr = _kyc_validator_addr
    max_protocol_upfront_fee = _max_protocol_upfront_fee
    max_protocol_settlement_fee = _max_protocol_settlement_fee
    self.protocol_upfront_fee = _protocol_upfront_fee
    self.protocol_settlement_fee = _protocol_settlement_fee
    self.protocol_wallet = _protocol_wallet
    self.soft_liquidation_fee = _soft_liquidation_fee

    collateral_token_decimals = 10 ** convert(staticcall IERC20Detailed(_collateral_token).decimals(), uint256)
    payment_token_decimals = 10 ** convert(staticcall IERC20Detailed(_payment_token).decimals(), uint256)
    offer_sig_domain_separator = keccak256(
        abi_encode(
            DOMAIN_TYPE_HASH,
            keccak256(ZHARTA_DOMAIN_NAME),
            keccak256(ZHARTA_DOMAIN_VERSION),
            chain.id,
            self
        )
    )




# Internal functions

@pure
@internal
def _compute_loan_id(loan: Loan) -> bytes32:
    return keccak256(concat(
        convert(loan.borrower, bytes32),
        convert(loan.lender, bytes32),
        convert(loan.start_time, bytes32),
        loan.offer_id,
    ))

@pure
@internal
def _compute_signed_offer_id(offer: SignedOffer) -> bytes32:
    return keccak256(concat(
        convert(offer.signature.v, bytes32),
        convert(offer.signature.r, bytes32),
        convert(offer.signature.s, bytes32),
    ))

@internal
def _check_and_update_offer_state(offer: SignedOffer, amount: uint256):
    offer_id: bytes32 = self._compute_signed_offer_id(offer)
    assert not self.revoked_offers[offer_id], "offer revoked"

    commited_liquidity: uint256 = self.commited_liquidity[offer.offer.tracing_id]
    assert commited_liquidity + amount <= offer.offer.available_liquidity, "offer fully utilized"
    self.commited_liquidity[offer.offer.tracing_id] = commited_liquidity + amount

    if offer.offer.borrower != empty(address):
        # offer has borrower => normal offer
        self._revoke_offer(offer_id, offer)


@internal
def _revoke_offer(offer_id: bytes32, offer: SignedOffer):

    self.revoked_offers[offer_id] = True

    log OfferRevoked(offer_id=offer_id, lender=offer.offer.lender)


@internal
def _reduce_commited_liquidity(tracing_id: bytes32, amount: uint256):
    commited_liquidity: uint256 = self.commited_liquidity[tracing_id]
    self.commited_liquidity[tracing_id] = 0 if amount > commited_liquidity else commited_liquidity - amount

@view
@internal
def _is_loan_valid(loan: Loan) -> bool:
    return self.loans[loan.id] == self._loan_state_hash(loan)

@pure
@internal
def _loan_state_hash(loan: Loan) -> bytes32:
    return keccak256(abi_encode(loan))


@internal
def _is_offer_signed_by_lender(signed_offer: SignedOffer) -> bool:
    return ecrecover(
        keccak256(
            concat(
                convert("\x19\x01", Bytes[2]),
                abi_encode(
                    offer_sig_domain_separator,
                    keccak256(abi_encode(OFFER_TYPE_HASH, signed_offer.offer))
                )
            )
        ),
        signed_offer.signature.v,
        signed_offer.signature.r,
        signed_offer.signature.s
    ) == signed_offer.offer.lender


@view
@internal
def _compute_settlement_interest(loan: Loan) -> uint256:
    return loan.amount * loan.apr * (block.timestamp - loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)


@internal
def _send_funds(_to: address, _amount: uint256):
    success: bool = False
    response: Bytes[32] = b""

    success, response = raw_call(
        payment_token,
        abi_encode(_to, _amount, method_id=method_id("transfer(address,uint256)")),
        max_outsize=32,
        revert_on_failure=False
    )

    if not success or not convert(response, bool):
        log TransferFailed(_to=_to, amount=_amount)
        self.pending_transfers[_to] += _amount


@internal
def _receive_funds(_from: address, _amount: uint256):
    assert extcall IERC20(payment_token).transferFrom(_from, self, _amount), "transferFrom failed"


@internal
def _transfer_funds(_from: address, _to: address, _amount: uint256):
    assert extcall IERC20(payment_token).transferFrom(_from, _to, _amount), "transferFrom failed"


@internal
def _send_collateral(wallet: address, _amount: uint256):
    assert extcall IERC20(collateral_token).transfer(wallet, _amount), "transfer failed"


@internal
def _receive_collateral(_from: address, _amount: uint256):
    assert extcall IERC20(collateral_token).transferFrom(_from, self, _amount), "transferFrom failed"


@internal
def _check_user(user: address) -> bool:
    return msg.sender == user or (self.authorized_proxies[msg.sender] and user == tx.origin)

@internal
def _check_offer_validity(offer: SignedOffer):
    assert offer.offer.expiration > block.timestamp, "offer expired"
    assert offer.offer.duration > 0, "duration is 0"
    assert offer.offer.payment_token == payment_token, "invalid payment token"
    assert offer.offer.collateral_token == collateral_token, "invalid collateral token"
    assert offer.offer.oracle_addr == empty(address) or offer.offer.oracle_addr == oracle_addr, "invalid oracle address"
    assert offer.offer.call_window != 0 or offer.offer.call_eligibility == 0, "call window is 0"
    assert offer.offer.min_collateral_amount > 0 or offer.offer.max_iltv > 0, "no min collateral nor max iltv"



@view
@internal
def _get_oracle_rate() -> UInt256Rational:
    convertion_rate_numerator: uint256 = 0
    convertion_rate_denominator: uint256 = 0
    if oracle_reverse:
        return UInt256Rational(
            numerator=10 ** convert(staticcall AggregatorV3Interface(oracle_addr).decimals(), uint256),
            denominator=convert((staticcall AggregatorV3Interface(oracle_addr).latestRoundData()).answer, uint256)
        )
    else:
        return UInt256Rational(
            numerator=convert((staticcall AggregatorV3Interface(oracle_addr).latestRoundData()).answer, uint256),
            denominator=10 ** convert(staticcall AggregatorV3Interface(oracle_addr).decimals(), uint256)
        )


@view
@internal
def _compute_ltv(collateral_amount: uint256, amount: uint256, convertion_rate: UInt256Rational) -> uint256:
    return amount * BPS * convertion_rate.denominator * collateral_token_decimals // (collateral_amount * convertion_rate.numerator * payment_token_decimals)


@view
@internal
def _compute_soft_liquidation(
    collateral_amount: uint256,
    outstanding_debt: uint256,
    initial_ltv: uint256,
    soft_liquidation_fee: uint256,
    convertion_rate: UInt256Rational,
) -> (uint256, uint256, uint256):
    """
    returns:
        principal_written_off: uint256 - the amount of principal written off
        collateral_claimed: uint256 - the amount of collateral claimed
        liquidation_fee: uint256 - the liquidation fee
    """
    collateral_value: uint256 = collateral_amount * convertion_rate.numerator * payment_token_decimals // (convertion_rate.denominator * collateral_token_decimals)
    principal_written_off: uint256 = (outstanding_debt * BPS - collateral_value * initial_ltv)  * BPS // (BPS * BPS - (BPS + soft_liquidation_fee) * initial_ltv)
    collateral_claimed: uint256 = principal_written_off * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)
    liquidation_fee: uint256 = collateral_claimed * soft_liquidation_fee // BPS

    return principal_written_off, collateral_claimed, liquidation_fee


@view
@internal
def _is_loan_defaulted(loan: Loan) -> bool:
    if block.timestamp > loan.maturity:
        return True
    if loan.call_time > 0:
        return block.timestamp > loan.call_time + loan.call_window
    return False
