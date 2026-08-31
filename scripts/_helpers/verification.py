"""
Vyper contract verification on block explorers.

Reusable module for verifying Vyper contracts on Etherscan (V2 API) and
Blockscout-based explorers (API v2). Can be called from the CLI script
(scripts/verify.py) or directly from deployment scripts.

The EXPLORERS registry maps each chain to the explorer API functions to call
and the explorer URL, chain id and api key env var to use, giving a uniform
chain-keyed API regardless of the explorer flavor:

    from scripts._helpers.verification import verification_status, verify_deployed_contract

    verified, twin = verification_status("base-sepolia", "0x...")
    if not verified:
        result = verify_deployed_contract(
            chain="base-sepolia",
            address="0x...",
            source_file="contracts/v1/P2PLendingVaultedErc20.vy",
        )

The explorer-specific functions (verify_contract for Etherscan,
blockscout_verify_contract for Blockscout) remain available for direct use.
"""

import json
import os
import time
from pathlib import Path

import requests
import vyper
from rich import print
from rich.markup import escape
from vyper.cli.vyper_compile import get_search_paths
from vyper.cli.vyper_json import compile_json
from vyper.compiler import compile_from_file_input
from vyper.compiler.input_bundle import FilesystemInputBundle

ETHERSCAN_API_URL = "https://api.etherscan.io/v2/api"


def _etherscan_get(api_key: str, chain_id: int, **params) -> dict:
    resp = requests.get(
        ETHERSCAN_API_URL,
        params={"chainid": chain_id, "apikey": api_key, **params},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def is_verified(api_key: str, chain_id: int, address: str) -> bool:
    """Check if a contract is already verified on Etherscan."""
    data = _etherscan_get(api_key, chain_id, module="contract", action="getsourcecode", address=address)
    if data.get("status") != "1" or not data.get("result"):
        return False
    return data["result"][0].get("ABI", "") != "Contract source code not verified"


def get_verified_constructor_args(api_key: str, chain_id: int, address: str) -> str | None:
    """Get constructor args from Etherscan for an already-verified contract."""
    data = _etherscan_get(api_key, chain_id, module="contract", action="getsourcecode", address=address)
    if data.get("status") != "1" or not data.get("result"):
        return None
    args = data["result"][0].get("ConstructorArguments", "")
    return args or None


def get_creation_tx_input(api_key: str, chain_id: int, address: str) -> tuple[str, str]:
    """Get creation tx hash and input data. Returns (tx_hash, tx_input_hex_no_0x)."""
    data = _etherscan_get(api_key, chain_id, module="contract", action="getcontractcreation", contractaddresses=address)
    if data.get("status") != "1" or not data.get("result"):
        raise RuntimeError(f"Failed to get creation tx for {address}: {data.get('message', data)}")
    tx_hash = data["result"][0]["txHash"]

    data = _etherscan_get(api_key, chain_id, module="proxy", action="eth_getTransactionByHash", txhash=tx_hash)
    tx_input = data.get("result", {}).get("input", "")
    if not tx_input:
        raise RuntimeError(f"Failed to get tx input for {tx_hash}")
    return tx_hash, tx_input.removeprefix("0x")


def get_deployed_code(api_key: str, chain_id: int, address: str) -> str:
    """Get deployed runtime bytecode via eth_getCode. Returns hex without 0x prefix."""
    data = _etherscan_get(api_key, chain_id, module="proxy", action="eth_getCode", address=address, tag="latest")
    code = data.get("result", "")
    if not code or code == "0x":
        raise RuntimeError(f"No code at {address}")
    return code.removeprefix("0x")


def generate_solc_json(source_file: str) -> dict:
    """Generate the Vyper standard JSON input for a source file."""
    search_paths = get_search_paths(None, include_sys_path=True)
    input_bundle = FilesystemInputBundle(search_paths)
    file_input = input_bundle.load_file(Path(source_file))
    result = compile_from_file_input(file_input, input_bundle=input_bundle, output_formats=["solc_json"])
    return result["solc_json"]


def compile_initcode(solc_json: dict) -> str:
    """Compile via vyper standard-json and return the initcode bytecode hex (no 0x prefix)."""
    solc_json_for_compile = dict(solc_json)
    solc_json_for_compile["settings"] = dict(solc_json["settings"])
    source_file = next(iter(solc_json["settings"]["outputSelection"]))
    solc_json_for_compile["settings"]["outputSelection"] = {source_file: ["evm.bytecode"]}

    output = compile_json(solc_json_for_compile)

    contracts = output.get("contracts", {})
    for path_contracts in contracts.values():
        for contract_data in path_contracts.values():
            bytecode = contract_data.get("evm", {}).get("bytecode", {}).get("object", "")
            if bytecode:
                return bytecode.removeprefix("0x")

    raise RuntimeError("No bytecode found in compilation output")


def extract_constructor_args(
    api_key: str,
    chain_id: int,
    address: str,
    solc_json: dict,
) -> str | None:
    """Extract constructor arguments using a fallback chain:

    1. Compare compiled initcode content against creation tx input (exact match)
    2. Use compiled initcode length to split creation tx input (tolerates metadata diffs)

    Returns None when the args can't be reliably extracted, likely because the
    deployed contract was compiled from a different version of the sources.
    """
    try:
        initcode = compile_initcode(solc_json)
        tx_hash, tx_input = get_creation_tx_input(api_key, chain_id, address)
        print(f"    creation tx: [bright_black]{escape(tx_hash)}[/]")

        # Strategy 1: exact initcode content match
        if tx_input.lower().startswith(initcode.lower()):
            print("    [bright_black]extracted via initcode match[/]")
            return tx_input[len(initcode) :]

        # Strategy 2: use compiled initcode length as split point
        # The initcode length is deterministic for the same contract structure,
        # even when metadata/integrity hashes differ between compilations.
        # Validate using eth_getCode: if the on-chain contract has code, the
        # deployment succeeded and the split should be correct.
        get_deployed_code(api_key, chain_id, address)
    except Exception as e:
        print(f"  [bold red]FAILED[/]: Could not extract constructor args: {escape(str(e))}")
        return None

    args_hex_len = len(tx_input) - len(initcode)
    if args_hex_len < 0 or args_hex_len % 64 != 0:
        print("  [bold red]FAILED[/]: Could not extract constructor args, likely contract versions differ")
        print(
            f"    [bright_black]creation tx input: {len(tx_input) // 2} bytes, "
            f"compiled initcode: {len(initcode) // 2} bytes[/]"
        )
        return None

    print(f"    [bright_black]extracted via initcode length ({args_hex_len // 2} bytes)[/]")
    return tx_input[len(initcode) :]


def submit_verification(  # noqa: PLR0917
    api_key: str,
    chain_id: int,
    address: str,
    source_file: str,
    solc_json: dict,
    constructor_args: str = "",
) -> str:
    """Submit verification request to Etherscan. Returns the GUID.

    All parameters are sent as query params per the V2 API spec, except sourceCode
    which is sent in the POST body to avoid URL length limits.
    """
    contract_name = os.path.basename(source_file).replace(".vy", "")  # noqa: PTH119
    contract_name_full = f"{source_file}:{contract_name}"

    query_params = {
        "chainid": chain_id,
        "apikey": api_key,
        "module": "contract",
        "action": "verifysourcecode",
        "codeformat": "vyper-json",
        "contractaddress": address,
        "contractname": contract_name_full,
        "compilerversion": "vyper:0.4.3",
        "optimizationUsed": "0",
    }
    if constructor_args:
        query_params["constructorArguments"] = constructor_args

    resp = requests.post(
        ETHERSCAN_API_URL,
        params=query_params,
        data={"sourceCode": json.dumps(solc_json)},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "1":
        raise RuntimeError(f"Verification submission failed: {data.get('result', data.get('message', data))}")

    return data["result"]


def check_verification_status(api_key: str, chain_id: int, guid: str) -> dict:
    """Check verification status for a GUID. Returns the raw API response."""
    resp = requests.get(
        ETHERSCAN_API_URL,
        params={
            "chainid": chain_id,
            "module": "contract",
            "action": "checkverifystatus",
            "guid": guid,
            "apikey": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def poll_verification(api_key: str, chain_id: int, guid: str, max_attempts: int = 10) -> bool:
    """Poll verification status until complete or failed."""
    for attempt in range(max_attempts):
        time.sleep(3)
        data = check_verification_status(api_key, chain_id, guid)
        result = data.get("result", "")
        status = data.get("status", "")

        if status == "1":
            print(f"  [bold green]VERIFIED[/]: {escape(result)}")
            return True

        if "pending" in result.lower():
            print(f"  [bright_black]attempt {attempt + 1}/{max_attempts}: {escape(result)}[/]")
            continue

        print(f"  [bold red]FAILED[/]: {escape(result)}")
        return False

    print(f"  [dark_orange bold]TIMEOUT[/]: max attempts ({max_attempts}) reached")
    return False


def save_solc_json(source_file: str, solc_json: dict) -> str:
    """Save solc_json to disk for manual verification. Returns the file path."""
    contract_name = os.path.basename(source_file).replace(".vy", "")  # noqa: PTH119
    out_dir = Path("solc_json") / os.path.dirname(source_file).replace("contracts/", "")  # noqa: PTH120
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{contract_name}.json"
    with open(out_path, "w") as f:
        json.dump(solc_json, f, separators=(", ", ": "))
        f.write("\n")
    return str(out_path)


def verify_contract(
    api_key: str,
    chain_id: int,
    address: str,
    source_file: str,
    constructor_args: str | None = None,
) -> bool:
    """Verify a single contract on Etherscan. Returns True on success.

    Args:
        api_key: Etherscan API key.
        chain_id: Chain ID (e.g. 1 for mainnet, 11155111 for sepolia).
        address: Deployed contract address.
        source_file: Path to the main .vy source file.
        constructor_args: ABI-encoded constructor args as hex string (no 0x prefix).
            None (default) auto-extracts them from the creation tx; pass "" for no args.
    """
    print(f"  Compiling [blue]{escape(source_file)}[/]...")
    solc_json = generate_solc_json(source_file)

    if constructor_args is None:
        constructor_args = extract_constructor_args(api_key, chain_id, address, solc_json)
        if constructor_args is None:
            return False

    print(f"  Submitting verification for [blue]{escape(address)}[/]...")
    guid = submit_verification(api_key, chain_id, address, source_file, solc_json, constructor_args)
    print(f"  GUID: [bright_black]{escape(guid)}[/]")

    print("  Polling verification status...")
    success = poll_verification(api_key, chain_id, guid)

    if not success:
        solc_path = save_solc_json(source_file, solc_json)
        print("  [bright_black]Verify manually at Etherscan web interface with:[/]")
        print(f"    solc_json: [blue]{escape(solc_path)}[/]")
        print(f"    constructor args: [bright_black]{escape(constructor_args)}[/]")

    return success


# Blockscout (API v2)


def _blockscout_api(explorer_url: str) -> str:
    return f"{explorer_url.rstrip('/')}/api/v2"


def blockscout_verification_status(explorer_url: str, address: str) -> tuple[bool, str | None]:
    """Return (is_verified, verified_twin_address) for a contract on a Blockscout explorer.

    Checks is_verified strictly: bytecode twins of a verified contract return
    the twin's source_code but is_verified=false and the twin's address.
    """
    resp = requests.get(f"{_blockscout_api(explorer_url)}/smart-contracts/{address}", timeout=30)
    if not resp.ok:
        return False, None
    data = resp.json()
    return data.get("is_verified") or False, data.get("verified_twin_address_hash")


def blockscout_is_verified(explorer_url: str, address: str) -> bool:
    """Check if a contract is already verified on a Blockscout explorer."""
    verified, _ = blockscout_verification_status(explorer_url, address)
    return verified


def blockscout_compiler_version(explorer_url: str) -> str:
    """Resolve the explorer's compiler version id matching the local vyper version."""
    resp = requests.get(f"{_blockscout_api(explorer_url)}/smart-contracts/verification/config", timeout=30)
    resp.raise_for_status()
    versions = resp.json().get("vyper_compiler_versions", [])
    prefix = f"v{vyper.__version__}+"
    return next((v for v in versions if v.startswith(prefix)), f"v{vyper.__version__}")


def blockscout_submit_verification(
    explorer_url: str,
    address: str,
    source_file: str,
    solc_json: dict,
    compiler_version: str,
) -> str:
    """Submit a vyper standard-json verification request to Blockscout. Returns the response message.

    Constructor args are auto-extracted by Blockscout from the creation tx.
    """
    contract_name = Path(source_file).stem
    resp = requests.post(
        f"{_blockscout_api(explorer_url)}/smart-contracts/{address}/verification/via/vyper-standard-input",
        data={"compiler_version": compiler_version, "license_type": "none"},
        files={"files[0]": (f"{contract_name}.json", json.dumps(solc_json), "application/json")},
        timeout=60,
    )
    resp.raise_for_status()
    message = resp.json().get("message", "")
    if "started" not in message.lower():
        raise RuntimeError(f"Verification submission failed for {address}: {message or resp.text}")
    return message


def blockscout_poll_verification(explorer_url: str, address: str, max_attempts: int = 10) -> bool:
    """Poll a Blockscout explorer until the contract shows as verified.

    Blockscout processes verifications asynchronously and exposes no failure
    status: a rejected verification just never shows as verified.
    """
    for attempt in range(max_attempts):
        time.sleep(3)
        if blockscout_is_verified(explorer_url, address):
            print("  [bold green]VERIFIED[/]")
            return True
        print(f"  [bright_black]attempt {attempt + 1}/{max_attempts}: pending[/]")

    print(f"  [dark_orange bold]TIMEOUT[/]: max attempts ({max_attempts}) reached, verification pending or rejected")
    return False


def blockscout_verify_contract(explorer_url: str, address: str, source_file: str) -> bool:
    """Verify a single contract on a Blockscout explorer. Returns True on success.

    Args:
        explorer_url: Base URL of the Blockscout explorer.
        address: Deployed contract address.
        source_file: Path to the main .vy source file.
    """
    print(f"  Compiling [blue]{escape(source_file)}[/]...")
    solc_json = generate_solc_json(source_file)
    compiler_version = blockscout_compiler_version(explorer_url)

    print(f"  Submitting verification for [blue]{escape(address)}[/] with compiler {escape(compiler_version)}...")
    message = blockscout_submit_verification(explorer_url, address, source_file, solc_json, compiler_version)
    print(f"  [bright_black]{escape(message)}[/]")

    print("  Polling verification status...")
    success = blockscout_poll_verification(explorer_url, address)

    if not success:
        solc_path = save_solc_json(source_file, solc_json)
        print("  [bright_black]Verify manually at the explorer web interface with:[/]")
        print(f"    url: [blue]{escape(explorer_url)}/address/{escape(address)}/contract-verification[/]")
        print(f"    solc_json: [blue]{escape(solc_path)}[/]")

    return success


# Uniform chain-keyed API


def _blockscout_status(explorer: dict, address: str) -> tuple[bool, str | None]:
    return blockscout_verification_status(explorer["url"], address)


def _blockscout_verify(explorer: dict, address: str, source_file: str, _constructor_args: str | None = None) -> bool:
    # blockscout extracts the constructor args from the creation tx, no need to pass them
    return blockscout_verify_contract(explorer["url"], address, source_file)


def _etherscan_status(explorer: dict, address: str) -> tuple[bool, str | None]:
    return is_verified(os.environ[explorer["api_key"]], explorer["chain_id"], address), None


def _etherscan_verify(explorer: dict, address: str, source_file: str, constructor_args: str | None = None) -> bool:
    return verify_contract(os.environ[explorer["api_key"]], explorer["chain_id"], address, source_file, constructor_args)


# chain -> explorer API functions, URL, chain id and api key env var name; the status and
# verify functions take the explorer entry as first argument. The etherscan-family
# explorers all use the Etherscan V2 multichain API with a single etherscan.io api key.
EXPLORERS = {
    "robinhood-testnet": {
        "url": "https://explorer.testnet.chain.robinhood.com",
        "chain_id": 46630,
        "status": _blockscout_status,
        "verify": _blockscout_verify,
    },
    "robinhood": {
        "url": "https://robinhoodchain.blockscout.com",
        "chain_id": 4663,
        "status": _blockscout_status,
        "verify": _blockscout_verify,
    },
    "ethereum": {
        "url": "https://etherscan.io",
        "chain_id": 1,
        "api_key": "ETHERSCAN_API_KEY",
        "status": _etherscan_status,
        "verify": _etherscan_verify,
    },
    "sepolia": {
        "url": "https://sepolia.etherscan.io",
        "chain_id": 11155111,
        "api_key": "ETHERSCAN_API_KEY",
        "status": _etherscan_status,
        "verify": _etherscan_verify,
    },
    "base": {
        "url": "https://basescan.org",
        "chain_id": 8453,
        "api_key": "ETHERSCAN_API_KEY",
        "status": _etherscan_status,
        "verify": _etherscan_verify,
    },
    "base-sepolia": {
        "url": "https://sepolia.basescan.org",
        "chain_id": 84532,
        "api_key": "ETHERSCAN_API_KEY",
        "status": _etherscan_status,
        "verify": _etherscan_verify,
    },
    "apechain": {
        "url": "https://apescan.io",
        "chain_id": 33139,
        "api_key": "ETHERSCAN_API_KEY",
        "status": _etherscan_status,
        "verify": _etherscan_verify,
    },
    "curtis": {
        "url": "https://curtis.apescan.io",
        "chain_id": 33111,
        "api_key": "ETHERSCAN_API_KEY",
        "status": _etherscan_status,
        "verify": _etherscan_verify,
    },
}


def get_explorer(chain: str) -> dict:
    """Return the explorer config for a chain, validating its requirements.

    Raises ValueError for chains without a configured explorer or missing api key env var.
    """
    explorer = EXPLORERS.get(chain)
    if explorer is None:
        raise ValueError(f"No block explorer configured for chain {chain} in {__name__}.EXPLORERS")
    if "api_key" in explorer and not os.environ.get(explorer["api_key"]):
        raise ValueError(f"{explorer['api_key']} env var not set, required for the {chain} explorer")
    return explorer


def verification_status(chain: str, address: str) -> tuple[bool, str | None]:
    """Return (is_verified, verified_twin_address) for a contract on the chain's explorer."""
    explorer = get_explorer(chain)
    return explorer["status"](explorer, address)


def verify_deployed_contract(chain: str, address: str, source_file: str, constructor_args: str | None = None) -> bool:
    """Verify a single contract on the chain's explorer. Returns True on success.

    Args:
        chain: Chain name, as configured in EXPLORERS.
        address: Deployed contract address.
        source_file: Path to the main .vy source file.
        constructor_args: ABI-encoded constructor args as hex string (no 0x prefix),
            as known at deployment time. None (default) extracts them from the
            creation tx, either locally (Etherscan) or explorer-side (Blockscout).
    """
    explorer = get_explorer(chain)
    return explorer["verify"](explorer, address, source_file, constructor_args)
