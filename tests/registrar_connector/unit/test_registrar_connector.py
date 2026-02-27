import boa
import pytest

ZERO_ADDRESS = boa.eval("empty(address)")


def test_init_version(connector):
    assert connector.VERSION() == "SecRegV1Connector.20260127"


def test_init_owner(connector, owner):
    assert connector.owner() == owner


def test_init_vault_registrar(connector, vault_registrar):
    assert connector.vault_registrar() == vault_registrar.address


def test_init_authorized_contracts(connector, p2p_vaulted, p2p_securitize):
    assert connector.authorized_contracts(p2p_vaulted.address) is True
    assert connector.authorized_contracts(p2p_securitize.address) is True


def test_init_empty_address_skipped(connector_def, vault_registrar, p2p_vaulted, owner):
    c = connector_def.deploy(
        vault_registrar.address,
        [p2p_vaulted.address, ZERO_ADDRESS],
    )
    assert c.authorized_contracts(p2p_vaulted.address) is True
    assert c.authorized_contracts(ZERO_ADDRESS) is False


def test_change_authorized_contracts_authorize(connector, owner, accounts):
    new_contract = accounts[5]
    connector.change_authorized_contracts(
        [(new_contract, True)],
        sender=owner,
    )
    assert connector.authorized_contracts(new_contract) is True


def test_change_authorized_contracts_deauthorize(connector_def, vault_registrar, p2p_vaulted, p2p_securitize, owner):
    c = connector_def.deploy(
        vault_registrar.address,
        [p2p_vaulted.address, p2p_securitize.address],
    )
    assert c.authorized_contracts(p2p_vaulted.address) is True

    c.change_authorized_contracts(
        [(p2p_vaulted.address, False)],
        sender=owner,
    )
    assert c.authorized_contracts(p2p_vaulted.address) is False
    assert c.authorized_contracts(p2p_securitize.address) is True


def test_change_authorized_contracts_event(connector_def, vault_registrar, p2p_vaulted, owner):
    c = connector_def.deploy(vault_registrar.address, [])
    c.change_authorized_contracts(
        [(p2p_vaulted.address, True)],
        sender=owner,
    )
    events = c.get_logs()
    assert len(events) == 1
    event = events[0]
    assert event.contracts == [(p2p_vaulted.address, True)]


def test_change_authorized_contracts_not_owner(connector, other):
    with boa.reverts("not owner"):
        connector.change_authorized_contracts(
            [(other, True)],
            sender=other,
        )


def test_register_vault(connector, p2p_vaulted, vault_registrar, accounts):
    borrower = accounts[0]
    vault_addr = p2p_vaulted.wallet_to_vault(borrower)

    connector.register_vault(p2p_vaulted.address, sender=borrower)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_not_authorized(connector, accounts):
    borrower = accounts[1]
    unauthorized_contract = accounts[6]

    with boa.reverts("not authorized"):
        connector.register_vault(unauthorized_contract, sender=borrower)


def test_register_vault_with_id(connector, p2p_securitize, vault_registrar, accounts):
    borrower = accounts[2]
    vault_id = 0
    vault_addr = p2p_securitize.vault_id_to_vault(borrower, vault_id)

    connector.register_vault_with_id(p2p_securitize.address, vault_id, sender=borrower)

    assert vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_with_id_not_authorized(connector, accounts):
    borrower = accounts[3]
    unauthorized_contract = accounts[7]

    with boa.reverts("not authorized"):
        connector.register_vault_with_id(unauthorized_contract, 0, sender=borrower)
