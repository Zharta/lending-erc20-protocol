"""
Verify deployed contracts on the chain's block explorer.

Reads the deployment config for ENV/CHAIN, checks each deployed contract
against the explorer API and submits a vyper standard-json verification for
the ones not verified yet.

Usage: make verify-<chain>  (e.g. make verify-robinhood-testnet)

Explorer selection is driven by the EXPLORERS registry in
scripts._helpers.verification: each chain maps to the explorer API functions
to call and the explorer URL to use.
"""

import json
import logging
import os
import warnings
from pathlib import Path

import click
from rich import print
from rich.markup import escape

from ._helpers import contracts as contracts_module
from ._helpers.basetypes import Environment
from ._helpers.verification import get_explorer, verification_status, verify_deployed_contract

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)
warnings.filterwarnings("ignore")

ENV = Environment[os.environ.get("ENV", "local")]
CHAIN = os.environ.get("CHAIN", "nochain")


def load_deployed_contracts(env: Environment, chain: str) -> list[tuple[str, str, str]]:
    """Return (key, address, source_file) for every config contract deployed from local sources."""
    config_file = Path.cwd() / "configs" / env.name / chain / "p2p-erc20.json"
    with config_file.open(encoding="utf8") as f:
        config = json.load(f)

    deployed = []
    seen = set()
    for scope in ("common", "p2p"):
        for name, c in config[scope].items():
            address = c.get("address")
            if not address or address.lower() in seen:
                continue
            # instantiate without address to resolve the source file without a network connection
            contract = contracts_module.__dict__[c["contract"]](
                key=f"{scope}.{name}", address=None, abi_key=c.get("abi_key"), **c.get("properties", {})
            )
            if contract.container is None:
                continue
            seen.add(address.lower())
            deployed.append((f"{scope}.{name}", address, contract.container.contract_type.source_id))
    return deployed


def verify_one(chain: str, key: str, address: str, source_file: str) -> tuple[bool, str | None]:
    """Verify a single deployed contract, containing any errors. Returns (success, twin)."""
    twin = None
    try:
        verified, twin = verification_status(chain, address)
        if verified:
            print(f"[bold]{escape(key)}[/] [bright_black]{escape(address)}[/] [green]already verified[/]")
            return True, twin
        print(f"\n[bold]{escape(key)}[/] [bright_black]{escape(address)}[/]")
        return verify_deployed_contract(chain, address, source_file), twin
    except Exception as e:  # deployed contracts may not match current sources, keep going
        print(f"  [bold red]ERROR[/]: {escape(str(e))}")
        return False, twin


@click.command()
def cli():
    try:
        explorer = get_explorer(CHAIN)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    contracts = load_deployed_contracts(ENV, CHAIN)
    print(f"Checking {len(contracts)} contracts in [blue]{ENV.name}[/]/[blue]{CHAIN}[/] against {explorer['url']}")

    failed = []
    failed_with_twin = []
    for key, address, source_file in contracts:
        success, twin = verify_one(CHAIN, key, address, source_file)
        if not success:
            if twin:
                failed_with_twin.append(f"{key} (twin {twin})")
            else:
                failed.append(key)

    if failed_with_twin:
        print(
            f"\n[dark_orange bold]FAILED with verified twin[/]: {len(failed_with_twin)} contracts not verified "
            f"but matching a verified twin bytecode: {', '.join(failed_with_twin)}"
        )
    if failed:
        print(f"\n[bold red]FAILED[/]: {len(failed)} contracts not verified: {', '.join(failed)}")
    if failed or failed_with_twin:
        raise SystemExit(1)
    print("\n[bold green]All contracts verified[/]")
