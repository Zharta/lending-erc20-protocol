import os

import boa
import pytest
from boa.environment import Env
from eth_account import Account

from ...conftest_base import ETH_FORK_BLOCK, build_erc20_contract_def_with_log_stuff
from ..conftest_base import sign_kyc, sign_register_vault


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


# Freshly generated, key-controlled account so it can both produce the EIP-712 investor signature
# (registrar set_investor_signature) and be registered as a Securitize investor.
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
    addr = "0x1ffD2C4373A0CBee33f974e4142611C8c4A4f366"
    boa.env.set_balance(addr, 10**21)
    return addr


@pytest.fixture(autouse=True)
def borrower_acred_funds(borrower, securitize_registry, acred_ds_token, token_issuer):
    """Register the borrower as a Securitize investor and issue collateral DS tokens, so the
    VaultRegistrar can create vaults for it (a fresh account is not pre-registered on-chain)."""
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
    addr = "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"
    boa.env.set_balance(addr, 10**21)
    return addr


@pytest.fixture
def securitize_registry(boa_env):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json")
    return contract_def.at("0x3A8E9CD2E17E1F2904b7f745Da29C9cA765Cc319")


# MultiVault contract definitions


@pytest.fixture(scope="session")
def p2p_lending_multivault_base_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultBase.vy")


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
def p2p_lending_multivault_refinance_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultRefinance.vy")


@pytest.fixture(scope="session")
def p2p_lending_multivault_liquidation_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultLiquidation.vy")


@pytest.fixture(scope="session")
def p2p_lending_multivault_loan_contract_def():
    return boa.load_partial("contracts/v1/P2PLendingMultiVaultLoan.vy")


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
def p2p_mv_refinance(p2p_lending_multivault_refinance_contract_def):
    return p2p_lending_multivault_refinance_contract_def.deploy()


@pytest.fixture
def p2p_mv_liquidation(p2p_lending_multivault_liquidation_contract_def):
    return p2p_lending_multivault_liquidation_contract_def.deploy()


@pytest.fixture
def p2p_mv_loan(p2p_lending_multivault_loan_contract_def):
    return p2p_lending_multivault_loan_contract_def.deploy()


@pytest.fixture
def securitize_vault_impl(securitize_mv_vault_contract_def):
    return securitize_mv_vault_contract_def.deploy()


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


TRUST_ROLE_TRANSFER_AGENT = 8


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
def set_investor_sig(registrar_connector, vault_registrar):
    """Store an EIP-712 RegisterVault authorization for `investor` on the connector.

    registerVault (invoked when the lending contract creates a per-loan vault) requires the investor
    to have authorized the connector via an EIP-712 signature; an empty one reverts (0x5335c859). The
    signature is bound to the investor's current operator nonce, so it authorizes one registration.
    """

    def _set(investor_account, deadline):
        v, r, s = sign_register_vault(investor_account, registrar_connector.address, vault_registrar, deadline)
        registrar_connector.set_investor_signature(deadline, (v, r, s), sender=investor_account.address)

    return _set


@pytest.fixture
def p2p_usdc_acred(
    p2p_lending_multivault_erc20_contract_def,
    p2p_mv_refinance,
    p2p_mv_liquidation,
    p2p_mv_loan,
    securitize_vault_impl,
    usdc,
    acred,
    oracle_acred_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
    redemption_wallet,
    registrar_connector,
    securitize_trust_service,
    securitize_owner,
):
    contract = p2p_lending_multivault_erc20_contract_def.deploy(
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
        p2p_mv_refinance.address,
        p2p_mv_liquidation.address,
        p2p_mv_loan.address,
        securitize_vault_impl.address,
        transfer_agent,
        boa.eval("empty(address)"),  # mint_addr (not used for ACRED here)
        redemption_wallet,
        registrar_connector.address,
        0,  # max_pending_window
    )
    registrar_connector.change_authorized_contract(contract.address, True, sender=owner)
    return contract


# ---------------------------------------------------------------------------
# Centrifuge async / ERC-7540 fork support
# ---------------------------------------------------------------------------
# Shared fulfilment/whitelisting helpers for the deJAAA (Ethereum) and deSPXA (Base) suites, which run on the
# same Centrifuge V3 deployment, so the centrifuge_* helpers take the spoke / root as explicit args.
# Fulfilment impersonates the spoke and calls AsyncRequestManager.callback(...); whitelisting impersonates
# the root (a ward of the hook).

# RequestCallbackMessageLib type tags (protocol-v3 RequestCallbackMessageLib.sol).
_RC_APPROVED_DEPOSITS = 1
_RC_ISSUED_SHARES = 2
_RC_REVOKED_SHARES = 3
_RC_FULFILLED_DEPOSIT = 4
_RC_FULFILLED_REDEEM = 5
_D18_ONE = 10**18  # neutral D18 price for the pool-per-asset / pool-per-share fields


def _left_investor(addr: str) -> bytes:
    """The manager decodes `investor` bytes32 left-aligned (address(bytes20(x)), bottom uint96 == 0)."""
    return bytes.fromhex(addr[2:]) + bytes(12)


# --- behaviour helpers (plain functions; the fixtures below only set up real objects) ----------------
# Every chain constant is a parameter so each suite reuses these with its own
# token / spoke / root / pool-id / scid.


def centrifuge_whitelist(hook, token, addr, root):
    """Whitelist an address (the loan vault / controller) as a member of `token` (a Centrifuge share
    token) so it can request deposits and hold shares. Impersonates `root` (a ward of the hook)."""
    boa.env.set_balance(root, 10**20)
    hook.updateMember(token, addr, 2**64 - 1, sender=root)


def centrifuge_fulfill_deposit(manager, pool_id, scid, asset_id, controller, assets, shares, spoke):
    """Issuer-side deposit fulfilment for a controller (the loan vault), impersonating `spoke`.

    Runs the three-message sequence the Hub relays: ApprovedDeposits, IssuedShares, FulfilledDepositRequest.
    `assets` is the USDC fulfilled; `shares` is the collateral minted (balanceSheet.issue, no pre-funding).
    After this claimableDepositRequest == assets and the controller can claim ~`shares` shares."""
    boa.env.set_balance(spoke, 10**20)

    def _cb(payload):
        manager.callback(pool_id, scid, asset_id, payload, sender=spoke)

    _cb(bytes([_RC_APPROVED_DEPOSITS]) + assets.to_bytes(16, "big") + _D18_ONE.to_bytes(16, "big"))
    _cb(bytes([_RC_ISSUED_SHARES]) + shares.to_bytes(16, "big") + _D18_ONE.to_bytes(16, "big"))
    _cb(
        bytes([_RC_FULFILLED_DEPOSIT])
        + _left_investor(controller)
        + assets.to_bytes(16, "big")
        + shares.to_bytes(16, "big")
        + (0).to_bytes(16, "big")
    )


def centrifuge_fulfill_redeem(manager, pool_id, scid, asset_id, controller, shares, assets, spoke):
    """Issuer-side redeem fulfilment for a controller, impersonating `spoke`.

    RevokedShares (burn `shares`, note `assets` USDC withdraw) then FulfilledRedeemRequest. After this
    claimableRedeemRequest == shares and claiming yields ~`assets` USDC (from pool escrow, no pre-funding)."""
    boa.env.set_balance(spoke, 10**20)

    def _cb(payload):
        manager.callback(pool_id, scid, asset_id, payload, sender=spoke)

    _cb(bytes([_RC_REVOKED_SHARES]) + assets.to_bytes(16, "big") + shares.to_bytes(16, "big") + _D18_ONE.to_bytes(16, "big"))
    _cb(
        bytes([_RC_FULFILLED_REDEEM])
        + _left_investor(controller)
        + assets.to_bytes(16, "big")
        + shares.to_bytes(16, "big")
        + (0).to_bytes(16, "big")
    )


def centrifuge_fulfill_cancel_deposit(manager, pool_id, scid, asset_id, controller, assets, spoke):
    """Issuer-side fulfilment of a DEPOSIT cancellation, impersonating `spoke`.

    On Base, cancelDepositRequest is asynchronous: it only submits the cancel and the reclaimed payment
    becomes claimable after the issuer relays a FulfilledDepositRequest with cancelledAssets = assets
    (zero fulfilled amounts) -> claimableCancelDepositRequest == assets. On Ethereum the cancel resolves
    synchronously, so this step is only needed by the Base suite."""
    boa.env.set_balance(spoke, 10**20)
    manager.callback(
        pool_id,
        scid,
        asset_id,
        bytes([_RC_FULFILLED_DEPOSIT])
        + _left_investor(controller)
        + (0).to_bytes(16, "big")  # fulfilledAssets
        + (0).to_bytes(16, "big")  # fulfilledShares
        + assets.to_bytes(16, "big"),  # cancelledAssets
        sender=spoke,
    )


def centrifuge_fulfill_cancel_redeem(manager, pool_id, scid, asset_id, controller, shares, spoke):
    """Issuer-side fulfilment of a REDEEM cancellation, impersonating `spoke`.

    Redeem analog of centrifuge_fulfill_cancel_deposit: on Base cancelRedeemRequest is async and the
    reclaimed shares become claimable after a FulfilledRedeemRequest with cancelledShares = shares
    (zero fulfilled amounts) -> claimableCancelRedeemRequest == shares. Not needed on Ethereum."""
    boa.env.set_balance(spoke, 10**20)
    manager.callback(
        pool_id,
        scid,
        asset_id,
        bytes([_RC_FULFILLED_REDEEM])
        + _left_investor(controller)
        + (0).to_bytes(16, "big")  # fulfilledAssets
        + (0).to_bytes(16, "big")  # fulfilledShares
        + shares.to_bytes(16, "big"),  # cancelledShares
        sender=spoke,
    )


# --- shared Centrifuge contract defs (ABI-only, env-agnostic) -----------------------------------------
# One session-scoped def per contract kind; per-token fixtures bind them to a chain-specific address
# with .at() under the right boa env (deJAAA -> Ethereum, deSPXA -> Base).


@pytest.fixture(scope="session")
def centrifuge_share_token_contract_def():
    return boa.loads_abi(
        """[
      {"name":"balanceOf","inputs":[{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"decimals","inputs":[],"outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"},
      {"name":"hook","inputs":[],"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}
    ]"""
    )


@pytest.fixture(scope="session")
def centrifuge_async_vault_contract_def():
    """The ERC-7540 AsyncVault surface the tests read: conversions + request-status views."""
    return boa.loads_abi(
        """[
      {"name":"convertToShares","inputs":[{"type":"uint256"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"convertToAssets","inputs":[{"type":"uint256"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"pendingDepositRequest","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"claimableDepositRequest","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"pendingRedeemRequest","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"claimableRedeemRequest","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"claimableCancelDepositRequest","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
      {"name":"claimableCancelRedeemRequest","inputs":[{"type":"uint256"},{"type":"address"}],"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}
    ]"""
    )


@pytest.fixture(scope="session")
def centrifuge_manager_contract_def():
    return boa.loads_abi(
        """[
      {"name":"callback","inputs":[{"type":"uint64"},{"type":"bytes16"},{"type":"uint128"},{"type":"bytes"}],"outputs":[],"stateMutability":"nonpayable","type":"function"}
    ]"""
    )


@pytest.fixture(scope="session")
def centrifuge_spoke_contract_def():
    return boa.loads_abi(
        """[
      {"name":"assetToId","inputs":[{"type":"address"},{"type":"uint256"}],"outputs":[{"type":"uint128"}],"stateMutability":"view","type":"function"}
    ]"""
    )


@pytest.fixture(scope="session")
def centrifuge_hook_contract_def():
    return boa.load_abi("contracts/auxiliary/CentrifugeFullRestrictions_abi.json")


@pytest.fixture(scope="session")
def centrifuge_async_vault_impl_contract_def():
    """The P2PLendingVaultCentrifugeAsync impl bytecode; each async loop suite deploys it under its own
    fork env (test_loop_dejaaa.py -> Ethereum, test_loop_despxa.py -> Base)."""
    return boa.load_partial("contracts/v1/P2PLendingVaultCentrifugeAsync.vy")
