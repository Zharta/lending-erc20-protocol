import boa
import pytest

# Constants mirroring the contract.
D18 = 10**18
D8 = 10**8


def _expected_answer(convert_to_assets_rate, usdc_usd_answer, usdc_usd_feed_decimals):
    """Reimplements the integer formula from xPrismOracleAdapter.latestRoundData().

    xprism_prism = convertToAssets(1e18) == convert_to_assets_rate (by the mock's design).
    usdc_usd_feed_precision = 10 ** usdc_usd_feed_decimals
    answer = xprism_prism * usdc_usd_feed_precision * D8 // (D18 * usdc_usd_answer)
    """
    xprism_prism = convert_to_assets_rate
    usdc_usd_feed_precision = 10**usdc_usd_feed_decimals
    return xprism_prism * usdc_usd_feed_precision * D8 // (D18 * usdc_usd_answer)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def xprism_mock(erc4626_mock_contract_def):
    # Default rate: convertToAssets(1e18) == 1.53e18.
    return erc4626_mock_contract_def.deploy(1_530_000_000_000_000_000)


@pytest.fixture
def feed_mock(oracle_mock_contract_def):
    # USDC/USD feed: 8 decimals, answer 0.99976089e8.
    return oracle_mock_contract_def.deploy(8, 99_976_089)


@pytest.fixture
def adapter(xprism_oracle_adapter_contract_def, xprism_mock, feed_mock):
    return xprism_oracle_adapter_contract_def.deploy(xprism_mock.address, feed_mock.address)


# ============================================================
# Constructor / immutables
# ============================================================


def test_constructor_stores_xprism(adapter, xprism_mock):
    assert adapter.xprism() == xprism_mock.address


def test_constructor_stores_usdc_usd_feed(adapter, feed_mock):
    assert adapter.usdc_usd_feed() == feed_mock.address


def test_decimals_is_8(adapter):
    assert adapter.decimals() == 8


# ============================================================
# latestRoundData: answer computation
# ============================================================


def test_latest_round_data_nominal_answer(adapter, xprism_mock, feed_mock):
    convert_to_assets_rate = 1_530_000_000_000_000_000  # 1.53e18
    usdc_usd_answer = 99_976_089  # 0.99976089e8
    feed_decimals = 8

    # Preconditions: fixtures actually set up the values this test asserts against.
    assert xprism_mock.convertToAssets(D18) == convert_to_assets_rate
    assert feed_mock.latestRoundData().answer == usdc_usd_answer
    assert feed_mock.decimals() == feed_decimals

    expected = _expected_answer(convert_to_assets_rate, usdc_usd_answer, feed_decimals)

    # NOTE: the independently computed formula yields 153036592.
    # The value 153043274 mentioned as a "sanity cross-check" in the task prompt is
    # INCORRECT for these inputs (1.53e18 / 0.99976089 == 1.530365...e18, i.e. 153036592
    # at 8 decimals). We assert against the formula-derived value, not the bad magic number.
    assert expected == 153036592
    assert adapter.latestRoundData().answer == expected


def test_latest_round_data_unit_rate(adapter, xprism_mock, feed_mock):
    convert_to_assets_rate = D18  # 1e18 -> 1 PRISM per xPRISM
    usdc_usd_answer = D8  # 1e8 -> USDC/USD == 1.0
    feed_decimals = 8

    xprism_mock.set_rate(convert_to_assets_rate)
    feed_mock.set_rate(usdc_usd_answer, sender=feed_mock.owner())

    assert xprism_mock.convertToAssets(D18) == convert_to_assets_rate
    assert feed_mock.latestRoundData().answer == usdc_usd_answer

    expected = _expected_answer(convert_to_assets_rate, usdc_usd_answer, feed_decimals)
    assert expected == D8  # unit inputs -> 1.0 at 8 decimals
    assert adapter.latestRoundData().answer == expected


def test_latest_round_data_scales_linearly_with_4626_rate(adapter, xprism_mock, feed_mock):
    usdc_usd_answer = D8  # fixed USDC/USD == 1.0
    feed_decimals = 8
    feed_mock.set_rate(usdc_usd_answer, sender=feed_mock.owner())

    rate_1x = D18
    rate_2x = 2 * D18

    xprism_mock.set_rate(rate_1x)
    expected_1x = _expected_answer(rate_1x, usdc_usd_answer, feed_decimals)
    answer_1x = adapter.latestRoundData().answer
    assert answer_1x == expected_1x

    xprism_mock.set_rate(rate_2x)
    expected_2x = _expected_answer(rate_2x, usdc_usd_answer, feed_decimals)
    answer_2x = adapter.latestRoundData().answer
    assert answer_2x == expected_2x

    # Doubling the 4626 rate doubles the reported price.
    assert answer_2x == 2 * answer_1x


def test_latest_round_data_feed_with_18_decimals(oracle_mock_contract_def, xprism_oracle_adapter_contract_def, xprism_mock):
    # USDC/USD feed reporting with 18 decimals instead of 8.
    convert_to_assets_rate = 1_530_000_000_000_000_000  # 1.53e18
    usdc_usd_answer_18dec = 999_760_890_000_000_000  # 0.99976089e18
    feed_decimals = 18

    feed_18 = oracle_mock_contract_def.deploy(feed_decimals, usdc_usd_answer_18dec)
    adapter = xprism_oracle_adapter_contract_def.deploy(xprism_mock.address, feed_18.address)

    assert xprism_mock.convertToAssets(D18) == convert_to_assets_rate
    assert feed_18.decimals() == feed_decimals
    assert feed_18.latestRoundData().answer == usdc_usd_answer_18dec

    expected = _expected_answer(convert_to_assets_rate, usdc_usd_answer_18dec, feed_decimals)
    assert adapter.latestRoundData().answer == expected

    # Feed decimals cancel out: the 18-decimal answer must equal the 8-decimal answer
    # (0.99976089 expressed at either precision), up to integer truncation. Both round to
    # the same 8-decimal result for these inputs.
    usdc_usd_answer_8dec = 99_976_089
    expected_8dec = _expected_answer(convert_to_assets_rate, usdc_usd_answer_8dec, 8)
    assert expected == expected_8dec


# ============================================================
# latestRoundData: revert conditions
# ============================================================


def test_latest_round_data_reverts_if_usdc_usd_price_zero(adapter, feed_mock):
    feed_mock.set_rate(0, sender=feed_mock.owner())
    assert feed_mock.latestRoundData().answer == 0
    with boa.reverts("invalid usdc/usd price"):
        adapter.latestRoundData()


def test_latest_round_data_reverts_if_usdc_usd_price_negative(adapter, feed_mock):
    feed_mock.set_rate(-1, sender=feed_mock.owner())
    assert feed_mock.latestRoundData().answer == -1
    with boa.reverts("invalid usdc/usd price"):
        adapter.latestRoundData()


# ============================================================
# latestRoundData: struct shape (unused fields hardcoded to 0)
# ============================================================


def test_latest_round_data_round_id_zero(adapter):
    assert adapter.latestRoundData().roundId == 0


def test_latest_round_data_started_at_zero(adapter):
    assert adapter.latestRoundData().startedAt == 0


def test_latest_round_data_updated_at_zero(adapter):
    assert adapter.latestRoundData().updatedAt == 0


def test_latest_round_data_answered_in_round_zero(adapter):
    assert adapter.latestRoundData().answeredInRound == 0
