"""Demo dataset (clearly labelled) and resettable local state. Refused outside demo mode."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from alembic import command
from alembic.config import Config
from psycopg.errors import DeadlockDetected, LockNotAvailable
from ramcove_chain.devchain import DevChain
from ramcove_protocol.rules import ProfileVersion
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from substrateinterface import Keypair

from ..config import ROOT
from ..store import audit
from ..store.db import tx
from ..store.devchain_sql import SqlDevChainStore
from ..store.schema import (
    champion_pointer,
    champions,
    identities,
    profile_versions,
    role_grants,
    validators,
    workers,
)
from ..store.schema import (
    settings as settings_t,
)
from .context import AppContext, ServiceError


@dataclass(frozen=True)
class DemoIdentity:
    key: str
    uri: str
    name: str
    roles: tuple[str, ...]


DEMO_IDENTITIES = [
    DemoIdentity("miner-ada", "//RamCoveDemoMinerAda", "Ada (demo miner)", ("miner",)),
    DemoIdentity("miner-bao", "//RamCoveDemoMinerBao", "Bao (demo miner)", ("miner",)),
    DemoIdentity("miner-cyd", "//RamCoveDemoMinerCyd", "Cyd (demo miner)", ("miner",)),
    DemoIdentity("miner-dee", "//RamCoveDemoMinerDee", "Dee (demo miner, unregistered)", ("miner",)),
    DemoIdentity(
        "validator-op",
        "//RamCoveDemoValidatorOperator",
        "RamCove owner-operated validator (demo)",
        ("validator",),
    ),
    DemoIdentity(
        "validator-weights",
        "//RamCoveDemoValidatorWeights",
        "Weight validator (demo, sets weights from the owner's signed results)",
        ("validator",),
    ),
    DemoIdentity("reviewer-1", "//RamCoveDemoReviewerOne", "Reviewer One (demo)", ("reviewer",)),
    DemoIdentity(
        "reviewer-2", "//RamCoveDemoReviewerTwo", "Independent reviewer (demo)", ("reviewer", "appeal_panel")
    ),
    DemoIdentity("panel-1", "//RamCoveDemoAppealPanel", "Appeal panel member (demo)", ("appeal_panel",)),
    DemoIdentity("operator", "//RamCoveDemoOperator", "Operator (demo)", ("operator",)),
]

DEMO_WORKERS = [
    ("w-op-1", "validator-op", "//RamCoveDemoWorkerOne"),
    ("w-op-2", "validator-op", "//RamCoveDemoWorkerTwo"),
]


def identity(key: str) -> tuple[DemoIdentity, Keypair]:
    for d in DEMO_IDENTITIES:
        if d.key == key:
            return d, Keypair.create_from_uri(d.uri)
    raise ServiceError("unknown_demo_identity", f"unknown demo identity {key}", 404)


def worker_keypair(worker_id: str) -> Keypair:
    for wid, _, uri in DEMO_WORKERS:
        if wid == worker_id:
            return Keypair.create_from_uri(uri)
    raise KeyError(worker_id)


def reset_database(ctx: AppContext) -> None:
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "reset is only available in demo mode", 403)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "services/api/migrations"))
    import os

    os.environ["RAMCOVE_MIGRATE_URL"] = ctx.settings.database_url
    # Dropping every table deadlocks with a controller or worker that is mid-query. PostgreSQL runs the
    # whole downgrade in one transaction and rolls it back cleanly when it picks this side as the victim,
    # so retrying after the other short transaction finishes is safe.
    for attempt in range(5):
        try:
            command.downgrade(cfg, "base")
            break
        except OperationalError as e:
            if not isinstance(e.orig, (DeadlockDetected, LockNotAvailable)) or attempt == 4:
                raise
            time.sleep(0.5 * (2**attempt))
    command.upgrade(cfg, "head")


def seed_base(ctx: AppContext) -> dict:
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "seeding is only available in demo mode", 403)
    profile = ProfileVersion.model_validate(
        json.loads((ROOT / "config/profiles/ramcove-p1@1.0.0.json").read_text())
    )
    with tx(ctx.engine) as conn:
        if conn.execute(select(profile_versions)).first():
            return {"seeded": False, "reason": "already seeded"}
        conn.execute(
            profile_versions.insert().values(
                profile_id=profile.profile_id,
                version=profile.version,
                rule_hash=profile.rule_hash(),
                body=profile.model_dump(mode="json", by_alias=True),
                active=True,
            )
        )
        conn.execute(
            champions.insert().values(
                profile_id=profile.profile_id,
                version=0,
                submission_id=None,
                author_hotkey=None,
                artifact_sha256=None,
                rule_hash=profile.rule_hash(),
                status="current",
                attribution={
                    "components": [],
                    "note": "Tuned vLLM v0.29.0 baseline. No author; earns nothing.",
                },
                status_reason="champion version 0: tuned baseline",
            )
        )
        conn.execute(champion_pointer.insert().values(profile_id=profile.profile_id, version=0))
        for d in DEMO_IDENTITIES:
            kp = Keypair.create_from_uri(d.uri)
            conn.execute(
                insert(identities)
                .values(hotkey=kp.ss58_address, display_name=d.name, demo=True)
                .on_conflict_do_nothing()
            )
            for role in d.roles:
                conn.execute(
                    role_grants.insert().values(
                        hotkey=kp.ss58_address,
                        role=role,
                        granted_by="demo-seed",
                        independent_group=None,
                    )
                )
        op = Keypair.create_from_uri("//RamCoveDemoValidatorOperator").ss58_address
        conn.execute(
            validators.insert().values(
                hotkey=op,
                name="RamCove owner-operated validator (demo): evaluates and publishes signed results",
                operator_affiliated=True,
                independence_group="ramcove-operator",
                scoring=True,
            )
        )
        wv = Keypair.create_from_uri("//RamCoveDemoValidatorWeights").ss58_address
        conn.execute(
            validators.insert().values(
                hotkey=wv,
                name="Weight validator (demo, no evaluation)",
                operator_affiliated=False,
                independence_group="weights-1",
                scoring=False,
            )
        )
        for wid, _validator, uri in DEMO_WORKERS:
            conn.execute(
                workers.insert().values(
                    id=wid,
                    validator=op,
                    profile_id=profile.profile_id,
                    provider="simulated-trusted-fixtures",
                    public_key=Keypair.create_from_uri(uri).ss58_address,
                    readiness={"simulated": True},
                    ready=False,
                    enabled=True,
                )
            )
        conn.execute(
            settings_t.insert().values(
                key="intake_paused", value={"paused": False}, updated_by="demo-seed", reason="demo start"
            )
        )
        chain = DevChain(SqlDevChainStore(conn))
        chain.produce_blocks(5)
        chain.store.register(ctx.settings.netuid, ctx.owner_hotkey)  # owner UID 0
        # both validators need a UID to set weights; the owner's validator evaluates, the other only follows
        for key in ("miner-ada", "miner-bao", "miner-cyd", "validator-op", "validator-weights"):
            chain.store.register(
                ctx.settings.netuid, Keypair.create_from_uri(identity(key)[0].uri).ss58_address
            )
        audit.append(
            conn,
            "demo-seed",
            "demo_seeded",
            "profile",
            profile.profile_id,
            {"rule_hash": profile.rule_hash(), "simulated": True},
            public=True,
        )
    from .settlement import publish_weight_plan

    with tx(ctx.engine) as conn:
        publish_weight_plan(conn, ctx, profile.profile_id)
    return {"seeded": True, "profile": profile.profile_id}
