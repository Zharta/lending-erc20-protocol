# @version 0.4.3

decimals: public(uint8)
rate: public(int256)
owner: public(address)


struct AggregatorV3LatestRoundData:
    roundId: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80

@deploy
def __init__(_decimals: uint8, _rate: int256):
    self.decimals = _decimals
    self.rate = _rate
    self.owner = msg.sender


@external
def set_rate(_rate: int256):
    assert msg.sender == self.owner
    self.rate = _rate


@external
@view
def latestRoundData() -> AggregatorV3LatestRoundData:
    return AggregatorV3LatestRoundData(
        roundId=0,
        answer= self.rate,
        startedAt=block.timestamp,
        updatedAt=block.timestamp,
        answeredInRound=0
    )
