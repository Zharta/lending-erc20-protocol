# @version 0.4.3

"""
@title SecuritizeRegistrarConnector
@author [Zharta](https://zharta.io/)
@notice This contract connects the vault registrar to the Securitize Registrar, allowing vaults to be registered
@dev Intendend

"""

# Interfaces

interface P2PLendingContract:
    def wallet_to_vault(wallet: address) -> address: view
    def vault_id_to_vault(wallet: address, vault_id: uint256) -> address: view

interface VaultRegistrar:
    def isRegistered(vaultAddress: address, investorWalletAddress: address) -> bool: view
    # def registerVault(vaultAddress: address, investorWalletAddress: address): nonpayable
    def registerVault(vaultAddress: address, investorWalletAddress: address, deadline: uint256, signature: Bytes[65]): nonpayable
    def unregisterVault(vaultAddress: address, investorWalletAddress: address): nonpayable
    def token() -> address: view
    def operatorNonce(investor: address, operator: address) -> uint256: view
    def invalidateOperatorPermission(operator: address): nonpayable

interface EIP1271Signer:
    def isValidSignature(hash: bytes32, signature: Bytes[65]) -> bytes4: view

struct ContractAuthorization:
    contract_address: address
    authorized: bool

struct Signature:
    v: uint256
    r: uint256
    s: uint256

struct RegistrarSignature:
    deadline: uint256
    signature: Signature

event ContractAuthorizationChanged:
    contract_address: address
    authorized: bool


VERSION: public(constant(String[26])) = "SecRegV2Connector.20260716"

DOMAIN_TYPE_HASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
REGISTER_TYPEHASH: constant(bytes32) = keccak256("RegisterVault(address investor,address operator,address token,uint256 nonce,uint256 deadline)")
REGISTRAR_NAME: constant(String[15]) = "VaultRegistrar"
REGISTRAR_VERSION: constant(String[1]) = "1"

MALLEABILITY_THRESHOLD: constant(uint256) = 57896044618658097711785492504343953926418782139537452191302581570759080747168
EIP1271_MAGIC_VALUE: constant(bytes4) = 0x1626ba7e

registrar_domain_separator: immutable(bytes32)

authorized_contracts: public(HashMap[address, bool])
investor_signatures: public(HashMap[address, RegistrarSignature])
vault_registrar: public(immutable(address))
owner: public(immutable(address))


@deploy
def __init__(_vault_registrar_addr: address):

    """
    @notice Initialize the contract with the given parameters.
    @param _vault_registrar_addr The address of the vault registrar contract.
    """

    vault_registrar = _vault_registrar_addr
    owner = msg.sender
    registrar_domain_separator = keccak256(
        abi_encode(
            DOMAIN_TYPE_HASH,
            keccak256(REGISTRAR_NAME),
            keccak256(REGISTRAR_VERSION),
            chain.id,
            _vault_registrar_addr
        )
    )


@external
def change_authorized_contract(contract_address: address, authorized: bool):
    """
    @notice Change the authorization status of a single contract.
    @param contract_address The address of the contract to change authorization for.
    @param authorized The new authorization status for the contract.
    """

    assert msg.sender == owner, "not owner"
    self.authorized_contracts[contract_address] = authorized

    log ContractAuthorizationChanged(contract_address=contract_address, authorized=authorized)


@external
def register_vault(vault: address, investor_wallet: address):
    """
        @notice Register a vault with the vault registrar for a given investor wallet.
        @param vault The address of the vault to register.
        @param investor_wallet The address of the investor wallet associated with the vault.
    """

    assert self.authorized_contracts[msg.sender], "not authorized"
    signature: RegistrarSignature = self.investor_signatures[investor_wallet]
    if not staticcall VaultRegistrar(vault_registrar).isRegistered(vault, investor_wallet):
        extcall VaultRegistrar(vault_registrar).registerVault(vault, investor_wallet, signature.deadline, self._sig_to_bytes65(signature.signature))


@external
def set_investor_signature(deadline: uint256, signature: Signature):
    """
    @notice Set the signature for an investor wallet to be used for vault registration.
    @param deadline The timestamp until which the signature is valid.
    @param signature The signature components (v, r, s) for the investor wallet.
    """

    if deadline == 0:
        # Allow clearing the signature by setting deadline to 0
        self.investor_signatures[msg.sender] = empty(RegistrarSignature)
        return

    assert deadline > block.timestamp, "signature expired"
    assert self._validate_signature(msg.sender, deadline, signature), "invalid signature"

    self.investor_signatures[msg.sender] = RegistrarSignature(deadline=deadline, signature=signature)



@internal
def _validate_signature(investor_wallet: address, deadline: uint256, signature: Signature) -> bool:

    assert signature.s <= MALLEABILITY_THRESHOLD, "invalid signature"
    assert investor_wallet != empty(address), "invalid signature"

    nonce: uint256 = staticcall VaultRegistrar(vault_registrar).operatorNonce(investor_wallet, self)
    token: address = staticcall VaultRegistrar(vault_registrar).token()

    message_hash: bytes32 = keccak256(
        concat(
            convert("\x19\x01", Bytes[2]),
            abi_encode(
                registrar_domain_separator,
                keccak256(abi_encode(
                    REGISTER_TYPEHASH,
                    investor_wallet,
                    self,
                    token,
                    nonce,
                    deadline
                ))
            )
        )
    )

    signer: address = ecrecover(
        message_hash,
        signature.v,
        signature.r,
        signature.s
    )

    # EOAs with an EIP-7702 delegation have code, so check signature before falling back to ERC-1271
    if signer == investor_wallet:
        return True

    if investor_wallet.is_contract:
        return staticcall EIP1271Signer(investor_wallet).isValidSignature(message_hash, self._sig_to_bytes65(signature)) == EIP1271_MAGIC_VALUE

    return False


@pure
@internal
def _sig_to_bytes65(s: Signature) -> Bytes[65]:
    return concat(convert(s.r, bytes32), convert(s.s, bytes32), convert(convert(s.v, uint8), bytes1))
