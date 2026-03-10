# @version 0.4.3

"""
@title VaultRegistrarMock
@notice Mock implementation of VaultRegistrar interface for testing and development
"""


token_addr: public(address)
registered: public(HashMap[address, HashMap[address, bool]])


@deploy
def __init__(_token: address):
    """
    @notice Initialize the mock vault registrar
    @param _token The token address this registrar is associated with
    """
    self.token_addr = _token


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
def registerVault(vaultAddress: address, investorWalletAddress: address):
    """
    @notice Register a vault for an investor
    @param vaultAddress The vault address
    @param investorWalletAddress The investor wallet address
    """
    self.registered[vaultAddress][investorWalletAddress] = True
