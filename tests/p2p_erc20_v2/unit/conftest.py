from hashlib import sha3_256
from pathlib import Path
from textwrap import dedent

import boa
import pytest
from eth_account import Account

from ..conftest_base import sign_kyc


@pytest.fixture(scope="session", autouse=True)
def boa_env():
    boa.interpret.set_cache_dir(cache_dir=".cache/titanoboa")
    return boa


@pytest.fixture(scope="session")
def accounts(boa_env):
    _accounts = [boa.env.generate_address() for _ in range(10)]
    for account in _accounts:
        boa.env.set_balance(account, 10**21)
    return _accounts


@pytest.fixture(scope="session")
def owner_account():
    return Account.create()


@pytest.fixture(scope="session")
def owner(owner_account, boa_env):
    boa.env.eoa = owner_account.address
    boa.env.set_balance(owner_account.address, 10**21)
    return owner_account.address


@pytest.fixture(scope="session")
def owner_key(owner_account):
    return owner_account.key


@pytest.fixture(scope="session")
def borrower_account():
    return Account.create()


@pytest.fixture(scope="session")
def borrower(borrower_account, boa_env):
    boa.env.set_balance(borrower_account.address, 10**21)
    return borrower_account.address


@pytest.fixture(scope="session")
def borrower_key(borrower_account):
    return borrower_account.key


@pytest.fixture(scope="session")
def lender_account():
    return Account.create()


@pytest.fixture(scope="session")
def lender(lender_account, boa_env):
    boa.env.set_balance(lender_account.address, 10**21)
    return lender_account.address


@pytest.fixture(scope="session")
def lender_key(lender_account):
    return lender_account.key


@pytest.fixture(scope="session")
def lender2_account():
    return Account.create()


@pytest.fixture(scope="session")
def lender2(lender2_account, boa_env):
    boa.env.set_balance(lender2_account.address, 10**21)
    return lender2_account.address


@pytest.fixture(scope="session")
def lender2_key(lender2_account):
    return lender2_account.key


@pytest.fixture(scope="session")
def kyc_validator_account():
    return Account.create()


@pytest.fixture(scope="session")
def kyc_validator(kyc_validator_account, boa_env):
    boa.env.set_balance(kyc_validator_account.address, 10**21)
    return kyc_validator_account.address


@pytest.fixture(scope="session")
def kyc_validator_key(kyc_validator_account):
    return kyc_validator_account.key


@pytest.fixture(scope="session")
def protocol_wallet(accounts):
    yield accounts[3]


@pytest.fixture(scope="session")
def transfer_agent():
    return boa.env.generate_address("transfer_agent")


@pytest.fixture(scope="session")
def erc721_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/ERC721.vy")


@pytest.fixture(scope="session")
def weth9_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/WETH9Mock.vy")


@pytest.fixture(scope="session")
def weth(weth9_contract_def, owner):
    return weth9_contract_def.deploy("Wrapped Ether", "WETH", 18, 10**20)


@pytest.fixture(scope="session")
def oracle_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/OracleMock.vy")


@pytest.fixture(scope="session")
def p2p_lending_refinance_contract_def(boa_env):
    return boa.load_partial("contracts/v2/P2PLendingV2Refinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_liquidation_contract_def(boa_env):
    return boa.load_partial("contracts/v2/P2PLendingV2Liquidation.vy")


@pytest.fixture(scope="session")
def p2p_lending_erc20_contract_def(boa_env):
    # return boa.load_partial("contracts/v2/P2PLendingV2Erc20.vy")

    # workaround: boa doesnt catch 'unused' events and fails, so we inject a dummy function that logs them
    contents = Path("contracts/v2/P2PLendingV2Erc20.vy").read_text(encoding="utf-8")
    contents += dedent("""
        @external
        def log_stuff():
            log LoanLiquidated(
                id=empty(bytes32),
                borrower=empty(address),
                lender=empty(address),
                liquidator=empty(address),
                outstanding_debt=0,
                collateral_for_debt=0,
                remaining_collateral=0,
                remaining_collateral_value=0,
                shortfall=0,
                liquidation_fee=0,
                protocol_settlement_fee_amount=0
            )
            log LoanPartiallyLiquidated(
                id=empty(bytes32),
                borrower=empty(address),
                lender=empty(address),
                written_off=0,
                collateral_claimed=0,
                liquidation_fee=0,
                updated_amount=0,
                updated_collateral_amount=0,
                updated_accrual_start_time=0,
                liquidator=empty(address),
                old_ltv=0,
                new_ltv=0
            )
            log LoanReplaced(
                id=empty(bytes32),
                amount=0,
                apr=0,
                maturity=0,
                start_time=0,
                borrower=empty(address),
                lender=empty(address),
                collateral_amount=0,
                min_collateral_amount=0,
                call_eligibility=0,
                call_window=0,
                liquidation_ltv=0,
                initial_ltv=0,
                origination_fee_amount=0,
                protocol_upfront_fee_amount=0,
                protocol_settlement_fee=0,
                partial_liquidation_fee=0,
                full_liquidation_fee=0,
                offer_id=empty(bytes32),
                offer_tracing_id=empty(bytes32),
                original_loan_id=empty(bytes32),
                paid_principal=0,
                paid_interest=0,
                paid_protocol_settlement_fee_amount=0
            )
            log LoanReplacedByLender(
                id=empty(bytes32),
                amount=0,
                apr=0,
                maturity=0,
                start_time=0,
                borrower=empty(address),
                lender=empty(address),
                collateral_amount=0,
                min_collateral_amount=0,
                call_eligibility=0,
                call_window=0,
                liquidation_ltv=0,
                initial_ltv=0,
                origination_fee_amount=0,
                protocol_upfront_fee_amount=0,
                protocol_settlement_fee=0,
                partial_liquidation_fee=0,
                full_liquidation_fee=0,
                offer_id=empty(bytes32),
                offer_tracing_id=empty(bytes32),
                original_loan_id=empty(bytes32),
                paid_principal=0,
                paid_interest=0,
                paid_protocol_settlement_fee_amount=0
            )

    """)
    return boa.loads_partial(contents, name="P2PLendingV2Erc20")


@pytest.fixture(scope="session")
def kyc_validator_contract_def(boa_env):
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def p2p_lending_erc20_proxy_contract_def(boa_env):
    return boa.load_partial("tests/stubs/P2PV2Erc20Proxy.vy")


@pytest.fixture(scope="session")
def sc_wallet_contract_def(boa_env):
    return boa.load_partial("tests/stubs/SCWallet.vy")


@pytest.fixture
def now():
    return boa.eval("block.timestamp")


@pytest.fixture
def kyc_for(kyc_validator_contract_def, kyc_validator_key, now):
    def sign_func(wallet, verifier):
        return sign_kyc(wallet, now, kyc_validator_key, verifier)

    return sign_func


@pytest.fixture(scope="module")
def empty_contract_def(boa_env):
    return boa.loads_partial(
        dedent(
            """
        dummy: uint256
     """
        )
    )


@pytest.fixture
def usdc(weth9_contract_def, owner):
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


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
def p2p_liquidation(p2p_lending_liquidation_contract_def):
    return p2p_lending_liquidation_contract_def.deploy()


@pytest.fixture(scope="session")
def vault_contract_def():
    return boa.load_partial("contracts/v2/P2PLendingV2Vault.vy")


@pytest.fixture
def vault_impl(vault_contract_def):
    return vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_weth(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    vault_impl,
    owner,
    transfer_agent,
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
        0,
        p2p_refinance.address,
        p2p_liquidation.address,
        vault_impl.address,
        transfer_agent,
    )


def inject_events_workaround(filename) -> str:
    contents = Path(filename).read_text(encoding="utf-8")
    contents.append(
        dedent("""
        @external
        def log_stuff():
            log LoanLiquidated(
                id=empty(bytes32),
                borrower=empty(address),
                lender=empty(address),
                liquidator=empty(address),
                outstanding_debt=0,
                collateral_for_debt=0,
                remaining_collateral=0,
                remaining_collateral_value=0,
                shortfall=0,
                liquidation_fee=0,
                protocol_settlement_fee_amount=0
            )
            log LoanPartiallyLiquidated(
                id=empty(bytes32),
                borrower=empty(address),
                lender=empty(address),
                written_off=0,
                collateral_claimed=0,
                liquidation_fee=0,
                updated_amount=0,
                updated_collateral_amount=0,
                updated_accrual_start_time=0,
                liquidator=empty(address),
                old_ltv=0,
                new_ltv=0
            )
    """)
    )
    return contents
