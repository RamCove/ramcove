"""In-process harness: real services and PostgreSQL, trusted in-process simulated worker, dev chain."""

from __future__ import annotations

import json
import os

from alembic import command
from alembic.config import Config
from ramcove_api.config import ROOT, load_settings
from ramcove_api.services import control, intake, queue, review, seed
from ramcove_api.services import workers as workers_svc
from ramcove_api.services.context import AppContext, ArtifactStore, baseline_fixture, load_trusted_fixtures
from ramcove_api.signing import ServiceSigner
from ramcove_api.store.db import make_engine, tx
from ramcove_api.store.schema import reviews, submissions
from ramcove_miner.artifact import pack, sign_artifact
from ramcove_miner.fixtures import by_name, manifest_for
from ramcove_protocol.rules import ProfileVersion
from ramcove_worker.isolation import SimulatedTrustedProvider
from ramcove_worker.runner import execute
from sqlalchemy import select
from substrateinterface import Keypair

TEST_URL = os.environ.get(
    "RAMCOVE_TEST_DATABASE_URL",
    "postgresql+psycopg://ramcove:ramcove-local-dev-only@127.0.0.1:54329/ramcove_test",
)


def make_ctx(tmp_path) -> AppContext:
    os.environ["RAMCOVE_ENV"] = "test"
    os.environ["RAMCOVE_DATABASE_URL"] = TEST_URL
    settings = load_settings()
    engine = make_engine(TEST_URL)
    ctx = AppContext(engine, settings, ServiceSigner(settings), ArtifactStore(tmp_path / "artifacts"))
    cfg = Config(str(ROOT / "alembic.ini"))
    os.environ["RAMCOVE_MIGRATE_URL"] = TEST_URL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    seed.seed_base(ctx)
    return ctx


def profile(ctx) -> ProfileVersion:
    with tx(ctx.engine) as conn:
        return ctx.profile(conn)


def hotkey(key: str) -> tuple[str, Keypair]:
    d, kp = seed.identity(key)
    return kp.ss58_address, kp


def provider() -> SimulatedTrustedProvider:
    return SimulatedTrustedProvider(load_trusted_fixtures(), baseline_fixture())


def bring_workers_online(ctx, ids=("w-op-1", "w-op-2")) -> None:
    for wid in ids:
        workers_svc.heartbeat(ctx, wid, provider().readiness().as_dict())


def submit_fixture(ctx, miner_key: str, fixture_name: str, parent_version: int = 0) -> dict:
    hk, kp = hotkey(miner_key)
    p = profile(ctx)
    fx = by_name(fixture_name)
    data = pack(manifest_for(fx, hk, p.profile_id, p.version, parent_version), fx["patch"])
    sig = sign_artifact(kp, data, ctx.settings.network, p.profile_id, p.version)
    return intake.preflight(ctx, hk, data, sig)


def pay_and_admit(ctx, sub_id: str, miner_key: str) -> dict:
    hk, _ = hotkey(miner_key)
    q = intake.reserve(ctx, sub_id, hk, payer=hk)
    assert q["status"] == "quoted", q
    intake.demo_pay(ctx, q["quote"]["quote_id"], hk)
    for _ in range(3):
        control.tick(ctx)
    return q


def artifact_bytes(ctx, sha: str) -> bytes:
    from ramcove_api.store.schema import artifacts

    with tx(ctx.engine) as conn:
        key = conn.execute(select(artifacts.c.storage_key).where(artifacts.c.sha256 == sha)).scalar()
    return ctx.artifacts.get(key)


def run_worker_once(ctx, worker_id: str) -> dict | None:
    payload = queue.lease_next(ctx, worker_id)
    if payload is None:
        return None
    p = profile(ctx)
    result = execute(payload, provider(), p, lambda sha: artifact_bytes(ctx, sha))
    queue.complete(ctx, worker_id, payload["job_id"], json.loads(json.dumps(result, default=list)))
    return {"stage": payload["stage"], "job": payload["job_id"], "result": result}


def drain(ctx, max_steps: int = 80, workers=("w-op-1", "w-op-2")) -> list[dict]:
    done = []
    for _ in range(max_steps):
        progressed = False
        for w in workers:
            bring_workers_online(ctx, (w,))
            r = run_worker_once(ctx, w)
            if r:
                done.append(r)
                progressed = True
        control.tick(ctx)
        if not progressed:
            break
    return done


def state(ctx, sub_id: str):
    with tx(ctx.engine) as conn:
        return conn.execute(select(submissions).where(submissions.c.id == sub_id)).first()


def approve_review(ctx, sub_id: str, reviewer_key: str = "reviewer-1") -> dict:
    hk, _ = hotkey(reviewer_key)
    with tx(ctx.engine) as conn:
        rid = conn.execute(
            select(reviews.c.id).where(reviews.c.submission_id == sub_id, reviews.c.decision.is_(None))
        ).scalar()
    crit = {c["id"]: True for c in queue.review_criteria()}
    return review.decide_review(
        ctx, rid, hk, "approve", "All published criteria passed in the demo review.", crit, False
    )
