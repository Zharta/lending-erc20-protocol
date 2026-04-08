# @version 0.4.3

"""
@title xPrismOracleAdapter
@author [Zharta](https://zharta.io/)
@notice Adapts xPRISM pricing to the Chainlink AggregatorV3 interface.
        Derives xPRISM/USDC price from the chain:
        xPRISM -> PRISM (ERC-4626) -> USDO (1:1 peg) -> USD (cUSDO/USD feed) -> USDC (USDC/USD feed)
        Formula: xPRISM_USDC = xprism_prism * cusdo_usd * D8 / (cusdo_usdo * usdc_usd)
"""

struct AggregatorV3LatestRoundData:
    roundId: uint80
    answer: int256
    startedAt: uint256
    updatedAt: uint256
    answeredInRound: uint80

interface IERC4626:
    def convertToAssets(shares: uint256) -> uint256: view

interface AggregatorV3Interface:
    def decimals() -> uint8: view
    def latestRoundData() -> AggregatorV3LatestRoundData: view

decimals: public(constant(uint8)) = 8
D18: constant(uint256) = 10 ** 18
D8: constant(uint256) = 10 ** 8

xprism: public(immutable(address))
cusdo: public(immutable(address))
cusdo_usd_feed: public(immutable(address))
usdc_usd_feed: public(immutable(address))

@deploy
def __init__(_xprism: address, _cusdo: address, _cusdo_usd_feed: address, _usdc_usd_feed: address):
    xprism = _xprism
    cusdo = _cusdo
    cusdo_usd_feed = _cusdo_usd_feed
    usdc_usd_feed = _usdc_usd_feed


@external
@view
def latestRoundData() -> AggregatorV3LatestRoundData:
    xprism_prism: uint256 = staticcall IERC4626(xprism).convertToAssets(D18)
    cusdo_usdo: uint256 = staticcall IERC4626(cusdo).convertToAssets(D18)

    cusdo_usd_feed_precision: uint256 = 10 ** convert(staticcall AggregatorV3Interface(cusdo_usd_feed).decimals(), uint256)
    usdc_usd_feed_precision: uint256 = 10 ** convert(staticcall AggregatorV3Interface(usdc_usd_feed).decimals(), uint256)

    cusdo_usd_data: AggregatorV3LatestRoundData = staticcall AggregatorV3Interface(cusdo_usd_feed).latestRoundData()
    assert cusdo_usd_data.answer > 0, "invalid cusdo/usd price"
    cusdo_usd: uint256 = convert(cusdo_usd_data.answer, uint256)

    usdc_usd_data: AggregatorV3LatestRoundData = staticcall AggregatorV3Interface(usdc_usd_feed).latestRoundData()
    assert usdc_usd_data.answer > 0, "invalid usdc/usd price"
    usdc_usd: uint256 = convert(usdc_usd_data.answer, uint256)

    # xPRISM/USDC (D8) = xprism_prism * cusdo_usd * D8 / (cusdo_usdo * usdc_usd)
    answer: int256 = convert(
        xprism_prism * cusdo_usd * usdc_usd_feed_precision * D8 // (cusdo_usdo * usdc_usd * cusdo_usd_feed_precision),
        int256
    )

    return AggregatorV3LatestRoundData(
        roundId=0,
        answer=answer,
        startedAt=0,
        updatedAt=0,
        answeredInRound=0
    )
