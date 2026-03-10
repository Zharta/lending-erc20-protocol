# @version 0.4.3

owner: public(address)

FLASH_LOAN_CALLBACK_SIZE: constant(uint256) = 10240
FLASH_LOAN_MAX_TOKENS: constant(uint256) = 1

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

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


implements: IFlashLender


@deploy
def __init__():
    self.owner = msg.sender


@external
def flashLoan(
    recepient: address,
    tokens: DynArray[address,FLASH_LOAN_MAX_TOKENS],
    amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS],
    data: Bytes[FLASH_LOAN_CALLBACK_SIZE]
):
    fee_amounts: DynArray[uint256,FLASH_LOAN_MAX_TOKENS] = []

    pre_loan_balances: DynArray[uint256,FLASH_LOAN_MAX_TOKENS] = []

    for i: uint256 in range(len(tokens), bound=FLASH_LOAN_MAX_TOKENS):
        pre_loan_balances.append(staticcall IERC20(tokens[i]).balanceOf(self))
        assert pre_loan_balances[i] >= amounts[i], "insufficient balance"
        extcall IERC20(tokens[i]).transfer(recepient, amounts[i])
        fee_amounts.append(0)

    extcall IFlashLoanRecipient(recepient).receiveFlashLoan(tokens, amounts, fee_amounts, data)

    for i: uint256 in range(len(tokens), bound=FLASH_LOAN_MAX_TOKENS):
        assert staticcall IERC20(tokens[i]).balanceOf(self) >= pre_loan_balances[i], "invalid post loan balance"
