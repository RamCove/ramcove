"""Runtime configuration. Execution modes are explicit and fail closed.

- ``demo``: deterministic dev chain, dev beacon, simulated worker, demo identities and seed scenarios.
- ``local``: same simulated chain but no demo sign-in or seed endpoints.
- ``testnet``: real read-only chain reads; writes stay disabled unless separately authorized (not in this build).
- ``mainnet`` is refused by this build.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    public_origin: str
    api_origin: str
    artifact_dir: Path
    network: str
    demo_features: bool
    chain_writes_enabled: bool
    netuid: int

    @property
    def simulated_chain(self) -> bool:
        return self.network == "room-devchain"


def load_settings() -> Settings:
    env = os.environ.get("ROOM_ENV", "demo")
    if env == "mainnet":
        raise ConfigError(
            "mainnet mode is not available in this build (writes and real payments are disabled)"
        )
    if env not in {"demo", "local", "testnet", "test"}:
        raise ConfigError(f"unknown ROOM_ENV {env!r}")
    network = "test" if env == "testnet" else "room-devchain"
    return Settings(
        env=env,
        database_url=os.environ.get(
            "ROOM_DATABASE_URL", "postgresql+psycopg://room:room-local-dev-only@127.0.0.1:54329/room"
        ),
        public_origin=os.environ.get("ROOM_PUBLIC_ORIGIN", "http://localhost:3787"),
        api_origin=os.environ.get("ROOM_API_ORIGIN", "http://localhost:8787"),
        artifact_dir=Path(os.environ.get("ROOM_ARTIFACT_DIR", str(ROOT / "var/artifacts"))),
        network=network,
        demo_features=env in {"demo", "test"},
        chain_writes_enabled=False,
        netuid=int(os.environ.get("ROOM_NETUID", "0")),
    )
