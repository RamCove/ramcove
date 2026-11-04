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
    # Origins allowed to send state-changing requests. The web app's proxy sets the origin from its own
    # configuration, so this lists the RamCove web deployments, never arbitrary sites.
    allowed_origins: tuple[str, ...] = ()
    # Public demo only: approve a technically passing submission after this many seconds, as a labelled
    # stand-in for the human reviewer. 0 keeps every review with a person.
    demo_auto_review_s: int = 0
    # The owner platform's secret for the question banks. Each period's seed is derived from it, so it must
    # never reach a repository or a worker; workers receive only the current period's seed.
    bank_secret: bytes | None = None

    @property
    def simulated_chain(self) -> bool:
        return self.network == "ramcove-devchain"


def load_settings() -> Settings:
    env = os.environ.get("RAMCOVE_ENV", "demo")
    if env == "mainnet":
        raise ConfigError("mainnet mode is not available in this build (chain writes are disabled)")
    if env not in {"demo", "local", "testnet", "test"}:
        raise ConfigError(f"unknown RAMCOVE_ENV {env!r}")
    network = "test" if env == "testnet" else "ramcove-devchain"
    return Settings(
        env=env,
        database_url=os.environ.get(
            "RAMCOVE_DATABASE_URL",
            "postgresql+psycopg://ramcove:ramcove-local-dev-only@127.0.0.1:54329/ramcove",
        ),
        public_origin=os.environ.get("RAMCOVE_PUBLIC_ORIGIN", "http://localhost:3787"),
        api_origin=os.environ.get("RAMCOVE_API_ORIGIN", "http://localhost:8787"),
        artifact_dir=Path(os.environ.get("RAMCOVE_ARTIFACT_DIR", str(ROOT / "var/artifacts"))),
        network=network,
        demo_features=env in {"demo", "test"},
        chain_writes_enabled=False,
        netuid=int(os.environ.get("RAMCOVE_NETUID", "0")),
        allowed_origins=tuple(
            o.strip()
            for o in os.environ.get(
                "RAMCOVE_ALLOWED_ORIGINS", os.environ.get("RAMCOVE_PUBLIC_ORIGIN", "http://localhost:3787")
            ).split(",")
            if o.strip()
        ),
        demo_auto_review_s=int(os.environ.get("RAMCOVE_DEMO_AUTO_REVIEW_S", "0")),
        bank_secret=_bank_secret(env),
    )


# Demo, test and local runs have no owner secret to protect; they use this labelled stand-in. Any other
# environment must set RAMCOVE_BANK_SECRET, or no question bank is issued and no evaluation starts.
DEMO_BANK_SECRET = b"ramcove demo question-bank secret: simulated, never for a real network"


def _bank_secret(env: str) -> bytes | None:
    value = os.environ.get("RAMCOVE_BANK_SECRET", "").strip()
    if value:
        return value.encode()
    return DEMO_BANK_SECRET if env in {"demo", "test", "local"} else None
