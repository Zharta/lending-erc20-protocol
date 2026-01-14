# @version 0.4.3

from ethereum.ercs import IERC165
from ethereum.ercs import IERC721
from ethereum.ercs import IERC20


from contracts.v1 import P2PLendingVaultedBase as base

interface P2PLendingVaultedErc20:
    def create_loan(
        offer: base.SignedOffer,
        principal: uint256,
        collateral_amount: uint256,
        borrower_kyc: base.SignedWalletValidation,
        lender_kyc: base.SignedWalletValidation
    ) -> bytes32: nonpayable
    def replace_loan(
        loan: base.Loan,
        offer: base.SignedOffer,
        principal: uint256,
        collateral_amount: uint256,
        lender_kyc: base.SignedWalletValidation
    ) -> bytes32: nonpayable
    def settle_loan(loan: base.Loan): nonpayable
    def revoke_offer(offer: base.SignedOffer): nonpayable
    def partially_liquidate_loan(loan: base.Loan): nonpayable
    def liquidate_loan(loan: base.Loan): nonpayable
    def call_loan(loan: base.Loan): nonpayable
    def add_collateral_to_loan(loan: base.Loan, collateral_amount: uint256): nonpayable
    def remove_collateral_from_loan(loan: base.Loan, collateral_amount: uint256): nonpayable



BPS: constant(uint256) = 10000

p2p_lending_erc20: address

@deploy
def __init__(_p2p_lending_erc20: address):
    self.p2p_lending_erc20 = _p2p_lending_erc20

@external
def create_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:
    return extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).create_loan(offer, principal, collateral_amount, borrower_kyc, lender_kyc)

@external
def replace_loan(
    loan: base.Loan,
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:
    return extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).replace_loan(loan, offer, principal, collateral_amount, lender_kyc)

@external
def settle_loan(loan: base.Loan):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).settle_loan(loan)

@external
def revoke_offer(offer: base.SignedOffer):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).revoke_offer(offer)

@external
def partially_liquidate_loan(loan: base.Loan):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).partially_liquidate_loan(loan)


@external
def liquidate_loan(loan: base.Loan):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).liquidate_loan(loan)


@external
def call_loan(loan: base.Loan):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).call_loan(loan)


@external
def add_collateral_to_loan(loan: base.Loan, collateral_amount: uint256):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).add_collateral_to_loan(loan, collateral_amount)


@external
def remove_collateral_from_loan(loan: base.Loan, collateral_amount: uint256):
    extcall P2PLendingVaultedErc20(self.p2p_lending_erc20).remove_collateral_from_loan(loan, collateral_amount)
