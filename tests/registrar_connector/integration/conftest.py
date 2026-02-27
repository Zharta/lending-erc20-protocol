import json
import os
import tempfile

import boa
import pytest
from boa.environment import Env
from eth_account import Account
from eth_utils import keccak

# OPERATOR_ROLE = keccak(b"OPERATOR_ROLE")
TRUST_ROLE_TRANSFER_AGENT = 8

# OZ_ACCESS_CONTROL_ABI = [
#     {
#         "inputs": [{"name": "role", "type": "bytes32"}, {"name": "account", "type": "address"}],
#         "name": "hasRole",
#         "outputs": [{"name": "", "type": "bool"}],
#         "stateMutability": "view",
#         "type": "function",
#     },
#     {
#         "inputs": [{"name": "role", "type": "bytes32"}, {"name": "account", "type": "address"}],
#         "name": "grantRole",
#         "outputs": [],
#         "stateMutability": "nonpayable",
#         "type": "function",
#     },
# ]


@pytest.fixture
def boa_env():
    new_env = Env()
    with boa.swap_env(new_env):
        fork_uri = os.environ["BOA_FORK_RPC_URL"]
        blkid = 24541820
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
def kyc_validator_account():
    return Account.create()


@pytest.fixture
def kyc_validator(kyc_validator_account, boa_env):
    boa.env.set_balance(kyc_validator_account.address, 10**21)
    return kyc_validator_account.address


@pytest.fixture(scope="session")
def transfer_agent():
    return boa.env.generate_address("transfer_agent")


@pytest.fixture(scope="session")
def securitize_redemption_wallet():
    return boa.env.generate_address("securitize_redemption_wallet")


# Securitize infrastructure on chain


@pytest.fixture
def securitize_owner():
    return "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"


@pytest.fixture
def securitize_trust_service(boa_env, securitize_owner):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeTrustService_abi.json")
    return contract_def.at("0xc397436742eAF7C325DDBFc4dc63D95822b27101")


# Real VaultRegistrar on chain


@pytest.fixture
def vault_registrar(boa_env):
    contract_def = boa.load_abi("contracts/auxiliary/VaultRegistrar_abi.json")
    return contract_def.at("0x9fbF77D74337FefA7D8993f507A38EDB4df620E5")


@pytest.fixture
def vault_registrar_admin():
    return "0xd69fefe5df62373dcbde3e1f9625cf334a2dae78"


# @pytest.fixture
# def vault_registrar_access_control(boa_env):
#     contract_def = boa.loads_abi(json.dumps(OZ_ACCESS_CONTROL_ABI))
#     return contract_def.at("0x9fbF77D74337FefA7D8993f507A38EDB4df620E5")


@pytest.fixture
def whitelisted_borrower(boa_env):
    return "0x81aF1E160c290E8Fff6381CCF67981f012Cf1009"


@pytest.fixture(scope="session")
def weth9_contract_def():
    return boa.load_partial("contracts/auxiliary/WETH9Mock.vy")


@pytest.fixture(scope="session")
def oracle_contract_def():
    return boa.load_partial("contracts/auxiliary/OracleMock.vy")


@pytest.fixture(scope="session")
def kyc_validator_contract_def():
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def vault_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVault.vy")


@pytest.fixture(scope="session")
def securitize_vault_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVaultSecuritize.vy")


@pytest.fixture(scope="session")
def p2p_lending_vaulted_erc20_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVaultedErc20.vy")


@pytest.fixture(scope="session")
def p2p_lending_vaulted_refinance_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVaultedRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_vaulted_liquidation_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingVaultedLiquidation.vy")


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
def connector_def():
    return boa.load_partial("contracts/SecuritizeRegistrarV1Connector.vy")


# Deploy fresh contracts on fork


@pytest.fixture
def usdc(weth9_contract_def, owner):
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


@pytest.fixture
def weth(weth9_contract_def, owner):
    return weth9_contract_def.deploy("Wrapped Ether", "WETH", 18, 10**20)


@pytest.fixture
def oracle(oracle_contract_def):
    rate = 387780390000
    decimals = 8
    return oracle_contract_def.deploy(decimals, rate)


@pytest.fixture
def kyc_validator_contract(kyc_validator_contract_def, kyc_validator):
    return kyc_validator_contract_def.deploy(kyc_validator)


@pytest.fixture
def p2p_vaulted_refinance(p2p_lending_vaulted_refinance_contract_def):
    return p2p_lending_vaulted_refinance_contract_def.deploy()


@pytest.fixture
def p2p_vaulted_liquidation(p2p_lending_vaulted_liquidation_contract_def):
    return p2p_lending_vaulted_liquidation_contract_def.deploy()


@pytest.fixture
def vault_impl(vault_contract_def):
    return vault_contract_def.deploy()


@pytest.fixture
def p2p_vaulted(
    p2p_lending_vaulted_erc20_contract_def,
    p2p_vaulted_refinance,
    p2p_vaulted_liquidation,
    vault_impl,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_vaulted_erc20_contract_def.deploy(
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
        0,
        p2p_vaulted_refinance.address,
        p2p_vaulted_liquidation.address,
        vault_impl.address,
        transfer_agent,
    )


@pytest.fixture
def p2p_securitize_refinance(p2p_lending_securitize_refinance_contract_def):
    return p2p_lending_securitize_refinance_contract_def.deploy()


@pytest.fixture
def p2p_securitize_liquidation(p2p_lending_securitize_liquidation_contract_def):
    return p2p_lending_securitize_liquidation_contract_def.deploy()


@pytest.fixture
def securitize_vault_impl(securitize_vault_contract_def):
    return securitize_vault_contract_def.deploy()


@pytest.fixture
def p2p_securitize(
    p2p_lending_securitize_erc20_contract_def,
    p2p_securitize_refinance,
    p2p_securitize_liquidation,
    securitize_vault_impl,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    owner,
    transfer_agent,
    securitize_redemption_wallet,
):
    return p2p_lending_securitize_erc20_contract_def.deploy(
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
        0,
        p2p_securitize_refinance.address,
        p2p_securitize_liquidation.address,
        securitize_vault_impl.address,
        transfer_agent,
        securitize_redemption_wallet,
    )


@pytest.fixture
def connector(
    connector_def,
    vault_registrar,
    vault_registrar_admin,
    p2p_vaulted,
    p2p_securitize,
    owner,
    securitize_trust_service,
    securitize_owner,
):
    contract = connector_def.deploy(vault_registrar.address, [p2p_vaulted.address, p2p_securitize.address])

    vault_registrar.grantRole(vault_registrar.OPERATOR_ROLE(), contract.address, sender=vault_registrar_admin)

    securitize_trust_service.addOperator("zharta_connector", contract.address, sender=securitize_owner)
    assert securitize_trust_service.getEntityByOperator(contract.address) == "zharta_connector"

    # securitize_trust_service.addEntity("zharta_connector", securitize_owner, sender=securitize_owner)
    # securitize_trust_service.addResource("zharta_connector", vault_registrar.address, sender=securitize_owner)
    securitize_trust_service.setRole(vault_registrar.address, TRUST_ROLE_TRANSFER_AGENT, sender=securitize_owner)
    return contract


# @pytest.fixture
# def connector(
#     connector_def,
#     vault_registrar,
#     vault_registrar_admin,
#     vault_registrar_access_control,
#     p2p_vaulted,
#     p2p_securitize,
#     owner,
#     securitize_trust_service,
#     securitize_owner,
# ):
#     contract = connector_def.deploy(
#         vault_registrar.address,
#         [p2p_vaulted.address, p2p_securitize.address],
#     )

#     # Grant OPERATOR_ROLE on VaultRegistrar so the connector can call registerVault
#     boa.env.set_balance(vault_registrar_admin, 10**21)
#     vault_registrar_access_control.grantRole(
#         OPERATOR_ROLE, contract.address, sender=vault_registrar_admin
#     )

#     # Add connector as operator on the Securitize Trust Service
#     securitize_trust_service.addOperator(
#         "zharta_connector", contract.address, sender=securitize_owner
#     )
#     assert securitize_trust_service.getEntityByOperator(contract.address) == "zharta_connector"
#     # assert securitize_trust_service.getRole(contract.address) == "X"

#     # Set up trust for VaultRegistrar in the Securitize Trust Service.
#     # The registrar needs TRANSFER_AGENT trust level to auto-register vault wallets
#     # via addWallet on the Securitize Registry Service.
#     securitize_trust_service.addEntity(
#         "zharta_connector", securitize_owner, sender=securitize_owner
#     )
#     securitize_trust_service.addResource(
#         "zharta_connector", vault_registrar.address, sender=securitize_owner
#     )
#     securitize_trust_service.setRole(
#         vault_registrar.address, TRUST_ROLE_TRANSFER_AGENT, sender=securitize_owner
#     )

#     return contract
