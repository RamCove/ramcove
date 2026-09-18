"""Network identities. Endpoint names are never trusted: the genesis hash must match before any use.

Verified by read-only RPC ``chain_getBlockHash(0)`` on 2026-09-17 (runtime spec_version 464):
- finney (mainnet): wss://entrypoint-finney.opentensor.ai
- test: wss://test.finney.opentensor.ai
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NetworkName = Literal["ramcove-devchain", "test", "finney"]


@dataclass(frozen=True)
class NetworkIdentity:
    name: NetworkName
    genesis_hash: str
    ss58_format: int
    token_decimals: int
    writes_allowed_in_this_build: bool
    simulated: bool


DEVCHAIN = NetworkIdentity("ramcove-devchain", "0x" + "00" * 31 + "01", 42, 9, True, True)
TESTNET = NetworkIdentity(
    "test", "0x8f9cf856bf558a14440e75569c9e58594757048d7b3a84b5d25f6bd978263105", 42, 9, False, False
)
FINNEY = NetworkIdentity(
    "finney", "0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03", 42, 9, False, False
)

KNOWN = {n.name: n for n in (DEVCHAIN, TESTNET, FINNEY)}


class NetworkMismatch(RuntimeError):
    pass


def require_identity(expected: NetworkIdentity, observed_genesis: str) -> None:
    if observed_genesis.lower() != expected.genesis_hash.lower():
        raise NetworkMismatch(
            f"endpoint genesis {observed_genesis} does not match {expected.name} ({expected.genesis_hash}); refusing"
        )
