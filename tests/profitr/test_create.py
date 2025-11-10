import os
from textwrap import dedent

import boa
import pytest
from boa.environment import Env

from ..conftest_base import (
    ZERO_ADDRESS,
    ZERO_BYTES32,
    Loan,
    Offer,
    SignedOffer,
    calc_ltv,
    compute_liquidity_key,
    compute_loan_hash,
    compute_signed_offer_id,
    get_events,
    get_last_event,
    replace_namedtuple_field,
    sign_kyc,
    sign_offer,
)

BPS = 10000


@pytest.fixture
def profitr_owner(owner):
    return "0x12c0c8a91C4b90779FFCd7272E7e59fDB7946F32"


@pytest.fixture
def fee_wallet(owner):
    return boa.env.generate_address("fee_wallet")


@pytest.fixture
def profitr_vault_impl():
    return boa.load("contracts/P2PLendingVaultProfitr.vy").deploy()


@pytest.fixture
def usdc(profitr_owner, owner, accounts, erc20_contract_def):
    contract = erc20_contract_def.at("0x926394525525a86Ef0a847698742dfBD9D42E6B3")
    holder = "0x0cBeE0516372F55dcff5a1299AD37498F54c30C8"
    assert contract.balanceOf(holder) > int(1_000_000 * 1e6)
    contract.transfer(profitr_owner, 10**12, sender=holder)
    contract.transfer(owner, 10**12, sender=holder)
    return contract


@pytest.fixture
def transfer_rules(profitr_owner):
    contract_def = boa.load_abi("contracts/auxiliary/Profitr_TransferRules_abi.json")
    contract = contract_def.at("0x675aD8A655AafC2ED612B19BC2d01C25691df764")
    # setTokenTypeRule(uint256 region, uint256 accreditation, uint256 tokenType, bool requiresAmlKyc, bool isActive)
    token_type = 2
    region = 1
    accreditation = 10
    contract.setTokenTypeRule(region, accreditation, token_type, True, True, sender=profitr_owner)
    # struct TransferRule {
    #     uint256 lockDurationSeconds;    // Holding period in seconds from mint timestamp
    #     bool requiresAmlKyc;            // Whether recipient must have AML/KYC
    #     bool isActive;                  // Whether this rule is currently active
    # }
    contract.setTransferRule(token_type, region, accreditation, (0, True, True), sender=profitr_owner)
    return contract


@pytest.fixture
def profitr_token():
    contract_def = boa.load_abi("contracts/auxiliary/Profitr_RestrictedLockupToken_abi.json")
    return contract_def.at("0x25d0CBaf6d1F5E649d1ae2c5dCF84d5EbA6058d3")


@pytest.fixture
def interest_payment():
    contract_def = boa.load_abi("contracts/auxiliary/Profitr_InterestPayment_abi.json")
    return contract_def.at("0x6b50aa271Ad315C71B2C2b21Cf8F4010c602A449")


@pytest.fixture
def access_control():
    contract_def = boa.load_abi("contracts/auxiliary/Profitr_AccessControl_abi.json")
    return contract_def.at("0x3c6B19A9E2dCb05Eed3964090722Db7f6d97d816")


@pytest.fixture
def identity_registry():
    contract_def = boa.load_abi("contracts/auxiliary/Profitr_IdentityRegistry_abi.json")
    return contract_def.at("0xbf0490e0f85296A8267e3Fc13AFA70e3D2c6D544")


@pytest.fixture
def purchase(profitr_owner, fee_wallet, access_control):
    contract_def = boa.load_abi("contracts/auxiliary/Profitr_PurchaseContract_abi.json")
    contract = contract_def.at("0x352f60B05633831265ccC53818f70157b63B79e2")
    assert profitr_owner == contract.owner()
    contract.updateAdminFeeWallet(fee_wallet, sender=profitr_owner)
    contract.updateOriginatorPaymentWallet(fee_wallet, sender=profitr_owner)
    access_control.grantRole(contract.address, 0x20, sender=profitr_owner)
    access_control.grantRole(contract.address, 0x3F, sender=profitr_owner)
    return contract


@pytest.fixture
def automation_admin(purchase, access_control, profitr_owner):
    admin = boa.env.generate_address("automation_admin")
    purchase.updateAutomationAdmin(admin, sender=profitr_owner)
    access_control.grantRole(admin, 0x28, sender=profitr_owner)
    access_control.grantRole(admin, 0x4, sender=profitr_owner)
    access_control.grantRole(admin, 0x3F, sender=profitr_owner)
    return admin


@pytest.fixture
def wallet_1(identity_registry, profitr_owner, profitr_token):
    wallet = boa.env.generate_address("wallet_1")
    identity_info = {
        "regions": [1],
        "accreditationType": 10,
        "lastAmlKycChangeTimestamp": 1760544672,
        "lastAccreditationChangeTimestamp": 1760544672,
        "amlKycPassed": True,
    }
    identity_registry.setIdentity(wallet, tuple(identity_info.values()), sender=profitr_owner)
    assert profitr_token.isAmlKycPassed(wallet)
    return wallet


@pytest.fixture
def wallet_2(identity_registry, profitr_owner, profitr_token):
    wallet = boa.env.generate_address("wallet_2")
    identity_info = {
        "regions": [1],
        "accreditationType": 10,
        "lastAmlKycChangeTimestamp": 1760544672,
        "lastAccreditationChangeTimestamp": 1760544672,
        "amlKycPassed": True,
    }
    identity_registry.setIdentity(wallet, tuple(identity_info.values()), sender=profitr_owner)
    assert profitr_token.isAmlKycPassed(wallet)
    return wallet


@pytest.fixture
def wallet_1_vault(identity_registry, profitr_owner, profitr_token, wallet_1, p2p_usdc_profitr):
    vault = p2p_usdc_profitr.wallet_to_vault(wallet_1)
    identity_info = {
        "regions": [1],
        "accreditationType": 10,
        "lastAmlKycChangeTimestamp": 1760544672,
        "lastAccreditationChangeTimestamp": 1760544672,
        "amlKycPassed": True,
    }
    identity_registry.setIdentity(vault, tuple(identity_info.values()), sender=profitr_owner)
    assert profitr_token.isAmlKycPassed(vault)
    return vault


# @pytest.fixture
# def usdc(owner, accounts, erc20_contract_def):
#     erc20 = erc20_contract_def.at("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
#     holder = "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1"
#     with boa.env.prank(holder):
#         for account in accounts:
#             erc20.transfer(account, 10**12, sender=holder)
#     erc20.transfer(owner, 10**12, sender=holder)
#     return erc20


@pytest.fixture(autouse=True)
def lender_funds(lender, usdc, owner):
    usdc.transfer(lender, int(1e10))


@pytest.fixture(autouse=True)
def kyc_lender(lender, kyc_for, kyc_validator_contract, now):
    return kyc_for(lender, kyc_validator_contract.address, expiration=now + 86400)


@pytest.fixture(autouse=True)
def kyc_borrower(borrower, kyc_for, kyc_validator_contract, now):
    return kyc_for(borrower, kyc_validator_contract.address, expiration=now + 86400)


@pytest.fixture(autouse=True)
def kyc_wallet_1(wallet_1, kyc_for, kyc_validator_contract, now):
    return kyc_for(wallet_1, kyc_validator_contract.address, expiration=now + 86400)


@pytest.fixture
def oracle_profitr_usd():
    contract_def = boa.load_partial("contracts/auxiliary/OracleMock.vy")
    return contract_def.deploy(8, int(1e8))


@pytest.fixture
def vault_impl(vault_contract_def):
    return vault_contract_def.deploy()


@pytest.fixture
def p2p_usdc_profitr(
    p2p_lending_erc20_contract_def,
    p2p_refinance,
    profitr_vault_impl,
    usdc,
    profitr_token,
    oracle_profitr_usd,
    kyc_validator_contract,
    owner,
    transfer_agent,
):
    return p2p_lending_erc20_contract_def.deploy(
        usdc,
        profitr_token,
        oracle_profitr_usd,
        False,
        kyc_validator_contract,
        0,
        0,
        owner,
        10000,
        10000,
        0,
        0,
        p2p_refinance.address,
        profitr_vault_impl.address,
        transfer_agent,
    )


def test_initial_setup(
    profitr_owner,
    p2p_usdc_profitr,
    profitr_token,
    usdc,
    purchase,
    transfer_rules,
    interest_payment,
    access_control,
    identity_registry,
    automation_admin,
    wallet_1,
    wallet_2,
):
    assert p2p_usdc_profitr.payment_token() == usdc.address
    assert p2p_usdc_profitr.collateral_token() == profitr_token.address

    mint_value = 10000
    payment_token_value = mint_value * int(1e6)
    profitr_token.mint(wallet_1, mint_value, sender=profitr_owner)

    usdc.approve(interest_payment.address, payment_token_value, sender=profitr_owner)
    interest_payment.fundInterest(payment_token_value, sender=profitr_owner)


def test_transfer(
    profitr_owner,
    p2p_usdc_profitr,
    profitr_token,
    usdc,
    purchase,
    transfer_rules,
    interest_payment,
    access_control,
    identity_registry,
    automation_admin,
    wallet_1,
    wallet_2,
):
    mint_value = 10000
    payment_token_value = mint_value * int(1e6)
    profitr_token.mint(wallet_1, mint_value, sender=profitr_owner)
    assert profitr_token.balanceOf(wallet_1) == mint_value

    # usdc.approve(interest_payment.address, payment_token_value, sender=profitr_owner)
    # interest_payment.fundInterest(payment_token_value, sender=profitr_owner)

    # assert interest_payment.totalInterestAmountFunded() == payment_token_value
    # assert interest_payment.totalInterestAmountUnused() == payment_token_value
    # assert interest_payment.totalInterestAmountClaimed() == 0
    # assert interest_payment.totalInterestAmountReclaimed() == 0

    profitr_token.transfer(wallet_2, mint_value, sender=wallet_1)
    assert profitr_token.balanceOf(wallet_1) == 0
    assert profitr_token.balanceOf(wallet_2) == mint_value


def test_claim_interest(
    profitr_owner,
    p2p_usdc_profitr,
    profitr_token,
    usdc,
    purchase,
    transfer_rules,
    interest_payment,
    access_control,
    identity_registry,
    automation_admin,
    wallet_1,
    wallet_2,
):
    mint_value = 10000
    payment_token_value = mint_value * int(1e6)
    profitr_token.mint(wallet_1, mint_value, sender=profitr_owner)
    assert profitr_token.balanceOf(wallet_1) == mint_value

    usdc.approve(interest_payment.address, payment_token_value, sender=profitr_owner)
    interest_payment.fundInterest(payment_token_value, sender=profitr_owner)

    assert interest_payment.totalInterestAmountFunded() == payment_token_value
    assert interest_payment.totalInterestAmountUnused() == payment_token_value
    assert interest_payment.totalInterestAmountClaimed() == 0
    assert interest_payment.totalInterestAmountReclaimed() == 0

    now = boa.eval("block.timestamp")
    period_start = interest_payment.interestAccrualStartTimestamp()
    period_end = now + 30
    assert interest_payment.interestAccrualStartTimestamp() < now
    assert interest_payment.interestAccrualEndTimestamp() > period_end
    assert interest_payment.interestRatePeriodSeconds() == 1

    # createPaymentPeriod(uint256 startTimestamp, uint256 endTimestamp, uint256 interestRate_, uint256 interestRatePeriodDuration)
    interest_payment.createPaymentPeriod(period_start, period_end, 500, 10, sender=profitr_owner)

    boa.env.time_travel(10)
    assert interest_payment.accruedInterest(wallet_1) == 50000

    boa.env.time_travel(30)
    assert interest_payment.accruedInterest(wallet_1) == 150000

    balance_before = usdc.balanceOf(wallet_1)
    interest_payment.claimInterest(150000, sender=wallet_1)

    assert usdc.balanceOf(wallet_1) == balance_before + 150000
    assert interest_payment.accruedInterest(wallet_1) == 150000
    assert profitr_token.balanceOf(wallet_1) == mint_value

    # interest_payment.fundDividend(payment_token_value, sender=profitr_owner)

    # profitr_token.transfer(wallet_2, mint_value, sender=wallet_1)
    # assert profitr_token.balanceOf(wallet_1) == 0
    # assert profitr_token.balanceOf(wallet_2) == mint_value


def test_transfer_interest(
    profitr_owner,
    p2p_usdc_profitr,
    profitr_token,
    usdc,
    purchase,
    transfer_rules,
    interest_payment,
    access_control,
    identity_registry,
    automation_admin,
    wallet_1,
    wallet_2,
):
    mint_value = 10000
    payment_token_value = mint_value * int(1e6)
    profitr_token.mint(wallet_1, mint_value, sender=profitr_owner)
    assert profitr_token.balanceOf(wallet_1) == mint_value

    usdc.approve(interest_payment.address, payment_token_value, sender=profitr_owner)
    interest_payment.fundInterest(payment_token_value, sender=profitr_owner)

    now = boa.eval("block.timestamp")
    period_start = interest_payment.interestAccrualStartTimestamp()
    period_end = now + 30

    interest_payment.createPaymentPeriod(period_start, period_end, 500, 10, sender=profitr_owner)

    boa.env.time_travel(10)
    assert interest_payment.accruedInterest(wallet_1) == 50000
    assert interest_payment.accruedInterest(wallet_2) == 0

    profitr_token.transfer(wallet_2, mint_value, sender=wallet_1)

    boa.env.time_travel(30)
    assert interest_payment.accruedInterest(wallet_1) == 50000
    assert interest_payment.accruedInterest(wallet_2) == 100000

    balance_before_1 = usdc.balanceOf(wallet_1)
    balance_before_2 = usdc.balanceOf(wallet_2)

    interest_payment.claimInterest(50000, sender=wallet_1)
    interest_payment.claimInterest(100000, sender=wallet_2)

    assert usdc.balanceOf(wallet_1) == balance_before_1 + 50000
    assert usdc.balanceOf(wallet_2) == balance_before_2 + 100000

    assert interest_payment.accruedInterest(wallet_1) == 50000
    assert interest_payment.accruedInterest(wallet_2) == 100000

    assert interest_payment.accruedInterestAt(wallet_1, now) == 0
    assert interest_payment.accruedInterestAt(wallet_2, now) == 0


def _test_purchase(
    profitr_owner,
    p2p_usdc_profitr,
    profitr_token,
    usdc,
    purchase,
    transfer_rules,
    interest_payment,
    access_control,
    identity_registry,
    automation_admin,
    wallet_1,
    wallet_2,
):
    mint_value = 10000
    payment_token_value = mint_value * int(1e6)
    # profitr_token.mint(wallet_1, mint_value, sender=profitr_owner)

    usdc.approve(interest_payment.address, payment_token_value, sender=profitr_owner)
    # interest_payment.fundInterest(payment_token_value, sender=profitr_owner)

    purchase_params = {
        "purchaseId": "PURCHASE-TEST-002",
        "payerAddress": wallet_2,
        "tokenRecipientAddress": wallet_2,
        "originatorPurchaseAmount": 9000000000,
        "prefundedInterestAmount": 0,
        "adminFeeExcludingPrefundedInterestAmount": 0,
        "totalAmount": 9000000000,
    }
    # identity_registry.grantAmlKyc(wallet_2, 0, sender=profitr_owner)
    # interest_payment.fundPrincipal(payment_token_value, sender=profitr_owner)

    purchase.executePurchase(tuple(purchase_params.values()), sender=profitr_owner)


def test_create_and_settle_loan(
    p2p_usdc_profitr,
    wallet_1,
    wallet_1_vault,
    lender,
    lender_key,
    kyc_wallet_1,
    kyc_lender,
    kyc_validator_contract,
    kyc_validator_key,
    usdc,
    profitr_token,
    oracle_profitr_usd,
    profitr_owner,
    purchase,
    transfer_rules,
    interest_payment,
    access_control,
    identity_registry,
    automation_admin,
    vault_contract_def,
):
    borrower = wallet_1
    principal = 1000 * int(1e6)
    collateral_amount = 10000
    now = boa.eval("block.timestamp")
    payment_token_value = collateral_amount * int(1e6)
    profitr_token.mint(wallet_1, collateral_amount, sender=profitr_owner)
    assert profitr_token.balanceOf(wallet_1) == collateral_amount

    usdc.approve(interest_payment.address, payment_token_value, sender=profitr_owner)
    interest_payment.fundInterest(payment_token_value, sender=profitr_owner)

    now = boa.eval("block.timestamp")
    period_start = interest_payment.interestAccrualStartTimestamp()
    period_end = now + 30
    loan_start = now + 10
    loan_end = loan_start + 50

    interest_payment.createPaymentPeriod(period_start, period_end, 500, 10, sender=profitr_owner)

    boa.env.time_travel(loan_start - now)

    offer = Offer(
        principal=principal,
        payment_token=p2p_usdc_profitr.payment_token(),
        collateral_token=p2p_usdc_profitr.collateral_token(),
        duration=100,
        min_collateral_amount=1,
        available_liquidity=principal,
        expiration=now + 100,
        lender=lender,
    )
    signed_offer = sign_offer(offer, lender_key, p2p_usdc_profitr.address)

    profitr_token.approve(wallet_1_vault, collateral_amount, sender=borrower)
    usdc.approve(p2p_usdc_profitr.address, principal, sender=lender)

    borrower_collateral_balance_before = profitr_token.balanceOf(borrower)
    borrower_accrued_interest_before = interest_payment.accruedInterest(borrower)
    borrower_balance_before = usdc.balanceOf(borrower)

    now = boa.eval("block.timestamp")
    boa.vm.py_evm.register_raw_precompile(
        "0x0000000000000000000000000000000000011111", lambda computation: print("0x" + computation.msg.data.hex())
    )

    origination_fee = offer.origination_fee_bps * principal // BPS
    lender_balance_before = usdc.balanceOf(lender)

    loan_id = p2p_usdc_profitr.create_loan(
        signed_offer, principal, collateral_amount, kyc_wallet_1, kyc_lender, sender=borrower
    )
    event = get_last_event(p2p_usdc_profitr, "LoanCreated")
    initial_ltv = calc_ltv(
        principal, offer.min_collateral_amount, usdc, profitr_token, oracle_profitr_usd, oracle_reverse=False
    )

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
        protocol_upfront_fee_amount=p2p_usdc_profitr.protocol_upfront_fee(),
        protocol_settlement_fee=p2p_usdc_profitr.protocol_settlement_fee(),
        partial_liquidation_fee=0,
        call_eligibility=offer.call_eligibility,
        call_window=offer.call_window,
        liquidation_ltv=offer.liquidation_ltv,
        oracle_addr=p2p_usdc_profitr.oracle_addr(),
        initial_ltv=initial_ltv,
        call_time=0,
    )
    assert compute_loan_hash(loan) == p2p_usdc_profitr.loans(loan_id)

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
    assert event.oracle_addr == p2p_usdc_profitr.oracle_addr()
    assert event.initial_ltv == initial_ltv
    assert event.origination_fee_amount == offer.origination_fee_bps * principal // BPS
    assert event.protocol_upfront_fee_amount == p2p_usdc_profitr.protocol_upfront_fee()
    assert event.protocol_settlement_fee == p2p_usdc_profitr.protocol_settlement_fee()
    assert event.partial_liquidation_fee == p2p_usdc_profitr.partial_liquidation_fee()
    assert event.offer_id == compute_signed_offer_id(signed_offer)
    assert event.offer_tracing_id == offer.tracing_id

    assert profitr_token.balanceOf(wallet_1_vault) == collateral_amount
    assert profitr_token.balanceOf(borrower) == borrower_collateral_balance_before - collateral_amount

    assert usdc.balanceOf(borrower) == borrower_balance_before + principal - origination_fee
    assert usdc.balanceOf(lender) == lender_balance_before - principal + origination_fee

    liquidity_key = compute_liquidity_key(offer.lender, offer.tracing_id)
    assert p2p_usdc_profitr.commited_liquidity(liquidity_key) == principal

    boa.env.time_travel(loan_end - loan_start)

    interest = loan.amount * loan.apr * (now - loan.accrual_start_time) // (86400 * 10000)
    amount_to_settle = loan.amount + interest

    usdc.approve(p2p_usdc_profitr.address, amount_to_settle, sender=loan.borrower)
    p2p_usdc_profitr.settle_loan(loan, sender=loan.borrower)

    assert profitr_token.balanceOf(wallet_1_vault) == 0
    assert profitr_token.balanceOf(borrower) == borrower_collateral_balance_before

    assert interest_payment.accruedInterest(borrower) == borrower_accrued_interest_before
    assert interest_payment.accruedInterest(wallet_1_vault) == 100000

    assert usdc.balanceOf(borrower) == borrower_balance_before - interest
    vault_contract_def.at(wallet_1_vault).claimInterest(interest_payment.address, usdc.address, 100000, sender=borrower)
    assert usdc.balanceOf(borrower) == borrower_balance_before - interest + 100000
