"""Promotion in admission order with an atomic champion check-and-set (review R2, R5, R6).

When a challenger is crowned, every other measured winner is re-compared with it by arithmetic: both gains are
ratios to the same earlier champion's fixed score, so nothing is measured again."""

from __future__ import annotations

from datetime import timedelta

from ramcove_protocol.scoring import gain_against_later_champion
from ramcove_protocol.settlement import AdmissionKey, QueueEntry, decide_promotion
from ramcove_protocol.state import AWAITING_PROMOTION, S
from ramcove_protocol.weights import KingState, UidSnapshot, build_weight_plan
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
    _lose,
    current_champion,
    king_queue,
    promoted_gains_since,
    requeue_evaluation,
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
        )
        for r in rows
    ]


def settle(conn: Connection, ctx: AppContext, profile_id: str) -> list[dict]:
    advisory_lock(conn, f"settlement:{profile_id}")
    profile = ctx.profile(conn, profile_id)
    actions: list[dict] = []
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
        if d.action == "recompare":
            recompare(conn, ctx, profile, sub, champ.version, "the champion changed before promotion")
            actions.append({"submission": sub.id, "action": "recompare"})
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
            capacity_milli_rps=int(base * (1 + (sub.bound_gain_ppm or 0) / 1e6)) if base else None,
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
            submissions.c.state.in_([s.value for s in AWAITING_PROMOTION]),
        )
    ).all():
        recompare(conn, ctx, profile, other, new_version, f"champion changed to version {new_version}")
    publish_weight_plan(conn, ctx, sub.profile_id)
    return True


def recompare(conn: Connection, ctx: AppContext, profile, sub, champion_version: int, reason: str) -> None:
    """Set a measured winner against a champion crowned after its measurement, without measuring again.
    Evidence taken under different published rules is not carried over: that evaluation runs again."""
    gains = (
        promoted_gains_since(conn, sub.profile_id, sub.compared_champion_version, champion_version)
        if sub.compared_champion_version is not None and sub.compared_rule_hash == profile.rule_hash()
        else None
    )
    if gains is None:
        requeue_evaluation(conn, ctx, sub, reason)
        return
    gain = gain_against_later_champion(sub.bound_gain_ppm or 0, gains)
    if gain > profile.replacement.delta_ppm:
        conn.execute(
            update(submissions)
            .where(submissions.c.id == sub.id)
            .values(
                bound_gain_ppm=gain,
                compared_champion_version=champion_version,
                compared_rule_hash=profile.rule_hash(),
            )
        )
        audit.append(
            conn,
            "controller",
            "recompared",
            "submission",
            sub.id,
            {
                "reason": reason,
                "new_champion_version": champion_version,
                "gain_ppm": gain,
                "still_clears": True,
            },
            public=True,
        )
        return
    _lose(
        conn,
        ctx,
        sub,
        "recompare_lose",
        "champion_changed",
        f"A new champion (version {champion_version}) was crowned first. Over it the gain is {gain / 1e4:.1f}%, "
        f"which does not exceed the {profile.replacement.delta_ppm / 1e4:.0f}% margin. Nothing was measured again.",
        bound_gain_ppm=gain,
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
    excluded = set((ctx.setting(conn, "excluded_hotkeys", {}) or {}).get("hotkeys") or {})
    kings = [
        KingState(
            profile_id,
            slot,
            k.version,
            k.author_hotkey,
            eligible=k.status in ("current", "superseded") and k.author_hotkey not in excluded,
        )
        for slot, k in enumerate(king_queue(conn, profile_id), start=1)
    ]
    plan = build_weight_plan(
        kings,
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
        "kings": [k.__dict__ for k in plan.kings],
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
        {
            "champion_version": champ.version,
            "kings_paid": sum(1 for k in plan.kings if k.paid),
            "no_winner": plan.no_winner,
        },
        public=True,
    )
    return body


def suspend_and_rollback(
    conn: Connection, ctx: AppContext, profile_id: str, operator: str, reason: str, deliberate: bool
) -> dict:
    """Emergency path: the previous safe stack becomes current again as a NEW version number, so every pending
    winner is evaluated again against it and the audit trail keeps the suspended version intact."""
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
            submissions.c.state.in_([s.value for s in AWAITING_PROMOTION]),
        )
    ).all():
        requeue_evaluation(conn, ctx, other, f"rollback to a safe stack (version {new_version})")
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
