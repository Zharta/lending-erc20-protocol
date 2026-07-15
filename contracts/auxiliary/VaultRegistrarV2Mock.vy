# @version 0.4.3

"""
@title VaultRegistrarV2Mock
@notice Mock implementation of VaultRegistrar V2 interface for testing.
        Validates EIP-712 signatures matching the real VaultRegistrar.sol contract.
"""


struct Registration:
    registered: bool
    deadline: uint256
    signature: Bytes[65]


DOMAIN_TYPE_HASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
REGISTER_TYPEHASH: constant(bytes32) = keccak256("RegisterVault(address investor,address operator,address token,uint256 nonce,uint256 deadline)")
REGISTRAR_NAME: constant(String[15]) = "VaultRegistrar"
REGISTRAR_VERSION: constant(String[1]) = "1"

MALLEABILITY_THRESHOLD: constant(uint256) = 57896044618658097711785492504343953926418782139537452191302581570759553434880
EIP1271_MAGIC_VALUE: constant(bytes4) = 0x1626ba7e

interface EIP1271Signer:
    def isValidSignature(hash: bytes32, signature: Bytes[65]) -> bytes4: view

domain_separator: immutable(bytes32)

token_addr: public(address)
registered: public(HashMap[address, HashMap[address, bool]])
registrations: public(HashMap[address, HashMap[address, Registration]])
operator_nonces: public(HashMap[address, HashMap[address, uint256]])


@deploy
def __init__(_token: address):
    """
    @notice Initialize the mock vault registrar
    @param _token The token address this registrar is associated with
    """
    self.token_addr = _token

    domain_separator = keccak256(
        abi_encode(
            DOMAIN_TYPE_HASH,
            keccak256(REGISTRAR_NAME),
            keccak256(REGISTRAR_VERSION),
            chain.id,
            self
        )
    )


@view
@external
def token() -> address:
    """
    @notice Returns the token address associated with this registrar
    @return The token address
    """
    return self.token_addr


@view
@external
def isRegistered(vaultAddress: address, investorWalletAddress: address) -> bool:
    """
    @notice Check if a vault is registered for an investor
    @param vaultAddress The vault address
    @param investorWalletAddress The investor wallet address
    @return True if the vault is registered for the investor
    """
    return self.registered[vaultAddress][investorWalletAddress]


@external
def registerVault(vaultAddress: address, investorWalletAddress: address, deadline: uint256, signature: Bytes[65]):
    """
    @notice Register a vault for an investor, validating the EIP-712 signature
    @param vaultAddress The vault address
    @param investorWalletAddress The investor wallet address (signer)
    @param deadline Unix timestamp after which the signature is invalid
    @param signature EIP-712 signature bytes (r[32] + s[32] + v[1])
    """
    assert block.timestamp <= deadline, "signature expired"
    assert len(signature) == 65, "invalid signature length"

    r: uint256 = convert(slice(signature, 0, 32), uint256)
    s: uint256 = convert(slice(signature, 32, 32), uint256)
    v: uint256 = convert(slice(signature, 64, 1), uint256)

    assert s <= MALLEABILITY_THRESHOLD, "invalid signature"

    operator: address = msg.sender
    nonce: uint256 = self.operator_nonces[investorWalletAddress][operator]

    message_hash: bytes32 = keccak256(
        concat(
            convert("\x19\x01", Bytes[2]),
            abi_encode(
                domain_separator,
                keccak256(abi_encode(
                    REGISTER_TYPEHASH,
                    investorWalletAddress,
                    operator,
                    self.token_addr,
                    nonce,
                    deadline
                ))
            )
        )
    )

    if investorWalletAddress.is_contract:
        assert staticcall EIP1271Signer(investorWalletAddress).isValidSignature(message_hash, signature) == EIP1271_MAGIC_VALUE, "invalid investor signature"
    else:
        signer: address = ecrecover(message_hash, v, r, s)
        assert signer == investorWalletAddress, "invalid investor signature"

    self.registered[vaultAddress][investorWalletAddress] = True
    self.registrations[vaultAddress][investorWalletAddress] = Registration(
        registered=True,
        deadline=deadline,
        signature=signature,
    )


@external
def unregisterVault(vaultAddress: address, investorWalletAddress: address):
    """
    @notice Unregister a vault for an investor
    @param vaultAddress The vault address
    @param investorWalletAddress The investor wallet address
    """
    self.registered[vaultAddress][investorWalletAddress] = False
    self.registrations[vaultAddress][investorWalletAddress] = Registration(
        registered=False,
        deadline=0,
        signature=b"",
    )


@view
@external
def operatorNonce(investor: address, operator: address) -> uint256:
    """
    @notice Get the operator nonce for an investor
    @param investor The investor address
    @param operator The operator address
    @return The nonce value
    """
    return self.operator_nonces[investor][operator]


@external
def invalidateOperatorPermission(operator: address):
    """
    @notice Invalidate an operator's permission (increments nonce)
    @param operator The operator address
    """
    self.operator_nonces[msg.sender][operator] += 1


@external
def set_operator_nonce(investor: address, operator: address, nonce: uint256):
    """
    @notice Test helper to set a specific operator nonce
    @param investor The investor address
    @param operator The operator address
    @param nonce The nonce value to set
    """
    self.operator_nonces[investor][operator] = nonce
