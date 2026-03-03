import json
from dataclasses import dataclass

from ape import project

from .basetypes import ContractConfig, DeploymentContext, abi_key
from .transactions import execute

ZERO_ADDRESS = "0x" + "00" * 20
ZERO_BYTES32 = "0x" + "00" * 32


def calculate_abi_key(filename: str) -> str:
    with open(filename, "r") as f:
        abi = json.load(f)
    return abi_key(abi)


class GenericContract(ContractConfig):
    _address: str
    _name: str

    def __init__(self, *, key: str, address: str, abi_key: str, name: str, abi_file: str, version: str | None = None):
        _abi_key = abi_key or calculate_abi_key(abi_file)
        super().__init__(key, None, None, version=version, abi_key=_abi_key)
        self._address = address
        self._name = name

    def address(self):
        return self._address

    def deployable(self, contract: DeploymentContext) -> bool:  # noqa: PLR6301, ARG002
        return False

    def __repr__(self):
        return f"GenericContract[key={self.key}, address={self._address}]"


@dataclass
class P2PLendingV0Erc20(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str,
        payment_token_key: str,
        collateral_token_key: str,
        oracle_key: str,
        oracle_reverse: bool = False,
        kyc_validator_key: str | None = None,
        refinance_impl_key: str | None = None,
        protocol_upfront_fee: int,
        protocol_settlement_fee: int,
        protocol_wallet: str,
        max_protocol_upfront_fee: int,
        max_protocol_settlement_fee: int,
        soft_liquidation_fee: int,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingV0Erc20,
            version=version,
            abi_key=abi_key,
            deployment_deps={payment_token_key, collateral_token_key, oracle_key, kyc_validator_key, refinance_impl_key},
            deployment_args=[
                payment_token_key,
                collateral_token_key,
                oracle_key,
                oracle_reverse,
                kyc_validator_key or ZERO_ADDRESS,
                protocol_upfront_fee,
                protocol_settlement_fee,
                protocol_wallet,
                max_protocol_upfront_fee,
                max_protocol_settlement_fee,
                soft_liquidation_fee,
                refinance_impl_key or ZERO_ADDRESS,
            ],
        )
        if address:
            self.load_contract(address)


@dataclass
class P2PLendingV0Securitize(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str,
        payment_token_key: str,
        collateral_token_key: str,
        oracle_key: str,
        oracle_reverse: bool = False,
        kyc_validator_key: str | None = None,
        refinance_impl_key: str | None = None,
        protocol_upfront_fee: int,
        protocol_settlement_fee: int,
        protocol_wallet: str,
        max_protocol_upfront_fee: int,
        max_protocol_settlement_fee: int,
        borrower: str,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingV0Securitize,
            version=version,
            abi_key=abi_key,
            deployment_deps={payment_token_key, collateral_token_key, oracle_key, kyc_validator_key, refinance_impl_key},
            deployment_args=[
                payment_token_key,
                collateral_token_key,
                oracle_key,
                oracle_reverse,
                kyc_validator_key or ZERO_ADDRESS,
                protocol_upfront_fee,
                protocol_settlement_fee,
                protocol_wallet,
                max_protocol_upfront_fee,
                max_protocol_settlement_fee,
                refinance_impl_key or ZERO_ADDRESS,
                borrower,
            ],
        )
        if address:
            self.load_contract(address)


@dataclass
class P2PLendingErc20(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str,
        payment_token_key: str,
        collateral_token_key: str,
        oracle_key: str,
        oracle_reverse: bool = False,
        kyc_validator_key: str | None = None,
        refinance_impl_key: str | None = None,
        liquidation_impl_key: str | None = None,
        protocol_upfront_fee: int,
        protocol_settlement_fee: int,
        protocol_wallet: str,
        max_protocol_upfront_fee: int,
        max_protocol_settlement_fee: int,
        soft_liquidation_fee: int,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingErc20,
            version=version,
            abi_key=abi_key,
            deployment_deps={
                payment_token_key,
                collateral_token_key,
                oracle_key,
                kyc_validator_key,
                refinance_impl_key,
                liquidation_impl_key,
            },
            deployment_args=[
                payment_token_key,
                collateral_token_key,
                oracle_key,
                oracle_reverse,
                kyc_validator_key or ZERO_ADDRESS,
                protocol_upfront_fee,
                protocol_settlement_fee,
                protocol_wallet,
                max_protocol_upfront_fee,
                max_protocol_settlement_fee,
                soft_liquidation_fee,
                refinance_impl_key or ZERO_ADDRESS,
                liquidation_impl_key or ZERO_ADDRESS,
            ],
        )
        if address:
            self.load_contract(address)


@dataclass
class P2PLendingSecuritize(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str,
        payment_token_key: str,
        collateral_token_key: str,
        oracle_key: str,
        oracle_reverse: bool = False,
        kyc_validator_key: str | None = None,
        refinance_impl_key: str | None = None,
        liquidation_impl_key: str | None = None,
        protocol_upfront_fee: int,
        protocol_settlement_fee: int,
        protocol_wallet: str,
        max_protocol_upfront_fee: int,
        max_protocol_settlement_fee: int,
        borrower: str,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingSecuritize,
            version=version,
            abi_key=abi_key,
            deployment_deps={
                payment_token_key,
                collateral_token_key,
                oracle_key,
                kyc_validator_key,
                refinance_impl_key,
                liquidation_impl_key,
            },
            deployment_args=[
                payment_token_key,
                collateral_token_key,
                oracle_key,
                oracle_reverse,
                kyc_validator_key or ZERO_ADDRESS,
                protocol_upfront_fee,
                protocol_settlement_fee,
                protocol_wallet,
                max_protocol_upfront_fee,
                max_protocol_settlement_fee,
                refinance_impl_key or ZERO_ADDRESS,
                liquidation_impl_key or ZERO_ADDRESS,
                borrower,
            ],
        )
        if address:
            self.load_contract(address)


@dataclass
class P2PLendingVaultedErc20(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str,
        payment_token_key: str,
        collateral_token_key: str,
        oracle_key: str,
        oracle_reverse: bool = False,
        kyc_validator_key: str | None = None,
        refinance_impl_key: str | None = None,
        liquidation_impl_key: str | None = None,
        vault_impl_key: str | None = None,
        protocol_upfront_fee: int,
        protocol_settlement_fee: int,
        protocol_wallet: str,
        transfer_agent: str,
        vault_registrar_connector_key: str | None = None,
        max_protocol_upfront_fee: int,
        max_protocol_settlement_fee: int,
        partial_liquidation_fee: int,
        full_liquidation_fee: int,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingVaultedErc20,
            version=version,
            abi_key=abi_key,
            deployment_deps={
                payment_token_key,
                collateral_token_key,
                oracle_key,
                kyc_validator_key,
                refinance_impl_key,
                vault_impl_key,
                liquidation_impl_key,
            }
            | ({vault_registrar_connector_key} if vault_registrar_connector_key else set()),
            deployment_args=[
                payment_token_key,
                collateral_token_key,
                oracle_key,
                oracle_reverse,
                kyc_validator_key or ZERO_ADDRESS,
                protocol_upfront_fee,
                protocol_settlement_fee,
                protocol_wallet,
                max_protocol_upfront_fee,
                max_protocol_settlement_fee,
                partial_liquidation_fee,
                full_liquidation_fee,
                refinance_impl_key,
                liquidation_impl_key,
                vault_impl_key,
                transfer_agent,
                vault_registrar_connector_key or ZERO_ADDRESS,
            ],
        )
        self.vault_registrar_connector_key = vault_registrar_connector_key
        if address:
            self.load_contract(address)

    def deploy(self, context: DeploymentContext):
        super().deploy(context)
        if self.vault_registrar_connector_key:
            execute(
                context,
                self.vault_registrar_connector_key,
                "change_authorized_contract",
                self.key,
                True,  # noqa: FBT003
            )


@dataclass
class LiquidationImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingLiquidation,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class LiquidationVaultedImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingVaultedLiquidation,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class RefinanceV0Impl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingV0Refinance,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class RefinanceImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingRefinance,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class RefinanceVaultedImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingVaultedRefinance,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class VaultImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingVault,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class Oracle(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        decimals: int | None = None,
        rate: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.OracleMock,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[decimals, int(rate) if rate else None],
        )
        if address:
            self.load_contract(address)


@dataclass
class Balancer(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.BalancerMock,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class Acred(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        supply: int | None = 0,
        oracle_key: str | None = None,
        stablecoin_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.AcredMock,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_deps={oracle_key, stablecoin_key},
            deployment_args=[int(supply) if supply else 0, oracle_key, stablecoin_key],
        )
        if address:
            self.load_contract(address)


@dataclass
class SecuritizeLoop(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        p2p_contract_key: str,
        balancer_key: str,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.SecuritizeProxy,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_deps={p2p_contract_key, balancer_key},
            deployment_args=[p2p_contract_key, balancer_key],
            config_deps={key: self.set_proxy_auth},
        )
        self.p2p_contract_key = p2p_contract_key
        if address:
            self.load_contract(address)

    def set_proxy_auth(self, context: DeploymentContext):
        execute(context, self.p2p_contract_key, "set_proxy_authorization", self.key, True)  # noqa: FBT003


@dataclass
class KYCValidator(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        validator: str,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.KYCValidator,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[validator],
        )
        if address:
            self.load_contract(address)


@dataclass
class ERC20External(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        address: str | None = None,
        abi_key: str | None = None,
    ):
        super().__init__(key, None, project.WETH9Mock, token=True, abi_key=abi_key)
        if address:
            self.load_contract(address)

    def deployable(self, context: DeploymentContext) -> bool:  # noqa: PLR6301, ARG002
        return False


@dataclass
class P2PLendingSecuritizeErc20(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str,
        payment_token_key: str,
        collateral_token_key: str,
        oracle_key: str,
        oracle_reverse: bool = False,
        kyc_validator_key: str | None = None,
        refinance_impl_key: str | None = None,
        liquidation_impl_key: str | None = None,
        vault_impl_key: str | None = None,
        protocol_upfront_fee: int,
        protocol_settlement_fee: int,
        protocol_wallet: str,
        transfer_agent: str,
        securitize_redemption_wallet: str,
        vault_registrar_connector_key: str,
        max_protocol_upfront_fee: int,
        max_protocol_settlement_fee: int,
        partial_liquidation_fee: int,
        full_liquidation_fee: int,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingSecuritizeErc20,
            version=version,
            abi_key=abi_key,
            deployment_deps={
                payment_token_key,
                collateral_token_key,
                oracle_key,
                kyc_validator_key,
                refinance_impl_key,
                liquidation_impl_key,
                vault_impl_key,
                vault_registrar_connector_key,
            },
            deployment_args=[
                payment_token_key,
                collateral_token_key,
                oracle_key,
                oracle_reverse,
                kyc_validator_key or ZERO_ADDRESS,
                protocol_upfront_fee,
                protocol_settlement_fee,
                protocol_wallet,
                max_protocol_upfront_fee,
                max_protocol_settlement_fee,
                partial_liquidation_fee,
                full_liquidation_fee,
                refinance_impl_key,
                liquidation_impl_key,
                vault_impl_key,
                transfer_agent,
                securitize_redemption_wallet,
                vault_registrar_connector_key,
            ],
        )
        self.vault_registrar_connector_key = vault_registrar_connector_key
        if address:
            self.load_contract(address)

    def deploy(self, context: DeploymentContext):
        super().deploy(context)
        execute(
            context,
            self.vault_registrar_connector_key,
            "change_authorized_contract",
            self.key,
            True,  # noqa: FBT003
        )


@dataclass
class LiquidationSecuritizeImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingSecuritizeLiquidation,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class RefinanceSecuritizeImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingSecuritizeRefinance,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)


@dataclass
class VaultRegistrarMock(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        token_key: str,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.VaultRegistrarMock,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_deps={token_key},
            deployment_args=[token_key],
        )
        if address:
            self.load_contract(address)


@dataclass
class SecuritizeRegistrarV1Connector(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        vault_registrar_key: str,
        address: str | None = None,
    ):
        self._vault_registrar_key = vault_registrar_key
        super().__init__(
            key,
            None,
            project.SecuritizeRegistrarV1Connector,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_deps={vault_registrar_key},
            deployment_args=[vault_registrar_key],
        )
        self.vault_registrar_key = vault_registrar_key
        if address:
            self.load_contract(address)


@dataclass
class VaultSecuritizeImpl(ContractConfig):
    def __init__(
        self,
        *,
        key: str,
        version: str | None = None,
        abi_key: str | None = None,
        address: str | None = None,
    ):
        super().__init__(
            key,
            None,
            project.P2PLendingVaultSecuritize,
            version=version,
            abi_key=abi_key,
            token=False,
            deployment_args=[],
        )
        if address:
            self.load_contract(address)
