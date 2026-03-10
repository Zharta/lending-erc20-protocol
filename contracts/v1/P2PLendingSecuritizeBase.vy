# @version 0.4.3

"""
@title P2PLendingVaultedBase
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.
@dev Keep all state here so that the storage layout is consistent across contracts

"""

# Interfaces

from ethereum.ercs import IERC721
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingVaultSecuritize as vault

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

interface EIP1271Signer:
    def is_valid_signature(hash: bytes32, signature: Bytes[65]) -> bytes4: view


# Structs

BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

MALLEABILITY_THRESHOLD: constant(uint256) = 57896044618658097711785492504343953926418782139537452191302581570759080747168
EIP1271_MAGIC_VALUE: constant(bytes4) = 0x1626ba7e


_COLLISION_OFFSET: constant(bytes1) = 0xFF
_DEPLOYMENT_CODE: constant(bytes9) = 0x602D3D8160093D39F3
_PRE: constant(bytes10) = 0x363d3d373d3d3d363d73
_POST: constant(bytes15) = 0x5af43d82803e903d91602b57fd5bf3

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
    liquidation_ltv: uint256 # optional, used if > 0
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


struct LoanExtensionOffer:
    loan_id: bytes32
    original_maturity: uint256
    new_maturity: uint256


struct SignedLoanExtensionOffer:
    offer: LoanExtensionOffer
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
    partial_liquidation_fee: uint256
    full_liquidation_fee: uint256
    call_eligibility: uint256 # amount of seconds after the start of the loan when the loan starts to be callable, 0 if not callable
    call_window: uint256 # amount of seconds after the loan is called where the borrower can repay the loan or the loan defaults entirely, optional and needs to be set if loan is callable
    liquidation_ltv: uint256 # needs to be higher than the initial ltv, optional and used if > 0
    oracle_addr: address # optional, needs to be set if soft_liquidaiton is defined
    initial_ltv: uint256 # initial ltv, needs to be set if soft_liquidation is defined
    call_time: uint256 # the time when the loan was called, 0 if not called
    vault_id: uint256
    redeem_start: uint256
    redeem_residual_collateral: uint256


struct UInt256Rational:
    numerator: uint256
    denominator: uint256


struct PartialLiquidationResult:
    collateral_claimed: uint256
    liquidation_fee: uint256
    debt_written_off: uint256
    updated_ltv: uint256


struct RedeemResult:
    vault: address
    collateral_redeemed: uint256
    payment_redeemed: uint256
    timestamp: uint256


struct SignedRedeemResult:
    result: RedeemResult
    signature: Signature


event OfferRevoked:
    offer_id: bytes32
    lender: address

event TransferFailed:
    _to: address
    amount: uint256

# Global variables


owner: public(address)
proposed_owner: public(address)
transfer_agent: public(address)


loans: public(HashMap[bytes32, bytes32])

protocol_wallet: public(address)
protocol_upfront_fee: public(uint256)
partial_liquidation_fee: public(uint256)
full_liquidation_fee: public(uint256)
protocol_settlement_fee: public(uint256)

commited_liquidity: public(HashMap[bytes32, uint256])
revoked_offers: public(HashMap[bytes32, bool])

authorized_proxies: public(HashMap[address, bool])
pending_transfers: public(HashMap[address, uint256])
vault_count: public(HashMap[address, uint256])

securitize_redemption_wallet: public(address)

ZHARTA_DOMAIN_NAME: constant(String[6]) = "Zharta"
ZHARTA_DOMAIN_VERSION: constant(String[1]) = "1"

DOMAIN_TYPE_HASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
OFFER_TYPE_DEF: constant(String[370]) = "Offer(uint256 principal,uint256 apr,address payment_token,address collateral_token,uint256 duration," \
                                        "uint256 origination_fee_bps,uint256 min_collateral_amount,uint256 max_iltv,uint256 available_liquidity," \
                                        "uint256 call_eligibility,uint256 call_window,uint256 liquidation_ltv,address oracle_addr," \
                                        "uint256 expiration,address lender,address borrower,bytes32 tracing_id)"
OFFER_TYPE_HASH: constant(bytes32) = keccak256(OFFER_TYPE_DEF)

EXTENSION_OFFER_TYPE_DEF: constant(String[82]) = "LoanExtensionOffer(bytes32 loan_id,uint256 original_maturity,uint256 new_maturity)"
EXTENSION_OFFER_TYPE_HASH: constant(bytes32) = keccak256(EXTENSION_OFFER_TYPE_DEF)


@deploy
def __init__():
    self.owner = msg.sender


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

    liquidity_key: bytes32 = self._commited_liquidity_key(offer.offer.lender, offer.offer.tracing_id)
    commited_liquidity: uint256 = self.commited_liquidity[liquidity_key]
    assert commited_liquidity + amount <= offer.offer.available_liquidity, "offer fully utilized"
    self.commited_liquidity[liquidity_key] = commited_liquidity + amount

    if offer.offer.borrower != empty(address):
        # offer has borrower => normal offer
        self._revoke_offer(offer_id, offer)


@internal
def _revoke_offer(offer_id: bytes32, offer: SignedOffer):

    self.revoked_offers[offer_id] = True

    log OfferRevoked(offer_id=offer_id, lender=offer.offer.lender)


@internal
def _reduce_commited_liquidity(lender: address, tracing_id: bytes32, amount: uint256):
    liquidity_key: bytes32 = self._commited_liquidity_key(lender, tracing_id)
    commited_liquidity: uint256 = self.commited_liquidity[liquidity_key]
    self.commited_liquidity[liquidity_key] = 0 if amount > commited_liquidity else commited_liquidity - amount

@pure
@internal
def _commited_liquidity_key(lender: address, tracing_id: bytes32) -> bytes32:
    return keccak256(concat(convert(lender, bytes32), tracing_id))

@view
@internal
def _is_loan_valid(loan: Loan) -> bool:
    return self.loans[loan.id] == self._loan_state_hash(loan)

@pure
@internal
def _loan_state_hash(loan: Loan) -> bytes32:
    return keccak256(abi_encode(loan))


@internal
def _is_offer_signed_by_lender(signed_offer: SignedOffer, offer_sig_domain_separator: bytes32) -> bool:
    assert signed_offer.signature.s <= MALLEABILITY_THRESHOLD, "invalid signature"

    message_hash: bytes32 = keccak256(
            concat(
                convert("\x19\x01", Bytes[2]),
                abi_encode(
                    offer_sig_domain_separator,
                    keccak256(abi_encode(OFFER_TYPE_HASH, signed_offer.offer))
                )
            )
        )

    signer: address = ecrecover(
        message_hash,
        signed_offer.signature.v,
        signed_offer.signature.r,
        signed_offer.signature.s
    )

    if signed_offer.offer.lender.is_contract:
        return staticcall EIP1271Signer(signed_offer.offer.lender).is_valid_signature(
            message_hash,
            concat(
                convert(signed_offer.signature.r, bytes32),
                convert(signed_offer.signature.s, bytes32),
                convert(convert(signed_offer.signature.v, uint8), bytes1)
            )
        ) == EIP1271_MAGIC_VALUE
    else:
        return signer == signed_offer.offer.lender

@internal
def _is_extension_offer_signed_by_lender(signed_offer: SignedLoanExtensionOffer, lender: address, offer_sig_domain_separator: bytes32) -> bool:
    assert signed_offer.signature.s <= MALLEABILITY_THRESHOLD, "invalid signature"

    message_hash: bytes32 = keccak256(
            concat(
                convert("\x19\x01", Bytes[2]),
                abi_encode(
                    offer_sig_domain_separator,
                    keccak256(abi_encode(EXTENSION_OFFER_TYPE_HASH, signed_offer.offer))
                )
            )
        )

    signer: address = ecrecover(
        message_hash,
        signed_offer.signature.v,
        signed_offer.signature.r,
        signed_offer.signature.s
    )

    if lender.is_contract:
        return staticcall EIP1271Signer(lender).is_valid_signature(
            message_hash,
            concat(
                convert(signed_offer.signature.r, bytes32),
                convert(signed_offer.signature.s, bytes32),
                convert(convert(signed_offer.signature.v, uint8), bytes1)
            )
        ) == EIP1271_MAGIC_VALUE
    else:
        return signer == lender


@internal
@view
def _validate_redeem_result_sig(redeem_result: SignedRedeemResult):
    assert ecrecover(
        keccak256(abi_encode(concat(convert("\x19\x00", Bytes[2]), keccak256(abi_encode(redeem_result.result))))),
         redeem_result.signature.v,
         redeem_result.signature.r,
         redeem_result.signature.s
    ) == self.owner, "invalid redeem result sig"


@view
@internal
def _compute_settlement_interest(loan: Loan) -> uint256:
    return loan.amount * loan.apr * (block.timestamp - loan.accrual_start_time) // (BPS * YEAR_TO_SECONDS)


@internal
def _send_funds(_to: address, _amount: uint256, payment_token: address):
    success: bool = False
    response: Bytes[32] = b""

    if _amount == 0:
        return
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
def _receive_funds(_from: address, _amount: uint256, payment_token: address):
    assert extcall IERC20(payment_token).transferFrom(_from, self, _amount), "transferFrom failed"


@internal
def _transfer_funds(_from: address, _to: address, _amount: uint256, payment_token: address):
    assert extcall IERC20(payment_token).transferFrom(_from, _to, _amount), "transferFrom failed"


@internal
def _send_collateral(wallet: address, _amount: uint256, _vault: vault.Vault):
    if _amount == 0:
        return
    extcall _vault.withdraw(_amount, wallet)


@internal
def _receive_collateral(_from: address, _amount: uint256, _vault: vault.Vault):
    extcall _vault.deposit(_amount, _from)


@internal
def _check_user(user: address) -> bool:
    return msg.sender == user or (self.authorized_proxies[msg.sender] and user == tx.origin)

@internal
def _check_offer_validity(offer: SignedOffer, payment_token: address, collateral_token: address, oracle_addr: address):
    assert offer.offer.expiration > block.timestamp, "offer expired"
    assert offer.offer.duration > 0, "duration is 0"
    assert offer.offer.payment_token == payment_token, "invalid payment token"
    assert offer.offer.collateral_token == collateral_token, "invalid collateral token"
    assert offer.offer.oracle_addr == empty(address) or offer.offer.oracle_addr == oracle_addr, "invalid oracle address"
    assert offer.offer.min_collateral_amount > 0 or offer.offer.max_iltv > 0, "no min collateral nor max iltv"
    assert offer.offer.call_eligibility == 0, "call eligibility not supported"
    assert offer.offer.call_window == 0, "call window not supported"


@view
@internal
def _get_oracle_rate(oracle_addr: address, oracle_reverse: bool) -> UInt256Rational:
    answer: int256 = (staticcall AggregatorV3Interface(oracle_addr).latestRoundData()).answer
    assert answer > 0, "invalid oracle rate"
    if oracle_reverse:
        return UInt256Rational(
            numerator=10 ** convert(staticcall AggregatorV3Interface(oracle_addr).decimals(), uint256),
            denominator=convert(answer, uint256)
        )
    else:
        return UInt256Rational(
            numerator=convert(answer, uint256),
            denominator=10 ** convert(staticcall AggregatorV3Interface(oracle_addr).decimals(), uint256)
        )


@view
@internal
def _compute_ltv(collateral_amount: uint256, amount: uint256, convertion_rate: UInt256Rational, payment_token_decimals: uint256, collateral_token_decimals: uint256) -> uint256:
    return amount * BPS * convertion_rate.denominator * collateral_token_decimals // (collateral_amount * convertion_rate.numerator * payment_token_decimals)


@view
@internal
def _compute_partial_liquidation(
    collateral_amount: uint256,
    outstanding_debt: uint256,
    initial_ltv: uint256,
    partial_liquidation_fee: uint256,
    convertion_rate: UInt256Rational,
    payment_token_decimals: uint256,
    collateral_token_decimals: uint256
) -> (uint256, uint256, uint256):
    """
    returns:
        principal_written_off: uint256 - the amount of principal written off
        collateral_claimed: uint256 - the amount of collateral claimed
        liquidation_fee: uint256 - the liquidation fee
    """
    collateral_value: uint256 = collateral_amount * convertion_rate.numerator * payment_token_decimals // (convertion_rate.denominator * collateral_token_decimals)
    principal_written_off: uint256 = (outstanding_debt * BPS - collateral_value * initial_ltv)  * BPS // (BPS * BPS - (BPS + partial_liquidation_fee) * initial_ltv)
    collateral_claimed: uint256 = principal_written_off * convertion_rate.denominator * collateral_token_decimals // (convertion_rate.numerator * payment_token_decimals)
    liquidation_fee: uint256 = collateral_claimed * partial_liquidation_fee // BPS

    return principal_written_off, collateral_claimed, liquidation_fee


@view
@internal
def _is_loan_defaulted(loan: Loan) -> bool:
    return block.timestamp > loan.maturity


@view
@internal
def _is_loan_redeemed(loan: Loan) -> bool:
    return loan.redeem_start > 0


@view
@internal
def _get_redeem_balances(loan: Loan, _vault: vault.Vault, payment_token: address, redeem_result: RedeemResult) -> (uint256, uint256):
    assert staticcall IERC20(payment_token).balanceOf(_vault.address) >= redeem_result.payment_redeemed, "invalid redeem payment amount"
    assert staticcall _vault.withdrawable_balance() >= loan.redeem_residual_collateral + redeem_result.collateral_redeemed, "invalid redeem collateral amnt"
    return redeem_result.payment_redeemed, loan.redeem_residual_collateral + redeem_result.collateral_redeemed


@view
@internal
def _is_loan_redeem_concluded(loan: Loan, _vault: vault.Vault, redeem_result: SignedRedeemResult) -> bool:
    if loan.redeem_start == 0:
        return False
    if redeem_result.result.timestamp < loan.redeem_start:
        return False
    if redeem_result.result.vault != _vault.address:
        return False
    self._validate_redeem_result_sig(redeem_result)
    return True


@internal
@view
def _get_vault(wallet: address, vault_id: uint256, _vault_impl_addr: address) -> vault.Vault:
    _vault: address = self._wallet_to_vault(wallet, vault_id, _vault_impl_addr)
    assert _vault.is_contract, "no vault exists for wallet"
    return vault.Vault(_vault)

@internal
def _create_vault_by_id_if_needed(wallet: address, vault_impl_addr: address, payment_token: address, vault_id: uint256) -> vault.Vault:
    _vault: address = self._wallet_to_vault(wallet, vault_id, vault_impl_addr)
    if not _vault.is_contract:
        _salt: bytes32 = keccak256(concat(convert(wallet, bytes20), convert(vault_id, bytes32)))
        _vault = create_minimal_proxy_to(vault_impl_addr, salt=_salt)
        extcall vault.Vault(_vault).initialise(wallet, payment_token)

    return vault.Vault(_vault)


@internal
def _create_vault_if_needed(wallet: address, vault_impl_addr: address, payment_token: address) -> vault.Vault:
    return self._create_vault_by_id_if_needed(wallet, vault_impl_addr, payment_token, self.vault_count[wallet])


@internal
def _create_new_vault(wallet: address, vault_impl_addr: address, payment_token: address) -> vault.Vault:
    # only creates a vault if needed
    _vault: vault.Vault = self._create_vault_if_needed(wallet, vault_impl_addr, payment_token)
    self.vault_count[wallet] += 1
    return _vault


@view
@internal
def _wallet_to_vault(wallet: address, vault_id: uint256, vault_impl_addr: address) -> address:
    _salt: bytes32 = keccak256(concat(convert(wallet, bytes20), convert(vault_id, bytes32)))
    return self._compute_address(
        _salt,
        keccak256(concat(
            _DEPLOYMENT_CODE,
            _PRE,
            convert(vault_impl_addr, bytes20),
            _POST
        )),
        self
    )

@pure
@internal
def _compute_address(salt: bytes32, bytecode_hash: bytes32, deployer: address) -> address:
    data: bytes32 = keccak256(concat(_COLLISION_OFFSET, convert(deployer, bytes20), salt, bytecode_hash))
    return self._convert_keccak256_2_address(data)


@pure
@internal
def _convert_keccak256_2_address(digest: bytes32) -> address:
    return convert(convert(digest, uint256) & convert(max_value(uint160), uint256), address)
