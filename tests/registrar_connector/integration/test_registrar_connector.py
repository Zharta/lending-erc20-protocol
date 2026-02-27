import boa
import pytest


def test_register_vault_vaulted(connector, p2p_vaulted, vault_registrar, whitelisted_borrower):
    borrower = whitelisted_borrower
    vault_addr = p2p_vaulted.wallet_to_vault(borrower)

    connector.register_vault(p2p_vaulted.address, sender=borrower)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_with_id_securitize(connector, p2p_securitize, vault_registrar, whitelisted_borrower):
    borrower = whitelisted_borrower
    vault_id = 0
    vault_addr = p2p_securitize.vault_id_to_vault(borrower, vault_id)

    connector.register_vault_with_id(p2p_securitize.address, vault_id, sender=borrower)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_without_id_securitize(connector, p2p_securitize, vault_registrar, whitelisted_borrower):
    borrower = whitelisted_borrower
    vault_id = 0
    vault_addr = p2p_securitize.wallet_to_vault(borrower)

    connector.register_vault_with_id(p2p_securitize.address, vault_id, sender=borrower)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_not_authorized(connector, accounts):
    borrower = accounts[2]
    unauthorized_contract = accounts[5]

    with boa.reverts("not authorized"):
        connector.register_vault(unauthorized_contract, sender=borrower)
