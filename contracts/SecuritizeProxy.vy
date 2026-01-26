# @version 0.4.3

from ethereum.ercs import IERC20
from contracts.v1 import P2PLendingVaultSecuritize as vault
from contracts.v1 import P2PLendingSecuritizeErc20
from contracts.v1 import P2PLendingSecuritizeBase as base

FLASH_LOAN_CALLBACK_SIZE: constant(uint256) = 10240
FLASH_LOAN_MAX_TOKENS: constant(uint256) = 1


interface SecuritizeSwap:
    def calculateDsTokenAmount(_stableCoinAmount: uint256) -> (uint256, uint256): view
    def calculateStableCoinAmount(_dsTokenAmount: uint256) -> uint256: view
    def buy(_dsTokenAmount: uint256, _maxStableCoinAmount: uint256): nonpayable


interface SecuritizeDSToken:
    def getDSService(_serviceId: uint256) -> address: view


interface IFlashLender:
    def flashLoan(
        recepient: address,
        tokens: DynArray[address,FLASH_LOAN_MAX_TOKENS],
        amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS],
        data: Bytes[FLASH_LOAN_CALLBACK_SIZE]
    ): nonpayable


interface IFlashLoanRecipient:
    def receiveFlashLoan(
        tokens: DynArray[address,FLASH_LOAN_MAX_TOKENS],
        amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS],
        fee_amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS],
        data: Bytes[FLASH_LOAN_CALLBACK_SIZE]
    ): nonpayable


implements: IFlashLoanRecipient


struct CallbackData:
    securitize_swap_contract: address
    collateral_to_buy: uint256
    collateral_max_spend: uint256
    payment_token: address
    borrower: address

    offer: base.SignedOffer
    principal: uint256
    collateral_amount: uint256
    borrower_kyc: base.SignedWalletValidation
    lender_kyc: base.SignedWalletValidation

BPS: constant(uint256) = 10000
SEC_SWAP_SERVICE_ID: constant(uint256) = 1<<14

p2p_lending_erc20: public(immutable(address))
flash_lender: public(immutable(address))


@deploy
def __init__(_p2p_lending_erc20: address, _flash_lender: address):
    p2p_lending_erc20 = _p2p_lending_erc20
    flash_lender = _flash_lender


@external
def receiveFlashLoan(
    tokens: DynArray[address,FLASH_LOAN_MAX_TOKENS],
    amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS],
    fee_amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS],
    data: Bytes[FLASH_LOAN_CALLBACK_SIZE]
) :

    # raw_call(0x0000000000000000000000000000000000011111, abi_encode(b"callback"))
    assert msg.sender == flash_lender, "unauthorized"
    assert fee_amounts[0] == 0, "fee not supported"

    callback_data: CallbackData = abi_decode(data, CallbackData)

    payment_token: address = staticcall P2PLendingSecuritizeErc20.__at__(p2p_lending_erc20).payment_token()
    collateral_token: address = staticcall P2PLendingSecuritizeErc20.__at__(p2p_lending_erc20).collateral_token()
    assert tokens[0] == payment_token, "Invalid asset"

    assert (staticcall IERC20(payment_token).balanceOf(self)) >= amounts[0], "Insufficient balance"

    collateral_max_spend: uint256 = staticcall SecuritizeSwap(callback_data.securitize_swap_contract).calculateStableCoinAmount(callback_data.collateral_to_buy)
    assert collateral_max_spend <= amounts[0], "Insufficient flash loan amount"

    assert staticcall IERC20(payment_token).balanceOf(self) >= collateral_max_spend, "Insufficient balance for swap"

    borrower_vault: address = staticcall P2PLendingSecuritizeErc20.__at__(p2p_lending_erc20).wallet_to_vault(callback_data.borrower)
    extcall IERC20(payment_token).approve(borrower_vault, collateral_max_spend)
    if not borrower_vault.is_contract:
        extcall P2PLendingSecuritizeErc20.__at__(p2p_lending_erc20).create_vault_if_needed(callback_data.borrower)
    extcall vault.__at__(borrower_vault).buy(payment_token, callback_data.collateral_to_buy, collateral_max_spend)

    self._create_loan(
        callback_data.offer,
        callback_data.principal,
        callback_data.collateral_amount,
        callback_data.borrower_kyc,
        callback_data.lender_kyc,
    )

    assert (staticcall IERC20(payment_token).balanceOf(callback_data.borrower)) >= amounts[0], "Insufficient balance"
    extcall IERC20(payment_token).transferFrom(callback_data.borrower, flash_lender, amounts[0])



@internal
def _create_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:
    return extcall P2PLendingSecuritizeErc20.__at__(p2p_lending_erc20).create_loan(
        offer,
        principal,
        collateral_amount,
        borrower_kyc,
        lender_kyc
    )


@external
def create_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation,
    collateral_to_buy: uint256,
    collateral_max_spend: uint256
):

    # raw_call(0x0000000000000000000000000000000000011111, abi_encode(b"refinance"))

    payment_token: address = staticcall P2PLendingSecuritizeErc20.__at__(p2p_lending_erc20).payment_token()
    callback_data: CallbackData = CallbackData(
        securitize_swap_contract = staticcall SecuritizeDSToken(offer.offer.collateral_token).getDSService(SEC_SWAP_SERVICE_ID),
        collateral_to_buy = collateral_to_buy,
        collateral_max_spend = collateral_max_spend,
        payment_token = payment_token,
        borrower = msg.sender,
        offer = offer,
        principal = principal,
        collateral_amount = collateral_amount,
        borrower_kyc = borrower_kyc,
        lender_kyc = lender_kyc,
    )

    extcall IFlashLender(flash_lender).flashLoan(
        self,
        [payment_token],
        [collateral_max_spend],
        abi_encode(callback_data)
    )
