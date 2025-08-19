import json
from dataclasses import dataclass
from hashlib import sha3_256

from ape import project
from ape.contracts.base import ContractContainer
from ethpm_types.contract_type import ContractType
from hexbytes import HexBytes
from rich import print
from rich.markup import escape

from .basetypes import ContractConfig, DeploymentContext, abi_key
from .transactions import check_owner, execute, execute_read

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
            deployment_deps={payment_token_key, collateral_token_key, oracle_key, kyc_validator_key},
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
            ],
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
            token=True,
            deployment_args=[decimals, int(rate) if rate else None],
        )
        if address:
            self.load_contract(address)


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
            token=True,
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
