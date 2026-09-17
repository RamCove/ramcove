"""Read projections. Public views never expose private source, unrevealed tests or internal errors."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from typing import Any

from room_protocol.money import format_tao
from room_protocol.reservation import can_issue_quote
from room_protocol.state import PAID_ACTIVE, TERMINAL, S
from sqlalchemy import func, or_, select

from ..store.db import now, tx
from ..store.schema import (
    appeals,
    artifacts,
    chain_observations,
    champions,
    comparisons,
    credits,
    incidents,
    jobs,
    quotes,
    receipts,
    refunds,
    reports,
    reviews,
    submissions,
    validators,
    weight_plans,
    workers,
)
from .context import AppContext
from .queue import current_champion

STAGE_LABEL = {
    "preflight_passed": "Checked, not yet reserved",
    "waitlisted": "On the free waiting list",
    "invited": "Invited to reserve capacity",
    "quoted": "Quote issued, awaiting payment",
    "admitted": "Paid, waiting for screening",
    "screening": "Screening (build and smoke checks)",
    "eval_queued": "Waiting for full evaluation",
    "evaluating": "Full evaluation running",
    "confirm_queued": "Waiting for confirmation blocks",
    "confirming": "Confirmation blocks running",
    "in_review": "Human review",
    "ready_for_promotion": "Approved, waiting in admission order",
    "promoted": "Champion",
    "not_promoted": "Did not replace the champion",
    "rejected_preflight": "Rejected by free checks",
    "rejected_screen": "Rejected in screening",
    "review_rejected": "Rejected in review",
    "expired_quote": "Quote expired",
    "expired_unregistered": "Expired: hotkey not registered in time",
    "operator_failed": "Stopped by an operator-side failure",
    "withdrawn": "Withdrawn by the miner",
}


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, default=str).encode()).decode()


def decode_cursor(cursor: str | None) -> list[Any] | None:
    if not cursor:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        return None


def mask_hotkey(hk: str | None) -> str | None:
    return None if not hk else f"{hk[:6]}…{hk[-4:]}"


def meta(ctx: AppContext) -> dict:
    return {
        "product": "ROOM",
        "tagline": "More AI. Same GPU.",
        "env": ctx.settings.env,
        "network": ctx.settings.network,
        "simulated_chain": ctx.settings.simulated_chain,
        "chain_writes_enabled": ctx.settings.chain_writes_enabled,
        "demo_features": ctx.settings.demo_features,
        "notice": (
            "Local development build. The chain, beacon, workers and payments are simulated and "
            "labelled; no real tokens move and no real GPU is measured."
        ),
    }


def overview(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        ready = ctx.ready_workers(conn, profile.profile_id)
        plan = ctx.capacity_plan(conn, profile, trusted_fixture=True)
        paused = bool(ctx.setting(conn, "intake_paused", {"paused": False}).get("paused"))
        committed = ctx.committed_centi(conn, profile.profile_id)
        check = can_issue_quote(committed, profile.envelope, plan, paused)
        counts = dict(
            conn.execute(select(submissions.c.state, func.count()).group_by(submissions.c.state)).all()
        )
        obs = conn.execute(select(chain_observations)).first()
        history = [
            {
                "version": c.version,
                "author": mask_hotkey(c.author_hotkey),
                "status": c.status,
                "capacity_milli_rps": c.capacity_milli_rps,
                "capacity_measured": c.capacity_measured,
                "bound_gain_ppm": c.bound_gain_ppm,
                "promoted_at": c.promoted_at,
                "simulated": True,
            }
            for c in conn.execute(
                select(champions)
                .where(champions.c.profile_id == profile.profile_id)
                .order_by(champions.c.version)
            ).all()
        ]
        price = ctx.latest_price(conn)
        inc = [
            dict(
                id=i.id,
                severity=i.severity,
                title=i.title,
                summary=i.public_summary,
                started_at=i.started_at,
                resolved_at=i.resolved_at,
            )
            for i in conn.execute(select(incidents).where(incidents.c.resolved_at.is_(None))).all()
        ]
        return {
            "profile": {
                "id": profile.profile_id,
                "version": profile.version,
                "title": profile.title,
                "rule_hash": profile.rule_hash(),
                "measured": profile.measured,
                "bootstrap_mode": profile.bootstrap.mode,
            },
            "champion": {
                "version": champ.version,
                "author": mask_hotkey(champ.author_hotkey),
                "is_baseline": champ.submission_id is None,
                "status": champ.status,
                "capacity_milli_rps": champ.capacity_milli_rps,
                "capacity_measured": champ.capacity_measured,
                "bound_gain_ppm": champ.bound_gain_ppm,
                "explain": (
                    "No miner holds the crown yet: version 0 is the tuned baseline and earns "
                    "nothing. The miner allocation is proposed for the owner UID (burn)."
                    if champ.submission_id is None
                    else "The champion's author receives this profile's whole miner allocation while "
                    "it stays eligible."
                ),
            },
            "champion_history": history,
            "queue": {
                "counts_by_state": counts,
                "admitted_active": sum(counts.get(s.value, 0) for s in PAID_ACTIVE),
                "waiting_list": counts.get("waitlisted", 0) + counts.get("invited", 0),
            },
            "capacity": {
                "workers_ready": len(ready),
                "workers_total": len(ctx.ready_workers(conn, profile.profile_id, None)),
                "committed_centi_gpu_hours": committed,
                "capacity_centi_gpu_hours": check.capacity_centi,
                "envelope_per_admission_centi": profile.envelope.total(),
                "intake_paused": paused,
                "accepting_paid_submissions": check.allowed,
                "reason": check.reason,
                "horizon_hours": plan.horizon_hours,
            },
            "fee": (
                {"amount_rao_estimate": None}
                if not price
                else {
                    "price_usd_micros": price.usd_micros_per_tao,
                    "price_simulated": price.simulated,
                    "price_observed_at": price.observed_at,
                    "service_cost_usd_cents": profile.fees.service_cost_usd_cents_per_admission,
                    "recovery_bp": profile.fees.recovery_bp,
                }
            ),
            "chain": None
            if not obs
            else {
                "network": obs.network,
                "finalized_number": obs.finalized_number,
                "finalized_hash": obs.finalized_hash,
                "genesis_hash": obs.genesis_hash,
                "simulated": obs.simulated,
                "observed_at": obs.observed_at,
            },
            "incidents": inc,
            "meta": meta(ctx),
        }


def profile_detail(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        latest_plan = conn.execute(select(weight_plans).order_by(weight_plans.c.created_at.desc())).first()
        return {
            "profile": profile.model_dump(mode="json", by_alias=True),
            "rule_hash": profile.rule_hash(),
            "champion": {
                "version": champ.version,
                "author": mask_hotkey(champ.author_hotkey),
                "artifact_sha256": champ.artifact_sha256,
                "attribution": champ.attribution,
                "status": champ.status,
                "capacity_milli_rps": champ.capacity_milli_rps,
                "capacity_measured": champ.capacity_measured,
                "promoted_at": champ.promoted_at,
                "bound_gain_ppm": champ.bound_gain_ppm,
            },
            "weight_plan": None if latest_plan is None else latest_plan.body,
            "values_are": "provisional planning values from the ROOM v0.2 whitepaper; none is measured on H100",
        }


def queue_page(ctx: AppContext, kind: str = "admitted", cursor: str | None = None, limit: int = 25) -> dict:
    with tx(ctx.engine) as conn:
        states = (
            [s.value for s in PAID_ACTIVE]
            if kind == "admitted"
            else ["waitlisted", "invited"]
            if kind == "waiting"
            else [s.value for s in TERMINAL]
        )
        q = select(submissions).where(submissions.c.state.in_(states))
        c = decode_cursor(cursor)
        if kind == "admitted":
            q = q.order_by(submissions.c.admission_block, submissions.c.admission_index)
            if c:
                q = q.where(
                    or_(
                        submissions.c.admission_block > c[0],
                        (submissions.c.admission_block == c[0]) & (submissions.c.admission_index > c[1]),
                    )
                )
        else:
            q = q.order_by(submissions.c.updated_at.desc(), submissions.c.id)
            if c:
                q = q.where(submissions.c.updated_at < c[0])
        rows = conn.execute(q.limit(limit + 1)).all()
        more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for r in rows:
            job = conn.execute(
                select(jobs.c.stage, jobs.c.status, jobs.c.lease_worker)
                .where(jobs.c.submission_id == r.id, jobs.c.status.in_(["queued", "leased"]))
                .order_by(jobs.c.created_at.desc())
                .limit(1)
            ).first()
            items.append(
                {
                    "submission_id": r.id,
                    "hotkey": mask_hotkey(r.hotkey),
                    "lineage": r.lineage,
                    "state": r.state,
                    "state_label": STAGE_LABEL.get(r.state, r.state),
                    "admission_key": [r.admission_block, r.admission_index] if r.admission_block else None,
                    "admitted_at": r.admitted_at,
                    "updated_at": r.updated_at,
                    "current_stage": None
                    if not job
                    else {"stage": job.stage, "status": job.status, "worker": job.lease_worker},
                    "triage_gain_ppm": r.triage_gain_ppm,
                    "bound_gain_ppm": r.bound_gain_ppm,
                    "rebases_used": r.rebases_used,
                    "outcome": None
                    if r.state not in {s.value for s in TERMINAL}
                    else {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
                }
            )
        nxt = None
        if more and rows:
            last = rows[-1]
            nxt = encode_cursor(
                [last.admission_block, last.admission_index] if kind == "admitted" else [last.updated_at]
            )
        return {
            "kind": kind,
            "items": items,
            "next_cursor": nxt,
            "note": (
                "Paid admissions are ordered by their finalized payment. Workers may run different "
                "submissions at the same time; promotion still follows admission order, so a single "
                "rank across stages would be misleading."
            ),
        }


def submission_view(ctx: AppContext, sub_id: str, viewer: str | None, roles: set[str]) -> dict:
    with tx(ctx.engine) as conn:
        r = conn.execute(select(submissions).where(submissions.c.id == sub_id)).first()
        if r is None:
            return {}
        owner = viewer == r.hotkey
        privileged = owner or bool({"operator", "reviewer"} & roles)
        art = conn.execute(select(artifacts).where(artifacts.c.sha256 == r.artifact_sha256)).first()
        js = conn.execute(
            select(jobs).where(jobs.c.submission_id == sub_id).order_by(jobs.c.created_at)
        ).all()
        cmps = conn.execute(
            select(comparisons)
            .where(comparisons.c.submission_id == sub_id)
            .order_by(comparisons.c.created_at)
        ).all()
        revs = conn.execute(select(reviews).where(reviews.c.submission_id == sub_id)).all()
        aps = conn.execute(select(appeals).where(appeals.c.submission_id == sub_id)).all()
        q = conn.execute(
            select(quotes).where(quotes.c.submission_id == sub_id).order_by(quotes.c.issued_at.desc())
        ).first()
        rc = conn.execute(select(receipts).where(receipts.c.submission_id == sub_id)).first()
        reps = conn.execute(select(reports).where(reports.c.submission_id == sub_id)).all()
        profile = ctx.profile_by_hash(conn, r.rule_hash)
        champ = current_champion(conn, r.profile_id)
        blocking = []
        if r.state == S.READY_FOR_PROMOTION:
            blocking = [
                x.id
                for x in conn.execute(
                    select(submissions.c.id).where(
                        submissions.c.profile_id == r.profile_id,
                        submissions.c.id != r.id,
                        submissions.c.state.in_([s.value for s in PAID_ACTIVE]),
                        or_(
                            submissions.c.admission_block < r.admission_block,
                            (submissions.c.admission_block == r.admission_block)
                            & (submissions.c.admission_index < r.admission_index),
                        ),
                    )
                ).all()
            ]
        out = {
            "submission_id": r.id,
            "state": r.state,
            "state_label": STAGE_LABEL.get(r.state, r.state),
            "hotkey": r.hotkey if privileged else mask_hotkey(r.hotkey),
            "lineage": r.lineage,
            "profile_id": r.profile_id,
            "profile_version": r.profile_version,
            "rule_hash": r.rule_hash,
            "support_ref": r.support_ref,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "admission_key": [r.admission_block, r.admission_index] if r.admission_block else None,
            "admitted_at": r.admitted_at,
            "deadline_at": r.deadline_at,
            "rebases_used": r.rebases_used,
            "max_rebases": profile.deadlines.max_rebases,
            "compared_champion_version": r.compared_champion_version,
            "current_champion_version": champ.version,
            "triage_gain_ppm": r.triage_gain_ppm,
            "bound_gain_ppm": r.bound_gain_ppm,
            "margin_ppm": profile.replacement.delta_ppm,
            "blocks_required": profile.replacement.blocks,
            "outcome": {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
            "method": art.manifest.get("method") if art else None,
            "mechanism": art.manifest.get("mechanism") if art else None,
            "trusted_fixture": art.trusted_fixture if art else None,
            "changed_paths": art.changed_paths if (privileged and art) else None,
            "artifact_sha256": r.artifact_sha256 if privileged else None,
            "blocking_submissions": blocking,
            "timeline": [
                {
                    "stage": j.stage,
                    "status": j.status,
                    "block_no": j.block_no,
                    "worker": j.lease_worker,
                    "champion_version": j.champion_version,
                    "attempts": j.attempts,
                    "created_at": j.created_at,
                    "updated_at": j.updated_at,
                    "lease_expires_at": j.lease_expires_at,
                    "gpu_centi_used": j.gpu_centi_used,
                }
                for j in js
            ],
            "comparisons": [
                {
                    "id": c.id,
                    "champion_version": c.champion_version,
                    "status": c.status,
                    "validator": mask_hotkey(c.validator),
                    "worker": c.worker,
                    "anchor_block": c.anchor_block,
                    "beacon_round": c.beacon_round,
                    "beacon_simulated": c.beacon_simulated,
                    "void_reason": c.void_reason,
                    "challenger_milli_rps": c.challenger_milli_rps,
                    "champion_milli_rps": c.champion_milli_rps,
                }
                for c in cmps
            ],
            "reviews": [
                {
                    "id": v.id,
                    "reviewer": mask_hotkey(v.reviewer),
                    "decision": v.decision,
                    "criteria": v.criteria,
                    "reasons": v.reasons,
                    "due_at": v.due_at,
                    "decided_at": v.decided_at,
                }
                for v in revs
            ],
            "appeals": [
                {
                    "id": a.id,
                    "status": a.status,
                    "kind": a.kind,
                    "grounds": a.grounds,
                    "decided_by": mask_hotkey(a.decided_by),
                    "decision_reason": a.decision_reason,
                    "due_at": a.due_at,
                }
                for a in aps
            ],
            "reports": [
                {
                    "id": p.id,
                    "kind": p.kind,
                    "hash": p.hash,
                    "simulated": p.simulated,
                    "body": p.public_body if (privileged or p.kind != "screen") else None,
                    "created_at": p.created_at,
                }
                for p in reps
            ],
            "simulated": True,
        }
        if privileged and q:
            out["quote"] = {
                "id": q.id,
                "amount_rao": q.amount_rao,
                "amount_tao": format_tao(q.amount_rao),
                "status": q.status,
                "expires_block": q.expires_block,
                "payer": q.payer,
                "recipient": q.recipient,
                "body": q.body,
                "signature": q.signature,
                "price_simulated": q.price_simulated,
                "service_cost_usd_cents": q.service_cost_usd_cents,
                "fee_usd_cents": q.fee_usd_cents,
            }
        if privileged and rc:
            out["receipt"] = {"id": rc.id, "body": rc.body, "signature": rc.signature, "signer": rc.signer}
        if privileged:
            out["credits"] = [
                {
                    "id": c.id,
                    "amount_rao": c.amount_rao,
                    "reason": c.reason,
                    "expires_at": c.expires_at,
                    "consumed_by": c.consumed_by,
                }
                for c in conn.execute(select(credits).where(credits.c.source_submission == sub_id)).all()
            ]
            out["refunds"] = [
                {"id": f.id, "amount_rao": f.amount_rao, "status": f.status, "reason": f.reason}
                for f in conn.execute(select(refunds).where(refunds.c.submission_id == sub_id)).all()
            ]
        return out


def my_submissions(ctx: AppContext, hotkey: str) -> dict:
    with tx(ctx.engine) as conn:
        rows = conn.execute(
            select(submissions)
            .where(submissions.c.hotkey == hotkey)
            .order_by(submissions.c.created_at.desc())
            .limit(100)
        ).all()
        cr = conn.execute(
            select(credits).where(credits.c.hotkey == hotkey, credits.c.consumed_by.is_(None))
        ).all()
        return {
            "items": [
                {
                    "submission_id": r.id,
                    "state": r.state,
                    "state_label": STAGE_LABEL.get(r.state, r.state),
                    "lineage": r.lineage,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                    "admission_key": [r.admission_block, r.admission_index] if r.admission_block else None,
                    "outcome": {"code": r.outcome_code, "summary": r.outcome_summary, "fee": r.fee_outcome},
                    "support_ref": r.support_ref,
                    "triage_gain_ppm": r.triage_gain_ppm,
                    "bound_gain_ppm": r.bound_gain_ppm,
                }
                for r in rows
            ],
            "credits": [
                {
                    "id": c.id,
                    "amount_rao": c.amount_rao,
                    "amount_tao": format_tao(c.amount_rao),
                    "reason": c.reason,
                    "expires_at": c.expires_at,
                }
                for c in cr
            ],
        }


def validator_workspace(ctx: AppContext, hotkey: str) -> dict:
    with tx(ctx.engine) as conn:
        v = conn.execute(select(validators).where(validators.c.hotkey == hotkey)).first()
        if v is None:
            return {"validator": None}
        ws = conn.execute(select(workers).where(workers.c.validator == hotkey)).all()
        obs = conn.execute(select(chain_observations)).first()
        profile = ctx.profile(conn)
        champ = current_champion(conn, profile.profile_id)
        pend = conn.execute(
            select(jobs)
            .where(jobs.c.status.in_(["queued", "leased"]))
            .order_by(jobs.c.priority_block, jobs.c.priority_index)
            .limit(50)
        ).all()
        cmps = conn.execute(
            select(comparisons)
            .where(comparisons.c.validator == hotkey)
            .order_by(comparisons.c.created_at.desc())
            .limit(20)
        ).all()
        return {
            "validator": {
                "hotkey": hotkey,
                "name": v.name,
                "scoring": v.scoring,
                "operator_affiliated": v.operator_affiliated,
                "independence_group": v.independence_group,
                "stake_share_bp": v.stake_share_bp,
            },
            "workers": [
                {
                    "id": w.id,
                    "provider": w.provider,
                    "online": bool(w.last_heartbeat and now() - w.last_heartbeat < timedelta(seconds=120)),
                    "safe_and_ready": w.ready,
                    "readiness": w.readiness,
                    "calibrated_champion_version": w.calibrated_champion_version,
                    "calibrated_at": w.calibrated_at,
                    "enabled": w.enabled,
                    "calibration_current": w.calibrated_champion_version == champ.version,
                }
                for w in ws
            ],
            "queue": [
                {
                    "job_id": j.id,
                    "stage": j.stage,
                    "status": j.status,
                    "submission_id": j.submission_id,
                    "priority": [j.priority_block, j.priority_index],
                    "lease_worker": j.lease_worker,
                    "lease_expires_at": j.lease_expires_at,
                }
                for j in pend
            ],
            "comparisons": [
                {
                    "id": c.id,
                    "submission_id": c.submission_id,
                    "status": c.status,
                    "champion_version": c.champion_version,
                    "beacon_round": c.beacon_round,
                    "worker": c.worker,
                    "challenger_milli_rps": c.challenger_milli_rps,
                    "champion_milli_rps": c.champion_milli_rps,
                }
                for c in cmps
            ],
            "chain": None
            if not obs
            else {
                "finalized_number": obs.finalized_number,
                "simulated": obs.simulated,
                "observed_at": obs.observed_at,
                "genesis_hash": obs.genesis_hash,
            },
            "reimbursement_note": (
                "Confirmation work is reimbursed per block at the published rate; this build "
                "records the policy but moves no funds."
            ),
        }


def status_page(ctx: AppContext) -> dict:
    with tx(ctx.engine) as conn:
        profile = ctx.profile(conn)
        ws = conn.execute(select(workers)).all()
        obs = conn.execute(select(chain_observations)).first()
        inc = conn.execute(select(incidents).order_by(incidents.c.started_at.desc()).limit(20)).all()
        stuck = conn.execute(
            select(func.count())
            .select_from(jobs)
            .where(jobs.c.status == "leased", jobs.c.lease_expires_at < now())
        ).scalar()
        return {
            "profile": profile.profile_id,
            "workers": [
                {
                    "id": w.id,
                    "online": bool(w.last_heartbeat and now() - w.last_heartbeat < timedelta(seconds=120)),
                    "safe_and_ready": w.ready,
                    "provider": w.provider,
                    "untrusted_code_isolation": bool(w.readiness.get("untrusted_code_isolation")),
                }
                for w in ws
            ],
            "expired_leases_waiting_for_sweep": stuck,
            "chain": None
            if not obs
            else {
                "finalized_number": obs.finalized_number,
                "simulated": obs.simulated,
                "observed_at": obs.observed_at,
            },
            "incidents": [
                {
                    "id": i.id,
                    "severity": i.severity,
                    "title": i.title,
                    "summary": i.public_summary,
                    "started_at": i.started_at,
                    "resolved_at": i.resolved_at,
                }
                for i in inc
            ],
            "meta": meta(ctx),
        }


def audit_page(ctx: AppContext, public_only: bool, cursor: str | None, limit: int = 50) -> dict:
    from ..store.schema import audit_events

    with tx(ctx.engine) as conn:
        q = select(audit_events).order_by(audit_events.c.id.desc()).limit(limit + 1)
        if public_only:
            q = q.where(audit_events.c.public)
        c = decode_cursor(cursor)
        if c:
            q = q.where(audit_events.c.id < c[0])
        rows = conn.execute(q).all()
        more = len(rows) > limit
        rows = rows[:limit]
        return {
            "items": [
                {
                    "id": r.id,
                    "at": r.at,
                    "actor": r.actor if not public_only else mask_hotkey(r.actor),
                    "action": r.action,
                    "subject_type": r.subject_type,
                    "subject_id": r.subject_id,
                    "data": r.data,
                    "hash": r.hash,
                }
                for r in rows
            ],
            "next_cursor": encode_cursor([rows[-1].id]) if more and rows else None,
        }


def verify_audit(ctx: AppContext) -> dict:
    from ..store import audit as audit_mod

    with tx(ctx.engine) as conn:
        ok, n, bad = audit_mod.verify_chain(conn)
        return {"ok": ok, "events_checked": n, "first_bad_event_id": bad}
