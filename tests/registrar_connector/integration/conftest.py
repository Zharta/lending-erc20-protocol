import os
from pathlib import Path
from textwrap import dedent

import boa
import pytest
from boa.environment import Env
from eth_account import Account

from tests.p2p_erc20_securitize.conftest_base import sign_kyc, sign_register_vault  # noqa: F401

# ---------------------------------------------------------------------------
# Securitize mainnet addresses (ACRED fund)
# ---------------------------------------------------------------------------
DS_TOKEN = "0x17418038ecF73BA4026c4f428547BF099706F27B"  # ACRED DS Token (collateral)
# Holder of the issuer role - can register investors and issue tokens.
TOKEN_ISSUER = "0x1ffD2C4373A0CBee33f974e4142611C8c4A4f366"
# Securitize owner: admin allowed to add operators on the registrar and grant trust roles.
SECURITIZE_OWNER = "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"

TRUST_ROLE_TRANSFER_AGENT = 8


# ---------------------------------------------------------------------------
# Fork / accounts
# ---------------------------------------------------------------------------
@pytest.fixture
def boa_env():
    new_env = Env()
    with boa.swap_env(new_env):
        fork_uri = os.environ["BOA_FORK_RPC_URL"]
        boa.env.fork(fork_uri, block_identifier=25300898)
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
def now():
    return boa.eval("block.timestamp")


# ---------------------------------------------------------------------------
# Securitize on-chain contracts (forked) + investor registration
# ---------------------------------------------------------------------------
@pytest.fixture
def token_issuer(boa_env):
    boa.env.set_balance(TOKEN_ISSUER, 10**21)
    return TOKEN_ISSUER


@pytest.fixture(scope="session")
def ds_token_contract_def():
    return boa.load_abi("contracts/auxiliary/SecuritizeDSToken_abi.json")


@pytest.fixture
def acred_ds_token(ds_token_contract_def, boa_env):
    return ds_token_contract_def.at(DS_TOKEN)


@pytest.fixture
def acred(erc20_contract_def, boa_env):
    # ERC20 view of the DS token (balanceOf/approve/transferFrom)
    return erc20_contract_def.at(DS_TOKEN)


@pytest.fixture
def securitize_registry(boa_env):
    return boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json").at(
        "0x3A8E9CD2E17E1F2904b7f745Da29C9cA765Cc319"
    )


@pytest.fixture
def securitize_trust_service(boa_env):
    return boa.load_abi("contracts/auxiliary/SecuritizeTrustService_abi.json").at("0xc397436742eAF7C325DDBFc4dc63D95822b27101")


@pytest.fixture(autouse=True)
def register_borrower_investor(securitize_registry, acred_ds_token, borrower, token_issuer):
    """Register the borrower as a Securitize investor and issue collateral DS tokens."""
    investor_id = "zharta_test_investor"
    securitize_registry.registerInvestor(investor_id, "", sender=token_issuer)
    securitize_registry.setCountry(investor_id, "US", sender=token_issuer)
    securitize_registry.addWallet(borrower, investor_id, sender=token_issuer)
    acred_ds_token.issueTokens(borrower, 200 * int(1e6), sender=token_issuer)
    return investor_id


# ---------------------------------------------------------------------------
# Mock payment token + oracle (deployed in-fork)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def weth9_mock_contract_def():
    return boa.load_partial("contracts/auxiliary/WETH9Mock.vy")


@pytest.fixture(scope="session")
def oracle_mock_contract_def():
    return boa.load_partial("contracts/auxiliary/OracleMock.vy")


@pytest.fixture
def usdc(weth9_mock_contract_def, owner, lender):
    token = weth9_mock_contract_def.deploy("USD Coin", "USDC", 6, int(1e13))
    token.transfer(lender, int(1e12), sender=owner)
    return token


@pytest.fixture
def oracle_acred_usd(oracle_mock_contract_def, owner):
    # decimals=8, rate ~ $1 collateral price (DS token is a stable credit token)
    return oracle_mock_contract_def.deploy(8, 100000000)


# ---------------------------------------------------------------------------
# Protocol KYC validator
# ---------------------------------------------------------------------------
@pytest.fixture
def kyc_validator_contract(kyc_validator_contract_def, kyc_validator):
    return kyc_validator_contract_def.deploy(kyc_validator)


@pytest.fixture
def kyc_for(kyc_validator_key, now):
    def sign_func(wallet, verifier, expiration=None):
        return sign_kyc(wallet, expiration or now, kyc_validator_key, verifier)

    return sign_func


# ---------------------------------------------------------------------------
# Securitize P2P lending stack
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def p2p_lending_securitize_erc20_contract_def():
    # workaround: boa doesn't catch 'unused' events and fails, so inject a dummy logger
    contents = Path("contracts/v1/P2PLendingSecuritizeErc20.vy").read_text(encoding="utf-8")
    contents += dedent("""
        @external
        def log_stuff():
            log LoanLiquidated(
                id=empty(bytes32), borrower=empty(address), lender=empty(address), liquidator=empty(address),
                outstanding_debt=0, collateral_for_debt=0, remaining_collateral=0, remaining_collateral_value=0,
                shortfall=0, liquidation_fee=0, protocol_settlement_fee_amount=0)
            log LoanPartiallyLiquidated(
                id=empty(bytes32), borrower=empty(address), lender=empty(address), written_off=0,
                collateral_claimed=0, liquidation_fee=0, updated_amount=0, updated_collateral_amount=0,
                updated_accrual_start_time=0, liquidator=empty(address), old_ltv=0, new_ltv=0)
            log LoanReplaced(
                id=empty(bytes32), amount=0, apr=0, maturity=0, start_time=0, borrower=empty(address),
                lender=empty(address), collateral_amount=0, min_collateral_amount=0, call_eligibility=0,
                call_window=0, liquidation_ltv=0, initial_ltv=0, origination_fee_amount=0,
                protocol_upfront_fee_amount=0, protocol_settlement_fee=0, partial_liquidation_fee=0,
                full_liquidation_fee=0, offer_id=empty(bytes32), offer_tracing_id=empty(bytes32),
                original_loan_id=empty(bytes32), paid_principal=0, paid_interest=0,
                paid_protocol_settlement_fee_amount=0)
            log LoanReplacedByLender(
                id=empty(bytes32), amount=0, apr=0, maturity=0, start_time=0, borrower=empty(address),
                lender=empty(address), collateral_amount=0, min_collateral_amount=0, call_eligibility=0,
                call_window=0, liquidation_ltv=0, initial_ltv=0, origination_fee_amount=0,
                protocol_upfront_fee_amount=0, protocol_settlement_fee=0, partial_liquidation_fee=0,
                full_liquidation_fee=0, offer_id=empty(bytes32), offer_tracing_id=empty(bytes32),
                original_loan_id=empty(bytes32), paid_principal=0, paid_interest=0,
                paid_protocol_settlement_fee_amount=0)
            log LoanMaturityExtended(
                loan_id=empty(bytes32), original_maturity=0, new_maturity=0, lender=empty(address),
                borrower=empty(address), caller=empty(address))
            log LoanBorrowerTransferred(
                loan_id=empty(bytes32), new_loan_id=empty(bytes32), old_borrower=empty(address),
                new_borrower=empty(address), lender=empty(address), vault_id=0)
    """)
    return boa.loads_partial(contents, name="P2PLendingSecuritizeErc20")


@pytest.fixture
def p2p_sec_refinance(p2p_lending_securitize_refinance_contract_def):
    return p2p_lending_securitize_refinance_contract_def.deploy()


@pytest.fixture
def p2p_sec_liquidation(p2p_lending_securitize_liquidation_contract_def):
    return p2p_lending_securitize_liquidation_contract_def.deploy()


@pytest.fixture
def securitize_vault_impl(securitize_vault_contract_def):
    return securitize_vault_contract_def.deploy()


# ---------------------------------------------------------------------------
# V2 registrar connector
# ---------------------------------------------------------------------------
@pytest.fixture
def vault_registrar(boa_env):
    return boa.load_abi("contracts/auxiliary/VaultRegistrarV2_abi.json").at("0xD280bcA62a7FC67011cAef77815e8606071BEf9F")


@pytest.fixture
def securitize_owner(boa_env):
    # Admin allowed to add operators on the registrar and grant trust roles.
    boa.env.set_balance(SECURITIZE_OWNER, 10**21)
    return SECURITIZE_OWNER


@pytest.fixture(scope="session")
def v2_connector_def():
    return boa.load_partial("contracts/SecuritizeRegistrarV2Connector.vy")


@pytest.fixture
def registrar_connector(v2_connector_def, vault_registrar, securitize_trust_service, securitize_owner, owner):
    assert boa.env.eoa == owner
    connector = v2_connector_def.deploy(vault_registrar.address)
    vault_registrar.addOperator(connector.address, sender=securitize_owner)
    # The registrar needs the TRANSFER_AGENT trust role to register vaults in the registry.
    securitize_trust_service.setRole(vault_registrar.address, TRUST_ROLE_TRANSFER_AGENT, sender=securitize_owner)
    return connector


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
    securitize_redemption_wallet,
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
        securitize_redemption_wallet,
        registrar_connector.address,
    )
    registrar_connector.change_authorized_contract(contract.address, True, sender=owner)
    return contract
