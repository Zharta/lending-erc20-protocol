"""
Script to calculate bytecode sizes for all Vyper contracts.
Displays sizes versus the EIP-170 contract size limit (24,576 bytes).
"""

import operator

from ape import project
from rich.console import Console
from rich.table import Table

# EIP-170 contract size limit (in bytes)
EIP170_LIMIT = 24576


def get_contract_bytecode_sizes() -> dict[str, int]:
    sizes = {}

    # Get all contract types from the project
    for contract_name in project.contracts:
        contract_type = project.contracts[contract_name]
        if contract_type.deployment_bytecode and contract_type.deployment_bytecode.bytecode:
            # Bytecode is hex string, each byte is 2 hex chars
            bytecode = contract_type.deployment_bytecode.bytecode
            # Remove '0x' prefix if present
            bytecode = bytecode.removeprefix("0x")
            size = len(bytecode) // 2
            sizes[contract_name] = size

    return sizes


def display_sizes(sizes: dict[str, int]) -> None:
    """Display contract sizes with rich formatting."""
    console = Console()

    # Sort by size descending
    sorted_sizes = sorted(sizes.items(), key=operator.itemgetter(1), reverse=True)

    # Create table with compact layout
    table = Table(
        title="Vyper Contract Bytecode Sizes (EIP-170 limit: 24,576 bytes)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Contract", style="cyan")
    table.add_column("Size (bytes)", justify="right")
    table.add_column("Usage", justify="left")

    for name, size in sorted_sizes:
        percentage = (size / EIP170_LIMIT) * 100

        # Determine color based on usage
        if percentage >= 100:
            color = "red"
        elif percentage >= 90:
            color = "yellow"
        elif percentage >= 75:
            color = "orange3"
        else:
            color = "green"

        # Create progress bar with percentage
        bar_width = 20
        filled = int((percentage / 100) * bar_width)
        filled = min(filled, bar_width)
        bar = f"[{color}]{'█' * filled}{'░' * (bar_width - filled)} {percentage:5.1f}%[/{color}]"

        table.add_row(name, f"{size:,}", bar)

    console.print()
    console.print(table)
    console.print()

    # Summary
    total_contracts = len(sizes)
    exceeding = sum(1 for s in sizes.values() if s > EIP170_LIMIT)
    warning = sum(1 for s in sizes.values() if EIP170_LIMIT * 0.9 <= s <= EIP170_LIMIT)

    console.print("[bold]Summary:[/bold]")
    console.print(f"  Total contracts: {total_contracts}")
    console.print(f"  EIP-170 limit: {EIP170_LIMIT:,} bytes")
    if exceeding > 0:
        console.print(f"  [red bold]Contracts exceeding limit: {exceeding}[/red bold]")
    if warning > 0:
        console.print(f"  [yellow]Contracts near limit (>90%): {warning}[/yellow]")
    console.print()


def main():
    """Main entry point."""
    console = Console()

    console.print("[bold blue]Calculating contract bytecode sizes...[/bold blue]")
    console.print()

    sizes = get_contract_bytecode_sizes()

    if not sizes:
        console.print("[red]No compiled contracts found. Run 'ape compile' first.[/red]")
        return

    display_sizes(sizes)


if __name__ == "__main__":
    main()
