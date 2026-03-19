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
def securitize_redemption_wallet():
    return boa.env.generate_address("securitize_redemption_wallet")


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
def acred_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/AcredMock.vy")


@pytest.fixture
def oracle_acred_usdc(oracle_contract_def):
    """Oracle with rate 3/10 to produce rounding in swaps."""
    return oracle_contract_def.deploy(1, 3)


@pytest.fixture
def acred(acred_contract_def, oracle_acred_usdc, usdc):
    return acred_contract_def.deploy(10**6, oracle_acred_usdc.address, usdc.address)


@pytest.fixture(scope="session")
def min_vault_manager():
    return boa.loads(
        dedent("""
        authorized: HashMap[address, bool]

        @external
        def authorized_proxies(proxy: address) -> bool:
            return self.authorized[proxy]

        @external
        def set_proxy(proxy: address, is_authorized: bool):
            self.authorized[proxy] = is_authorized
    """)
    )


@pytest.fixture
def no_zero_transfer_erc20():
    """ERC20 that reverts on zero-amount transferFrom calls."""
    return boa.loads(
        dedent("""
        balances: HashMap[address, uint256]

        @external
        @view
        def balanceOf(_owner: address) -> uint256:
            return self.balances[_owner]

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            self.balances[msg.sender] -= _value
            self.balances[_to] += _value
            return True

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            assert _value > 0, "zero transferFrom not allowed"
            self.balances[_from] -= _value
            self.balances[_to] += _value
            return True
    """)
    )


@pytest.fixture
def zero_revert_erc20():
    """ERC20 that reverts on zero-amount transfer calls and tracks if transfer was called."""
    return boa.loads(
        dedent("""
        transfer_called: bool

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            assert _value > 0, "zero transfer"
            self.transfer_called = True
            return True

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            return True

        @external
        @view
        def was_transfer_called() -> bool:
            return self.transfer_called
    """)
    )


@pytest.fixture
def failing_transfer_erc20():
    """ERC20 where transfer always returns False (simulates transfer failure)."""
    return boa.loads(
        dedent("""
        balances: HashMap[address, uint256]

        @external
        @view
        def balanceOf(_owner: address) -> uint256:
            return self.balances[_owner]

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            return False

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            self.balances[_to] += _value
            return True
    """)
    )


@pytest.fixture
def tracking_erc20():
    """ERC20 that tracks the last transferFrom amount for branch verification."""
    return boa.loads(
        dedent("""
        balances: HashMap[address, uint256]
        last_transfer_from_amount: public(uint256)

        @external
        @view
        def balanceOf(_owner: address) -> uint256:
            return self.balances[_owner]

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            self.balances[msg.sender] -= _value
            self.balances[_to] += _value
            return True

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
            self.last_transfer_from_amount = _value
            self.balances[_from] -= _value
            self.balances[_to] += _value
            return True
    """)
    )


@pytest.fixture
def vault_proxy():
    """Proxy contract that calls vault.buy() or vault.withdraw_funds(), so msg.sender != tx.origin."""
    return boa.loads(
        dedent("""
        from ethereum.ercs import IERC20

        interface IVault:
            def buy(payment_token: address, min_ds_token_amount: uint256, stable_coin_amount: uint256): nonpayable
            def withdraw_funds(payment_token: address, amount: uint256): nonpayable

        @external
        def proxy_buy(vault: address, payment_token: address, min_ds_token: uint256, stable_amount: uint256):
            extcall IERC20(payment_token).transferFrom(msg.sender, self, stable_amount)
            extcall IERC20(payment_token).approve(vault, stable_amount)
            extcall IVault(vault).buy(payment_token, min_ds_token, stable_amount)

        @external
        def proxy_withdraw_funds(vault: address, payment_token: address, amount: uint256):
            extcall IVault(vault).withdraw_funds(payment_token, amount)
    """)
    )


@pytest.fixture(scope="session")
def p2p_lending_securitize_erc20_contract_def(boa_env):
    # workaround: boa doesnt catch 'unused' events and fails, so we inject a dummy function that logs them
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
            log LoanBorrowerTransferred(
                loan_id=empty(bytes32),
                new_loan_id=empty(bytes32),
                old_borrower=empty(address),
                new_borrower=empty(address),
                lender=empty(address),
                vault_id=0
            )

    """)
    return boa.loads_partial(contents, name="P2PLendingSecuritizeErc20")


@pytest.fixture(scope="session")
def kyc_validator_contract_def(boa_env):
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def p2p_lending_erc20_proxy_contract_def(boa_env):
    return boa.load_partial("tests/stubs/P2PSecuritizeErc20Proxy.vy")


@pytest.fixture
def now():
    return boa.eval("block.timestamp")


@pytest.fixture
def kyc_for(kyc_validator_contract_def, kyc_validator_key, now):
    def sign_func(wallet, verifier, expiration=None):
        return sign_kyc(wallet, expiration or now, kyc_validator_key, verifier)

    return sign_func


@pytest.fixture
def usdc(weth9_contract_def, owner):
    return weth9_contract_def.deploy("USDC", "USDC", 6, 10**20)


@pytest.fixture
def oracle(oracle_contract_def, owner):
    rate = 387780390000
    decimals = 8
    return oracle_contract_def.deploy(decimals, rate)


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
def vault_registrar_weth(vault_registrar_mock_contract_def, weth):
    return vault_registrar_mock_contract_def.deploy(weth.address)


@pytest.fixture(scope="session")
def registrar_connector_def(boa_env):
    return boa.load_partial("contracts/SecuritizeRegistrarV1Connector.vy")


@pytest.fixture
def securitize_vault_impl(securitize_vault_contract_def):
    return securitize_vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_weth(
    p2p_lending_securitize_erc20_contract_def,
    p2p_sec_refinance,
    p2p_sec_liquidation,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    securitize_vault_impl,
    owner,
    transfer_agent,
    securitize_redemption_wallet,
):
    return p2p_lending_securitize_erc20_contract_def.deploy(
        usdc,  # payment_token
        weth,  # collateral_token
        oracle,  # oracle_addr
        False,  # oracle_reverse
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
