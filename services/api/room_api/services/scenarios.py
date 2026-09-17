"""Seeded demo scenarios. Each one drives the real services and a real (simulated) worker.

Nothing is written straight into a result table: a scenario only performs the same calls a miner,
worker, reviewer or operator would make, so what you see on screen is produced by the protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from room_miner.artifact import pack, sign_artifact
from room_miner.fixtures import by_name, manifest_for
from room_protocol.rules import ProfileVersion
from room_worker.isolation import SimulatedTrustedProvider
from room_worker.runner import execute
from sqlalchemy import select, update

from ..store.db import now, tx
from ..store.schema import artifacts, jobs, reviews, submissions
from . import control, intake, queue, review, seed
from .context import AppContext, ServiceError, baseline_fixture, load_trusted_fixtures
from .queue import review_criteria

SCENARIOS = {
    "fresh": "Seeded state only: champion version 0, nothing submitted.",
    "champion": "A challenger is measured, reviewed and promoted to champion version 1.",
    "busy": "Several submissions in flight: one promoted, one failing quality, one waiting.",
    "rejected_payment": "An underpaid quote is rejected and a refund liability is opened.",
    "worker_failure": "A lease expires twice, the submission ends as an operator failure with a credit.",
    "stale_comparison": "Two potential winners: the first is promoted, the second is rebased.",
    "failed_quality": "A challenger that saves memory but loses accuracy is rejected.",
    "no_champion_registration": "A technically approved winner never registers, so the incumbent keeps the crown.",
}


@dataclass
class Harness:
    ctx: AppContext

    def provider(self) -> SimulatedTrustedProvider:
        return SimulatedTrustedProvider(load_trusted_fixtures(), baseline_fixture())

    def profile(self) -> ProfileVersion:
        with tx(self.ctx.engine) as conn:
            return self.ctx.profile(conn)

    def hotkey(self, key: str) -> tuple[str, object]:
        d, kp = seed.identity(key)
        return kp.ss58_address, kp

    def online(self, workers: tuple[str, ...] = ("w-op-1", "w-op-2")) -> None:
        from . import workers as workers_svc

        for wid in workers:
            workers_svc.heartbeat(self.ctx, wid, self.provider().readiness().as_dict())

    def submit(self, miner: str, fixture: str) -> str:
        hk, kp = self.hotkey(miner)
        p = self.profile()
        fx = by_name(fixture)
        with tx(self.ctx.engine) as conn:
            champ = queue.current_champion(conn, p.profile_id)
        data = pack(manifest_for(fx, hk, p.profile_id, p.version, champ.version), fx["patch"])
        sig = sign_artifact(kp, data, self.ctx.settings.network, p.profile_id, p.version)
        r = intake.preflight(self.ctx, hk, data, sig)
        if not r.get("ok"):
            raise ServiceError("scenario_failed", f"preflight rejected: {r.get('errors')}", 500)
        return r["submission_id"]

    def pay(self, sub_id: str, miner: str, amount_override: int | None = None) -> dict:
        hk, _ = self.hotkey(miner)
        q = intake.reserve(self.ctx, sub_id, hk, payer=hk)
        if q["status"] != "quoted":
            return q
        intake.demo_pay(self.ctx, q["quote"]["quote_id"], hk, amount_override=amount_override)
        for _ in range(3):
            control.tick(self.ctx)
        return q

    def work(self, steps: int = 60, workers: tuple[str, ...] = ("w-op-1", "w-op-2")) -> int:
        done = 0
        for _ in range(steps):
            progressed = False
            for wid in workers:
                self.online((wid,))
                payload = queue.lease_next(self.ctx, wid)
                if payload is None:
                    continue
                result = execute(payload, self.provider(), self.profile(), self._artifact)
                queue.complete(self.ctx, wid, payload["job_id"], json.loads(json.dumps(result, default=list)))
                progressed = True
                done += 1
            control.tick(self.ctx)
            if not progressed:
                break
        return done

    def _artifact(self, sha: str) -> bytes:
        with tx(self.ctx.engine) as conn:
            key = conn.execute(select(artifacts.c.storage_key).where(artifacts.c.sha256 == sha)).scalar()
        return self.ctx.artifacts.get(key)

    def approve(self, sub_id: str, reviewer: str = "reviewer-1") -> None:
        hk, _ = self.hotkey(reviewer)
        with tx(self.ctx.engine) as conn:
            rid = conn.execute(
                select(reviews.c.id).where(reviews.c.submission_id == sub_id, reviews.c.decision.is_(None))
            ).scalar()
        if rid:
            review.decide_review(
                self.ctx,
                rid,
                hk,
                "approve",
                "Demo review: published criteria all pass.",
                {c["id"]: True for c in review_criteria()},
                False,
            )
            control.tick(self.ctx)

    def state(self, sub_id: str) -> str:
        with tx(self.ctx.engine) as conn:
            return conn.execute(select(submissions.c.state).where(submissions.c.id == sub_id)).scalar()

    def mark(self, sub_id: str, scenario: str) -> None:
        with tx(self.ctx.engine) as conn:
            conn.execute(update(submissions).where(submissions.c.id == sub_id).values(scenario=scenario))


def run(ctx: AppContext, name: str) -> dict:
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "scenarios are only available in demo mode", 403)
    if name not in SCENARIOS:
        raise ServiceError("unknown_scenario", f"unknown scenario {name}", 404)
    h = Harness(ctx)
    h.online()
    out: dict = {"scenario": name, "description": SCENARIOS[name], "submissions": {}}

    if name == "fresh":
        return out

    if name in ("champion", "busy", "stale_comparison", "no_champion_registration"):
        win = h.submit("miner-ada", "fragmentation-aware-allocator")
        h.mark(win, name)
        h.pay(win, "miner-ada")
        if name == "busy":
            bad = h.submit("miner-bao", "evict-quarter")
            h.mark(bad, name)
            h.pay(bad, "miner-bao")
            out["submissions"]["quality_failure"] = bad
        if name == "stale_comparison":
            second = h.submit("miner-bao", "kv8-conversation-retention")
            h.mark(second, name)
            h.pay(second, "miner-bao")
            out["submissions"]["second_potential_winner"] = second
        h.work()
        out["submissions"]["challenger"] = win
        if name == "no_champion_registration":
            # a miner whose hotkey is not registered on the dev chain cannot take the crown
            hk, _ = h.hotkey("miner-ada")
            with tx(ctx.engine) as conn:
                ctx.chain(conn).store.deregister(ctx.settings.netuid, hk)
            out["note"] = (
                f"{hk} is not registered, so the incumbent keeps the allocation until the grace ends."
            )
        if h.state(win) == "in_review":
            h.approve(win)
        h.work()
        for _ in range(3):
            control.tick(ctx)
        out["final_state"] = h.state(win)
        return out

    if name == "failed_quality":
        bad = h.submit("miner-bao", "evict-quarter")
        h.mark(bad, name)
        h.pay(bad, "miner-bao")
        h.work()
        out["submissions"]["quality_failure"] = bad
        out["final_state"] = h.state(bad)
        return out

    if name == "rejected_payment":
        sub = h.submit("miner-cyd", "quality-drift")
        h.mark(sub, name)
        q = h.pay(sub, "miner-cyd", amount_override=1_000)  # far below the quoted amount
        out["submissions"]["underpaid"] = sub
        out["quote_status"] = q.get("status")
        out["final_state"] = h.state(sub)
        return out

    if name == "worker_failure":
        sub = h.submit("miner-cyd", "kv8-conversation-retention")
        h.mark(sub, name)
        h.pay(sub, "miner-cyd")
        with tx(ctx.engine) as conn:
            # force the screening lease to expire twice: the miner keeps priority, then gets a credit
            for _ in range(2):
                job = conn.execute(
                    select(jobs).where(jobs.c.submission_id == sub, jobs.c.status.in_(["queued", "leased"]))
                ).first()
                if job is None:
                    break
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job.id)
                    .values(
                        status="leased",
                        lease_worker="w-op-1",
                        lease_expires_at=now(),
                        attempts=job.attempts + 1,
                    )
                )
                queue.expire_leases(conn, ctx)
        control.tick(ctx)
        out["submissions"]["stalled"] = sub
        out["final_state"] = h.state(sub)
        return out

    return out
