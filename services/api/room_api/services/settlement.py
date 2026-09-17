"""Promotion in admission order with an atomic champion check-and-set (review R2, R5, R6)."""

from __future__ import annotations

from datetime import timedelta

from room_protocol.settlement import AdmissionKey, QueueEntry, decide_promotion
from room_protocol.state import PAID_ACTIVE, S
from room_protocol.weights import ChampionState, UidSnapshot, build_weight_plan
from sqlalchemy import Connection, select, update

from ..store import audit
from ..store.db import advisory_lock, new_id, now
from ..store.schema import (
    champion_pointer,
    champions,
    jobs,
    profile_versions,
    submissions,
    weight_plans,
    workers,
)
from .context import AppContext
from .queue import (
    _consume_fee,
    _create_blocks,
    _operator_failure,
    cancel_stale_blocks,
    current_champion,
    transition,
)

NETUID_DEMO = 0


def _entries(conn: Connection, ctx: AppContext, profile_id: str) -> list[QueueEntry]:
    chain = ctx.chain(conn)
    _, uids = chain.hotkey_uid_map(ctx.settings.netuid)
    rows = conn.execute(
        select(submissions).where(
            submissions.c.profile_id == profile_id, submissions.c.admission_block.is_not(None)
        )
    ).all()
    return [
        QueueEntry(
            r.id,
            r.profile_id,
            AdmissionKey(r.admission_block, r.admission_index),
            S(r.state),
            r.compared_champion_version,
            r.compared_rule_hash,
            r.hotkey in uids,
            bool(r.deadline_at and r.deadline_at < now()),
        )
        for r in rows
    ]


def settle(conn: Connection, ctx: AppContext, profile_id: str) -> list[dict]:
    advisory_lock(conn, f"settlement:{profile_id}")
    profile = ctx.profile(conn, profile_id)
    actions: list[dict] = []
    # 1. bounded lifecycle: end-to-end deadlines release the barrier as operator failures (miner not charged)
    for r in conn.execute(
        select(submissions).where(
            submissions.c.profile_id == profile_id,
            submissions.c.state.in_([s.value for s in PAID_ACTIVE]),
            submissions.c.deadline_at < now(),
        )
    ).all():
        if r.state == S.READY_FOR_PROMOTION:
            continue  # governed by the registration grace below
        _operator_failure(conn, ctx, r.id, "end-to-end service deadline passed")
        actions.append({"submission": r.id, "action": "deadline_operator_failure"})
    entries = _entries(conn, ctx, profile_id)
    champ = current_champion(conn, profile_id)
    rule_hash = profile.rule_hash()
    for e in sorted((x for x in entries if x.state == S.READY_FOR_PROMOTION), key=lambda x: x.key):
        sub = conn.execute(select(submissions).where(submissions.c.id == e.submission_id)).first()
        grace_over = bool(
            sub.ready_since
            and now() - sub.ready_since > timedelta(seconds=profile.deadlines.registration_grace_s)
        )
        d = decide_promotion(e, entries, champ.version, rule_hash, registration_expired=grace_over)
        if d.action == "promote":
            promoted = promote(conn, ctx, profile, sub, champ.version)
            actions.append({"submission": sub.id, "action": "promoted" if promoted else "cas_failed"})
            break  # champion changed: later entries are re-evaluated next tick against the new version
        if d.action == "rebase":
            rebase(
                conn, ctx, profile, sub, champ.version, "champion or rule version changed before promotion"
            )
            actions.append({"submission": sub.id, "action": "rebase"})
        elif d.action == "expire_registration":
            transition(
                conn,
                ctx,
                sub.id,
                "registration_expired",
                fee_outcome="consumed",
                outcome_code="registration_expired",
                outcome_summary="Technically approved, but the hotkey was not registered within the grace "
                "period. The incumbent champion kept its allocation.",
            )
            _consume_fee(conn, ctx, sub.id)
            audit.append(conn, "controller", "registration_expired", "submission", sub.id, {}, public=True)
            actions.append({"submission": sub.id, "action": "registration_expired"})
        elif d.action == "wait":
            actions.append(
                {"submission": sub.id, "action": "wait", "reason": d.reason, "blocking": list(d.blocking)}
            )
    return actions


def promote(conn: Connection, ctx: AppContext, profile, sub, compared_version: int) -> bool:
    res = conn.execute(
        update(champion_pointer)
        .where(
            champion_pointer.c.profile_id == sub.profile_id, champion_pointer.c.version == compared_version
        )
        .values(version=compared_version + 1, updated_at=now())
    )
    if res.rowcount != 1:
        return False  # another promotion won the race; this one will be rebased
    new_version = compared_version + 1
    conn.execute(
        update(champions)
        .where(champions.c.profile_id == sub.profile_id, champions.c.status == "current")
        .values(status="superseded")
    )
    from ..store.schema import artifacts

    art = conn.execute(select(artifacts).where(artifacts.c.sha256 == sub.artifact_sha256)).first()
    prev = conn.execute(
        select(champions).where(
            champions.c.profile_id == sub.profile_id, champions.c.version == compared_version
        )
    ).first()
    base = prev.capacity_milli_rps or 0
    conn.execute(
        champions.insert().values(
            profile_id=sub.profile_id,
            version=new_version,
            submission_id=sub.id,
            author_hotkey=sub.hotkey,
            artifact_sha256=sub.artifact_sha256,
            rule_hash=sub.rule_hash,
            capacity_milli_rps=int(base * (1 + (sub.triage_gain_ppm or 0) / 1e6)) if base else None,
            capacity_measured=False,
            bound_gain_ppm=sub.bound_gain_ppm,
            status="current",
            attribution={
                "components": [
                    {
                        "hotkey": sub.hotkey,
                        "lineage": sub.lineage,
                        "method": art.manifest.get("method"),
                        "artifact_sha256": sub.artifact_sha256,
                    }
                ],
                "note": "Champion is the complete stack actually tested; earlier components are not "
                "assumed to be included unless present in this artifact.",
            },
        )
    )
    transition(
        conn,
        ctx,
        sub.id,
        "promote",
        fee_outcome="consumed",
        outcome_code="promoted",
        outcome_summary=f"Promoted to champion version {new_version}.",
    )
    _consume_fee(conn, ctx, sub.id)
    conn.execute(
        update(workers).where(workers.c.profile_id == sub.profile_id).values(calibrated_champion_version=None)
    )
    audit.append(
        conn,
        "controller",
        "champion_promoted",
        "champion",
        f"{sub.profile_id}:{new_version}",
        {
            "submission_id": sub.id,
            "author_hotkey": sub.hotkey,
            "previous_version": compared_version,
            "bound_gain_ppm": sub.bound_gain_ppm,
        },
        public=True,
    )
    for other in conn.execute(
        select(submissions).where(
            submissions.c.profile_id == sub.profile_id,
            submissions.c.id != sub.id,
            submissions.c.state.in_(
                [S.CONFIRM_QUEUED.value, S.CONFIRMING.value, S.IN_REVIEW.value, S.READY_FOR_PROMOTION.value]
            ),
        )
    ).all():
        rebase(conn, ctx, profile, other, new_version, f"champion changed to version {new_version}")
    publish_weight_plan(conn, ctx, sub.profile_id)
    return True


def rebase(conn: Connection, ctx: AppContext, profile, sub, champion_version: int, reason: str) -> None:
    if sub.rebases_used >= profile.deadlines.max_rebases:
        _operator_failure(conn, ctx, sub.id, "maximum automatic rebases reached after champion changes")
        return
    cancel_stale_blocks(conn, sub.id, champion_version)
    transition(
        conn,
        ctx,
        sub.id,
        "rebase",
        rebases_used=sub.rebases_used + 1,
        compared_champion_version=None,
        ready_since=None,
    )
    _create_blocks(
        conn,
        conn.execute(select(submissions).where(submissions.c.id == sub.id)).first(),
        profile,
        champion_version,
    )
    audit.append(
        conn,
        "controller",
        "rebased",
        "submission",
        sub.id,
        {"reason": reason, "new_champion_version": champion_version, "fee": "no new fee", "priority": "kept"},
        public=True,
    )


def publish_weight_plan(conn: Connection, ctx: AppContext, profile_id: str) -> dict:
    chain = ctx.chain(conn)
    block, uids = chain.hotkey_uid_map(ctx.settings.netuid)
    champ = current_champion(conn, profile_id)
    body_profile = conn.execute(
        select(profile_versions.c.body).where(
            profile_versions.c.active, profile_versions.c.profile_id == profile_id
        )
    ).scalar()
    state = ChampionState(
        profile_id,
        champ.version,
        champ.author_hotkey,
        eligible=champ.status == "current",
        suspended=champ.status == "suspended",
    )
    plan = build_weight_plan(
        [state],
        {profile_id: 10_000},
        UidSnapshot(block, ctx.settings.netuid, uids, ctx.owner_hotkey),
        no_winner_mechanism_verified=bool(body_profile.get("no_winner_writer_verified")),
    )
    body = {
        "schema": plan.schema,
        "snapshot_block": plan.snapshot_block,
        "netuid": plan.netuid,
        "champion_version": champ.version,
        "entries": [e.__dict__ for e in plan.entries],
        "no_winner": plan.no_winner,
        "notes": list(plan.notes),
        "writer_enabled": plan.writer_enabled and ctx.settings.chain_writes_enabled,
        "status": "proposed_not_submitted",
        "simulated": ctx.settings.simulated_chain,
    }
    pid = new_id("wp")
    conn.execute(
        weight_plans.insert().values(
            id=pid,
            network=ctx.settings.network,
            snapshot_block=block,
            body=body,
            writer_enabled=body["writer_enabled"],
            simulated=body["simulated"],
        )
    )
    audit.append(
        conn,
        "controller",
        "weight_plan_proposed",
        "weight_plan",
        pid,
        {"champion_version": champ.version, "no_winner": plan.no_winner},
        public=True,
    )
    return body


def suspend_and_rollback(
    conn: Connection, ctx: AppContext, profile_id: str, operator: str, reason: str, deliberate: bool
) -> dict:
    """Emergency path: the reviewed previous safe stack becomes current again as a NEW version number, so every
    pending comparison is rebased and the audit trail keeps the suspended version intact."""
    advisory_lock(conn, f"settlement:{profile_id}")
    profile = ctx.profile(conn, profile_id)
    champ = current_champion(conn, profile_id)
    if champ.version == 0:
        return {"ok": False, "reason": "version 0 is the tuned baseline; nothing to roll back to"}
    prev = conn.execute(
        select(champions)
        .where(
            champions.c.profile_id == profile_id,
            champions.c.version < champ.version,
            champions.c.status.in_(["superseded"]),
        )
        .order_by(champions.c.version.desc())
        .limit(1)
    ).first()
    new_version = champ.version + 1
    conn.execute(
        update(champion_pointer)
        .where(champion_pointer.c.profile_id == profile_id, champion_pointer.c.version == champ.version)
        .values(version=new_version)
    )
    conn.execute(
        update(champions)
        .where(champions.c.profile_id == profile_id, champions.c.version == champ.version)
        .values(status="rolled_back", status_reason=reason)
    )
    restored_author = prev.author_hotkey if prev else None
    conn.execute(
        champions.insert().values(
            profile_id=profile_id,
            version=new_version,
            submission_id=prev.submission_id if prev else None,
            author_hotkey=restored_author,
            artifact_sha256=prev.artifact_sha256 if prev else None,
            rule_hash=profile.rule_hash(),
            capacity_milli_rps=prev.capacity_milli_rps if prev else None,
            bound_gain_ppm=prev.bound_gain_ppm if prev else None,
            status="current",
            attribution={
                "restored_from_version": prev.version if prev else 0,
                "reason": reason,
                "suspended_version": champ.version,
                "suspended_flaw_deliberate": deliberate,
            },
            status_reason=f"restored after rollback of version {champ.version}",
        )
    )
    for other in conn.execute(
        select(submissions).where(
            submissions.c.profile_id == profile_id,
            submissions.c.state.in_(
                [S.CONFIRM_QUEUED.value, S.CONFIRMING.value, S.IN_REVIEW.value, S.READY_FOR_PROMOTION.value]
            ),
        )
    ).all():
        rebase(conn, ctx, profile, other, new_version, f"rollback to a safe stack (version {new_version})")
    conn.execute(
        update(workers).where(workers.c.profile_id == profile_id).values(calibrated_champion_version=None)
    )
    conn.execute(
        update(jobs)
        .where(jobs.c.stage == "calibration", jobs.c.status == "queued")
        .values(status="cancelled")
    )
    audit.append(
        conn,
        operator,
        "champion_rolled_back",
        "champion",
        f"{profile_id}:{champ.version}",
        {
            "reason": reason,
            "deliberate": deliberate,
            "restored_version": new_version,
            "restored_author": restored_author,
        },
        public=True,
    )
    publish_weight_plan(conn, ctx, profile_id)
    return {"ok": True, "suspended_version": champ.version, "current_version": new_version}
