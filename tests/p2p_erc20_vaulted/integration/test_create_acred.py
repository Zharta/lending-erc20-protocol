"""
Integration tests for P2PLendingVaultedErc20 with ACRED token and real VaultRegistrar.
These tests use the actual ACRED token and VaultRegistrar on mainnet fork.
"""

import boa
import pytest

from ..conftest_base import (
    ZERO_BYTES32,
    Offer,
    compute_liquidity_key,
    get_last_event,
    sign_offer,
)

BPS = 10000

SEC_REG_ACCREDITED = 2
SEC_REG_APPROVED = 1


@pytest.fixture
def acred(owner, accounts, erc20_contract_def):
    return erc20_contract_def.at("0x17418038ecF73BA4026c4f428547BF099706F27B")


@pytest.fixture
def oracle_acred_usd(oracle_contract_def, owner):
    return oracle_contract_def.at("0xD6BcbbC87bFb6c8964dDc73DC3EaE6d08865d51C")


@pytest.fixture
def vault_registrar_contract_def():
    return boa.load_abi("contracts/auxiliary/VaultRegistrar_abi.json")


@pytest.fixture
def vault_registrar(vault_registrar_contract_def):
    return vault_registrar_contract_def.at("0x9fbF77D74337FefA7D8993f507A38EDB4df620E5")


@pytest.fixture
def securitize_owner():
    return "0x59c1eAcEc450c57Dcb9b8725d0F96635C2b676Ee"


@pytest.fixture
def vault_registrar_admin():
    return "0xd69fefe5df62373dcbde3e1f9625cf334a2dae78"


@pytest.fixture
def securitize_registry(securitize_owner, now):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeRegistryService_abi.json")
    return contract_def.at("0x3A8E9CD2E17E1F2904b7f745Da29C9cA765Cc319")


@pytest.fixture
def securitize_trust_service(securitize_owner, now):
    contract_def = boa.load_abi("contracts/auxiliary/SecuritizeTrustService_abi.json")
    return contract_def.at("0xc397436742eAF7C325DDBFc4dc63D95822b27101")


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
    vault_registrar,
    securitize_trust_service,
    securitize_owner,
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
        boa.eval("empty(address)"),  # vault_registrar_addr
    )
    securitize_trust_service.addOperator("p2p_usdc_acred", contract.address, sender=securitize_owner)
    return contract


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e12))


@pytest.fixture
def registrar_connector(
    registrar_connector_def,
    vault_registrar,
    vault_registrar_admin,
    p2p_usdc_acred,
    owner,
    securitize_trust_service,
    securitize_owner,
):
    TRUST_ROLE_TRANSFER_AGENT = 8

    contract = registrar_connector_def.deploy(vault_registrar.address, [p2p_usdc_acred.address])

    vault_registrar.grantRole(vault_registrar.OPERATOR_ROLE(), contract.address, sender=vault_registrar_admin)

    securitize_trust_service.addOperator("zharta_connector", contract.address, sender=securitize_owner)
    assert securitize_trust_service.getEntityByOperator(contract.address) == "zharta_connector"

    # securitize_trust_service.addEntity("zharta_connector", securitize_owner, sender=securitize_owner)
    # securitize_trust_service.addResource("zharta_connector", vault_registrar.address, sender=securitize_owner)
    securitize_trust_service.setRole(vault_registrar.address, TRUST_ROLE_TRANSFER_AGENT, sender=securitize_owner)

    p2p_usdc_acred.change_vault_registrar(contract.address, sender=owner)
    return contract


@pytest.fixture
def sec_borrower(securitize_registry, p2p_usdc_acred, securitize_owner, now):
    return "0x81aF1E160c290E8Fff6381CCF67981f012Cf1009"


def test_create_loan(
    p2p_usdc_acred,
    sec_borrower,
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
    borrower = sec_borrower
    # Generate KYC for the actual borrower and lender
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)

    # The borrower already has ACRED (sec_borrower is a known holder)
    boa.env.set_balance(borrower, 10**21)

    # Get the borrower's ACRED balance to determine how much we can use
    borrower_acred_balance = acred.balanceOf(borrower)
    # Use 10% of borrower's balance or a minimum of 1e15 (0.001 ACRED)
    collateral_amount = min(borrower_acred_balance // 10, int(1e17))
    if collateral_amount == 0:
        collateral_amount = int(1e15)  # Minimum amount for test

    # Adjust principal to maintain LTV within limits (ACRED price is ~$10, so 1e17 ACRED = ~$1)
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

    # Approve collateral
    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    borrower_collateral_balance_before = acred.balanceOf(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    # Create loan
    loan_id = p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)
    event = get_last_event(p2p_usdc_acred, "LoanCreated")

    # Verify loan was created
    assert p2p_usdc_acred.loans(loan_id) != ZERO_BYTES32, "Loan should be recorded"

    # event assertions
    assert event.id == loan_id
    assert event.amount == principal
    assert event.borrower == borrower
    assert event.lender == lender
    assert event.collateral_amount == collateral_amount

    # Verify vault registration - this is the key test for vault_registrar functionality
    vault_addr = p2p_usdc_acred.wallet_to_vault(borrower)
    assert vault_registrar.isRegistered(vault_addr, borrower), "Vault should be registered with registrar"

    # Balance assertions
    assert acred.balanceOf(vault_addr) == collateral_amount
    assert acred.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount
    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_acred.commited_liquidity(liquidity_key) == principal
