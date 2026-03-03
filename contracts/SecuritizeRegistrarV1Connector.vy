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
    def registerVault(vaultAddress: address, investorWalletAddress: address): nonpayable


struct ContractAuthorization:
    contract_address: address
    authorized: bool

event ContractAuthorizationChanged:
    contract_address: address
    authorized: bool


VERSION: public(constant(String[26])) = "SecRegV1Connector.20260303"
CHANGE_BATCH: constant(uint256) = 32

authorized_contracts: public(HashMap[address, bool])
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
    if not staticcall VaultRegistrar(vault_registrar).isRegistered(vault, investor_wallet):
        extcall VaultRegistrar(vault_registrar).registerVault(vault, investor_wallet)
