"""Service signing for quotes and receipts (sr25519 via substrate-interface).

Demo/local modes derive a deterministic *demo* key that is published in this repository and has no
value on any network. Any other mode requires an external signer, which this build does not provide,
so issuing signed records fails closed there.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ramcove_protocol.canonical import signing_payload
from substrateinterface import Keypair

from .config import ConfigError, Settings

DEMO_SERVICE_URI = "//RamCoveDemoIntakeService"


@lru_cache(maxsize=4)
def _demo_keypair(uri: str) -> Keypair:
    return Keypair.create_from_uri(uri)


class ServiceSigner:
    def __init__(self, settings: Settings) -> None:
        if not settings.simulated_chain:
            raise ConfigError(
                "no production signer configured; signed quotes/receipts are disabled in this mode"
            )
        self._kp = _demo_keypair(DEMO_SERVICE_URI)
        self.network = settings.network
        self.demo = True

    @property
    def address(self) -> str:
        return self._kp.ss58_address

    def sign(self, record_type: str, body: dict[str, Any]) -> str:
        return "0x" + self._kp.sign(signing_payload(record_type, self.network, body)).hex()


def verify_sr25519(address: str, message: bytes, signature: bytes) -> bool:
    try:
        return bool(Keypair(ss58_address=address).verify(message, signature))
    except (ValueError, TypeError):
        return False
