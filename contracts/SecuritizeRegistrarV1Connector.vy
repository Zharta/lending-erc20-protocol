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

event ContractsAuthorizationChanged:
    contracts: DynArray[ContractAuthorization, CHANGE_BATCH]


VERSION: public(constant(String[26])) = "SecRegV1Connector.20260127"
CHANGE_BATCH: constant(uint256) = 32

authorized_contracts: public(HashMap[address, bool])
vault_registrar: public(immutable(address))
owner: public(immutable(address))


@deploy
def __init__(_vault_registrar_addr: address, _authorized_contracts: DynArray[address, CHANGE_BATCH]):

    """
    @notice Initialize the contract with the given parameters.
    @param _vault_registrar_addr The address of the vault registrar contract.
    @param _authorized_contracts An array of addresses that are authorized to call the registerVault
    """

    vault_registrar = _vault_registrar_addr
    owner = msg.sender
    for addr: address in _authorized_contracts:
        if addr != empty(address):
            self.authorized_contracts[addr] = True


@external
def change_authorized_contracts(contracts: DynArray[ContractAuthorization, CHANGE_BATCH]):
    """
    @notice Change a list of authorized contracts.
    @param contracts An array of ContractAuthorization structs, each containing a contract address and a boolean indicating whether it should be authorized or deauthorized.
    """

    assert msg.sender == owner, "not owner"
    for c: ContractAuthorization in contracts:
        self.authorized_contracts[c.contract_address] = c.authorized

    log ContractsAuthorizationChanged(contracts=contracts)


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


