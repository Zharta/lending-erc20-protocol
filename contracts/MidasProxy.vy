# @version 0.4.3

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.v1 import P2PLendingVaultMidas as vault
from contracts.v1 import P2PLendingMultiVaultErc20
from contracts.v1 import P2PLendingMultiVaultBase as base

FLASH_LOAN_CALLBACK_SIZE: constant(uint256) = 10240
FLASH_LOAN_MAX_TOKENS: constant(uint256) = 1


struct AggregatorV3LatestRoundData:
    roundId: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80

interface AggregatorV3Interface:
    def decimals() -> uint8: view
    def latestRoundData() -> AggregatorV3LatestRoundData: view

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
    deposit_vault: address
    collateral_to_buy: uint256
    collateral_max_spend: uint256
    payment_token: address
    borrower: address

    offer: base.SignedOffer
    principal: uint256
    collateral_amount: uint256
    borrower_kyc: base.SignedWalletValidation
    lender_kyc: base.SignedWalletValidation


event LeveragedLoanCreated:
    loan_id: bytes32
    p2p_lending_erc20: address
    principal: uint256
    loan_collateral_amount: uint256
    aquired_collateral: uint256
    max_collateral_buy_value: uint256
    flash_loan_amount: uint256


BPS: constant(uint256) = 10000

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

    assert msg.sender == flash_lender, "unauthorized"
    assert fee_amounts[0] == 0, "fee not supported"

    callback_data: CallbackData = abi_decode(data, CallbackData)

    payment_token: address = staticcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).payment_token()
    collateral_token: address = staticcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).collateral_token()
    assert tokens[0] == payment_token, "Invalid asset"

    assert (staticcall IERC20(payment_token).balanceOf(self)) >= amounts[0], "Insufficient balance"

    assert callback_data.collateral_max_spend <= amounts[0], "Insufficient flash loan amount"

    assert staticcall IERC20(payment_token).balanceOf(self) >= callback_data.collateral_max_spend, "Insufficient balance for swap"

    borrower_vault: address = staticcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).wallet_to_vault(callback_data.borrower)
    extcall IERC20(payment_token).approve(borrower_vault, callback_data.collateral_max_spend)
    if not borrower_vault.is_contract:
        extcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).create_vault_if_needed(callback_data.borrower)
    extcall vault.__at__(borrower_vault).buy(payment_token, callback_data.deposit_vault, callback_data.collateral_to_buy, callback_data.collateral_max_spend)

    loan_id: bytes32 = self._create_loan(
        callback_data.offer,
        callback_data.principal,
        callback_data.collateral_amount,
        callback_data.borrower_kyc,
        callback_data.lender_kyc,
    )

    assert (staticcall IERC20(payment_token).balanceOf(callback_data.borrower)) >= amounts[0], "Insufficient balance"
    extcall IERC20(payment_token).transferFrom(callback_data.borrower, flash_lender, amounts[0])

    log LeveragedLoanCreated(
        loan_id = loan_id,
        p2p_lending_erc20 = p2p_lending_erc20,
        principal = callback_data.principal,
        loan_collateral_amount = callback_data.collateral_amount,
        aquired_collateral = callback_data.collateral_to_buy,
        max_collateral_buy_value = callback_data.collateral_max_spend,
        flash_loan_amount = amounts[0]
    )



@internal
def _create_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:
    return extcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).create_loan(
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
    collateral_max_spend: uint256,
    oracle_addr: address,
    deposit_vault: address
):

    payment_token: address = staticcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).payment_token()
    collateral_token: address = staticcall P2PLendingMultiVaultErc20.__at__(p2p_lending_erc20).collateral_token()
    rate_numerator: uint256 = 0
    rate_denominator: uint256 = 0
    (rate_numerator, rate_denominator) = self._get_oracle_rate(oracle_addr)

    payment_decimals: uint256 = convert(staticcall IERC20Detailed(payment_token).decimals(), uint256)
    collateral_decimals: uint256 = convert(staticcall IERC20Detailed(collateral_token).decimals(), uint256)
    expected_collateral_swap_value: uint256 = collateral_to_buy * rate_numerator * 10**payment_decimals // (rate_denominator * 10**collateral_decimals)
    assert expected_collateral_swap_value <= collateral_max_spend, "max spend too low"

    callback_data: CallbackData = CallbackData(
        deposit_vault = deposit_vault,
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


@view
@internal
def _get_oracle_rate(oracle_addr: address) -> (uint256, uint256):
    return convert((staticcall AggregatorV3Interface(oracle_addr).latestRoundData()).answer, uint256), 10 ** convert(staticcall AggregatorV3Interface(oracle_addr).decimals(), uint256)
