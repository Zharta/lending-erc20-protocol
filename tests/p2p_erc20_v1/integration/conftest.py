import os
from datetime import datetime as dt
from hashlib import sha3_256
from pathlib import Path
from textwrap import dedent

import boa
import pytest
from boa.environment import Env
from boa.vm.py_evm import register_raw_precompile
from eth_account import Account
from web3 import Web3

from ..conftest_base import ZERO_ADDRESS, get_last_event, sign_kyc


@pytest.fixture
def boa_env():
    new_env = Env()
    with boa.swap_env(new_env):
        fork_uri = os.environ["BOA_FORK_RPC_URL"]
        blkid = 23628063
        boa.env.fork(fork_uri, block_identifier=blkid)
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


@pytest.fixture
def oracle_usdc_eth(oracle_contract_def, owner):
    return oracle_contract_def.at("0x986b5E1e1755e3C2440e960477f25201B0a8bbD4")


@pytest.fixture(scope="session")
def p2p_lending_erc20_contract_def():
    # workaround: boa doesnt catch 'unused' events and fails, so we inject a dummy function that logs them
    contents = Path("contracts/v1/P2PLendingErc20.vy").read_text(encoding="utf-8")
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
    return boa.loads_partial(contents, name="P2PLendingErc20")


@pytest.fixture(scope="session")
def p2p_lending_refinance_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_liquidation_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingLiquidation.vy")


@pytest.fixture(scope="session")
def p2p_lending_erc20_proxy_contract_def():
    return boa.load_partial("tests/stubs/P2PErc20Proxy.vy")


@pytest.fixture
def now():
    return boa.eval("block.timestamp")


@pytest.fixture
def kyc_for(kyc_validator_contract_def, kyc_validator_key, now):
    def sign_func(wallet, verifier, expiration=now):
        return sign_kyc(wallet, expiration, kyc_validator_key, verifier)

    return sign_func


@pytest.fixture
def kyc_validator_contract(kyc_validator_contract_def, kyc_validator):
    return kyc_validator_contract_def.deploy(kyc_validator)


@pytest.fixture
def p2p_refinance(p2p_lending_refinance_contract_def):
    return p2p_lending_refinance_contract_def.deploy()


@pytest.fixture
def p2p_liquidation(p2p_lending_liquidation_contract_def):
    return p2p_lending_liquidation_contract_def.deploy()


@pytest.fixture
def p2p_usdc_weth(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    usdc,
    weth,
    oracle_usdc_eth,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        weth,
        oracle_usdc_eth,
        True,
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
        transfer_agent,
    )
