# @version 0.4.3

"""
@title P2PLendingErc20
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.

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


event LoanCreated:
    id: bytes32
    amount: uint256
    apr: uint256
    payment_token: address
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_token: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    soft_liquidation_ltv: uint256
    oracle_addr: address
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    soft_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32

event LoanPaid:
    id: bytes32
    borrower: address
    lender: address
    payment_token: address
    paid_principal: uint256
    paid_interest: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee_amount: uint256


event LoanReplaced:
    id: bytes32
    amount: uint256
    apr: uint256
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    soft_liquidation_ltv: uint256
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    soft_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32
    original_loan_id: bytes32
    paid_principal: uint256
    paid_interest: uint256
    paid_protocol_settlement_fee_amount: uint256

event LoanCollateralClaimed:
    id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    collateral_amount: uint256


event LoanCollateralAdded:
    id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    old_collateral_amount: uint256
    new_collateral_amount: uint256
    old_ltv: uint256
    new_ltv: uint256


event LoanCollateralRemoved:
    id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    old_collateral_amount: uint256
    new_collateral_amount: uint256
    old_ltv: uint256
    new_ltv: uint256


event LoanSoftLiquidated:
    id: bytes32
    borrower: address
    lender: address
    written_off: uint256
    collateral_claimed: uint256
    liquidation_fee: uint256
    updated_amount: uint256
    updated_collateral_amount: uint256
    updated_accrual_start_time: uint256
    liquidator: address
    old_ltv: uint256
    new_ltv: uint256

event LoanCalled:
    id: bytes32
    borrower: address
    lender: address
    call_time: uint256

event OfferRevoked:
    offer_id: bytes32
    lender: address

event OwnerProposed:
    owner: address
    proposed_owner: address

event OwnershipTransferred:
    old_owner: address
    new_owner: address

event ProtocolFeeSet:
    old_upfront_fee: uint256
    old_settlement_fee: uint256
    new_upfront_fee: uint256
    new_settlement_fee: uint256

event SoftLiquidationFeeSet:
    old_fee: uint256
    new_fee: uint256

event ProtocolWalletChanged:
    old_wallet: address
    new_wallet: address

event ProxyAuthorizationChanged:
    proxy: address
    value: bool

event TransferFailed:
    _to: address
    amount: uint256

event PendingTransfersClaimed:
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

VERSION: public(constant(String[30])) = "P2PLendingErc20.20250826"

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



# Config functions


@external
def set_soft_liquidation_fee(new_soft_liquidation_fee: uint256):

    """
    @notice Set the soft liquidation fee
    @dev Sets the soft liquidation fee to the given value and logs the event. Admin function.
    @param new_soft_liquidation_fee The new soft liquidation fee.
    """

    assert msg.sender == self.owner
    assert new_soft_liquidation_fee <= BPS, "soft liquidation fee exceeds BPS"

    log SoftLiquidationFeeSet(old_fee=self.soft_liquidation_fee, new_fee=new_soft_liquidation_fee)
    self.soft_liquidation_fee = new_soft_liquidation_fee


@external
def set_protocol_fee(protocol_upfront_fee: uint256, protocol_settlement_fee: uint256):

    """
    @notice Set the protocol fee
    @dev Sets the protocol fee to the given value and logs the event. Admin function.
    @param protocol_upfront_fee The new protocol upfront fee.
    @param protocol_settlement_fee The new protocol settlement fee.
    """

    assert msg.sender == self.owner
    assert protocol_upfront_fee <= max_protocol_upfront_fee, "upfront fee exceeds max"
    assert protocol_settlement_fee <= max_protocol_settlement_fee, "settlement fee exceeds max"

    log ProtocolFeeSet(
        old_upfront_fee=self.protocol_upfront_fee,
        old_settlement_fee=self.protocol_settlement_fee,
        new_upfront_fee=protocol_upfront_fee,
        new_settlement_fee=protocol_settlement_fee
    )
    self.protocol_upfront_fee = protocol_upfront_fee
    self.protocol_settlement_fee = protocol_settlement_fee


@external
def change_protocol_wallet(new_protocol_wallet: address):

    """
    @notice Change the protocol wallet
    @dev Changes the protocol wallet to the given address and logs the event. Admin function.
    @param new_protocol_wallet The new protocol wallet.
    """

    assert msg.sender == self.owner
    assert new_protocol_wallet != empty(address)

    log ProtocolWalletChanged(old_wallet=self.protocol_wallet, new_wallet=new_protocol_wallet)
    self.protocol_wallet = new_protocol_wallet


@external
def set_proxy_authorization(_proxy: address, _value: bool):

    """
    @notice Set authorization
    @dev Sets the authorization for the given proxy and logs the event. Admin function.
    @param _proxy The address of the proxy.
    @param _value The value of the authorization.
    """

    assert msg.sender == self.owner

    self.authorized_proxies[_proxy] = _value

    log ProxyAuthorizationChanged(proxy=_proxy, value=_value)


@external
def propose_owner(_address: address):

    """
    @notice Propose a new owner
    @dev Proposes a new owner and logs the event. Admin function.
    @param _address The address of the proposed owner.
    """

    assert msg.sender == self.owner
    assert _address != empty(address)

    log OwnerProposed(owner=self.owner, proposed_owner=_address)
    self.proposed_owner = _address


@external
def claim_ownership():

    """
    @notice Claim the ownership of the contract
    @dev Claims the ownership of the contract and logs the event. Requires the caller to be the proposed owner.
    """

    assert msg.sender == self.proposed_owner

    log OwnershipTransferred(old_owner=self.owner, new_owner=self.proposed_owner)
    self.owner = msg.sender
    self.proposed_owner = empty(address)


# Core functions

@external
def create_loan(
    offer: SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: SignedWalletValidation,
    lender_kyc: SignedWalletValidation
) -> bytes32:

    """
    @notice Create a loan.
    @param offer The signed offer.
    @param principal The principal amount of the loan.
    @param collateral_amount The amount of collateral tokens to be used for the loan.
    @param borrower_kyc The signed KYC validation for the borrower.
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the created loan.
    """


    assert self._is_offer_signed_by_lender(offer, offer.offer.lender), "offer not signed by lender"
    self._check_offer_validity(offer)

    borrower: address = msg.sender if not self.authorized_proxies[msg.sender] else tx.origin

    assert staticcall KYCValidator(kyc_validator_addr).check_validations_pair(borrower_kyc, lender_kyc), "KYC validation fail"
    assert offer.offer.borrower == empty(address) or offer.offer.borrower == borrower, "borrower not allowed"
    assert offer.offer.principal == 0 or offer.offer.principal == principal, "offer principal mismatch"
    assert offer.offer.min_collateral_amount <= collateral_amount, "low collateral amount"
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"

    convertion_rate: UInt256Rational = self._get_oracle_rate()
    initial_ltv: uint256 = self._compute_ltv(collateral_amount, principal, convertion_rate)
    if offer.offer.max_iltv > 0:
        assert initial_ltv <= offer.offer.max_iltv, "initial ltv gt max iltv"

    if offer.offer.soft_liquidation_ltv > 0:
        assert offer.offer.soft_liquidation_ltv > initial_ltv, "liquidation ltv gt initial ltv"
        # required for soft liquidation: (1 + f) * iltv < 1
        assert (BPS + self.soft_liquidation_fee) * initial_ltv < BPS * BPS, "initial ltv too high"

    offer_id: bytes32 = self._compute_signed_offer_id(offer)
    loan: Loan = Loan(
        id=empty(bytes32),
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.offer.apr,
        payment_token=offer.offer.payment_token,
        maturity=block.timestamp + offer.offer.duration,
        start_time=block.timestamp,
        accrual_start_time=block.timestamp,
        borrower=borrower,
        lender=offer.offer.lender,
        collateral_token=collateral_token,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.offer.min_collateral_amount,
        origination_fee_amount=offer.offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=self.protocol_upfront_fee * principal // BPS,
        protocol_settlement_fee=self.protocol_settlement_fee,
        soft_liquidation_fee=self.soft_liquidation_fee,
        call_eligibility=offer.offer.call_eligibility,
        call_window=offer.offer.call_window,
        soft_liquidation_ltv=offer.offer.soft_liquidation_ltv,
        oracle_addr=oracle_addr,
        initial_ltv=initial_ltv,
        call_time=0,
    )
    loan.id = self._compute_loan_id(loan)

    assert self.loans[loan.id] == empty(bytes32), "loan already exists"
    self._check_and_update_offer_state(offer, principal)
    self.loans[loan.id] = self._loan_state_hash(loan)

    self._receive_collateral(loan.borrower, loan.collateral_amount)
    self._transfer_funds(loan.lender, loan.borrower, loan.amount - loan.origination_fee_amount)

    if loan.protocol_upfront_fee_amount > 0:
        self._transfer_funds(loan.lender, self.protocol_wallet, loan.protocol_upfront_fee_amount)

    log LoanCreated(
        id=loan.id,
        amount=loan.initial_amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        soft_liquidation_ltv=loan.soft_liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv=loan.initial_ltv,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        soft_liquidation_fee=loan.soft_liquidation_fee,
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
    )
    return loan.id


@external
def settle_loan(loan: Loan):

    """
    @notice Settle a loan.
    @param loan The loan to be settled.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert not self._is_loan_defaulted(loan), "loan defaulted"
    assert self._check_user(loan.borrower), "not borrower"

    interest: uint256 = self._compute_settlement_interest(loan)
    protocol_settlement_fee: uint256 = loan.protocol_settlement_fee * interest // BPS

    self.loans[loan.id] = empty(bytes32)
    self._reduce_commited_liquidity(loan.offer_tracing_id, loan.amount)

    self._receive_funds(loan.borrower, loan.amount + interest)

    self._send_funds(loan.lender, loan.amount + interest - protocol_settlement_fee)
    if protocol_settlement_fee > 0:
        self._send_funds(self.protocol_wallet, protocol_settlement_fee)

    self._send_collateral(loan.borrower, loan.collateral_amount)

    log LoanPaid(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        payment_token=loan.payment_token,
        paid_principal=loan.amount,
        paid_interest=interest,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee_amount=protocol_settlement_fee
    )


@external
def claim_defaulted_loan_collateral(loan: Loan):

    """
    @notice Claim defaulted loan collateral.
    @param loan The loan whose collateral is to be claimed. The loan maturity must have been passed.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert self._is_loan_defaulted(loan), "loan not defaulted"
    assert self._check_user(loan.lender), "not lender"

    self.loans[loan.id] = empty(bytes32)

    self._send_collateral(loan.lender, loan.collateral_amount)

    log LoanCollateralClaimed(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount
    )


@external
def soft_liquidate_loan(loan: Loan):

    """
    @notice Settle a loan.
    @param loan The loan to be settled.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert not self._is_loan_defaulted(loan), "loan defaulted"
    liquidator: address = msg.sender if not self.authorized_proxies[msg.sender] else tx.origin

    current_interest: uint256 = self._compute_settlement_interest(loan)
    convertion_rate: UInt256Rational = self._get_oracle_rate()
    current_ltv: uint256 = self._compute_ltv(loan.collateral_amount, loan.amount + current_interest, convertion_rate)

    assert current_ltv >= loan.soft_liquidation_ltv, "ltv lt liquidation ltv"

    principal_written_off: uint256 = 0
    collateral_claimed: uint256 = 0
    liquidation_fee: uint256 = 0
    principal_written_off, collateral_claimed, liquidation_fee = self._compute_soft_liquidation(
        loan.collateral_amount,
        loan.amount + current_interest,
        loan.initial_ltv,
        loan.soft_liquidation_fee,
        convertion_rate,
    )

    assert principal_written_off < loan.amount + current_interest, "written off ge debt"

    updated_loan: Loan = Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount + current_interest - principal_written_off,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=block.timestamp,  # reset accrual start time
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount - collateral_claimed,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        soft_liquidation_fee=loan.soft_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        soft_liquidation_ltv= loan.soft_liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time,
    )

    self.loans[loan.id] = self._loan_state_hash(updated_loan)

    if liquidator == loan.lender:
        self._send_collateral(liquidator, collateral_claimed + liquidation_fee)
    else:
        self._send_collateral(liquidator, liquidation_fee)
        self._send_collateral(loan.lender, collateral_claimed)

    log LoanSoftLiquidated(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        written_off=principal_written_off,
        collateral_claimed=collateral_claimed,
        liquidation_fee=liquidation_fee,
        updated_amount=updated_loan.amount,
        updated_collateral_amount=updated_loan.collateral_amount,
        updated_accrual_start_time=updated_loan.accrual_start_time,
        liquidator=liquidator,
        old_ltv=current_ltv,
        new_ltv=self._compute_ltv(updated_loan.collateral_amount, updated_loan.amount, convertion_rate)
    )


@external
def call_loan(loan: Loan):

    """
    @notice Call a loan.
    @param loan The loan to be called.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert self._check_user(loan.lender), "not lender"

    assert loan.call_eligibility > 0, "loan not callable"
    assert loan.call_time == 0, "loan already called"
    assert block.timestamp >= loan.start_time + loan.call_eligibility, "call eligibility not reached"
    assert not self._is_loan_defaulted(loan), "loan defaulted"

    updated_loan: Loan = Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        soft_liquidation_fee=loan.soft_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        soft_liquidation_ltv= loan.soft_liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=block.timestamp,
    )
    self.loans[loan.id] = self._loan_state_hash(updated_loan)
    log LoanCalled(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        call_time=updated_loan.call_time,
    )


@external
def add_collateral_to_loan(loan: Loan, collateral_amount: uint256):

    """
    @notice Add collateral to a loan.
    @param loan The loan to which collateral is to be added.
    @param collateral_amount The amount of collateral tokens to be added.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert self._check_user(loan.borrower), "not borrower"
    assert not self._is_loan_defaulted(loan), "loan defaulted"

    convertion_rate: UInt256Rational = self._get_oracle_rate()
    outstanding_debt: uint256 = loan.amount + self._compute_settlement_interest(loan)
    old_ltv: uint256 = self._compute_ltv(loan.collateral_amount, outstanding_debt, convertion_rate)
    new_ltv: uint256 = self._compute_ltv(loan.collateral_amount + collateral_amount, outstanding_debt, convertion_rate)

    self._receive_collateral(loan.borrower, collateral_amount)

    updated_loan: Loan = Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount + collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        soft_liquidation_fee=loan.soft_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        soft_liquidation_ltv= loan.soft_liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time
    )
    self.loans[updated_loan.id] = self._loan_state_hash(updated_loan)

    log LoanCollateralAdded(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        old_collateral_amount=loan.collateral_amount,
        new_collateral_amount=updated_loan.collateral_amount,
        old_ltv=old_ltv,
        new_ltv=new_ltv
    )

@external
def remove_collateral_from_loan(loan: Loan, collateral_amount: uint256):

    """
    @notice Add collateral to a loan.
    @param loan The loan to which collateral is to be added.
    @param collateral_amount The amount of collateral tokens to be added.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert self._check_user(loan.borrower), "not borrower"
    assert not self._is_loan_defaulted(loan), "loan defaulted"

    assert loan.min_collateral_amount + collateral_amount <= loan.collateral_amount, "collateral bellow min"

    convertion_rate: UInt256Rational = self._get_oracle_rate()
    outstanding_debt: uint256 = loan.amount + self._compute_settlement_interest(loan)
    old_ltv: uint256 = self._compute_ltv(loan.collateral_amount, outstanding_debt, convertion_rate)
    new_ltv: uint256 = self._compute_ltv(loan.collateral_amount - collateral_amount, outstanding_debt, convertion_rate)

    assert loan.initial_ltv >= new_ltv, "ltv gt initial ltv"

    updated_loan: Loan = Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount - collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        soft_liquidation_fee=loan.soft_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        soft_liquidation_ltv= loan.soft_liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time
    )
    self.loans[updated_loan.id] = self._loan_state_hash(updated_loan)

    self._send_collateral(loan.borrower, collateral_amount)

    log LoanCollateralRemoved(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        old_collateral_amount=loan.collateral_amount,
        new_collateral_amount=updated_loan.collateral_amount,
        old_ltv=old_ltv,
        new_ltv=new_ltv
    )

@external
def replace_loan(
    loan: Loan,
    offer: SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    lender_kyc: SignedWalletValidation
) -> bytes32:

    """
    @notice Replace an existing loan by accepting a new offer over the same collateral. The current loan is settled and the new loan is created. Must be called by the borrower.
    @dev No collateral transfer is required. The borrower must be the same as the borrower of the current loan.
    @param loan The loan to be replaced.
    @param offer The new signed offer.
    @param principal The principal amount of the new loan, 0 means the outstanding debt
    @param collateral_amount The amount of collateral tokens to be used for the new loan.
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the new loan.
    """

    assert self._is_loan_valid(loan), "invalid loan"
    assert self._check_user(loan.borrower), "not borrower"
    assert not self._is_loan_defaulted(loan), "loan defaulted"

    assert self._is_offer_signed_by_lender(offer, offer.offer.lender), "offer not signed by lender"
    self._check_offer_validity(offer)

    assert staticcall KYCValidator(kyc_validator_addr).check_validation(lender_kyc), "KYC validation fail"
    assert offer.offer.borrower == empty(address) or offer.offer.borrower == loan.borrower, "borrower not allowed"
    assert offer.offer.min_collateral_amount <= collateral_amount, "low collateral amount"
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"

    interest: uint256 = self._compute_settlement_interest(loan)
    protocol_settlement_fee: uint256 = loan.protocol_settlement_fee * interest // BPS
    outstanding_debt: uint256 = loan.amount + interest
    new_principal: uint256 = outstanding_debt if principal == 0 else principal
    assert offer.offer.principal == 0 or offer.offer.principal == new_principal, "offer principal mismatch"

    convertion_rate: UInt256Rational = self._get_oracle_rate()
    initial_ltv: uint256 = self._compute_ltv(collateral_amount, new_principal, convertion_rate)

    if offer.offer.max_iltv > 0:
        assert initial_ltv <= offer.offer.max_iltv, "initial ltv gt max iltv"

    if offer.offer.soft_liquidation_ltv > 0:
        assert offer.offer.soft_liquidation_ltv > initial_ltv, "liquidation ltv gt initial ltv"
        # required for soft liquidation: (1 + f) * iltv < 1
        assert (BPS + self.soft_liquidation_fee) * initial_ltv < BPS * BPS, "initial ltv too high"

    offer_id: bytes32 = self._compute_signed_offer_id(offer)
    new_loan: Loan = Loan(
        id=empty(bytes32),
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        initial_amount=new_principal,
        amount=new_principal,
        apr=offer.offer.apr,
        payment_token=offer.offer.payment_token,
        maturity=block.timestamp + offer.offer.duration,
        start_time=block.timestamp,
        accrual_start_time=block.timestamp,
        borrower=loan.borrower,
        lender=offer.offer.lender,
        collateral_token=collateral_token,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.offer.min_collateral_amount,
        origination_fee_amount=offer.offer.origination_fee_bps * new_principal // BPS,
        protocol_upfront_fee_amount=self.protocol_upfront_fee * new_principal // BPS,
        protocol_settlement_fee=self.protocol_settlement_fee,
        soft_liquidation_fee=self.soft_liquidation_fee,
        call_eligibility=offer.offer.call_eligibility,
        call_window=offer.offer.call_window,
        soft_liquidation_ltv=offer.offer.soft_liquidation_ltv,
        oracle_addr=oracle_addr,
        initial_ltv=initial_ltv,
        call_time=0,
    )
    new_loan.id = self._compute_loan_id(new_loan)
    assert self.loans[new_loan.id] == empty(bytes32), "loan already exists"

    self.loans[loan.id] = empty(bytes32)
    self._reduce_commited_liquidity(loan.offer_tracing_id, loan.amount)

    self._check_and_update_offer_state(offer, new_principal)
    self.loans[new_loan.id] = self._loan_state_hash(new_loan)

    if collateral_amount > loan.collateral_amount:
        self._receive_collateral(loan.borrower, collateral_amount - loan.collateral_amount)
    elif collateral_amount < loan.collateral_amount:
        self._send_collateral(loan.borrower, loan.collateral_amount - collateral_amount)


    borrower_delta: int256 = convert(new_principal, int256) - convert(outstanding_debt + new_loan.origination_fee_amount, int256)
    old_lender_delta: uint256 = outstanding_debt - protocol_settlement_fee
    new_lender_delta: int256 = convert(new_loan.origination_fee_amount, int256) - convert(new_loan.amount + new_loan.protocol_upfront_fee_amount, int256)
    if borrower_delta < 0:
        self._receive_funds(loan.borrower, convert(-borrower_delta, uint256))

    if loan.lender == offer.offer.lender:
        lender_delta: int256 = convert(old_lender_delta, int256) + new_lender_delta
        if lender_delta < 0:
            self._receive_funds(loan.lender, convert(-lender_delta, uint256))
        elif lender_delta > 0:
            self._send_funds(loan.lender, convert(lender_delta, uint256))
    else:
        if new_lender_delta < 0:
            self._receive_funds(new_loan.lender, convert(-new_lender_delta, uint256))
        if old_lender_delta > 0:
            self._send_funds(loan.lender, old_lender_delta)
        else:
            self._send_funds(new_loan.lender, convert(new_lender_delta, uint256))

    if borrower_delta > 0:
        self._send_funds(loan.borrower, convert(borrower_delta, uint256))


    if protocol_settlement_fee + new_loan.protocol_upfront_fee_amount > 0:
        self._send_funds(self.protocol_wallet, protocol_settlement_fee + new_loan.protocol_upfront_fee_amount)

    log LoanReplaced(
        id=new_loan.id,
        amount=new_loan.initial_amount,
        apr=new_loan.apr,
        maturity=new_loan.maturity,
        start_time=new_loan.start_time,
        borrower=new_loan.borrower,
        lender=new_loan.lender,
        collateral_amount=new_loan.collateral_amount,
        min_collateral_amount=new_loan.min_collateral_amount,
        call_eligibility=new_loan.call_eligibility,
        call_window=new_loan.call_window,
        soft_liquidation_ltv=new_loan.soft_liquidation_ltv,
        initial_ltv=new_loan.initial_ltv,
        origination_fee_amount=new_loan.origination_fee_amount,
        protocol_upfront_fee_amount=new_loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=new_loan.protocol_settlement_fee,
        soft_liquidation_fee=new_loan.soft_liquidation_fee,
        offer_id=new_loan.offer_id,
        offer_tracing_id=new_loan.offer_tracing_id,
        original_loan_id=loan.id,
        paid_principal=loan.amount,
        paid_interest=interest,
        paid_protocol_settlement_fee_amount=protocol_settlement_fee
    )

    return new_loan.id


@external
def revoke_offer(offer: SignedOffer):

    """
    @notice Revoke an offer.
    @param offer The signed offer to be revoked.
    """

    assert self._check_user(offer.offer.lender), "not lender"
    assert offer.offer.expiration > block.timestamp, "offer expired"
    assert self._is_offer_signed_by_lender(offer, offer.offer.lender), "offer not signed by lender"

    offer_id: bytes32 = self._compute_signed_offer_id(offer)
    assert not self.revoked_offers[offer_id], "offer already revoked"

    self._revoke_offer(offer_id, offer)


@external
def claim_pending_transfers():
    assert self.pending_transfers[msg.sender] > 0, "no pending transfers"
    _amount: uint256 = self.pending_transfers[msg.sender]
    self.pending_transfers[msg.sender] = 0

    assert extcall IERC20(payment_token).transfer(msg.sender, _amount), "error sending funds"
    log PendingTransfersClaimed(_to=msg.sender, amount=_amount)



@view
@external
def onERC721Received(_operator: address, _from: address, _tokenId: uint256, _data: Bytes[1024]) -> bytes4:

    """
    @notice ERC721 token receiver callback.
    @dev Returns the ERC721 receiver callback selector.
    @param _operator The address which called `safeTransferFrom` function.
    @param _from The address which previously owned the token.
    @param _tokenId The NFT identifier which is being transferred.
    @param _data Additional data with no specified format.
    @return The ERC721 receiver callback selector.
    """

    return method_id("onERC721Received(address,address,uint256,bytes)", output_type=bytes4)


@view
@external
def current_ltv(loan: Loan) -> uint256:

    """
    @notice Get the current LTV of a loan.
    @param loan The loan to get the current LTV for.
    @return The current LTV of the loan.
    """

    assert self._is_loan_valid(loan), "invalid loan"

    convertion_rate: UInt256Rational = self._get_oracle_rate()
    return self._compute_ltv(loan.collateral_amount, loan.amount + self._compute_settlement_interest(loan), convertion_rate)


@view
@external
def is_loan_defaulted(loan: Loan) -> bool:

    """
    @notice Check if a loan is defaulted.
    @param loan The loan to check.
    @return True if the loan is defaulted, false otherwise.
    """

    return self._is_loan_defaulted(loan)


@view
@external
def simulate_soft_liquidation(loan: Loan) -> SoftLiquidationResult:

    assert self._is_loan_valid(loan), "invalid loan"
    assert not self._is_loan_defaulted(loan), "loan defaulted"

    current_interest: uint256 = self._compute_settlement_interest(loan)
    convertion_rate: UInt256Rational = self._get_oracle_rate()
    current_ltv: uint256 = self._compute_ltv(loan.collateral_amount, loan.amount + current_interest, convertion_rate)

    assert current_ltv >= loan.soft_liquidation_ltv, "ltv lt liquidation ltv"

    debt_written_off: uint256 = 0
    collateral_claimed: uint256 = 0
    liquidation_fee: uint256 = 0
    debt_written_off, collateral_claimed, liquidation_fee = self._compute_soft_liquidation(
        loan.collateral_amount,
        loan.amount + current_interest,
        loan.initial_ltv,
        loan.soft_liquidation_fee,
        convertion_rate,
    )

    assert debt_written_off < loan.amount + current_interest, "written off ge debt"

    return SoftLiquidationResult(
        collateral_claimed=collateral_claimed,
        liquidation_fee=liquidation_fee,
        debt_written_off=debt_written_off,
        updated_ltv=self._compute_ltv(loan.collateral_amount - collateral_claimed, loan.amount + current_interest - debt_written_off, convertion_rate)
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
def _is_offer_signed_by_lender(signed_offer: SignedOffer, lender: address) -> bool:
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
    ) == lender


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
