from hashlib import sha3_256
from textwrap import dedent

import boa
import pytest

# from ...conftest_base import CollectionContract


@pytest.fixture
def usdc(weth9_contract_def, owner):
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


@pytest.fixture
def weth(weth9_contract_def, owner):
    return weth9_contract_def.deploy("WETH", "WETH", 18, 10**20)


@pytest.fixture
def oracle(oracle_contract_def):
    rate = 387780390000
    decimals = 8
    return oracle_contract_def.deploy(decimals, rate)


@pytest.fixture
def kyc_validator_contract(kyc_validator_contract_def, kyc_validator):
    return kyc_validator_contract_def.deploy(kyc_validator)


@pytest.fixture
def p2p_refinance(p2p_lending_refinance_contract_def):
    return p2p_lending_refinance_contract_def.deploy()


@pytest.fixture
def vault_impl(vault_contract_def):
    return vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_weth(
    p2p_lending_erc20_contract_def, p2p_refinance, usdc, weth, oracle, kyc_validator_contract, vault_impl, owner
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        weth,
        oracle,
        False,
        kyc_validator_contract,
        0,
        0,
        owner,
        10000,
        10000,
        0,
        p2p_refinance.address,
        vault_impl.address,
    )


@pytest.fixture
def now():
    return boa.eval("block.timestamp")
