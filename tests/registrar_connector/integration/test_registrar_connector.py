import boa
import pytest


def test_register_vault_vaulted(connector, p2p_vaulted, vault_registrar, whitelisted_borrower):
    borrower = whitelisted_borrower
    vault_addr = p2p_vaulted.wallet_to_vault(borrower)

    connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_securitize(connector, p2p_securitize, vault_registrar, whitelisted_borrower):
    borrower = whitelisted_borrower
    vault_id = 0
    vault_addr = p2p_securitize.vault_id_to_vault(borrower, vault_id)

    connector.register_vault(vault_addr, borrower, sender=p2p_securitize.address)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_not_authorized(connector):
    unauthorized = boa.env.generate_address("unauthorized")
    vault_addr = boa.env.generate_address("vault")
    investor = boa.env.generate_address("investor")

    with boa.reverts("not authorized"):
        connector.register_vault(vault_addr, investor, sender=unauthorized)
