# @version 0.4.3

"""
@title P2PLendingSecuritizeErc20
@author [Zharta](https://zharta.io/)
@notice This contract facilitates peer-to-peer lending using ERC20s as collateral.

"""

from contracts.v1 import P2PLendingSecuritizeBase as base

initializes: base
exports: base.__interface__

# Interfaces

from ethereum.ercs import IERC721
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

from contracts.v1 import P2PLendingVaultSecuritize as vault

# Workaround for allowing static calls to functions that delegate to other facets
interface StaticSelf:
    def _simulate_partial_liquidation(loan: base.Loan) -> base.PartialLiquidationResult: view


event LoanCreated:
    id: bytes32
    amount: uint256
    apr: uint256
    payment_token: address
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_token: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    liquidation_ltv: uint256
    oracle_addr: address
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    partial_liquidation_fee: uint256
    full_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32
    oracle_rate_num: uint256
    oracle_rate_den: uint256
    vault_id: uint256
    vault_addr: address


event LoanPaid:
    id: bytes32
    borrower: address
    lender: address
    payment_token: address
    paid_principal: uint256
    paid_interest: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee_amount: uint256
    in_vault_payment_token: uint256
    in_vault_collateral: uint256


event LoanCollateralClaimed:
    id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    collateral_amount: uint256


event LoanReplaced:
    id: bytes32
    amount: uint256
    apr: uint256
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    liquidation_ltv: uint256
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    partial_liquidation_fee: uint256
    full_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32
    original_loan_id: bytes32
    paid_principal: uint256
    paid_interest: uint256
    paid_protocol_settlement_fee_amount: uint256

event LoanReplacedByLender:
    id: bytes32
    amount: uint256
    apr: uint256
    maturity: uint256
    start_time: uint256
    borrower: address
    lender: address
    collateral_amount: uint256
    min_collateral_amount: uint256
    call_eligibility: uint256
    call_window: uint256
    liquidation_ltv: uint256
    initial_ltv: uint256
    origination_fee_amount: uint256
    protocol_upfront_fee_amount: uint256
    protocol_settlement_fee: uint256
    partial_liquidation_fee: uint256
    full_liquidation_fee: uint256
    offer_id: bytes32
    offer_tracing_id: bytes32
    original_loan_id: bytes32
    paid_principal: uint256
    paid_interest: uint256
    paid_protocol_settlement_fee_amount: uint256


event LoanCollateralAdded:
    id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    old_collateral_amount: uint256
    new_collateral_amount: uint256
    old_ltv: uint256
    new_ltv: uint256


event LoanCollateralRemoved:
    id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    old_collateral_amount: uint256
    new_collateral_amount: uint256
    old_ltv: uint256
    new_ltv: uint256


event LoanPartiallyLiquidated:
    id: bytes32
    borrower: address
    lender: address
    written_off: uint256
    collateral_claimed: uint256
    liquidation_fee: uint256
    updated_amount: uint256
    updated_collateral_amount: uint256
    updated_accrual_start_time: uint256
    liquidator: address
    old_ltv: uint256
    new_ltv: uint256

event LoanLiquidated:
    id: bytes32
    borrower: address
    lender: address
    liquidator: address
    outstanding_debt: uint256
    collateral_for_debt: uint256
    remaining_collateral: uint256
    remaining_collateral_value: uint256
    shortfall: uint256
    liquidation_fee: uint256
    protocol_settlement_fee_amount: uint256

event LoanMaturityExtended:
    loan_id: bytes32
    original_maturity: uint256
    new_maturity: uint256
    lender: address
    borrower: address
    caller: address

event OwnerProposed:
    owner: address
    proposed_owner: address

event OwnershipTransferred:
    old_owner: address
    new_owner: address

event TransferAgentChanged:
    old_agent: address
    new_agent: address
    by: address

event SecuritizeRedemptionWalletChanged:
    old_wallet: address
    new_wallet: address

event VaultRegistrarChanged:
    old_registrar: address
    new_registrar: address


event ProtocolFeeSet:
    old_upfront_fee: uint256
    old_settlement_fee: uint256
    new_upfront_fee: uint256
    new_settlement_fee: uint256

event PartialLiquidationFeeSet:
    old_fee: uint256
    new_fee: uint256

event FullLiquidationFeeSet:
    old_fee: uint256
    new_fee: uint256

event ProtocolWalletChanged:
    old_wallet: address
    new_wallet: address

event ProxyAuthorizationChanged:
    proxy: address
    value: bool

event PendingTransfersClaimed:
    _to: address
    amount: uint256


event LoanBorrowerTransferred:
    loan_id: bytes32
    new_loan_id: bytes32
    old_borrower: address
    new_borrower: address
    lender: address
    vault_id: uint256

event LoanCollateralRedeemStarted:
    loan_id: bytes32
    borrower: address
    lender: address
    collateral_token: address
    vault_id: uint256
    redeem_start: uint256
    redeem_residual_collateral: uint256


BPS: constant(uint256) = 10000
YEAR_TO_SECONDS: constant(uint256) = 365 * 24 * 60 * 60

VERSION: public(constant(String[31])) = "P2PLendingSErc20.20260126"

payment_token: public(immutable(address))
collateral_token: public(immutable(address))
oracle_addr: public(immutable(address))
oracle_reverse: public(immutable(bool))
kyc_validator_addr: public(immutable(address))

max_protocol_upfront_fee: public(immutable(uint256))
max_protocol_settlement_fee: public(immutable(uint256))

payment_token_decimals: public(immutable(uint256))
collateral_token_decimals: public(immutable(uint256))

offer_sig_domain_separator: immutable(bytes32)

refinance_addr: public(immutable(address))
liquidation_addr: public(immutable(address))
vault_impl_addr: public(immutable(address))

@deploy
def __init__(
    _payment_token: address,
    _collateral_token: address,
    _oracle_addr: address,
    _oracle_reverse: bool,
    _kyc_validator_addr: address,
    _protocol_upfront_fee: uint256,
    _protocol_settlement_fee: uint256,
    _protocol_wallet: address,
    _max_protocol_upfront_fee: uint256,
    _max_protocol_settlement_fee: uint256,
    _partial_liquidation_fee: uint256,
    _full_liquidation_fee: uint256,
    _refinance_addr: address,
    _liquidation_addr: address,
    _vault_impl_addr: address,
    _transfer_agent: address,
    _securitize_redemption_wallet: address,
    _vault_registrar_addr: address
):

    """
    @notice Initialize the contract with the given parameters.
    @param _payment_token The address of the payment token.
    @param _collateral_token The address of the collateral token.
    @param _oracle_addr The address of the oracle contract for collateral valuation.
    @param _oracle_reverse Whether the oracle returns the collateral price in reverse (i.e., 1 / price).
    @param _protocol_upfront_fee The percentage (bps) of the principal paid to the protocol at origination.
    @param _protocol_settlement_fee The percentage (bps) of the interest paid to the protocol at settlement.
    @param _protocol_wallet The address where the protocol fees are accrued.
    @param _max_protocol_upfront_fee The maximum percentage (bps) of the principal that can be charged as protocol upfront fee.
    @param _max_protocol_settlement_fee The maximum percentage (bps) of the interest that can be charged as protocol settlement fee.
    @param _partial_liquidation_fee The percentage (bps) of the principal that is charged as a liquidation fee when a loan is partially liquidated.
    @param _full_liquidation_fee The percentage (bps) of the principal that is charged as a liquidation fee when a loan is fully liquidated.
    @param _refinance_addr The address of the facet contract implementing the refinance functionality.
    @param _liquidation_addr The address of the facet contract implementing the liquidation functionality.
    @param _vault_impl_addr The address of the vault implementation contract.
    @param _transfer_agent The wallet address for the transfer agent role.
    @param _securitize_redemption_wallet The wallet address for Securitize redemptions.
    @param _vault_registrar_addr The address of the vault registrar connector contract.
    """

    base.__init__()

    payment_token = _payment_token
    collateral_token = _collateral_token
    oracle_addr = _oracle_addr
    oracle_reverse = _oracle_reverse
    kyc_validator_addr = _kyc_validator_addr
    max_protocol_upfront_fee = _max_protocol_upfront_fee
    max_protocol_settlement_fee = _max_protocol_settlement_fee
    refinance_addr = _refinance_addr
    liquidation_addr = _liquidation_addr
    vault_impl_addr = _vault_impl_addr
    collateral_token_decimals = 10 ** convert(staticcall IERC20Detailed(_collateral_token).decimals(), uint256)
    payment_token_decimals = 10 ** convert(staticcall IERC20Detailed(_payment_token).decimals(), uint256)
    base.protocol_upfront_fee = _protocol_upfront_fee
    base.protocol_settlement_fee = _protocol_settlement_fee
    base.protocol_wallet = _protocol_wallet
    base.transfer_agent = _transfer_agent
    base.securitize_redemption_wallet = _securitize_redemption_wallet
    base.vault_registrar = _vault_registrar_addr
    base.partial_liquidation_fee = _partial_liquidation_fee
    base.full_liquidation_fee = _full_liquidation_fee

    offer_sig_domain_separator = keccak256(
        abi_encode(
            base.DOMAIN_TYPE_HASH,
            keccak256(base.ZHARTA_DOMAIN_NAME),
            keccak256(base.ZHARTA_DOMAIN_VERSION),
            chain.id,
            self
        )
    )



# Config functions


@external
def set_partial_liquidation_fee(new_partial_liquidation_fee: uint256):

    """
    @notice Set the partial liquidation fee
    @dev Sets the partial liquidation fee to the given value and logs the event. Admin function.
    @param new_partial_liquidation_fee The new partial liquidation fee.
    """

    assert msg.sender == base.owner
    assert new_partial_liquidation_fee <= BPS, "fee exceeds BPS"

    log PartialLiquidationFeeSet(old_fee=base.partial_liquidation_fee, new_fee=new_partial_liquidation_fee)
    base.partial_liquidation_fee = new_partial_liquidation_fee


@external
def set_full_liquidation_fee(new_full_liquidation_fee: uint256):

    """
    @notice Set the full liquidation fee
    @dev Sets the full liquidation fee to the given value and logs the event. Admin function.
    @param new_full_liquidation_fee The new full liquidation fee.
    """

    assert msg.sender == base.owner
    assert new_full_liquidation_fee <= BPS, "fee exceeds BPS"

    log FullLiquidationFeeSet(old_fee=base.full_liquidation_fee, new_fee=new_full_liquidation_fee)
    base.full_liquidation_fee = new_full_liquidation_fee


@external
def set_protocol_fee(protocol_upfront_fee: uint256, protocol_settlement_fee: uint256):

    """
    @notice Set the protocol fee
    @dev Sets the protocol fee to the given value and logs the event. Admin function.
    @param protocol_upfront_fee The new protocol upfront fee.
    @param protocol_settlement_fee The new protocol settlement fee.
    """

    assert msg.sender == base.owner
    assert protocol_upfront_fee <= max_protocol_upfront_fee, "upfront fee exceeds max"
    assert protocol_settlement_fee <= max_protocol_settlement_fee, "settlement fee exceeds max"

    log ProtocolFeeSet(
        old_upfront_fee=base.protocol_upfront_fee,
        old_settlement_fee=base.protocol_settlement_fee,
        new_upfront_fee=protocol_upfront_fee,
        new_settlement_fee=protocol_settlement_fee
    )
    base.protocol_upfront_fee = protocol_upfront_fee
    base.protocol_settlement_fee = protocol_settlement_fee


@external
def change_protocol_wallet(new_protocol_wallet: address):

    """
    @notice Change the protocol wallet
    @dev Changes the protocol wallet to the given address and logs the event. Admin function.
    @param new_protocol_wallet The new protocol wallet.
    """

    assert msg.sender == base.owner
    assert new_protocol_wallet != empty(address)

    log ProtocolWalletChanged(old_wallet=base.protocol_wallet, new_wallet=new_protocol_wallet)
    base.protocol_wallet = new_protocol_wallet


@external
def set_proxy_authorization(_proxy: address, _value: bool):

    """
    @notice Set authorization
    @dev Sets the authorization for the given proxy and logs the event. Admin function.
    @param _proxy The address of the proxy.
    @param _value The value of the authorization.
    """

    assert msg.sender == base.owner

    base.authorized_proxies[_proxy] = _value

    log ProxyAuthorizationChanged(proxy=_proxy, value=_value)


@external
def propose_owner(_address: address):

    """
    @notice Propose a new owner
    @dev Proposes a new owner and logs the event. Admin function.
    @param _address The address of the proposed owner.
    """

    assert msg.sender == base.owner
    assert _address != empty(address)

    log OwnerProposed(owner=base.owner, proposed_owner=_address)
    base.proposed_owner = _address


@external
def claim_ownership():

    """
    @notice Claim the ownership of the contract
    @dev Claims the ownership of the contract and logs the event. Requires the caller to be the proposed owner.
    """

    assert msg.sender == base.proposed_owner

    log OwnershipTransferred(old_owner=base.owner, new_owner=base.proposed_owner)
    base.owner = msg.sender
    base.proposed_owner = empty(address)


@external
def set_transfer_agent(_address: address):

    """
    @notice Set transfer agent
    @dev Sets the transfer agent to the given address. Admin function.
    @param _address The address of the new transfer agent.
    """

    assert msg.sender == base.owner or msg.sender == base.transfer_agent
    log TransferAgentChanged(old_agent=base.transfer_agent, new_agent=_address, by=msg.sender)
    base.transfer_agent = _address

@external
def set_securitize_redemption_wallet(_address: address):

    """
    @notice Set Securitize redemption wallet
    @dev Sets the Securitize redemption wallet to the given address. Admin function.
    @param _address The address of the new Securitize redemption wallet.
    """

    assert msg.sender == base.owner
    log SecuritizeRedemptionWalletChanged(old_wallet=base.securitize_redemption_wallet, new_wallet=_address)
    base.securitize_redemption_wallet = _address

@external
def change_vault_registrar(new_vault_registrar: address):

    """
    @notice Change the vault registrar
    @dev Changes the vault registrar to the given address and logs the event. Admin function.
    @param new_vault_registrar The new vault registrar.
    """

    assert msg.sender == base.owner
    log VaultRegistrarChanged(old_registrar=base.vault_registrar, new_registrar=new_vault_registrar)
    base.vault_registrar = new_vault_registrar


# Core functions

@external
def create_loan(
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    borrower_kyc: base.SignedWalletValidation,
    lender_kyc: base.SignedWalletValidation
) -> bytes32:

    """
    @notice Create a loan.
    @param offer The signed offer.
    @param principal The principal amount of the loan.
    @param collateral_amount The amount of collateral tokens to be used for the loan.
    @param borrower_kyc The signed KYC validation for the borrower.
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the created loan.
    """


    assert base._is_offer_signed_by_lender(offer, offer_sig_domain_separator), "offer not signed by lender"
    self._check_offer_validity(offer)

    borrower: address = msg.sender if not base.authorized_proxies[msg.sender] else tx.origin

    assert staticcall base.KYCValidator(kyc_validator_addr).check_validations_pair(borrower_kyc, lender_kyc), "KYC validation fail"
    assert lender_kyc.validation.wallet == offer.offer.lender, "KYC validation fail"
    assert borrower_kyc.validation.wallet == borrower, "KYC validation fail"
    assert offer.offer.borrower == empty(address) or offer.offer.borrower == borrower, "borrower not allowed"
    assert offer.offer.principal == 0 or offer.offer.principal == principal, "offer principal mismatch"
    assert offer.offer.min_collateral_amount <= collateral_amount, "low collateral amount"
    assert offer.offer.origination_fee_bps <= BPS, "origination fee gt principal"

    convertion_rate: base.UInt256Rational = self._get_oracle_rate()

    max_initial_ltv: uint256 = offer.offer.max_iltv
    if offer.offer.max_iltv == 0:
        max_initial_ltv = self._compute_ltv(offer.offer.min_collateral_amount, principal, convertion_rate)

    initial_ltv: uint256 = self._compute_ltv(collateral_amount, principal, convertion_rate)
    assert initial_ltv <= max_initial_ltv, "initial ltv gt max iltv"

    if offer.offer.liquidation_ltv > 0:
        assert offer.offer.liquidation_ltv > max_initial_ltv, "liquidation ltv le initial ltv"
        # required for soft liquidation: (1 + f) * iltv < 1
        assert (BPS + base.partial_liquidation_fee) * max_initial_ltv < BPS * BPS, "initial ltv too high"

    offer_id: bytes32 = base._compute_signed_offer_id(offer)
    loan: base.Loan = base.Loan(
        id=empty(bytes32),
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        initial_amount=principal,
        amount=principal,
        apr=offer.offer.apr,
        payment_token=offer.offer.payment_token,
        maturity=block.timestamp + offer.offer.duration,
        start_time=block.timestamp,
        accrual_start_time=block.timestamp,
        borrower=borrower,
        lender=offer.offer.lender,
        collateral_token=collateral_token,
        collateral_amount=collateral_amount,
        min_collateral_amount=offer.offer.min_collateral_amount,
        origination_fee_amount=offer.offer.origination_fee_bps * principal // BPS,
        protocol_upfront_fee_amount=base.protocol_upfront_fee * principal // BPS,
        protocol_settlement_fee=base.protocol_settlement_fee,
        partial_liquidation_fee=base.partial_liquidation_fee,
        full_liquidation_fee=base.full_liquidation_fee,
        call_eligibility=offer.offer.call_eligibility,
        call_window=offer.offer.call_window,
        liquidation_ltv=offer.offer.liquidation_ltv,
        oracle_addr=oracle_addr,
        initial_ltv=max_initial_ltv,
        call_time=0,
        vault_id=base.vault_count[borrower],
        redeem_start=0,
        redeem_residual_collateral=0,
    )
    loan.id = base._compute_loan_id(loan)

    assert base.loans[loan.id] == empty(bytes32), "loan already exists"
    base._check_and_update_offer_state(offer, principal)
    base.loans[loan.id] = base._loan_state_hash(loan)

    _vault: vault.Vault = base._create_new_vault(loan.borrower, vault_impl_addr, collateral_token, base.vault_registrar)
    base._receive_collateral(loan.borrower, loan.collateral_amount, _vault)
    self._transfer_funds(loan.lender, loan.borrower, loan.amount - loan.origination_fee_amount)

    if loan.protocol_upfront_fee_amount > 0:
        self._transfer_funds(loan.lender, base.protocol_wallet, loan.protocol_upfront_fee_amount)

    log LoanCreated(
        id=loan.id,
        amount=loan.initial_amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv=loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv=loan.initial_ltv,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        offer_id=offer_id,
        offer_tracing_id=offer.offer.tracing_id,
        oracle_rate_num=convertion_rate.numerator,
        oracle_rate_den=convertion_rate.denominator,
        vault_id=loan.vault_id,
        vault_addr=_vault.address,
    )
    return loan.id


@external
def settle_loan(loan: base.Loan, redeem_result: base.SignedRedeemResult):

    """
    @notice Settle a loan.
    @param loan The loan to be settled.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert base._check_user(loan.borrower), "not borrower"

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    in_vault_collateral: uint256 = 0
    in_vault_payment_token: uint256 = 0
    if base._is_loan_redeemed(loan):
        assert base._is_loan_redeem_concluded(loan, _vault, redeem_result), "redeem not concluded"
        in_vault_payment_token, in_vault_collateral = base._get_redeem_balances(loan, _vault, payment_token, redeem_result.result)

    interest: uint256 = base._compute_settlement_interest(loan)
    protocol_settlement_fee: uint256 = loan.protocol_settlement_fee * interest // BPS

    base.loans[loan.id] = empty(bytes32)
    base._reduce_commited_liquidity(loan.lender, loan.offer_tracing_id, loan.amount)

    if in_vault_payment_token > 0:
        extcall _vault.withdraw_funds(loan.payment_token, in_vault_payment_token)

    # in_vault_payment_token + received funds - funds_returned_to_borrower == loan.amount + interest
    # in_vault_payment_token - (loan.amount + interest) == borrower_funds_delta

    borrower_funds_delta: int256 = convert(in_vault_payment_token, int256) - convert(loan.amount + interest, int256)
    if borrower_funds_delta < 0:
        self._receive_funds(loan.borrower, convert(-borrower_funds_delta, uint256))
    elif borrower_funds_delta > 0:
        self._send_funds(loan.borrower, convert(borrower_funds_delta, uint256))

    self._send_funds(loan.lender, loan.amount + interest - protocol_settlement_fee)
    if protocol_settlement_fee > 0:
        self._send_funds(base.protocol_wallet, protocol_settlement_fee)

    # collateral in vault can be 0 < ... < loan.collateral_amount < ...
    base._send_collateral(loan.borrower, in_vault_collateral, _vault)

    log LoanPaid(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        payment_token=loan.payment_token,
        paid_principal=loan.amount,
        paid_interest=interest,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee_amount=protocol_settlement_fee,
        in_vault_payment_token=in_vault_payment_token,
        in_vault_collateral=in_vault_collateral,
    )


@external
def partially_liquidate_loan(loan: base.Loan):

    """
    @notice Partialy liquidates a loan if the LTV exceeds the liquidation_ltv, resulting in a write-off of part of the debt and transfer of part of the collateral to the lender. The loan remains active. Can be called by anyone.
    @param loan The loan to be soft liquidated.
    """
    raw_call(
        liquidation_addr,
        abi_encode(
            loan,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            vault_impl_addr,
            method_id=method_id("partially_liquidate_loan((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),address,address,address,bool,address,uint256,uint256,bytes32,address)"),
        ),
        is_delegate_call=True
    )



@external
def liquidate_loan(loan: base.Loan, redeem_result: base.SignedRedeemResult):

    """
    @notice Fully liquidates a defaulted loan. Can be called by anyone.
    @param loan The loan to be soft liquidated.
    """

    raw_call(
        liquidation_addr,
        abi_encode(
            loan,
            redeem_result,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            vault_impl_addr,
            method_id=method_id("liquidate_loan((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),((address,uint256,uint256,uint256),(uint256,uint256,uint256)),address,address,address,bool,address,uint256,uint256,bytes32,address)"),
        ),
        is_delegate_call=True
    )


@external
def add_collateral_to_loan(loan: base.Loan, collateral_amount: uint256):

    """
    @notice Add collateral to a loan.
    @param loan The loan to which collateral is to be added.
    @param collateral_amount The amount of collateral tokens to be added.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._check_user(loan.borrower), "not borrower"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert not base._is_loan_redeemed(loan), "loan redeemed"

    convertion_rate: base.UInt256Rational = self._get_oracle_rate()
    outstanding_debt: uint256 = loan.amount + base._compute_settlement_interest(loan)
    old_ltv: uint256 = self._compute_ltv(loan.collateral_amount, outstanding_debt, convertion_rate)
    new_ltv: uint256 = self._compute_ltv(loan.collateral_amount + collateral_amount, outstanding_debt, convertion_rate)

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    base._receive_collateral(loan.borrower, collateral_amount, _vault)

    updated_loan: base.Loan = base.Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount + collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv= loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time,
        vault_id=loan.vault_id,
        redeem_start=loan.redeem_start,
        redeem_residual_collateral=loan.redeem_residual_collateral,
    )
    base.loans[updated_loan.id] = base._loan_state_hash(updated_loan)

    log LoanCollateralAdded(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        old_collateral_amount=loan.collateral_amount,
        new_collateral_amount=updated_loan.collateral_amount,
        old_ltv=old_ltv,
        new_ltv=new_ltv
    )

@external
def remove_collateral_from_loan(loan: base.Loan, collateral_amount: uint256):

    """
    @notice Add collateral to a loan.
    @param loan The loan to which collateral is to be added.
    @param collateral_amount The amount of collateral tokens to be added.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._check_user(loan.borrower), "not borrower"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert not base._is_loan_redeemed(loan), "loan redeemed"

    assert loan.min_collateral_amount + collateral_amount <= loan.collateral_amount, "collateral bellow min"

    convertion_rate: base.UInt256Rational = self._get_oracle_rate()
    outstanding_debt: uint256 = loan.amount + base._compute_settlement_interest(loan)
    old_ltv: uint256 = self._compute_ltv(loan.collateral_amount, outstanding_debt, convertion_rate)
    new_ltv: uint256 = self._compute_ltv(loan.collateral_amount - collateral_amount, outstanding_debt, convertion_rate)

    assert loan.initial_ltv >= new_ltv, "ltv gt initial ltv"

    updated_loan: base.Loan = base.Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount - collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv= loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time,
        vault_id=loan.vault_id,
        redeem_start=loan.redeem_start,
        redeem_residual_collateral=loan.redeem_residual_collateral,
    )
    base.loans[updated_loan.id] = base._loan_state_hash(updated_loan)

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    base._send_collateral(loan.borrower, collateral_amount, _vault)

    log LoanCollateralRemoved(
        id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        old_collateral_amount=loan.collateral_amount,
        new_collateral_amount=updated_loan.collateral_amount,
        old_ltv=old_ltv,
        new_ltv=new_ltv
    )


@external
def extend_loan(
    loan: base.Loan,
    offer: base.SignedLoanExtensionOffer,
    new_maturity: uint256,
):

    """
    @notice Extend a loan.
    @dev All loan parameters remain the same except the maturity which is extended to the new maturity. Must be called by the borrower and the offer must be signed by the lender.
    @param loan The current loan.
    @param offer The signed offer for the loan extension.
    @param new_maturity The new maturity timestamp for the loan.
    """

    raw_call(
        refinance_addr,
        abi_encode(
            loan,
            offer,
            new_maturity,
            offer_sig_domain_separator,
            method_id=method_id("extend_loan((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),((bytes32,uint256,uint256),(uint256,uint256,uint256)),uint256,bytes32)"),
        ),
        is_delegate_call=True
    )



@external
def extend_loan_lender(loan: base.Loan, new_maturity: uint256):

    """
    @notice Extend a loan.
    @dev All loan parameters remain the same except the maturity which is extended to the new maturity. Must be called by the lender.
    @param loan The current loan.
    @param new_maturity The new maturity timestamp for the loan.
    """

    raw_call(
        refinance_addr,
        abi_encode(
            loan,
            new_maturity,
            method_id=method_id("extend_loan_lender((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),uint256)"),
        ),
        is_delegate_call=True
    )



@external
def revoke_offer(offer: base.SignedOffer):

    """
    @notice Revoke an offer.
    @param offer The signed offer to be revoked.
    """

    assert base._check_user(offer.offer.lender), "not lender"
    assert offer.offer.expiration > block.timestamp, "offer expired"
    assert base._is_offer_signed_by_lender(offer, offer_sig_domain_separator), "offer not signed by lender"

    offer_id: bytes32 = base._compute_signed_offer_id(offer)
    assert not base.revoked_offers[offer_id], "offer already revoked"

    base._revoke_offer(offer_id, offer)


@external
def claim_pending_transfers():
    assert base.pending_transfers[msg.sender] > 0, "no pending transfers"
    _amount: uint256 = base.pending_transfers[msg.sender]
    base.pending_transfers[msg.sender] = 0

    assert extcall IERC20(payment_token).transfer(msg.sender, _amount), "error sending funds"
    log PendingTransfersClaimed(_to=msg.sender, amount=_amount)



@view
@external
def current_ltv(loan: base.Loan) -> uint256:

    """
    @notice Get the current LTV of a loan.
    @param loan The loan to get the current LTV for.
    @return The current LTV of the loan.
    """

    assert base._is_loan_valid(loan), "invalid loan"

    convertion_rate: base.UInt256Rational = self._get_oracle_rate()
    return self._compute_ltv(loan.collateral_amount, loan.amount + base._compute_settlement_interest(loan), convertion_rate)


@view
@external
def is_loan_defaulted(loan: base.Loan) -> bool:

    """
    @notice Check if a loan is defaulted.
    @param loan The loan to check.
    @return True if the loan is defaulted, false otherwise.
    """

    return base._is_loan_defaulted(loan)


@view
@external
def is_loan_redeemed(loan: base.Loan) -> bool:
    """
    @notice Check if a loan started a redeem process.
    @param loan The loan to check.
    @return True if the loan is redeemed, false otherwise.
    """

    return base._is_loan_redeemed(loan)


@view
@external
def simulate_partial_liquidation(loan: base.Loan) -> base.PartialLiquidationResult:
    """
    @notice Simulates a partial liquidation of a loan.
    @param loan The loan to simulate a partial liquidation for.
    @return The result of the partial liquidation simulation.
    """
    return staticcall StaticSelf(self)._simulate_partial_liquidation(loan)


@external
def _simulate_partial_liquidation(loan: base.Loan) -> base.PartialLiquidationResult:

    assert msg.sender == self
    return abi_decode(raw_call(
        liquidation_addr,
        abi_encode(
            loan,
            oracle_addr,
            oracle_reverse,
            payment_token_decimals,
            collateral_token_decimals,
            method_id=method_id("simulate_partial_liquidation((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),address,bool,uint256,uint256)"),
        ),
        max_outsize=128,
        is_delegate_call=True,
    ), base.PartialLiquidationResult)


@external
def replace_loan(
    loan: base.Loan,
    offer: base.SignedOffer,
    principal: uint256,
    collateral_amount: uint256,
    lender_kyc: base.SignedWalletValidation,
) -> bytes32:

    """
    @notice Replace an existing loan by accepting a new offer over the same collateral. The current loan is settled and the new loan is created. Must be called by the borrower.
    @dev The borrower must be the same as the borrower of the current loan.
    @param loan The loan to be replaced.
    @param offer The new signed offer.
    @param principal The principal amount of the new loan, 0 means the outstanding debt
    @param collateral_amount The amount of collateral tokens to be used for the new loan.
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the new loan.
    """
    return convert(raw_call(
        refinance_addr,
        abi_encode(
            loan,
            offer,
            principal,
            collateral_amount,
            lender_kyc,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            vault_impl_addr,
            method_id=method_id("replace_loan((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),((uint256,uint256,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,address,address,bytes32),(uint256,uint256,uint256)),uint256,uint256,((address,uint256),(uint256,uint256,uint256)),address,address,address,bool,address,uint256,uint256,bytes32,address)"),
        ),
        max_outsize=32,
        is_delegate_call=True
    ), bytes32)


@external
def replace_loan_lender(
    loan: base.Loan,
    offer: base.SignedOffer,
    principal: uint256,
    lender_kyc: base.SignedWalletValidation,
) -> bytes32:

    """
    @notice Sell an existing loan by accepting a new offer over the same collateral. The current loan is settled and the new loan is created. Must be called by the lender.
    @dev No collateral transfer is required. The borrower must be the same as the borrower of the current loan.
    @param loan The loan to be replaced.
    @param offer The new signed offer.
    @param principal The principal amount of the new loan, 0 means the outstanding debt
    @param lender_kyc The signed KYC validation for the lender.
    @return The ID of the new loan.
    """

    return convert(raw_call(
        refinance_addr,
        abi_encode(
            loan,
            offer,
            principal,
            lender_kyc,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            method_id=method_id("replace_loan_lender((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),((uint256,uint256,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,address,address,bytes32),(uint256,uint256,uint256)),uint256,((address,uint256),(uint256,uint256,uint256)),address,address,address,bool,address,uint256,uint256,bytes32)"),
        ),
        max_outsize=32,
        is_delegate_call=True
    ), bytes32)


@view
@external
def wallet_to_vault(wallet: address) -> address:

    """
    @notice Get the vault address for a given wallet
    @param wallet The wallet address
    @return The vault address for the given wallet
    """

    return base._wallet_to_vault(wallet, base.vault_count[wallet], vault_impl_addr)

@view
@external
def vault_id_to_vault(wallet: address, vault_id: uint256) -> address:

    """
    @notice Get the vault address for a given wallet
    @param wallet The wallet address
    @return The vault address for the given wallet
    """

    return base._wallet_to_vault(wallet, vault_id, vault_impl_addr)

@external
def create_vault_if_needed(wallet: address):

    """
    @notice Create a vault for a given wallet if it does not exist
    @param wallet The wallet address
    """

    base._create_vault_if_needed(wallet, vault_impl_addr, collateral_token, base.vault_registrar)


@external
def redeem(loan: base.Loan, residual_collateral: uint256):
    """
    @notice Redeem a loan by paying off the outstanding debt and reclaiming the collateral.
    @param loan The loan to be redeemed.
    """

    assert base._is_loan_valid(loan), "invalid loan"
    assert base._check_user(loan.borrower), "not borrower"
    assert not base._is_loan_defaulted(loan), "loan defaulted"
    assert not base._is_loan_redeemed(loan), "loan already redeemed"
    assert base.securitize_redemption_wallet != empty(address), "redemption wallet not set"

    assert residual_collateral <= loan.collateral_amount, "residual collateral gt total"

    updated_loan: base.Loan = base.Loan(
        id=loan.id,
        offer_id=loan.offer_id,
        offer_tracing_id=loan.offer_tracing_id,
        initial_amount=loan.initial_amount,
        amount=loan.amount,
        apr=loan.apr,
        payment_token=loan.payment_token,
        maturity=loan.maturity,
        start_time=loan.start_time,
        accrual_start_time=loan.accrual_start_time,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        collateral_amount=loan.collateral_amount,
        min_collateral_amount=loan.min_collateral_amount,
        origination_fee_amount=loan.origination_fee_amount,
        protocol_upfront_fee_amount=loan.protocol_upfront_fee_amount,
        protocol_settlement_fee=loan.protocol_settlement_fee,
        partial_liquidation_fee=loan.partial_liquidation_fee,
        full_liquidation_fee=loan.full_liquidation_fee,
        call_eligibility=loan.call_eligibility,
        call_window=loan.call_window,
        liquidation_ltv= loan.liquidation_ltv,
        oracle_addr=loan.oracle_addr,
        initial_ltv= loan.initial_ltv,
        call_time=loan.call_time,
        vault_id=loan.vault_id,
        redeem_start=block.timestamp,
        redeem_residual_collateral=residual_collateral
    )
    base.loans[updated_loan.id] = base._loan_state_hash(updated_loan)

    _vault: vault.Vault = base._get_vault(loan.borrower, loan.vault_id, vault_impl_addr)
    base._send_collateral(base.securitize_redemption_wallet, loan.collateral_amount - residual_collateral, _vault)

    log LoanCollateralRedeemStarted(
        loan_id=loan.id,
        borrower=loan.borrower,
        lender=loan.lender,
        collateral_token=loan.collateral_token,
        vault_id=loan.vault_id,
        redeem_start=updated_loan.redeem_start,
        redeem_residual_collateral=updated_loan.redeem_residual_collateral,
    )


@external
def transfer_loan(loan: base.Loan, new_borrower: address, new_borrower_kyc: base.SignedWalletValidation, redeem_result: base.SignedRedeemResult):

    """
    @notice Transfer a loan to a new borrower.
    @dev Only allowed to be called by the transfer agent. Used for supporting cases of death, lost keys, or legal transfers
    @param loan The loan to be transferred.
    @param new_borrower The address of the new borrower.
    @param new_borrower_kyc The signed KYC validation for the new borrower.
    @param redeem_result The signed redeem result if the loan is in redeem, empty otherwise.
    """

    raw_call(
        liquidation_addr,
        abi_encode(
            loan,
            new_borrower,
            new_borrower_kyc,
            redeem_result,
            payment_token,
            collateral_token,
            oracle_addr,
            oracle_reverse,
            kyc_validator_addr,
            collateral_token_decimals,
            payment_token_decimals,
            offer_sig_domain_separator,
            vault_impl_addr,
            base.vault_registrar,
            method_id=method_id("transfer_loan((bytes32,bytes32,bytes32,uint256,uint256,uint256,address,uint256,uint256,uint256,address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256),address,((address,uint256),(uint256,uint256,uint256)),((address,uint256,uint256,uint256),(uint256,uint256,uint256)),address,address,address,bool,address,uint256,uint256,bytes32,address,address)"),
        ),
        is_delegate_call=True
    )



# Internal functions

@internal
def _is_offer_signed_by_lender(signed_offer: base.SignedOffer) -> bool:
    return base._is_offer_signed_by_lender(signed_offer, offer_sig_domain_separator)


@internal
def _check_offer_validity(offer: base.SignedOffer):
    base._check_offer_validity(offer, payment_token, collateral_token, oracle_addr)

@view
@internal
def _get_oracle_rate() -> base.UInt256Rational:
    return base._get_oracle_rate(oracle_addr, oracle_reverse)


@view
@internal
def _compute_ltv(collateral_amount: uint256, amount: uint256, convertion_rate: base.UInt256Rational) -> uint256:
    return base._compute_ltv(collateral_amount, amount, convertion_rate, payment_token_decimals, collateral_token_decimals)


@internal
def _send_funds(_to: address, _amount: uint256):
    base._send_funds(_to, _amount, payment_token)


@internal
def _receive_funds(_from: address, _amount: uint256):
    base._receive_funds(_from, _amount, payment_token)


@internal
def _transfer_funds(_from: address, _to: address, _amount: uint256):
    base._transfer_funds(_from, _to, _amount, payment_token)
