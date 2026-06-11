#
# This test is temporary. As soon as the registrar v2 is on mainnet, replace it by a test in the p2p_erc20_securitize suite with the same logic, and remove the registrar_connector suite.
#
#

import boa
import pytest

from tests.p2p_erc20_securitize.conftest_base import Offer, sign_offer

from .conftest import sign_register_vault

BPS = 10000


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract):
    return kyc_for(lender, kyc_validator_contract.address)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract):
    return kyc_for(borrower, kyc_validator_contract.address)


def test_create_loan_registers_vault_with_registrar(
    p2p_usdc_acred,
    borrower,
    borrower_account,
    now,
    lender,
    lender_key,
    kyc_borrower,
    kyc_lender,
    acred,
    usdc,
    registrar_connector,
    vault_registrar,
):
    vault_id = p2p_usdc_acred.vault_count(borrower)

    principal = 1000 * int(1e9)
    collateral_amount = 95 * int(1e6)
    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_acred.payment_token(),
        collateral_token=p2p_usdc_acred.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_acred.address)

    # The borrower (Securitize investor) authorizes the connector to register vaults
    # on its behalf by storing an EIP-712 RegisterVault signature.
    deadline = now + 3600
    v, r, s = sign_register_vault(borrower_account, registrar_connector.address, vault_registrar, deadline)
    registrar_connector.set_investor_signature(deadline, (v, r, s), sender=borrower)

    acred.approve(p2p_usdc_acred.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_acred.address, principal, sender=lender)

    # Precondition: the vault is not yet registered
    vault_addr = p2p_usdc_acred.wallet_to_vault(borrower)
    assert vault_registrar.isRegistered(vault_addr, borrower) is False

    p2p_usdc_acred.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    vault_addr = p2p_usdc_acred.vault_id_to_vault(borrower, vault_id)
    assert vault_registrar.isRegistered(vault_addr, borrower) is True
    assert acred.balanceOf(vault_addr) == collateral_amount
