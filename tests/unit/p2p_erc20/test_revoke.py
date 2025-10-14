import boa
import pytest

from ...conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Offer,
    compute_signed_offer_id,
    get_last_event,
    manipulate_signature,
    replace_namedtuple_field,
    sign_offer,
)


@pytest.fixture
def p2p_erc20_proxy(p2p_usdc_weth, p2p_lending_erc20_proxy_contract_def):
    return p2p_lending_erc20_proxy_contract_def.deploy(p2p_usdc_weth.address)


def test_revoke_offer_reverts_if_sender_is_not_lender(p2p_usdc_weth, borrower, now, lender, lender_key, p2p_erc20_proxy):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("not lender"):
        p2p_usdc_weth.revoke_offer(signed_offer, sender=borrower)

    p2p_usdc_weth.set_proxy_authorization(p2p_erc20_proxy, True, sender=p2p_usdc_weth.owner())
    with boa.reverts("not lender"):
        p2p_erc20_proxy.revoke_offer(signed_offer, sender=borrower)


def test_revoke_offer_reverts_if_proxy_not_auth(p2p_usdc_weth, borrower, now, lender, lender_key, p2p_erc20_proxy):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.set_proxy_authorization(p2p_erc20_proxy, False, sender=p2p_usdc_weth.owner())
    with boa.reverts("not lender"):
        p2p_erc20_proxy.revoke_offer(signed_offer, sender=lender)


def test_revoke_offer_reverts_if_offer_expired(p2p_usdc_weth, borrower, now, lender, lender_key):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    with boa.reverts("offer expired"):
        p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)


def test_revoke_offer_reverts_if_offer_not_signed_by_lender(p2p_usdc_weth, borrower, now, lender, borrower_key):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, borrower_key, p2p_usdc_weth.address)

    with boa.reverts("offer not signed by lender"):
        p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)


def test_revoke_offer_reverts_if_offer_already_revoked(p2p_usdc_weth, borrower, now, lender, lender_key):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)

    with boa.reverts("offer already revoked"):
        p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)


def test_revoke_offer_reverts_if_signature_is_manipulated(p2p_usdc_weth, borrower, now, lender, lender_key):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)
    manipulated_signed_offer = replace_namedtuple_field(signed_offer, signature=manipulate_signature(signed_offer.signature))

    with boa.reverts("invalid signature"):
        p2p_usdc_weth.revoke_offer(manipulated_signed_offer, sender=lender)

    assert not p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))


def test_revoke_offer_marks_offer_as_revoked(p2p_usdc_weth, borrower, now, lender, lender_key):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)

    assert p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))


def test_revoke_offer_logs_event(p2p_usdc_weth, borrower, now, lender, lender_key):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.revoke_offer(signed_offer, sender=lender)

    event = get_last_event(p2p_usdc_weth, "OfferRevoked")
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.lender == lender


def test_revoke_offer_works_with_proxy(p2p_usdc_weth, borrower, now, lender, lender_key, p2p_erc20_proxy):
    offer = Offer(
        principal=1000,
        payment_token=p2p_usdc_weth.payment_token(),
        collateral_token=p2p_usdc_weth.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_weth.address)

    p2p_usdc_weth.set_proxy_authorization(p2p_erc20_proxy, True, sender=p2p_usdc_weth.owner())
    p2p_erc20_proxy.revoke_offer(signed_offer, sender=lender)

    assert p2p_usdc_weth.revoked_offers(compute_signed_offer_id(signed_offer))
