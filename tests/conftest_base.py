"""Shared helpers for integration (mainnet-fork) test suites.

Two things live here so they can never drift between suites:

- ``ETH_FORK_BLOCK``: the ONE Ethereum-mainnet fork block every integration suite
  that forks ``BOA_FORK_RPC_URL`` pins. Keeping a single block avoids per-suite
  divergence (and lets us pick a block new enough for every real contract the
  suites touch, e.g. the deJAAA CentrifugeOracleAdapter).

- ``build_erc20_contract_def_with_log_stuff``: GENERATES the ``log_stuff`` dummy
  function boa needs to decode facet-emitted events, from compiler data. Vyper's
  boa fails to register an event that is declared in the main contract but only
  ``log``-emitted from a delegatecall facet, so we append a function that logs
  every such event once. Generating it from ``used_events`` / ``event_defs``
  means it can never go stale when a field is added to an event (a hand-written
  list silently broke the whole dir when ``LeveragedLoanCreated.mint_deadline``
  was added).
"""

from pathlib import Path
from textwrap import dedent

import boa

# The single Ethereum-mainnet fork block for ALL suites forking BOA_FORK_RPC_URL.
# Chosen >= the deJAAA CentrifugeOracleAdapter deploy (~25022228) so the despxa /
# Centrifuge fork flows work without a divergent block; validated on the despxa suite.
ETH_FORK_BLOCK = 25400000

# The single BASE-mainnet fork block for the deSPXA suite (test_loop_despxa.py), which
# forks a base-mainnet RPC derived from BOA_FORK_RPC_URL (eth-mainnet -> base-mainnet).
# One block per chain, same rule as ETH_FORK_BLOCK. Chosen recent (latest ~48.59M at
# time of writing) where the deSPXA AsyncVault prices and the Centrifuge spoke is live,
# so a freshly-deployed CentrifugeOracleAdapter can read pricePoolPerShare for deSPXA.
BASE_FORK_BLOCK = 48500000


def build_erc20_contract_def_with_log_stuff(main_source_path, main_name, base_def, facet_defs):
    """Return a ``loads_partial`` of the main ERC20 contract with a generated ``log_stuff``.

    ``log_stuff`` emits (with empty args) every event that is *used* by one of the
    delegatecall facets, so boa can decode those events when they surface in a fork
    test. Events declared in the shared base module are emitted with the ``base.``
    prefix. The event field lists come straight from the compiler, so they stay in
    sync with the contract automatically.

    Args:
        main_source_path: path to the main ``*Erc20.vy`` source (str or Path).
        main_name: the ``name=`` to give the loaded partial.
        base_def: the base module ``load_partial`` (for its own ``event_defs``).
        facet_defs: iterable of facet ``load_partial`` objects (Loan / Refinance /
            Liquidation) whose ``used_events`` need decoding.
    """
    base_event_names = {e._metadata["event_type"].name for e in base_def.compiler_data.global_ctx.event_defs}

    events = {e for facet in facet_defs for e in facet.compiler_data.global_ctx.used_events}

    indent = " " * (4 * 2)
    contents = Path(main_source_path).read_text(encoding="utf-8")
    contents += dedent("""
        @external
        def log_stuff():

    """)
    for event in events:
        prefix = "base." if event.name in base_event_names else ""
        args = ", ".join(f"{n}=empty({t})" for n, t in event.arguments.items())
        contents += f"{indent}log {prefix}{event.name}({args})\n"

    return boa.loads_partial(contents, name=main_name)
