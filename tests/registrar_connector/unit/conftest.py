from pathlib import Path
from textwrap import dedent

import boa
import pytest
from eth_account import Account


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
def other_account():
    return Account.create()


@pytest.fixture(scope="session")
def other(other_account, boa_env):
    boa.env.set_balance(other_account.address, 10**21)
    return other_account.address


@pytest.fixture(scope="session")
def protocol_wallet(accounts):
    yield accounts[3]


@pytest.fixture(scope="session")
def transfer_agent():
    return boa.env.generate_address("transfer_agent")


@pytest.fixture(scope="session")
def securitize_redemption_wallet():
    return boa.env.generate_address("securitize_redemption_wallet")


@pytest.fixture(scope="session")
def kyc_validator_account():
    return Account.create()


@pytest.fixture(scope="session")
def kyc_validator(kyc_validator_account, boa_env):
    boa.env.set_balance(kyc_validator_account.address, 10**21)
    return kyc_validator_account.address


# Contract definitions


@pytest.fixture(scope="session")
def weth9_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/WETH9Mock.vy")


@pytest.fixture(scope="session")
def oracle_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/OracleMock.vy")


@pytest.fixture(scope="session")
def kyc_validator_contract_def(boa_env):
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def vault_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVault.vy")


@pytest.fixture(scope="session")
def securitize_vault_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVaultSecuritize.vy")


@pytest.fixture(scope="session")
def p2p_lending_vaulted_refinance_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVaultedRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_vaulted_liquidation_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVaultedLiquidation.vy")


@pytest.fixture(scope="session")
def p2p_lending_vaulted_erc20_contract_def(boa_env):
    contents = Path("contracts/v1/P2PLendingVaultedErc20.vy").read_text(encoding="utf-8")
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
    return boa.loads_partial(contents, name="P2PLendingVaultedErc20")


@pytest.fixture(scope="session")
def p2p_lending_securitize_refinance_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingSecuritizeRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_securitize_liquidation_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingSecuritizeLiquidation.vy")


@pytest.fixture(scope="session")
def p2p_lending_securitize_erc20_contract_def(boa_env):
    contents = Path("contracts/v1/P2PLendingSecuritizeErc20.vy").read_text(encoding="utf-8")
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
            log LoanMaturityExtended(
                loan_id=empty(bytes32),
                original_maturity=0,
                new_maturity=0,
                lender=empty(address),
                borrower=empty(address),
                caller=empty(address)
            )

    """)
    return boa.loads_partial(contents, name="P2PLendingSecuritizeErc20")


# Token fixtures


@pytest.fixture(scope="session")
def usdc(weth9_contract_def, owner):
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


@pytest.fixture(scope="session")
def weth(weth9_contract_def, owner):
    return weth9_contract_def.deploy("Wrapped Ether", "WETH", 18, 10**20)


@pytest.fixture(scope="session")
def oracle(oracle_contract_def):
    rate = 387780390000
    decimals = 8
    return oracle_contract_def.deploy(decimals, rate)


@pytest.fixture(scope="session")
def kyc_validator_contract(kyc_validator_contract_def, kyc_validator):
    return kyc_validator_contract_def.deploy(kyc_validator)


# P2P Vaulted contract fixtures


@pytest.fixture(scope="session")
def p2p_vaulted_refinance(p2p_lending_vaulted_refinance_contract_def):
    return p2p_lending_vaulted_refinance_contract_def.deploy()


@pytest.fixture(scope="session")
def p2p_vaulted_liquidation(p2p_lending_vaulted_liquidation_contract_def):
    return p2p_lending_vaulted_liquidation_contract_def.deploy()


@pytest.fixture(scope="session")
def vault_impl(vault_contract_def):
    return vault_contract_def.deploy()


@pytest.fixture(scope="session")
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


# P2P Securitize contract fixtures


@pytest.fixture(scope="session")
def p2p_securitize_refinance(p2p_lending_securitize_refinance_contract_def):
    return p2p_lending_securitize_refinance_contract_def.deploy()


@pytest.fixture(scope="session")
def p2p_securitize_liquidation(p2p_lending_securitize_liquidation_contract_def):
    return p2p_lending_securitize_liquidation_contract_def.deploy()


@pytest.fixture(scope="session")
def securitize_vault_impl(securitize_vault_contract_def):
    return securitize_vault_contract_def.deploy()


@pytest.fixture(scope="session")
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


# Vault Registrar and Connector fixtures


@pytest.fixture(scope="session")
def vault_registrar_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/VaultRegistrarMock.vy")


@pytest.fixture(scope="session")
def vault_registrar(vault_registrar_contract_def, usdc, owner):
    return vault_registrar_contract_def.deploy(usdc.address)


@pytest.fixture(scope="session")
def connector_def(boa_env):
    return boa.load_partial("contracts/SecuritizeRegistrarV1Connector.vy")


@pytest.fixture(scope="session")
def connector(connector_def, vault_registrar, p2p_vaulted, p2p_securitize, owner):
    return connector_def.deploy(
        vault_registrar.address,
        [p2p_vaulted.address, p2p_securitize.address],
    )
