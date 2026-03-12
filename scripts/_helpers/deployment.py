import json
import logging
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from typing import Any

from ape import accounts, chain
from rich import print as rprint
from rich.markup import escape

from . import contracts as contracts_module
from .basetypes import (
    ContractConfig,
    DeploymentContext,
    Environment,
)
from .dependency import DependencyManager
from .verification import is_verified, verify_contract

ENV = Environment[os.environ.get("ENV", "local")]
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")


logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)
warnings.filterwarnings("ignore")


class Context(Enum):
    DEPLOYMENT = "deployment"
    CONSOLE = "console"


def _parallel_create(specs: list, max_workers: int = 16) -> list:
    def create_contract(spec):
        key, contract_type, address, abi_key, properties = spec
        return contracts_module.__dict__[contract_type](key=key, address=address, abi_key=abi_key, **properties)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(create_contract, spec) for spec in specs]
        return [future.result() for future in as_completed(futures)]


def load_contracts(env: Environment, chain: str) -> list[ContractConfig]:
    config_file = Path.cwd() / "configs" / env.name / chain / "p2p-erc20.json"
    with config_file.open(encoding="utf8") as f:
        config = json.load(f)

    contract_specs = [
        (f"{scope}.{name}", c["contract"], c.get("address"), c.get("abi_key"), c.get("properties", {}))
        for scope in ["common", "p2p", "proxies"]
        for name, c in config[scope].items()
    ]

    return _parallel_create(contract_specs)


def store_contracts(env: Environment, chain: str, contracts: list[ContractConfig]):
    config_file = Path.cwd() / "configs" / env.name / chain / "p2p-erc20.json"
    with config_file.open(encoding="utf8") as f:
        config = json.load(f)

    contracts_dict = {c.key: c for c in contracts}
    for scope in ["common", "p2p", "proxies"]:
        for name, c in config[scope].items():
            key = f"{scope}.{name}"
            if key in contracts_dict:
                c["address"] = contracts_dict[key].address()
                if contracts_dict[key].abi_key:
                    c["abi_key"] = contracts_dict[key].abi_key
                if contracts_dict[key].version:
                    c["version"] = contracts_dict[key].version
            properties = c.get("properties", {})
            addresses = c.get("properties_addresses", {})
            for prop_key, prop_val in properties.items():
                if prop_key.endswith("_key") and prop_val in contracts_dict:
                    addresses[prop_key[:-4]] = contracts_dict[prop_val].address()
            c["properties_addresses"] = addresses

    with open(config_file, "w") as f:
        f.write(json.dumps(config, indent=4, sort_keys=True))


def load_tokens(env: Environment, chain: str) -> list[ContractConfig]:
    config_file = Path.cwd() / "configs" / env.name / chain / "tokens.json"
    with config_file.open(encoding="utf8") as f:
        config = json.load(f)

    token_specs = [
        (f"common.{name}", c.get("contract_def", "ERC20External"), c.get("address"), c.get("abi_key"), {})
        for name, c in config.items()
    ]
    return _parallel_create(token_specs)


def load_configs(env: Environment, chain: str) -> dict:
    config_file = Path.cwd() / "configs" / env.name / chain / "p2p-erc20.json"
    with config_file.open(encoding="utf8") as f:
        config = json.load(f)

    _configs = config.get("configs", {})
    return {f"configs.{k}": v for k, v in _configs.items()}


def verify_contracts(context: DeploymentContext, contracts: list[ContractConfig]):
    print()
    if context.env not in {Environment.int, Environment.prod}:
        rprint(f"[bright_black]Skipping verification for {context.env.name} environment[/]")
        return
    if not ETHERSCAN_API_KEY:
        keys = " ".join(c.key for c in contracts)
        rprint("[dark_orange bold]WARNING[/]: ETHERSCAN_API_KEY not set, skipping verification")
        rprint("[bright_black]Verify later with:[/]")
        rprint(f"  python scripts/verify.py --env {context.env.name} --chain {chain.provider.network.name} --contracts {keys}")
        return

    rprint(f"\nVerifying [blue]{len(contracts)}[/] contract(s) on Etherscan...")
    results = {}
    for contract in contracts:
        if context.dryrun:
            rprint(f"  [bright_black]Skipping [blue]{escape(contract.key)}[/blue]: dry run mode[/]")
            continue

        if contract.contract is None:
            rprint(f"  [bright_black]Skipping [blue]{escape(contract.key)}[/blue]: no contract instance[/]")
            continue
        if is_verified(ETHERSCAN_API_KEY, chain.provider.network.chain_id, contract.address()):
            rprint(f"  [bright_black]Skipping [blue]{escape(contract.key)}[/blue]: already verified[/]")
            results[contract.key] = True
            continue
        rprint(f"\n  Verifying [blue]{escape(contract.key)}[/] at [blue]{escape(contract.address())}[/]...")
        try:
            success = verify_contract(
                api_key=ETHERSCAN_API_KEY,
                chain_id=chain.provider.network.chain_id,
                address=contract.address(),
                source_file=contract.container.source_id,
                constructor_args=(contract.deploy_args.hex() if contract.deploy_args else "").removeprefix("0x"),
            )
            results[contract.key] = success
        except Exception as e:
            rprint(f"  [bold red]Error[/]: {escape(str(e))}")
            results[contract.key] = False

    if results:
        rprint("\n  Verification summary:")
        for key, success in results.items():
            status = "[bold green]OK[/]" if success else "[bold red]FAIL[/]"
            rprint(f"    {status} [blue]{escape(key)}[/]")
        succeeded = sum(1 for v in results.values() if v)
        rprint(f"  [bold]{succeeded}/{len(results)}[/] verified successfully")


class DeploymentManager:
    def __init__(self, env: Environment, chain: str, context: Context = Context.DEPLOYMENT):
        self.env = env
        self.chain = chain
        match env:
            case Environment.local:
                self.owner = accounts.test_accounts[0]
            case Environment.dev:
                self.owner = accounts.load("devacc")
            case Environment.int:
                self.owner = accounts.load("intacc")
            case Environment.prod:
                self.owner = accounts.load("prodacc")
        self.context = DeploymentContext(self._get_contracts(context), self.env, self.chain, self.owner, self._get_configs())

    def _get_contracts(self, context: Context) -> dict[str, ContractConfig]:
        contracts = load_contracts(self.env, self.chain)
        tokens = load_tokens(self.env, self.chain)
        all_contracts = contracts + tokens

        # always deploy everything in local
        if self.env == Environment.local and context == Context.DEPLOYMENT:
            for contract in all_contracts:
                contract.contract = None

        return {c.key: c for c in all_contracts}

    def _get_configs(self) -> dict[str, Any]:
        return load_configs(self.env, self.chain)

    def _save_state(self):
        store_contracts(self.env, self.chain, list(self.context.contracts.values()))

    def deploy(self, changes: set[str], *, dryrun=False, save_state=True):
        self.owner.set_autosign(True) if self.env != Environment.local else None
        self.context.dryrun = dryrun
        dependency_manager = DependencyManager(self.context, changes)
        contracts_to_deploy = dependency_manager.build_contract_deploy_set()
        dependencies_tx = dependency_manager.build_transaction_set()

        for contract in contracts_to_deploy:
            if contract.deployable(self.context):
                contract.deploy(self.context)

        if save_state and not dryrun:
            self._save_state()

        for dependency_tx in dependencies_tx:
            dependency_tx(self.context)

        if save_state and not dryrun:
            self._save_state()

        verify_contracts(self.context, [c for c in contracts_to_deploy if c.deployable(self.context)])

    def deploy_all(self, *, dryrun=False, save_state=True):
        self.deploy(self.context.contract.keys(), dryrun=dryrun, save_state=save_state)
