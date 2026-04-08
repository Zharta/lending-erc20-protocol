# @version 0.4.3

"""
@title CentrifugeOracleAdapter
@author [Zharta](https://zharta.io/)
@notice Adapts Centrifuge Spoke price feeds to the Chainlink AggregatorV3 interface.
        Wraps Spoke.pricePoolPerShare() (D18, in pool currency) into latestRoundData()
"""

struct AggregatorV3LatestRoundData:
    roundId: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80

struct PriceMarkers:
    computedAt: uint64
    maxAge: uint64
    validUntil: uint64

interface CentrifugeSpoke:
    def shareTokenDetails(shareToken: address) -> (uint64, bytes16): view
    def pricePoolPerShare(poolId: uint64, scId: bytes16, checkValidity: bool) -> uint128: view
    def markersPricePoolPerShare(poolId: uint64, scId: bytes16) -> PriceMarkers: view

decimals: public(constant(uint8)) = 18

spoke: public(immutable(address))
asset: public(immutable(address))

@deploy
def __init__(_spoke: address, _asset: address):
    spoke = _spoke
    asset = _asset


@external
@view
def latestRoundData() -> AggregatorV3LatestRoundData:
    poolId: uint64 = empty(uint64)
    scId: bytes16 = empty(bytes16)

    poolId, scId = staticcall CentrifugeSpoke(spoke).shareTokenDetails(asset)
    assert poolId != empty(uint64), "unknown asset"

    price: uint128 = staticcall CentrifugeSpoke(spoke).pricePoolPerShare(poolId, scId, True)

    return AggregatorV3LatestRoundData(
        roundId=0,
        answer=convert(price, int256),
        startedAt=0,
        updatedAt=0,
        answeredInRound=0
    )
