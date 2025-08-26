import contextlib
from collections import namedtuple
from dataclasses import field
from enum import IntEnum
from functools import cached_property
from hashlib import sha3_256
from itertools import starmap
from textwrap import dedent
from typing import NamedTuple

import boa
import eth_abi
import vyper
from boa.contracts.event_decoder import RawLogEntry
from boa.contracts.vyper.vyper_contract import VyperContract
from eth.exceptions import Revert
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from web3 import Web3

ZERO_ADDRESS = boa.eval("empty(address)")
ZERO_BYTES32 = boa.eval("empty(bytes32)")
BPS = 10000


def get_last_event(contract: VyperContract, name: str | None = None):
    matching_events = [
        e for e in contract.get_logs() if not isinstance(e, RawLogEntry) and (name is None or name == type(e).__name__)
    ]
    return EventWrapper(matching_events[-1])


def get_events(contract: VyperContract, name: str | None = None):
    return [
        EventWrapper(e)
        for e in contract.get_logs()
        if not isinstance(e, RawLogEntry) and (name is None or name == type(e).__name__)
    ]


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


@contextlib.contextmanager
def deploy_reverts():
    try:
        yield
        raise ValueError("Did not revert")
    except Revert:
        ...


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
    soft_liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    expiration: int = 0
    lender: str = ZERO_ADDRESS
    borrower: str = ZERO_ADDRESS
    tracing_id: bytes = ZERO_BYTES32


Signature = namedtuple("Signature", ["v", "r", "s"], defaults=[0, ZERO_BYTES32, ZERO_BYTES32])

SignedOffer = namedtuple("SignedOffer", ["offer", "signature"], defaults=[Offer(), Signature()])

WalletValidation = namedtuple("WalletValidation", ["wallet", "expiration_time"], defaults=[ZERO_ADDRESS, 0])

SignedWalletValidation = namedtuple(
    "SignedWalletValidation", ["validation", "signature"], defaults=[WalletValidation(), Signature()]
)


class Loan(NamedTuple):
    id: bytes = ZERO_BYTES32
    offer_id: bytes = ZERO_BYTES32
    offer_tracing_id: bytes = ZERO_BYTES32
    initial_amount: int = 0
    amount: int = 0
    apr: int = 0
    payment_token: str = ZERO_ADDRESS
    maturity: int = 0
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
    soft_liquidation_fee: int = 0
    call_eligibility: int = 0
    call_window: int = 0
    soft_liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    initial_ltv: int = 0
    call_time: int = 0

    def get_interest(self, timestamp):
        return self.apr * self.amount * (timestamp - self.accrual_start_time) // (365 * 24 * 3600)


AggregatorV3LatestRoundData = namedtuple(
    "AggregatorV3LatestRoundData",
    ["roundId", "answer", "startedAt", "updatedAt", "answeredInRound"],
    defaults=[0, 0, 0, 0, 0],
)


def compute_loan_hash(loan: Loan):
    encoded = eth_abi.encode(
        [
            "(bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256)"
        ],
        [loan],
    )
    return boa.eval(f"""keccak256({encoded})""")


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
                {"name": "soft_liquidation_ltv", "type": "uint256"},
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


def replace_namedtuple_field(namedtuple, **kwargs):
    return namedtuple.__class__(**namedtuple._asdict() | kwargs)


def replace_list_element(lst, index, value):
    return lst[:index] + [value] + lst[index + 1 :]


def get_loan_mutations(loan):
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
    yield replace_namedtuple_field(loan, soft_liquidation_fee=loan.soft_liquidation_fee + 1)
    yield replace_namedtuple_field(loan, call_eligibility=loan.call_eligibility + 1)
    yield replace_namedtuple_field(loan, call_window=loan.call_window + 1)
    yield replace_namedtuple_field(loan, soft_liquidation_ltv=loan.soft_liquidation_ltv + 1)
    yield replace_namedtuple_field(loan, oracle_addr=random_address)
    yield replace_namedtuple_field(loan, initial_ltv=loan.initial_ltv + 1)
    yield replace_namedtuple_field(loan, call_time=loan.call_time + 1)
    yield replace_namedtuple_field(loan, offer_id=ZERO_BYTES32)
    yield replace_namedtuple_field(loan, offer_tracing_id=b"1")
    yield replace_namedtuple_field(loan, accrual_start_time=loan.accrual_start_time + 1)
    yield replace_namedtuple_field(loan, id=keccak(encode(["bytes32"], [compute_loan_hash(loan)])))
    yield replace_namedtuple_field(loan, maturity=loan.maturity - 1)
    yield replace_namedtuple_field(loan, start_time=loan.start_time - 1)
    yield replace_namedtuple_field(loan, borrower=random_address)
    yield replace_namedtuple_field(loan, lender=random_address)


def calc_ltv(principal, collateral_amount, principal_token, collateral_token, oracle):
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    principal_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    return (
        principal * BPS * oracle_decimals * collateral_token_decimals // (collateral_amount * rate * principal_token_decimals)
    )


def calc_collateral_from_ltv(principal, ltv, principal_token, collateral_token, oracle):
    print(f"calc_collateral_from_ltv {principal=}, {ltv=}")
    rate = oracle.latestRoundData().answer
    oracle_decimals = 10 ** oracle.decimals()
    principal_token_decimals = 10 ** principal_token.decimals()
    collateral_token_decimals = 10 ** collateral_token.decimals()
    return principal * BPS * oracle_decimals * collateral_token_decimals // (ltv * rate * principal_token_decimals)


def calc_soft_liquidation(loan, principal_token, collateral_token, oracle, timestamp):
    convertion_rate_numerator = oracle.latestRoundData().answer
    convertion_rate_denominator = 10 ** oracle.decimals()
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
        // (BPS * BPS - (BPS + loan.soft_liquidation_fee) * loan.initial_ltv)
    )
    collateral_claimed = (
        principal_written_off
        * convertion_rate_denominator
        * collateral_token_decimals
        // (convertion_rate_numerator * payment_token_decimals)
    )
    liquidation_fee = collateral_claimed * loan.soft_liquidation_fee // BPS

    return principal_written_off, collateral_claimed, liquidation_fee
