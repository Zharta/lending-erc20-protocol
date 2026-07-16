"""
Regression tests for the signature-validation security fix in
`P2PLendingMultiVaultBase._is_offer_signed_by_lender` and
`_is_extension_offer_signed_by_lender`.

The fix does three things:
  1. Zero-address guard: reverts "invalid signature" if the lender is the zero
     address, before signature recovery (guards against ecrecover returning
     address(0) on a malformed signature matching a zero lender).
  2. Plain ECDSA recover is checked FIRST (`if signer == lender: return True`)
     before the ERC-1271 `is_contract` branch, so an EIP-7702-delegated EOA
     (which has code) still validates via its plain signature.
  3. The ERC-1271 interface method is `isValidSignature` (the standard name);
     a contract lender is honored only when it returns the magic 0x1626ba7e.
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    LoanExtensionOffer,
    Offer,
    compute_signed_offer_id,
    replace_namedtuple_field,
    sign_extension_offer,
    sign_offer,
)

BPS = 10000
DAY = 86400


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc):
    usdc.mint(lender, 10**12)


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


# Minimal ERC-1271 signer mock exposing the STANDARD method name `isValidSignature`
# (the fix renamed the interface method from `is_valid_signature`). It returns the
# magic value or a non-magic value depending on a settable flag, so a single mock
# covers both the "validly signed contract lender" and "invalid contract lender"
# branches without needing to produce a real owner signature.
EIP1271_MOCK_SRC = """
# pragma version 0.4.3

EIP1271_MAGIC_VALUE: constant(bytes4) = 0x1626ba7e

valid: public(bool)

@deploy
def __init__(_valid: bool):
    self.valid = _valid

@external
@view
def isValidSignature(hash: bytes32, signature: Bytes[65]) -> bytes4:
    return EIP1271_MAGIC_VALUE if self.valid else 0x00000000
"""


def _base_offer(now, lender, borrower, usdc, weth, oracle, principal):
    return Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )


# ============== 1. Zero-address lender guard (create path) ==============


def test_create_loan_reverts_if_lender_is_zero_address(
    p2p_usdc_weth, borrower, now, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    """Zero-address guard fires before signature recovery: an offer whose lender
    field is the zero address must revert "invalid signature", even though the
    signature itself is well-formed (non-malleable)."""
    principal = 1000 * 10**6
    offer = _base_offer(now, ZERO_ADDRESS, borrower, usdc, weth, oracle, principal)
    # Sign with a real key so the signature is well-formed and non-malleable;
    # the recovered signer is irrelevant because the zero-address guard fires first.
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    with boa.reverts("invalid signature"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


# ============== 2. Zero-address lender guard (extension path) ==============
#
# BLINDSPOT (test_patterns section 4): the zero-address guard added to
# `_is_extension_offer_signed_by_lender` ("invalid signature") cannot be reached
# through the public `extend_loan` API with a zero lender. `extend_loan`
# (P2PLendingMultiVaultRefinance.extend_loan) passes `loan.lender` as the `lender`
# argument, and asserts `_is_loan_valid(loan)` FIRST. Since `lender` is part of the
# loan hash, a loan with a zero lender fails `_is_loan_valid` ("invalid loan")
# before `_is_extension_offer_signed_by_lender` is ever called. The guard is valid
# defence-in-depth at the internal-function level, but there is no public entry
# point that reaches it with `lender == address(0)`.
#
# The test below documents and pins that actual reachable behavior: a started loan
# whose lender field is zeroed reverts "invalid loan" (loan-validity) via the public
# API, not "invalid signature". If a future change reorders the checks so the guard
# becomes reachable, this test's revert message would change and flag the shift.


def test_extend_loan_with_zeroed_lender_reverts_invalid_loan(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    principal = 1000 * 10**6
    offer = _base_offer(now, lender, borrower, usdc, weth, oracle, principal)
    offer = replace_namedtuple_field(offer, tracing_id=32 * b"\1")
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    loan = Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(signed_offer),
        offer_tracing_id=offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.apr,
        payment_token=offer.payment_token,
        collateral_token=offer.collateral_token,
        maturity=now + offer.duration,
        create_time=now,
        start_time=now,
        accrual_start_time=now,
        borrower=borrower,
        lender=lender,
        collateral_amount=collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_weth.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_weth.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_weth.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_weth.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=0,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=0,
    )

    new_maturity = loan.maturity + 10 * DAY
    extension_offer = LoanExtensionOffer(
        loan_id=loan.id,
        original_maturity=loan.maturity,
        new_maturity=new_maturity,
    )
    signed_extension = sign_extension_offer(extension_offer, lender_key, p2p_usdc_weth.address)

    # Zero out the lender in the loan passed to extend_loan. loan.lender is part of
    # the loan hash and is what extend_loan forwards to the extension guard, so this
    # fails loan-validity ("invalid loan") before the "invalid signature" guard.
    zeroed_lender_loan = replace_namedtuple_field(loan, lender=ZERO_ADDRESS)

    with boa.reverts("invalid loan"):
        p2p_usdc_weth.extend_loan(zeroed_lender_loan, signed_extension, new_maturity, sender=borrower)


# ============== 3. Normal EOA lender still validates (reorder didn't break it) ==============


def test_create_loan_eoa_lender_validates_via_plain_signature(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    """A normally-signed EOA offer creates successfully. This proves the reordered
    logic still hits `if signer == lender: return True` (plain ECDSA recover) before
    the ERC-1271 branch. An EOA has no code, so the recover path is the only one that
    can succeed here."""
    principal = 1000 * 10**6
    offer = _base_offer(now, lender, borrower, usdc, weth, oracle, principal)
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    # Non-zero loan id and stored loan hash prove the loan was created.
    assert loan_id != ZERO_BYTES32
    assert p2p_usdc_weth.loans(loan_id) != ZERO_BYTES32


# ============== 4. Contract lender via isValidSignature (ERC-1271) ==============


def test_create_loan_contract_lender_validates_when_isvalidsignature_returns_magic(
    p2p_usdc_weth, borrower, now, lender_key, kyc_for, kyc_validator_contract, kyc_borrower, usdc, weth, oracle
):
    """A contract lender whose `isValidSignature` returns the magic value 0x1626ba7e
    is accepted: the offer's signer (from ecrecover) does not equal the contract
    lender, so validation falls through to the `is_contract` ERC-1271 branch, which
    now calls the renamed `isValidSignature` method. Loan creation succeeds."""
    lender_contract = boa.loads(EIP1271_MOCK_SRC, True)  # valid=True -> returns magic value
    kyc_lender = kyc_for(lender_contract.address, kyc_validator_contract.address)

    # Fund the contract lender so it can supply the principal.
    usdc.mint(lender_contract.address, 10**12)
    usdc.approve(p2p_usdc_weth.address, 1000 * 10**6, sender=lender_contract.address)

    principal = 1000 * 10**6
    offer = _base_offer(now, lender_contract.address, borrower, usdc, weth, oracle, principal)
    # Signed by an arbitrary key: ecrecover will NOT match the contract lender,
    # forcing the ERC-1271 branch. The mock ignores signature contents.
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert loan_id != ZERO_BYTES32
    assert p2p_usdc_weth.loans(loan_id) != ZERO_BYTES32


def test_create_loan_reverts_if_contract_lender_isvalidsignature_returns_non_magic(
    p2p_usdc_weth, borrower, now, lender_key, kyc_for, kyc_validator_contract, kyc_borrower, usdc, weth, oracle
):
    """A contract lender whose `isValidSignature` returns a non-magic value is
    rejected: `_is_offer_signed_by_lender` returns False, so `create_loan` reverts
    "offer not signed by lender". This proves the renamed branch is reached and its
    return value is honored (not blindly trusted)."""
    lender_contract = boa.loads(EIP1271_MOCK_SRC, False)  # valid=False -> returns 0x00000000
    kyc_lender = kyc_for(lender_contract.address, kyc_validator_contract.address)

    usdc.mint(lender_contract.address, 10**12)
    usdc.approve(p2p_usdc_weth.address, 1000 * 10**6, sender=lender_contract.address)

    principal = 1000 * 10**6
    offer = _base_offer(now, lender_contract.address, borrower, usdc, weth, oracle, principal)
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)


# ============== 5. EIP-7702-delegated EOA lender (the root-cause scenario) ==============


def test_create_loan_7702_delegated_eoa_lender_validates_via_plain_signature(
    p2p_usdc_weth, borrower, now, lender, lender_key, kyc_borrower, kyc_lender, usdc, weth, oracle
):
    """The exact bug the fix addresses. A smart-wallet EOA with an EIP-7702 delegation
    HAS code, so `lender.is_contract` is true — yet it still signs offers with its own
    key. The old code (`if is_contract: ERC-1271 else: ecrecover`) treated it as a pure
    contract and routed to ERC-1271, ignoring the perfectly valid ECDSA signature.

    We reproduce the delegation with `set_code`: the key-controlled `lender` EOA is given
    the runtime code of a smart wallet whose `isValidSignature` returns a NON-magic value
    (so the ERC-1271 branch would REJECT this signature). Creation nevertheless SUCCEEDS —
    which is only possible via the fix's `if signer == lender: return True` plain-signature
    path, checked before the `is_contract` branch. On the pre-fix code this reverts
    "offer not signed by lender".
    """
    principal = 1000 * 10**6
    offer = _base_offer(now, lender, borrower, usdc, weth, oracle, principal)
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    # EIP-7702: delegate the lender EOA to a "smart wallet" whose isValidSignature does
    # NOT validate this signature (empty storage -> valid=False -> non-magic). The EOA now
    # has code (is_contract == true) but keeps its signing key.
    delegate = boa.loads(EIP1271_MOCK_SRC, False)
    boa.env.set_code(lender, boa.env.get_code(delegate.address))
    assert len(boa.env.get_code(lender)) > 0  # precondition: the lender EOA now has code
    assert staticcall_is_valid_returns_non_magic(lender)  # precondition: ERC-1271 path would reject

    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)
    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)

    # Succeeds via the plain-signature path despite the ERC-1271 delegate rejecting it.
    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    assert loan_id != ZERO_BYTES32
    assert p2p_usdc_weth.loans(loan_id) != ZERO_BYTES32


def staticcall_is_valid_returns_non_magic(addr) -> bool:
    """The delegated EOA's isValidSignature returns a non-magic value (proving that, had
    validation taken the ERC-1271 branch, it would have rejected the offer)."""
    signer = boa.loads_abi(
        '[{"name":"isValidSignature","inputs":[{"type":"bytes32"},{"type":"bytes"}],'
        '"outputs":[{"type":"bytes4"}],"stateMutability":"view","type":"function"}]'
    ).at(addr)
    return signer.isValidSignature(ZERO_BYTES32, b"\x00" * 65) != bytes.fromhex("1626ba7e")
