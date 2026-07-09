"""
Integration tests for P2PLendingVaultedErc20 with ACRED token and the real V2 VaultRegistrar.
These tests use the actual ACRED token and VaultRegistrar on mainnet fork (block 25300898).
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Loan,
    Offer,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_last_event,
    sign_offer,
    sign_register_vault,
)

BPS = 10000


# Securitize mainnet addresses (ACRED fund)
DS_TOKEN = "0x17418038ecF73BA4026c4f428547BF099706F27B"  # ACRED DS Token (collateral)
# Holder of the issuer role - can register investors and issue tokens.
TOKEN_ISSUER = "0x1ffD2C4373A0CBee33f974e4142611C8c4A4f366"
# Securitize owner: admin allowed to add operators on the registrar and grant trust roles.
SECURITIZE_OWNER = "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"

TRUST_ROLE_TRANSFER_AGENT = 8


@pytest.fixture
def acred(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at(DS_TOKEN)


@pytest.fixture(scope="session")
def ds_token_contract_def():
    return boa.load_abi("contracts/auxiliary/SecuritizeDSToken_abi.json")


@pytest.fixture
def acred_ds_token(ds_token_contract_def, boa_env):
    return ds_token_contract_def.at(DS_TOKEN)


@pytest.fixture
def oracle_acred_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0xD6BcbbC87bFb6c8964dDc73DC3EaE6d08865d51C")


@pytest.fixture
def vault_registrar_contract_def():
    return boa.load_abi("contracts/auxiliary/VaultRegistrarV2_abi.json")


@pytest.fixture
def vault_registrar(vault_registrar_contract_def):
    return vault_registrar_contract_def.at("0xD280bcA62a7FC67011cAef77815e8606071BEf9F")


@pytest.fixture
def securitize_owner():
    boa.env.set_balance(SECURITIZE_OWNER, 10**21)
    return SECURITIZE_OWNER


@pytest.fixture
def token_issuer(boa_env):
    boa.env.set_balance(TOKEN_ISSUER, 10**21)
    return TOKEN_ISSUER


@pytest.fixture
def securitize_registry(boa_env):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json")
    return contract_def.at("0x3A8E9CD2E17E1F2904b7f745Da29C9cA765Cc319")


@pytest.fixture
def securitize_trust_service(boa_env):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeTrustService_abi.json")
    return contract_def.at("0xc397436742eAF7C325DDBFc4dc63D95822b27101")


@pytest.fixture(autouse=True)
def register_borrower_investor(securitize_registry, acred_ds_token, borrower, token_issuer):
    """Register the borrower as a Securitize investor and issue collateral DS tokens."""
    investor_id = "zharta_test_investor"
    securitize_registry.registerInvestor(investor_id, "", sender=token_issuer)
    securitize_registry.setCountry(investor_id, "US", sender=token_issuer)
    securitize_registry.addWallet(borrower, investor_id, sender=token_issuer)
    acred_ds_token.issueTokens(borrower, 200 * int(1e6), sender=token_issuer)
    return investor_id


@pytest.fixture
def p2p_usdc_acred(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    p2p_liquidation,
    vault_impl,
    usdc,
    acred,
    oracle_acred_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
    registrar_connector,
):
    contract = p2p_lending_erc20_contract_def.deploy(
        usdc,
        acred,
        oracle_acred_usd,
        False,  # oracle_reverse (ACRED/USD oracle is not reversed)
        kyc_validator_contract,
        0,  # protocol_upfront_fee
        0,  # protocol_settlement_fee
        owner,  # protocol_wallet
        10000,  # max_protocol_upfront_fee
        10000,  # max_protocol_settlement_fee
        0,  # partial_liquidation_fee
        0,  # full_liquidation_fee
        p2p_refinance.address,  # refinance_addr
        p2p_liquidation.address,  # liquidation_addr
        vault_impl.address,  # vault_impl_addr
        transfer_agent,  # transfer_agent
        registrar_connector.address,  # vault_registrar_addr
    )
    registrar_connector.change_authorized_contract(contract.address, True, sender=owner)
    contract.change_vault_registrar(registrar_connector.address, sender=owner)
    return contract


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture
def registrar_connector(
    registrar_connector_def,
    vault_registrar,
    securitize_trust_service,
    securitize_owner,
    owner,
):
    assert boa.env.eoa == owner
    connector = registrar_connector_def.deploy(vault_registrar.address)
    vault_registrar.addOperator(connector.address, sender=securitize_owner)
    # The registrar needs the TRANSFER_AGENT trust role to register vaults in the registry.
    securitize_trust_service.setRole(vault_registrar.address, TRUST_ROLE_TRANSFER_AGENT, sender=securitize_owner)
    return connector


def test_oracle_data(oracle_acred_usd, p2p_usdc_acred):
    answer = oracle_acred_usd.latestRoundData()[1]

    assert oracle_acred_usd.address == p2p_usdc_acred.oracle_addr()
    assert oracle_acred_usd.decimals() == 8

    # ACRED trades at ~$1,097.55 per token at fork block 25300898. Must change if fork block changes.
    min_price = 1097 * 10**8
    max_price = 1098 * 10**8
    assert min_price <= answer <= max_price, f"oracle answer {answer} outside sane range [{min_price}, {max_price}]"


def test_create_loan(
    p2p_usdc_acred,
    borrower,
    borrower_account,
    lender,
    lender_key,
    now,
    kyc_for,
    kyc_validator_contract,
    acred,
    usdc,
    oracle_acred_usd,
    vault_registrar,
    registrar_connector,
):
    # Generate KYC for the borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has ACRED (issued by register_borrower_investor fixture)
    borrower_acred_balance = acred.balanceOf(borrower)
    collateral_amount = min(borrower_acred_balance // 10, int(1e17))
    if collateral_amount == 0:
        collateral_amount = int(1e15)  # Minimum amount for test

    principal = 100 * int(1e6)  # 100 USDC

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_acred.payment_token(),
        collateral_token=p2p_usdc_acred.collateral_token(),
        duration=100,
        min_collateral_amount=collateral_amount,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
        max_iltv=9500,  # 95% max initial LTV (ACRED price may be low)
        liquidation_ltv=9900,  # 99% liquidation LTV
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acred.address)

    # The borrower (Securitize investor) authorizes the connector to register vaults
    # on its behalf by storing an EIP-712 RegisterVault signature.
    deadline = now + 3600
    v, r, s = sign_register_vault(borrower_account, registrar_connector.address, vault_registrar, deadline)
    registrar_connector.set_investor_signature(deadline, (v, r, s), sender=borrower)

    # Approve collateral
    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    borrower_collateral_balance_before = acred.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Precondition: the vault is not yet registered
    vault_addr = p2p_usdc_acred.wallet_to_vault(borrower)
    assert vault_registrar.isRegistered(vault_addr, borrower) is False

    # Create loan
    loan_id = p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_acred, "LoanCreated")

    # Verify loan was created with proper hash
    loan = Loan(
        id=loan_id,
        offer_id=compute_signed_offer_id(signed_offer),
        offer_tracing_id=offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.apr,
        payment_token=offer.payment_token,
        collateral_token=offer.collateral_token,
        maturity=now + offer.duration,
        start_time=now,
        accrual_start_time=now,
        borrower=borrower,
        lender=lender,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.min_collateral_amount,
        origination_fee_amount=offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=p2p_usdc_acred.protocol_upfront_fee() * principal // BPS,
        protocol_settlement_fee=p2p_usdc_acred.protocol_settlement_fee(),
        partial_liquidation_fee=p2p_usdc_acred.partial_liquidation_fee(),
        full_liquidation_fee=p2p_usdc_acred.full_liquidation_fee(),
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_acred.oracle_addr(),
        initial_ltv=offer.max_iltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_acred.loans(loan_id), "Loan hash should match"

    # event assertions
    assert event.id == loan_id
    assert event.amount == principal
    assert event.apr == offer.apr
    assert event.payment_token == offer.payment_token
    assert event.maturity == now + offer.duration
    assert event.start_time == now
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_token == offer.collateral_token
    assert event.collateral_amount == collateral_amount
    assert event.call_eligibility == offer.call_eligibility
    assert event.call_window == offer.call_window
    assert event.liquidation_ltv == offer.liquidation_ltv
    assert event.oracle_addr == p2p_usdc_acred.oracle_addr()
    assert event.initial_ltv == offer.max_iltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_acred.protocol_upfront_fee() * principal // BPS
    assert event.protocol_settlement_fee == p2p_usdc_acred.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_acred.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    # Verify vault registration - this is the key test for vault_registrar functionality
    vault_addr = p2p_usdc_acred.wallet_to_vault(borrower)
    assert vault_registrar.isRegistered(vault_addr, borrower) is True

    # Balance assertions
    assert acred.balanceOf(vault_addr) == collateral_amount
    assert acred.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal
