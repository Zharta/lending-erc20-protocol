# @version 0.4.3

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

interface SecuritizeSwap:
    def calculateDsTokenAmount(_stableCoinAmount: uint256) -> (uint256, uint256, uint256): view
    def swap(_liquidityAmount: uint256, _minOutAmount: uint256): nonpayable


interface SecuritizeDSToken:
    def getDSService(_serviceId: uint256) -> address: view


struct AggregatorV3LatestRoundData:
    roundId: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80

interface AggregatorV3Interface:
    def decimals() -> uint8: view
    def latestRoundData() -> AggregatorV3LatestRoundData: view

implements: IERC20
implements: IERC20Detailed
implements: SecuritizeDSToken
implements: SecuritizeSwap

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Deposit:
    wallet: indexed(address)
    value: uint256

event Withdrawal:
    wallet: indexed(address)
    value: uint256

SEC_SWAP_SERVICE_ID: constant(uint256) = 1<<14

name: public(constant(String[41])) = "Apollo Diversified Credit Securitize Fund"
symbol: public(constant(String[5])) = "ACRED"
decimals: public(constant(uint8)) = 6

balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)
minter: address
oracle_addr: public(address)
stable_coin_addr: public(address)

blacklisted: public(HashMap[address, bool])

@deploy
def __init__(_supply: uint256, oracle_addr: address, stable_coin_addr: address):
    init_supply: uint256 = _supply * 10 ** convert(decimals, uint256)
    self.balanceOf[msg.sender] = init_supply
    self.totalSupply = init_supply
    self.minter = msg.sender
    self.oracle_addr = oracle_addr
    self.stable_coin_addr = stable_coin_addr
    log Transfer(sender=empty(address), receiver=msg.sender, value=init_supply)



@external
def transfer(_to : address, _value : uint256) -> bool:
    """
    @dev Transfer token for a specified address
    @param _to The address to transfer to.
    @param _value The amount to be transferred.
    """
    assert not self.blacklisted[msg.sender]
    assert not self.blacklisted[_to]

    self.balanceOf[msg.sender] -= _value
    self.balanceOf[_to] += _value
    log Transfer(sender=msg.sender, receiver=_to, value=_value)
    return True


@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    """
     @dev Transfer tokens from one address to another.
     @param _from address The address which you want to send tokens from
     @param _to address The address which you want to transfer to
     @param _value uint256 the amount of tokens to be transferred
    """
    assert not self.blacklisted[_from]
    assert not self.blacklisted[_to]

    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value
    self.allowance[_from][msg.sender] -= _value
    log Transfer(sender=_from, receiver=_to, value=_value)
    return True


@external
def approve(_spender : address, _value : uint256) -> bool:
    """
    @dev Approve the passed address to spend the specified amount of tokens on behalf of msg.sender.
         Beware that changing an allowance with this method brings the risk that someone may use both the old
         and the new allowance by unfortunate transaction ordering. One possible solution to mitigate this
         race condition is to first reduce the spender's allowance to 0 and set the desired value afterwards:
         https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729
    @param _spender The address which will spend the funds.
    @param _value The amount of tokens to be spent.
    """
    self.allowance[msg.sender][_spender] = _value
    log Approval(owner=msg.sender, spender=_spender, value=_value)
    return True


@external
def mint(_to: address, _value: uint256):
    """
    @dev Mint an amount of the token and assigns it to an account.
         This encapsulates the modification of balances such that the
         proper events are emitted.
    @param _to The account that will receive the created tokens.
    @param _value The amount that will be created.
    """
    assert msg.sender == self.minter
    assert _to != empty(address)
    self.totalSupply += _value
    self.balanceOf[_to] += _value
    log Transfer(sender=empty(address), receiver=_to, value=_value)


@internal
def _burn(_to: address, _value: uint256):
    """
    @dev Internal function that burns an amount of the token of a given
         account.
    @param _to The account whose tokens will be burned.
    @param _value The amount that will be burned.
    """
    assert _to != empty(address)
    self.totalSupply -= _value
    self.balanceOf[_to] -= _value
    log Transfer(sender=_to, receiver=empty(address), value=_value)


@external
def burn(_value: uint256):
    """
    @dev Burn an amount of the token of msg.sender.
    @param _value The amount that will be burned.
    """
    self._burn(msg.sender, _value)


@external
def burnFrom(_to: address, _value: uint256):
    """
    @dev Burn an amount of the token from a given account.
    @param _to The account whose tokens will be burned.
    @param _value The amount that will be burned.
    """
    self.allowance[_to][msg.sender] -= _value
    self._burn(_to, _value)


@external
@payable
def deposit():
    self.balanceOf[msg.sender] += msg.value
    log Deposit(wallet=msg.sender, value=msg.value)

@external
def withdraw(amount: uint256):
    assert self.balanceOf[msg.sender] >= amount
    self.balanceOf[msg.sender] -= amount
    send(msg.sender, amount)
    log Withdrawal(wallet=msg.sender, value=amount)

@external
def blacklist(_address: address, _value: bool):
    assert msg.sender == self.minter
    self.blacklisted[_address] = _value

@external
@view
def getDSService(_serviceId: uint256) -> address:
    if _serviceId == SEC_SWAP_SERVICE_ID:
        return self
    return empty(address)

@external
@view
def calculateDsTokenAmount(_stableCoinAmount: uint256) -> (uint256, uint256, uint256):
    numerator: uint256 = 0
    denominator: uint256 = 0
    (numerator, denominator) = self._get_rate()
    amount: uint256 = _stableCoinAmount * denominator // numerator
    return amount, numerator, 0

@external
def swap(liquidityAmount: uint256, minOutAmount: uint256):
    numerator: uint256 = 0
    denominator: uint256 = 0
    (numerator, denominator) = self._get_rate()
    _dsTokenAmount: uint256 = liquidityAmount * numerator // denominator
    _liquidityAmount: uint256 = _dsTokenAmount * denominator // numerator
    assert _dsTokenAmount >= minOutAmount, "insufficient output amount"

    extcall IERC20(self.stable_coin_addr).transferFrom(msg.sender, self, _liquidityAmount)

    self.totalSupply += _dsTokenAmount
    self.balanceOf[msg.sender] += _dsTokenAmount
    log Transfer(sender=empty(address), receiver=msg.sender, value=_dsTokenAmount)

@internal
@view
def _get_rate() -> (uint256, uint256):
    return convert((staticcall AggregatorV3Interface(self.oracle_addr).latestRoundData()).answer, uint256), 10 ** convert(staticcall AggregatorV3Interface(self.oracle_addr).decimals(), uint256)
