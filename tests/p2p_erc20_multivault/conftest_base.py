from collections import namedtuple
from dataclasses import dataclass, field
from textwrap import dedent
from typing import NamedTuple

import boa
import eth_abi
from boa.contracts.event_decoder import RawLogEntry
from boa.contracts.vyper.vyper_contract import VyperContract
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import function_signature_to_4byte_selector, keccak

# Constants
ZERO_ADDRESS = boa.eval("empty(address)")
ZERO_BYTES32 = boa.eval("empty(bytes32)")
BPS = 10000


# Event helpers
class EventWrapper:
    def __init__(self, event: namedtuple):
        self.event = event
        self.event_name = type(event).__name__
        self.args_dict = event._asdict()

    def __getattr__(self, name):
        if name in self.args_dict:
            return self.args_dict[name]
        raise AttributeError(f"No attr {name} in {self.event_name}. Event data is {self.event}")

    def __repr__(self):
        return f"<EventWrapper {self.event_name} {self.args_dict}>"


def get_last_event(contract: VyperContract, name: str | None = None):
    matching_events = [
        e
        for e in contract.get_logs(strict=False)
        if not isinstance(e, RawLogEntry) and (name is None or name == type(e).__name__)
    ]
    return EventWrapper(matching_events[-1])


def get_calls(contract, signature: str, arg_types: list[str] | None = None):
    """Return decoded calls matching a function signature from the last computation trace.

    Args:
        contract: The contract whose last computation to inspect.
        signature: Function signature, e.g. 'swap(uint256,uint256)'.
        arg_types: ABI types to decode args. If None, returns raw calldata.

    Returns:
        List of decoded arg tuples (if arg_types) or raw calldata bytes.
    """
    selector = function_signature_to_4byte_selector(signature)
    results = []
    for child in contract._computation.children:
        if child.msg.data_as_bytes[:4] == selector:
            if arg_types:
                results.append(eth_abi.decode(arg_types, child.msg.data_as_bytes[4:]))
            else:
                results.append(child.msg.data_as_bytes)
    return results


def get_events(contract: VyperContract, name: str | None = None):
    return [
        EventWrapper(e)
        for e in contract.get_logs()
        if not isinstance(e, RawLogEntry) and (name is None or name == type(e).__name__)
    ]


# Data structures
class Offer(NamedTuple):
    principal: int = 0
    apr: int = 0
    payment_token: str = ZERO_ADDRESS
    collateral_token: str = ZERO_ADDRESS
    duration: int = 0
    origination_fee_bps: int = 0
    min_collateral_amount: int = 0
    max_iltv: int = 0
    available_liquidity: int = 0
    call_eligibility: int = 0
    call_window: int = 0
    liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    expiration: int = 0
    lender: str = ZERO_ADDRESS
    borrower: str = ZERO_ADDRESS
    tracing_id: bytes = ZERO_BYTES32


Signature = namedtuple("Signature", ["v", "r", "s"], defaults=[0, 0, 0])

SignedOffer = namedtuple("SignedOffer", ["offer", "signature"], defaults=[Offer(), Signature()])

WalletValidation = namedtuple("WalletValidation", ["wallet", "expiration_time"], defaults=[ZERO_ADDRESS, 0])

SignedWalletValidation = namedtuple(
    "SignedWalletValidation", ["validation", "signature"], defaults=[WalletValidation(), Signature()]
)

RedeemResult = namedtuple(
    "RedeemResult",
    ["vault", "collateral_redeemed", "payment_redeemed", "timestamp"],
    defaults=[ZERO_ADDRESS, 0, 0, 0],
)

SignedRedeemResult = namedtuple("SignedRedeemResult", ["result", "signature"], defaults=[RedeemResult(), Signature()])

LoanExtensionOffer = namedtuple(
    "LoanExtensionOffer", ["loan_id", "original_maturity", "new_maturity"], defaults=[ZERO_BYTES32, 0, 0]
)

SignedLoanExtensionOffer = namedtuple(
    "SignedLoanExtensionOffer", ["offer", "signature"], defaults=[LoanExtensionOffer(), Signature()]
)


class Loan(NamedTuple):
    """Loan struct for MultiVault contracts.

    Mirrors P2PLendingMultiVaultBase.vy struct Loan (31 fields). Note the extra
    ``create_time`` field inserted between ``maturity`` and ``start_time`` compared
    to the Securitize Loan struct.
    """

    id: bytes = ZERO_BYTES32
    offer_id: bytes = ZERO_BYTES32
    offer_tracing_id: bytes = ZERO_BYTES32
    initial_amount: int = 0
    amount: int = 0
    apr: int = 0
    payment_token: str = ZERO_ADDRESS
    maturity: int = 0
    create_time: int = 0
    start_time: int = 0
    accrual_start_time: int = 0
    borrower: str = ZERO_ADDRESS
    lender: str = ZERO_ADDRESS
    collateral_token: str = ZERO_ADDRESS
    collateral_amount: int = 0
    min_collateral_amount: int = 0
    origination_fee_amount: int = 0
    protocol_upfront_fee_amount: int = 0
    protocol_settlement_fee: int = 0
    partial_liquidation_fee: int = 0
    full_liquidation_fee: int = 0
    call_eligibility: int = 0
    call_window: int = 0
    liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    initial_ltv: int = 0
    call_time: int = 0
    vault_id: int = 0
    redeem_start: int = 0
    redeem_residual_collateral: int = 0
    max_pending_window: int = 0

    def get_interest(self, timestamp):
        return self.apr * self.amount * (timestamp - self.accrual_start_time) // (365 * 24 * 3600 * BPS)

    def get_capped_interest(self, timestamp):
        # Interest accrued to `timestamp` but never past maturity (charged by cancel_pending_loan).
        end_time = min(timestamp, self.maturity)
        return self.apr * self.amount * (end_time - self.accrual_start_time) // (365 * 24 * 3600 * BPS)

    def get_liquidation_interest(self):
        # Full-term interest charged on liquidation.
        return self.apr * self.amount * (self.maturity - self.accrual_start_time) // (365 * 24 * 3600 * BPS)


AggregatorV3LatestRoundData = namedtuple(
    "AggregatorV3LatestRoundData",
    ["roundId", "answer", "startedAt", "updatedAt", "answeredInRound"],
    defaults=[0, 0, 0, 0, 0],
)


@dataclass
class FullLiquidationResult:
    outstanding_debt: int = field(default=0)
    liquidation_fee: int = field(default=0)
    collateral_for_debt: int = field(default=0)
    remaining_collateral: int = field(default=0)
    remaining_collateral_value: int = field(default=0)
    shortfall: int = field(default=0)
    protocol_settlement_fee_amount: int = field(default=0)
    receive_from_liquidator: int = field(default=0)
    send_to_lender: int = field(default=0)
    send_to_protocol: int = field(default=0)
    send_to_borrower: int = field(default=0)
    send_to_liquidator: int = field(default=0)


@dataclass
class FullLiquidationRedeemedResult:
    outstanding_debt: int = field(default=0)
    liquidation_fee: int = field(default=0)
    liquidation_fee_collateral: int = field(default=0)
    in_vault_payment_token: int = field(default=0)
    collateral_for_debt: int = field(default=0)
    remaining_collateral: int = field(default=0)
    remaining_collateral_value: int = field(default=0)
    shortfall: int = field(default=0)
    protocol_settlement_fee_amount: int = field(default=0)
    liquidator_funds_delta: int = field(default=0)
    lender_funds_delta: int = field(default=0)
    borrower_funds_delta: int = field(default=0)
    liquidator_collateral_delta: int = field(default=0)
    borrower_collateral_delta: int = field(default=0)


# Hash computation functions
def compute_loan_hash(loan: Loan):
    """Compute the on-chain loan state hash for the MultiVault Loan struct (31 fields).

    Mirrors P2PLendingMultiVaultBase.vy `_loan_state_hash` = keccak256(abi_encode(loan)).
    The extra ``create_time`` uint256 sits between ``maturity`` and ``start_time``.
    """
    encoded = eth_abi.encode(
        [
            "(bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256,uint256)"
        ],
        [loan],
    )
    return boa.eval(f"""keccak256({encoded})""")


def compute_loan_id(borrower: str, lender: str, create_time: int, offer_id: bytes):
    return boa.eval(
        f"""keccak256(concat(convert({borrower}, bytes32), convert({lender}, bytes32), convert({create_time}, bytes32), {offer_id}))"""  # noqa: E501
    )


def compute_signed_offer_id(offer: SignedOffer):
    return boa.eval(
        dedent(
            f"""keccak256(
            concat(
                convert({offer.signature.v}, bytes32),
                convert({offer.signature.r}, bytes32),
                convert({offer.signature.s}, bytes32),
            ))"""
        )
    )


def compute_liquidity_key(lender: str, offer_tracing_id: bytes):
    return boa.eval(
        dedent(
            f"""keccak256(
            concat(
                convert({lender}, bytes32),
                convert({offer_tracing_id}, bytes32),
            ))"""
        )
    )


# Signing functions
def sign_offer(offer: Offer, lender_key: str, verifying_contract: str) -> SignedOffer:
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Offer": [
                {"name": "principal", "type": "uint256"},
                {"name": "apr", "type": "uint256"},
                {"name": "payment_token", "type": "address"},
                {"name": "collateral_token", "type": "address"},
                {"name": "duration", "type": "uint256"},
                {"name": "origination_fee_bps", "type": "uint256"},
                {"name": "min_collateral_amount", "type": "uint256"},
                {"name": "max_iltv", "type": "uint256"},
                {"name": "available_liquidity", "type": "uint256"},
                {"name": "call_eligibility", "type": "uint256"},
                {"name": "call_window", "type": "uint256"},
                {"name": "liquidation_ltv", "type": "uint256"},
                {"name": "oracle_addr", "type": "address"},
                {"name": "expiration", "type": "uint256"},
                {"name": "lender", "type": "address"},
                {"name": "borrower", "type": "address"},
                {"name": "tracing_id", "type": "bytes32"},
            ],
        },
        "primaryType": "Offer",
        "domain": {
            "name": "Zharta",
            "version": "1",
            "chainId": boa.eval("chain.id"),
            "verifyingContract": verifying_contract,
        },
        "message": offer._asdict(),
    }
    signable_msg = encode_typed_data(full_message=typed_data)
    signed_msg = Account.from_key(lender_key).sign_message(signable_msg)
    lender_signature = Signature(signed_msg.v, signed_msg.r, signed_msg.s)

    return SignedOffer(offer, lender_signature)


def sign_kyc(wallet: str, timestamp: int, signer_key: str, verifying_contract: str) -> SignedWalletValidation:
    wallet_validation = {"wallet": wallet, "expiration_time": timestamp}
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "WalletValidation": [
                {"name": "wallet", "type": "address"},
                {"name": "expiration_time", "type": "uint256"},
            ],
        },
        "primaryType": "WalletValidation",
        "domain": {
            "name": "Zharta",
            "version": "1",
            "chainId": boa.eval("chain.id"),
            "verifyingContract": verifying_contract,
        },
        "message": wallet_validation,
    }
    signable_msg = encode_typed_data(full_message=typed_data)
    signed_msg = Account.from_key(signer_key).sign_message(signable_msg)
    signature = Signature(signed_msg.v, signed_msg.r, signed_msg.s)

    return SignedWalletValidation(WalletValidation(**wallet_validation), signature)


def sign_extension_offer(offer: LoanExtensionOffer, lender_key: str, verifying_contract: str) -> SignedLoanExtensionOffer:
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "LoanExtensionOffer": [
                {"name": "loan_id", "type": "bytes32"},
                {"name": "original_maturity", "type": "uint256"},
                {"name": "new_maturity", "type": "uint256"},
            ],
        },
        "primaryType": "LoanExtensionOffer",
        "domain": {
            "name": "Zharta",
            "version": "1",
            "chainId": boa.eval("chain.id"),
            "verifyingContract": verifying_contract,
        },
        "message": offer._asdict(),
    }
    signable_msg = encode_typed_data(full_message=typed_data)
    signed_msg = Account.from_key(lender_key).sign_message(signable_msg)
    lender_signature = Signature(signed_msg.v, signed_msg.r, signed_msg.s)

    return SignedLoanExtensionOffer(offer, lender_signature)


def sign_redeem_result(result: RedeemResult, owner_key: str) -> SignedRedeemResult:
    """
    Sign a RedeemResult with the owner's private key.
    Matches the contract's _validate_redeem_result_sig:
        keccak256(abi_encode(concat("\x19\x00", keccak256(abi_encode(redeem_result.result)))))
    """
    # ABI encode the result struct
    encoded_result = encode(
        ["(address,uint256,uint256,uint256)"],
        [(result.vault, result.collateral_redeemed, result.payment_redeemed, result.timestamp)],
    )
    # Hash the encoded result
    inner_hash = keccak(encoded_result)
    # Prefix with \x19\x00 and hash again
    prefixed = b"\x19\x00" + inner_hash
    message_hash = keccak(encode(["bytes"], [prefixed]))

    # Sign with eth_account (recoverable signature)
    signed = Account.from_key(owner_key).unsafe_sign_hash(message_hash)
    signature = Signature(signed.v, signed.r, signed.s)

    return SignedRedeemResult(result, signature)


def sign_register_vault(account, connector_address, vault_registrar, deadline, investor_address=None):
    """
    Sign an EIP-712 RegisterVault message matching the V2 connector's _validate_signature logic.

    Args:
        account: eth_account.Account with private key
        connector_address: address of the V2 connector (the operator)
        vault_registrar: deployed V2 vault registrar contract
        deadline: uint256 deadline timestamp
        investor_address: address to use as investor in the message (defaults to account.address).

    Returns:
        tuple (v, r, s) as ints
    """
    investor = investor_address or account.address
    token_addr = vault_registrar.token()
    nonce = vault_registrar.operatorNonce(investor, connector_address)

    structured_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "RegisterVault": [
                {"name": "investor", "type": "address"},
                {"name": "operator", "type": "address"},
                {"name": "token", "type": "address"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "RegisterVault",
        "domain": {
            "name": "VaultRegistrar",
            "version": "1",
            "chainId": boa.eval("chain.id"),
            "verifyingContract": vault_registrar.address,
        },
        "message": {
            "investor": investor,
            "operator": connector_address,
            "token": token_addr,
            "nonce": nonce,
            "deadline": deadline,
        },
    }

    signable_message = encode_typed_data(full_message=structured_data)
    signed = account.sign_message(signable_message)
    return signed.v, signed.r, signed.s


# Utility functions
def replace_namedtuple_field(namedtuple, **kwargs):
    return namedtuple.__class__(**namedtuple._asdict() | kwargs)


def manipulate_signature(sig: Signature):
    new_v = (sig.v + 1) if sig.v % 2 else (sig.v - 1)
    new_s = int("0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141", 16) - sig.s
    return Signature(new_v, sig.r, new_s)


def get_loan_mutations(loan: Loan):
    """Generate single-field mutations for the MultiVault Loan struct."""
    random_address = boa.env.generate_address("random")

    yield replace_namedtuple_field(loan, id=ZERO_BYTES32)
    yield replace_namedtuple_field(loan, amount=loan.amount + 1)
    yield replace_namedtuple_field(loan, apr=loan.apr + 1)
    yield replace_namedtuple_field(loan, payment_token=random_address)
    yield replace_namedtuple_field(loan, collateral_token=random_address)
    yield replace_namedtuple_field(loan, collateral_amount=loan.collateral_amount + 1)
    yield replace_namedtuple_field(loan, min_collateral_amount=loan.min_collateral_amount + 1)
    yield replace_namedtuple_field(loan, initial_amount=loan.initial_amount + 1)
    yield replace_namedtuple_field(loan, origination_fee_amount=loan.origination_fee_amount + 1)
    yield replace_namedtuple_field(loan, protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount + 1)
    yield replace_namedtuple_field(loan, protocol_settlement_fee=loan.protocol_settlement_fee + 1)
    yield replace_namedtuple_field(loan, partial_liquidation_fee=loan.partial_liquidation_fee + 1)
    yield replace_namedtuple_field(loan, full_liquidation_fee=loan.full_liquidation_fee + 1)
    yield replace_namedtuple_field(loan, call_eligibility=loan.call_eligibility + 1)
    yield replace_namedtuple_field(loan, call_window=loan.call_window + 1)
    yield replace_namedtuple_field(loan, liquidation_ltv=loan.liquidation_ltv + 1)
    yield replace_namedtuple_field(loan, oracle_addr=random_address)
    yield replace_namedtuple_field(loan, initial_ltv=loan.initial_ltv + 1)
    yield replace_namedtuple_field(loan, call_time=loan.call_time + 1)
    yield replace_namedtuple_field(loan, offer_id=ZERO_BYTES32)
    yield replace_namedtuple_field(loan, offer_tracing_id=b"1")
    yield replace_namedtuple_field(loan, accrual_start_time=loan.accrual_start_time + 1)
    yield replace_namedtuple_field(loan, id=keccak(encode(["bytes32"], [compute_loan_hash(loan)])))
    yield replace_namedtuple_field(loan, maturity=loan.maturity - 1)
    yield replace_namedtuple_field(loan, create_time=loan.create_time + 1)
    yield replace_namedtuple_field(loan, start_time=loan.start_time + 1)
    yield replace_namedtuple_field(loan, borrower=random_address)
    yield replace_namedtuple_field(loan, lender=random_address)
    # MultiVault-specific fields
    yield replace_namedtuple_field(loan, vault_id=loan.vault_id + 1)
    yield replace_namedtuple_field(loan, redeem_start=loan.redeem_start + 1)
    yield replace_namedtuple_field(loan, redeem_residual_collateral=loan.redeem_residual_collateral + 1)


# Calculation functions
def calc_ltv(principal, collateral_amount, principal_token, collateral_token, oracle, *, oracle_reverse=False):
    latest_round_data = AggregatorV3LatestRoundData(*oracle.latestRoundData())
    rate = latest_round_data.answer
    oracle_decimals = 10 ** oracle.decimals()
    if oracle_reverse:
        rate, oracle_decimals = oracle_decimals, rate
    principal_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    return (
        principal * BPS * oracle_decimals * collateral_token_decimals // (collateral_amount * rate * principal_token_decimals)
    )


def calc_collateral_from_ltv(principal, ltv, principal_token, collateral_token, oracle):
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    principal_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    return principal * BPS * oracle_decimals * collateral_token_decimals // (ltv * rate * principal_token_decimals)


def calc_partial_liquidation(loan, principal_token, collateral_token, oracle, timestamp, *, oracle_reverse=False):
    convertion_rate_numerator = oracle.latestRoundData().answer
    convertion_rate_denominator = 10 ** oracle.decimals()
    if oracle_reverse:
        convertion_rate_numerator, convertion_rate_denominator = convertion_rate_denominator, convertion_rate_numerator
    payment_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    collateral_amount = loan.collateral_amount
    outstanding_debt = loan.amount + loan.get_interest(timestamp)
    collateral_value = (
        collateral_amount
        * convertion_rate_numerator
        * payment_token_decimals
        // (convertion_rate_denominator * collateral_token_decimals)
    )
    principal_written_off = (
        (outstanding_debt * BPS - collateral_value * loan.initial_ltv)
        * BPS
        // (BPS * BPS - (BPS + loan.partial_liquidation_fee) * loan.initial_ltv)
    )
    collateral_claimed = (
        principal_written_off
        * convertion_rate_denominator
        * collateral_token_decimals
        // (convertion_rate_numerator * payment_token_decimals)
    )
    liquidation_fee = collateral_claimed * loan.partial_liquidation_fee // BPS

    return principal_written_off, collateral_claimed, liquidation_fee


def calc_full_liquidation(loan, principal_token, collateral_token, oracle, timestamp=0, *, oracle_reverse=False):
    convertion_rate_numerator = oracle.latestRoundData().answer
    convertion_rate_denominator = 10 ** oracle.decimals()
    if oracle_reverse:
        convertion_rate_numerator, convertion_rate_denominator = convertion_rate_denominator, convertion_rate_numerator
    payment_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    timestamp = timestamp or min(loan.call_time + loan.call_window if loan.call_time > 0 else 2**256, loan.maturity)
    current_interest = loan.get_interest(timestamp)
    outstanding_debt = loan.amount + current_interest

    liquidation_fee = min(
        loan.collateral_amount,
        outstanding_debt
        * loan.full_liquidation_fee
        * convertion_rate_denominator
        * collateral_token_decimals
        // (convertion_rate_numerator * payment_token_decimals * BPS),
    )

    collateral_for_debt = (outstanding_debt * convertion_rate_denominator * collateral_token_decimals) // (
        convertion_rate_numerator * payment_token_decimals
    )
    remaining_collateral = loan.collateral_amount - liquidation_fee
    remaining_collateral_value = (
        remaining_collateral
        * convertion_rate_numerator
        * payment_token_decimals
        // (convertion_rate_denominator * collateral_token_decimals)
    )
    shortfall = max(0, outstanding_debt - remaining_collateral_value)
    protocol_settlement_fee_amount = min(loan.protocol_settlement_fee * current_interest // BPS, remaining_collateral_value)

    receive_from_liquidator = min(remaining_collateral_value, outstanding_debt)
    send_to_lender = receive_from_liquidator - protocol_settlement_fee_amount
    send_to_protocol = protocol_settlement_fee_amount

    send_to_liquidator = min(loan.collateral_amount, collateral_for_debt + liquidation_fee)
    send_to_borrower = loan.collateral_amount - send_to_liquidator

    # conservation-of-funds assertions
    assert send_to_liquidator + send_to_borrower == loan.collateral_amount, "collateral not conserved"
    assert send_to_lender + send_to_protocol == receive_from_liquidator, "liquidity not conserved"
    assert send_to_liquidator >= 0, "send_to_liquidator negative"
    assert send_to_borrower >= 0, "send_to_borrower negative"
    assert send_to_lender >= 0, "send_to_lender negative"
    assert send_to_protocol >= 0, "send_to_protocol negative"
    assert receive_from_liquidator >= 0, "receive_from_liquidator negative"
    assert liquidation_fee >= 0, "liquidation_fee negative"
    assert shortfall >= 0, "shortfall negative"
    assert liquidation_fee <= loan.collateral_amount, "liquidation_fee exceeds collateral"
    assert send_to_lender <= outstanding_debt, "lender receives more than debt"

    return FullLiquidationResult(
        outstanding_debt=outstanding_debt,
        liquidation_fee=liquidation_fee,
        collateral_for_debt=collateral_for_debt,
        remaining_collateral=remaining_collateral,
        remaining_collateral_value=remaining_collateral_value,
        shortfall=shortfall,
        protocol_settlement_fee_amount=protocol_settlement_fee_amount,
        receive_from_liquidator=receive_from_liquidator,
        send_to_lender=send_to_lender,
        send_to_protocol=send_to_protocol,
        send_to_borrower=send_to_borrower,
        send_to_liquidator=send_to_liquidator,
    )


def calc_full_liquidation_redeemed(
    loan,
    principal_token,
    collateral_token,
    oracle,
    in_vault_payment_token,
    in_vault_collateral,
    timestamp=0,
    *,
    oracle_reverse=False,
):
    """
    Compute expected liquidation values for redeemed loans.

    For redeemed loans, the vault contains both payment tokens (from redemption)
    and residual collateral, unlike non-redeemed loans which have only collateral.

    The liquidation flow mirrors P2PLendingSecuritizeLiquidation.vy:liquidate_loan (lines 218-319):
    1. Compute liquidation_fee in payment token terms
    2. Allocate fee from payment tokens first, then collateral if needed
    3. Determine which of three scenarios applies:
       - Full cover by payment tokens
       - Cover by payment + collateral
       - Shortfall
    4. Compute delta values for each party
    """
    rate_num = oracle.latestRoundData().answer
    rate_den = 10 ** oracle.decimals()
    if oracle_reverse:
        rate_num, rate_den = rate_den, rate_num
    pay_dec = 10 ** principal_token.decimals()
    coll_dec = 10 ** collateral_token.decimals()

    timestamp = timestamp or loan.maturity
    current_interest = loan.get_interest(timestamp)
    outstanding_debt = loan.amount + current_interest

    # Step 1: Liquidation fee in payment token terms
    liquidation_fee = outstanding_debt * loan.full_liquidation_fee // BPS
    liquidation_fee_collateral = 0

    # Step 2: Fee allocation - deduct from payment tokens first
    ivpt = in_vault_payment_token  # mutable copy
    if liquidation_fee <= ivpt:
        ivpt -= liquidation_fee
    else:
        liquidation_fee_collateral = min(
            in_vault_collateral,
            (liquidation_fee - ivpt) * rate_den * coll_dec // (rate_num * pay_dec),
        )
        liquidation_fee = ivpt
        ivpt = 0

    # Step 3: Compute remaining values
    collateral_for_debt = (
        (outstanding_debt - ivpt) * rate_den * coll_dec // (rate_num * pay_dec) if ivpt < outstanding_debt else 0
    )
    remaining_collateral = in_vault_collateral - liquidation_fee_collateral
    remaining_collateral_value = remaining_collateral * rate_num * pay_dec // (rate_den * coll_dec)
    protocol_settlement_fee_amount = min(
        loan.protocol_settlement_fee * current_interest // BPS,
        ivpt + remaining_collateral_value,
    )
    shortfall = outstanding_debt - remaining_collateral_value if remaining_collateral_value < outstanding_debt else 0

    # Step 4: Compute deltas based on scenario
    liquidator_funds_delta = 0
    lender_funds_delta = 0
    borrower_funds_delta = 0
    liquidator_collateral_delta = 0
    borrower_collateral_delta = 0

    if ivpt >= outstanding_debt:
        # Scenario 1: payment tokens fully cover the debt
        lender_funds_delta = outstanding_debt - protocol_settlement_fee_amount
        liquidator_funds_delta = liquidation_fee
        borrower_funds_delta = ivpt - outstanding_debt
        liquidator_collateral_delta = 0
        borrower_collateral_delta = in_vault_collateral

    elif ivpt + remaining_collateral_value >= outstanding_debt:
        # Scenario 2: payment + collateral cover the debt
        lender_funds_delta = outstanding_debt - protocol_settlement_fee_amount
        liquidator_funds_delta = liquidation_fee + ivpt - outstanding_debt
        borrower_funds_delta = 0
        liquidator_collateral_delta = min(collateral_for_debt, remaining_collateral) + liquidation_fee_collateral
        borrower_collateral_delta = (
            in_vault_collateral - liquidator_collateral_delta if in_vault_collateral > liquidator_collateral_delta else 0
        )

    else:
        # Scenario 3: shortfall
        lender_funds_delta = ivpt + remaining_collateral_value - protocol_settlement_fee_amount
        liquidator_funds_delta = liquidation_fee - remaining_collateral_value
        borrower_funds_delta = 0
        liquidator_collateral_delta = in_vault_collateral
        borrower_collateral_delta = 0

    # Conservation assertions
    # collateral: all vault collateral must go to liquidator or borrower
    assert liquidator_collateral_delta + borrower_collateral_delta == in_vault_collateral, "collateral not conserved"
    # payment tokens: all vault payment tokens must go to lender, liquidator, borrower, or protocol
    # note: in_vault_payment_token is the original input (before fee deduction), and
    # ivpt + liquidation_fee == in_vault_payment_token in all branches
    assert (
        lender_funds_delta + liquidator_funds_delta + borrower_funds_delta + protocol_settlement_fee_amount
        == in_vault_payment_token
    ), "payment tokens not conserved"
    # non-negative outflows (liquidator_funds_delta can be negative — liquidator pays into the system)
    assert lender_funds_delta >= 0, "lender_funds_delta negative"
    assert borrower_funds_delta >= 0, "borrower_funds_delta negative"
    assert liquidator_collateral_delta >= 0, "liquidator_collateral_delta negative"
    assert borrower_collateral_delta >= 0, "borrower_collateral_delta negative"
    assert protocol_settlement_fee_amount >= 0, "protocol_settlement_fee_amount negative"
    # bounds
    assert lender_funds_delta <= outstanding_debt, "lender receives more than debt"
    assert (
        liquidation_fee + liquidation_fee_collateral * rate_num * pay_dec // (rate_den * coll_dec)
        <= outstanding_debt * loan.full_liquidation_fee // BPS
    ), "total fee exceeds expected"

    return FullLiquidationRedeemedResult(
        outstanding_debt=outstanding_debt,
        liquidation_fee=liquidation_fee,
        liquidation_fee_collateral=liquidation_fee_collateral,
        in_vault_payment_token=ivpt,
        collateral_for_debt=collateral_for_debt,
        remaining_collateral=remaining_collateral,
        remaining_collateral_value=remaining_collateral_value,
        shortfall=shortfall,
        protocol_settlement_fee_amount=protocol_settlement_fee_amount,
        liquidator_funds_delta=liquidator_funds_delta,
        lender_funds_delta=lender_funds_delta,
        borrower_funds_delta=borrower_funds_delta,
        liquidator_collateral_delta=liquidator_collateral_delta,
        borrower_collateral_delta=borrower_collateral_delta,
    )
