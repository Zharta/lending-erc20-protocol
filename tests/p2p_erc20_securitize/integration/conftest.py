import os

import boa
import pytest
from boa.environment import Env
from eth_account import Account

from ...conftest_base import ETH_FORK_BLOCK, build_erc20_contract_def_with_log_stuff
from ..conftest_base import sign_kyc

# Securitize mainnet addresses (ACRED fund)
DS_TOKEN = "0x17418038ecF73BA4026c4f428547BF099706F27B"  # ACRED DS Token (collateral)
# Holder of the issuer role - can register investors and issue tokens.
TOKEN_ISSUER = "0x1ffD2C4373A0CBee33f974e4142611C8c4A4f366"
# Securitize owner: admin allowed to add operators on the registrar and grant trust roles.
SECURITIZE_OWNER = "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"

TRUST_ROLE_TRANSFER_AGENT = 8


@pytest.fixture
def boa_env():
    new_env = Env()
    with boa.swap_env(new_env):
        fork_uri = os.environ["BOA_FORK_RPC_URL"]
        boa.env.fork(fork_uri, block_identifier=ETH_FORK_BLOCK)
        yield


@pytest.fixture
def accounts(boa_env):
    _accounts = [boa.env.generate_address() for _ in range(10)]
    for account in _accounts:
        boa.env.set_balance(account, 10**21)
    return _accounts


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


# Borrower is a freshly generated account whose key we control, so it can both
# produce the EIP-712 investor signature and be registered as a Securitize investor.
@pytest.fixture(scope="session")
def borrower_account():
    return Account.create()


@pytest.fixture(scope="session")
def borrower_key(borrower_account):
    return borrower_account.key


@pytest.fixture
def borrower(borrower_account, boa_env):
    boa.env.set_balance(borrower_account.address, 10**21)
    return borrower_account.address


@pytest.fixture
def token_issuer(boa_env):
    boa.env.set_balance(TOKEN_ISSUER, 10**21)
    return TOKEN_ISSUER


@pytest.fixture(autouse=True)
def borrower_acred_funds(borrower, securitize_registry, acred_ds_token, token_issuer):
    """Register the borrower as a Securitize investor and issue collateral DS tokens.

    A freshly generated account is not pre-registered on-chain, so the investor
    must be registered before the VaultRegistrar can create vaults for it.
    """
    investor_id = "zharta_test_investor"
    securitize_registry.registerInvestor(investor_id, "", sender=token_issuer)
    securitize_registry.setCountry(investor_id, "US", sender=token_issuer)
    securitize_registry.addWallet(borrower, investor_id, sender=token_issuer)
    acred_ds_token.issueTokens(borrower, 200 * int(1e6), sender=token_issuer)
    return investor_id


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


@pytest.fixture
def weth(weth9_contract_def, owner, accounts):
    weth = weth9_contract_def.at("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    holder = "0xF04a5cC80B1E94C69B48f5ee68a08CD2F09A7c3E"
    with boa.env.prank(holder):
        for account in accounts:
            weth.transfer(account, 10**21, sender=holder)
    weth.transfer(owner, 10**21, sender=holder)
    return weth


@pytest.fixture(scope="session")
def ds_token_contract_def():
    return boa.load_abi("contracts/auxiliary/SecuritizeDSToken_abi.json")


@pytest.fixture
def acred(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x17418038ecF73BA4026c4f428547BF099706F27B")


@pytest.fixture
def acred_ds_token(ds_token_contract_def, boa_env):
    return ds_token_contract_def.at("0x17418038ecF73BA4026c4f428547BF099706F27B")


@pytest.fixture
def usdc(owner, accounts, erc20_contract_def):
    erc20 = erc20_contract_def.at("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
    holder = "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1"
    with boa.env.prank(holder):
        for account in accounts:
            erc20.transfer(account, 10**12, sender=holder)
    erc20.transfer(owner, 10**12, sender=holder)
    return erc20


@pytest.fixture
def oracle_usdc_eth(oracle_contract_def, owner):
    return oracle_contract_def.at("0x986b5E1e1755e3C2440e960477f25201B0a8bbD4")


@pytest.fixture
def oracle_acred_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0xD6BcbbC87bFb6c8964dDc73DC3EaE6d08865d51C")


@pytest.fixture
def redemption_wallet(accounts, usdc):
    wallet = "0xbb543C77436645C8b95B64eEc39E3C0d48D4842b"
    usdc.transfer(wallet, int(1e12), sender=accounts[0])
    return wallet


@pytest.fixture
def securitize_owner(boa_env):
    # Admin allowed to add operators on the registrar and grant trust roles.
    boa.env.set_balance(SECURITIZE_OWNER, 10**21)
    return SECURITIZE_OWNER


@pytest.fixture
def securitize_registry(boa_env):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json")
    return contract_def.at("0x3A8E9CD2E17E1F2904b7f745Da29C9cA765Cc319")


@pytest.fixture(scope="session")
def p2p_lending_securitize_base_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingSecuritizeBase.vy")


@pytest.fixture(scope="session")
def p2p_lending_securitize_erc20_contract_def(
    p2p_lending_securitize_base_contract_def,
    p2p_lending_securitize_refinance_contract_def,
    p2p_lending_securitize_liquidation_contract_def,
):
    # workaround: boa doesnt catch 'unused' events and fails, so we inject a generated dummy that logs them
    return build_erc20_contract_def_with_log_stuff(
        "contracts/v1/P2PLendingSecuritizeErc20.vy",
        "P2PLendingSecuritizeErc20",
        p2p_lending_securitize_base_contract_def,
        [
            p2p_lending_securitize_refinance_contract_def,
            p2p_lending_securitize_liquidation_contract_def,
        ],
    )


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
        boa.eval("empty(address)"),  # vault_registrar_addr
    )


@pytest.fixture
def securitize_trust_service(boa_env):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeTrustService_abi.json")
    return contract_def.at("0xc397436742eAF7C325DDBFc4dc63D95822b27101")


@pytest.fixture(scope="session")
def vault_registrar_contract_def():
    return boa.load_abi("contracts/auxiliary/VaultRegistrarV2_abi.json")


@pytest.fixture
def vault_registrar(vault_registrar_contract_def, boa_env):
    return vault_registrar_contract_def.at("0xD280bcA62a7FC67011cAef77815e8606071BEf9F")


@pytest.fixture(scope="session")
def registrar_connector_def():
    return boa.load_partial("contracts/SecuritizeRegistrarV2Connector.vy")


@pytest.fixture
def registrar_connector(
    registrar_connector_def,
    vault_registrar,
    securitize_trust_service,
    securitize_owner,
    owner,
):
    assert boa.env.eoa == owner
    contract = registrar_connector_def.deploy(vault_registrar.address)
    vault_registrar.addOperator(contract.address, sender=securitize_owner)
    # The registrar needs the TRANSFER_AGENT trust role to register vaults in the registry.
    securitize_trust_service.setRole(vault_registrar.address, TRUST_ROLE_TRANSFER_AGENT, sender=securitize_owner)
    return contract


@pytest.fixture
def p2p_usdc_acred(
    p2p_lending_securitize_erc20_contract_def,
    p2p_sec_refinance,
    p2p_sec_liquidation,
    securitize_vault_impl,
    usdc,
    acred,
    oracle_acred_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
    redemption_wallet,
    registrar_connector,
):
    contract = p2p_lending_securitize_erc20_contract_def.deploy(
        usdc,
        acred,
        oracle_acred_usd,
        False,  # oracle_reverse
        kyc_validator_contract,
        0,
        0,
        owner,
        10000,
        10000,
        0,
        0,
        p2p_sec_refinance.address,
        p2p_sec_liquidation.address,
        securitize_vault_impl.address,
        transfer_agent,
        redemption_wallet,
        registrar_connector.address,
    )
    registrar_connector.change_authorized_contract(contract.address, True, sender=owner)
    return contract
