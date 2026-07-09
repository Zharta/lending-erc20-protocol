import boa
import pytest
from eth_account import Account

from tests.p2p_erc20_securitize.conftest_base import sign_register_vault

ZERO_ADDRESS = boa.eval("empty(address)")

# EIP-712 constants matching the V2 connector contract
DOMAIN_TYPE_HASH = bytes.fromhex(
    "8b73c3c69bb8fe3d512ecc4cf759cc79239f7b179b0ffacaa9a75d522b39400f"
)  # keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")

REGISTER_TYPEHASH = bytes.fromhex(
    "6a948757026098a65c96cac1826cba44e5facc2ed1ad7a7a7d9b1057b0830e10"
)  # keccak256("RegisterVault(address investor,address operator,address token,uint256 nonce,uint256 deadline)")

MALLEABILITY_THRESHOLD = 57896044618658097711785492504343953926418782139537452191302581570759080747168


# ============================================================
# Initialization tests
# ============================================================


def test_init_owner(v2_connector, owner):
    assert v2_connector.owner() == owner


def test_init_vault_registrar(v2_connector, v2_vault_registrar):
    assert v2_connector.vault_registrar() == v2_vault_registrar.address


def test_init_authorized_contracts_vaulted(v2_connector, p2p_vaulted):
    assert v2_connector.authorized_contracts(p2p_vaulted.address) is True


def test_init_authorized_contracts_securitize(v2_connector, p2p_securitize):
    assert v2_connector.authorized_contracts(p2p_securitize.address) is True


def test_init_unauthorized_address_is_false(v2_connector):
    random_addr = boa.env.generate_address("random")
    assert v2_connector.authorized_contracts(random_addr) is False


def test_init_investor_signatures_deadline_empty(v2_connector):
    random_addr = boa.env.generate_address("random_investor")
    sig = v2_connector.investor_signatures(random_addr)
    assert sig[0] == 0


def test_init_investor_signatures_signature_empty(v2_connector):
    random_addr = boa.env.generate_address("random_investor2")
    sig = v2_connector.investor_signatures(random_addr)
    assert sig[1] == (0, 0, 0)


# ============================================================
# change_authorized_contract tests
# ============================================================


def test_change_authorized_contract_authorize(v2_connector, owner):
    new_contract = boa.env.generate_address("new_contract_v2")
    v2_connector.change_authorized_contract(new_contract, True, sender=owner)
    assert v2_connector.authorized_contracts(new_contract) is True


def test_change_authorized_contract_deauthorize(v2_connector_def, v2_vault_registrar, p2p_vaulted, owner):
    c = v2_connector_def.deploy(v2_vault_registrar.address)
    c.change_authorized_contract(p2p_vaulted.address, True, sender=owner)
    assert c.authorized_contracts(p2p_vaulted.address) is True

    c.change_authorized_contract(p2p_vaulted.address, False, sender=owner)
    assert c.authorized_contracts(p2p_vaulted.address) is False


def test_change_authorized_contract_deauthorize_does_not_affect_others(
    v2_connector_def, v2_vault_registrar, p2p_vaulted, p2p_securitize, owner
):
    c = v2_connector_def.deploy(v2_vault_registrar.address)
    c.change_authorized_contract(p2p_vaulted.address, True, sender=owner)
    c.change_authorized_contract(p2p_securitize.address, True, sender=owner)

    c.change_authorized_contract(p2p_vaulted.address, False, sender=owner)
    assert c.authorized_contracts(p2p_securitize.address) is True


def test_change_authorized_contract_event(v2_connector_def, v2_vault_registrar, p2p_vaulted, owner):
    c = v2_connector_def.deploy(v2_vault_registrar.address)
    c.change_authorized_contract(p2p_vaulted.address, True, sender=owner)

    events = c.get_logs()
    assert len(events) == 1
    event = events[0]
    assert event.contract_address == p2p_vaulted.address
    assert event.authorized is True


def test_change_authorized_contract_reverts_if_not_owner(v2_connector, other):
    with boa.reverts("not owner"):
        v2_connector.change_authorized_contract(other, True, sender=other)


# ============================================================
# set_investor_signature tests
# ============================================================


def test_set_investor_signature_stores_deadline(v2_connector, v2_vault_registrar, investor_account, investor):
    deadline = boa.eval("block.timestamp") + 3600

    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    stored = v2_connector.investor_signatures(investor)
    assert stored[0] == deadline


def test_set_investor_signature_stores_signature(v2_connector, v2_vault_registrar, investor_account, investor):
    deadline = boa.eval("block.timestamp") + 3600

    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    stored = v2_connector.investor_signatures(investor)
    assert stored[1] == (v, r, s)


def test_set_investor_signature_zero_deadline_clears_signature(v2_connector, v2_vault_registrar, investor_account, investor):
    deadline = boa.eval("block.timestamp") + 3600
    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)
    assert v2_connector.investor_signatures(investor)[1] == (v, r, s)

    # Investor revokes stored signature by passing deadline=0
    v2_connector.set_investor_signature(0, (0, 0, 0), sender=investor)

    assert v2_connector.investor_signatures(investor)[0] == 0
    assert v2_connector.investor_signatures(investor)[1] == (0, 0, 0)


def test_set_investor_signature_reverts_if_expired(v2_connector, investor):
    expired_deadline = boa.eval("block.timestamp") - 1

    with boa.reverts("signature expired"):
        v2_connector.set_investor_signature(expired_deadline, (27, 1, 1), sender=investor)


def test_set_investor_signature_reverts_if_invalid_signature(v2_connector, v2_vault_registrar, investor):
    deadline = boa.eval("block.timestamp") + 3600

    # Use a bogus signature that won't recover to investor's address
    # r and s must be non-zero and s below malleability threshold
    with boa.reverts("invalid signature"):
        v2_connector.set_investor_signature(deadline, (27, 12345, 6789), sender=investor)


def test_set_investor_signature_reverts_if_wrong_signer(v2_connector, v2_vault_registrar, investor):
    deadline = boa.eval("block.timestamp") + 3600

    # Sign with a different account than the investor calling set_investor_signature
    wrong_signer = Account.create()
    v, r, s = sign_register_vault(wrong_signer, v2_connector.address, v2_vault_registrar, deadline)

    with boa.reverts("invalid signature"):
        v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)


def test_set_investor_signature_reverts_if_s_above_malleability_threshold(v2_connector, investor):
    deadline = boa.eval("block.timestamp") + 3600

    # s value above the malleability threshold
    high_s = MALLEABILITY_THRESHOLD + 1
    with boa.reverts("invalid signature"):
        v2_connector.set_investor_signature(deadline, (27, 12345, high_s), sender=investor)


def test_set_investor_signature_overwrites_deadline(v2_connector, v2_vault_registrar, investor_account, investor):
    deadline1 = boa.eval("block.timestamp") + 3600
    v1, r1, s1 = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline1)
    v2_connector.set_investor_signature(deadline1, (v1, r1, s1), sender=investor)
    assert v2_connector.investor_signatures(investor)[0] == deadline1

    deadline2 = boa.eval("block.timestamp") + 7200
    v2, r2, s2 = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline2)
    v2_connector.set_investor_signature(deadline2, (v2, r2, s2), sender=investor)

    assert v2_connector.investor_signatures(investor)[0] == deadline2


def test_set_investor_signature_overwrites_signature(v2_connector, v2_vault_registrar, investor_account, investor):
    deadline1 = boa.eval("block.timestamp") + 3600
    v1, r1, s1 = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline1)
    v2_connector.set_investor_signature(deadline1, (v1, r1, s1), sender=investor)
    assert v2_connector.investor_signatures(investor)[1] == (v1, r1, s1)

    deadline2 = boa.eval("block.timestamp") + 7200
    v2, r2, s2 = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline2)
    v2_connector.set_investor_signature(deadline2, (v2, r2, s2), sender=investor)

    assert v2_connector.investor_signatures(investor)[1] == (v2, r2, s2)


# ============================================================
# register_vault tests
# ============================================================


def test_register_vault(v2_connector, v2_vault_registrar, p2p_vaulted, investor_account, investor):
    borrower = investor
    deadline = boa.eval("block.timestamp") + 3600

    # Store signature for investor
    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    vault_addr = p2p_vaulted.wallet_to_vault(borrower)

    # Precondition: vault not yet registered
    assert v2_vault_registrar.isRegistered(vault_addr, borrower) is False

    v2_connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)

    assert v2_vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_forwards_deadline(v2_connector, v2_vault_registrar, p2p_vaulted, investor_account, investor):
    borrower = investor
    deadline = boa.eval("block.timestamp") + 7200

    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    vault_addr = p2p_vaulted.wallet_to_vault(borrower)
    v2_connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)

    reg = v2_vault_registrar.registrations(vault_addr, borrower)
    assert reg[1] == deadline


def test_register_vault_forwards_signature_bytes(v2_connector, v2_vault_registrar, p2p_vaulted, investor_account, investor):
    borrower = investor
    deadline = boa.eval("block.timestamp") + 7200

    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    vault_addr = p2p_vaulted.wallet_to_vault(borrower)
    v2_connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)

    reg = v2_vault_registrar.registrations(vault_addr, borrower)
    expected_sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big") + v.to_bytes(1, "big")
    assert reg[2] == expected_sig_bytes


def test_register_vault_skips_if_already_registered(v2_connector, v2_vault_registrar, p2p_vaulted, investor_account, investor):
    """When vault is already registered, register_vault should not call registerVault again."""
    borrower = investor
    deadline = boa.eval("block.timestamp") + 3600

    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    vault_addr = p2p_vaulted.wallet_to_vault(borrower)

    # First registration (may already be registered from a prior test -- that's fine)
    v2_connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)
    assert v2_vault_registrar.isRegistered(vault_addr, borrower) is True

    # Clear the stored signature
    v2_connector.set_investor_signature(0, (0, 0, 0), sender=investor)

    # Second registration attempt should be a no-op (already registered)
    v2_connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)

    # Still registered
    assert v2_vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_reverts_if_not_authorized(v2_connector):
    unauthorized = boa.env.generate_address("unauthorized_v2")
    vault_addr = boa.env.generate_address("vault_v2")
    investor_addr = boa.env.generate_address("investor_v2")

    with boa.reverts("not authorized"):
        v2_connector.register_vault(vault_addr, investor_addr, sender=unauthorized)


def test_register_vault_from_securitize(v2_connector, v2_vault_registrar, p2p_securitize, investor_account, investor):
    """Verify register_vault works when called from an authorized securitize contract."""
    borrower = investor
    vault_id = 0
    vault_addr = p2p_securitize.vault_id_to_vault(borrower, vault_id)
    deadline = boa.eval("block.timestamp") + 3600

    v, r, s = sign_register_vault(investor_account, v2_connector.address, v2_vault_registrar, deadline)
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=investor)

    v2_connector.register_vault(vault_addr, borrower, sender=p2p_securitize.address)

    assert v2_vault_registrar.isRegistered(vault_addr, borrower) is True


def test_register_vault_reverts_if_no_signature(v2_connector, v2_vault_registrar, p2p_vaulted):
    borrower = boa.env.generate_address("investor_no_sig")
    vault_addr = p2p_vaulted.wallet_to_vault(borrower)

    # No signature stored for borrower — registrar should reject the empty signature
    with boa.reverts():
        v2_connector.register_vault(vault_addr, borrower, sender=p2p_vaulted.address)


# ============================================================
# set_investor_signature EIP-1271 (smart contract wallet) tests
# ============================================================


def test_set_investor_signature_stores_deadline_eip1271(
    v2_connector, v2_vault_registrar, sc_wallet_contract_def, investor_account
):
    sc_wallet = sc_wallet_contract_def.deploy(investor_account.address)
    boa.env.set_balance(sc_wallet.address, 10**21)
    deadline = boa.eval("block.timestamp") + 3600

    v, r, s = sign_register_vault(
        investor_account, v2_connector.address, v2_vault_registrar, deadline, investor_address=sc_wallet.address
    )
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=sc_wallet.address)

    assert v2_connector.investor_signatures(sc_wallet.address)[0] == deadline


def test_set_investor_signature_stores_signature_eip1271(
    v2_connector, v2_vault_registrar, sc_wallet_contract_def, investor_account
):
    sc_wallet = sc_wallet_contract_def.deploy(investor_account.address)
    boa.env.set_balance(sc_wallet.address, 10**21)
    deadline = boa.eval("block.timestamp") + 3600

    v, r, s = sign_register_vault(
        investor_account, v2_connector.address, v2_vault_registrar, deadline, investor_address=sc_wallet.address
    )
    v2_connector.set_investor_signature(deadline, (v, r, s), sender=sc_wallet.address)

    assert v2_connector.investor_signatures(sc_wallet.address)[1] == (v, r, s)


def test_set_investor_signature_reverts_if_eip1271_invalid(v2_connector, v2_vault_registrar, sc_wallet_contract_def):
    wrong_owner = Account.create()
    sc_wallet = sc_wallet_contract_def.deploy(wrong_owner.address)
    boa.env.set_balance(sc_wallet.address, 10**21)
    deadline = boa.eval("block.timestamp") + 3600

    # Sign with a different key than the SC wallet's owner — ecrecover will
    # recover other_account.address which != wrong_owner, so is_valid_signature returns 0x00000000
    other_account = Account.create()
    v, r, s = sign_register_vault(
        other_account, v2_connector.address, v2_vault_registrar, deadline, investor_address=sc_wallet.address
    )

    with boa.reverts("invalid signature"):
        v2_connector.set_investor_signature(deadline, (v, r, s), sender=sc_wallet.address)
