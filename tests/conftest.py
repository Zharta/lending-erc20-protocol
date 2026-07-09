from textwrap import dedent

import boa
import pytest
from eth_account import Account


@pytest.fixture(scope="session")
def owner_account():
    return Account.create()


# Common contract definition fixtures shared across integration test suites.
# Unit tests override these with mock implementations in their own conftest files.


@pytest.fixture(scope="session")
def erc20_contract_def():
    return boa.load_abi("tests/stubs/USDC_abi.json")


@pytest.fixture(scope="session")
def weth9_contract_def():
    return boa.load_abi("tests/stubs/WETH9_abi.json")


@pytest.fixture(scope="session")
def oracle_contract_def():
    return boa.load_abi("tests/stubs/ChainlinkAggregator_abi.json")


@pytest.fixture(scope="session")
def kyc_validator_contract_def():
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def erc721_contract_def():
    return boa.load_partial("contracts/auxiliary/ERC721.vy")


@pytest.fixture(scope="session")
def vault_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVault.vy")


@pytest.fixture(scope="session")
def sc_wallet_contract_def():
    return boa.load_partial("tests/stubs/SCWallet.vy")


@pytest.fixture(scope="session")
def p2p_lending_securitize_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingSecuritizeErc20.vy")


@pytest.fixture(scope="session")
def p2p_lending_securitize_refinance_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingSecuritizeRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_securitize_liquidation_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingSecuritizeLiquidation.vy")


@pytest.fixture(scope="session")
def securitize_vault_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVaultSecuritize.vy")


@pytest.fixture(scope="session")
def vault_registrar_mock_contract_def():
    return boa.load_partial("contracts/auxiliary/VaultRegistrarV2Mock.vy")


@pytest.fixture(scope="session")
def securitize_proxy_contract_def():
    return boa.load_partial("contracts/SecuritizeProxy.vy")


@pytest.fixture(scope="module")
def empty_contract_def():
    return boa.loads_partial(
        dedent(
            """
        dummy: uint256
     """
        )
    )


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False, help="run slow tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
