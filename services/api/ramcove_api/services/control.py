"""Controller tick: chain progress (dev), payments, expiries, invitations, settlement, refunds, observations."""

from __future__ import annotations

from datetime import timedelta

from ramcove_protocol.reservation import can_issue_quote
from ramcove_protocol.state import S
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from ..store import audit
from ..store.db import advisory_lock, now, tx
from ..store.schema import (
    chain_observations,
    price_observations,
    profile_versions,
    submissions,
    workers,
)
from .accounting import confirm_sent_refunds
from .context import WORKER_HEARTBEAT_FRESH_S, AppContext
from .payments import expire_quotes, scan_finalized
from .queue import expire_leases
from .settlement import settle


def invite_waitlist(conn, ctx: AppContext, profile_id: str) -> int:
    profile = ctx.profile(conn, profile_id)
    advisory_lock(conn, f"capacity:{profile_id}")
    n = 0
    for sub in conn.execute(
        select(submissions).where(
            submissions.c.profile_id == profile_id,
            submissions.c.state == S.INVITED.value,
            submissions.c.invited_until < now(),
        )
    ).all():
        conn.execute(
            update(submissions)
            .where(submissions.c.id == sub.id)
            .values(state=S.WAITLISTED.value, waitlisted_at=now(), invited_until=None, updated_at=now())
        )
        audit.append(conn, "controller", "invitation_missed", "submission", sub.id, {})
    invited = conn.execute(
        select(submissions).where(
            submissions.c.profile_id == profile_id, submissions.c.state == S.INVITED.value
        )
    ).all()
    paused = bool(ctx.setting(conn, "intake_paused", {"paused": False}).get("paused"))
    for sub in conn.execute(
        select(submissions)
        .where(submissions.c.profile_id == profile_id, submissions.c.state == S.WAITLISTED.value)
        .order_by(submissions.c.waitlisted_at)
    ).all():
        plan = ctx.capacity_plan(conn, profile, trusted_fixture=True)
        committed = ctx.committed_centi(conn, profile_id) + len(invited) * profile.envelope.total()
        if not can_issue_quote(committed, profile.envelope, plan, paused).allowed:
            break
        conn.execute(
            update(submissions)
            .where(submissions.c.id == sub.id)
            .values(
                state=S.INVITED.value,
                invited_until=now() + timedelta(seconds=profile.deadlines.invitation_ttl_s),
                updated_at=now(),
            )
        )
        audit.append(conn, "controller", "invited_from_waitlist", "submission", sub.id, {})
        invited.append(sub)
        n += 1
    return n


def tick(ctx: AppContext, produce_block: bool = True) -> dict:
    out: dict = {}
    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        if produce_block and ctx.settings.simulated_chain:
            chain.produce_block()
        if ctx.settings.demo_features:
            latest = ctx.latest_price(conn)
            if latest is None or (latest.simulated and now() - latest.observed_at > timedelta(minutes=5)):
                conn.execute(
                    price_observations.insert().values(
                        source="simulated:demo-price",
                        usd_micros=227_920_000,
                        simulated=True,
                        observed_at=now(),
                    )
                )
        head = chain.finalized_head()
        conn.execute(
            insert(chain_observations)
            .values(
                network=ctx.settings.network,
                finalized_number=head.number,
                finalized_hash=head.hash,
                genesis_hash=chain.genesis_hash(),
                simulated=ctx.settings.simulated_chain,
                observed_at=now(),
            )
            .on_conflict_do_update(
                index_elements=["network"],
                set_={"finalized_number": head.number, "finalized_hash": head.hash, "observed_at": now()},
            )
        )
        out["payments"] = scan_finalized(conn, ctx)
        out["quotes_expired"] = expire_quotes(conn, ctx)
    with tx(ctx.engine) as conn:
        out["leases_expired"] = expire_leases(conn, ctx)
        stale = now() - timedelta(seconds=WORKER_HEARTBEAT_FRESH_S)
        conn.execute(
            update(workers).where(workers.c.last_heartbeat < stale, workers.c.ready).values(ready=False)
        )
    for pid in _profiles(ctx):
        with tx(ctx.engine) as conn:
            out.setdefault("invited", 0)
            out["invited"] += invite_waitlist(conn, ctx, pid)
        with tx(ctx.engine) as conn:
            out.setdefault("settlement", []).extend(settle(conn, ctx, pid))
    with tx(ctx.engine) as conn:
        out["refunds_confirmed"] = confirm_sent_refunds(conn, ctx)
    return out


def _profiles(ctx: AppContext) -> list[str]:
    with tx(ctx.engine) as conn:
        return [
            r.profile_id
            for r in conn.execute(select(profile_versions.c.profile_id).where(profile_versions.c.active))
        ]
