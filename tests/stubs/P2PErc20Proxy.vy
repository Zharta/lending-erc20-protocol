# @version 0.4.3

from ethereum.ercs import IERC165
from ethereum.ercs import IERC721
from ethereum.ercs import IERC20


interface P2PLendingErc20:
    def create_loan(
        offer: SignedOffer,
        principal: uint256,
        collateral_amount: uint256,
        borrower_kyc: SignedWalletValidation,
        lender_kyc: SignedWalletValidation
    ) -> bytes32: nonpayable
    def replace_loan(
        loan: Loan,
        offer: SignedOffer,
        principal: uint256,
        collateral_amount: uint256,
        lender_kyc: SignedWalletValidation
    ) -> bytes32: nonpayable
    def settle_loan(loan: Loan): nonpayable
    def claim_defaulted_loan_collateral(loan: Loan): nonpayable
    def revoke_offer(offer: SignedOffer): nonpayable
    def soft_liquidate_loan(loan: Loan): nonpayable
    def call_loan(loan: Loan): nonpayable
    def add_collateral_to_loan(loan: Loan, collateral_amount: uint256): nonpayable
    def remove_collateral_from_loan(loan: Loan, collateral_amount: uint256): nonpayable



struct WalletValidation:
    wallet: address
    expiration_time: uint256

struct SignedWalletValidation:
    validation: WalletValidation
    signature: Signature

struct Offer:
    principal: uint256
    apr: uint256
    payment_token: address
    collateral_token: address
    duration: uint256
    origination_fee_amount: uint256

    min_collateral_amount: uint256
    max_iltv: uint256
    available_liquidity: uint256
    call_eligibility: uint256
    call_window: uint256
    soft_liquidation_ltv: uint256
    oracle_addr: address

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
    accrual_start_time: uint256
    borrower: address
    lender: address
    collateral_token: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    soft_liquidation_fee: uint256
    call_eligibility: uint256
    call_window: uint256
    soft_liquidation_ltv: uint256
    oracle_addr: address
    initial_ltv: uint256
    call_time: uint256

BPS: constant(uint256) = 10000

p2p_lending_erc20: address

@deploy
def __init__(_p2p_lending_erc20: address):
    self.p2p_lending_erc20 = _p2p_lending_erc20

@external
def create_loan(
    offer: SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: SignedWalletValidation,
    lender_kyc: SignedWalletValidation
) -> bytes32:
    return extcall P2PLendingErc20(self.p2p_lending_erc20).create_loan(offer, principal, collateral_amount, borrower_kyc, lender_kyc)

@external
def replace_loan(
    loan: Loan,
    offer: SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    lender_kyc: SignedWalletValidation
) -> bytes32:
    return extcall P2PLendingErc20(self.p2p_lending_erc20).replace_loan(loan, offer, principal, collateral_amount, lender_kyc)

@external
def settle_loan(loan: Loan):
    extcall P2PLendingErc20(self.p2p_lending_erc20).settle_loan(loan)

@external
def claim_defaulted_loan_collateral(loan: Loan):
    extcall P2PLendingErc20(self.p2p_lending_erc20).claim_defaulted_loan_collateral(loan)


@external
def revoke_offer(offer: SignedOffer):
    extcall P2PLendingErc20(self.p2p_lending_erc20).revoke_offer(offer)

@external
def soft_liquidate_loan(loan: Loan):
    extcall P2PLendingErc20(self.p2p_lending_erc20).soft_liquidate_loan(loan)


@external
def call_loan(loan: Loan):
    extcall P2PLendingErc20(self.p2p_lending_erc20).call_loan(loan)


@external
def add_collateral_to_loan(loan: Loan, collateral_amount: uint256):
    extcall P2PLendingErc20(self.p2p_lending_erc20).add_collateral_to_loan(loan, collateral_amount)


@external
def remove_collateral_from_loan(loan: Loan, collateral_amount: uint256):
    extcall P2PLendingErc20(self.p2p_lending_erc20).remove_collateral_from_loan(loan, collateral_amount)
