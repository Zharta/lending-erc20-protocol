from hashlib import sha3_256
from itertools import starmap

import boa
import pytest

from ...conftest_base import ZERO_ADDRESS, get_last_event

BPS = 10000


def test_initial_state(
    p2p_usdc_weth,
    oracle,
    kyc_validator_contract,
    kyc_validator,
    weth,
    usdc,
    owner,
):
    assert p2p_usdc_weth.owner() == owner
    assert p2p_usdc_weth.payment_token() == usdc.address
    assert p2p_usdc_weth.collateral_token() == weth.address
    assert p2p_usdc_weth.oracle_addr() == oracle.address
    assert p2p_usdc_weth.kyc_validator_addr() == kyc_validator_contract.address
    assert p2p_usdc_weth.protocol_upfront_fee() == 0
    assert p2p_usdc_weth.protocol_settlement_fee() == 0
    assert p2p_usdc_weth.protocol_wallet() == owner
    assert p2p_usdc_weth.max_protocol_settlement_fee() == 10000
    assert p2p_usdc_weth.partial_liquidation_fee() == 0

    assert kyc_validator_contract.owner() == owner
    assert kyc_validator_contract.validator() == kyc_validator


def test_set_protocol_fee_reverts_if_not_owner(p2p_usdc_weth):
    with boa.reverts():
        p2p_usdc_weth.set_protocol_fee(1, 1, sender=boa.env.generate_address("random"))


def test_set_protocol_fee_reverts_if_gt_max(p2p_usdc_weth, owner):
    with boa.reverts("upfront fee exceeds max"):
        p2p_usdc_weth.set_protocol_fee(p2p_usdc_weth.max_protocol_upfront_fee() + 1, 0, sender=owner)

    with boa.reverts("settlement fee exceeds max"):
        p2p_usdc_weth.set_protocol_fee(0, p2p_usdc_weth.max_protocol_settlement_fee() + 1, sender=owner)


def test_set_protocol_fee(p2p_usdc_weth, owner):
    upfront_fee = 1
    settlement_fee = 1
    p2p_usdc_weth.set_protocol_fee(upfront_fee, settlement_fee, sender=owner)
    assert p2p_usdc_weth.protocol_upfront_fee() == upfront_fee
    assert p2p_usdc_weth.protocol_settlement_fee() == settlement_fee

    p2p_usdc_weth.set_protocol_fee(0, 0, sender=owner)
    assert p2p_usdc_weth.protocol_upfront_fee() == 0
    assert p2p_usdc_weth.protocol_settlement_fee() == 0


def test_set_protocol_fee_logs_event(p2p_usdc_weth, owner):
    old_upfront_fee = p2p_usdc_weth.protocol_upfront_fee()
    old_settlement_fee = p2p_usdc_weth.protocol_settlement_fee()
    new_upfront_fee = old_upfront_fee + 1
    new_settlement_fee = old_settlement_fee + 1

    p2p_usdc_weth.set_protocol_fee(new_upfront_fee, new_settlement_fee, sender=owner)
    event = get_last_event(p2p_usdc_weth, "ProtocolFeeSet")

    assert event.old_upfront_fee == old_upfront_fee
    assert event.old_settlement_fee == old_settlement_fee
    assert event.new_upfront_fee == new_upfront_fee
    assert event.new_settlement_fee == new_settlement_fee


def test_change_protocol_wallet_reverts_if_not_owner(p2p_usdc_weth):
    new_wallet = boa.env.generate_address("new_wallet")
    with boa.reverts():
        p2p_usdc_weth.change_protocol_wallet(new_wallet, sender=boa.env.generate_address("random"))


def test_change_protocol_wallet_reverts_if_zero_address(p2p_usdc_weth, owner):
    with boa.reverts():
        p2p_usdc_weth.change_protocol_wallet(ZERO_ADDRESS, sender=owner)


def test_change_protocol_wallet(p2p_usdc_weth, owner):
    new_wallet = boa.env.generate_address("new_wallet")
    p2p_usdc_weth.change_protocol_wallet(new_wallet, sender=owner)

    assert p2p_usdc_weth.protocol_wallet() == new_wallet


def test_change_protocol_wallet_logs_event(p2p_usdc_weth, owner):
    new_wallet = boa.env.generate_address("new_wallet")
    p2p_usdc_weth.change_protocol_wallet(new_wallet, sender=owner)
    event = get_last_event(p2p_usdc_weth, "ProtocolWalletChanged")

    assert event.old_wallet == owner
    assert event.new_wallet == new_wallet


def test_set_proxy_authorization_reverts_if_not_owner(p2p_usdc_weth):
    proxy = boa.env.generate_address("proxy")
    random = boa.env.generate_address("random")
    with boa.reverts():
        p2p_usdc_weth.set_proxy_authorization(proxy, True, sender=random)


def test_set_proxy_authorization(p2p_usdc_weth, owner):
    proxy = boa.env.generate_address("proxy")
    p2p_usdc_weth.set_proxy_authorization(proxy, True, sender=owner)
    assert p2p_usdc_weth.authorized_proxies(proxy) is True

    p2p_usdc_weth.set_proxy_authorization(proxy, False, sender=owner)
    assert p2p_usdc_weth.authorized_proxies(proxy) is False


def test_set_proxy_authorization_logs_event(p2p_usdc_weth, owner):
    proxy = boa.env.generate_address("proxy")
    p2p_usdc_weth.set_proxy_authorization(proxy, True, sender=owner)
    event = get_last_event(p2p_usdc_weth, "ProxyAuthorizationChanged")

    assert event.proxy == proxy
    assert event.value is True


def test_propose_owner_reverts_if_wrong_caller(p2p_usdc_weth):
    new_owner = boa.env.generate_address("new_owner")
    with boa.reverts():
        p2p_usdc_weth.propose_owner(new_owner, sender=new_owner)


def test_propose_owner_reverts_if_zero_address(p2p_usdc_weth, owner):
    with boa.reverts():
        p2p_usdc_weth.propose_owner(ZERO_ADDRESS, sender=owner)


def test_propose_owner(p2p_usdc_weth, owner):
    new_owner = boa.env.generate_address("new_owner")
    p2p_usdc_weth.propose_owner(new_owner, sender=owner)

    assert p2p_usdc_weth.proposed_owner() == new_owner


def test_propose_owner_logs_event(p2p_usdc_weth, owner):
    new_owner = boa.env.generate_address("new_owner")
    p2p_usdc_weth.propose_owner(new_owner, sender=owner)
    event = get_last_event(p2p_usdc_weth, "OwnerProposed")

    assert event.owner == owner
    assert event.proposed_owner == new_owner


def test_kyc_validator_propose_owner_reverts_if_wrong_caller(kyc_validator_contract):
    new_owner = boa.env.generate_address("new_owner")
    with boa.reverts("not owner"):
        kyc_validator_contract.propose_owner(new_owner, sender=new_owner)


def test_kyc_validator_propose_owner_reverts_if_zero_address(kyc_validator_contract, owner):
    with boa.reverts("address is zero"):
        kyc_validator_contract.propose_owner(ZERO_ADDRESS, sender=owner)


def test_kyc_validator_propose_owner(kyc_validator_contract, owner):
    new_owner = boa.env.generate_address("new_owner")
    kyc_validator_contract.propose_owner(new_owner, sender=owner)

    assert kyc_validator_contract.proposed_owner() == new_owner


def test_kyc_validator_propose_owner_logs_event(kyc_validator_contract, owner):
    new_owner = boa.env.generate_address("new_owner")
    kyc_validator_contract.propose_owner(new_owner, sender=owner)
    event = get_last_event(kyc_validator_contract, "OwnerProposed")

    assert event.owner == owner
    assert event.proposed_owner == new_owner


def test_claim_ownership_reverts_if_wrong_caller(p2p_usdc_weth, owner):
    new_owner = boa.env.generate_address("new_owner")
    p2p_usdc_weth.propose_owner(new_owner, sender=owner)

    with boa.reverts():
        p2p_usdc_weth.claim_ownership(sender=owner)


def test_claim_ownership(p2p_usdc_weth, owner):
    new_owner = boa.env.generate_address("new_owner")
    p2p_usdc_weth.propose_owner(new_owner, sender=owner)

    p2p_usdc_weth.claim_ownership(sender=new_owner)

    assert p2p_usdc_weth.proposed_owner() == ZERO_ADDRESS
    assert p2p_usdc_weth.owner() == new_owner


def test_claim_ownership_logs_event(p2p_usdc_weth, owner):
    new_owner = boa.env.generate_address("new_owner")
    p2p_usdc_weth.propose_owner(new_owner, sender=owner)

    p2p_usdc_weth.claim_ownership(sender=new_owner)
    event = get_last_event(p2p_usdc_weth, "OwnershipTransferred")

    assert event.old_owner == owner
    assert event.new_owner == new_owner


def test_kyc_validator_claim_ownership_reverts_if_wrong_caller(kyc_validator_contract, owner):
    new_owner = boa.env.generate_address("new_owner")
    kyc_validator_contract.propose_owner(new_owner, sender=owner)

    with boa.reverts("not the proposed owner"):
        kyc_validator_contract.claim_ownership(sender=owner)


def test_kyc_validator_claim_ownership(kyc_validator_contract, owner):
    new_owner = boa.env.generate_address("new_owner")
    kyc_validator_contract.propose_owner(new_owner, sender=owner)

    kyc_validator_contract.claim_ownership(sender=new_owner)

    assert kyc_validator_contract.proposed_owner() == ZERO_ADDRESS
    assert kyc_validator_contract.owner() == new_owner


def test_kyc_validator_claim_ownership_logs_event(kyc_validator_contract, owner):
    new_owner = boa.env.generate_address("new_owner")
    kyc_validator_contract.propose_owner(new_owner, sender=owner)

    kyc_validator_contract.claim_ownership(sender=new_owner)
    event = get_last_event(kyc_validator_contract, "OwnershipTransferred")

    assert event.old_owner == owner
    assert event.new_owner == new_owner


def test_set_partial_liquidation_fee_reverts_if_not_owner(p2p_usdc_weth):
    with boa.reverts():
        p2p_usdc_weth.set_partial_liquidation_fee(1, sender=boa.env.generate_address("random"))


def test_set_partial_liquidation_fee_reverts_if_gt_max(p2p_usdc_weth, owner):
    with boa.reverts("fee exceeds BPS"):
        p2p_usdc_weth.set_partial_liquidation_fee(BPS + 1, sender=owner)


def test_set_partial_liquidation_fee(p2p_usdc_weth, owner):
    new_partial_liquidation_fee = 1234
    p2p_usdc_weth.set_partial_liquidation_fee(new_partial_liquidation_fee, sender=owner)
    assert p2p_usdc_weth.partial_liquidation_fee() == new_partial_liquidation_fee


def test_set_partial_liquidation_fee_logs_event(p2p_usdc_weth, owner):
    old_partial_liquidation_fee = p2p_usdc_weth.partial_liquidation_fee()
    new_partial_liquidation_fee = old_partial_liquidation_fee + 1

    p2p_usdc_weth.set_partial_liquidation_fee(new_partial_liquidation_fee, sender=owner)
    event = get_last_event(p2p_usdc_weth, "PartialLiquidationFeeSet")

    assert event.old_fee == old_partial_liquidation_fee
    assert event.new_fee == new_partial_liquidation_fee
