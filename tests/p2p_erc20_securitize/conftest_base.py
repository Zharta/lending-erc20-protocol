from collections import namedtuple
from dataclasses import dataclass, field
from typing import NamedTuple

import boa
import eth_abi
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak

from tests.conftest_base import (  # noqa: F401
    BPS,
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    Signature,
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


class SecuritizeLoan(NamedTuple):
    """Loan struct for Securitize contracts with vault_id, redeem_start, redeem_residual_collateral fields"""

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


def get_securitize_loan_mutations(loan: SecuritizeLoan):
    """Generate mutations for SecuritizeLoan struct"""
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
