"""Shared application context: engine, settings, signer, profiles, chain access and artifact storage."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from room_chain.devchain import DevChain
from room_chain.network import DEVCHAIN
from room_protocol.fees import PriceObservation
from room_protocol.reservation import CapacityPlan
from room_protocol.rules import ProfileVersion
from sqlalchemy import Connection, Engine, func, select
from substrateinterface import Keypair

from ..config import ROOT, Settings
from ..signing import ServiceSigner
from ..store.db import now
from ..store.devchain_sql import SqlDevChainStore
from ..store.schema import price_observations, profile_versions, submissions, workers
from ..store.schema import settings as settings_t

DEMO_EVALUATION_WALLET_URI = "//RoomDemoEvaluationWallet"
DEMO_OWNER_HOTKEY_URI = "//RoomDemoSubnetOwner"
WORKER_HEARTBEAT_FRESH_S = 120


class ServiceError(Exception):
    """User-facing, safe error with a stable code."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class ArtifactStore:
    """Local content-addressed storage (development stand-in for S3-compatible storage)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)

    def put(self, sha256: str, data: bytes) -> str:
        key = f"artifacts/{sha256[:2]}/{sha256}.tar.gz"
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd, tmp = tempfile.mkstemp(dir=path.parent)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        return key

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


@dataclass
class AppContext:
    engine: Engine
    settings: Settings
    signer: ServiceSigner
    artifacts: ArtifactStore

    @property
    def evaluation_wallet(self) -> str:
        return Keypair.create_from_uri(DEMO_EVALUATION_WALLET_URI).ss58_address

    @property
    def owner_hotkey(self) -> str:
        return Keypair.create_from_uri(DEMO_OWNER_HOTKEY_URI).ss58_address

    def chain(self, conn: Connection) -> DevChain:
        if not self.settings.simulated_chain:
            raise ServiceError(
                "chain_unavailable", "only the simulated dev chain is wired in this build", 503
            )
        return DevChain(SqlDevChainStore(conn), finality_lag=2)

    @property
    def network_identity(self):
        return DEVCHAIN

    def profile(self, conn: Connection, profile_id: str | None = None) -> ProfileVersion:
        q = select(profile_versions.c.body).where(profile_versions.c.active)
        if profile_id:
            q = q.where(profile_versions.c.profile_id == profile_id)
        body = conn.execute(q.limit(1)).scalar()
        if body is None:
            raise ServiceError("no_profile", "no active profile is published", 404)
        return ProfileVersion.model_validate(body)

    def profile_by_hash(self, conn: Connection, rule_hash: str) -> ProfileVersion:
        body = conn.execute(
            select(profile_versions.c.body).where(profile_versions.c.rule_hash == rule_hash)
        ).scalar()
        if body is None:
            raise ServiceError("unknown_profile_version", "profile version not found", 404)
        return ProfileVersion.model_validate(body)

    def setting(self, conn: Connection, key: str, default=None):
        v = conn.execute(select(settings_t.c.value).where(settings_t.c.key == key)).scalar()
        return default if v is None else v

    def latest_price(self, conn: Connection) -> PriceObservation | None:
        row = conn.execute(
            select(price_observations).order_by(price_observations.c.observed_at.desc()).limit(1)
        ).first()
        if not row:
            return None
        return PriceObservation(row.source, int(row.usd_micros), row.observed_at, row.simulated)

    def ready_workers(self, conn: Connection, profile_id: str, untrusted_capable: bool | None = None) -> list:
        fresh = now() - timedelta(seconds=WORKER_HEARTBEAT_FRESH_S)
        rows = conn.execute(
            select(workers).where(
                workers.c.profile_id == profile_id,
                workers.c.enabled,
                workers.c.ready,
                workers.c.last_heartbeat >= fresh,
            )
        ).all()
        if untrusted_capable is None:
            return list(rows)
        return [r for r in rows if bool(r.readiness.get("untrusted_code_isolation")) == untrusted_capable]

    def capacity_plan(self, conn: Connection, profile: ProfileVersion, trusted_fixture: bool) -> CapacityPlan:
        ready = self.ready_workers(conn, profile.profile_id)
        if not trusted_fixture:
            ready = [r for r in ready if r.readiness.get("untrusted_code_isolation")]
        return CapacityPlan(workers_ready=len(ready), horizon_hours=336)

    def committed_centi(self, conn: Connection, profile_id: str) -> int:
        return int(
            conn.execute(
                select(func.coalesce(func.sum(submissions.c.reserved_centi), 0)).where(
                    submissions.c.profile_id == profile_id
                )
            ).scalar()
            or 0
        )


def load_trusted_fixtures() -> dict[str, dict]:
    """Trusted demo fixtures, identified by artifact hash produced by the repository's deterministic builder."""
    path = ROOT / "fixtures" / "trusted_fixtures.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def baseline_fixture() -> dict:
    path = ROOT / "fixtures" / "trusted_fixtures.json"
    return json.loads(path.read_text())["_baseline"]
