"""
Etherscan Vyper contract verification CLI.

Reads contract addresses from deployment configs and submits verification
requests via the Etherscan V2 API using vyper-json format.

Usage:
    python scripts/verify.py --env prod --chain ethereum
    python scripts/verify.py --env int --chain sepolia --contracts common.kyc p2p.usdc_acred_vaulted
    python scripts/verify.py --env int --chain sepolia --check GUID
"""

import argparse
import json
import os
import sys

from _helpers.verification import (
    check_verification_status,
    extract_constructor_args,
    generate_solc_json,
    is_verified,
    verify_contract,
)

CHAIN_IDS = {
    ("prod", "ethereum"): 1,
    ("int", "sepolia"): 11155111,
    ("int", "citrea"): 5115,
}

CONTRACT_SOURCE_MAP = {
    "P2PLendingVaultedErc20": "contracts/v1/P2PLendingVaultedErc20.vy",
    "P2PLendingSecuritizeErc20": "contracts/v1/P2PLendingSecuritizeErc20.vy",
    "P2PLendingErc20": "contracts/v1/P2PLendingErc20.vy",
    "P2PLendingSecuritize": "contracts/v1/P2PLendingSecuritize.vy",
    "P2PLendingV0Erc20": "contracts/v0/P2PLendingV0Erc20.vy",
    "P2PLendingV0Securitize": "contracts/v0/P2PLendingV0Securitize.vy",
    "LiquidationImpl": "contracts/v1/P2PLendingLiquidation.vy",
    "LiquidationVaultedImpl": "contracts/v1/P2PLendingVaultedLiquidation.vy",
    "LiquidationSecuritizeImpl": "contracts/v1/P2PLendingSecuritizeLiquidation.vy",
    "RefinanceImpl": "contracts/v1/P2PLendingRefinance.vy",
    "RefinanceVaultedImpl": "contracts/v1/P2PLendingVaultedRefinance.vy",
    "RefinanceSecuritizeImpl": "contracts/v1/P2PLendingSecuritizeRefinance.vy",
    "VaultImpl": "contracts/v1/P2PLendingVault.vy",
    "VaultSecuritizeImpl": "contracts/v1/P2PLendingVaultSecuritize.vy",
    "KYCValidator": "contracts/KYCValidator.vy",
    "Oracle": "contracts/auxiliary/OracleMock.vy",
    "Balancer": "contracts/auxiliary/BalancerMock.vy",
    "Acred": "contracts/auxiliary/AcredMock.vy",
    "VaultRegistrarMock": "contracts/auxiliary/VaultRegistrarMock.vy",
    "SecuritizeLoop": "contracts/SecuritizeProxy.vy",
    "SecuritizeRegistrarV1Connector": "contracts/SecuritizeRegistrarV1Connector.vy",
}

# Contracts with no constructor args (facets / implementations)
NO_CONSTRUCTOR_ARGS = {
    "LiquidationImpl",
    "LiquidationVaultedImpl",
    "LiquidationSecuritizeImpl",
    "RefinanceImpl",
    "RefinanceVaultedImpl",
    "RefinanceSecuritizeImpl",
    "VaultImpl",
    "VaultSecuritizeImpl",
    "Balancer",
}


def load_config(env: str, chain: str) -> dict:
    config_path = f"configs/{env}/{chain}/p2p-erc20.json"
    with open(config_path) as f:
        return json.load(f)


def get_contracts_to_verify(config: dict, filter_keys: list[str] | None) -> list[dict]:
    """Extract contracts from config, optionally filtered by dotted keys like 'common.kyc'."""
    contracts = []
    for section in ("common", "p2p", "proxies"):
        section_data = config.get(section, {})
        for name, entry in section_data.items():
            key = f"{section}.{name}"
            address = entry.get("address", "")
            contract_type = entry.get("contract", "")

            if filter_keys and key not in filter_keys:
                continue
            if not address or address == "0x" + "00" * 20:
                print(f"  SKIP {key}: no address")
                continue
            if contract_type not in CONTRACT_SOURCE_MAP:
                print(f"  SKIP {key}: unknown contract type '{contract_type}'")
                continue

            contracts.append(
                {
                    "key": key,
                    "address": address,
                    "contract_type": contract_type,
                    "source_file": CONTRACT_SOURCE_MAP[contract_type],
                }
            )
    return contracts


def verify_from_config(api_key: str, chain_id: int, contract: dict) -> bool:
    """Verify a contract discovered from config, extracting constructor args if needed."""
    key = contract["key"]
    address = contract["address"]
    contract_type = contract["contract_type"]
    source_file = contract["source_file"]

    print(f"\n{'=' * 60}")
    print(f"  {key}")
    print(f"  type: {contract_type}")
    print(f"  address: {address}")
    print(f"  source: {source_file}")

    try:
        # Check if already verified
        if is_verified(api_key, chain_id, address):
            print("  already verified, skipping")
            return True

        # Get constructor args
        constructor_args = ""
        if contract_type not in NO_CONSTRUCTOR_ARGS:
            print("  extracting constructor args...")
            solc_json = generate_solc_json(source_file)
            constructor_args = extract_constructor_args(api_key, chain_id, address, solc_json)
            if constructor_args:
                print(f"    constructor args: {constructor_args[:64]}{'...' if len(constructor_args) > 64 else ''}")
            else:
                print("    no constructor args found")

        return verify_contract(api_key, chain_id, address, source_file, constructor_args)

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Verify Vyper contracts on Etherscan")
    parser.add_argument("--env", required=True, help="Environment (e.g., prod, int)")
    parser.add_argument("--chain", required=True, help="Chain (e.g., ethereum, sepolia)")
    parser.add_argument("--contracts", nargs="*", help="Contract keys to verify (e.g., common.kyc p2p.usdc_acred_vaulted)")
    parser.add_argument("--check", help="Check verification status for a GUID")
    args = parser.parse_args()

    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        print("ERROR: ETHERSCAN_API_KEY environment variable not set")
        sys.exit(1)

    chain_id = CHAIN_IDS.get((args.env, args.chain))
    if chain_id is None:
        print(f"ERROR: unknown env/chain combination: {args.env}/{args.chain}")
        print(f"  available: {', '.join(f'{e}/{c}' for e, c in CHAIN_IDS)}")
        sys.exit(1)

    # Check-only mode
    if args.check:
        print(f"Checking verification status for GUID: {args.check}")
        data = check_verification_status(api_key, chain_id, args.check)
        print(f"  status: {data.get('status')}")
        print(f"  result: {data.get('result')}")
        sys.exit(0)

    # Load config and get contracts
    config = load_config(args.env, args.chain)
    contracts = get_contracts_to_verify(config, args.contracts)

    if not contracts:
        print("No contracts to verify")
        sys.exit(0)

    print(f"Verifying {len(contracts)} contract(s) on {args.env}/{args.chain} (chain_id={chain_id})")

    # Verify each contract
    results = {}
    for contract in contracts:
        success = verify_from_config(api_key, chain_id, contract)
        results[contract["key"]] = success

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for key, success in results.items():
        status = "OK" if success else "FAIL"
        print(f"  [{status}] {key}")

    total = len(results)
    succeeded = sum(1 for v in results.values() if v)
    print(f"\n  {succeeded}/{total} verified successfully")

    sys.exit(0 if succeeded == total else 1)


if __name__ == "__main__":
    main()
