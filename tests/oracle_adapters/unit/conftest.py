from textwrap import dedent

import boa
import pytest


@pytest.fixture(scope="session", autouse=True)
def boa_env():
    boa.interpret.set_cache_dir(cache_dir=".cache/titanoboa")
    return boa


# Contract definitions


@pytest.fixture(scope="session")
def xprism_oracle_adapter_contract_def(boa_env):
    return boa.load_partial("contracts/xPrismOracleAdapter.vy")


@pytest.fixture(scope="session")
def oracle_mock_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/OracleMock.vy")


@pytest.fixture(scope="session")
def erc4626_mock_contract_def(boa_env):
    # Minimal ERC-4626 mock exposing convertToAssets.
    # `rate` is the value returned for convertToAssets(1e18), i.e. the assets-per-share
    # scaled to 1e18 shares. convertToAssets(shares) = shares * rate // 1e18, so that
    # convertToAssets(1e18) == rate exactly.
    return boa.loads_partial(
        dedent(
            """
            # @version 0.4.3

            rate: public(uint256)

            @deploy
            def __init__(_rate: uint256):
                self.rate = _rate

            @external
            def set_rate(_rate: uint256):
                self.rate = _rate

            @external
            @view
            def convertToAssets(shares: uint256) -> uint256:
                return shares * self.rate // 10 ** 18
            """
        ),
        name="ERC4626Mock",
    )
