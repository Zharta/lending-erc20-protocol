# @version 0.4.3

"""
@title KYCValidator
@author [Zharta](https://zharta.io/)
@notice This contract is used to validate wallets based on signed data from a KYC validator.
"""

# Structs

struct WalletValidation:
    wallet: address
    expiration_time: uint256

struct Signature:
    v: uint256
    r: uint256
    s: uint256

struct SignedWalletValidation:
    validation: WalletValidation
    signature: Signature

event ValidatorSet:
    old_validator: address
    new_validator: address

event OwnerProposed:
    owner: address
    proposed_owner: address

event OwnershipTransferred:
    old_owner: address
    new_owner: address

# Global variables

owner: public(address)
proposed_owner: public(address)

validator: public(address)

VERSION: public(constant(String[30])) = "KYCValidator.20250826"

ZHARTA_DOMAIN_NAME: constant(String[6]) = "Zharta"
ZHARTA_DOMAIN_VERSION: constant(String[1]) = "1"

DOMAIN_TYPE_HASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
VALIDATION_TYPE_DEF: constant(String[56]) = "WalletValidation(address wallet,uint256 expiration_time)"
VALIDATION_TYPE_HASH: constant(bytes32) = keccak256(VALIDATION_TYPE_DEF)

validation_sig_domain_separator: immutable(bytes32)


@deploy
def __init__(_validator: address):

    """
    @notice Initialize the contract with the given parameters.
    @param _validator The address of the KYC validator
    """

    assert _validator != empty(address)
    self.owner = msg.sender
    self.validator = _validator

    validation_sig_domain_separator = keccak256(
        abi_encode(
            DOMAIN_TYPE_HASH,
            keccak256(ZHARTA_DOMAIN_NAME),
            keccak256(ZHARTA_DOMAIN_VERSION),
            chain.id,
            self
        )
    )


@external
def check_validation(validation: SignedWalletValidation) -> bool:
    """
    @notice Validate a wallet using the signed validation data.
    @param validation The signed wallet validation data
    @return True if the wallet is valid, False otherwise
    """
    return self._check_validation(validation)

@external
def check_validations_pair(validation1: SignedWalletValidation, validation2: SignedWalletValidation) -> bool:
    """
    @notice Validate a pair of wallets using the signed validation data.
    @param validation1 The signed wallet validation data for the first wallet
    @param validation2 The signed wallet validation data for the second wallet
    @return True if both wallets are valid, False otherwise
    """
    return self._check_validation(validation1) and self._check_validation(validation2)


@internal
def _check_validation(signed_validation: SignedWalletValidation) -> bool:
    return ecrecover(
        keccak256(
            concat(
                convert("\x19\x01", Bytes[2]),
                abi_encode(
                    validation_sig_domain_separator,
                    keccak256(abi_encode(VALIDATION_TYPE_HASH, signed_validation.validation))
                )
            )
        ),
        signed_validation.signature.v,
        signed_validation.signature.r,
        signed_validation.signature.s
    ) == self.validator and signed_validation.validation.expiration_time >= block.timestamp


@external
def propose_owner(_address: address):

    """
    @notice Propose a new owner
    @dev Proposes a new owner and logs the event. Admin function.
    @param _address The address of the proposed owner.
    """

    assert msg.sender == self.owner, "not owner"
    assert _address != empty(address), "address is zero"

    log OwnerProposed(owner=self.owner, proposed_owner=_address)
    self.proposed_owner = _address


@external
def claim_ownership():

    """
    @notice Claim the ownership of the contract
    @dev Claims the ownership of the contract and logs the event. Requires the caller to be the proposed owner.
    """

    assert msg.sender == self.proposed_owner, "not the proposed owner"

    log OwnershipTransferred(old_owner=self.owner, new_owner=self.proposed_owner)
    self.owner = msg.sender
    self.proposed_owner = empty(address)

@external
def set_validator(_validator: address):
    """
    @notice Set the KYC validator address.
    @param _validator The address of the KYC validator
    """
    assert msg.sender == self.owner, "not owner"
    assert _validator != empty(address), "empty validator"

    log ValidatorSet(old_validator=self.validator, new_validator=_validator)
    self.validator = _validator
