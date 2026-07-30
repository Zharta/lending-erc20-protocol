from hashlib import sha3_256
from itertools import starmap

import boa
import pytest

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    get_last_event,
    sign_offer,
)

BPS = 10000


def test_initial_state(
    p2p_usdc_weth,
    oracle,
    kyc_validator_contract,
    kyc_validator,
    weth,
    usdc,
    owner,
    redemption_wallet,
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
    assert p2p_usdc_weth.redemption_addr() == redemption_wallet
    assert p2p_usdc_weth.mint_addr() == ZERO_ADDRESS
    assert p2p_usdc_weth.vault_registrar() == ZERO_ADDRESS

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


def test_kyc_validator_set_validator_reverts_if_wrong_caller(kyc_validator_contract):
    random = boa.env.generate_address("random")
    with boa.reverts("not owner"):
        kyc_validator_contract.set_validator(random, sender=random)


def test_kyc_validator_set_validator_reverts_if_zero_address(kyc_validator_contract, owner):
    with boa.reverts("empty validator"):
        kyc_validator_contract.set_validator(ZERO_ADDRESS, sender=owner)


def test_kyc_validator_set_validator(kyc_validator_contract, owner):
    new_validator = boa.env.generate_address("new_validator")
    kyc_validator_contract.set_validator(new_validator, sender=owner)

    assert kyc_validator_contract.validator() == new_validator


def test_kyc_validator_set_validator_logs_event(kyc_validator_contract, owner):
    new_validator = boa.env.generate_address("new_validator")
    old_validator = kyc_validator_contract.validator()

    kyc_validator_contract.set_validator(new_validator, sender=owner)
    event = get_last_event(kyc_validator_contract, "ValidatorSet")

    assert event.old_validator == old_validator
    assert event.new_validator == new_validator


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


def test_set_full_liquidation_fee_reverts_if_not_owner(p2p_usdc_weth):
    random = boa.env.generate_address("random")
    with boa.reverts():
        p2p_usdc_weth.set_full_liquidation_fee(100, sender=random)


def test_set_full_liquidation_fee_reverts_if_gt_max(p2p_usdc_weth, owner):
    with boa.reverts("fee exceeds BPS"):
        p2p_usdc_weth.set_full_liquidation_fee(BPS + 1, sender=owner)


def test_set_full_liquidation_fee(p2p_usdc_weth, owner):
    new_fee = 500
    p2p_usdc_weth.set_full_liquidation_fee(new_fee, sender=owner)
    assert p2p_usdc_weth.full_liquidation_fee() == new_fee


def test_set_full_liquidation_fee_logs_event(p2p_usdc_weth, owner):
    old_fee = p2p_usdc_weth.full_liquidation_fee()
    new_fee = 500

    p2p_usdc_weth.set_full_liquidation_fee(new_fee, sender=owner)
    event = get_last_event(p2p_usdc_weth, "FullLiquidationFeeSet")

    assert event.old_fee == old_fee
    assert event.new_fee == new_fee


def test_set_transfer_agent_reverts_if_not_owner_or_agent(p2p_usdc_weth, transfer_agent):
    random = boa.env.generate_address("random")
    with boa.reverts():
        p2p_usdc_weth.set_transfer_agent(boa.env.generate_address("new_agent"), sender=random)


def test_set_transfer_agent_by_owner(p2p_usdc_weth, owner, transfer_agent):
    new_agent = boa.env.generate_address("new_agent")
    p2p_usdc_weth.set_transfer_agent(new_agent, sender=owner)
    assert p2p_usdc_weth.transfer_agent() == new_agent


def test_set_transfer_agent_by_current_agent(p2p_usdc_weth, owner, transfer_agent):
    # First set a transfer agent
    initial_agent = boa.env.generate_address("initial_agent")
    p2p_usdc_weth.set_transfer_agent(initial_agent, sender=owner)

    # Then change it by the current agent
    new_agent = boa.env.generate_address("new_agent")
    p2p_usdc_weth.set_transfer_agent(new_agent, sender=initial_agent)
    assert p2p_usdc_weth.transfer_agent() == new_agent


def test_set_transfer_agent_logs_event(p2p_usdc_weth, owner, transfer_agent):
    new_agent = boa.env.generate_address("new_agent")
    old_agent = p2p_usdc_weth.transfer_agent()

    p2p_usdc_weth.set_transfer_agent(new_agent, sender=owner)
    event = get_last_event(p2p_usdc_weth, "TransferAgentChanged")

    assert event.old_agent == old_agent
    assert event.new_agent == new_agent
    assert event.by == owner


# MultiVault-specific tests for redemption_addr
def test_set_redemption_addr_reverts_if_not_owner(p2p_usdc_weth):
    random = boa.env.generate_address("random")
    new_addr = boa.env.generate_address("new_addr")
    with boa.reverts():
        p2p_usdc_weth.set_redemption_addr(new_addr, sender=random)


def test_set_redemption_addr(p2p_usdc_weth, owner):
    new_addr = boa.env.generate_address("new_addr")
    p2p_usdc_weth.set_redemption_addr(new_addr, sender=owner)
    assert p2p_usdc_weth.redemption_addr() == new_addr


def test_set_redemption_addr_logs_event(p2p_usdc_weth, owner, redemption_wallet):
    new_addr = boa.env.generate_address("new_addr")

    p2p_usdc_weth.set_redemption_addr(new_addr, sender=owner)
    event = get_last_event(p2p_usdc_weth, "RedemptionAddressChanged")

    assert event.old_addr == redemption_wallet
    assert event.new_addr == new_addr


# MultiVault-specific tests for mint_addr
def test_set_mint_addr_reverts_if_not_owner(p2p_usdc_weth):
    random = boa.env.generate_address("random")
    new_addr = boa.env.generate_address("new_addr")
    with boa.reverts():
        p2p_usdc_weth.set_mint_addr(new_addr, sender=random)


def test_set_mint_addr(p2p_usdc_weth, owner):
    new_addr = boa.env.generate_address("new_addr")
    p2p_usdc_weth.set_mint_addr(new_addr, sender=owner)
    assert p2p_usdc_weth.mint_addr() == new_addr


def test_set_mint_addr_logs_event(p2p_usdc_weth, owner):
    new_addr = boa.env.generate_address("new_addr")

    # mint_addr starts as empty(address)
    old_addr = p2p_usdc_weth.mint_addr()

    p2p_usdc_weth.set_mint_addr(new_addr, sender=owner)
    event = get_last_event(p2p_usdc_weth, "MintAddressChanged")

    assert event.old_addr == old_addr
    assert event.new_addr == new_addr


def test_change_vault_registrar_reverts_if_not_owner(p2p_usdc_weth):
    random = boa.env.generate_address("random")
    new_registrar = boa.env.generate_address("new_registrar")
    with boa.reverts():
        p2p_usdc_weth.change_vault_registrar(new_registrar, sender=random)


def test_change_vault_registrar(p2p_usdc_weth, owner):
    new_registrar = boa.env.generate_address("new_registrar")
    p2p_usdc_weth.change_vault_registrar(new_registrar, sender=owner)
    assert p2p_usdc_weth.vault_registrar() == new_registrar


def test_change_vault_registrar_logs_event(p2p_usdc_weth, owner):
    old_registrar = p2p_usdc_weth.vault_registrar()
    new_registrar = boa.env.generate_address("new_registrar")

    p2p_usdc_weth.change_vault_registrar(new_registrar, sender=owner)
    event = get_last_event(p2p_usdc_weth, "VaultRegistrarChanged")

    assert event.old_registrar == old_registrar
    assert event.new_registrar == new_registrar


# MultiVault-specific tests for loan facet address (set_loan_addr)
def test_set_loan_addr_reverts_if_not_owner(p2p_usdc_weth):
    random = boa.env.generate_address("random")
    new_addr = boa.env.generate_address("new_loan_facet")
    with boa.reverts():
        p2p_usdc_weth.set_loan_addr(new_addr, sender=random)


def test_set_loan_addr_reverts_if_zero_address(p2p_usdc_weth, owner):
    with boa.reverts():
        p2p_usdc_weth.set_loan_addr(ZERO_ADDRESS, sender=owner)


def test_set_loan_addr(p2p_usdc_weth, owner):
    new_addr = boa.env.generate_address("new_loan_facet")
    p2p_usdc_weth.set_loan_addr(new_addr, sender=owner)
    assert p2p_usdc_weth.loan_addr() == new_addr


def test_set_loan_addr_logs_event(p2p_usdc_weth, owner, p2p_mv_loan):
    new_addr = boa.env.generate_address("new_loan_facet")
    old_addr = p2p_usdc_weth.loan_addr()
    assert old_addr == p2p_mv_loan.address  # precondition: wired to the loan facet at deploy

    p2p_usdc_weth.set_loan_addr(new_addr, sender=owner)
    event = get_last_event(p2p_usdc_weth, "LoanAddrChanged")

    assert event.old_addr == old_addr
    assert event.new_addr == new_addr


def test_set_loan_addr_updates_facet_used_by_create_loan(
    p2p_usdc_weth,
    p2p_lending_multivault_loan_contract_def,
    owner,
    borrower,
    now,
    lender,
    lender_key,
    kyc_for,
    kyc_validator_contract,
    usdc,
    weth,
    oracle,
):
    # Swap the loan facet for a freshly deployed second instance.
    new_loan_facet = p2p_lending_multivault_loan_contract_def.deploy()
    assert new_loan_facet.address != p2p_usdc_weth.loan_addr()  # precondition: a different facet
    p2p_usdc_weth.set_loan_addr(new_loan_facet.address, sender=owner)
    assert p2p_usdc_weth.loan_addr() == new_loan_facet.address

    # create_loan must still work, now delegating to the new facet.
    kyc_borrower = kyc_for(borrower, kyc_validator_contract.address)
    kyc_lender = kyc_for(lender, kyc_validator_contract.address)
    usdc.mint(lender, 10**12)

    principal = 1000 * 10**6
    offer = Offer(
        principal=principal,
        apr=1000,
        payment_token=usdc.address,
        collateral_token=weth.address,
        duration=100,
        origination_fee_bps=100,
        min_collateral_amount=0,
        max_iltv=8000,
        available_liquidity=principal,
        call_eligibility=0,
        call_window=0,
        liquidation_ltv=0,
        oracle_addr=oracle.address,
        expiration=now + 100,
        lender=lender,
        borrower=borrower,
        tracing_id=ZERO_BYTES32,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    collateral_amount = int(1e18)
    weth.deposit(value=collateral_amount, sender=borrower)
    weth.approve(p2p_usdc_weth.wallet_to_vault(borrower), collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_weth.address, principal, sender=lender)

    borrower_usdc_before = usdc.balanceOf(borrower)
    origination_fee = offer.origination_fee_bps * principal // BPS

    loan_id = p2p_usdc_weth.create_loan(signed_offer, principal, collateral_amount, kyc_borrower, kyc_lender, sender=borrower)

    # Loan was created and its effects applied via the swapped-in facet.
    assert loan_id != ZERO_BYTES32
    assert p2p_usdc_weth.loans(loan_id) != ZERO_BYTES32
    assert weth.balanceOf(p2p_usdc_weth.vault_id_to_vault(borrower, 0)) == collateral_amount
    assert usdc.balanceOf(borrower) == borrower_usdc_before + principal - origination_fee
