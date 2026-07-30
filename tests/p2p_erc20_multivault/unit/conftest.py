from textwrap import dedent

import boa
import pytest
from eth_account import Account

from ...conftest_base import build_erc20_contract_def_with_log_stuff
from ..conftest_base import (
    ZERO_BYTES32,
    Loan,
    Offer,
    compute_signed_offer_id,
    sign_kyc,
    sign_offer,
)

BPS = 10000


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
def redemption_wallet():
    return boa.env.generate_address("redemption_wallet")


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
    return acred_contract_def.deploy("ACRED", "ACRED", 6, 10**6, oracle_acred_usdc.address, usdc.address)


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
    """ERC20 where transfer always returns False (simulates transfer failure).

    transferFrom works normally (moves balances, returns True).
    Includes mint for direct balance setup.
    """
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

        @external
        def mint(_to: address, _value: uint256):
            self.balances[_to] += _value
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
def false_transfer_from_erc20():
    """ERC20 where transferFrom always returns False (simulates transferFrom failure).

    transfer works normally (moves balances, returns True).
    Includes approve and mint for full payment-token compatibility.
    """
    return boa.loads(
        dedent("""
        balances: HashMap[address, uint256]
        allowance_map: HashMap[address, HashMap[address, uint256]]

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
            return False

        @external
        def approve(_spender: address, _value: uint256) -> bool:
            self.allowance_map[msg.sender][_spender] = _value
            return True

        @external
        def mint(_to: address, _value: uint256):
            self.balances[_to] += _value
    """)
    )


@pytest.fixture
def failing_transfer_payment_erc20():
    """ERC20 where transfer returns False and transferFrom returns True, with decimals().

    Designed for use as a payment token in the lending contract, where create_loan
    calls decimals() and transferFrom succeeds, but settle_loan's transfer fails
    (creating pending transfers).
    """
    return boa.loads(
        dedent("""
        @external
        @view
        def decimals() -> uint256:
            return 9

        @external
        def transfer(_to: address, _value: uint256) -> bool:
            return False

        @external
        def transferFrom(_from: address, _to: address, _value: uint256) -> bool:
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
def p2p_lending_multivault_base_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultBase.vy")


@pytest.fixture(scope="session")
def p2p_lending_multivault_loan_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultLoan.vy")


@pytest.fixture(scope="session")
def p2p_lending_multivault_liquidation_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultLiquidation.vy")


@pytest.fixture(scope="session")
def p2p_lending_multivault_refinance_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_multivault_erc20_contract_def(
    p2p_lending_multivault_base_contract_def,
    p2p_lending_multivault_loan_contract_def,
    p2p_lending_multivault_liquidation_contract_def,
    p2p_lending_multivault_refinance_contract_def,
):
    # workaround: boa doesnt catch 'unused' events and fails, so we inject a generated dummy that logs them
    return build_erc20_contract_def_with_log_stuff(
        "contracts/v1/P2PLendingMultiVaultErc20.vy",
        "P2PLendingMultiVaultErc20",
        p2p_lending_multivault_base_contract_def,
        [
            p2p_lending_multivault_loan_contract_def,
            p2p_lending_multivault_liquidation_contract_def,
            p2p_lending_multivault_refinance_contract_def,
        ],
    )


@pytest.fixture(scope="session")
def kyc_validator_contract_def(boa_env):
    return boa.load_partial("contracts/KYCValidator.vy")


@pytest.fixture(scope="session")
def p2p_lending_erc20_proxy_contract_def(boa_env):
    return boa.load_partial("tests/stubs/P2PMultiVaultErc20Proxy.vy")


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
def p2p_mv_refinance(p2p_lending_multivault_refinance_contract_def):
    return p2p_lending_multivault_refinance_contract_def.deploy()


@pytest.fixture
def p2p_mv_liquidation(p2p_lending_multivault_liquidation_contract_def):
    return p2p_lending_multivault_liquidation_contract_def.deploy()


@pytest.fixture
def p2p_mv_loan(p2p_lending_multivault_loan_contract_def):
    return p2p_lending_multivault_loan_contract_def.deploy()


@pytest.fixture
def vault_registrar_weth(vault_registrar_mock_contract_def, weth):
    return vault_registrar_mock_contract_def.deploy(weth.address)


@pytest.fixture(scope="session")
def registrar_connector_def(boa_env):
    return boa.load_partial("contracts/SecuritizeRegistrarV1Connector.vy")


@pytest.fixture(scope="session")
def midas_vault_mock_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/MidasVaultMock.vy")


@pytest.fixture
def securitize_vault_impl(securitize_mv_vault_contract_def):
    """Default vault impl: the REAL P2PLendingVaultSecuritizeMV (caps MINT_SYNC | REDEEM_MANUAL).

    REDEEM_MANUAL (not REDEEM_SYNC) so redeem() reaches the deferred "redeemed, awaiting settle"
    state used by the settle/liquidate/transfer/replace redeemed-loan tests (the p2p's redeem()
    guard rejects REDEEM_SYNC vaults). `redeem_manual` just transfers the collateral token to the
    redemption vault; the leveraged mint tests use the `p2p_usdc_acred` market (collateral is an
    AcredMock so `mint_sync` can resolve its swap connector).
    """
    return securitize_mv_vault_contract_def.deploy()


@pytest.fixture
def securitize_vault_impl_sync(midas_vault_impl_contract_def):
    """Sync vault impl: the REAL P2PLendingVaultMidas (caps MINT_SYNC | REDEEM_SYNC).

    Used by the atomic redeem_and_settle path; `redeem_sync` calls `redeemInstant` + the fee getters
    on the market's redemption_addr, so `p2p_usdc_weth_sync` wires a MidasVaultMock there.
    """
    return midas_vault_impl_contract_def.deploy()


@pytest.fixture(scope="session")
def midas_vault_impl_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVaultMidas.vy")


@pytest.fixture
def p2p_usdc_weth(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    securitize_vault_impl,
    owner,
    transfer_agent,
    redemption_wallet,
):
    return p2p_lending_multivault_erc20_contract_def.deploy(
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
        p2p_mv_refinance.address,  # refinance_addr
        p2p_mv_liquidation.address,  # liquidation_addr
        p2p_mv_loan.address,  # loan_addr
        securitize_vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        boa.eval("empty(address)"),  # mint_addr
        redemption_wallet,  # redemption_addr
        boa.eval("empty(address)"),  # vault_registrar_addr
        0,  # max_pending_window
    )


# AcredMock rate for the leveraged market: ds = stable * den // num, den = 10**decimals, num = rate.
# decimals=12, rate=1500 -> num=1500, den=10**12. This maps a 6-dec USDC mint_spend to an 18-dec DS
# collateral at a full-spend 1:1 economic rate: a full mint of 1500e6 USDC yields exactly 1e18 DS and
# consumes all 1500e6 (refund 0), and swap is self-consistent (liquidity pulled = ds*num//den). A plain
# 0-decimal 1:1 oracle can't be used here because it would leave collateral at 6-dec scale (~1.5e-9 DS),
# blowing past the loan's max LTV. Kept separate from `oracle_acred_usdc` (3/10, securitize/buy tests).
ACRED_LEV_ORACLE_DECIMALS = 12
ACRED_LEV_ORACLE_RATE = 1500


@pytest.fixture
def oracle_acred_lev(oracle_contract_def):
    return oracle_contract_def.deploy(ACRED_LEV_ORACLE_DECIMALS, ACRED_LEV_ORACLE_RATE)


@pytest.fixture
def acred_lev(acred_contract_def, oracle_acred_lev, usdc):
    """18-decimal AcredMock used as the leveraged market's collateral (the DS token).

    P2PLendingVaultSecuritizeMV.mint_sync resolves its swap connector from the collateral token via
    getDSService(1<<14), so the collateral MUST be an AcredMock. Wired to the 1:1 `oracle_acred_lev`
    and to `usdc` as the stablecoin the swap pulls.
    """
    return acred_contract_def.deploy("ACREDLEV", "ACREDLEV", 18, 10**6, oracle_acred_lev.address, usdc.address)


@pytest.fixture
def p2p_usdc_acred(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    usdc,
    acred_lev,
    oracle,
    kyc_validator_contract,
    securitize_vault_impl,
    owner,
    transfer_agent,
    redemption_wallet,
):
    """Leveraged-mint market: real SecuritizeMV impl, collateral = the 18-dec AcredMock (`acred_lev`).

    Mirrors `p2p_usdc_weth` but the collateral token is the AcredMock so `mint_sync` can resolve its
    swap connector and mint DS tokens against `usdc`. The loan's oracle stays the main `oracle`; the
    acred's internal 1:1 oracle (independent) governs the swap rate.
    """
    return p2p_lending_multivault_erc20_contract_def.deploy(
        usdc,  # payment_token
        acred_lev,  # collateral_token (AcredMock DS token)
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
        p2p_mv_refinance.address,  # refinance_addr
        p2p_mv_liquidation.address,  # liquidation_addr
        p2p_mv_loan.address,  # loan_addr
        securitize_vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        boa.eval("empty(address)"),  # mint_addr
        redemption_wallet,  # redemption_addr
        boa.eval("empty(address)"),  # vault_registrar_addr
        0,  # max_pending_window
    )


@pytest.fixture
def midas_redemption_vault(midas_vault_mock_contract_def, weth):
    """The Midas RedemptionVault mock wired as `redemption_addr` for the sync market.

    Constructed with (mtoken=weth, instant_fee=0). `redeem_sync` staticcalls its fee getters and calls
    `redeemInstant` on it, which pulls the redeemed collateral (weth) and pays out `set_deliver_amount`
    usdc. Tests configure `set_waived`/`set_deliver_amount` and pre-fund it with the payout token.
    """
    return midas_vault_mock_contract_def.deploy(weth.address, 0)


@pytest.fixture
def p2p_usdc_weth_sync(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    securitize_vault_impl_sync,
    owner,
    transfer_agent,
    midas_redemption_vault,
):
    """Lending contract wired to the REAL P2PLendingVaultMidas impl (MINT_SYNC | REDEEM_SYNC).

    Used by the atomic redeem_and_settle tests (and to assert redeem() rejects a sync vault). Mirrors
    `p2p_usdc_weth` except: the vault impl is the real Midas vault, and `redemption_addr` is a
    MidasVaultMock (redeem_sync calls redeemInstant + fee getters on it) instead of an EOA.
    """
    return p2p_lending_multivault_erc20_contract_def.deploy(
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
        p2p_mv_refinance.address,  # refinance_addr
        p2p_mv_liquidation.address,  # liquidation_addr
        p2p_mv_loan.address,  # loan_addr
        securitize_vault_impl_sync.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        boa.eval("empty(address)"),  # mint_addr
        midas_redemption_vault.address,  # redemption_addr (MidasVaultMock)
        boa.eval("empty(address)"),  # vault_registrar_addr
        0,  # max_pending_window
    )


# ---------------------------------------------------------------------------
# Centrifuge async (ERC-7540) fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def centrifuge_async_vault_mock_contract_def(boa_env):
    return boa.load_partial("contracts/auxiliary/CentrifugeAsyncVaultMock.vy")


@pytest.fixture(scope="session")
def centrifuge_async_vault_impl_contract_def(boa_env):
    return boa.load_partial("contracts/v1/P2PLendingVaultCentrifugeAsync.vy")


@pytest.fixture
def centrifuge_async_vault_impl(centrifuge_async_vault_impl_contract_def):
    """The Centrifuge async vault implementation (async ERC-7540 capabilities constant on the impl).

    Used as `vault_impl_addr` so per-borrower CREATE2 clones drive the Centrifuge ERC-7540 async
    mint/redeem lifecycle instead of the instant Midas-style mint.
    """
    return centrifuge_async_vault_impl_contract_def.deploy()


@pytest.fixture
def centrifuge_async_vault_mock(centrifuge_async_vault_mock_contract_def, usdc, weth):
    """Centrifuge ERC-7540 AsyncVault mock.

    asset == usdc (payment token pulled on requestDeposit / paid on redeem claim),
    share == weth (collateral token paid on deposit claim / pulled on requestRedeem). This single
    vault is BOTH the market mint_addr and redemption_addr for the Centrifuge async market.
    """
    return centrifuge_async_vault_mock_contract_def.deploy(usdc.address, weth.address)


@pytest.fixture
def p2p_usdc_weth_centrifuge(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    usdc,
    weth,
    oracle,
    kyc_validator_contract,
    centrifuge_async_vault_impl,
    centrifuge_async_vault_mock,
    owner,
    transfer_agent,
):
    """Lending contract wired to a Centrifuge async (ERC-7540) vault impl.

    Both mint_addr and redemption_addr point at the same CentrifugeAsyncVaultMock (the async vault is
    stateless about the AsyncVault address and receives it from the market on each call). A non-zero
    max_pending_window (50s) makes the borrower-only guard on cancel_pending_loan meaningful (with
    window 0 the permissionless recovery path would always be open). The window is kept BELOW the
    async offers' 100s duration so "past window" (t=51) is decoupled from "past maturity" (t=101):
    a permissionless cancel can fire while the loan is still pending-but-not-defaulted.
    """
    return p2p_lending_multivault_erc20_contract_def.deploy(
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
        p2p_mv_refinance.address,  # refinance_addr
        p2p_mv_liquidation.address,  # liquidation_addr
        p2p_mv_loan.address,  # loan_addr
        centrifuge_async_vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        centrifuge_async_vault_mock.address,  # mint_addr (same Centrifuge vault as redemption)
        centrifuge_async_vault_mock.address,  # redemption_addr
        boa.eval("empty(address)"),  # vault_registrar_addr
        50,  # max_pending_window (< the async offers' 100s duration)
    )


@pytest.fixture
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


@pytest.fixture
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


def _async_offer(usdc, weth, oracle, lender, borrower, now, *, principal, min_collateral_amount=0):
    return Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=0,
        min_collateral_amount=min_collateral_amount,
        max_iltv=8000,
        available_liquidity=max(principal, 1),
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 10**6,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )


@pytest.fixture
def centrifuge_signed_offer(usdc, weth, oracle, lender, borrower, lender_key, now, p2p_usdc_weth_centrifuge):
    """A signed standard offer for the Centrifuge async market, for inline/revert tests."""
    offer = _async_offer(usdc, weth, oracle, lender, borrower, now, principal=1000 * 10**6)
    return sign_offer(offer, lender_key, p2p_usdc_weth_centrifuge.address)


@pytest.fixture
def sign_centrifuge_offer(p2p_usdc_weth_centrifuge, usdc, weth, oracle, lender, borrower, lender_key, now):
    """Build + sign an async (Centrifuge-market) offer for `principal`; the test calls create_leveraged_loan itself."""

    def _sign(principal, *, origination_fee_bps=0, min_collateral_amount=0):
        offer = _async_offer(
            usdc, weth, oracle, lender, borrower, now, principal=principal, min_collateral_amount=min_collateral_amount
        )
        offer = offer._replace(available_liquidity=principal, origination_fee_bps=origination_fee_bps)
        return sign_offer(offer, lender_key, p2p_usdc_weth_centrifuge.address)

    return _sign


@pytest.fixture
def fund_centrifuge_leveraged(p2p_usdc_weth_centrifuge, usdc, borrower, lender):
    """Pre-fund an async create_leveraged_loan: mint+approve the lender's principal (net origination fee)
    and the borrower's margin (= mint_spend - lender's contribution). No collateral seeding — the async
    vault mints it on the deposit claim.
    """

    def _fund(principal, mint_spend, *, origination_fee_bps=0):
        lender_to_vault = principal - origination_fee_bps * principal // BPS
        borrower_margin = mint_spend - lender_to_vault
        usdc.mint(lender, mint_spend)
        usdc.approve(p2p_usdc_weth_centrifuge.address, mint_spend, sender=lender)
        if borrower_margin > 0:
            usdc.mint(borrower, borrower_margin)
            usdc.approve(p2p_usdc_weth_centrifuge.address, borrower_margin, sender=borrower)

    return _fund


def expected_pending_centrifuge_loan(
    p2p, signed_offer, loan_id, borrower, lender, now, *, principal, collateral, offer_principal=None
):
    """The Loan an async create_leveraged_loan stores while PENDING (deposit requested, not yet started).

    `start_time == 0` (not started) and `max_pending_window` is snapshotted from the market. Fees are
    snapshotted on the ORIGINAL offer principal (`offer_principal`, the contract's `fee_principal`),
    NOT the stored `principal` — pass `offer_principal` when the two differ. The async create commits the
    full principal without reconciliation, so `offer_principal == principal` there; the param exists to
    match the contract's fee basis exactly (see `_validate_and_build_loan`). Fee/window getters are read
    here, so call this AFTER the create tx and do NOT also assert the LoanCreated/LeveragedLoanCreated
    events on the same `p2p` (a getter read resets boa's last-computation used by get_logs) — event tests
    create inline.
    """
    fee_principal = principal if offer_principal is None else offer_principal
    offer = signed_offer.offer
    return Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(signed_offer),
        offer_tracing_id=offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.apr,
        payment_token=offer.payment_token,
        collateral_token=offer.collateral_token,
        maturity=now + offer.duration,
        create_time=now,
        start_time=0,
        accrual_start_time=now,
        borrower=borrower,
        lender=lender,
        collateral_amount=collateral,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * fee_principal // BPS,
        protocol_upfront_fee_amount=p2p.protocol_upfront_fee() * fee_principal // BPS,
        protocol_settlement_fee=p2p.protocol_settlement_fee(),
        partial_liquidation_fee=p2p.partial_liquidation_fee(),
        full_liquidation_fee=p2p.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=offer.oracle_addr,
        initial_ltv=offer.max_iltv,
        call_time=0,
        vault_id=0,
        redeem_start=0,
        redeem_residual_collateral=0,
        max_pending_window=p2p.max_pending_window(),
    )


# Alias for backward compatibility with securitize test naming
@pytest.fixture(scope="session")
def securitize_redemption_wallet(redemption_wallet):
    return redemption_wallet
