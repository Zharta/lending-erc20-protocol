import os
from textwrap import dedent

import boa
import pytest
from boa.environment import Env
from eth_account import Account

from ..conftest_base import sign_kyc


@pytest.fixture
def boa_env():
    new_env = Env()
    with boa.swap_env(new_env):
        fork_uri = os.environ["BOA_FORK_RPC_URL"]
        blkid = 24325853
        boa.env.fork(fork_uri, block_identifier=blkid)
        yield


@pytest.fixture
def accounts(boa_env):
    _accounts = [boa.env.generate_address() for _ in range(10)]
    for account in _accounts:
        boa.env.set_balance(account, 10**21)
    return _accounts


@pytest.fixture(scope="session")
def owner_account():
    return Account.create()


@pytest.fixture
def owner(owner_account, boa_env):
    boa.env.eoa = owner_account.address
    boa.env.set_balance(owner_account.address, 10**21)
    return owner_account.address


@pytest.fixture(scope="session")
def owner_key(owner_account):
    return owner_account.key


@pytest.fixture(scope="session")
def kyc_validator_account():
    return Account.create()


@pytest.fixture
def kyc_validator(kyc_validator_account, boa_env):
    boa.env.set_balance(kyc_validator_account.address, 10**21)
    return kyc_validator_account.address


@pytest.fixture(scope="session")
def kyc_validator_key(kyc_validator_account):
    return kyc_validator_account.key


@pytest.fixture(scope="session")
def borrower_account():
    return Account.create()


@pytest.fixture
def borrower(borrower_account, boa_env):
    boa.env.set_balance(borrower_account.address, 10**21)
    return borrower_account.address


@pytest.fixture(scope="session")
def borrower_key(borrower_account):
    return borrower_account.key


@pytest.fixture(scope="session")
def lender_account():
    return Account.create()


@pytest.fixture
def lender(lender_account, boa_env):
    boa.env.set_balance(lender_account.address, 10**21)
    return lender_account.address


@pytest.fixture(scope="session")
def lender_key(lender_account):
    return lender_account.key


@pytest.fixture(scope="session")
def lender2_account():
    return Account.create()


@pytest.fixture
def lender2(lender2_account, boa_env):
    boa.env.set_balance(lender2_account.address, 10**21)
    return lender2_account.address


@pytest.fixture(scope="session")
def lender2_key(lender2_account):
    return lender2_account.key


@pytest.fixture
def protocol_wallet(accounts):
    yield accounts[3]


@pytest.fixture(scope="session")
def transfer_agent():
    return boa.env.generate_address("transfer_agent")


@pytest.fixture(scope="session")
def securitize_redemption_wallet():
    return boa.env.generate_address("securitize_redemption_wallet")


@pytest.fixture(scope="session")
def erc20_contract_def():
    return boa.load_abi("tests/stubs/USDC_abi.json")


@pytest.fixture(scope="session")
def weth9_contract_def():
    return boa.load_abi("tests/stubs/WETH9_abi.json")


@pytest.fixture
def weth(weth9_contract_def, owner, accounts):
    weth = weth9_contract_def.at("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    holder = "0xF04a5cC80B1E94C69B48f5ee68a08CD2F09A7c3E"
    with boa.env.prank(holder):
        for account in accounts:
            weth.transfer(account, 10**21, sender=holder)
    weth.transfer(owner, 10**21, sender=holder)
    return weth


@pytest.fixture
def usdc(owner, accounts, erc20_contract_def):
    erc20 = erc20_contract_def.at("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    holder = "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1"
    with boa.env.prank(holder):
        for account in accounts:
            erc20.transfer(account, 10**12, sender=holder)
    erc20.transfer(owner, 10**12, sender=holder)
    return erc20


@pytest.fixture(scope="session")
def oracle_contract_def():
    return boa.load_abi("tests/stubs/ChainlinkAggregator_abi.json")


@pytest.fixture
def oracle_usdc_eth(oracle_contract_def, owner):
    return oracle_contract_def.at("0x986b5E1e1755e3C2440e960477f25201B0a8bbD4")


@pytest.fixture(scope="session")
def p2p_lending_securitize_erc20_contract_def():
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
def kyc_validator_contract_def():
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def securitize_proxy_contract_def():
    return boa.load_partial("contracts/SecuritizeProxy.vy")


@pytest.fixture
def now():
    return boa.eval("block.timestamp")


@pytest.fixture
def kyc_for(kyc_validator_contract_def, kyc_validator_key, now):
    def sign_func(wallet, verifier, expiration=None):
        return sign_kyc(wallet, expiration or now, kyc_validator_key, verifier)

    return sign_func


@pytest.fixture
def kyc_validator_contract(kyc_validator_contract_def, kyc_validator):
    return kyc_validator_contract_def.deploy(kyc_validator)


@pytest.fixture
def p2p_sec_refinance(p2p_lending_securitize_refinance_contract_def):
    return p2p_lending_securitize_refinance_contract_def.deploy()


@pytest.fixture
def p2p_sec_liquidation(p2p_lending_securitize_liquidation_contract_def):
    return p2p_lending_securitize_liquidation_contract_def.deploy()


@pytest.fixture
def securitize_vault_impl(securitize_vault_contract_def):
    return securitize_vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_weth(
    p2p_lending_securitize_erc20_contract_def,
    p2p_sec_refinance,
    p2p_sec_liquidation,
    securitize_vault_impl,
    usdc,
    weth,
    oracle_usdc_eth,
    kyc_validator_contract,
    owner,
    transfer_agent,
    securitize_redemption_wallet,
):
    return p2p_lending_securitize_erc20_contract_def.deploy(
        usdc,  # payment_token
        weth,  # collateral_token
        oracle_usdc_eth,  # oracle_addr
        True,  # oracle_reverse (USDC/ETH oracle is reversed)
        kyc_validator_contract,  # kyc_validator_addr
        0,  # protocol_upfront_fee
        0,  # protocol_settlement_fee
        owner,  # protocol_wallet
        10000,  # max_protocol_upfront_fee
        10000,  # max_protocol_settlement_fee
        0,  # partial_liquidation_fee
        0,  # full_liquidation_fee
        p2p_sec_refinance.address,  # refinance_addr
        p2p_sec_liquidation.address,  # liquidation_addr
        securitize_vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        securitize_redemption_wallet,  # securitize_redemption_wallet
    )


@pytest.fixture
def empty_contract_def():
    return boa.loads_partial(
        dedent(
            """
        dummy: uint256
     """
        )
    )
