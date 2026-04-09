import contextlib
from collections import namedtuple
from typing import NamedTuple

import boa
import eth_abi
from eth.exceptions import Revert
from eth_abi import encode
from eth_utils import keccak

from tests.conftest_base import (  # noqa: F401
    BPS,
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    SignedOffer,
    calc_collateral_from_ltv,
    calc_full_liquidation,
    calc_ltv,
    calc_partial_liquidation,
    compute_liquidity_key,
    compute_signed_offer_id,
    get_calls,
    get_events,
    get_last_event,
    manipulate_signature,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
)


@contextlib.contextmanager
def deploy_reverts():
    try:
        yield
        raise ValueError("Did not revert")
    except Revert:
        ...


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
    partial_liquidation_fee: int = 0
    full_liquidation_fee: int = 0
    call_eligibility: int = 0
    call_window: int = 0
    liquidation_ltv: int = 0
    oracle_addr: str = ZERO_ADDRESS
    initial_ltv: int = 0
    call_time: int = 0

    def get_interest(self, timestamp):
        return self.apr * self.amount * (timestamp - self.accrual_start_time) // (365 * 24 * 3600 * BPS)


class SecuritizeLoan(NamedTuple):
    """Loan struct for Securitize contracts with additional fields for vault_id, redeem_start, redeem_residual_collateral"""

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

    def get_interest(self, timestamp):
        return self.apr * self.amount * (timestamp - self.accrual_start_time) // (365 * 24 * 3600 * BPS)


PartialLiquidationResult = namedtuple(
    "PartialLiquidationResult",
    ["collateral_claimed", "liquidation_fee", "debt_written_off", "updated_ltv"],
    defaults=[0, 0, 0, 0],
)


def compute_loan_hash(loan: Loan):
    encoded = eth_abi.encode(
        [
            "(bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256)"
        ],
        [loan],
    )
    return boa.eval(f"""keccak256({encoded})""")


def compute_securitize_loan_hash(loan: SecuritizeLoan):
    """Compute hash for SecuritizeLoan struct (29 fields)"""
    encoded = eth_abi.encode(
        [
            "(bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256)"
        ],
        [loan],
    )
    return boa.eval(f"""keccak256({encoded})""")


def compute_loan_id(borrower: str, lender: str, start_time: int, offer_id: bytes):
    return boa.eval(
        f"""keccak256(concat(convert({borrower}, bytes32), convert({lender}, bytes32), convert({start_time}, bytes32), {offer_id}))"""  # noqa: E501
    )


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
    yield replace_namedtuple_field(loan, start_time=loan.start_time - 1)
    yield replace_namedtuple_field(loan, borrower=random_address)
    yield replace_namedtuple_field(loan, lender=random_address)


def get_securitize_loan_mutations(loan: SecuritizeLoan):
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
    yield replace_namedtuple_field(loan, id=keccak(encode(["bytes32"], [compute_securitize_loan_hash(loan)])))
    yield replace_namedtuple_field(loan, maturity=loan.maturity - 1)
    yield replace_namedtuple_field(loan, start_time=loan.start_time - 1)
    yield replace_namedtuple_field(loan, borrower=random_address)
    yield replace_namedtuple_field(loan, lender=random_address)
    # Securitize-specific fields
    yield replace_namedtuple_field(loan, vault_id=loan.vault_id + 1)
    yield replace_namedtuple_field(loan, redeem_start=loan.redeem_start + 1)
    yield replace_namedtuple_field(loan, redeem_residual_collateral=loan.redeem_residual_collateral + 1)
