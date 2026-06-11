import os
from pathlib import Path
from textwrap import dedent

import boa
import pytest
from boa.environment import Env
from eth_account import Account
from eth_account.messages import encode_typed_data

from tests.p2p_erc20_securitize.conftest_base import sign_kyc

# ---------------------------------------------------------------------------
# Securitize Sepolia testnet addresses (https://labs.securitize.io)
# ---------------------------------------------------------------------------
DS_TOKEN = "0xE52c3eAf88138762E24916F25124Ab7bE0c9817a"  # Securitize DS Token (collateral)
VAULT_REGISTRAR_V2 = "0x8D7aee4813432C19209c2CBBb3095c71384c1d43"  # VaultRegistrar V2
REGISTRY_SERVICE = "0xdAE984876F612F5505710268EB901644985e0aEe"  # Securitize registry service
# Holder of the DS token MASTER/issuer role - can register investors and issue tokens.
DS_MASTER = "0x3A8A0baC3481C452de5d53946c73De4980c8C668"

# The registrar's EIP-712 domain separator is baked in at its real deployment on
# Sepolia, so signatures must use the real Sepolia chain id. titanoboa exposes the
# forked chain id through the `chain.id` opcode (even though boa.env.evm.chain.chain_id
# reports the local default of 1).


# ---------------------------------------------------------------------------
# EIP-712 RegisterVault signing helper (matches SecuritizeRegistrarV2Connector)
# ---------------------------------------------------------------------------
def sign_register_vault(account, connector_address, vault_registrar, deadline, investor_address=None):
    investor = investor_address or account.address
    structured_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "RegisterVault": [
                {"name": "investor", "type": "address"},
                {"name": "operator", "type": "address"},
                {"name": "token", "type": "address"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "RegisterVault",
        "domain": {
            "name": "VaultRegistrar",
            "version": "1",
            "chainId": boa.eval("chain.id"),
            "verifyingContract": vault_registrar.address,
        },
        "message": {
            "investor": investor,
            "operator": connector_address,
            "token": vault_registrar.token(),
            "nonce": vault_registrar.operatorNonce(investor, connector_address),
            "deadline": deadline,
        },
    }
    signed = account.sign_message(encode_typed_data(full_message=structured_data))
    return signed.v, signed.r, signed.s


# ---------------------------------------------------------------------------
# Fork / accounts
# ---------------------------------------------------------------------------
@pytest.fixture
def boa_env():
    new_env = Env()
    with boa.swap_env(new_env):
        fork_uri = os.environ["BOA_SEPOLIA_FORK_RPC_URL"]
        boa.env.fork(fork_uri)
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
def ds_master(boa_env):
    boa.env.set_balance(DS_MASTER, 10**21)
    return DS_MASTER


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
    return boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json").at(REGISTRY_SERVICE)


@pytest.fixture(autouse=True)
def register_borrower_investor(securitize_registry, acred_ds_token, borrower, ds_master):
    """Register the borrower as a Securitize investor and issue collateral DS tokens."""
    investor_id = "zharta_test_investor"
    securitize_registry.registerInvestor(investor_id, "", sender=ds_master)
    securitize_registry.setCountry(investor_id, "US", sender=ds_master)
    securitize_registry.addWallet(borrower, investor_id, sender=ds_master)
    acred_ds_token.issueTokens(borrower, 200 * int(1e6), sender=ds_master)
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
    return boa.load_abi("contracts/auxiliary/VaultRegistrarV2_abi.json").at(VAULT_REGISTRAR_V2)


@pytest.fixture
def securitize_owner(accounts):
    # On Sepolia any wallet may register itself/an operator on the registrar.
    return accounts[4]


@pytest.fixture(scope="session")
def v2_connector_def():
    return boa.load_partial("contracts/SecuritizeRegistrarV2Connector.vy")


@pytest.fixture
def registrar_connector(v2_connector_def, vault_registrar, securitize_owner, owner):
    assert boa.env.eoa == owner
    connector = v2_connector_def.deploy(vault_registrar.address)
    vault_registrar.addOperator(connector.address, sender=securitize_owner)
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
